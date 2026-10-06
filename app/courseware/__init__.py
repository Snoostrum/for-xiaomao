"""课件助手:课件库(store)、解析(parse)、问答(qa)。

这里放三块共用的路径规则与错误类型:
- 课件原件:data/courses/<16位内容哈希>.pdf —— 内容相同就是同一份(天然去重)
- 解析缓存:data/cache/<同一个 id>/(pages/ 逐页 Markdown,img/ 留给扫描页渲染图)
"""

from __future__ import annotations

import re
from pathlib import Path

from app.errors import HumanError

_ID_RE = re.compile(r"^[0-9a-f]{16}$")


class CoursewareError(HumanError):
    """课件流程里说给用户听的人话错误;server 统一翻成 400 + message。"""


def is_course_id(course_id: str) -> bool:
    """像不像小灶自己发的课件 id。列表接口用它过滤目录里人手放进去的杂物。"""
    return bool(_ID_RE.match(course_id or ""))


def check_course_id(course_id: str) -> str:
    """课件 id 只认 16 位小写十六进制——顺带挡住 ../ 这类路径穿越。"""
    if not is_course_id(course_id):
        raise CoursewareError("课件编号不对——刷新页面再试。")
    return course_id


def courses_dir(data_dir: Path) -> Path:
    return data_dir / "courses"


def course_file(data_dir: Path, course_id: str) -> Path:
    return courses_dir(data_dir) / f"{check_course_id(course_id)}.pdf"


def course_meta_file(data_dir: Path, course_id: str) -> Path:
    return courses_dir(data_dir) / f"{check_course_id(course_id)}.json"


def cache_dir(data_dir: Path, course_id: str) -> Path:
    return data_dir / "cache" / check_course_id(course_id)


def page_md(cache: Path, n: int) -> Path:
    """第 n 页的 Markdown 文件。页号补零只为了在文件夹里排序好看。"""
    return cache / "pages" / f"{n:03d}.md"
