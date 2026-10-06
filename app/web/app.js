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
const inputVision = document.getElementById("vision-model");
const inputKey = document.getElementById("api-key");

// 取预设和已存配置;失败也要继续——保证下面的按钮监听挂得上,并把人话提示显示出来
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

// 首屏补默认值:平台已选中但地址/模型空白时,用该预设补上(只填空字段,不覆盖已有值)
const initPreset = presets.find((x) => x.key === sel.value);
if (initPreset) {
  if (!inputBase.value) inputBase.value = initPreset.base_url;
  if (!inputModel.value) inputModel.value = initPreset.default_model;
}

sel.addEventListener("change", () => {
  const p = presets.find((x) => x.key === sel.value);
  if (p) {
    inputBase.value = p.base_url;
    inputModel.value = p.default_model;
  }
});

// 保存当前表单:btn-save 与 btn-test 共用。返回 { ok, error } 供调用方判断是否继续。
async function saveForm() {
  const body = {
    provider: sel.value,
    base_url: inputBase.value,
    model: inputModel.value,
    vision_model: inputVision.value,
    api_key: inputKey.value,
  };
  try {
    const r = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    inputKey.value = "";
    inputKey.placeholder = "已保存:" + (r.api_key_masked || "未填") + "(留空 = 不改)";
    show("save-result", "已保存 ✔", true);
    return { ok: true };
  } catch (e) {
    show("save-result", e.message, false);
    return { ok: false, error: e.message };
  }
}

document.getElementById("btn-save").addEventListener("click", async () => {
  await saveForm();
});

// 测试连接:先保存当前表单(服务端测的是磁盘上已保存的配置),
// 保存失败就把人话错误显示到 test-result,不发测试请求。
document.getElementById("btn-test").addEventListener("click", async () => {
  show("test-result", "测试中…", true);
  const saved = await saveForm();
  if (!saved.ok) {
    show("test-result", saved.error, false);
    return;
  }
  try {
    const r = await api("/api/test-connection", { method: "POST" });
    show("test-result", r.message, r.ok);
  } catch (e) {
    show("test-result", e.message, false);
  }
});

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
    if (c.status && c.status.state === "done") {
      act.append(makeBtn("提问", () => openAsk(c)));
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
    if (currentCourse && currentCourse.id === c.id) {
      currentCourse = null;
      askArea.hidden = true;
    }
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
