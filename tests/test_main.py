import os
import subprocess
import sys


def test_version_constant():
    from app import __version__
    assert __version__.count(".") == 2


def test_cli_prints_version_and_data_dir(tmp_path):
    # PYTHONIOENCODING=utf-8:中文 Windows 上子进程默认按 GBK 输出,和父进程按 utf-8 解码会对不上
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    out = subprocess.run(
        [sys.executable, "-m", "app.main", "--version", "--data-dir", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert out.returncode == 0
    assert "0.1.0" in out.stdout
    assert str(tmp_path) in out.stdout


def test_self_test_starts_server_and_exits_zero(tmp_path):
    # --self-test 会真起服务、请求自己的 /api/status;这是 CI 与两个启动器共用的冒烟路径
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    out = subprocess.run(
        [sys.executable, "-m", "app.main", "--self-test", "--data-dir", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=30,
    )
    assert out.returncode == 0
    assert "自检通过" in out.stdout


def test_default_data_dir_is_next_to_exe_when_frozen(monkeypatch, tmp_path):
    from app.main import default_data_dir

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "小灶.exe"))
    assert default_data_dir() == tmp_path / "data"


def test_setup_console_does_not_crash():
    from app.main import _setup_console

    _setup_console()


def test_main_with_chat_runs_terminal_loop(tmp_path):
    # 真正的端到端:--chat 强制开聊天,管道喂「你好→退出」;地址是假的,所以会看到人话报错。
    # 有意不设 PYTHONIOENCODING:输入输出的 UTF-8 由 app 自己收——这正是这条测试要盯的。
    from app.config import Config, save_config

    save_config(tmp_path, Config(provider="custom", base_url="http://127.0.0.1:1/v1", api_key="k", model="m"))
    out = subprocess.run(
        [sys.executable, "-m", "app.main", "--chat", "--no-browser", "--port", "0", "--data-dir", str(tmp_path)],
        input="你好\n退出\n", capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert out.returncode == 0
    assert "你>" in out.stdout
    assert "连不上" in out.stdout  # 假地址:报错也必须是人话
    assert out.stdout.count("连不上") == 1  # 「退出」被认出来了,没有被当成第二句继续问
    assert "再见" in out.stdout
