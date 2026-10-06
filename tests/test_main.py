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


def test_check_pymupdf_round_trips_a_small_pdf():
    # 解析课件的库得真能干活:建一份、存一遍、开回来、抽字对得上(内存里走,不落盘)
    from app.main import _check_pymupdf

    _check_pymupdf()  # 不抛异常就算过


def test_self_test_reports_pymupdf_ready(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    out = subprocess.run(
        [sys.executable, "-m", "app.main", "--self-test", "--data-dir", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=30,
    )
    assert out.returncode == 0
    assert "PyMuPDF 就位" in out.stdout


def test_self_test_speaks_before_the_import_error_when_pymupdf_missing(tmp_path):
    # 打包漏了 pymupdf 的样子:import 就炸。自检必须抢在那之前说人话,
    # 而不是甩一段 ImportError traceback 给朋友看。
    # 做法:在 PYTHONPATH 前面塞一个同名模块,import 时直接抛 ImportError。
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "pymupdf.py").write_text('raise ImportError("模拟:打包时把 PyMuPDF 漏了")\n', encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(shadow) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    out = subprocess.run(
        [sys.executable, "-m", "app.main", "--self-test", "--data-dir", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=30,
    )
    assert out.returncode == 1
    assert "自检失败:PyMuPDF 不可用" in out.stdout
    assert "Traceback" not in out.stdout + out.stderr  # 朋友不该看到 py 的栈


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
