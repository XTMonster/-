// 设置页（v1.7 卡 C2）：六分组手风琴。
// 读-改-写纪律（钉死）：GET /v1/ui/config 的完整对象原样持有，表单只改对应键，
// 保存时整包 JSON PUT 回去（B2 按 Content-Type 双收）；未知键原样带回，前端不重建配置。
import { api, el, describeError, onPageShow } from "./app.js";
import { getPath, setPath } from "./lib.js";

const page = document.getElementById("page-cfg");
let loaded = null;           // 服务端返回的完整配置对象（唯一持有处）
let maskedKey = "";          // GET 回来的掩码 key，只用作 placeholder

// ---- 共享 helper：规则页等其它模块复用同一读-改-写通道 ----

/** 读配置（每次都重新 GET，不缓存：配置可能被别处改过）。 */
export async function loadConfig() {
  const cfg = await api("/v1/ui/config");
  return cfg;
}

/**
 * 整包写回。mutate(cfg) 原地改要变的键；返回服务端 {issues}。
 * 发送前强制把 llm.api_key 置空串：config 通道永不带 key 值（TDD §4.3）。
 */
export async function saveConfig(cfg) {
  const body = JSON.parse(JSON.stringify(cfg));
  if (body.llm && typeof body.llm === "object") body.llm.api_key = "";
  return api("/v1/ui/config", { method: "PUT", body, headers: { "Content-Type": "application/json" } });
}

export async function updateConfig(mutate) {
  const cfg = await loadConfig();
  mutate(cfg);
  return saveConfig(cfg);
}

function hasPath(obj, path) { return getPath(obj, path) !== undefined; }

// ---- 字段描述：path / 标签 / 类型 ----
const PROVIDERS = ["openai", "deepseek", "anthropic", "local"]; // config.py LLMConfig.provider 注释
const GROUPS = [
  { title: "模型", fields: [
    { path: "llm.provider", label: "provider", type: "select", options: PROVIDERS },
    { path: "llm.model", label: "model", type: "text" },
    { path: "llm.base_url", label: "base_url", type: "text" },
    { path: "llm.timeout_s", label: "timeout_s（秒）", type: "number", step: "1" },
    { path: "llm.max_tokens", label: "max_tokens（0 = 不发送）", type: "number", step: "1" },
  ], extra: renderKeyAndTest },
  { title: "思考强度", fields: [
    { path: "llm.thinking_level", label: "思考强度", type: "radio",
      options: [["off", "关闭"], ["low", "低"], ["medium", "中"], ["high", "高"]],
      note: "高 = 慢思考，超时建议 ≥ 600 s" },
  ] },
  { title: "上下文", fields: [
    { path: "orchestration.context_window_tokens", label: "上下文窗口（tok）", type: "range",
      min: 8192, max: 131072, step: 1024, note: "超出即裁剪：保 system＋最新轮" },
  ] },
  { title: "知识库", fields: [
    { path: "rag.enabled", label: "启用知识库", type: "checkbox" },
    { path: "rag.backend", label: "backend", type: "text" },
    { path: "rag.top_k", label: "top_k", type: "number", step: "1" },
    { path: "rag.rule_top_k", label: "规则包 rule_top_k", type: "number", step: "1" },
    { path: "rag.cases_backend", label: "案例层 cases_backend", type: "select", options: ["lightrag", "hybrid", "off"] },
    { path: "rag.cases_top_k", label: "案例 cases_top_k", type: "number", step: "1" },
    { path: "rag.max_tokens_per_call", label: "每镜上限 max_tokens_per_call", type: "number", step: "1" },
    { path: "rag.plan_prefetch_tokens", label: "plan_prefetch_tokens", type: "number", step: "1" },
  ] },
  { title: "目标模型", fields: [], extra: renderTargetModels },
  { title: "预算", fields: [
    { path: "budget.max_cost_usd", label: "费用上限（USD）", type: "number", step: "0.1" },
    { path: "budget.max_wall_minutes", label: "墙钟（分钟）", type: "number", step: "1" },
    { path: "budget.max_llm_calls_ceiling", label: "调用硬顶", type: "number", step: "1" },
  ] },
];

