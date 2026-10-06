from app.config import Config, config_path, load_config, mask_key, save_config


def test_roundtrip(tmp_path):
    cfg = Config(provider="openrouter", base_url="https://x/v1", api_key="sk-abc", model="m",
                 vision_model="vm", download_dir="")
    save_config(tmp_path, cfg)
    assert load_config(tmp_path) == cfg


def test_key_and_url_whitespace_stripped(tmp_path):
    cfg = Config(provider=" openrouter ", base_url=" https://x/v1 \n", api_key="  sk-abc\n", model=" m ", download_dir="")
    save_config(tmp_path, cfg)
    got = load_config(tmp_path)
    assert got.api_key == "sk-abc"
    assert got.base_url == "https://x/v1"
    assert got.provider == "openrouter"
    assert got.model == "m"


def test_missing_file_returns_defaults(tmp_path):
    assert load_config(tmp_path) == Config()


def test_corrupt_config_backed_up_and_defaults_returned(tmp_path):
    p = config_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ 这不是 json", encoding="utf-8")
    assert load_config(tmp_path) == Config()
    assert (tmp_path / "config.json.broken1").exists()
    assert not p.exists()
    # 再坏一次,应该得到 broken2,不覆盖第一次的备份
    p.write_text("还是坏", encoding="utf-8")
    load_config(tmp_path)
    assert (tmp_path / "config.json.broken2").exists()


def test_paths_with_spaces_and_cjk(tmp_path):
    d = tmp_path / "我的 小灶"
    d.mkdir()
    save_config(d, Config(api_key="sk-x"))
    assert load_config(d).api_key == "sk-x"


def test_mask_key():
    assert mask_key("") == ""
    assert mask_key("short") == "*****"
    assert mask_key("sk-1234567890") == "sk-1…7890"
