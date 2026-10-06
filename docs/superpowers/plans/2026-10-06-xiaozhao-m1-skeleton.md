# 小灶 M1「装得上」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个"双击就能开"的本地小应用骨架:浏览器窗口 + 三个标签页 + 设置页(填 Key、测试连接);Windows 开发机上全流程可跑,Mac 包能在 CI 出包并冒烟通过。

**Architecture:** 单进程本地服务(Flask,只绑 `127.0.0.1`),浏览器当窗口;配置与日志落在程序目录旁的 `data/`;平台适配层(预设 + OpenAI 兼容调用)把"换模型"隔离成改配置;Mac 交付用 python-build-standalone 自带解释器 + `start.command`,由 GitHub Actions(macos-15)出 tar.gz 并冒烟。

**Tech Stack:** Python 3.12/3.13、Flask、requests、pytest;前端 = 无框架原生 HTML/JS/CSS;打包 = python-build-standalone + tar.gz + GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-10-06-xiaozhao-design.md`。本计划只实现它的 M1 里程碑(§5 表第一行;"装得上")。§2 课件助手、§3 下载管家、M4 交付各自另有计划,等 M1 验收后再拆。

**执行环境:** 开发机 = Windows 11(用户机器);Python/pytest 命令在 PowerShell 里跑;`bash -n`、tar 等用 Git Bash。CI 在 macos-15。

## Global Constraints

- 服务只绑 `127.0.0.1`;默认端口 `8756`,被占用自动顺延,再不行交给系统挑。
- 所有文件读写显式 `encoding="utf-8"`;路径只用 `pathlib`。
- 运行时依赖仅限 **flask、requests**(测试另加 pytest)。M1 不引入任何其他三方包。
- 面向用户的错误一律"人话"中文,不得把英文栈丢到界面上;细节写日志。
- 数据目录 = 程序目录同级的 `data/`(更新时不碰它)。
- 不假设 venv;不写死绝对路径。
- 每个任务结束提交一次 git;信息用 `feat:/fix:/docs:/chore:` 前缀。
- 模型名、接口地址全部来自配置/预设,不散落在业务代码里。
- 预设里标 `# 需核实` 的值,动手当天打开对应平台文档确认(规格 §6-4)。
- 每次 git 提交的信息末尾都带一行 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。

## Review Focus

1. **粘贴的 Key 带空格 / 换行 / 全角字符**:期望保存时自动清理——否则"测试连接"永远失败而用户不知为什么。(Task 3)
2. **config.json 被改坏或写入中断**:期望应用照常启动、坏文件被备份、界面照常可用——不白屏、不崩溃。(Task 3)
3. **8756 端口被别的程序占用**:期望自动换端口,且浏览器打开的还是真正在跑的那个地址。(Task 5)
4. **base_url 写错 / 断网 / 超时**:期望"人话"提示并附上尝试过的网址,而不是英文栈。(Task 4)
5. **工具放在带空格或中文的路径下**(如 `~/我的 小灶/`):期望配置、日志、数据读写全部正常。(Task 3 的路径测试 + Task 7 脚本里的引号)

---

### Task 1: 项目骨架与 CLI 入口

**Files:**
- Create: `requirements.txt`, `.gitignore`, `app/__init__.py`, `app/main.py`, `tests/__init__.py`(空文件), `tests/test_main.py`

**Interfaces:**
- Produces: `app.__version__: str`;`app.main.main(argv: list[str] | None = None) -> int`;`app.main.default_data_dir() -> pathlib.Path`(程序目录同级 `data/`)。

- [ ] **Step 1: 写失败测试 `tests/test_main.py`**

```python
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
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_main.py -q`
Expected: FAIL(ModuleNotFoundError: No module named 'app')

- [ ] **Step 3: 实现**

`app/__init__.py`:

```python
__version__ = "0.1.0"
```

`app/main.py`:

```python
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
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.version:
        print(f"小灶 v{__version__}")
        print(f"数据目录:{data_dir}")
        return 0

    print(f"数据目录:{data_dir}")
    print("(服务入口将在 Task 5 接通)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`requirements.txt`:

```
flask>=3.0
requests>=2.31
```

`.gitignore`:

```
__pycache__/
*.pyc
.pytest_cache/
data/
dist/
xiaozhao-macos-*.tar.gz
pbs.tar.gz
Mac自检-输出.txt
```

- [ ] **Step 4: 装依赖并跑测试**

Run: `pip install flask requests pytest` 然后 `python -m pytest tests/test_main.py -q`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 项目骨架与 CLI 入口(--version/--data-dir)"
```

