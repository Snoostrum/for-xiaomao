from app.server import create_app


def make_client(tmp_path):
    app = create_app(tmp_path)
    app.config["TESTING"] = True
    return app.test_client()


def test_index_shows_three_tabs(tmp_path):
    html = make_client(tmp_path).get("/").get_data(as_text=True)
    for name in ("课件助手", "下载管家", "设置"):
        assert name in html


def test_presets_endpoint_lists_platforms(tmp_path):
    data = make_client(tmp_path).get("/api/presets").get_json()
    keys = [p["key"] for p in data]
    assert "openrouter" in keys and "kimi" in keys and "custom" in keys


def test_js_and_css_are_served(tmp_path):
    c = make_client(tmp_path)
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/style.css").status_code == 200
