from __future__ import annotations

import logging
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import flask.cli
from flask import Flask, jsonify, request, send_from_directory

from app import __version__
from app.config import load_config, mask_key, save_config
from app.llm.presets import PRESETS
from app.llm.provider import test_connection
from app.logging_setup import setup_logging

log = logging.getLogger(__name__)


def find_free_port(preferred: int) -> int:
    """先试首选端口,再顺延 20 个;都不行就让系统挑。preferred=0 表示直接让系统挑。"""
    candidates = [preferred, *range(preferred + 1, preferred + 21)] if preferred else [0]
    for port in candidates:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return int(s.getsockname()[1])  # 绑 0 时这里拿到的是系统真正分配的口
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def create_app(data_dir: Path) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["DATA_DIR"] = data_dir
    web_dir = Path(__file__).resolve().parent / "web"

    def _local_origin_ok(origin: str) -> bool:
        """Origin 头只认本机。浏览器发跨站请求一定会带 Origin;curl/测试不带,放行。"""
        try:
            return urlparse(origin).hostname in ("127.0.0.1", "localhost")
        except ValueError:
            return False

    @app.before_request
    def _guard_cross_origin():
        if request.method in ("POST", "PUT", "DELETE"):
            origin = request.headers.get("Origin", "")
            if origin and not _local_origin_ok(origin):
                log.warning("拒绝了来自 %s 的 %s %s", origin, request.method, request.path)
                return jsonify({"ok": False, "message": "这个请求不是从小灶页面发出来的,已拒绝。"}), 403
        return None

    @app.get("/")
    def index():
        return send_from_directory(web_dir, "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename: str):
        return send_from_directory(web_dir, filename)

    @app.get("/api/status")
    def api_status():
        cfg = load_config(data_dir)
        return jsonify({"version": __version__, "os": sys.platform, "has_key": bool(cfg.api_key)})

    @app.get("/api/presets")
    def api_presets():
        return jsonify([
            {"key": p.key, "name": p.name, "base_url": p.base_url, "default_model": p.default_model}
            for p in PRESETS.values()
        ])

    @app.get("/api/config")
    def api_get_config():
        cfg = load_config(data_dir)
        return jsonify({
            "provider": cfg.provider,
            "base_url": cfg.base_url,
            "model": cfg.model,
            "vision_model": cfg.vision_model,
            "api_key_masked": mask_key(cfg.api_key),
            "download_dir": cfg.download_dir,
        })

    @app.post("/api/config")
    def api_save_config():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "message": "请求格式不对(需要 JSON 对象)——请在页面上操作。"}), 400
        cfg = load_config(data_dir)
        new_provider = str(body.get("provider", "")).strip()
        if new_provider:  # 空 = 不改动已保存的平台(前端没加载全时,别把人配置抹掉)
            cfg.provider = new_provider
        cfg.base_url = str(body.get("base_url", cfg.base_url)).strip()
        cfg.model = str(body.get("model", cfg.model)).strip()
        if "vision_model" in body:
            cfg.vision_model = str(body.get("vision_model") or "").strip()
        cfg.download_dir = str(body.get("download_dir", cfg.download_dir)).strip()
        new_key = str(body.get("api_key", "")).strip()
        if new_key:  # 空 = 不改动已保存的 Key
            cfg.api_key = new_key
        preset = PRESETS.get(cfg.provider)
        if preset and not cfg.base_url:
            cfg.base_url = preset.base_url
        if preset and not cfg.model:
            cfg.model = preset.default_model
        save_config(data_dir, cfg)
        return jsonify({"ok": True, "api_key_masked": mask_key(cfg.api_key)})

    @app.post("/api/test-connection")
    def api_test_connection():
        cfg = load_config(data_dir)
        ok, msg = test_connection(cfg)
        return jsonify({"ok": ok, "message": msg})

    return app


def start_server(data_dir: Path, port: int = 8756, open_browser: bool = True) -> tuple[int, str]:
    """在后台线程把服务起起来,立刻返回 (真实端口, 地址)——黑窗口留给终端聊天用。"""
    setup_logging(data_dir)
    app = create_app(data_dir)
    real_port = find_free_port(port)
    url = f"http://127.0.0.1:{real_port}/"
    if real_port != port:
        log.info("端口 %s 被占用,改用 %s", port, real_port)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    log.info("小灶启动于 %s(数据目录 %s)", url, data_dir)
    flask.cli.show_server_banner = lambda *a, **k: None  # 黑窗口留给聊天,不印 Flask 的横幅
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=real_port, debug=False, use_reloader=False),
        daemon=True,
    ).start()
    return real_port, url