---

### Task 2: 「Mac 自检.command」(独立脚本,先交付给朋友)

**Files:**
- Create: `tools/macheck.command`

**Interfaces:**
- Produces: 一份可发给朋友的脚本;运行后在同目录生成 `Mac自检-输出.txt`。

**为什么排这么前**:规格 §6-3 要朋友的芯片与系统版本(决定打包架构);这份脚本是唯一能拿到它的途径,越早给他越好。

- [ ] **Step 1: 写脚本 `tools/macheck.command`**

```bash
#!/bin/bash
# 小灶 · Mac 自检(把生成的 txt 发回即可)
# 双击不行的话:打开「终端」,输入 bash 空格,把本文件拖进去,回车。
cd "$(dirname "$0")" || exit 1
OUT="Mac自检-输出.txt"
{
  echo "== 小灶 Mac 自检 =="
  echo "时间: $(date 2>/dev/null || true)"
  echo "-- 芯片架构 --"; uname -m 2>/dev/null || echo "(uname 不可用)"
  echo "-- 系统版本 --"; sw_vers 2>/dev/null || echo "(非 macOS 或 sw_vers 不可用)"
  echo "-- CPU 型号 --"; sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "(不可用)"
  echo "-- 本脚本自身的权限位与扩展属性 --"; ls -l@ "$0" 2>/dev/null || true
  echo "-- 是否已存在 python 目录(正常应显示:没有) --"; ls -ld python 2>/dev/null || echo "(没有,正常)"
} 2>&1 | tee "$OUT"
echo
echo "已保存到:$OUT —— 把这个文件发回来就行。"
read -n 1 -s -r -p "按任意键关闭此窗口…"
```

- [ ] **Step 2: 开发机语法与容错验证(Windows Git Bash)**

Run: `bash -n tools/macheck.command && bash tools/macheck.command </dev/null`
Expected: 语法检查通过;运行输出里非 macOS 的项显示"(不可用)"仍然跑完;生成 `Mac自检-输出.txt`。
Run: `rm Mac自检-输出.txt`(清掉本机测试产物)
说明:Mac 真机上的行为(权限位、双击体验)留到 Task 9 的验收清单,不在这里假装验证。

- [ ] **Step 3: 记录可执行位并提交**

```bash
git add -A
git update-index --chmod=+x tools/macheck.command
git commit -m "feat: Mac 自检.command(开发机语法验证;真机行为待朋友跑)"
```

---

### Task 3: 配置模块(app/config.py)

**Files:**
- Create: `app/config.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Config` dataclass,字段:`provider: str`、`base_url: str`、`api_key: str`、`model: str`、`download_dir: str`
  - `config_path(data_dir: Path) -> Path`
  - `mask_key(key: str) -> str`(≤8 位全星号;更长保留头 4 尾 4,中间 `…`)
  - `load_config(data_dir: Path) -> Config`(坏文件自动备份为 `config.json.broken<N>`;字符串字段自动 strip;文件不存在返回默认值)
  - `save_config(data_dir: Path, cfg: Config) -> None`(原子写:先 `.tmp` 再 `replace`)

- [ ] **Step 1: 写失败测试 `tests/test_config.py`**

```python
from app.config import Config, config_path, load_config, mask_key, save_config


def test_roundtrip(tmp_path):
    cfg = Config(provider="openrouter", base_url="https://x/v1", api_key="sk-abc", model="m", download_dir="")
    save_config(tmp_path, cfg)
    assert load_config(tmp_path) == cfg


def test_key_and_url_whitespace_stripped(tmp_path):
    cfg = Config(provider=" openrouter ", base_url=" https://x/v1 \n", api_key="  sk-abc\n", model=" m ", download_dir="")
    save_config(tmp_path, cfg)
    got = load_config(tmp_path)
    assert got.api_key == "sk-abc"
    assert got.base_url == "https://x/v1"
    assert got.provider == "openrouter"
    assert got.model == "m"


def test_missing_file_returns_defaults(tmp_path):
    assert load_config(tmp_path) == Config()


def test_corrupt_config_backed_up_and_defaults_returned(tmp_path):
    p = config_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ 这不是 json", encoding="utf-8")
    assert load_config(tmp_path) == Config()
    assert (tmp_path / "config.json.broken1").exists()
    assert not p.exists()
    # 再坏一次,应该得到 broken2,不覆盖第一次的备份
    p.write_text("还是坏", encoding="utf-8")
    load_config(tmp_path)
    assert (tmp_path / "config.json.broken2").exists()


def test_paths_with_spaces_and_cjk(tmp_path):
    d = tmp_path / "我的 小灶"
    d.mkdir()
    save_config(d, Config(api_key="sk-x"))
    assert load_config(d).api_key == "sk-x"


def test_mask_key():
    assert mask_key("") == ""
    assert mask_key("short") == "*****"
    assert mask_key("sk-1234567890") == "sk-1…7890"
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现 `app/config.py`**

```python
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

