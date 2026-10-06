import io
import json

import pytest

from app.courseware import CoursewareError, course_file, course_meta_file
from app.courseware.store import delete_course, list_courses, save_upload

# 注:brief 里写成 b"%PDF-1.4 中文…" 的字节字面量在 Python 3 是 SyntaxError,
# 内容一字不改,改用 .encode("utf-8") 得到同样的 bytes。
PDF_A = b"%PDF-1.4 " + "这是一份假 PDF,store 只验魔数不解析".encode("utf-8")
PDF_B = b"%PDF-1.4 " + "另一份内容不同的假 PDF".encode("utf-8")


def upload(data_dir, content: bytes, name: str):
    return save_upload(data_dir, io.BytesIO(content), name)


def test_same_content_different_name_is_one_course(tmp_path):
    # Review Focus #1 的第一道闸:内容一样(改了名)→ 同一份,不建第二条
    cid1, new1 = upload(tmp_path, PDF_A, "讲义.pdf")
    cid2, new2 = upload(tmp_path, PDF_A, "讲义-最终版(1).pdf")
    assert new1 is True and new2 is False
    assert cid1 == cid2
    assert len(list_courses(tmp_path)) == 1
    assert not list((tmp_path / "courses").glob("*.part"))  # 临时文件不残留


def test_different_content_is_second_course(tmp_path):
    cid1, _ = upload(tmp_path, PDF_A, "a.pdf")
    cid2, _ = upload(tmp_path, PDF_B, "b.pdf")
    assert cid1 != cid2 and len(list_courses(tmp_path)) == 2


def test_non_pdf_rejected_and_nothing_left(tmp_path):
    with pytest.raises(CoursewareError) as ei:
        upload(tmp_path, "JFIF 这是一张图片".encode("utf-8"), "照片.pdf")
    assert "PDF" in str(ei.value)
    assert list_courses(tmp_path) == []
    assert not list((tmp_path / "courses").glob("*"))  # 坏的也不留垃圾


def test_list_shows_newest_first(tmp_path):
    cid1, _ = upload(tmp_path, PDF_A, "老的.pdf")
    cid2, _ = upload(tmp_path, PDF_B, "新的.pdf")
    meta = json.loads(course_meta_file(tmp_path, cid1).read_text(encoding="utf-8"))
    meta["added_at"] = "2026-01-01T00:00:00"  # 同一秒上传分不出先后,把老的改成"昨天"
    course_meta_file(tmp_path, cid1).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    assert [c["id"] for c in list_courses(tmp_path)] == [cid2, cid1]
    assert list_courses(tmp_path)[1]["name"] == "老的.pdf"


def test_delete_removes_files_and_cache(tmp_path):
    cid, _ = upload(tmp_path, PDF_A, "讲义.pdf")
    cache = tmp_path / "cache" / cid
    cache.mkdir(parents=True)
    (cache / "占位.txt").write_text("x", encoding="utf-8")
    delete_course(tmp_path, cid)
    assert list_courses(tmp_path) == []
    assert not course_file(tmp_path, cid).exists()
    assert not cache.exists()


def test_bad_course_id_is_rejected(tmp_path):
    # 编号来自网址,必须只认 16 位十六进制——../../ 这类穿越直接人话拒绝
    with pytest.raises(CoursewareError):
        course_file(tmp_path, "../../etc/passwd")
    with pytest.raises(CoursewareError):
        delete_course(tmp_path, "Z" * 16)
