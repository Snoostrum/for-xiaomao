# 小灶 M2「课件助手能答」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「课件助手」真正能用:PDF 入库 → 三层解析(本地抽字;扫描页走视觉模型;MinerU 只留接口)→ 答案带页码引用的问答;解析只跑一次、有缓存;用量可查。顺带把 M1 攒下的口子(跨站防护、400/编码话术、预设缺失)收干净。

**Architecture:** 在现有 Flask 本地服务上加一个 `app/courseware/` 域:`store`(按内容哈希命名的课件库)、`parse`(逐页落盘、meta.json 即"完成标记"、断了可续)、`qa`(全文进长上下文、页码引用、超长人话拦截)。provider 增加 `chat_completion_full` 返回平台给的用量;新增 `app/usage.py` 记本机小账本;配置增加可选 `vision_model`。写接口统一加 Origin 守卫。前端在「课件助手」面板加:上传、列表、解析进度轮询、提问。

**Tech Stack:** Python 3.12/3.13、Flask、requests、**PyMuPDF(pymupdf)**、pytest;前端继续无框架原生 HTML/JS/CSS;打包继续 PyInstaller(Windows)+ python-build-standalone(macOS)。

**Spec:** `docs/superpowers/specs/2026-10-06-xiaozhao-design.md`。本计划实现它的 **M2 里程碑**(§5 表第二行:「课件助手能答」),并处理复审攒下的口子(见各任务)。M3 下载管家、M4 交付各自另写。

**执行环境:** 开发机 = Windows 11(用户机器);`python`/`pytest`/`git` 命令在 PowerShell 里跑;CI 双平台(build-windows = windows-latest;build-macos = macos-15)。装依赖用清华源。

## Global Constraints

- 服务只绑 `127.0.0.1`;所有文件读写显式 `encoding="utf-8"`;路径只用 `pathlib`。
- 运行时依赖 = **flask、requests、pymupdf**;不引入其他新三方包(测试仍只用 pytest)。装新包用 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。
- 面向用户的错误一律"人话"中文(细节写日志);**新接口出错 = 非 2xx + `{"ok": false, "message": 人话}``**,跨站请求 403。
- 新增数据全部落 `data/` 下:`courses/`(课件原件)、`cache/<16位哈希>/`(解析缓存)、`usage.jsonl`(用量账本);程序目录与 data 的分离规矩不变。
- 关键常量(照抄,勿自行改值):`SCANNED_TEXT_THRESHOLD=20`、`RENDER_DPI=150`、`PARSE_VERSION=1`、`MAX_UPLOAD_BYTES=200MB`、`MAX_CORPUS_CHARS=200000`、`VISION_MAX_TOKENS=4096`、`VISION_TIMEOUT=120.0`、`ASK_MAX_TOKENS=2048`、`ASK_TIMEOUT=180.0`。
- 模型名/地址/价格继续走配置与预设,不散落进业务代码;平台标 `# 需核实` 的值动手当天复核。
- 前端无框架、无构建步骤;新 CSS 只追加不改旧样式;中文注释、注释说"为什么"。
- 每个任务结束提交一次 git(`feat:/fix:/test:/docs:` 前缀);提交信息末尾带一行 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。
- 每次推 main 双平台 CI 都要保持绿;红了先修再往下。

## Review Focus

1. **同一份课件重复上传(改了文件名)**:期望认成同一份(内容哈希),不建第二份、不重复解析、不重复花钱。(Task 6 / Task 7 的测试)
2. **坏 PDF / 空 PDF / 加密 PDF**:期望"人话"说明并保留已有课件,不是英文栈、不是永久卡死。(Task 7 的测试)
3. **解析到一半退出、或人为删掉一半缓存**:期望重开点「解析」能接着跑(已抽过的页不重抽、不重复花钱),完成后 meta 照常落定。(Task 7 的测试)
4. **Key / 接口地址含非 ASCII 字符**:期望返回人话提示(而不是 Flask 500 或 UnicodeEncodeError 栈)。(Task 2 的测试)
5. **模型返回空回答 / 平台没给 usage**:期望界面显示人话而不是一片空白;用量账本照记一笔(次数不丢)。(Task 9 / Task 5 的测试)

---

### Task 1: 安全收口——Origin 守卫 + 非对象 body→400

**Files:**
- Modify: `app/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: 现有 `create_app(data_dir)` 结构。
- Produces: 全局 `before_request` 守卫:POST/PUT/DELETE 带 `Origin` 头且主机不是 `127.0.0.1`/`localhost` → 403 `{"ok": false, "message": ...}`(不带 Origin 的请求放行——curl 与测试不受影响)。`POST /api/config` 对非 JSON、非对象 body → 400 `{"ok": false, "message": ...}`。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_server.py`)**

```python
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
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_server.py -q`
Expected: 4 条新测试 FAIL(非对象 body 500 / text/plain 也可能 200 / 跨站没拦 / 无所谓)。

- [ ] **Step 3: 实现(`app/server.py`)**

顶部 import 区加一行:

```python
from urllib.parse import urlparse
```

`create_app()` 里 `web_dir = ...` 之后加守卫(位置在全部路由之前没关系,`before_request` 是请求时跑):

```python
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
```

`api_save_config` 的 body 解析改成:

```python
    @app.post("/api/config")
    def api_save_config():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "message": "请求格式不对(需要 JSON 对象)——请在页面上操作。"}), 400
        cfg = load_config(data_dir)
        # ……以下保持原样(cfg.provider = str(body.get(...)) 那几行不改)
```

- [ ] **Step 4: 跑测试,确认全过**

Run: `python -m pytest tests/test_server.py -q`(再补一发全量:`python -m pytest -q`)
Expected: 全过;原有测试不受影响(测试客户端不带 Origin)。

- [ ] **Step 5: 提交**

```bash
git add app/server.py tests/test_server.py
git commit -m "fix: 写接口加 Origin 守卫;非对象 JSON 体返回 400(口子①④)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: provider 话术与边界——400 人话、非 ASCII 不 500、full 版本带用量

**Files:**
- Create: `app/errors.py`
- Modify: `app/llm/provider.py`
- Test: `tests/test_provider.py`

**Interfaces:**
- Consumes: 现有 `_post_chat`、`chat_completion`、`test_connection`。
- Produces: `app.errors.HumanError(human, detail)`(带人话的异常基类);`app.llm.provider.LLMError` 改为它的子类(构造签名不变,现有代码/测试照旧);`chat_completion_full(cfg, messages, max_tokens=1024, timeout=60.0) -> tuple[str, dict]` 返回 (正文, usage);`chat_completion` 变成它的薄包装。HTTP 400 → 人话「模型名或请求内容」口径;非 latin-1 的 Key/地址 → 人话。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_provider.py`)**

```python
from app.llm.provider import chat_completion_full  # 加到文件头部的 import 区

def test_400_tells_user_model_name_or_content():
    with FakeLLM(status=400) as fake:
        ok, msg = test_connection(cfg_for(fake))
        assert ok is False
        assert "400" in msg and "模型名" in msg  # 口径:模型名或请求内容,别一口咬死


def test_404_tells_user_url_or_model():
    with FakeLLM(status=404) as fake:
        ok, msg = test_connection(cfg_for(fake))
        assert ok is False and "接口地址" in msg


def test_500_says_platform_side_error():
    with FakeLLM(status=500) as fake:
        ok, msg = test_connection(cfg_for(fake))
        assert ok is False and "对方服务器" in msg


def test_non_latin1_key_gets_human_message_not_crash():
    # 口子⑧:Key 里混进中文/表情 → http.client 编码炸 → 以前是 Flask 500,现在是测试连接的人话
    with FakeLLM() as fake:
        cfg = cfg_for(fake)
        cfg.api_key = "sk-密钥"
        ok, msg = test_connection(cfg)
        assert ok is False and "字符" in msg


def test_chat_completion_full_returns_usage():
    body = {"choices": [{"message": {"content": "收到"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
    with FakeLLM(body=body) as fake:
        text, usage = chat_completion_full(cfg_for(fake), [{"role": "user", "content": "hi"}])
        assert text == "收到"
        assert usage["prompt_tokens"] == 3


def test_chat_completion_full_missing_usage_gives_empty_dict():
    with FakeLLM() as fake:  # 默认 body 不带 usage
        _text, usage = chat_completion_full(cfg_for(fake), [{"role": "user", "content": "hi"}])
        assert usage == {}
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_provider.py -q`
Expected: 新测试 FAIL(400 落进"没见过的错误"、编码报错直接抛、没有 `chat_completion_full`)。

- [ ] **Step 3: 实现**

`app/errors.py`(新文件):

```python
from __future__ import annotations


class HumanError(Exception):
    """带人话的异常:界面上展示 human,细节留给日志/排查。"""

    def __init__(self, human: str, detail: str = ""):
        super().__init__(human)
        self.human = human
        self.detail = detail
```

`app/llm/provider.py`:
- 顶部加 `from app.errors import HumanError`,并让 `LLMError` 继承它:

```python
class LLMError(HumanError):
    """调用模型失败的统一异常。构造签名与以前一致:(人话, 细节)。"""
```

- `_post_chat` 的异常链里,在通用 `RequestException` **之前**插入编码类分支,并在 403 与 404 之间插入 400 分支:

```python
    except (requests.exceptions.InvalidHeader, requests.exceptions.InvalidURL, UnicodeEncodeError) as e:
        raise LLMError(
            "『Key』或『接口地址』里有奇怪的字符(编码不对)——检查有没有混进表情或特殊符号。",
            f"{e!r} | {url}",
        )
    except requests.exceptions.RequestException as e:
        # ……(原有的通用分支,保持不动)
```

```python
    if resp.status_code == 400:
        raise LLMError(
            "平台说这个请求不对(400)——常见原因是『模型名』填错了(也可能是请求内容有问题)。去「设置」里核对一下。",
            resp.text[:300],
        )
```

- 把 `chat_completion` 拆成两半:

```python
def _extract_text(data: dict) -> str:
    try:
        # content 偶尔是 null(只有推理没有正文),别把 None 当回复带出去
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError("回应里没有文本内容——可能模型名不对。", str(data)[:300])


def chat_completion_full(cfg: Config, messages: list[dict], max_tokens: int = 1024, timeout: float = 60.0) -> tuple[str, dict]:
    """返回 (正文, 用量)。用量给「成本可见」用;平台没给就给空 dict。"""
    data = _post_chat(cfg, {"model": cfg.model, "messages": messages, "max_tokens": max_tokens}, timeout)
    return _extract_text(data), (data.get("usage") or {})


def chat_completion(cfg: Config, messages: list[dict], max_tokens: int = 1024, timeout: float = 60.0) -> str:
    return chat_completion_full(cfg, messages, max_tokens=max_tokens, timeout=timeout)[0]
```

- [ ] **Step 4: 跑测试,确认全过**

Run: `python -m pytest tests/test_provider.py -q`(再全量 `python -m pytest -q`)
Expected: 全过;原 8 条不受影响。

- [ ] **Step 5: 提交**

