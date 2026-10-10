// 聊天页（v1.7 卡 C4，纯前端；后端 POST /v1/ui/chat 见 B7）。
// 写操作入口不做：v1.7 聊天只读（白名单为空），前端连按钮都不画。
import { api, el, describeError, onEvents } from "./app.js";

const SESSION_KEY = "bd_chat_session";
const page = document.getElementById("page-chat");

function sessionId() {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = (crypto.randomUUID && crypto.randomUUID()) ||
      `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

// ---- 对话流 ----
const flow = el("div", { class: "bd-chat-flow", role: "log", "aria-live": "polite", "aria-label": "对话" });
const input = el("input", { id: "chat-input", type: "text", autocomplete: "off",
  placeholder: "问点什么…（例如「现在跑到哪了」；v1.7 聊天只读）" });
const sendBtn = el("button", { class: "bd-btn", type: "submit" }, "发送");

function bubble(kind, text, sources) {
  const node = el("div", { class: `bd-bubble bd-bubble--${kind}` }, text);
  if (sources && sources.length) {
    node.append(el("details", { class: "bd-sources" }, el("summary", {}, `来源 ${sources.length} 条`),
      el("ul", {}, sources.map((s) => el("li", {}, `${s.type || "?"} · ${s.id || ""}`)))));
  }
  flow.append(node);
  flow.scrollTop = flow.scrollHeight;
}

async function send(ev) {
  ev.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  bubble("me", message);
  input.value = "";
  input.disabled = true;
  sendBtn.disabled = true;
  try {
    const r = await api("/v1/ui/chat", { method: "POST", body: { session_id: sessionId(), message } });
    bubble("ai", (r && r.reply) || "（空回复）", r && r.sources);
  } catch (err) {
    bubble("err", describeError(err));
  } finally {
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
  }
}

// ---- 状态卡（事件聚合，缺字段显 "-"）----
const status = { state: "-", shot: "-", llmCalls: 0, tokens: null, cost: null, targetModel: "-", slices: null };
const statusBox = el("div");
function kv(label, value) { return el("div", { class: "bd-kv" }, el("span", {}, label), el("span", {}, value)); }
function renderStatus() {
  const rows = [
    kv("状态", status.state),
    kv("镜头", status.shot),
    kv("LLM", `${status.llmCalls} 次${status.tokens === null ? "" : ` · ${status.tokens} tok`}`),
    kv("费用", status.cost === null ? "-" : `$${Number(status.cost).toFixed(2)}`),
    kv("目标模型", status.targetModel),
  ];
  if (status.slices) rows.push(kv("切片建议", status.slices));
  statusBox.replaceChildren(...rows);
}

onEvents((events) => {
  for (const e of events) {
    const p = e.payload || {};
    if (e.kind === "state_change" && e.state) status.state = e.state;
    if (e.kind === "shot_progress" && e.shot_id) {
      status.shot = p.total ? `${e.shot_id} / ${p.total}` : e.shot_id;
    }
    if (e.kind === "llm_call") status.llmCalls += 1;
    if (typeof p.tokens_total === "number") status.tokens = p.tokens_total;
    if (typeof p.cost_usd === "number") status.cost = p.cost_usd;
    if (p.target_model) status.targetModel = String(p.target_model);
    if (p.target_advice && Array.isArray(p.target_advice.slices)) {
      status.slices = p.target_advice.slices.length ? `${p.target_advice.slices.length} 段` : null;
    }
  }
  renderStatus();
});

// 目标模型行：首屏从配置读一次（缺键/不可达则保持 "-"）。
api("/v1/ui/config").then((cfg) => {
  const tm = cfg && cfg.delivery && cfg.delivery.target_model;
  if (tm) { status.targetModel = String(tm); renderStatus(); }
}).catch(() => {});

// ---- 页面骨架 ----
const polishBanner = el("div", { class: "bd-panel", style: "border-color:var(--bd-yellow);margin-bottom:10px" },
  "剧本优化：贴入草稿 → 建议清单＋改写稿 diff，采纳需二次确认。 ",
  el("button", { class: "bd-btn", type: "button",
    onclick: () => document.dispatchEvent(new CustomEvent("bd:open-polish")) }, "打开剧本优化"));

page.append(
  el("div", { class: "bd-col bd-col--wide" }, polishBanner,
    el("div", { class: "bd-panel" }, el("h2", {}, "聊天"), flow,
      el("form", { class: "bd-row", style: "margin-top:10px", onsubmit: send },
        el("label", { for: "chat-input", class: "bd-hint", style: "margin:0" }, "消息"), input, sendBtn))),
  el("div", { class: "bd-col" }, el("div", { class: "bd-panel" }, el("h2", {}, "运行状态"), statusBox)));
bubble("ai", "我是米迦尔。剧本贴给我，或者问我「状态」。");
renderStatus();