_STRIP_FIELDS = ("provider", "base_url", "api_key", "model", "download_dir")


@dataclass
class Config:
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    download_dir: str = ""


def config_path(data_dir: Path) -> Path:
    return data_dir / "config.json"


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "…" + key[-4:]


def _as_str(v: object) -> str:
    return "" if v is None else str(v)


def _backup_broken(p: Path) -> Path:
    n = 1
    while True:
        candidate = p.with_name(f"{p.name}.broken{n}")
        if not candidate.exists():
            return candidate
        n += 1


def load_config(data_dir: Path) -> Config:
    p = config_path(data_dir)
    if not p.exists():
        return Config()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config.json 顶层不是对象")
        cfg = Config(**{f.name: _as_str(raw.get(f.name)) for f in fields(Config)})
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        backup = _backup_broken(p)
        p.replace(backup)
        log.warning("config.json 读取失败(%s),已备份到 %s,按默认值继续", e, backup.name)
        return Config()
    for name in _STRIP_FIELDS:
        setattr(cfg, name, getattr(cfg, name).strip())
    return cfg


def save_config(data_dir: Path, cfg: Config) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in _STRIP_FIELDS:
        setattr(cfg, name, getattr(cfg, name).strip())
    p = config_path(data_dir)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
```

- [ ] **Step 4: 跑测试,确认通过**

Run: `python -m pytest tests/test_config.py -q`
Expected: `6 passed`

- [ ] **Step 5: 提交**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: 配置模块(原子写/坏文件备份/Key 脱敏)"
```

---

### Task 4: 平台预设 + LLM 适配层(app/llm/)

**Files:**
- Create: `app/llm/__init__.py`(空文件), `app/llm/presets.py`, `app/llm/provider.py`, `tests/test_provider.py`

**Interfaces:**
- Consumes: `app.config.Config`(Task 3)
- Produces:
  - `Preset` dataclass(`key, name, base_url, default_model`)与 `PRESETS: dict[str, Preset]`
  - `LLMError(Exception)`:`human`(人话中文)、`detail`(给日志)
  - `chat_completion(cfg: Config, messages: list[dict], max_tokens: int = 1024, timeout: float = 60.0) -> str`
  - `test_connection(cfg: Config) -> tuple[bool, str]`

- [ ] **Step 1: 写失败测试 `tests/test_provider.py`(自带本地假 LLM 服务器)**

```python
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.config import Config
from app.llm.provider import chat_completion, test_connection


class FakeLLM:
    """可编排返回码的本地假服务,并记录收到的每个请求。"""

    def __init__(self, status: int = 200, body: dict | None = None):
        self.status = status
        self.body = body or {"choices": [{"message": {"content": "收到"}}]}
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append({
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "json": json.loads(self.rfile.read(length) or b"{}"),
                })
                payload = json.dumps(outer.body).encode("utf-8")
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()


def cfg_for(fake: FakeLLM) -> Config:
    return Config(provider="custom", base_url=fake.base_url, api_key="sk-test", model="m")


def test_success_hits_chat_completions_with_bearer():
    with FakeLLM() as fake:
        ok, msg = test_connection(cfg_for(fake))
        assert ok is True
        req = fake.requests[0]
        assert req["path"] == "/v1/chat/completions"
        assert req["auth"] == "Bearer sk-test"
        assert req["json"]["model"] == "m"


def test_401_tells_user_key_problem():
    with FakeLLM(status=401) as fake:
        ok, msg = test_connection(cfg_for(fake))
        assert ok is False and "Key" in msg


def test_429_tells_user_rate_limited():
    with FakeLLM(status=429) as fake:
        ok, msg = test_connection(cfg_for(fake))
        assert ok is False and "频繁" in msg


def test_connection_refused_says_cannot_reach_with_url():
    cfg = Config(provider="custom", base_url="http://127.0.0.1:1/v1", api_key="k", model="m")
    ok, msg = test_connection(cfg)
    assert ok is False and "连不上" in msg and "127.0.0.1:1" in msg


def test_chat_completion_returns_text():
    with FakeLLM() as fake:
        assert chat_completion(cfg_for(fake), [{"role": "user", "content": "hi"}]) == "收到"


def test_missing_key_says_so():
    ok, msg = test_connection(Config())
    assert ok is False and "Key" in msg
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_provider.py -q`
Expected: FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现 `app/llm/presets.py`**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    base_url: str
    default_model: str


