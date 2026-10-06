import logging
import socket

from app.config import Config, load_config, save_config
from app.logging_setup import setup_logging
from app.server import create_app, find_free_port


def make_client(tmp_path):
    app = create_app(tmp_path)
    app.config["TESTING"] = True
    return app.test_client()


def test_status_reports_version_and_no_key(tmp_path):
    data = make_client(tmp_path).get("/api/status").get_json()
    assert data["has_key"] is False
    assert data["version"]


def test_get_config_masks_key(tmp_path):
    save_config(tmp_path, Config(provider="kimi", api_key="sk-1234567890"))
    data = make_client(tmp_path).get("/api/config").get_json()
    assert data["api_key_masked"] == "sk-1…7890"
    assert "sk-1234567890" not in str(data)


def test_post_config_fills_preset_defaults_and_keeps_key_when_blank(tmp_path):
    save_config(tmp_path, Config(provider="kimi", api_key="sk-old"))
    r = make_client(tmp_path).post("/api/config", json={"provider": "openrouter", "api_key": "  ", "base_url": "", "model": ""})
    assert r.status_code == 200
    cfg = load_config(tmp_path)
    assert cfg.provider == "openrouter"
    assert cfg.base_url == "https://openrouter.ai/api/v1"
    assert cfg.model  # 预设默认模型已填入
    assert cfg.api_key == "sk-old"  # 留空 = 不改


def test_post_config_stores_new_key(tmp_path):
    make_client(tmp_path).post("/api/config", json={"provider": "openrouter", "api_key": " sk-new\n", "base_url": "", "model": ""})
    assert load_config(tmp_path).api_key == "sk-new"


def test_test_connection_endpoint_wires_provider(tmp_path, monkeypatch):
    import app.server as server_mod
    save_config(tmp_path, Config(provider="custom", base_url="https://x/v1", api_key="k", model="m"))
    monkeypatch.setattr(server_mod, "test_connection", lambda cfg: (True, "连接成功,模型有回应 ✔"))
    r = make_client(tmp_path).post("/api/test-connection")
    assert r.get_json() == {"ok": True, "message": "连接成功,模型有回应 ✔"}


def test_find_free_port_avoids_busy_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    busy = s.getsockname()[1]
    try:
        assert find_free_port(busy) != busy
    finally:
        s.close()


def test_find_free_port_zero_returns_real_assigned_port():
    assert 1024 < find_free_port(0) < 65536


def test_setup_logging_writes_utf8_file_and_is_idempotent(tmp_path):
    setup_logging(tmp_path)
    setup_logging(tmp_path)  # 再来一次不应该重复挂 handler
    logging.getLogger("xiaozhao.test").info("你好,日志")
    text = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "你好,日志" in text
