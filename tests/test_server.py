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


def test_post_config_rejects_non_object_body(tmp_path):
    # 数组/字符串这类"合法 JSON 但不是对象"的 body:400,不能 500,也不许改坏配置
    save_config(tmp_path, Config(provider="kimi", api_key="sk-old"))
    r = make_client(tmp_path).post("/api/config", json=[1, 2, 3])
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    assert load_config(tmp_path).provider == "kimi"


def test_post_config_rejects_non_json_body(tmp_path):
    # 恶意页面只能发 text/plain 这种"简单请求";换掉 force=True 后它连解析都过不了
    r = make_client(tmp_path).post("/api/config", data="provider=x", content_type="text/plain")
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_cross_origin_post_is_rejected(tmp_path):
    # 别的网页拿着用户浏览器朝本机发 POST:拦下(这一条是口子①的守门员)
    r = make_client(tmp_path).post(
        "/api/config", json={"provider": "kimi"}, headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403
    assert r.get_json()["ok"] is False


def test_same_origin_post_is_allowed(tmp_path):
    # 我们自己的页面(fetch 的 POST 会带 Origin):必须放行
    r = make_client(tmp_path).post(
        "/api/config", json={"provider": "kimi", "base_url": "", "model": ""},
        headers={"Origin": "http://127.0.0.1:8756"},
    )
    assert r.status_code == 200