# 模型名与接口地址都会随平台调整;设置页允许手改,不做硬校验。
# 「需核实」= 动手当天打开对应平台文档确认一次(规格 §6-4)。
PRESETS: dict[str, Preset] = {
    "openrouter": Preset(
        key="openrouter",
        name="OpenRouter(免费起步)",
        base_url="https://openrouter.ai/api/v1",
        default_model="google/gemma-4-31b-it:free",  # 需核实
    ),
    "kimi": Preset(
        key="kimi",
        name="Kimi 国际版",
        base_url="https://api.moonshot.ai/v1",  # 需核实(platform.kimi.ai 文档)
        default_model="kimi-k3",  # 需核实
    ),
    "bailian_intl": Preset(
        key="bailian_intl",
        name="阿里百炼国际版",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",  # 需核实
        default_model="qwen3.8-flash",  # 需核实
    ),
    "custom": Preset(key="custom", name="自定义", base_url="", default_model=""),
}
```

- [ ] **Step 4: 实现 `app/llm/provider.py`**

```python
from __future__ import annotations

import logging

import requests

from app.config import Config

log = logging.getLogger(__name__)


class LLMError(Exception):
    def __init__(self, human: str, detail: str = ""):
        super().__init__(human)
        self.human = human
        self.detail = detail


def _chat_url(cfg: Config) -> str:
    return cfg.base_url.rstrip("/") + "/chat/completions"


def _post_chat(cfg: Config, payload: dict, timeout: float) -> dict:
    url = _chat_url(cfg)
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        raise LLMError("等太久了没收到回应——网络慢或对方服务在忙,过会儿再试。", f"timeout {url}")
    except requests.exceptions.SSLError as e:
        raise LLMError("安全连接没建起来(SSL 错误)——检查『接口地址』填对了没有。", f"{e} | {url}")
    except requests.exceptions.ConnectionError as e:
        raise LLMError(f"连不上 {url} ——检查网络,或确认『接口地址』填对了。", f"{e} | {url}")

    if resp.status_code == 401:
        raise LLMError("Key 不对或已过期——去平台重新复制一个,粘贴到上面。", resp.text[:300])
    if resp.status_code == 402:
        raise LLMError("账户余额不足——去平台充值,或者先用免费模型。", resp.text[:300])
    if resp.status_code == 403:
        raise LLMError("平台拒绝了这个请求(403)——可能是地区限制或权限问题。", resp.text[:300])
    if resp.status_code == 404:
        raise LLMError("接口地址或模型名不对(404)——检查『接口地址』和『模型名』。", resp.text[:300])
    if resp.status_code == 429:
        raise LLMError("请求太频繁被限速了——等一分钟再试。", resp.text[:300])
    if resp.status_code >= 500:
        raise LLMError("对方服务器出错——不是你的问题,过会儿再试。", resp.text[:300])
    if resp.status_code != 200:
        raise LLMError(f"遇到没见过的错误(HTTP {resp.status_code})——细节在日志里。", resp.text[:300])

    try:
        return resp.json()
    except ValueError:
        raise LLMError("对方的回应看不懂(不是 JSON)——可能接口地址不对。", resp.text[:300])


def chat_completion(cfg: Config, messages: list[dict], max_tokens: int = 1024, timeout: float = 60.0) -> str:
    payload = {"model": cfg.model, "messages": messages, "max_tokens": max_tokens}
    data = _post_chat(cfg, payload, timeout)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("回应里没有文本内容——可能模型名不对。", str(data)[:300])


def test_connection(cfg: Config) -> tuple[bool, str]:
    if not cfg.api_key:
        return False, "还没填 Key。"
    if not cfg.base_url:
        return False, "还没填接口地址。"
    if not cfg.model:
        return False, "还没填模型名。"
    try:
        chat_completion(cfg, [{"role": "user", "content": "你好"}], max_tokens=4, timeout=15.0)
    except LLMError as e:
        log.warning("测试连接失败:%s | %s", e.human, e.detail)
        return False, e.human
    return True, "连接成功,模型有回应 ✔"