let fieldId = 0;
function renderField(cfg, f) {
  if (!hasPath(cfg, f.path)) {
    // 后端尚未提供该键（例如 A2 新键未落地）：如实说明，不凭空写入新键。
    return el("p", { class: "bd-hint" }, `${f.label}：当前配置里没有 ${f.path}（后端未提供该键）`);
  }
  const value = getPath(cfg, f.path);
  const id = `cfg-f-${++fieldId}`;
  const wrap = el("div", { class: "bd-field" });
  if (f.type === "radio") {
    const fs = el("fieldset", {}, el("legend", {}, f.label));
    for (const [v, text] of f.options) {
      const rid = `${id}-${v}`;
      fs.append(el("input", { type: "radio", name: id, id: rid, value: v, checked: value === v,
        onchange: () => setPath(loaded, f.path, v) }), el("label", { for: rid, style: "display:inline;margin-right:12px" }, text));
    }
    wrap.append(fs);
  } else if (f.type === "checkbox") {
    wrap.append(el("label", { for: id, style: "display:inline" },
      el("input", { type: "checkbox", id, checked: Boolean(value),
        onchange: (e) => setPath(loaded, f.path, e.target.checked) }), " ", f.label));
  } else if (f.type === "select") {
    const opts = f.options.includes(value) ? f.options : [value, ...f.options];
    wrap.append(el("label", { for: id }, f.label),
      el("select", { id, onchange: (e) => setPath(loaded, f.path, e.target.value) },
        opts.map((o) => el("option", { value: o, selected: o === value }, o))));
  } else if (f.type === "range") {
    const out = el("output", { for: id }, String(value));
    wrap.append(el("label", { for: id }, f.label, " ", out),
      el("input", { type: "range", id, min: f.min, max: f.max, step: f.step, value,
        oninput: (e) => { const n = Number(e.target.value); setPath(loaded, f.path, n); out.textContent = String(n); } }));
  } else {
    const isNum = f.type === "number";
    wrap.append(el("label", { for: id }, f.label),
      el("input", { id, type: isNum ? "number" : "text", step: f.step, value: value ?? "",
        onchange: (e) => setPath(loaded, f.path, isNum ? Number(e.target.value) : e.target.value) }));
  }
  if (f.note) wrap.append(el("p", { class: f.path === "llm.thinking_level" ? "bd-warntext" : "bd-hint" }, f.note));
  return wrap;
}

// ---- 模型组附加：key 与测试连接 ----
const keyInput = el("input", { id: "cfg-api-key", type: "password", autocomplete: "off" });
function renderKeyAndTest() {
  keyInput.placeholder = maskedKey || "未设置";
  keyInput.value = "";
  const result = el("p", { class: "bd-hint", role: "status" });
  const testBtn = el("button", { class: "bd-btn bd-btn--ghost", type: "button", onclick: async () => {
    result.textContent = "测试中…";
    try {
      await api("/health");
      await api("/v1/chat", { method: "POST", body: {
        messages: [{ role: "user", content: "ping" }], tools: [], tool_choice: "none",
        temperature: 0, purpose: "react", max_tokens: 8 } });
      result.textContent = "连接正常（sidecar 与上游模型均可达）";
      result.className = "bd-ok";
    } catch (err) {
      result.textContent = describeError(err);
      result.className = "bd-warntext";
    }
  } }, "测试连接");
  return el("div", {},
    el("label", { for: "cfg-api-key" }, "API key（留空 = 不修改）"), keyInput,
    el("div", { class: "bd-row", style: "margin-top:8px" }, testBtn,
      el("span", { class: "bd-hint" }, "会产生一次 LLM 调用")), result);
}

