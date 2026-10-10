// BlockDirector Web 前端核心（v1.7 卡 C1）。
// 职责：token 流程、统一 api() helper、页签切换、离线横幅、事件轮询与分发。
// 各页模块只 import 这里导出的函数，不各自 fetch、不各自轮询。

export const POLL_INTERVAL_MS = 2000; // 统一 2 s（技术方案 D3：轮询 ≥1.5 s）
const TOKEN_KEY = "bd_token";

// ---- token：?token= → sessionStorage → 抹掉地址栏 query（TDD §7）----
function takeTokenFromUrl() {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    sessionStorage.setItem(TOKEN_KEY, fromUrl);
    url.searchParams.delete("token");
    history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

let token = takeTokenFromUrl();

export class ApiError extends Error {
  constructor(status, body) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

// ---- 离线横幅：网络抛错才算离线；HTTP 4xx/5xx 是服务端在线的业务错误 ----
const offlineBanner = document.getElementById("offline");
export function showOffline() { offlineBanner.hidden = false; }
export function hideOffline() { offlineBanner.hidden = true; }

/**
 * 统一请求入口。返回解析后的 JSON；非 2xx 抛 ApiError（带响应体）；
 * 网络层失败显离线横幅后原样抛出，调用方自行决定展示（不白屏，A-U2-3）。
 * @param {string} path  以 /v1/ 或 /health 开头的路径
 * @param {{method?:string, body?:any, headers?:Object}} [opts]
 */
export async function api(path, opts = {}) {
  const headers = { Authorization: `Bearer ${token}`, ...(opts.headers || {}) };
  let body;
  if (opts.body !== undefined) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    body = typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body);
  }
  let resp;
  try {
    resp = await fetch(path, { method: opts.method || "GET", headers, body });
  } catch (err) {
    showOffline();
    throw err;
  }
  hideOffline();
  const text = await resp.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = { raw: text }; }
  }
  if (resp.status === 401) showTokenGate();
  if (!resp.ok) throw new ApiError(resp.status, data);
  return data;
}

// ---- 事件总线：轮询结果按 kind 分发给订阅者 ----
const subscribers = new Set();
/** 订阅 UIEvent 批次；返回取消订阅函数。handler(events: UIEvent[]) */
export function onEvents(handler) {
  subscribers.add(handler);
  return () => subscribers.delete(handler);
}

function dispatch(events) {
  if (!events || events.length === 0) return;
  for (const handler of subscribers) {
    try { handler(events); } catch (err) { console.error("event handler failed", err); }
  }
}

let since = 0;
let pollTimer = null;
async function pollEvents() {
  try {
    const r = await api(`/v1/ui/events?since=${since}`);
    if (r && typeof r.latest_seq === "number") since = r.latest_seq;
    dispatch((r && r.events) || []);
  } catch (err) {
    // 离线横幅已由 api() 处理；401 已弹 token 框；其余错误只记控制台。
    if (!(err instanceof ApiError)) console.debug("poll failed", err);
  }
  pollTimer = setTimeout(pollEvents, POLL_INTERVAL_MS);
}

// ---- 页签切换 ----
const tabs = Array.from(document.querySelectorAll('nav [role="tab"]'));
const pages = Array.from(document.querySelectorAll(".bd-page"));
const pageHooks = new Map(); // page -> onShow 回调（懒加载数据）

/** 页模块注册「页面显示时」回调（如进入轨迹页才拉 shots）。 */
export function onPageShow(page, fn) { pageHooks.set(page, fn); }

export function showPage(name) {
  for (const tab of tabs) tab.setAttribute("aria-selected", String(tab.dataset.page === name));
  for (const page of pages) page.hidden = page.dataset.page !== name;
  const hook = pageHooks.get(name);
  if (hook) hook();
}
for (const tab of tabs) tab.addEventListener("click", () => showPage(tab.dataset.page));

// ---- token 输入兜底（无 token 或 401）----
const gate = document.getElementById("token-gate");
function showTokenGate() { gate.hidden = false; }
document.getElementById("token-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const value = document.getElementById("token-input").value.trim();
  if (!value) return;
  token = value;
  sessionStorage.setItem(TOKEN_KEY, value);
  gate.hidden = true;
  if (pollTimer === null) pollEvents();
});

// ---- 小工具：页模块共用 ----
/** 建元素：el("div", {class: "x"}, "文本", child) */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** 把错误渲染成一行可读文本（不吞错：调用方负责显示）。 */
export function describeError(err) {
  if (err instanceof ApiError) {
    const detail = err.body && (err.body.message || err.body.error || err.body.detail);
    return `请求失败（HTTP ${err.status}）${detail ? "：" + detail : ""}`;
  }
  return "sidecar 不可达";
}

// ---- 启动 ----
async function boot() {
  // 页模块在核心就绪后**顺序**载入（它们 import 本文件的导出）。顺序有意义：
  // rules.js 挂在 knowledge.js 建好的知识页栏里，并行 import 不保证求值次序。
  for (const mod of ["./chat.js", "./trajectory.js", "./knowledge.js", "./rules.js",
    "./settings.js", "./polish.js", "./assistant.js"]) {
    try { await import(mod); } catch (err) { console.error(`load ${mod} failed`, err); }
  }
  showPage("chat");
  if (!token) { showTokenGate(); return; }
  pollEvents();
}
boot();