```bash
git add app/errors.py app/llm/provider.py tests/test_provider.py
git commit -m "fix: 400 与人话同口径;非 ASCII Key 不再 500;provider 增加带用量的 full 版本(口子③⑧⑪)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 配置加固——provider 不写空、预设失败保表单、DeepSeek 预设、vision_model 字段

**Files:**
- Modify: `app/config.py`、`app/llm/presets.py`、`app/server.py`、`app/web/index.html`、`app/web/app.js`
- Test: `tests/test_config.py`、`tests/test_server.py`、`tests/test_web.py`

**Interfaces:**
- Produces: `Config.vision_model: str = ""`(空 = 跟主模型一样);`GET/POST /api/config` 均含 `vision_model`;POST 时 body 里 `provider` 为空字符串 → **保留**已存的平台(不再写空)。预设表新增 `deepseek`。前端:平台列表或已存配置取不到时禁用「保存/测试连接」并说人话。

- [ ] **Step 1: 写失败测试**

`tests/test_config.py` — 改 `test_roundtrip` 带上新字段:

```python
def test_roundtrip(tmp_path):
    cfg = Config(provider="openrouter", base_url="https://x/v1", api_key="sk-abc", model="m",
                 vision_model="vm", download_dir="")
    save_config(tmp_path, cfg)
    assert load_config(tmp_path) == cfg
```

`tests/test_server.py` — 追加:

```python
def test_post_config_blank_provider_keeps_stored(tmp_path):
    # 口子⑤:前端没加载全时会把 provider 发成空——不能把人已存的平台抹掉
    save_config(tmp_path, Config(provider="kimi", api_key="sk-old", base_url="https://x/v1", model="m"))
    r = make_client(tmp_path).post("/api/config", json={"provider": "", "api_key": "", "base_url": "https://x/v1", "model": "m"})
    assert r.status_code == 200
    assert load_config(tmp_path).provider == "kimi"


def test_vision_model_roundtrip(tmp_path):
    c = make_client(tmp_path)
    c.post("/api/config", json={"provider": "custom", "base_url": "https://x/v1", "model": "m", "vision_model": " vm "})
    assert load_config(tmp_path).vision_model == "vm"
    assert c.get("/api/config").get_json()["vision_model"] == "vm"
```

`tests/test_web.py` — 改预设测试并追加:

```python
def test_presets_endpoint_lists_platforms(tmp_path):
    data = make_client(tmp_path).get("/api/presets").get_json()
    keys = [p["key"] for p in data]
    assert "openrouter" in keys and "kimi" in keys and "deepseek" in keys and "custom" in keys


def test_settings_has_vision_model_field(tmp_path):
    html = make_client(tmp_path).get("/").get_data(as_text=True)
    assert 'id="vision-model"' in html
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_config.py tests/test_server.py tests/test_web.py -q`
Expected: 新断言 FAIL(Config 没这个字段 / provider 被写空 / 没有 deepseek / 页面没这个输入框)。

- [ ] **Step 3: 实现**

`app/config.py`:字段与 strip 列表都加 `vision_model`:

```python
_STRIP_FIELDS = ("provider", "base_url", "api_key", "model", "vision_model", "download_dir")


@dataclass
class Config:
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    vision_model: str = ""  # 看扫描页用的模型;留空 = 和主模型相同
    download_dir: str = ""
```

`app/llm/presets.py` — 在 `custom` 之前加(2026-10-06 在用户机器实测可用):

```python
    "deepseek": Preset(
        key="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-flash",  # deepseek-chat 仍是别名;以平台当天文档为准
    ),
```

`app/server.py` — `api_get_config` 的 jsonify 里加 `"vision_model": cfg.vision_model,`;`api_save_config` 里改两处:

```python
        new_provider = str(body.get("provider", "")).strip()
        if new_provider:  # 空 = 不改动已保存的平台(前端没加载全时,别把人配置抹掉)
            cfg.provider = new_provider
        if "vision_model" in body:
            cfg.vision_model = str(body.get("vision_model") or "").strip()
```

(原来 `cfg.provider = str(body.get("provider", cfg.provider)).strip()` 那一行删掉,其余字段照旧。)

`app/web/index.html` — 设置面板里「模型名」之后加一个字段;并把「接口地址」的提示改清楚:

```html
    <label>接口地址
      <input id="base-url" placeholder="如 https://api.deepseek.com/v1(填平台的接口地址,不是网页地址)">
    </label>
    <label>模型名
      <input id="model" placeholder="例如 deepseek-flash">
    </label>
    <label>视觉模型(看扫描页用;留空 = 和上面模型相同)
      <input id="vision-model" placeholder="可不填">
    </label>
```

`app/web/app.js` — 三处小改:
1. 加 `const inputVision = document.getElementById("vision-model");`
2. 顶部加载段拆成两段 try,各自失败都要说人话,且**任一失败就禁用保存/测试按钮**:

```js
let presets = [];
const loadErrors = [];
try {
  presets = await api("/api/presets");
  for (const p of presets) {
    sel.append(new Option(p.name, p.key));
  }
} catch (e) {
  loadErrors.push(e.message);
}

try {
  const cfg = await api("/api/config");
  if (cfg.provider && !presets.some((p) => p.key === cfg.provider)) {
    sel.append(new Option(cfg.provider + "(列表里没有,保留原样)", cfg.provider));
  }
  sel.value = cfg.provider || "openrouter";
  inputBase.value = cfg.base_url || "";
  inputModel.value = cfg.model || "";
  inputVision.value = cfg.vision_model || "";
  if (cfg.api_key_masked) {
    inputKey.placeholder = "已保存:" + cfg.api_key_masked + "(留空 = 不改)";
  }
} catch (e) {
  loadErrors.push(e.message);
}

if (loadErrors.length) {
  // 口子⑥:表单没加载全时别让保存/测试可点——否则一按就把已存配置写成空白
  document.getElementById("btn-save").disabled = true;
  document.getElementById("btn-test").disabled = true;
  show("save-result", loadErrors.join("\n") + "\n(刷新页面再试;先别保存,免得把已有配置覆盖成空白。)", false);
}
```

3. `saveForm()` 的 body 加一行 `vision_model: inputVision.value,`。

- [ ] **Step 4: 跑测试,确认全过 + 手动过一眼设置页**

Run: `python -m pytest tests/test_config.py tests/test_server.py tests/test_web.py -q`
再手动:`python -m app.main --no-browser --port 8760 --data-dir data` → 浏览器开 `http://127.0.0.1:8760/` → 设置页能看到「视觉模型」输入框、平台下拉里有 DeepSeek;断网刷新(或临时改 `/api/presets` 请求看 devtools)时保存按钮应被禁用。

- [ ] **Step 5: 提交**

```bash
git add app/config.py app/llm/presets.py app/server.py app/web/index.html app/web/app.js tests/test_config.py tests/test_server.py tests/test_web.py
git commit -m "feat: 设置加视觉模型与 DeepSeek 预设;平台不写空、表单加载失败禁保存(口子⑤⑥⑩)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 启动器问候语

**Files:**
- Modify: `启动小灶.bat`、`start.command`

**Interfaces:**
- Produces: 双击后窗口第一行就是「正在启动小灶…」——空白等待期不再让人以为没反应(候选口子⑨)。

- [ ] **Step 1: 改两个启动器**

`启动小灶.bat` — 在 `cd /d "%~dp0"` 之后、`set PY=python` 之前插一行(必须在 `chcp 65001` 之后,不然中文乱码):

```bat
echo 正在启动小灶…(服务起来后浏览器会自动打开;这个窗口别关)
```

`start.command` — 在 `PY=./python/bin/python3` 那行之前插一行:

```bash
echo "正在启动小灶…(服务起来后浏览器会自动打开;这个窗口别关)"
```

两个文件都保持**原编码不动**(bat 为 UTF-8、`chcp 65001` 已就位)。

- [ ] **Step 2: 验证**

Run: 双击 `启动小灶.bat`(或 PowerShell 里 `cmd /c 启动小灶.bat`)→ 第一行就应看到问候语,随后浏览器打开。
再跑一发自检确认没碰坏:`python -m app.main --self-test`。
Expected: 问候语在、自检通过。

- [ ] **Step 3: 提交**

```bash
git add 启动小灶.bat start.command
git commit -m "feat: 双击启动先报一句'正在启动'(口子⑨)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: 用量账本——app/usage.py + /api/usage

**Files:**
- Create: `app/usage.py`
- Modify: `app/server.py`
- Test: `tests/test_usage.py`(新建)、`tests/test_server.py`

**Interfaces:**
- Produces: `record_usage(data_dir: Path, purpose: str, model: str, usage: dict | None) -> None`(追加一行到 `data/usage.jsonl`;平台没给 usage 也记一笔、token 记 0);`usage_totals(data_dir) -> dict` 返回 `{"calls": int, "prompt_tokens": int, "completion_tokens": int}`(坏行跳过)。`GET /api/usage` 返回同一结构。

- [ ] **Step 1: 写失败测试**

`tests/test_usage.py`(新文件):

```python
from app.usage import record_usage, usage_totals


def test_record_and_total(tmp_path):
    record_usage(tmp_path, "提问", "m", {"prompt_tokens": 120, "completion_tokens": 30})
    record_usage(tmp_path, "看扫描页", "m", None)  # 平台没给用量也要记一笔次数
    t = usage_totals(tmp_path)
    assert t == {"calls": 2, "prompt_tokens": 120, "completion_tokens": 30}


def test_totals_on_missing_file_is_zero(tmp_path):
    assert usage_totals(tmp_path) == {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def test_bad_line_is_skipped(tmp_path):
    record_usage(tmp_path, "提问", "m", {"prompt_tokens": 1, "completion_tokens": 1})
    with (tmp_path / "usage.jsonl").open("a", encoding="utf-8") as f:
        f.write("这不是 json\n")
    assert usage_totals(tmp_path)["calls"] == 1
```

`tests/test_server.py` — 追加:

```python
def test_usage_endpoint_reports_totals(tmp_path):
    from app.usage import record_usage

    record_usage(tmp_path, "提问", "m", {"prompt_tokens": 5, "completion_tokens": 5})
    data = make_client(tmp_path).get("/api/usage").get_json()
    assert data["calls"] == 1 and data["prompt_tokens"] == 5
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_usage.py -q`
Expected: FAIL(No module named 'app.usage')。

- [ ] **Step 3: 实现**

`app/usage.py`(新文件):

```python
"""用量小账本:每次问模型花了多少 token,记在本机(data/usage.jsonl),给「成本可见」用。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _usage_path(data_dir: Path) -> Path:
    return data_dir / "usage.jsonl"


def record_usage(data_dir: Path, purpose: str, model: str, usage: dict | None) -> None:
    """追加一条用量。平台没回 usage 也记一笔(次数照算、token 记 0)——别让账本漏次。"""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "purpose": purpose,
        "model": model,
        "prompt_tokens": int((usage or {}).get("prompt_tokens") or 0),
        "completion_tokens": int((usage or {}).get("completion_tokens") or 0),
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with _usage_path(data_dir).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:  # 记账失败不能把正事搞砸
        log.warning("用量记录失败:%s", e)


def usage_totals(data_dir: Path) -> dict:
    """汇总全本账。坏行跳过,不因一行脏数据全盘失败。"""
    calls = prompt = completion = 0
    p = _usage_path(data_dir)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            calls += 1
            prompt += int(e.get("prompt_tokens") or 0)
            completion += int(e.get("completion_tokens") or 0)
    return {"calls": calls, "prompt_tokens": prompt, "completion_tokens": completion}
```

