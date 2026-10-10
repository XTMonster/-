// 像素小助手 Web 组件（v1.7 卡 C3，TDD §6.2）。
// 状态→clip 映射从 GET /v1/ui/state_map 拿（单一真源 contracts/assistant.py，JS 不硬编码）；
// 帧表从 /static/assets/assistant/frames.json 拿。CSS steps(frames) 逐帧跳。
import { api, el, onEvents } from "./app.js";

const ASSET_BASE = "/static/assets/assistant/";
const POS_KEY = "bd_assistant_pos";
const root = document.getElementById("assistant");
const sprite = el("div", { class: "bd-sprite", role: "img", "aria-label": "小助手" });
const tag = el("span", { class: "bd-statetag" }, "IDLE");
root.append(tag, sprite);

let table = null;      // frames.json
let stateMap = {};     // DriverState.value -> clip
let currentClip = "";
let lastState = "IDLE"; // 映射/帧表到达前收到的 state_change 不能丢
const FALLBACK_CLIP = "sit"; // 与 contracts.assistant.clip_for_state 的回落一致

function ensureKeyframes(name, frames, scale) {
  const id = `bd-kf-${name}`;
  if (document.getElementById(id)) return;
  const width = table.base_size * frames * scale;
  document.head.append(el("style", { id },
    `@keyframes bd-clip-${name} { from { background-position: 0 0; } to { background-position: -${width}px 0; } }`));
}

function playClip(name) {
  if (!table || !table.clips) return;
  const clip = table.clips[name] ? name : (table.clips[FALLBACK_CLIP] ? FALLBACK_CLIP : null);
  if (!clip || clip === currentClip) return;
  currentClip = clip;
  const spec = table.clips[clip];
  const scale = 192 / table.base_size;
  ensureKeyframes(clip, spec.frames, scale);
  sprite.style.backgroundImage = `url("${ASSET_BASE}${spec.file}")`;
  sprite.style.backgroundSize = `${table.base_size * spec.frames * scale}px 192px`;
  const seconds = spec.frames / (table.fps || 12);
  sprite.style.animation = `bd-clip-${clip} ${seconds}s steps(${spec.frames}) ${spec.loop === false ? 1 : "infinite"}`;
}

export function setAssistantState(state) {
  lastState = state || "IDLE";
  tag.textContent = lastState;
  playClip(stateMap[lastState] || FALLBACK_CLIP);
}

// ---- 拖拽（Pointer Events）＋位置持久化 ----
function applyPos(pos) {
  const maxX = window.innerWidth - root.offsetWidth;
  const maxY = window.innerHeight - root.offsetHeight;
  root.style.left = `${Math.max(0, Math.min(maxX, pos.x))}px`;
  root.style.top = `${Math.max(0, Math.min(maxY, pos.y))}px`;
  root.style.right = "auto";
  root.style.bottom = "auto";
}
try {
  const saved = JSON.parse(localStorage.getItem(POS_KEY) || "null");
  if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) applyPos(saved);
} catch { /* 坏的存档等同无存档 */ }

let drag = null;
root.addEventListener("pointerdown", (e) => {
  const r = root.getBoundingClientRect();
  drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
  root.setPointerCapture(e.pointerId);
  root.classList.add("is-dragging");
});
root.addEventListener("pointermove", (e) => {
  if (drag) applyPos({ x: e.clientX - drag.dx, y: e.clientY - drag.dy });
});
root.addEventListener("pointerup", (e) => {
  if (!drag) return;
  drag = null;
  root.releasePointerCapture(e.pointerId);
  root.classList.remove("is-dragging");
  const r = root.getBoundingClientRect();
  localStorage.setItem(POS_KEY, JSON.stringify({ x: r.left, y: r.top }));
});

// ---- 事件接入：state_change → 换 clip ----
onEvents((events) => {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].kind === "state_change" && events[i].state) { setAssistantState(events[i].state); break; }
  }
});

async function boot() {
  try {
    const resp = await fetch(`${ASSET_BASE}frames.json`);
    if (resp.ok) table = await resp.json();
  } catch { /* 离线：小助手是附属品，静默不显示 */ }
  try {
    const m = await api("/v1/ui/state_map");
    stateMap = (m && (m.state_map || m)) || {};
  } catch { stateMap = {}; }
  currentClip = "";            // 映射到了：按当前状态重算 clip
  setAssistantState(lastState);
}
boot();
