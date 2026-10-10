// 剧本优化页（v1.7 卡 E3）：建议清单（含分工维度）＋行级 LCS diff 双栏＋采纳（二次确认）。
// 后端：POST /v1/ui/script/polish {script} → {suggestions[], rewritten}；
//       POST /v1/ui/script/polish/accept {run_id}（卡 E2）。diff 不引第三方库。
import { api, el, describeError, showPage } from "./app.js";
import { lineDiff } from "./lib.js";

const page = document.getElementById("page-polish");
const scriptInput = el("textarea", { id: "polish-script", rows: "10", placeholder: "把剧本草稿贴在这里" });
const runInput = el("input", { id: "polish-run", type: "text", autocomplete: "off", placeholder: "采纳写回的 run id" });
const status = el("p", { class: "bd-hint", role: "status", "aria-live": "polite" });
const suggestionsBox = el("div");
const left = el("div", { class: "bd-diff-col", "aria-label": "原稿" });
const right = el("div", { class: "bd-diff-col", "aria-label": "改写稿" });
const acceptBtn = el("button", { class: "bd-btn", type: "button", disabled: true }, "采纳改写稿");

function renderDiff(original, rewritten) {
  const line = (cls, text) => el("div", { class: `bd-diff-line ${cls}` }, text ?? "");
  const ls = [], rs = [];
  for (const o of lineDiff(original, rewritten)) {
    if (o.op === "eq") { ls.push(line("", o.a)); rs.push(line("", o.b)); }
    else if (o.op === "del") { ls.push(line("bd-diff-del", "- " + o.a)); rs.push(line("bd-diff-pad", "")); }
    else { ls.push(line("bd-diff-pad", "")); rs.push(line("bd-diff-add", "+ " + o.b)); }
  }
  left.replaceChildren(...ls);
  right.replaceChildren(...rs);
}

// 同步滚动（防回环：只跟随用户正在滚的那一栏）
let syncing = null;
for (const [src, dst] of [[left, right], [right, left]]) {
  src.addEventListener("scroll", () => {
    if (syncing && syncing !== src) return;
    syncing = src;
    dst.scrollTop = src.scrollTop;
    requestAnimationFrame(() => { syncing = null; });
  });
}

const SKIP_HINT = /skip_white_model|跳过白模|不需要白模|直出/;
function renderSuggestions(list) {
  if (!list || !list.length) { suggestionsBox.replaceChildren(el("p", { class: "bd-hint" }, "没有建议")); return; }
  suggestionsBox.replaceChildren(el("ol", {}, list.map((s) => el("li", {}, String(s),
    SKIP_HINT.test(String(s)) ? el("span", { class: "bd-badge" }, "建议 skip_white_model") : null))));
}

async function polish(ev) {
  ev.preventDefault();
  const script = scriptInput.value;
  if (!script.trim()) return;
  status.textContent = "优化中（会产生一次 LLM 调用）…";
  acceptBtn.disabled = true;
  try {
    const r = await api("/v1/ui/script/polish", { method: "POST", body: { script } });
    renderSuggestions(r && r.suggestions);
    renderDiff(script, (r && r.rewritten) || "");
    status.textContent = "完成：左原稿、右改写稿；未采纳前 PLANNING 输入恒为原稿。";
    acceptBtn.disabled = false;
  } catch (err) {
    status.textContent = describeError(err);
  }
}

acceptBtn.addEventListener("click", async () => {
  const runId = runInput.value.trim();
  if (!runId) { status.textContent = "请先填写要写回的 run id"; runInput.focus(); return; }
  if (!window.confirm(`确认采纳改写稿并写回 ${runId}？`)) return;
  try {
    const r = await api("/v1/ui/script/polish/accept", { method: "POST", body: { run_id: runId } });
    status.textContent = (r && (r.note || r.message)) || "已采纳（polish.json accepted=true）";
  } catch (err) {
    status.textContent = describeError(err);
  }
});

page.append(el("div", { class: "bd-col" },
  el("div", { class: "bd-panel" }, el("h2", {}, "剧本优化"),
    el("form", { onsubmit: polish },
      el("label", { for: "polish-script" }, "剧本草稿"), scriptInput,
      el("div", { class: "bd-row", style: "margin-top:8px" }, el("button", { class: "bd-btn", type: "submit" }, "优化"),
        el("button", { class: "bd-btn bd-btn--ghost", type: "button", onclick: () => showPage("chat") }, "返回聊天"))),
    status),
  el("div", { class: "bd-panel" }, el("h3", {}, "建议清单"), suggestionsBox),
  el("div", { class: "bd-panel" }, el("h3", {}, "diff（左原稿 / 右改写稿）"), el("div", { class: "bd-diff" }, left, right),
    el("div", { class: "bd-row", style: "margin-top:8px" },
      el("label", { for: "polish-run", style: "margin:0" }, "run id"), runInput, acceptBtn))));

document.addEventListener("bd:open-polish", () => showPage("polish"));