`app/server.py`:顶部 `from app.usage import usage_totals`,并加路由:

```python
    @app.get("/api/usage")
    def api_usage():
        return jsonify(usage_totals(data_dir))
```

- [ ] **Step 4: 跑测试,确认全过**

Run: `python -m pytest tests/test_usage.py tests/test_server.py -q`
Expected: 全过。

- [ ] **Step 5: 提交**

```bash
git add app/usage.py app/server.py tests/test_usage.py tests/test_server.py
git commit -m "feat: 本机用量账本与 /api/usage(成本可见)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 课件库 store——按内容哈希入库,天然去重

**Files:**
- Create: `app/courseware/__init__.py`、`app/courseware/store.py`
- Test: `tests/test_store.py`(新建)

**Interfaces:**
- Consumes: `app.errors.HumanError`(Task 2)。
- Produces: `app.courseware.CoursewareError`(人话异常,后续 Task 8/9/10 全用它);路径规则 `courses_dir(data_dir)`、`course_file(data_dir, course_id)`(校验 id、挡路径穿越)、`course_meta_file(...)`、`cache_dir(data_dir, course_id)`、`page_md(cache, n)`(→ `pages/001.md`);store 操作 `save_upload(data_dir, stream, filename) -> tuple[str, bool]`(返回 (课件id, 是否新入库))、`list_courses(data_dir) -> list[dict]`(每项 `{id, name, added_at, size}`,新的在前)、`delete_course(data_dir, course_id) -> None`。

- [ ] **Step 1: 写失败测试(`tests/test_store.py` 新文件)**

```python
import io
import json

import pytest

from app.courseware import CoursewareError, course_file, course_meta_file
from app.courseware.store import delete_course, list_courses, save_upload

PDF_A = b"%PDF-1.4 这是一份假 PDF,store 只验魔数不解析"
PDF_B = b"%PDF-1.4 另一份内容不同的假 PDF"


def upload(data_dir, content: bytes, name: str):
    return save_upload(data_dir, io.BytesIO(content), name)


def test_same_content_different_name_is_one_course(tmp_path):
    # Review Focus #1 的第一道闸:内容一样(改了名)→ 同一份,不建第二条
    cid1, new1 = upload(tmp_path, PDF_A, "讲义.pdf")
    cid2, new2 = upload(tmp_path, PDF_A, "讲义-最终版(1).pdf")
    assert new1 is True and new2 is False
    assert cid1 == cid2
    assert len(list_courses(tmp_path)) == 1
    assert not list((tmp_path / "courses").glob("*.part"))  # 临时文件不残留


def test_different_content_is_second_course(tmp_path):
    cid1, _ = upload(tmp_path, PDF_A, "a.pdf")
    cid2, _ = upload(tmp_path, PDF_B, "b.pdf")
    assert cid1 != cid2 and len(list_courses(tmp_path)) == 2


def test_non_pdf_rejected_and_nothing_left(tmp_path):
    with pytest.raises(CoursewareError) as ei:
        upload(tmp_path, b"JFIF 这是一张图片", "照片.pdf")
    assert "PDF" in str(ei.value)
    assert list_courses(tmp_path) == []
    assert not list((tmp_path / "courses").glob("*"))  # 坏的也不留垃圾


def test_list_shows_newest_first(tmp_path):
    cid1, _ = upload(tmp_path, PDF_A, "老的.pdf")
    cid2, _ = upload(tmp_path, PDF_B, "新的.pdf")
    meta = json.loads(course_meta_file(tmp_path, cid1).read_text(encoding="utf-8"))
    meta["added_at"] = "2026-01-01T00:00:00"  # 同一秒上传分不出先后,把老的改成"昨天"
    course_meta_file(tmp_path, cid1).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    assert [c["id"] for c in list_courses(tmp_path)] == [cid2, cid1]
    assert list_courses(tmp_path)[1]["name"] == "老的.pdf"


def test_delete_removes_files_and_cache(tmp_path):
    cid, _ = upload(tmp_path, PDF_A, "讲义.pdf")
    cache = tmp_path / "cache" / cid
    cache.mkdir(parents=True)
    (cache / "占位.txt").write_text("x", encoding="utf-8")
    delete_course(tmp_path, cid)
    assert list_courses(tmp_path) == []
    assert not course_file(tmp_path, cid).exists()
    assert not cache.exists()


def test_bad_course_id_is_rejected(tmp_path):
    # 编号来自网址,必须只认 16 位十六进制——../../ 这类穿越直接人话拒绝
    with pytest.raises(CoursewareError):
        course_file(tmp_path, "../../etc/passwd")
    with pytest.raises(CoursewareError):
        delete_course(tmp_path, "Z" * 16)
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_store.py -q`
Expected: FAIL(`No module named 'app.courseware'`)。

- [ ] **Step 3: 实现**

`app/courseware/__init__.py`(新文件):

```python
"""课件助手:课件库(store)、解析(parse)、问答(qa)。

这里放三块共用的路径规则与错误类型:
- 课件原件:data/courses/<16位内容哈希>.pdf —— 内容相同就是同一份(天然去重)
- 解析缓存:data/cache/<同一个 id>/(pages/ 逐页 Markdown,img/ 留给扫描页渲染图)
"""

from __future__ import annotations

import re
from pathlib import Path

from app.errors import HumanError

_ID_RE = re.compile(r"^[0-9a-f]{16}$")


class CoursewareError(HumanError):
    """课件流程里说给用户听的人话错误;server 统一翻成 400 + message。"""


def check_course_id(course_id: str) -> str:
    """课件 id 只认 16 位小写十六进制——顺带挡住 ../ 这类路径穿越。"""
    if not _ID_RE.match(course_id or ""):
        raise CoursewareError("课件编号不对——刷新页面再试。")
    return course_id


def courses_dir(data_dir: Path) -> Path:
    return data_dir / "courses"


def course_file(data_dir: Path, course_id: str) -> Path:
    return courses_dir(data_dir) / f"{check_course_id(course_id)}.pdf"


def course_meta_file(data_dir: Path, course_id: str) -> Path:
    return courses_dir(data_dir) / f"{check_course_id(course_id)}.json"


def cache_dir(data_dir: Path, course_id: str) -> Path:
    return data_dir / "cache" / check_course_id(course_id)


def page_md(cache: Path, n: int) -> Path:
    """第 n 页的 Markdown 文件。页号补零只为了在文件夹里排序好看。"""
    return cache / "pages" / f"{n:03d}.md"
```

`app/courseware/store.py`(新文件):

```python
"""课件库:上传的原件按内容哈希存成 data/courses/<id>.pdf,显示名放旁边的 .json。

为什么要哈希命名:同一份课件改个文件名再传,内容哈希不变 → 认成同一份,
不重复存、不重复解析、不重复花钱;显示名不受文件系统限制,中文随便叫。
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from app.courseware import CoursewareError, course_file, course_meta_file, courses_dir

log = logging.getLogger(__name__)

_CHUNK = 1024 * 1024  # 1MB 一块:几百 MB 的课件也不整份塞进内存


def save_upload(data_dir: Path, stream, filename: str) -> tuple[str, bool]:
    """把上传的文件流存进课件库,返回 (课件id, 是否新入库)。

    边写边算内容哈希;先落成临时文件,验过 %PDF 魔数才正式入位——半截文件不入库。
    """
    courses = courses_dir(data_dir)
    courses.mkdir(parents=True, exist_ok=True)
    tmp = courses / f".upload-{secrets.token_hex(6)}.part"
    h = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as out:
            while True:
                chunk = stream.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
                out.write(chunk)
        with tmp.open("rb") as f:
            if not f.read(5).startswith(b"%PDF"):
                raise CoursewareError("这个文件看起来不是 PDF——小灶只认 PDF 课件。")
        course_id = h.hexdigest()[:16]
        target = course_file(data_dir, course_id)
        if target.exists():  # 内容一样(文件名不同也算):直接用已有的
            return course_id, False
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)  # 入位后这里已不存在;失败路径把半截文件清掉
    course_meta_file(data_dir, course_id).write_text(
        json.dumps(
            {
                "name": filename or f"{course_id}.pdf",
                "added_at": datetime.now().isoformat(timespec="seconds"),
                "size": size,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return course_id, True


def list_courses(data_dir: Path) -> list[dict]:
    """课件列表,新放的前面。坏掉的说明文件跳过——一条脏数据不该打不开整个列表。"""
    courses = courses_dir(data_dir)
    out: list[dict] = []
    if not courses.exists():
        return out
    for mfile in courses.glob("*.json"):
        try:
            meta = json.loads(mfile.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                continue
            course_id = mfile.stem
            if not (courses / f"{course_id}.pdf").exists():
                continue  # 只有说明没有原件:当它不存在
            out.append(
                {
                    "id": course_id,
                    "name": str(meta.get("name") or f"{course_id}.pdf"),
                    "added_at": str(meta.get("added_at") or ""),
                    "size": int(meta.get("size") or 0),
                }
            )
        except (OSError, ValueError):
            log.warning("课件说明文件坏了,跳过:%s", mfile.name)
    out.sort(key=lambda c: c["added_at"], reverse=True)
    return out


def delete_course(data_dir: Path, course_id: str) -> None:
    """删课件:原件、说明、解析缓存一起清干净。"""
    pdf = course_file(data_dir, course_id)  # 顺带校验 id
    if not pdf.exists():
        raise CoursewareError("这份课件不在了——刷新页面看看。")
    pdf.unlink()
    course_meta_file(data_dir, course_id).unlink(missing_ok=True)
    shutil.rmtree(data_dir / "cache" / course_id, ignore_errors=True)
```

- [ ] **Step 4: 跑测试,确认全过**

Run: `python -m pytest tests/test_store.py -q`(再全量 `python -m pytest -q`)
Expected: 6 条全过。

- [ ] **Step 5: 提交**

```bash
git add app/courseware/__init__.py app/courseware/store.py tests/test_store.py
git commit -m "feat: 课件库——按内容哈希入库,同一份课件改名再传不重复" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: 解析第一层——抽文字 + 缓存骨架(断了能续)

**Files:**
- Modify: `requirements.txt`(加 `pymupdf`)
- Create: `app/courseware/parse.py`
- Test: `tests/test_parse.py`(新建)

**Interfaces:**
- Consumes: `course_file`、`cache_dir`、`page_md`、`CoursewareError`(Task 6)。
- Produces: `parse_text_layer(data_dir, course_id, progress=None) -> dict`,返回 `{"total": 总页数, "scanned_pages": [看着是扫描件的页], "pending_scanned": [其中还没让模型看过的], "done_pages": 缓存里已好的页数}`;`read_meta(data_dir, course_id) -> dict | None`(meta.json 在 = 完整解析跑完过,坏文件/旧版本当没有);`course_status(data_dir, course_id) -> dict`(→ `{"state": "done"|"partial"|"none", ...}`,给列表接口用);常量 `SCANNED_TEXT_THRESHOLD=20`、`PARSE_VERSION=1`;类型别名 `Progress = Callable[[int, int], None]`(刚处理完第几页, 共几页)。**parse_text_layer 不写 meta、不调模型**——那两件事在 Task 8。

- [ ] **Step 1: 装依赖**

`requirements.txt` 加一行(在 requests 之后):

```
pymupdf>=1.24
```

Run: `python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
Expected: 装上 pymupdf(开发机已装 1.28.2,会直接通过)。

- [ ] **Step 2: 写失败测试(`tests/test_parse.py` 新文件)**

```python
import pymupdf
import pytest

from app.courseware import CoursewareError, cache_dir, page_md
from app.courseware.parse import parse_text_layer, read_meta
from app.courseware.store import save_upload

# 已在这台机器上验过:pymupdf 1.28 里 fontname="china-s" 能写中文并能原样抽回来
EMPTY_PDF_ZERO_PAGES = (
    b"%PDF-1.4\n"
    b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
    b"2 0 obj <</Type /Pages /Kids [] /Count 0>> endobj\n"
    b"trailer <</Root 1 0 R /Size 3>>\n"
    b"%%EOF\n"
)


def make_pdf(path, texts: list[str]) -> bytes:
    """texts 里空字符串 = 这一页不写文字(拿来模拟扫描页)。"""
    doc = pymupdf.open()
    for t in texts:
        page = doc.new_page()
        if t:
            page.insert_text((72, 72), t, fontname="china-s", fontsize=12)
    data = doc.tobytes()
    doc.close()
    path.write_bytes(data)
    return data


def add_course(data_dir, tmp_path, texts: list[str]) -> str:
    src = tmp_path / "示例课件.pdf"
    make_pdf(src, texts)
    with src.open("rb") as f:
        course_id, _ = save_upload(data_dir, f, "示例课件.pdf")
    return course_id


def test_text_pages_extracted_into_page_files(tmp_path):
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["第一页讲向量", "第二页讲矩阵", "第三页讲特征值"])
    seen = []
    result = parse_text_layer(data, cid, progress=lambda n, total: seen.append((n, total)))
    assert result["total"] == 3
    assert result["scanned_pages"] == []
    assert result["done_pages"] == 3
    assert seen == [(1, 3), (2, 3), (3, 3)]
    cache = cache_dir(data, cid)
    assert "矩阵" in page_md(cache, 2).read_text(encoding="utf-8")


def test_scanned_page_detected_but_left_for_vision_layer(tmp_path):
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["文字页", ""])
    result = parse_text_layer(data, cid)
    assert result["scanned_pages"] == [2]
    assert result["pending_scanned"] == [2]
    assert not page_md(cache_dir(data, cid), 2).exists()  # 第一层不碰扫描页
    assert read_meta(data, cid) is None  # 还没完整解析:没有完成标记


def test_resume_only_reextracts_missing_pages(tmp_path):
    # Review Focus #3:人为删掉一页缓存,再解析 → 只补那一页
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["一", "二", "三"])
    parse_text_layer(data, cid)
    page_md(cache_dir(data, cid), 2).unlink()
    seen = []
    result = parse_text_layer(data, cid, progress=lambda n, total: seen.append(n))
    assert seen == [2]           # 只有缺的那页重抽了
    assert result["done_pages"] == 3
    assert page_md(cache_dir(data, cid), 2).exists()


def test_corrupt_pdf_gives_human_error(tmp_path):
    # Review Focus #2:魔数像 PDF、内容是坏的 → 人话,不是英文栈
    data = tmp_path / "data"
    src = tmp_path / "坏.pdf"
    src.write_bytes(b"%PDF-1.4 garbage")
    with src.open("rb") as f:
        cid, _ = save_upload(data, f, "坏.pdf")
    with pytest.raises(CoursewareError) as ei:
        parse_text_layer(data, cid)
    assert "打不开" in str(ei.value)


def test_zero_page_pdf_gives_human_error(tmp_path):
    # Review Focus #2 的另一半:一页都没有的空 PDF(手工构造——pymupdf 自己存不出 0 页文件)
    data = tmp_path / "data"
    src = tmp_path / "空.pdf"
    src.write_bytes(EMPTY_PDF_ZERO_PAGES)
    with src.open("rb") as f:
        cid, _ = save_upload(data, f, "空.pdf")
    with pytest.raises(CoursewareError) as ei:
        parse_text_layer(data, cid)
    assert "一页都没有" in str(ei.value)


def test_course_status_none_then_partial(tmp_path):
    from app.courseware.parse import course_status

    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["有字", ""])
    assert course_status(data, cid)["state"] == "none"
    parse_text_layer(data, cid)
    st = course_status(data, cid)
    assert st["state"] == "partial" and st["parsed_pages"] == 1
```

- [ ] **Step 3: 跑测试,确认失败**

Run: `python -m pytest tests/test_parse.py -q`
Expected: FAIL(`No module named 'app.courseware.parse'`)。

- [ ] **Step 4: 实现(`app/courseware/parse.py` 新文件)**

```python
"""课件解析:第一层直接抽文字(免费、快);抽不出字的页当扫描件,第二层交视觉模型。

