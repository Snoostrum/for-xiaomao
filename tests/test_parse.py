import json

import pymupdf
import pytest

from app.config import Config
from app.courseware import CoursewareError, cache_dir, course_file, page_md
from app.courseware.parse import (
    PARSE_VERSION,
    course_status,
    parse_course,
    parse_text_layer,
    read_meta,
    vision_cfg,
)
from app.courseware.store import save_upload
from app.usage import usage_totals
from tests.test_provider import FakeLLM, cfg_for

# 已在这台机器上验过:pymupdf 1.28 里 fontname="china-s" 能写中文并能原样抽回来
EMPTY_PDF_ZERO_PAGES = (
    b"%PDF-1.4\n"
    b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
    b"2 0 obj <</Type /Pages /Kids [] /Count 0>> endobj\n"
    b"trailer <</Root 1 0 R /Size 3>>\n"
    b"%%EOF\n"
)

# brief 夹具里的示例文字是「第一页讲向量」这类短串,但 SCANNED_TEXT_THRESHOLD=20 的判据下
# 它们会被当成扫描页(与用例意图正相反)。阈值属计划「关键常量(照抄,勿自行改值)」,不能动;
# 于是只把「文字页」的示例文字补到 20 字符以上,页面角色与断言一字未改。


def make_pdf(path, texts: list[str]) -> bytes:
    """texts 里空字符串 = 这一页不写文字(拿来模拟扫描页)。"""
    doc = pymupdf.open()
    for t in texts:
        page = doc.new_page()
        if t:
            page.insert_text((72, 72), t, fontname="china-s", fontsize=12)
    data = doc.tobytes()
    doc.close()
    path.write_bytes(data)
    return data


def add_course(data_dir, tmp_path, texts: list[str]) -> str:
    src = tmp_path / "示例课件.pdf"
    make_pdf(src, texts)
    with src.open("rb") as f:
        course_id, _ = save_upload(data_dir, f, "示例课件.pdf")
    return course_id


def test_text_pages_extracted_into_page_files(tmp_path):
    data = tmp_path / "data"
    cid = add_course(
        data,
        tmp_path,
        [
            "第一页讲向量:向量的定义、加法、数乘与点积运算都在这一页。",
            "第二页讲矩阵:矩阵的乘法、转置与逆矩阵的定义都在这一页。",
            "第三页讲特征值:特征值与特征向量的求法和几何意义都在这页。",
        ],
    )
    seen = []
    result = parse_text_layer(data, cid, progress=lambda n, total: seen.append((n, total)))
    assert result["total"] == 3
    assert result["scanned_pages"] == []
    assert result["done_pages"] == 3
    assert seen == [(1, 3), (2, 3), (3, 3)]
    cache = cache_dir(data, cid)
    assert "矩阵" in page_md(cache, 2).read_text(encoding="utf-8")


def test_scanned_page_detected_but_left_for_vision_layer(tmp_path):
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["文字页:这一页的文字层是好的,它不是扫描件。", ""])
    result = parse_text_layer(data, cid)
    assert result["scanned_pages"] == [2]
    assert result["pending_scanned"] == [2]
    assert not page_md(cache_dir(data, cid), 2).exists()  # 第一层不碰扫描页
    assert read_meta(data, cid) is None  # 还没完整解析:没有完成标记


def test_resume_only_reextracts_missing_pages(tmp_path):
    # Review Focus #3:人为删掉一页缓存,再解析 → 只补那一页
    data = tmp_path / "data"
    cid = add_course(
        data,
        tmp_path,
        [
            "第一页的文字内容在这里,足够长,不会被当扫描页。",
            "第二页的文字内容在这里,足够长,不会被当扫描页。",
            "第三页的文字内容在这里,足够长,不会被当扫描页。",
        ],
    )
    parse_text_layer(data, cid)
    page_md(cache_dir(data, cid), 2).unlink()
    seen = []
    result = parse_text_layer(data, cid, progress=lambda n, total: seen.append(n))
    assert seen == [2]           # 只有缺的那页重抽了
    assert result["done_pages"] == 3
    assert page_md(cache_dir(data, cid), 2).exists()


