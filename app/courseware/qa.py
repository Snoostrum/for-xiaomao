"""课件问答:整份课件(逐页 Markdown)塞进一次长上下文,要求答案标页码。

M2 不做多轮、不做检索——150 页以内的课件整份进去就够(设计文档 §2);
更长的会被人话劝回去拆章节,宁可说清楚,也不把账单烧成无底洞。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import Config
from app.courseware import CoursewareError, cache_dir, page_md
from app.courseware.parse import read_meta
from app.llm.provider import LLMError, chat_completion_full
from app.usage import record_usage

log = logging.getLogger(__name__)

MAX_CORPUS_CHARS = 200_000  # 全文超这个量级就劝拆分
ASK_MAX_TOKENS = 2048
ASK_TIMEOUT = 180.0  # 长课件回答慢,给足时间

ASK_PROMPT = """你在帮学生看课件。下面是课件的全文,按页分隔(格式:=== 第 N 页 ===)。
要求:
1. 只根据课件内容回答;引用到课件的地方,标出来源页码,格式「第 N 页」;
2. 课件里没有的内容,直说「课件里没有提到」,不要编;
3. 用学生看得懂的话,中文回答,别啰嗦。

课件全文:
{corpus}

学生的问题:{question}"""


def build_corpus(data_dir: Path, course_id: str) -> str:
    """把所有已解析的页拼成带页码标记的全文;没解析完或缺页时抛 CoursewareError(人话)。

    按 meta 记的页数逐页读,而不是扫 pages/ 目录:少一页(缓存被删了一半、解析没跑完)
    就得当场拦下来——残卷当「课件全文」交给模型,答案和账单都是错的。
    逐页读也顺手绕开了 glob 排序 + int(文件名):pages/ 里混进别的 .md 也不会炸。
    """
    meta = read_meta(data_dir, course_id)
    if meta is None:
        raise CoursewareError("这份课件还没解析完——先点「解析」,解析完再问。")
    try:
        pages = int(meta.get("pages") or 0)
    except (ValueError, TypeError):  # 说明文件被手改坏:按「没解析完」报人话,别 500
        pages = 0
    if pages <= 0:
        raise CoursewareError("这份课件还没解析完——先点「解析」,解析完再问。")
    cache = cache_dir(data_dir, course_id)
    missing = [n for n in range(1, pages + 1) if not page_md(cache, n).exists()]
    if missing:
        raise CoursewareError(f"缓存缺了 {len(missing)} 页——先点「解析」补齐再问。")
    parts = [
        f"=== 第 {n} 页 ===\n{page_md(cache, n).read_text(encoding='utf-8').strip()}"
        for n in range(1, pages + 1)
    ]
    return "\n\n".join(parts)


def ask_course(data_dir: Path, course_id: str, question: str, cfg: Config) -> str:
    """对一份课件提问,返回带页码的答案;出错抛 CoursewareError(人话)。"""
    question = question.strip()
    if not question:
        raise CoursewareError("问题还没写呢。")
    corpus = build_corpus(data_dir, course_id)  # 没解析完、缓存缺页都从这里抛人话
    if len(corpus) > MAX_CORPUS_CHARS:
        raise CoursewareError(
            f"这份课件太长了(约 {len(corpus) // 1000} 千字),一次塞不进模型——"
            "建议把它按章节拆成几个 PDF 再放进来。"
        )
    if not (cfg.api_key and cfg.base_url and cfg.model):
        raise CoursewareError("还没把模型配好——去「设置」把 Key、接口地址、模型名填好再问。")
    messages = [{"role": "user", "content": ASK_PROMPT.format(corpus=corpus, question=question)}]
    try:
        text, usage = chat_completion_full(cfg, messages, max_tokens=ASK_MAX_TOKENS, timeout=ASK_TIMEOUT)
    except LLMError as e:
        raise CoursewareError(e.human, e.detail)
    record_usage(data_dir, "提问", cfg.model, usage)
    return text.strip() or "(模型这次没说话——再问一遍试试。)"