缓存规矩(data/cache/<id>/):
- pages/001.md 逐页落盘,写完一页是一页 —— 断了、断电了,已好的页都留着;
- meta.json **最后**写 —— 它在,才代表这份课件完整解析跑完过;
- 重跑时缺哪页补哪页(断点续传),缓存里有的页一个模型请求都不发。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

import pymupdf

from app.courseware import CoursewareError, cache_dir, course_file, page_md

log = logging.getLogger(__name__)

SCANNED_TEXT_THRESHOLD = 20  # 一页抽出来不到这么多字符,当它是扫描/图片页
PARSE_VERSION = 1            # 缓存格式版本;将来解析方式大改时 +1,老 meta 自动作废

Progress = Callable[[int, int], None]  # (刚处理完第几页, 共几页)


def is_scanned_text(text: str) -> bool:
    return len(text.strip()) < SCANNED_TEXT_THRESHOLD


def _open_doc(data_dir: Path, course_id: str) -> pymupdf.Document:
    src = course_file(data_dir, course_id)  # 顺带校验 id
    if not src.exists():
        raise CoursewareError("这份课件不在了——刷新页面看看。")
    try:
        return pymupdf.open(src)
    except Exception as e:  # FileDataError 等:坏文件、加密文件都落这里
        raise CoursewareError("这个 PDF 打不开(可能坏了或者加了密码)——换一份试试。", repr(e))


def meta_file(data_dir: Path, course_id: str) -> Path:
    return cache_dir(data_dir, course_id) / "meta.json"


def read_meta(data_dir: Path, course_id: str) -> dict | None:
    """解析完成标记。没跑完 = 没有;坏文件、老版本当没有(页文件还在,照样能续)。"""
    p = meta_file(data_dir, course_id)
    if not p.exists():
        return None
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or int(meta.get("version") or 0) != PARSE_VERSION:
        return None
    return meta


def parse_text_layer(data_dir: Path, course_id: str, progress: Progress | None = None) -> dict:
    """第一层:能直接抽到字的页抽成 Markdown 落盘。

    返回 {"total", "scanned_pages", "pending_scanned", "done_pages"}。
    只看文件里的文字层,不花钱;扫描页记下来,留给视觉层。
    """
    doc = _open_doc(data_dir, course_id)
    try:
        total = doc.page_count
        if total == 0:
            raise CoursewareError("这个 PDF 一页都没有——像是空文件。")
        cache = cache_dir(data_dir, course_id)
        (cache / "pages").mkdir(parents=True, exist_ok=True)
        scanned: list[int] = []
        pending: list[int] = []
        done = 0
        for i in range(total):
            n = i + 1
            target = page_md(cache, n)
            text = doc[i].get_text().strip()
            if is_scanned_text(text):
                scanned.append(n)
                if target.exists():  # 视觉层之前已经看过了:算已好,不重看、不重复花钱
                    done += 1
                else:
                    pending.append(n)
                continue
            if target.exists():  # 续传:这页之前抽过
                done += 1
                continue
            target.write_text(text, encoding="utf-8")
            done += 1
            if progress:
                progress(n, total)
        return {"total": total, "scanned_pages": scanned, "pending_scanned": pending, "done_pages": done}
    finally:
        doc.close()


def course_status(data_dir: Path, course_id: str) -> dict:
    """给课件列表用:这份解析到哪了。"""
    meta = read_meta(data_dir, course_id)
    if meta is not None:
        return {
            "state": "done",
            "pages": int(meta.get("pages") or 0),
            "scanned_pages": len(meta.get("scanned_pages") or []),
            "parsed_at": str(meta.get("parsed_at") or ""),
        }
    pages = cache_dir(data_dir, course_id) / "pages"
    parsed = len(list(pages.glob("*.md"))) if pages.exists() else 0
    return {"state": "partial" if parsed else "none", "parsed_pages": parsed}
```

- [ ] **Step 5: 跑测试,确认全过**

Run: `python -m pytest tests/test_parse.py -q`(再全量 `python -m pytest -q`)
Expected: 6 条全过。

- [ ] **Step 6: 提交**

```bash
git add requirements.txt app/courseware/parse.py tests/test_parse.py
git commit -m "feat: 课件解析第一层——抽文字落缓存,扫描页留给视觉层,支持断点续传" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: 解析第二层——扫描页渲染成图,交给视觉模型

**Files:**
- Create: 无(继续写 `app/courseware/parse.py`)
- Test: `tests/test_parse.py`(追加)

**Interfaces:**
- Consumes: `parse_text_layer`、`read_meta`(Task 7);`chat_completion_full`(Task 2);`record_usage`(Task 5);`Config.vision_model`(Task 3)。
- Produces: `parse_course(data_dir, course_id, cfg, progress=None) -> dict` —— 完整解析一遍,**meta.json 最后写**;`vision_cfg(cfg) -> Config`(vision_model 留空 = 跟主模型);常量 `RENDER_DPI=150`、`VISION_MAX_TOKENS=4096`、`VISION_TIMEOUT=120.0`。视觉页失败:重试一次,还不行就抛 `CoursewareError`(人话里带「接着来」),已解析的页全部保留。

- [ ] **Step 1: 写失败测试(追加到 `tests/test_parse.py`)**

import 区补:

```python
from app.config import Config
from app.courseware.parse import parse_course, vision_cfg
from app.usage import usage_totals
from tests.test_provider import FakeLLM, cfg_for


def vision_body(text="扫描页识别结果:$x^2+y^2=1$"):
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 800, "completion_tokens": 60},
    }
```

测试:

