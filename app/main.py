from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app import __version__


def _setup_console() -> None:
    """标准输入输出统一走 UTF-8:重定向到文件/管道时,中文和 ✔ 这类符号不会变乱码。

    真控制台本来就按 Unicode 走,这里主要管"被管道/文件重定向"的情况;
    输入用 errors=replace:遇到坏字节就替成 �,别让聊天崩在解码报错上。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


def default_data_dir() -> Path:
    """数据目录:开发时在程序目录旁边;打包成 exe 后在 exe 旁边——整个文件夹挪个地方,Key 也跟着走。"""
    if getattr(sys, "frozen", False):  # PyInstaller 打包后 sys.frozen 为 True
        return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parent.parent / "data"


def main(argv: list[str] | None = None) -> int:
    _setup_console()
    parser = argparse.ArgumentParser(prog="xiaozhao", description="小灶 · 本地课件助手与下载管家")
    parser.add_argument("--version", action="store_true", help="显示版本后退出")
    parser.add_argument("--port", type=int, default=8756, help="服务端口(默认 8756)")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动开浏览器")
    parser.add_argument("--chat", action="store_true", help="强制打开终端聊天(默认只在交互式终端里开)")
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

    from app.chat import chat_loop
    from app.server import start_server

    _port, url = start_server(data_dir, port=args.port, open_browser=not args.no_browser)

    if args.chat or (sys.stdin is not None and sys.stdin.isatty()):
        chat_loop(data_dir, url)
    else:
        _wait_forever()

    if getattr(sys, "frozen", False) and sys.stdin is not None and sys.stdin.isatty():
        try:  # 双击打开的窗口:别让"再见"一闪而过
            input("(按回车键关闭窗口)")
        except (EOFError, KeyboardInterrupt):
            pass
    return 0


def _wait_forever() -> None:
    """不是交互式终端(比如被脚本调起):只开网页服务,等 Ctrl+C / 关窗口。"""
    import time

    print("没有交互式终端——只开了网页服务;按 Ctrl+C 或关掉窗口结束。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


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
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1) as r:
                data = _json.loads(r.read().decode("utf-8"))
            assert data["version"]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
                page = r.read().decode("utf-8")
            assert "小灶" in page  # 网页资源也打进去了(打包版最容易漏的就是这个)
            print("自检通过:服务已起来,/api/status 与首页都正常")
            return 0
        except Exception:
            time.sleep(0.1)
    print("自检失败:等了 5 秒服务没起来")
    return 1


if __name__ == "__main__":
    sys.exit(main())
