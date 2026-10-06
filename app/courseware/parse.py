"""课件解析:第一层直接抽文字(免费、快);抽不出字的页当扫描件,第二层交视觉模型。

缓存规矩(data/cache/<id>/):
- pages/001.md 逐页落盘,写完一页是一页 —— 断了、断电了,已好的页都留着;
- meta.json **最后**写 —— 它在,才代表这份课件完整解析跑完过;
- 重跑时缺哪页补哪页(断点续传),缓存里有的页一个模型请求都不发。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

import pymupdf

from app.courseware import CoursewareError, cache_dir, course_file, page_md

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
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or int(meta.get("version") or 0) != PARSE_VERSION:
        return None
    return meta


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
            target.write_text(text, encoding="utf-8")
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