def test_corrupt_pdf_gives_human_error(tmp_path):
    # Review Focus #2:魔数像 PDF、内容是坏的 → 人话,不是英文栈
    data = tmp_path / "data"
    src = tmp_path / "坏.pdf"
    src.write_bytes(b"%PDF-1.4 garbage")
    with src.open("rb") as f:
        cid, _ = save_upload(data, f, "坏.pdf")
    with pytest.raises(CoursewareError) as ei:
        parse_text_layer(data, cid)
    assert "打不开" in str(ei.value)


def test_zero_page_pdf_gives_human_error(tmp_path):
    # Review Focus #2 的另一半:一页都没有的空 PDF(手工构造——pymupdf 自己存不出 0 页文件)
    data = tmp_path / "data"
    src = tmp_path / "空.pdf"
    src.write_bytes(EMPTY_PDF_ZERO_PAGES)
    with src.open("rb") as f:
        cid, _ = save_upload(data, f, "空.pdf")
    with pytest.raises(CoursewareError) as ei:
        parse_text_layer(data, cid)
    assert "一页都没有" in str(ei.value)


def test_course_status_none_then_partial(tmp_path):
    from app.courseware.parse import course_status

    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["有字:这一页有文字层,内容够长,不算扫描页。", ""])
    assert course_status(data, cid)["state"] == "none"
    parse_text_layer(data, cid)
    st = course_status(data, cid)
    assert st["state"] == "partial" and st["parsed_pages"] == 1


# —— 以下是对着 Review Focus 三条与 Interfaces 判据补的验收专项 ——


def test_reupload_same_content_under_new_name_does_not_reparse(tmp_path):
    # Review Focus #1 的解析半边:同一份课件改了名再传 → 同一个 id、缓存照旧,一页都不重抽
    data = tmp_path / "data"
    src = tmp_path / "示例课件.pdf"
    payload = make_pdf(
        src,
        [
            "第一页的文字内容在这里,足够长,不会被当扫描页。",
            "第二页的文字内容在这里,足够长,不会被当扫描页。",
        ],
    )
    with src.open("rb") as f:
        cid, is_new = save_upload(data, f, "示例课件.pdf")
    assert is_new is True
    parse_text_layer(data, cid)
    stamps = {n: page_md(cache_dir(data, cid), n).stat().st_mtime_ns for n in (1, 2)}

    renamed = tmp_path / "换个名字再传一次.pdf"
    renamed.write_bytes(payload)
    with renamed.open("rb") as f:
        cid2, is_new2 = save_upload(data, f, "换个名字再传一次.pdf")
    assert cid2 == cid and is_new2 is False  # 内容相同 = 同一份(接 T6 的 is_new 判据)
    seen = []
    result = parse_text_layer(data, cid2, progress=lambda n, total: seen.append(n))
    assert seen == []  # 一个重抽都没有
    assert result["done_pages"] == 2
    assert {n: page_md(cache_dir(data, cid2), n).stat().st_mtime_ns for n in (1, 2)} == stamps


