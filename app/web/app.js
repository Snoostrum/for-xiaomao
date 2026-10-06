async function api(path, opts) {
  let resp;
  try {
    resp = await fetch(path, opts);
  } catch {
    throw new Error("连不上小灶的本地服务——它可能已经退出了。关掉启动窗口,重新打开一次小灶。");
  }
  if (!resp.ok) {
    throw new Error(`小灶的本地服务出错了(HTTP ${resp.status})——关掉启动窗口,重新打开一次小灶。`);
  }
  try {
    return await resp.json();
  } catch {
    throw new Error("小灶的回应看不懂——关掉启动窗口,重新打开一次小灶。");
  }
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

// 取预设和已存配置;失败也要继续——保证下面的按钮监听挂得上,并把人话提示显示出来
let presets = [];
try {
  presets = await api("/api/presets");
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
} catch (e) {
  show("save-result", e.message, false);
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
  try {
    const r = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    inputKey.value = "";
    inputKey.placeholder = "已保存:" + (r.api_key_masked || "未填") + "(留空 = 不改)";
    show("save-result", "已保存 ✔", true);
  } catch (e) {
    show("save-result", e.message, false);
  }
});

document.getElementById("btn-test").addEventListener("click", async () => {
  show("test-result", "测试中…", true);
  try {
    const r = await api("/api/test-connection", { method: "POST" });
    show("test-result", r.message, r.ok);
  } catch (e) {
    show("test-result", e.message, false);
  }
});
