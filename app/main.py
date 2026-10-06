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
    args = parser.parse_args(argv)

    data_dir = args.data_dir or default_data_dir()

    if args.version:
        print(f"小灶 v{__version__}")
        print(f"数据目录:{data_dir}")
        return 0

    data_dir.mkdir(parents=True, exist_ok=True)

    from app.server import run_server

    run_server(data_dir, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