def test_encrypted_pdf_gives_human_error_and_leaves_everything_alone(tmp_path):
    # Review Focus #2 的加密半边:带密码的 PDF 用 pymupdf 打开不报错、翻页才炸,
    # 漏出去就是英文栈——得自己挡成一句人话;原件留着,别的课件照常解析(不是永久卡死)。
    data = tmp_path / "data"
    src = tmp_path / "加密.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "加密页里的文字内容,足够长的一行字在这里。", fontname="china-s", fontsize=12)
    doc.save(src, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    doc.close()
    with src.open("rb") as f:
        cid, _ = save_upload(data, f, "加密.pdf")
    with pytest.raises(CoursewareError) as ei:
        parse_text_layer(data, cid)
    assert "打不开" in str(ei.value)
    assert course_file(data, cid).exists()  # 课件原件不动
    with pytest.raises(CoursewareError):    # 再点一次还是同一句人话,不是别的错
        parse_text_layer(data, cid)
    other = add_course(data, tmp_path, ["另一份好课件的文字内容在这里,足够长,不会被当扫描页。"])
    assert parse_text_layer(data, other)["done_pages"] == 1  # 一份坏的不影响别的


def test_resume_after_half_the_cache_is_gone(tmp_path):
    # Review Focus #3:解析到一半退出(缓存只剩前半)→ 重开只补缺的页,不从头重抽
    data = tmp_path / "data"
    cid = add_course(
        data, tmp_path, [f"第 {n} 页的文字内容在这里,足够长,不会被当扫描页。" for n in range(1, 5)]
    )
    parse_text_layer(data, cid)
    for n in (2, 4):  # 人为删掉一半
        page_md(cache_dir(data, cid), n).unlink()
    seen = []
    result = parse_text_layer(data, cid, progress=lambda n, total: seen.append(n))
    assert seen == [2, 4]
    assert result["done_pages"] == 4
    assert sorted(p.name for p in (cache_dir(data, cid) / "pages").glob("*.md")) == [
        "001.md",
        "002.md",
        "003.md",
        "004.md",
    ]


def test_read_meta_ignores_missing_broken_and_old_version(tmp_path):
    # Interfaces 判据:meta.json 在 = 完整解析跑完过;没有、坏文件、老版本都当没有
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["这一页的文字内容在这里,足够长,不会被当扫描页。"])
    assert read_meta(data, cid) is None  # 还没有完成标记
    mf = cache_dir(data, cid) / "meta.json"
    mf.parent.mkdir(parents=True, exist_ok=True)  # 缓存目录还没建:这个用例只管 read_meta
    mf.write_text("{ 这不是 JSON", encoding="utf-8")
    assert read_meta(data, cid) is None  # 坏文件:当没有(页文件还在,照样能续)
    mf.write_text(json.dumps({"version": PARSE_VERSION - 1, "pages": 1, "scanned_pages": []}), encoding="utf-8")
    assert read_meta(data, cid) is None  # 老版本:自动作废
    mf.write_text(json.dumps({"version": PARSE_VERSION, "pages": 1, "scanned_pages": []}), encoding="utf-8")
    assert read_meta(data, cid) == {"version": PARSE_VERSION, "pages": 1, "scanned_pages": []}


def test_course_status_done_reads_meta(tmp_path):
    # 完成标记在 = done。meta 由 Task 8 的最后一步落定,这里手工摆一份形状相同的,
    # 钉住列表接口(T10)要读的那几个键。
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["这一页的文字内容在这里,足够长,不会被当扫描页。", ""])
    parse_text_layer(data, cid)
    (cache_dir(data, cid) / "meta.json").write_text(
        json.dumps({"version": PARSE_VERSION, "pages": 2, "scanned_pages": [2], "parsed_at": "2026-10-07T10:00:00"}),
        encoding="utf-8",
    )
    assert course_status(data, cid) == {
        "state": "done",
        "pages": 2,
        "scanned_pages": 1,
        "parsed_at": "2026-10-07T10:00:00",
    }


# —— Task 8:第二层——扫描页渲染成图,交给视觉模型 ——

# 与 T7 同一个坑:夹具里「文字页内容在这里」这类短串会被 SCANNED_TEXT_THRESHOLD=20
# 判成扫描页(与用例意图正好相反)。阈值属计划「关键常量(照抄,勿自行改值)」,不能动;
# 于是只把「文字页」的示例文字补到 20 字符以上,页面角色与断言一字未改。


def vision_body(text="扫描页识别结果:$x^2+y^2=1$"):
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 800, "completion_tokens": 60},
    }