// ---- 目标模型组 ----
function renderTargetModels(cfg) {
  const box = el("div", {}, el("p", { class: "bd-hint" }, "读取规格表中…"));
  if (!hasPath(cfg, "delivery.target_model")) {
    box.replaceChildren(el("p", { class: "bd-hint" }, "当前配置里没有 delivery.target_model（后端未提供该键）"));
    return box;
  }
  api("/v1/ui/target_models").then((r) => {
    const models = (r && r.models) || r || {};
    const names = Object.keys(models).filter((k) => k !== "current");
    const current = getPath(loaded, "delivery.target_model");
    const summary = el("div");
    const showSpec = (name) => {
      const spec = models[name];
      const raw = (spec && (spec.raw || spec)) || {};
      summary.replaceChildren(...Object.entries(raw).map(([k, v]) =>
        el("div", { class: "bd-kv" }, el("span", {}, k), el("span", {}, JSON.stringify(v)))));
    };
    const select = el("select", { id: "cfg-target-model", onchange: (e) => {
      setPath(loaded, "delivery.target_model", e.target.value); showSpec(e.target.value); } },
      (names.includes(current) ? names : [current, ...names]).map((n) =>
        el("option", { value: n, selected: n === current }, n)));
    box.replaceChildren(el("label", { for: "cfg-target-model" }, "目标模型"), select,
      el("p", { class: "bd-hint" }, "规格摘要（只读）："), summary);
    showSpec(current);
  }).catch((err) => box.replaceChildren(el("p", { class: "bd-warntext" }, describeError(err))));
  return box;
}

// ---- 页面 ----
const issuesBox = el("div", { role: "status", "aria-live": "polite" });
function renderIssues(issues, savedOk) {
  issuesBox.replaceChildren();
  if (savedOk) issuesBox.append(el("p", { class: "bd-ok" }, "已保存到磁盘"));
  for (const it of issues || []) {
    const sev = String(it.severity || "warning").toLowerCase();
    issuesBox.append(el("div", { class: `bd-issue bd-issue--${sev === "error" ? "error" : "warning"}` },
      `${it.code || ""} ${it.path || it.field || ""}：${it.message || ""}`));
  }
}

async function save() {
  try {
    const key = keyInput.value.trim();
    if (key) {
      // 先写 key（独立通道），成功后再写配置；config 里永不含 key。
      await api("/v1/ui/secret", { method: "PUT", body: { provider: getPath(loaded, "llm.provider"), api_key: key } });
      keyInput.value = "";
    }
    const r = await saveConfig(loaded);
    renderIssues(r && r.issues, true);
    await render();
  } catch (err) {
    const issues = err && err.body && err.body.issues;
    if (issues) {
      renderIssues(issues, false);
      issuesBox.prepend(el("p", { class: "bd-warntext" }, "存在 error 级问题，未写盘："));
    } else {
      issuesBox.replaceChildren(el("p", { class: "bd-warntext" }, describeError(err)));
    }
  }
}

async function render() {
  page.replaceChildren(el("div", { class: "bd-panel" }, "读取配置中…"));
  try {
    loaded = await loadConfig();
  } catch (err) {
    page.replaceChildren(el("div", { class: "bd-panel bd-warntext" }, describeError(err)));
    return;
  }
  maskedKey = String(getPath(loaded, "llm.api_key") || "");
  const groups = GROUPS.map((g, i) => {
    const d = el("details", { class: "bd-group", open: i === 0 }, el("summary", {}, g.title),
      ...g.fields.map((f) => renderField(loaded, f)));
    if (g.extra) d.append(g.extra(loaded));
    return d;
  });
  page.replaceChildren(el("div", { class: "bd-col" },
    el("div", { class: "bd-panel" }, el("h2", {}, "设置"),
      el("p", { class: "bd-hint" }, "保存即写盘；插件下次运行前重读。规则开关在「知识库·规则」页签。"),
      ...groups,
      el("div", { class: "bd-row" }, el("button", { class: "bd-btn", type: "button", onclick: save }, "保存"),
        el("a", { href: "#", onclick: (e) => { e.preventDefault(); document.dispatchEvent(new CustomEvent("bd:open-polish")); } }, "剧本优化")),
      issuesBox)));
}

onPageShow("cfg", render);
