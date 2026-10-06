from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app import __version__


def default_data_dir() -> Path:
    """程序目录同级的 data/(更新程序时不动它)。"""
    return Path(__file__).resolve().parent.parent / "data"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xiaozhao", description="小灶 · 本地课件助手与下载管家")
    parser.add_argument("--version", action="store_true", help="显示版本后退出")
    parser.add_argument("--port", type=int, default=8756, help="服务端口(默认 8756)")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动开浏览器")
    parser.add_argument("--data-dir", type=Path, default=None, help="数据目录(默认:程序目录旁的 data/)")
    parser.add_argument("--self-test", action="store_true", help="启动服务自检一轮后退出(给 CI 和启动器用)")
    args = parser.parse_args(argv)

    data_dir = args.data_dir or default_data_dir()

    if args.version:
        print(f"小灶 v{__version__}")
        print(f"数据目录:{data_dir}")
        return 0

    if args.self_test:
        return _run_self_test(data_dir)

    data_dir.mkdir(parents=True, exist_ok=True)

    from app.server import run_server

    run_server(data_dir, port=args.port, open_browser=not args.no_browser)
    return 0


def _run_self_test(data_dir: Path) -> int:
    import json as _json
    import threading
    import time
    import urllib.request

    from app.server import create_app, find_free_port

    app = create_app(data_dir)
    port = find_free_port(0)
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=True,
    ).start()
    url = f"http://127.0.0.1:{port}/api/status"
    for _ in range(50):
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                data = _json.loads(r.read().decode("utf-8"))
            assert data["version"]
            print("自检通过:服务已起来,/api/status 正常")
            return 0
        except Exception:
            time.sleep(0.1)
    print("自检失败:等了 5 秒服务没起来")
    return 1


if __name__ == "__main__":
    sys.exit(main())
