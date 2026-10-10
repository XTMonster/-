// 轨迹页（v1.7 卡 C6）：左镜头列表（含运镜文字列）＋右 2D 俯视画布。只读，不做 3D。
// 数据源：GET /v1/ui/shots?run=<id>（原样回 <runs-dir>/<run>/export/shots.json）；
// 房间半宽 = config.scene.extent_m。角色路径只认逐镜 `paths` 键——缺键整层不画、不猜站位点。
import { api, el, describeError, onEvents, onPageShow } from "./app.js";
import * as geo from "./lib.js";

const page = document.getElementById("page-traj");
const CANVAS_W = 640;
const CANVAS_H = 640;
const PALETTE = ["#2EC4E6", "#F6C90E", "#E8791A", "#5fd38d", "#c792ea", "#ff6b6b"];

let extent = 12;          // scene.extent_m 缺省值（config.py SceneConfig）
let shots = [];
let currentRun = "";

const runInput = el("input", { id: "traj-run", type: "text", autocomplete: "off", placeholder: "run id" });
const listBox = el("div", {}, el("p", { class: "bd-hint" }, "选择一个 run 后显示镜头"));
const canvas = el("canvas", { class: "bd-topview", width: CANVAS_W, height: CANVAS_H,
  role: "img", "aria-label": "俯视轨迹图" });
const readout = el("div", { class: "bd-readout", "aria-live": "polite" });
const legend = el("div", { class: "bd-legend" });
const statusLine = el("p", { class: "bd-hint", role: "status" });

const worldToCanvas = (x, y) => geo.worldToCanvas(x, y, extent, CANVAS_W, CANVAS_H);
const canvasToWorld = (px, py) => geo.canvasToWorld(px, py, extent, CANVAS_W, CANVAS_H);
const collectPaths = geo.collectPaths;