def test_scanned_page_goes_to_vision_and_lands_in_md(tmp_path):
    data = tmp_path / "data"
    with FakeLLM(body=vision_body()) as fake:
        cid = add_course(data, tmp_path, ["文字页内容在这里,这一页的文字层是好的,不是扫描件。", ""])
        meta = parse_course(data, cid, cfg_for(fake))
    assert meta["scanned_pages"] == [2]
    assert "x^2" in page_md(cache_dir(data, cid), 2).read_text(encoding="utf-8")
    parts = fake.requests[0]["json"]["messages"][0]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert usage_totals(data)["calls"] == 1  # 看这一页记了一笔账


def test_second_parse_costs_nothing_more(tmp_path):
    # Review Focus #1/#3 的核心:全部解析好之后再点「解析」——一个模型请求都不许发
    data = tmp_path / "data"
    with FakeLLM(body=vision_body()) as fake:
        cid = add_course(data, tmp_path, ["文字页的文字内容在这里,足够长,不会被当扫描页。", ""])
        parse_course(data, cid, cfg_for(fake))
        sent_after_first = len(fake.requests)
        meta = parse_course(data, cid, cfg_for(fake))  # 第二遍
    assert len(fake.requests) == sent_after_first
    assert meta["scanned_pages"] == [2]  # 重跑也算得出"哪些页是扫描件"
    assert usage_totals(data)["calls"] == 1


def test_text_only_course_needs_no_model_at_all(tmp_path):
    # 全是文字页的课件:连 Key 都没配也能解析完(解析是本地活)
    data = tmp_path / "data"
    cid = add_course(
        data,
        tmp_path,
        [
            "第一页的文字内容在这里,足够长,不会被当扫描页。",
            "第二页的文字内容在这里,足够长,不会被当扫描页。",
        ],
    )
    meta = parse_course(data, cid, Config())
    assert meta["pages"] == 2 and read_meta(data, cid) is not None


def test_scanned_pages_without_key_is_human(tmp_path):
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["文字页的文字内容在这里,足够长,不会被当扫描页。", ""])
    with pytest.raises(CoursewareError) as ei:
        parse_course(data, cid, Config())
    assert "设置" in str(ei.value)


def test_vision_cfg_override():
    cfg = Config(provider="custom", base_url="http://x/v1", api_key="k", model="主模型", vision_model="看图模型")
    assert vision_cfg(cfg).model == "看图模型"
    assert vision_cfg(Config(model="主模型")).model == "主模型"  # 留空 = 跟主模型
    assert cfg.model == "主模型"  # 原配置不被改坏


def test_vision_failure_keeps_pages_and_resumes(tmp_path):
    # Review Focus #3:模型挂了 → 人话 + 已解析页保留;修好后接着跑,只补缺的页
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["文字页的文字内容在这里,足够长,不会被当扫描页。", ""])
    with FakeLLM(status=500) as fake:
        with pytest.raises(CoursewareError) as ei:
            parse_course(data, cid, cfg_for(fake))
    assert "接着来" in str(ei.value)
    assert page_md(cache_dir(data, cid), 1).exists()  # 文字页留着
    assert read_meta(data, cid) is None               # 没跑完 = 没有完成标记
    with FakeLLM(body=vision_body("补上的")) as fake2:
        meta = parse_course(data, cid, cfg_for(fake2))
        assert len(fake2.requests) == 1  # 只补了第 2 页,第 1 页没重跑
    assert meta["pages"] == 2


def test_empty_vision_answer_writes_note_not_blank(tmp_path):
    # Review Focus #5 的解析侧:模型对一页什么都没说 → 页文件里是人话说明,不是空文件
    data = tmp_path / "data"
    with FakeLLM(body=vision_body("")) as fake:
        cid = add_course(data, tmp_path, [""])
        parse_course(data, cid, cfg_for(fake))
    text = page_md(cache_dir(data, cid), 1).read_text(encoding="utf-8")
    assert text.strip() != "" and "没说出内容" in text
