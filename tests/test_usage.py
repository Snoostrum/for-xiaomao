from app.usage import record_usage, usage_totals


def test_record_and_total(tmp_path):
    record_usage(tmp_path, "提问", "m", {"prompt_tokens": 120, "completion_tokens": 30})
    record_usage(tmp_path, "看扫描页", "m", None)  # 平台没给用量也要记一笔次数
    t = usage_totals(tmp_path)
    assert t == {"calls": 2, "prompt_tokens": 120, "completion_tokens": 30}


def test_totals_on_missing_file_is_zero(tmp_path):
    assert usage_totals(tmp_path) == {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def test_bad_line_is_skipped(tmp_path):
    record_usage(tmp_path, "提问", "m", {"prompt_tokens": 1, "completion_tokens": 1})
    with (tmp_path / "usage.jsonl").open("a", encoding="utf-8") as f:
        f.write("这不是 json\n")
    assert usage_totals(tmp_path)["calls"] == 1