```

- [ ] **Step 5: 跑测试,确认通过**

Run: `python -m pytest tests/test_provider.py -q`
Expected: `6 passed`

- [ ] **Step 6: 提交**

```bash
git add app/llm/ tests/test_provider.py
git commit -m "feat: LLM 适配层(平台预设/人话报错/测试连接)"
```

---

### Task 5: 本地服务与 API(app/server.py + 日志)

**Files:**
- Create: `app/server.py`, `app/logging_setup.py`, `tests/test_server.py`
- Modify: `app/main.py`(把"服务入口将在 Task 5 接通"换成真正的 `run_server`)

**Interfaces:**
- Consumes: `Config/load_config/save_config/mask_key`(Task 3)、`PRESETS`/`test_connection`(Task 4)
- Produces:
  - `create_app(data_dir: Path) -> flask.Flask`
  - `find_free_port(preferred: int) -> int`
  - `run_server(data_dir: Path, port: int = 8756, open_browser: bool = True) -> None`
  - `setup_logging(data_dir: Path) -> None`(轮转日志 `data/logs/app.log`,1MB × 3)
  - HTTP API:
    - `GET /api/status` → `{"version", "os", "has_key"}`
    - `GET /api/presets` → `[{"key","name","base_url","default_model"}]`
    - `GET /api/config` → `{"provider","base_url","model","api_key_masked","download_dir"}`(永不返回明文 Key)
    - `POST /api/config` → 保存;空 `api_key` 表示"不改";选了预设且地址/模型为空则用预设默认值补;返回 `{"ok": true, "api_key_masked": ...}`
    - `POST /api/test-connection` → `{"ok": bool, "message": str}`

- [ ] **Step 1: 写失败测试 `tests/test_server.py`**

```python
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
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_server.py -q`
Expected: FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现 `app/logging_setup.py`**

```python
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
```

- [ ] **Step 4: 实现 `app/server.py`**

```python
from __future__ import annotations

import logging
import socket
import sys
import threading
import webbrowser
from pathlib import Path

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
            "api_key_masked": mask_key(cfg.api_key),
            "download_dir": cfg.download_dir,
        })

    @app.post("/api/config")
    def api_save_config():
        body = request.get_json(force=True, silent=True) or {}
        cfg = load_config(data_dir)
        cfg.provider = str(body.get("provider", cfg.provider)).strip()
        cfg.base_url = str(body.get("base_url", cfg.base_url)).strip()
        cfg.model = str(body.get("model", cfg.model)).strip()
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


def run_server(data_dir: Path, port: int = 8756, open_browser: bool = True) -> None:
    setup_logging(data_dir)
    app = create_app(data_dir)
    real_port = find_free_port(port)
    url = f"http://127.0.0.1:{real_port}/"
    if real_port != port:
        log.info("端口 %s 被占用,改用 %s", port, real_port)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    log.info("小灶启动于 %s(数据目录 %s)", url, data_dir)
    print(f"小灶已启动:{url}")
    print("(关掉这个窗口就会退出)")
    app.run(host="127.0.0.1", port=real_port, debug=False, use_reloader=False)
```

- [ ] **Step 5: 修改 `app/main.py` 接上服务**

把 `--version` 分支之后的临时输出替换为:

```python
    from app.server import run_server

    run_server(data_dir, port=args.port, open_browser=not args.no_browser)
    return 0
```

- [ ] **Step 6: 跑全部测试,确认通过**

Run: `python -m pytest -q`
Expected: 之前所有测试 + 新增 7 条,全部 passed

- [ ] **Step 7: 手动冒烟(不开浏览器)**

Run: `python -m app.main --no-browser --port 8765`
然后另开一个终端:`curl.exe http://127.0.0.1:8765/api/status`(PowerShell 里用 `curl.exe`)
Expected: 返回含 `"version"` 的 JSON;Ctrl+C 停掉服务
注:此时 `/` 还 404(前端文件在 Task 6 建),属预期。

- [ ] **Step 8: 提交**

```bash
git add app/server.py app/logging_setup.py app/main.py tests/test_server.py
git commit -m "feat: 本地服务与 API(状态/配置/测试连接/日志/端口自动顺延)"
```

---

### Task 6: 前端三标签页 + 设置页

**Files:**
- Create: `app/web/index.html`, `app/web/app.js`, `app/web/style.css`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `GET /api/presets`、`GET /api/config`、`POST /api/config`、`POST /api/test-connection`(Task 5)
- Produces: 可视界面(三个标签;设置页可填、可存、可测);页面在浏览器里的完整验收留到 Task 9。

- [ ] **Step 1: 写失败测试 `tests/test_web.py`**

```python
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
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_web.py -q`
Expected: FAIL(404,文件还不存在)

- [ ] **Step 3: 实现 `app/web/index.html`**