```python
def test_scanned_page_goes_to_vision_and_lands_in_md(tmp_path):
    data = tmp_path / "data"
    with FakeLLM(body=vision_body()) as fake:
        cid = add_course(data, tmp_path, ["文字页内容在这里", ""])
        meta = parse_course(data, cid, cfg_for(fake))
    assert meta["scanned_pages"] == [2]
    assert "x^2" in page_md(cache_dir(data, cid), 2).read_text(encoding="utf-8")
    parts = fake.requests[0]["json"]["messages"][0]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert usage_totals(data)["calls"] == 1  # 看这一页记了一笔账


def test_second_parse_costs_nothing_more(tmp_path):
    # Review Focus #1/#3 的核心:全部解析好之后再点「解析」——一个模型请求都不许发
    data = tmp_path / "data"
    with FakeLLM(body=vision_body()) as fake:
        cid = add_course(data, tmp_path, ["文字", ""])
        parse_course(data, cid, cfg_for(fake))
        sent_after_first = len(fake.requests)
        meta = parse_course(data, cid, cfg_for(fake))  # 第二遍
    assert len(fake.requests) == sent_after_first
    assert meta["scanned_pages"] == [2]  # 重跑也算得出"哪些页是扫描件"
    assert usage_totals(data)["calls"] == 1


def test_text_only_course_needs_no_model_at_all(tmp_path):
    # 全是文字页的课件:连 Key 都没配也能解析完(解析是本地活)
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["一", "二"])
    meta = parse_course(data, cid, Config())
    assert meta["pages"] == 2 and read_meta(data, cid) is not None


def test_scanned_pages_without_key_is_human(tmp_path):
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["文字", ""])
    with pytest.raises(CoursewareError) as ei:
        parse_course(data, cid, Config())
    assert "设置" in str(ei.value)


def test_vision_cfg_override():
    cfg = Config(provider="custom", base_url="http://x/v1", api_key="k", model="主模型", vision_model="看图模型")
    assert vision_cfg(cfg).model == "看图模型"
    assert vision_cfg(Config(model="主模型")).model == "主模型"  # 留空 = 跟主模型
    assert cfg.model == "主模型"  # 原配置不被改坏


def test_vision_failure_keeps_pages_and_resumes(tmp_path):
    # Review Focus #3:模型挂了 → 人话 + 已解析页保留;修好后接着跑,只补缺的页
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["文字页", ""])
    with FakeLLM(status=500) as fake:
        with pytest.raises(CoursewareError) as ei:
            parse_course(data, cid, cfg_for(fake))
    assert "接着来" in str(ei.value)
    assert page_md(cache_dir(data, cid), 1).exists()  # 文字页留着
    assert read_meta(data, cid) is None               # 没跑完 = 没有完成标记
    with FakeLLM(body=vision_body("补上的")) as fake2:
        meta = parse_course(data, cid, cfg_for(fake2))
        assert len(fake2.requests) == 1  # 只补了第 2 页,第 1 页没重跑
    assert meta["pages"] == 2


def test_empty_vision_answer_writes_note_not_blank(tmp_path):
    # Review Focus #5 的解析侧:模型对一页什么都没说 → 页文件里是人话说明,不是空文件
    data = tmp_path / "data"
    with FakeLLM(body=vision_body("")) as fake:
        cid = add_course(data, tmp_path, [""])
        parse_course(data, cid, cfg_for(fake))
    text = page_md(cache_dir(data, cid), 1).read_text(encoding="utf-8")
    assert text.strip() != "" and "没说出内容" in text
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_parse.py -q`
Expected: 新测试 FAIL(`cannot import name 'parse_course'`)。

- [ ] **Step 3: 实现(继续写 `app/courseware/parse.py`)**

文件头部 import 区补齐(在 `import pymupdf` 前后):

```python
import base64
from dataclasses import replace
from datetime import datetime

from app.config import Config
from app.llm.provider import LLMError, chat_completion_full
from app.usage import record_usage
```

文件末尾追加:

```python
RENDER_DPI = 150        # 扫描页渲染的清晰度:够看清字和公式,又不至于图片太大
VISION_MAX_TOKENS = 4096
VISION_TIMEOUT = 120.0

VISION_PROMPT = (
    "这是一份课件 PDF 的第 {page} 页(共 {total} 页),它没有文字层(扫描或图片形式)。"
    "请把这一页的内容完整转成 Markdown:文字照抄;公式用 $...$;表格尽量还原;"
    "看不清的地方标 [看不清]。不要解释、不要客套,只输出这一页的内容。"
)


def vision_cfg(cfg: Config) -> Config:
    """看扫描页用哪套配置:填了『视觉模型』就用它,留空 = 和主模型相同。"""
    if not cfg.vision_model:
        return cfg
    return replace(cfg, model=cfg.vision_model)


def render_page_png(doc: pymupdf.Document, page_index: int) -> bytes:
    return doc[page_index].get_pixmap(dpi=RENDER_DPI).tobytes("png")


def _look_at_page(data_dir: Path, cfg: Config, png: bytes, page_no: int, total: int) -> str:
    """让模型看一页扫描件。失败重试一次——视觉请求偶尔抽风,再来一遍再下结论。"""
    b64 = base64.b64encode(png).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_PROMPT.format(page=page_no, total=total)},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }
    ]
    last: LLMError | None = None
    for _ in range(2):
        try:
            text, usage = chat_completion_full(
                cfg, messages, max_tokens=VISION_MAX_TOKENS, timeout=VISION_TIMEOUT
            )
            record_usage(data_dir, "看扫描页", cfg.model, usage)
            return text.strip()
        except LLMError as e:
            last = e
    raise last


def parse_course(data_dir: Path, course_id: str, cfg: Config, progress: Progress | None = None) -> dict:
    """完整解析一遍:文本层 + 扫描页视觉层;meta.json 最后写 = 这遍跑完了。

    中途失败:页文件都留着;修好问题再点「解析」,只补没看过的页——不重复花钱。
    """
    summary = parse_text_layer(data_dir, course_id, progress)
    pending = summary["pending_scanned"]
    total = summary["total"]
    if pending:
        vcfg = vision_cfg(cfg)
        if not (vcfg.api_key and vcfg.base_url and vcfg.model):
            raise CoursewareError(
                f"有 {len(pending)} 页是扫描/图片页,需要模型来看——"
                "先去「设置」把 Key、接口地址、模型名填好,再点「解析」。"
            )
        doc = _open_doc(data_dir, course_id)
        try:
            cache = cache_dir(data_dir, course_id)
            for n in pending:
                try:
                    text = _look_at_page(data_dir, vcfg, render_page_png(doc, n - 1), n, total)
                except LLMError as e:
                    raise CoursewareError(
                        f"第 {n} 页(扫描页)没看成:{e.human}——已经解析好的页都留着,弄好后点「解析」接着来。",
                        e.detail,
                    )
                if not text:
                    text = "(这一页模型没说出内容;可以之后再点一次「解析」重看)"  # 空回答不留白页
                page_md(cache, n).write_text(text, encoding="utf-8")
                if progress:
                    progress(n, total)
        finally:
            doc.close()
    meta = {
        "version": PARSE_VERSION,
        "pages": total,
        "scanned_pages": summary["scanned_pages"],
        "parsed_at": datetime.now().isoformat(timespec="seconds"),
    }
    cache = cache_dir(data_dir, course_id)
    cache.mkdir(parents=True, exist_ok=True)
    tmp = meta_file(data_dir, course_id).with_name("meta.json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(meta_file(data_dir, course_id))  # 最后一步:完成标记落定
    return meta
```

- [ ] **Step 4: 跑测试,确认全过**

Run: `python -m pytest tests/test_parse.py -q`(再全量 `python -m pytest -q`)
Expected: 13 条全过。

- [ ] **Step 5: 提交**

```bash
git add app/courseware/parse.py tests/test_parse.py
git commit -m "feat: 解析第二层——扫描页渲染给视觉模型,带重试与断点续传,meta 最后落定" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: 课件问答 qa——整份课件进长上下文,答案带页码

**Files:**
- Create: `app/courseware/qa.py`
- Test: `tests/test_qa.py`(新建)

**Interfaces:**
- Consumes: `read_meta`(Task 7)、`cache_dir` 和 `CoursewareError`(Task 6);`chat_completion_full`(Task 2);`record_usage`(Task 5)。
- Produces: `ask_course(data_dir, course_id, question, cfg) -> str`(答案文本;出错抛 `CoursewareError` 人话);`build_corpus(data_dir, course_id) -> str`(按页拼全文,`=== 第 N 页 ===` 分隔);常量 `MAX_CORPUS_CHARS=200000`、`ASK_MAX_TOKENS=2048`、`ASK_TIMEOUT=180.0`。**只认已完整解析的课件**(meta 在);解析没完成先劝回去解析。

- [ ] **Step 1: 写失败测试(`tests/test_qa.py` 新文件)**

```python
import json

import pytest

from app.config import Config
from app.courseware import CoursewareError, cache_dir, course_file, page_md
from app.courseware.parse import PARSE_VERSION, meta_file
from app.courseware.qa import ask_course, build_corpus
from app.usage import usage_totals
from tests.test_parse import add_course
from tests.test_provider import FakeLLM, cfg_for