function draw() {
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#0a0812";
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
  // 1 m 网格
  ctx.strokeStyle = "#1f1a2e";
  ctx.lineWidth = 1;
  for (let m = -Math.floor(extent); m <= Math.floor(extent); m++) {
    const [gx] = worldToCanvas(m, 0);
    const [, gy] = worldToCanvas(0, m);
    ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, CANVAS_H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(CANVAS_W, gy); ctx.stroke();
  }
  // 房间矩形 ±extent
  const [rx0, ry0] = worldToCanvas(-extent, extent);
  ctx.strokeStyle = "#2EC4E6";
  ctx.lineWidth = 2;
  ctx.strokeRect(rx0, ry0, CANVAS_W - 2 * rx0, CANVAS_H - 2 * ry0);

  // 角色路径层
  const paths = collectPaths(shots);
  const ids = Object.keys(paths).sort();
  legend.replaceChildren();
  ids.forEach((cid, i) => {
    const color = PALETTE[i % PALETTE.length];
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    paths[cid].forEach(([x, y], k) => {
      const [px, py] = worldToCanvas(x, y);
      if (k === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.stroke();
    legend.append(el("span", {}, el("span", { class: "bd-swatch", style: `background:${color}` }), cid));
  });
  if (shots.length && ids.length === 0) {
    ctx.fillStyle = "#a39cb3";
    ctx.font = "13px monospace";
    ctx.textAlign = "right";
    ctx.fillText("此导出包无路径数据（v1.7 前产物）", CANVAS_W - 10, 20);
    ctx.textAlign = "left";
  }

  // 相机层：逐镜机位点＋相邻镜机位连线箭头
  const cams = [...shots].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map((s) => ({ id: s.shot_id, pos: s.camera && s.camera.position }))
    .filter((c) => Array.isArray(c.pos) && c.pos.length >= 2);
  ctx.fillStyle = "#F2F2F0";
  ctx.strokeStyle = "rgba(242,242,240,.45)";
  ctx.lineWidth = 1;
  cams.forEach((c, i) => {
    const [px, py] = worldToCanvas(c.pos[0], c.pos[1]);
    ctx.fillRect(px - 3, py - 3, 6, 6);
    ctx.font = "11px monospace";
    ctx.fillText(c.id, px + 5, py - 5);
    if (i > 0) {
      const [qx, qy] = worldToCanvas(cams[i - 1].pos[0], cams[i - 1].pos[1]);
      ctx.beginPath(); ctx.moveTo(qx, qy); ctx.lineTo(px, py); ctx.stroke();
      const a = Math.atan2(py - qy, px - qx);
      ctx.beginPath();
      ctx.moveTo(px, py);
      ctx.lineTo(px - 8 * Math.cos(a - 0.4), py - 8 * Math.sin(a - 0.4));
      ctx.lineTo(px - 8 * Math.cos(a + 0.4), py - 8 * Math.sin(a + 0.4));
      ctx.closePath(); ctx.stroke();
    }
  });
}

canvas.addEventListener("mousemove", (e) => {
  const r = canvas.getBoundingClientRect();
  const px = (e.clientX - r.left) * (CANVAS_W / r.width);
  const py = (e.clientY - r.top) * (CANVAS_H / r.height);
  const [x, y] = canvasToWorld(px, py);
  readout.textContent = `x = ${x.toFixed(2)} m, y = ${y.toFixed(2)} m`;
});
canvas.addEventListener("mouseleave", () => { readout.textContent = ""; });

function renderList() {
  if (!shots.length) { listBox.replaceChildren(el("p", { class: "bd-hint" }, "该 run 没有镜头")); return; }
  const rows = [...shots].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)).map((s) =>
    el("tr", {}, el("td", {}, s.shot_id), el("td", {}, s.shot_type || "-"),
      el("td", {}, s.duration_seconds != null ? `${s.duration_seconds}s` : "-"),
      el("td", {}, s.camera_narration || "-")));
  listBox.replaceChildren(el("table", { class: "bd-table" },
    el("thead", {}, el("tr", {}, el("th", {}, "镜号"), el("th", {}, "景别"), el("th", {}, "时长"), el("th", {}, "运镜文字"))),
    el("tbody", {}, rows)));
}

async function loadRun(run) {
  if (!run) return;
  statusLine.textContent = `读取 ${run}…`;
  try {
    const cfg = await api("/v1/ui/config");
    const ext = Number(cfg && cfg.scene && cfg.scene.extent_m);
    if (ext > 0) extent = ext;
  } catch { /* 读不到配置就用缺省半宽，画布仍可读 */ }
  try {
    const data = await api(`/v1/ui/shots?run=${encodeURIComponent(run)}`);
    shots = (data && data.shots) || [];
    statusLine.textContent = `${run}：${shots.length} 镜 · 房间半宽 ${extent} m`;
  } catch (err) {
    shots = [];
    statusLine.textContent = describeError(err);
  }
  renderList();
  draw();
}

onEvents((events) => {
  for (const e of events) {
    const rid = e.payload && e.payload.run_id;
    if (rid) currentRun = String(rid);
  }
  if (currentRun && !runInput.value) runInput.value = currentRun;
});

page.append(
  el("div", { class: "bd-col" }, el("div", { class: "bd-panel" }, el("h2", {}, "镜头列表"),
    el("form", { class: "bd-row", onsubmit: (e) => { e.preventDefault(); loadRun(runInput.value.trim()); } },
      el("label", { for: "traj-run", style: "margin:0" }, "run"), runInput,
      el("button", { class: "bd-btn", type: "submit" }, "载入")),
    el("p", { class: "bd-hint" }, "只列出 sidecar runs 目录下的运行。"), statusLine, listBox)),
  el("div", { class: "bd-col bd-col--wide" }, el("div", { class: "bd-panel" },
    el("h2", {}, "2D 俯视（房间边界 / 角色路径 / 机位）"), canvas, readout, legend)));
draw();
onPageShow("traj", () => { if (!shots.length && runInput.value) loadRun(runInput.value.trim()); });