```html
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>小灶</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header>
  <h1>小灶</h1>
  <nav>
    <button class="tab active" data-tab="course">课件助手</button>
    <button class="tab" data-tab="download">下载管家</button>
    <button class="tab" data-tab="settings">设置</button>
  </nav>
</header>
<main>
  <section class="panel active" id="panel-course">
    <p>课件助手还没接上——在下一个里程碑。</p>
  </section>
  <section class="panel" id="panel-download">
    <p>下载管家还没接上——再下一个里程碑。</p>
  </section>
  <section class="panel" id="panel-settings">
    <label>平台
      <select id="provider"></select>
    </label>
    <label>接口地址
      <input id="base-url" placeholder="https://.../v1">
    </label>
    <label>模型名
      <input id="model" placeholder="例如 kimi-k3">
    </label>
    <label>API Key
      <input id="api-key" type="password" placeholder="粘贴到这里(已存过就留空,表示不改)">
    </label>
    <div class="actions">
      <button id="btn-save">保存</button>
      <button id="btn-test">测试连接</button>
    </div>
    <p id="save-result"></p>
    <p id="test-result"></p>
  </section>
</main>
<script type="module" src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: 实现 `app/web/app.js`**

```javascript
async function api(path, opts) {
  const resp = await fetch(path, opts);
  return resp.json();
}

function show(id, text, ok) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = ok ? "ok" : "err";
}

// 标签切换
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + btn.dataset.tab));
  });
});

const sel = document.getElementById("provider");
const inputBase = document.getElementById("base-url");
const inputModel = document.getElementById("model");
const inputKey = document.getElementById("api-key");

const presets = await api("/api/presets");
for (const p of presets) {
  sel.append(new Option(p.name, p.key));
}

const cfg = await api("/api/config");
sel.value = cfg.provider || "openrouter";
inputBase.value = cfg.base_url || "";
inputModel.value = cfg.model || "";
if (cfg.api_key_masked) {
  inputKey.placeholder = "已保存:" + cfg.api_key_masked + "(留空 = 不改)";
}

sel.addEventListener("change", () => {
  const p = presets.find((x) => x.key === sel.value);
  if (p) {
    inputBase.value = p.base_url;
    inputModel.value = p.default_model;
  }
});

