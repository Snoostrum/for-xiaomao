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
