"""课件问答:整份课件(逐页 Markdown)塞进一次长上下文,要求答案标页码。

M2 不做多轮、不做检索——150 页以内的课件整份进去就够(设计文档 §2);
更长的会被人话劝回去拆章节,宁可说清楚,也不把账单烧成无底洞。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import Config
from app.courseware import CoursewareError, cache_dir
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
    """把所有已解析的页拼成带页码标记的全文。"""
    pages_dir = cache_dir(data_dir, course_id) / "pages"
    parts = []
    for p in sorted(pages_dir.glob("*.md"), key=lambda x: int(x.stem)):
        n = int(p.stem)
        parts.append(f"=== 第 {n} 页 ===\n{p.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(parts)


def ask_course(data_dir: Path, course_id: str, question: str, cfg: Config) -> str:
    """对一份课件提问,返回带页码的答案;出错抛 CoursewareError(人话)。"""
    question = question.strip()
    if not question:
        raise CoursewareError("问题还没写呢。")
    if read_meta(data_dir, course_id) is None:
        raise CoursewareError("这份课件还没解析完——先点「解析」,解析完再问。")
    corpus = build_corpus(data_dir, course_id)
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
