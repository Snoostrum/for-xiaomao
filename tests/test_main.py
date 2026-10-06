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
