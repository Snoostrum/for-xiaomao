"""课件库:上传的原件按内容哈希存成 data/courses/<id>.pdf,显示名放旁边的 .json。

为什么要哈希命名:同一份课件改个文件名再传,内容哈希不变 → 认成同一份,
不重复存、不重复解析、不重复花钱;显示名不受文件系统限制,中文随便叫。
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from app.courseware import CoursewareError, course_file, course_meta_file, courses_dir

log = logging.getLogger(__name__)

_CHUNK = 1024 * 1024  # 1MB 一块:几百 MB 的课件也不整份塞进内存


def save_upload(data_dir: Path, stream, filename: str) -> tuple[str, bool]:
    """把上传的文件流存进课件库,返回 (课件id, 是否新入库)。

    边写边算内容哈希;先落成临时文件,验过 %PDF 魔数才正式入位——半截文件不入库。
    """
    courses = courses_dir(data_dir)
    courses.mkdir(parents=True, exist_ok=True)
    tmp = courses / f".upload-{secrets.token_hex(6)}.part"
    h = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as out:
            while True:
                chunk = stream.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
                out.write(chunk)
        with tmp.open("rb") as f:
            if not f.read(5).startswith(b"%PDF"):
                raise CoursewareError("这个文件看起来不是 PDF——小灶只认 PDF 课件。")
        course_id = h.hexdigest()[:16]
        target = course_file(data_dir, course_id)
        if target.exists():  # 内容一样(文件名不同也算):直接用已有的
            return course_id, False
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)  # 入位后这里已不存在;失败路径把半截文件清掉
    course_meta_file(data_dir, course_id).write_text(
        json.dumps(
            {
                "name": filename or f"{course_id}.pdf",
                "added_at": datetime.now().isoformat(timespec="seconds"),
                "size": size,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return course_id, True


def list_courses(data_dir: Path) -> list[dict]:
    """课件列表,新放的前面。坏掉的说明文件跳过——一条脏数据不该打不开整个列表。"""
    courses = courses_dir(data_dir)
    out: list[dict] = []
    if not courses.exists():
        return out
    for mfile in courses.glob("*.json"):
        try:
            meta = json.loads(mfile.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                continue
            course_id = mfile.stem
            if not (courses / f"{course_id}.pdf").exists():
                continue  # 只有说明没有原件:当它不存在
            out.append(
                {
                    "id": course_id,
                    "name": str(meta.get("name") or f"{course_id}.pdf"),
                    "added_at": str(meta.get("added_at") or ""),
                    "size": int(meta.get("size") or 0),
                }
            )
        except (OSError, ValueError):
            log.warning("课件说明文件坏了,跳过:%s", mfile.name)
    out.sort(key=lambda c: c["added_at"], reverse=True)
    return out


def delete_course(data_dir: Path, course_id: str) -> None:
    """删课件:原件、说明、解析缓存一起清干净。"""
    pdf = course_file(data_dir, course_id)  # 顺带校验 id
    if not pdf.exists():
        raise CoursewareError("这份课件不在了——刷新页面看看。")
    pdf.unlink()
    course_meta_file(data_dir, course_id).unlink(missing_ok=True)
    shutil.rmtree(data_dir / "cache" / course_id, ignore_errors=True)
