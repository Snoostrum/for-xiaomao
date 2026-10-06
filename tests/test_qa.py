import json

import pytest

from app.config import Config
from app.courseware import CoursewareError, cache_dir, course_file, page_md
from app.courseware.parse import PARSE_VERSION, meta_file
from app.courseware.qa import ask_course, build_corpus
from app.usage import usage_totals
from tests.test_parse import add_course
from tests.test_provider import FakeLLM, cfg_for


def seed_parsed(data_dir, tmp_path, pages: list[str]) -> str:
    """直接铺一份"已完整解析"的课件:问答测的是问答,不重测解析。"""
    cid = add_course(data_dir, tmp_path, ["占位"])
    cache = cache_dir(data_dir, cid) / "pages"
    cache.mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(pages, start=1):
        (cache / f"{i:03d}.md").write_text(text, encoding="utf-8")
    meta_file(data_dir, cid).write_text(
        json.dumps({"version": PARSE_VERSION, "pages": len(pages), "scanned_pages": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return cid


def test_answer_comes_back_and_corpus_has_page_markers(tmp_path):
    data = tmp_path / "data"
    body = {
        "choices": [{"message": {"content": "矩阵乘法在第 2 页讲过。"}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 20},
    }
    with FakeLLM(body=body) as fake:
        cid = seed_parsed(data, tmp_path, ["第一页讲向量", "第二页讲矩阵乘法"])
        answer = ask_course(data, cid, "矩阵乘法在哪页?", cfg_for(fake))
        assert "第 2 页" in answer
        sent = fake.requests[0]["json"]["messages"][0]["content"]
        assert "=== 第 1 页 ===" in sent and "=== 第 2 页 ===" in sent
        assert "矩阵乘法在哪页?" in sent
    assert usage_totals(data)["calls"] == 1
    assert usage_totals(data)["prompt_tokens"] == 900


def test_ask_before_parse_is_human(tmp_path):
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["一页"])
    with pytest.raises(CoursewareError) as ei:
        ask_course(data, cid, "讲了啥?", Config(provider="custom", base_url="http://x/v1", api_key="k", model="m"))
    assert "解析" in str(ei.value)


def test_empty_question_is_human(tmp_path):
    data = tmp_path / "data"
    cid = seed_parsed(data, tmp_path, ["内容"])
    with pytest.raises(CoursewareError):
        ask_course(data, cid, "   ", Config(provider="custom", base_url="http://x/v1", api_key="k", model="m"))


def test_too_long_corpus_asks_to_split(tmp_path):
    # Review Focus:超长课件不硬塞,人话劝拆章节
    data = tmp_path / "data"
    cid = seed_parsed(data, tmp_path, ["长" * 250_000])
    with pytest.raises(CoursewareError) as ei:
        ask_course(data, cid, "讲了啥?", Config(provider="custom", base_url="http://x/v1", api_key="k", model="m"))
    assert "拆" in str(ei.value)


def test_missing_model_config_is_human(tmp_path):
    data = tmp_path / "data"
    cid = seed_parsed(data, tmp_path, ["内容"])
    with pytest.raises(CoursewareError) as ei:
        ask_course(data, cid, "讲了啥?", Config())
    assert "设置" in str(ei.value)


def test_empty_answer_falls_back_to_human_line(tmp_path):
    # Review Focus #5 的问答侧:模型给了空回答 → 界面上是人话,不是一片空白
    data = tmp_path / "data"
    with FakeLLM(body={"choices": [{"message": {"content": ""}}]}) as fake:
        cid = seed_parsed(data, tmp_path, ["内容"])
        answer = ask_course(data, cid, "讲了啥?", cfg_for(fake))
    assert answer.strip() != "" and "再问" in answer


# —— 以下是对着 Review Focus #5 的「无 usage」半边补的验收专项 ——


def test_missing_usage_still_records_a_call(tmp_path):
    # Review Focus #5:平台没回 usage(token 字段整个缺)→ 回答照常给人话,账本照记一笔,不漏次
    data = tmp_path / "data"
    with FakeLLM() as fake:  # FakeLLM 默认 body 不带 usage
        cid = seed_parsed(data, tmp_path, ["内容"])
        answer = ask_course(data, cid, "讲了啥?", cfg_for(fake))
    assert answer == "收到"
    assert usage_totals(data)["calls"] == 1
    assert usage_totals(data)["prompt_tokens"] == 0