def seed_parsed(data_dir, tmp_path, pages: list[str]) -> str:
    """直接铺一份"已完整解析"的课件:问答测的是问答,不重测解析。"""
    cid = add_course(data_dir, tmp_path, ["占位"])
    cache = cache_dir(data_dir, cid) / "pages"
    cache.mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(pages, start=1):
        (cache / f"{i:03d}.md").write_text(text, encoding="utf-8")
    meta_file(data_dir, cid).write_text(
        json.dumps({"version": PARSE_VERSION, "pages": len(pages), "scanned_pages": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return cid


def test_answer_comes_back_and_corpus_has_page_markers(tmp_path):
    data = tmp_path / "data"
    body = {
        "choices": [{"message": {"content": "矩阵乘法在第 2 页讲过。"}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 20},
    }
    with FakeLLM(body=body) as fake:
        cid = seed_parsed(data, tmp_path, ["第一页讲向量", "第二页讲矩阵乘法"])
        answer = ask_course(data, cid, "矩阵乘法在哪页?", cfg_for(fake))
        assert "第 2 页" in answer
        sent = fake.requests[0]["json"]["messages"][0]["content"]
        assert "=== 第 1 页 ===" in sent and "=== 第 2 页 ===" in sent
        assert "矩阵乘法在哪页?" in sent
    assert usage_totals(data)["calls"] == 1
    assert usage_totals(data)["prompt_tokens"] == 900


def test_ask_before_parse_is_human(tmp_path):
    data = tmp_path / "data"
    cid = add_course(data, tmp_path, ["一页"])
    with pytest.raises(CoursewareError) as ei:
        ask_course(data, cid, "讲了啥?", Config(provider="custom", base_url="http://x/v1", api_key="k", model="m"))
    assert "解析" in str(ei.value)


def test_empty_question_is_human(tmp_path):
    data = tmp_path / "data"
    cid = seed_parsed(data, tmp_path, ["内容"])
    with pytest.raises(CoursewareError):
        ask_course(data, cid, "   ", Config(provider="custom", base_url="http://x/v1", api_key="k", model="m"))


def test_too_long_corpus_asks_to_split(tmp_path):
    # Review Focus:超长课件不硬塞,人话劝拆章节
    data = tmp_path / "data"
    cid = seed_parsed(data, tmp_path, ["长" * 250_000])
    with pytest.raises(CoursewareError) as ei:
        ask_course(data, cid, "讲了啥?", Config(provider="custom", base_url="http://x/v1", api_key="k", model="m"))
    assert "拆" in str(ei.value)


def test_missing_model_config_is_human(tmp_path):
    data = tmp_path / "data"
    cid = seed_parsed(data, tmp_path, ["内容"])
    with pytest.raises(CoursewareError) as ei:
        ask_course(data, cid, "讲了啥?", Config())
    assert "设置" in str(ei.value)


def test_empty_answer_falls_back_to_human_line(tmp_path):
    # Review Focus #5 的问答侧:模型给了空回答 → 界面上是人话,不是一片空白
    data = tmp_path / "data"
    with FakeLLM(body={"choices": [{"message": {"content": ""}}]}) as fake:
        cid = seed_parsed(data, tmp_path, ["内容"])
        answer = ask_course(data, cid, "讲了啥?", cfg_for(fake))
    assert answer.strip() != "" and "再问" in answer
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_qa.py -q`
Expected: FAIL(`No module named 'app.courseware.qa'`)。

- [ ] **Step 3: 实现(`app/courseware/qa.py` 新文件)**

```python
"""课件问答:整份课件(逐页 Markdown)塞进一次长上下文,要求答案标页码。

M2 不做多轮、不做检索——150 页以内的课件整份进去就够(设计文档 §2);
更长的会被人话劝回去拆章节,宁可说清楚,也不把账单烧成无底洞。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import Config
from app.courseware import CoursewareError, cache_dir
from app.courseware.parse import read_meta
from app.llm.provider import LLMError, chat_completion_full
from app.usage import record_usage

log = logging.getLogger(__name__)

MAX_CORPUS_CHARS = 200_000  # 全文超这个量级就劝拆分
ASK_MAX_TOKENS = 2048
ASK_TIMEOUT = 180.0  # 长课件回答慢,给足时间

ASK_PROMPT = """你在帮学生看课件。下面是课件的全文,按页分隔(格式:=== 第 N 页 ===)。
要求:
1. 只根据课件内容回答;引用到课件的地方,标出来源页码,格式「第 N 页」;
2. 课件里没有的内容,直说「课件里没有提到」,不要编;
3. 用学生看得懂的话,中文回答,别啰嗦。

课件全文:
{corpus}

学生的问题:{question}"""


def build_corpus(data_dir: Path, course_id: str) -> str:
    """把所有已解析的页拼成带页码标记的全文。"""
    pages_dir = cache_dir(data_dir, course_id) / "pages"
    parts = []
    for p in sorted(pages_dir.glob("*.md"), key=lambda x: int(x.stem)):
        n = int(p.stem)
        parts.append(f"=== 第 {n} 页 ===\n{p.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(parts)


def ask_course(data_dir: Path, course_id: str, question: str, cfg: Config) -> str:
    """对一份课件提问,返回带页码的答案;出错抛 CoursewareError(人话)。"""
    question = question.strip()
    if not question:
        raise CoursewareError("问题还没写呢。")
    if read_meta(data_dir, course_id) is None:
        raise CoursewareError("这份课件还没解析完——先点「解析」,解析完再问。")
    corpus = build_corpus(data_dir, course_id)
    if len(corpus) > MAX_CORPUS_CHARS:
        raise CoursewareError(
            f"这份课件太长了(约 {len(corpus) // 1000} 千字),一次塞不进模型——"
            "建议把它按章节拆成几个 PDF 再放进来。"
        )
    if not (cfg.api_key and cfg.base_url and cfg.model):
        raise CoursewareError("还没把模型配好——去「设置」把 Key、接口地址、模型名填好再问。")
    messages = [{"role": "user", "content": ASK_PROMPT.format(corpus=corpus, question=question)}]
    try:
        text, usage = chat_completion_full(cfg, messages, max_tokens=ASK_MAX_TOKENS, timeout=ASK_TIMEOUT)
    except LLMError as e:
        raise CoursewareError(e.human, e.detail)
    record_usage(data_dir, "提问", cfg.model, usage)
    return text.strip() or "(模型这次没说话——再问一遍试试。)"
```

- [ ] **Step 4: 跑测试,确认全过**

Run: `python -m pytest tests/test_qa.py -q`(再全量 `python -m pytest -q`)
Expected: 6 条全过。

- [ ] **Step 5: 提交**

```bash
git add app/courseware/qa.py tests/test_qa.py
git commit -m "feat: 课件问答——全文带页码标记进长上下文,超长劝拆分,空回答有人话" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: 服务端接口 + 课件页(上传 / 列表 / 解析 / 删除)

**Files:**
- Modify: `app/server.py`、`app/web/index.html`、`app/web/app.js`、`app/web/style.css`
- Test: `tests/test_server.py`、`tests/test_web.py`

**Interfaces:**
- Consumes: `save_upload`/`list_courses`/`delete_course`(Task 6)、`parse_course`/`course_status`(Task 7/8)、`HumanError`(Task 2)。
- Produces: `POST /api/courses`(multipart,字段名 `file`;→ `{ok, id, is_new}`)、`GET /api/courses`(每项带 `status` 与在跑时的 `job`)、`POST /api/courses/<id>/parse`(开后台线程,立即返回;状态在列表里看)、`DELETE /api/courses/<id>`;`MAX_UPLOAD_BYTES = 200 * 1024 * 1024`;413 与 `HumanError` 的统一 errorhandler(→ 400 + `{ok:false, message}`);前端 `api()` 升级为先读服务端人话。

- [ ] **Step 1: 写失败测试**

`tests/test_server.py` — 顶部补 import,并追加:

```python
import io
import time

import pymupdf

from app.config import Config, load_config, save_config  # Task 1 已加过就跳过这行
from tests.test_provider import FakeLLM, cfg_for


def make_pdf_bytes(text="第一页内容") -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text, fontname="china-s", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def upload(client, name="讲义.pdf", content=None):
    payload = content if content is not None else make_pdf_bytes()
    return client.post(
        "/api/courses", data={"file": (io.BytesIO(payload), name)}, content_type="multipart/form-data"
    )


def test_upload_list_delete_roundtrip(tmp_path):
    c = make_client(tmp_path)
    r = upload(c)
    assert r.status_code == 200 and r.get_json()["is_new"] is True
    course_id = r.get_json()["id"]
    items = c.get("/api/courses").get_json()
    assert len(items) == 1 and items[0]["name"] == "讲义.pdf"
    assert items[0]["status"]["state"] == "none"
    assert c.delete(f"/api/courses/{course_id}").status_code == 200
    assert c.get("/api/courses").get_json() == []


def test_same_pdf_with_new_name_is_not_duplicated(tmp_path):
    # Review Focus #1:同一份课件(改了文件名)再来一次 → 不建第二条、不重复解析
    c = make_client(tmp_path)
    first = upload(c, "讲义.pdf").get_json()
    second = upload(c, "讲义-最终版.pdf").get_json()
    assert second["is_new"] is False and second["id"] == first["id"]
    assert len(c.get("/api/courses").get_json()) == 1


def test_upload_non_pdf_is_human_error(tmp_path):
    c = make_client(tmp_path)
    r = upload(c, "照片.jpg", b"JFIF 我是图片")
    assert r.status_code == 400
    assert "PDF" in r.get_json()["message"]
    assert c.get("/api/courses").get_json() == []


def test_upload_too_big_is_human_413(tmp_path):
    c = make_client(tmp_path)
    c.application.config["MAX_CONTENT_LENGTH"] = 100  # 测试里把上限调小,不用真造 200MB
    r = upload(c, "大.pdf", b"%PDF-" + b"x" * 500)
    assert r.status_code == 413
    assert "太大" in r.get_json()["message"]


def test_parse_endpoint_runs_in_background_and_reports_done(tmp_path):
    c = make_client(tmp_path)
    course_id = upload(c).get_json()["id"]
    assert c.post(f"/api/courses/{course_id}/parse").status_code == 200
    item = None
    for _ in range(100):  # 后台线程:轮询等它跑完(纯文字 PDF,不需要模型)
        item = c.get("/api/courses").get_json()[0]
        if item.get("job", {}).get("state") in ("done", "failed"):
            break
        time.sleep(0.05)
    assert item["job"]["state"] == "done"
    assert item["status"]["state"] == "done"


def test_parse_and_delete_bad_id_are_human(tmp_path):
    c = make_client(tmp_path)
    assert c.post("/api/courses/zzz/parse").status_code == 400
    assert c.delete("/api/courses/zzz").status_code == 400
```

`tests/test_web.py` — 追加:

```python
def test_course_panel_is_real_ui_not_placeholder(tmp_path):
    html = make_client(tmp_path).get("/").get_data(as_text=True)
    assert 'id="course-file"' in html and 'id="btn-upload"' in html
    assert "课件助手还没接上" not in html  # 占位话被真界面换掉了(下载页占位 M3 再换)
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_server.py tests/test_web.py -q`
Expected: 新测试 FAIL(404 / 占位话还在)。

- [ ] **Step 3: 实现服务端(`app/server.py`)**

import 区补:

```python
from app.courseware import CoursewareError, course_file
from app.courseware.parse import course_status, parse_course
from app.courseware.store import delete_course, list_courses, save_upload
from app.errors import HumanError
from app.usage import usage_totals  # Task 5 已加过就跳过
```

模块级常量(放在 `log = logging.getLogger(__name__)` 之后):

```python
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 单次上传上限;超出 Flask 会抛 413,下面接人话
```

`create_app()` 里 `web_dir = ...` 之后加:

```python
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    jobs: dict[str, dict] = {}  # 解析任务的内存状态;进程重启就没了,页面只当"没在跑"
```

放在 `return app` 之前的最后几条路由:

```python
    @app.post("/api/courses")
    def api_upload_course():
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"ok": False, "message": "没收到文件——重新选一下再放。"}), 400
        try:
            # Path(...).name:有些浏览器会带完整路径,只留文件名
            course_id, is_new = save_upload(data_dir, f.stream, Path(f.filename).name)
        except CoursewareError as e:
            return jsonify({"ok": False, "message": e.human}), 400
        except OSError:
            log.exception("保存课件失败")
            return jsonify({"ok": False, "message": "存课件时出错了——看看磁盘是不是满了,再试一次。"}), 500
        return jsonify({"ok": True, "id": course_id, "is_new": is_new})

    @app.get("/api/courses")
    def api_list_courses():
        items = []
        for course in list_courses(data_dir):
            course["status"] = course_status(data_dir, course["id"])
            job = jobs.get(course["id"])
            if job:
                course["job"] = dict(job)
            items.append(course)
        return jsonify(items)

    @app.post("/api/courses/<course_id>/parse")
    def api_parse_course(course_id: str):
        if jobs.get(course_id, {}).get("state") == "running":
            return jsonify({"ok": True, "job": dict(jobs[course_id])})  # 已在跑,别开第二个
        try:
            src = course_file(data_dir, course_id)
        except CoursewareError as e:
            return jsonify({"ok": False, "message": e.human}), 400
        if not src.exists():
            return jsonify({"ok": False, "message": "这份课件不在了——刷新页面看看。"}), 400
        cfg = load_config(data_dir)
        jobs[course_id] = {"state": "running", "done": 0, "total": 0}

        def report(done: int, total: int) -> None:
            jobs[course_id] = {"state": "running", "done": done, "total": total}

        def run() -> None:
            try:
                meta = parse_course(data_dir, course_id, cfg, progress=report)
                jobs[course_id] = {"state": "done", "done": meta["pages"], "total": meta["pages"]}
            except HumanError as e:
                log.warning("解析课件 %s 失败:%s | %s", course_id, e.human, e.detail)
                jobs[course_id] = {"state": "failed", "message": e.human}
            except Exception:
                log.exception("解析课件 %s 出了意外", course_id)
                jobs[course_id] = {"state": "failed", "message": "解析出了点意外——细节在日志里;再点一次「解析」多半能续上。"}

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True, "job": dict(jobs[course_id])})

    @app.delete("/api/courses/<course_id>")
    def api_delete_course(course_id: str):
        if jobs.get(course_id, {}).get("state") == "running":
            return jsonify({"ok": False, "message": "这份正在解析——等它跑完(或退出重开小灶)再删。"}), 400
        try:
            delete_course(data_dir, course_id)
        except CoursewareError as e:
            return jsonify({"ok": False, "message": e.human}), 400
        jobs.pop(course_id, None)
        return jsonify({"ok": True})

    @app.errorhandler(413)
    def payload_too_large(_e):
        return jsonify({"ok": False, "message": "这个文件太大了(上限 200MB)——换小一点的,或拆开传。"}), 413

    @app.errorhandler(HumanError)
    def human_error(e: HumanError):
        log.warning("接口 %s 出错:%s | %s", request.path, e.human, e.detail)
        return jsonify({"ok": False, "message": e.human}), 400
```

- [ ] **Step 4: 实现前端**

`app/web/index.html` — 课件面板整段替换(第 19-21 行那三行):

```html
  <section class="panel active" id="panel-course">
    <div class="row">
      <input type="file" id="course-file" accept=".pdf,application/pdf">
      <button id="btn-upload">放进课件库</button>
    </div>
    <p id="upload-result"></p>
    <ul id="course-list" class="course-list"></ul>
    <p class="hint">放进来 → 点「解析」→ 解析就是把课件拆成一页一页存在本机;解析过的页不会重复解析。</p>
  </section>
```

`app/web/app.js` — 第一件事:把最上面的 `api()` 整个函数替换成(新的会先读服务端给的人话):

```js
async function api(path, opts = {}) {
  let resp;
  try {
    resp = await fetch(path, opts);
  } catch {
    throw new Error("连不上小灶的本地服务——它可能已经退出了。关掉启动窗口,重新打开一次小灶。");
  }
  let data = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }
  if (!resp.ok || (data && data.ok === false)) {
    // 服务端给了人话就用它;没有才用兜底话术
    throw new Error((data && data.message) || `小灶的本地服务出错(HTTP ${resp.status})——关掉启动窗口,重新打开一次小灶。`);
  }
  if (data === null) {
    throw new Error("小灶的回应看不懂——关掉启动窗口,重新打开一次小灶。");
  }
  return data;
}
```

文件末尾追加(课件页全部逻辑):

```js
// ---------- 课件助手 ----------
const courseList = document.getElementById("course-list");
const courseFile = document.getElementById("course-file");
const btnUpload = document.getElementById("btn-upload");
let refreshTimer = null;

function fmtSize(bytes) {
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
  return Math.max(1, Math.round(bytes / 1024)) + " KB";
}

function statusText(c) {
  if (c.job && c.job.state === "running") {
    return "解析中…" + (c.job.total ? `已到第 ${c.job.done} / ${c.job.total} 页` : "");
  }
  if (c.job && c.job.state === "failed") return "上次解析没成:" + c.job.message;
  if (c.status && c.status.state === "done") {
    return `解析好了(${c.status.pages} 页` +
      (c.status.scanned_pages ? `,其中 ${c.status.scanned_pages} 页扫描件` : "") + ")";
  }
  if (c.status && c.status.state === "partial") {
    return `解析没跑完(已好 ${c.status.parsed_pages} 页)——再点「解析」接着来`;
  }
  return "还没解析";
}

function makeBtn(text, onClick) {
  const b = document.createElement("button");
  b.textContent = text;
  b.addEventListener("click", onClick);
  return b;
}

async function refreshCourses() {
  let courses;
  try {
    courses = await api("/api/courses");
  } catch (e) {
    show("upload-result", e.message, false);
    return;
  }
  courseList.textContent = "";
  for (const c of courses) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "course-name";
    name.textContent = c.name; // textContent:文件名里的尖括号也当文字显示,不给注入的机会
    const meta = document.createElement("span");
    meta.className = "course-meta";
    meta.textContent = fmtSize(c.size) + " · " + statusText(c);
    const act = document.createElement("span");
    act.className = "course-actions";
    if (!(c.job && c.job.state === "running")) {
      act.append(makeBtn("解析", () => runParse(c.id)));
    }
    act.append(makeBtn("删除", () => removeCourse(c)));
    li.append(name, meta, act);
    courseList.append(li);
  }
  if (courses.some((c) => c.job && c.job.state === "running")) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refreshCourses, 1500); // 有解析在跑:进度自己会动
  }
}

async function runParse(courseId) {
  try {
    await api(`/api/courses/${courseId}/parse`, { method: "POST" });
    show("upload-result", "开始解析——进度在列表里,这个页面别关。", true);
    clearTimeout(refreshTimer);
    refreshCourses();
  } catch (e) {
    show("upload-result", e.message, false);
  }
}

async function removeCourse(c) {
  try {
    await api(`/api/courses/${c.id}`, { method: "DELETE" });
    show("upload-result", `已删:${c.name}`, true);
    refreshCourses();
  } catch (e) {
    show("upload-result", e.message, false);
  }
}

btnUpload.addEventListener("click", async () => {
  const file = courseFile.files[0];
  if (!file) {
    show("upload-result", "先选一个 PDF 文件。", false);
    return;
  }
  btnUpload.disabled = true;
  show("upload-result", "正在放进课件库…", true);
  try {
    const fd = new FormData();
    fd.append("file", file);
    const r = await api("/api/courses", { method: "POST", body: fd });
    show(
      "upload-result",
      r.is_new ? "已入库——点它后面的「解析」。" : "这份课件之前就放过了(内容一样,改了名也认得出来)——直接用就行。",
      true
    );
    courseFile.value = "";
    refreshCourses();
  } catch (e) {
    show("upload-result", e.message, false);
  }
  btnUpload.disabled = false;
});

refreshCourses();
```

`app/web/style.css` 末尾追加:

```css
.row { display: flex; gap: 10px; align-items: center; margin: 12px 0; }
.row input { margin-top: 0; }
.row input[type="file"] { flex: 1; padding: 6px; }
.course-list { list-style: none; margin: 12px 0; padding: 0; }
.course-list li {
  display: flex; gap: 10px; align-items: center;
  padding: 10px 12px; margin-bottom: 8px;
  border: 1px solid #e5e2da; border-radius: 8px; background: #fff;
}
.course-name { flex: 1; word-break: break-all; }
.course-meta { color: #777; font-size: 13px; }
.course-actions { display: flex; gap: 6px; }
#upload-result { white-space: pre-wrap; }
```

- [ ] **Step 5: 跑测试,确认全过 + 手动过一眼**

Run: `python -m pytest tests/test_server.py tests/test_web.py -q`(再全量 `python -m pytest -q`)
再手动:`python -m app.main --no-browser --port 8761 --data-dir data` → 开 `http://127.0.0.1:8761/` → 传一份真 PDF,点解析,看进度条(状态文字)自己动;传同一个文件改个名,看「之前就放过了」。

- [ ] **Step 6: 提交**

```bash
git add app/server.py app/web/index.html app/web/app.js app/web/style.css tests/test_server.py tests/test_web.py
git commit -m "feat: 课件接口与课件页——上传/列表/后台解析进度/删除;api() 优先展示服务端人话" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: 提问接口 + 提问界面 + 用量显示

**Files:**
- Modify: `app/server.py`、`app/web/index.html`、`app/web/app.js`
- Test: `tests/test_server.py`、`tests/test_web.py`

**Interfaces:**
- Consumes: `ask_course`(Task 9)、`usage_totals`(Task 5)、`HumanError` errorhandler(Task 10)。
- Produces: `POST /api/courses/<id>/ask`(body `{"question": "..."}` → `{"ok": true, "answer": "..."}`;出错走统一 400 人话);前端:解析好的课件多一个「提问」按钮 → 展开提问区;设置页有 `#usage-line` 用量一行。

- [ ] **Step 1: 写失败测试**

`tests/test_server.py` — 追加:

```python
def test_ask_end_to_end(tmp_path):
    # 一份文字版课件:上传 → 解析(本地活,不花钱)→ 提问(走 FakeLLM)
    with FakeLLM() as fake:  # 默认回答「收到」
        save_config(tmp_path, cfg_for(fake))
        c = make_client(tmp_path)
        course_id = upload(c).get_json()["id"]
        c.post(f"/api/courses/{course_id}/parse")
        for _ in range(100):
            if c.get("/api/courses").get_json()[0]["status"]["state"] == "done":
                break
            time.sleep(0.05)
        r = c.post(f"/api/courses/{course_id}/ask", json={"question": "这页讲了啥?"})
        assert r.status_code == 200
        assert r.get_json()["answer"] == "收到"
        assert c.get("/api/usage").get_json()["calls"] == 1


def test_ask_unparsed_course_is_human(tmp_path):
    c = make_client(tmp_path)
    course_id = upload(c).get_json()["id"]
    r = c.post(f"/api/courses/{course_id}/ask", json={"question": "在吗"})
    assert r.status_code == 400 and "解析" in r.get_json()["message"]


def test_ask_non_object_body_is_400(tmp_path):
    r = make_client(tmp_path).post("/api/courses/zzz/ask", json=[1, 2])
    assert r.status_code == 400 and r.get_json()["ok"] is False
```

`tests/test_web.py` — 追加:

```python
def test_course_panel_has_ask_and_usage_line(tmp_path):
    html = make_client(tmp_path).get("/").get_data(as_text=True)
    assert 'id="ask-input"' in html and 'id="btn-ask"' in html
    assert 'id="usage-line"' in html
```

- [ ] **Step 2: 跑测试,确认失败**

Run: `python -m pytest tests/test_server.py tests/test_web.py -q`
Expected: 新测试 FAIL(404 / 页面没有这些元素)。

- [ ] **Step 3: 实现服务端(`app/server.py`)**

import 区补 `from app.courseware.qa import ask_course`;在 `api_delete_course` 附近加:

```python
    @app.post("/api/courses/<course_id>/ask")
    def api_ask_course(course_id: str):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "message": "请求格式不对——用页面上的输入框问。"}), 400
        cfg = load_config(data_dir)
        # 出错(没解析、太长、Key 不对……)会抛 HumanError,由统一 errorhandler 翻成 400 人话
        answer = ask_course(data_dir, course_id, str(body.get("question") or ""), cfg)
        return jsonify({"ok": True, "answer": answer})
```

- [ ] **Step 4: 实现前端**

`app/web/index.html` — 课件面板在 `</ul>` 与 `.hint` 之间插提问区,并在设置面板 `test-result` 后面加用量行:

```html
    <div id="ask-area" hidden>
      <h3 id="ask-title"></h3>
      <div class="row">
        <input id="ask-input" placeholder="比如:第 3 页讲的是什么?">
        <button id="btn-ask">提问</button>
      </div>
      <div id="ask-result"></div>
    </div>
```

```html
    <p id="usage-line" class="hint"></p>
```

`app/web/app.js` 末尾追加:

```js
// ---------- 提问 ----------
const askArea = document.getElementById("ask-area");
const askTitle = document.getElementById("ask-title");
const askInput = document.getElementById("ask-input");
const askResult = document.getElementById("ask-result");
const btnAsk = document.getElementById("btn-ask");
let asking = false;
let currentCourse = null;

function openAsk(course) {
  currentCourse = course;
  askTitle.textContent = "问这份课件:" + course.name;
  askArea.hidden = false;
  askResult.textContent = "";
  askInput.focus();
}

async function askCurrent() {
  if (asking || !currentCourse) return;
  const question = askInput.value.trim();
  if (!question) {
    askResult.className = "err";
    askResult.textContent = "问题还没写呢。";
    return;
  }
  asking = true;
  btnAsk.disabled = true;
  askResult.className = "ok";
  askResult.textContent = "正在翻课件想…(课件长的话要等一会儿)";
  try {
    const r = await api(`/api/courses/${currentCourse.id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    askResult.className = "ok";
    askResult.textContent = r.answer;
    askInput.value = "";
    loadUsage();
  } catch (e) {
    askResult.className = "err";
    askResult.textContent = e.message;
  }
  asking = false;
  btnAsk.disabled = false;
}

btnAsk.addEventListener("click", askCurrent);
askInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") askCurrent();
});

async function loadUsage() {
  try {
    const u = await api("/api/usage");
    document.getElementById("usage-line").textContent =
      `模型调用累计:${u.calls} 次 · 输入 ${u.prompt_tokens} / 输出 ${u.completion_tokens} tokens(本机记录,仅供参考)`;
  } catch {
    // 用量显示不重要,拉不到就算了
  }
}

document.querySelector('button[data-tab="settings"]').addEventListener("click", loadUsage);
```

再改两处已有代码:
1. `refreshCourses()` 里,解析好的课件多一个「提问」按钮——把这段

```js
    if (!(c.job && c.job.state === "running")) {
      act.append(makeBtn("解析", () => runParse(c.id)));
    }
    act.append(makeBtn("删除", () => removeCourse(c)));
```

改成:

```js
    if (!(c.job && c.job.state === "running")) {
      act.append(makeBtn("解析", () => runParse(c.id)));
    }
    if (c.status && c.status.state === "done") {
      act.append(makeBtn("提问", () => openAsk(c)));
    }
    act.append(makeBtn("删除", () => removeCourse(c)));
```

2. `removeCourse()` 里补一句:删掉的正好是正在问的这份 → 收起提问区。在 `await api(...DELETE...)` 之后加:

```js
    if (currentCourse && currentCourse.id === c.id) {
      currentCourse = null;
      askArea.hidden = true;
    }
```

`app/web/style.css` 末尾追加:

```css
#ask-title { font-size: 16px; margin: 20px 0 0; }
#ask-result { white-space: pre-wrap; margin-top: 10px; }
#usage-line { margin-top: 16px; font-size: 13px; color: #777; }
```

- [ ] **Step 5: 跑测试,确认全过 + 手动跑一遍全流程**

Run: `python -m pytest -q`
再手动(需要真 Key,或指向一个能连通的小模型):起服务 → 传课件 → 解析 → 提问 → 看答案有没有页码、设置页用量有没有涨。

- [ ] **Step 6: 提交**

```bash
git add app/server.py app/web/index.html app/web/app.js app/web/style.css tests/test_server.py tests/test_web.py
git commit -m "feat: 提问接口与提问区;设置页显示本机累计用量" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 12: 打包与 CI——pymupdf 进包、自检加解析库检查

**Files:**
- Modify: `app/main.py`、`scripts/build_macos.sh`、`requirements.txt`(Task 7 已改,这里只核对)
- 预计不改: `xiaozhao.spec`(PyInstaller 的官方 hooks-contrib 自带 pymupdf 钩子)

**Interfaces:**
- Produces: `--self-test` 先验 PyMuPDF(内存里做一份小 PDF、存一遍、开回来、抽字对得上)——打包漏了库,CI 当场红,不等到朋友那边才发现。

- [ ] **Step 1: 扩自检(`app/main.py`)**

在 `_run_self_test` 上方加函数:

```python
def _check_pymupdf() -> None:
    """解析课件的库在不在、能不能真干活:内存里做份小 PDF 走一圈(不落盘)。"""
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "selftest", fontsize=12)
    data = doc.tobytes()
    doc.close()
    reopened = pymupdf.open(stream=data, filetype="pdf")
    try:
        assert reopened[0].get_text().strip() == "selftest"
    finally:
        reopened.close()
```

`_run_self_test` 里,`from app.server import create_app, find_free_port` 之后、起服务之前插:

```python
    try:
        _check_pymupdf()
    except Exception as e:
        print(f"自检失败:PyMuPDF 不可用({e!r})——打包时把解析库漏了")
        return 1
    print("PyMuPDF 就位(解析课件没问题)")
```

- [ ] **Step 2: 改 macOS 打包脚本(`scripts/build_macos.sh`)**

第 23 行的冒烟 import 行:

```bash
  && ./python/bin/python3 -c "import app, flask, requests, pymupdf; print('import ok')" \
```

- [ ] **Step 3: 本地验证**

Run:
```powershell
python -m pytest -q
python -m app.main --self-test --data-dir data
```
Expected: 全过;自检输出多一行「PyMuPDF 就位」,最后「自检通过」。

- [ ] **Step 4: 本地打 Windows 包并冒烟**

Run:
```powershell
python -m pip install pyinstaller
pyinstaller xiaozhao.spec --noconfirm
.\dist\小灶.exe --self-test
git status --short
```
Expected: exe 自检同样打出「PyMuPDF 就位」+「自检通过」。
- 若 exe 自检报「PyMuPDF 不可用」:`xiaozhao.spec` 的 `Analysis(...)` 里把 `hiddenimports=[]` 改成 `hiddenimports=["pymupdf"]`,重新打包重试。
- `git status --short` 除改过的源码外应当干净——若 `data/` 冒出来,立刻往 `.gitignore` 加一行 `data/`(**data 里有朋友的 Key 和课件,绝不能上 GitHub**)。

- [ ] **Step 5: 提交并推 main,等 CI 双绿**

```bash
git add app/main.py scripts/build_macos.sh requirements.txt
git commit -m "chore: 自检与 Mac 打包冒烟带上 pymupdf——打包漏库 CI 当场红" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
git push origin main
gh run list --limit 2
```
Expected: build-windows 与 build-macos 都 success(Windows 侧会因为 pymupdf 变大几十 MB,属正常);红了就修,绿了才算完。

- [ ] **Step 6: 补提交(若有)**

若 Step 4 改了 `xiaozhao.spec` 或 `.gitignore`,单独提交:

```bash
git add xiaozhao.spec .gitignore
git commit -m "chore: 打包补丁(spec/.gitignore)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
git push origin main
```

---

### Task 13: M2 验收(在开发机上,照着跑)

**Files:**
- Create: `docs/验收/M2-验收记录.md`(结论、实测花费、遗留问题)

**Interfaces:**
- Consumes: 前面全部任务。
- Produces: 通过线(设计文档 §5 M2 行)的验收结论:真实课件能答、页码引用对、扫描页可读、不重复花钱、成本有实测数字、搞破坏全是人话。

- [ ] **Step 1: 起服务,过一遍界面**

双击 `启动小灶.bat`(或 `.\dist\小灶.exe`)。逐条勾:
- [ ] 窗口第一行是「正在启动小灶…」;浏览器自动打开
- [ ] 设置页有「视觉模型」输入框;平台下拉里有 DeepSeek
- [ ] 课件助手页有:选文件 + 「放进课件库」;不再是占位文字
- [ ] 下载管家页仍是占位(它是 M3,不慌)

- [ ] **Step 2: 文本型课件走全流程**

- [ ] 放一份真课件(朋友的真课件到手就用;没到先用任意中文讲义/论文 PDF,≥20 页)
- [ ] 点「解析」→ 状态自己跳(「解析中…已到第 N / M 页」)→「解析好了(N 页)」
- [ ] 打开 `data\cache\<id>\pages\`,抽查 2~3 页:文字和课件对得上
- [ ] 提 5 个问题(围绕内容问,比如「第 10 页讲了什么」「这门课一共有哪些主题」「把第 3 页的内容列成要点」…):
  **通过线:至少 4 个答案带页码引用(「第 N 页」),且页码对得上真实内容**

- [ ] **Step 3: 扫描件走视觉**

- [ ] 放一份扫描件(朋友真扫描课件优先;没有就用手机拍几页拼成 PDF)
- [ ] 解析(这时才用到模型;主模型不能看图的话,在设置里把「视觉模型」填成一个能看图的模型)→ 完成
- [ ] 抽查该课件的 `pages\*.md`:文字可读;公式大致还原;**记下代价**(这一份花了多少 tokens,下面算钱用)

- [ ] **Step 4: 不重复花钱(Review Focus #1/#3)**

```powershell
Get-Content data\usage.jsonl | Measure-Object -Line     # 记下行数
```
- [ ] 对同一份课件**再点一次「解析」** → 跑完后再数 `usage.jsonl`:行数不变
- [ ] 提 1 个问题 → 行数 +1
- [ ] 删掉 `data\cache\<id>\pages\` 里一半文件 → 再点「解析」→ 它只补缺的页(能看出进度数字),完成后状态回到「解析好了」

- [ ] **Step 5: 成本实测(写数字,不写感觉)**

```powershell
python -c "import json,pathlib; rows=[json.loads(l) for l in pathlib.Path('data/usage.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]; p=sum(r['prompt_tokens'] for r in rows); c=sum(r['completion_tokens'] for r in rows); print(f'调用 {len(rows)} 次,输入 {p} tokens,输出 {c} tokens')"
```
- [ ] 把总数 × 平台当前单价(打开平台官网定价页抄一眼)→ 算出:**一门 20 页课件解析 + 问 5 个问题大约多少钱**;按每周 3 门课估一个月
- [ ] 数字和结论写进 `docs/验收/M2-验收记录.md`

- [ ] **Step 6: 故意搞破坏(全是人话才算过)**

- [ ] 断网(或把代理关掉)提一个问题 → 出「连不上」之类人话,不是英文报错
- [ ] 设置里换成错 Key 保存 → 提问 / 解析扫描件 → 人话提示,不是 500 白屏
- [ ] 把 `设置-接口地址` 填成网页地址(比如 platform.deepseek.com)→ 提问 → 人话
- [ ] 传一个把 `.docx` 改名的假 PDF → 「看起来不是 PDF」人话
- [ ] 解析到一半把服务杀进程(黑窗口跑着的时候直接关)→ 重开小灶 → 列表应显示「解析没跑完(已好 N 页)」→ 点「解析」能接着跑完

- [ ] **Step 7: 写结论**

`docs/验收/M2-验收记录.md` 写:每项过没过、页码引用命中率(几个问题对几个)、实测花费、踩到的坑与遗留(比如某个平台不接受 `data:` 图片这种)、以及「朋友的哪一步等真课件到手再补跑」。

- [ ] **Step 8: 提交**

```bash
git add docs/验收/M2-验收记录.md
git commit -m "docs: M2 验收记录" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 后续计划(不在本计划内,按顺序各写各的)

- **M3 下载管家**:高清图片/素材 + 视频/录播批量下载(yt-dlp / gallery-dl 封装,自研只做「页面找原图 + 高清筛选 + 限速」薄层);入口就是「下载管家」标签页现在的占位。动手前先问朋友要 3~5 条常逛站点链接。
- **M4 给朋友装(Mac 真机)**:curl 一键安装说明 + 朋友 Mac 上的真机自检 + 第一次打开引导(注册指南、粘 Key、测试连接);口子⑦(start.command 对 python 目录整体丢失的兜底)在这里收;朋友的 Mac 自检还欠着一次(递成品时顺带跑)。
