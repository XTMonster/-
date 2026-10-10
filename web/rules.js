// 规则页（v1.7 卡 C5 下半区）：列表来自 GET /v1/ui/rules（真源 contracts/rule_catalog.py，
// 前端不存第二份元信息）。开关 = 改 audit.rules_disabled 后整包 PUT config（settings.js 的读-改-写）。
// 只能关闭，阈值不可改。
import { api, el, describeError } from "./app.js";
import { updateConfig } from "./settings.js";
import { toggleDisabled } from "./lib.js";

const body = el("div", {}, el("p", { class: "bd-hint" }, "读取中…"));
const status = el("p", { class: "bd-hint", role: "status", "aria-live": "polite" });

async function toggle(ruleId, enable) {
  status.textContent = `保存中：${ruleId} → ${enable ? "开" : "关"}…`;
  try {
    await updateConfig((cfg) => {
      cfg.audit = cfg.audit || {};
      cfg.audit.rules_disabled = toggleDisabled(cfg.audit.rules_disabled, ruleId, enable);
    });
    status.textContent = `已保存：${ruleId} ${enable ? "已开启" : "已关闭"}`;
  } catch (err) {
    status.textContent = describeError(err);
  }
  await load();
}

async function load() {
  let r;
  try {
    r = await api("/v1/ui/rules");
  } catch (err) {
    body.replaceChildren(el("p", { class: "bd-warntext" }, describeError(err)));
    return;
  }
  const disabled = new Set((r && r.disabled) || []);
  const rows = ((r && r.rules) || []).map((rule) => {
    const on = !disabled.has(rule.id);
    const id = `rule-${rule.id}`;
    return el("tr", { class: on ? "" : "bd-rule--off" },
      el("td", {}, rule.id),
      el("td", { class: `bd-sev-${rule.severity}` }, rule.severity),
      el("td", {}, rule.summary),
      el("td", {}, el("label", { for: id, style: "margin:0;display:inline" },
        el("input", { type: "checkbox", id, checked: on, onchange: (e) => toggle(rule.id, e.target.checked) }),
        on ? " 开" : " 关")));
  });
  body.replaceChildren(el("table", { class: "bd-table" },
    el("thead", {}, el("tr", {}, el("th", {}, "编号"), el("th", {}, "严重级"), el("th", {}, "简介"), el("th", {}, "开关"))),
    el("tbody", {}, rows)));
}

const panel = el("div", { class: "bd-panel" }, el("h2", {}, "规则开关"),
  el("p", { class: "bd-warntext" }, "只能关闭，阈值不可改；关闭会在每次审计留 skipped 痕。"),
  body, status);
document.getElementById("page-kb").firstElementChild.append(panel);
// 知识页的 onPageShow 由 knowledge.js 注册（Map 单槽）；本模块挂它派发的事件。
document.addEventListener("bd:kb-shown", load);
