"""课件解析:第一层直接抽文字(免费、快);抽不出字的页当扫描件,第二层交视觉模型。

缓存规矩(data/cache/<id>/):
- pages/001.md 逐页落盘,写完一页是一页 —— 断了、断电了,已好的页都留着;
- meta.json **最后**写 —— 它在,才代表这份课件完整解析跑完过;
- 重跑时缺哪页补哪页(断点续传),缓存里有的页一个模型请求都不发。
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

import pymupdf

from app.config import Config
from app.courseware import CoursewareError, cache_dir, course_file, page_md
from app.llm.provider import LLMError, chat_completion_full
from app.usage import record_usage

log = logging.getLogger(__name__)

SCANNED_TEXT_THRESHOLD = 20  # 一页抽出来不到这么多字符,当它是扫描/图片页
PARSE_VERSION = 1            # 缓存格式版本;将来解析方式大改时 +1,老 meta 自动作废

Progress = Callable[[int, int], None]  # (刚处理完第几页, 共几页)


def is_scanned_text(text: str) -> bool:
    return len(text.strip()) < SCANNED_TEXT_THRESHOLD


def _open_doc(data_dir: Path, course_id: str) -> pymupdf.Document:
    src = course_file(data_dir, course_id)  # 顺带校验 id
    if not src.exists():
        raise CoursewareError("这份课件不在了——刷新页面看看。")
    try:
        doc = pymupdf.open(src)
    except Exception as e:  # FileDataError 等:坏文件落这里
        raise CoursewareError("这个 PDF 打不开(可能坏了或者加了密码)——换一份试试。", repr(e))
    if doc.needs_pass:  # 带密码的 PDF 打开时不报错、翻页才炸——在这里提前挡成同一句人话
        doc.close()
        raise CoursewareError("这个 PDF 打不开(可能坏了或者加了密码)——换一份试试。")
    return doc


def meta_file(data_dir: Path, course_id: str) -> Path:
    return cache_dir(data_dir, course_id) / "meta.json"


def read_meta(data_dir: Path, course_id: str) -> dict | None:
    """解析完成标记。没跑完 = 没有;坏文件、老版本当没有(页文件还在,照样能续)。"""
    p = meta_file(data_dir, course_id)
    if not p.exists():
        return None
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            return None
        # version 被人手改坏(不是数字)也算「读不动」:别让 int() 逃出去把接口带崩
        version = int(meta.get("version") or 0)
    except (OSError, ValueError, TypeError):
        return None
    if version != PARSE_VERSION:
        return None
    return meta


def _write_page_md(cache: Path, n: int, text: str) -> None:
    """写一页 Markdown。先落临时文件再改名——续传把「文件在」当「这页已解析好」,
    直接写一半就断电的话,残页会被当成解析结果,重跑也不会补(同 meta.json 的写法)。
    """
    target = page_md(cache, n)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)


def parse_text_layer(data_dir: Path, course_id: str, progress: Progress | None = None) -> dict:
    """第一层:能直接抽到字的页抽成 Markdown 落盘。

    返回 {"total", "scanned_pages", "pending_scanned", "done_pages"}。
    只看文件里的文字层,不花钱;扫描页记下来,留给视觉层。
    """
    doc = _open_doc(data_dir, course_id)
    try:
        total = doc.page_count
        if total == 0:
            raise CoursewareError("这个 PDF 一页都没有——像是空文件。")
        cache = cache_dir(data_dir, course_id)
        (cache / "pages").mkdir(parents=True, exist_ok=True)
        scanned: list[int] = []
        pending: list[int] = []
        done = 0
        for i in range(total):
            n = i + 1
            target = page_md(cache, n)
            text = doc[i].get_text().strip()
            if is_scanned_text(text):
                scanned.append(n)
                if target.exists():  # 视觉层之前已经看过了:算已好,不重看、不重复花钱
                    done += 1
                else:
                    pending.append(n)
                continue
            if target.exists():  # 续传:这页之前抽过
                done += 1
                continue
            _write_page_md(cache, n, text)
            done += 1
            if progress:
                progress(n, total)
        return {"total": total, "scanned_pages": scanned, "pending_scanned": pending, "done_pages": done}
    finally:
        doc.close()


def course_status(data_dir: Path, course_id: str) -> dict:
    """给课件列表用:这份解析到哪了。"""
    meta = read_meta(data_dir, course_id)
    if meta is not None:
        return {
            "state": "done",
            "pages": int(meta.get("pages") or 0),
            "scanned_pages": len(meta.get("scanned_pages") or []),
            "parsed_at": str(meta.get("parsed_at") or ""),
        }
    pages = cache_dir(data_dir, course_id) / "pages"
    parsed = len(list(pages.glob("*.md"))) if pages.exists() else 0
    return {"state": "partial" if parsed else "none", "parsed_pages": parsed}


RENDER_DPI = 150        # 扫描页渲染的清晰度:够看清字和公式,又不至于图片太大
VISION_MAX_TOKENS = 4096
VISION_TIMEOUT = 120.0

VISION_PROMPT = (
    "这是一份课件 PDF 的第 {page} 页(共 {total} 页),它没有文字层(扫描或图片形式)。"
    "请把这一页的内容完整转成 Markdown:文字照抄;公式用 $...$;表格尽量还原;"
    "看不清的地方标 [看不清]。不要解释、不要客套,只输出这一页的内容。"
)


def vision_cfg(cfg: Config) -> Config:
    """看扫描页用哪套配置:填了『视觉模型』就用它,留空 = 和主模型相同。"""
    if not cfg.vision_model:
        return cfg
    return replace(cfg, model=cfg.vision_model)


def render_page_png(doc: pymupdf.Document, page_index: int) -> bytes:
    return doc[page_index].get_pixmap(dpi=RENDER_DPI).tobytes("png")


def _look_at_page(data_dir: Path, cfg: Config, png: bytes, page_no: int, total: int) -> str:
    """让模型看一页扫描件。失败重试一次——视觉请求偶尔抽风,再来一遍再下结论。"""
    b64 = base64.b64encode(png).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_PROMPT.format(page=page_no, total=total)},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }
    ]
    last: LLMError | None = None
    for _ in range(2):
        try:
            text, usage = chat_completion_full(
                cfg, messages, max_tokens=VISION_MAX_TOKENS, timeout=VISION_TIMEOUT
            )
            record_usage(data_dir, "看扫描页", cfg.model, usage)
            return text.strip()
        except LLMError as e:
            last = e
    raise last


def parse_course(data_dir: Path, course_id: str, cfg: Config, progress: Progress | None = None) -> dict:
    """完整解析一遍:文本层 + 扫描页视觉层;meta.json 最后写 = 这遍跑完了。

    中途失败:页文件都留着;修好问题再点「解析」,只补没看过的页——不重复花钱。
    """
    summary = parse_text_layer(data_dir, course_id, progress)
    pending = summary["pending_scanned"]
    total = summary["total"]
    if pending:
        vcfg = vision_cfg(cfg)
        if not (vcfg.api_key and vcfg.base_url and vcfg.model):
            raise CoursewareError(
                f"有 {len(pending)} 页是扫描/图片页,需要模型来看——"
                "先去「设置」把 Key、接口地址、模型名填好,再点「解析」。"
            )
        doc = _open_doc(data_dir, course_id)
        try:
            cache = cache_dir(data_dir, course_id)
            for n in pending:
                try:
                    text = _look_at_page(data_dir, vcfg, render_page_png(doc, n - 1), n, total)
                except LLMError as e:
                    raise CoursewareError(
                        f"第 {n} 页(扫描页)没看成:{e.human}——已经解析好的页都留着,弄好后点「解析」接着来。",
                        e.detail,
                    )
                if not text:
                    text = "(这一页模型没说出内容)"  # 空回答不留白页
                _write_page_md(cache, n, text)
                if progress:
                    progress(n, total)
        finally:
            doc.close()
    meta = {
        "version": PARSE_VERSION,
        "pages": total,
        "scanned_pages": summary["scanned_pages"],
        "parsed_at": datetime.now().isoformat(timespec="seconds"),
    }
    cache = cache_dir(data_dir, course_id)
    cache.mkdir(parents=True, exist_ok=True)
    tmp = meta_file(data_dir, course_id).with_name("meta.json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(meta_file(data_dir, course_id))  # 最后一步:完成标记落定
    return meta