document.getElementById("btn-save").addEventListener("click", async () => {
  const body = {
    provider: sel.value,
    base_url: inputBase.value,
    model: inputModel.value,
    api_key: inputKey.value,
  };
  const r = await api("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  inputKey.value = "";
  inputKey.placeholder = "已保存:" + (r.api_key_masked || "未填") + "(留空 = 不改)";
  show("save-result", "已保存 ✔", true);
});

document.getElementById("btn-test").addEventListener("click", async () => {
  show("test-result", "测试中…", true);
  const r = await api("/api/test-connection", { method: "POST" });
  show("test-result", r.message, r.ok);
});
```

- [ ] **Step 5: 实现 `app/web/style.css`**

```css
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, "PingFang SC", "Microsoft YaHei", sans-serif;
  color: #222; background: #faf9f6;
}
header {
  display: flex; align-items: center; gap: 24px;
  padding: 16px 24px; border-bottom: 1px solid #e5e2da; background: #fff;
}
h1 { font-size: 20px; margin: 0; }
nav { display: flex; gap: 8px; }
.tab {
  font-size: 15px; padding: 8px 16px; border-radius: 8px;
  border: 1px solid #d8d4c8; background: #fff; cursor: pointer;
}
.tab.active { background: #2f6f4f; color: #fff; border-color: #2f6f4f; }
main { max-width: 720px; margin: 0 auto; padding: 24px; }
.panel { display: none; }
.panel.active { display: block; }
label { display: block; margin: 14px 0 6px; font-size: 14px; color: #555; }
input, select {
  display: block; width: 100%; margin-top: 6px;
  padding: 10px 12px; font-size: 15px;
  border: 1px solid #d8d4c8; border-radius: 8px; background: #fff;
}
.actions { margin-top: 18px; display: flex; gap: 12px; }
button { font-size: 15px; padding: 10px 20px; border-radius: 8px; cursor: pointer; }
#btn-save { background: #2f6f4f; color: #fff; border: none; }
#btn-test { background: #fff; border: 1px solid #d8d4c8; }
.ok { color: #2f6f4f; }
.err { color: #b23b2e; white-space: pre-wrap; }
```

- [ ] **Step 6: 跑测试,确认通过**

Run: `python -m pytest -q`
Expected: 全部 passed

- [ ] **Step 7: 浏览器手动过一遍(开发机)**

Run: `python -m app.main`(会自己开浏览器)
检查:三个标签能点;设置页选平台会自动填地址和模型;填一个**故意错的** Key → 保存 → 测试连接 → 应显示人话报错(「Key 不对或已过期…」或「连不上…」),不是英文。
说明:开发机在中国大陆,直连 OpenRouter 可能连不上——「连不上 http://…」也是**正确**结果;如果能开代理想测成功路径,在系统代理开着的情况下再试一次。

- [ ] **Step 8: 提交**

```bash
git add app/web/ tests/test_web.py
git commit -m "feat: 前端三标签页与设置页(平台预设/保存/测试连接)"
```

---

### Task 7: 启动器(start.command / 启动小灶.bat)+ --self-test

**Files:**
- Create: `start.command`, `启动小灶.bat`
- Modify: `app/main.py`(增加 `--self-test`)

**Interfaces:**
- Consumes: `create_app` / `find_free_port`(Task 5)
- Produces: `python -m app.main --self-test`(起来 → 请求 `/api/status` → 打印「自检通过」→ 退出 0;失败退出 1)。CI 冒烟(Task 8)也用它。

- [ ] **Step 1: 给 `app/main.py` 加 `--self-test`**

argparse 增加一行:

```python
    parser.add_argument("--self-test", action="store_true", help="启动服务自检一轮后退出(给 CI 和启动器用)")
```

在 `--version` 分支后面加:

```python
    if args.self_test:
        return _run_self_test(data_dir)
```

并新增函数:

```python
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
```

- [ ] **Step 2: 写 `start.command`(Mac 双击入口)**

```bash
#!/bin/bash
# 小灶 · Mac 启动器(双击运行)
cd "$(dirname "$0")" || exit 1
PY=./python/bin/python3
[ -x "$PY" ] || PY=$(command -v python3 || command -v python || command -v py)
if [ -z "$PY" ]; then
  echo "没找到 Python——请把整个文件夹按说明重新解压一次。"
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi
"$PY" -m app.main "$@"
echo
read -n 1 -s -r -p "小灶已退出。按任意键关闭此窗口…"
```

- [ ] **Step 3: 写 `启动小灶.bat`(Windows 双击入口)**

```bat
@echo off
cd /d "%~dp0"
set PY=python
if exist python\python.exe set PY=python\python.exe
%PY% -m app.main %*
echo.
echo 小灶已退出。
pause
```

- [ ] **Step 4: 开发机跑两个启动器的自检路径**

Run(Git Bash):`bash -n start.command && bash start.command --self-test`
Expected: 输出「自检通过:服务已起来,/api/status 正常」,随后退出
Run(PowerShell):`cmd /c 启动小灶.bat --self-test`
Expected: 同上
注:脚本里的引号(`cd "$(dirname "$0")"`、`%~dp0`)就是"路径带空格/中文"的保险;Mac 真机行为在 Task 9 验收。

- [ ] **Step 5: 记录可执行位并提交**

```bash
git add app/main.py start.command 启动小灶.bat
git update-index --chmod=+x start.command
git commit -m "feat: 双平台启动器与 --self-test(CI 冒烟共用)"
```

---

### Task 8: Mac 打包 + CI 出包冒烟

**Files:**
- Create: `scripts/build_macos.sh`, `.github/workflows/build-macos.yml`

**Interfaces:**
- Consumes: `start.command`(Task 7)、`--self-test`(Task 7)、`requirements.txt`(Task 1)
- Produces: GitHub Actions artifact `xiaozhao-macos-arm64`(内含 `xiaozhao-macos-arm64.tar.gz`)。

- [ ] **Step 1: 写 `scripts/build_macos.sh`(在 macOS runner 上执行)**

```bash
#!/usr/bin/env bash
# 在 macOS(GitHub Actions macos-15,arm64)上组装交付包并冒烟测试
set -euo pipefail

PY_TAG="20261003"   # 若下载 404:去 python-build-standalone releases 页换最新 tag(版本号 PBS_VER 也要跟着改)
PBS_VER="3.13.16+20261003"
ASSET="cpython-${PBS_VER}-aarch64-apple-darwin-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_TAG}/${ASSET}"

rm -rf dist
mkdir -p dist/xiaozhao
curl -fsSL "$URL" -o pbs.tar.gz
tar -xzf pbs.tar.gz -C dist/xiaozhao          # 解出 python/ 目录

./dist/xiaozhao/python/bin/python3 -m pip install --upgrade pip
./dist/xiaozhao/python/bin/python3 -m pip install -r requirements.txt

cp -R app requirements.txt start.command dist/xiaozhao/
chmod +x dist/xiaozhao/start.command dist/xiaozhao/python/bin/python3

# 冒烟 1:能 import;冒烟 2:服务能起来、/api/status 有回应
(cd dist/xiaozhao \
  && ./python/bin/python3 -c "import app, flask, requests; print('import ok')" \
  && ./python/bin/python3 -m app.main --self-test)

tar -czf xiaozhao-macos-arm64.tar.gz -C dist xiaozhao
echo "--- 确认权限位(start.command 与 python3 应为 rwxr-xr-x)---"
tar -tvzf xiaozhao-macos-arm64.tar.gz | grep -E "start.command|bin/python3$" || true
ls -lh xiaozhao-macos-arm64.tar.gz
```

- [ ] **Step 2: 写 `.github/workflows/build-macos.yml`**

```yaml
name: build-macos
on:
  push:
    branches: [main]
  workflow_dispatch:
jobs:
  build:
    runs-on: macos-15
    steps:
      - uses: actions/checkout@v4
      - name: 组装 + 冒烟
        run: bash scripts/build_macos.sh
      - name: 上传产物
        uses: actions/upload-artifact@v4
        with:
          name: xiaozhao-macos-arm64
          path: xiaozhao-macos-arm64.tar.gz
```

注:若 CI 提示 action 版本过旧,按提示升 tag 即可。

- [ ] **Step 3: 开发机语法检查**

Run(Git Bash):`bash -n scripts/build_macos.sh`
Expected: 无输出(语法通过)

- [ ] **Step 4: 提交**

```bash
git add scripts/build_macos.sh .github/workflows/build-macos.yml
git commit -m "build: Mac 打包脚本与 CI 出包冒烟(macos-15)"
```

- [ ] **Step 5: 建远端并推上去(和用户一起做,先把这三件事问清楚)**

1. 问用户:仓库名(建议 `xiaozhao`)、可见性(公开 = CI 分钟数免费且无限;私有 = 也行,但 macOS runner 按 10 倍计分钟)。
2. 用户在 GitHub 建好空仓库后,本地执行(大陆需走代理):

```bash
git branch -M main   # 分支名统一叫 main(CI 的触发条件写的就是 main)
git -c http.proxy=http://127.0.0.1:7897 remote add origin https://github.com/<用户名>/<仓库名>.git
git -c http.proxy=http://127.0.0.1:7897 push -u origin main
```

3. 打开仓库的 Actions 页,等 `build-macos` 跑完:应全绿,artifact 里有 `xiaozhao-macos-arm64.tar.gz`。
Expected: 日志里能看到 `import ok` 与 `自检通过`;`tar -tvzf` 那两行权限位是 `rwxr-xr-x`。

---

### Task 9: M1 验收(用户执行)

**对应规格 §5 的 M1 通过线。**

- [ ] Windows 侧:双击 `启动小灶.bat` → 浏览器自动打开 → 三个标签页都在 → 设置页填 Key/选平台 → 保存 → 「测试连接」
  - 预期:要么显示「连接成功」(系统代理开着、能到该平台时),要么显示**人话**报错(「连不上 http://…」)——两种都是合格结果;出现英文栈或白屏 = 不通过。
- [ ] 故意把 Key 改错(如乱敲几个字符)→ 测试连接 → 应显示「Key 不对或已过期…」
- [ ] 把文件夹复制到一个**带空格和中文**的路径(如 `C:\Users\Sneeuw\Desktop\我的 小灶\`)再双击,重复上一行——行为应一致。
- [ ] Mac 侧(免真机部分):确认 GitHub Actions 最新一次跑绿;下载 artifact,`tar -tvzf` 看 `start.command` 与 `python/bin/python3` 的权限位;把 `Mac 自检.command` 发给朋友,要回 `Mac自检-输出.txt`。
- [ ] 记录结果(截图/文字)发给 Claude。通过 → 拆 M2(课件助手)计划。

---

## 后续计划(不在本计划内,按顺序各写各的)

- **M2 课件助手**:入库、解析三层(PyMuPDF→视觉→MinerU 预留)、parse-once 缓存、长上下文问答与页码引用、课件页 UI。
- **M3 下载管家**:引擎插件接口、yt-dlp/gallery-dl 封装、自研薄层(页面找原图)、侦察→勾选→下载 → 归档、护栏。
- **M4 给朋友装**:一页操作卡、API 注册指南、更新通道(检查更新)、curl 安装、Mac 真机验收全表。
