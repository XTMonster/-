// 知识库页上半区（v1.7 卡 C5）：统计条＋试检索三栏＋trace。
// 试检索走 /v1/retrieve——与注入提示词同一端点（"看到的就是模型吃到的"）。
// 不提供在线编辑语料/重建索引（门①–⑩链路不许被 UI 绕过）。
import { api, el, describeError, onPageShow } from "./app.js";

const page = document.getElementById("page-kb");
const statsBox = el("div", { class: "bd-row" }, "读取中…");
const resultBox = el("div");
const queryInput = el("input", { id: "kb-query", type: "text", autocomplete: "off",
  placeholder: "试检索，例如：镜头类型=过肩 或 对话 正反打" });
const topK = el("input", { id: "kb-topk", type: "number", min: "1", max: "50", value: "5", style: "width:5em" });

function laneList(items, render) {
  if (!items || items.length === 0) return el("p", { class: "bd-hint" }, "（空）");
  return el("ul", { class: "bd-list" }, items.map(render));
}

let lastResult = null;
let domainFilter = "";

function renderResult(r) {
  lastResult = r;
  const allCards = r.cards || [];
  const domains = Array.from(new Set(allCards.map((c) => c.domain).filter(Boolean))).sort();
  if (domainFilter && !domains.includes(domainFilter)) domainFilter = "";
  const cards = domainFilter ? allCards.filter((c) => c.domain === domainFilter) : allCards;
  const edges = r.edges || [];
  const cases = r.cases || [];
  const domainSelect = el("select", { id: "kb-domain", onchange: (e) => { domainFilter = e.target.value; renderResult(lastResult); } },
    el("option", { value: "" }, "全部域"), domains.map((d) => el("option", { value: d, selected: d === domainFilter }, d)));
  resultBox.replaceChildren(
    el("div", { class: "bd-row", style: "margin-bottom:8px" },
      el("label", { for: "kb-domain", style: "margin:0" }, "域筛（只筛本次结果）"), domainSelect),
    el("div", { class: "bd-cols3" },
      el("div", { class: "bd-panel" }, el("h3", {}, `经验建议（软）cards[] · ${cards.length}${domainFilter ? ` / ${allCards.length}` : ""}`),
        laneList(cards, (c) => el("li", {}, el("b", {}, `${c.id} `), `${c.title || ""}`,
          el("div", { class: "bd-hint" }, `${c.domain || ""}`)))),
      el("div", { class: "bd-panel" }, el("h3", {}, `硬约束 edges[] · ${edges.length}`),
        laneList(edges, (e) => el("li", {}, el("b", {}, `${e.type || ""} `), e.edge_id || "",
          (e.forbid && e.forbid.length) ? el("div", { class: "bd-warntext" }, `forbid × ${e.forbid.length}`) : null))),
      el("div", { class: "bd-panel" }, el("h3", {}, `参考案例 cases[] · ${cases.length}`),
        laneList(cases, (c) => el("li", {}, el("b", {}, `${c.case_type || ""} `), c.title || c.case_id || "",
          el("div", { class: "bd-hint" }, c.excerpt || ""))))),
    el("details", {}, el("summary", {}, "trace"), el("pre", { class: "bd-pre" }, JSON.stringify(r.trace || {}, null, 2))));
}

async function search(ev) {
  ev.preventDefault();
  const query = queryInput.value.trim();
  if (!query) return;
  resultBox.replaceChildren(el("p", { class: "bd-hint" }, "检索中…"));
  try {
    const r = await api("/v1/retrieve", { method: "POST", body: { query, top_k: Number(topK.value) || 5 } });
    renderResult(r || {});
  } catch (err) {
    resultBox.replaceChildren(el("p", { class: "bd-warntext" }, describeError(err)));
  }
}

async function loadStats() {
  try {
    const s = await api("/v1/ui/knowledge/stats");
    const n = (k) => el("b", { style: "color:var(--bd-cyan)" }, String((s && s[k]) ?? 0));
    statsBox.replaceChildren("卡 ", n("cards"), " · 边 ", n("edges"), " · 案例 ", n("cases"),
      el("span", { class: "bd-hint" }, `（实读行数${s && s.cards_note ? "；" + s.cards_note : ""}）`));
  } catch (err) {
    statsBox.replaceChildren(el("span", { class: "bd-warntext" }, describeError(err)));
  }
}

export const knowledgePanel = el("div", { class: "bd-panel" }, el("h2", {}, "知识库"), statsBox,
  el("form", { class: "bd-row", style: "margin:10px 0", onsubmit: search },
    el("label", { for: "kb-query", style: "margin:0" }, "查询"), queryInput,
    el("label", { for: "kb-topk", style: "margin:0" }, "top_k"), topK,
    el("button", { class: "bd-btn", type: "submit" }, "检索")),
  resultBox);

page.append(el("div", { class: "bd-col", id: "kb-col" }, knowledgePanel));
onPageShow("kb", () => { loadStats(); document.dispatchEvent(new CustomEvent("bd:kb-shown")); });
