"""§4.1b 的 Q6b **读数通道**：注入体积必须从**真正发出去的 prompt 里量**。

为什么单独一个工具（2026-10-03 的独立审计查出来的，见
`docs/knowledge/ROUND_AUDIT_20261003_INJECTION_AND_FLOORS.md`）：§4.1b 的 Q6b 行
写着——

    必须读实际发给模型的 prompt（`llm_trace.jsonl` 的 `prompt`），**不得**读
    `knowledge_trace` 的自述；并断言注入 token **整场 ≤ `rag.plan_prefetch_tokens`
    （默认 2000）**、**每镜 ≤ `rag.max_tokens_per_call`（默认 800）**（**是两个键，
    不是一个**），`required_edges_dropped_by_budget` 由"prompt 里实际缺失的 required
    边"独立计数

而链上跑的 `tools/holdout_score.py` 的 Q6b 是**对夹具的 `q` 重渲染**
（`render_edges`）——它回答的是"如果按这条 `q` 检索，注入文本会不会缺成员"，
不是"这一跑真的注入了什么、体积多少"。§4.1b 硬规则 2 允许的通道只有
①渲染/几何 ②**实际发给模型的 prompt** ③人工 held-out ④`audit_log.jsonl` 的
逐次事件；这条 Q6b 点名的是②，而②此前**一个执行者都没有**。

两半的处置**不一样，且必须分开写**（不许用""半边没量到""把整条说成绿）：

* **token 半边判硬**：注入块从 prompt 里**机械定位**（见 :func:`locate_knowledge`），
  用**与裁剪器同一个** `estimate_tokens` 计数，超上限即失败；
* **丢边半边如实记账**：`required_edges_dropped_by_budget` 要按 `q` 把这一跑的
  镜头 join 回 held-out 的 `must`，才能知道"这一镜本来该有哪些 required 边"。
  join 不到就记 `not_measured` 并写明原因——**绝不**把它算成"没有丢边"。

用法::

    python tools/knowledge/injection_audit.py \
        --llm-trace docs/evidence/<run-id>/llm_trace.jsonl \
        --shots docs/evidence/<run-id>/export/shots.json \
        --audit-log docs/evidence/<run-id>/audit_log.jsonl \
        --holdout fixtures/knowledge_holdout.jsonl \
        --out docs/evidence/<run-id>/injection_audit.json

纯 Python、不依赖 bpy、不联网。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.tokens import estimate_tokens  # noqa: E402
from tools.holdout_score import (  # noqa: E402
    build_norm_index,
    entry_key,
    load_graph,
)
from tools.knowledge.run_evidence import (  # noqa: E402
    NA,
    normalise_query_pairs,
    run_query_mirror,
)

PASS, FAIL = "pass", "fail"

#: §4.1b 的 Q6b 行点名的**两个键**（不是同一个）。写成表，为的是让
#: "把两个 scope 都拿一个数去比"这种退化实现当场能被读出来。
CAP_KEYS: Dict[str, str] = {
    "plan": "rag.plan_prefetch_tokens",
    "shot": "rag.max_tokens_per_call",
}

DEFAULT_PLAN_CAP = 2000
DEFAULT_SHOT_CAP = 800

#: 剧本正文的起点标记。**所有字面量检索都必须止步于它**：剧本是不可信内容，
#: 里面的字面量不许影响"注入块到哪儿结束"这件事（否则一次剧本注入就能把
#: 审计的读数拉小）。
UNTRUSTED_MARK = "<untrusted_script_content>"

#: 兜底用的段落前缀。**只在模板字面量对不上时**才走它（例如将来有人把标题或
#: 尾随段落改掉）：三栏各自的标题以 `【` 起，案例/卡片的续行以 `[…` 起。
#: 它是启发式，所以 `locator` 字段会如实写明这一条读数用的是哪一套规则。
_PARA_PREFIXES: Tuple[str, ...] = ("【", "[", "…")

#: 模板里的占位符（`{knowledge}`/`{script}`/`{scene_text}`/`{brief}`…）。字面量
#: 只能取到**下一个占位符之前**——两个 scope 后面的占位符名字并不一样
#: （B1 用 `{scene_text}`，阶段 A 用 `{script}`），按名字写死就会漏。
_PLACEHOLDER_RE = re.compile(r"\{[a-z_]+\}")


def _literal_until_placeholder(text: str) -> str:
    match = _PLACEHOLDER_RE.search(text or "")
    return text[:match.start()] if match else text


def _header_of(template: str) -> str:
    """`{knowledge}` 占位符**独占一行**，所以它前面最后一行就是标题。"""
    return template.split("{knowledge}")[0].rstrip("\n").rsplit("\n", 1)[-1]


def scope_markers() -> Dict[str, Dict[str, Any]]:
    """两个 scope 的定位规则，**全部从真正的模板里推导**（不另抄一份）。

    `{knowledge}` 后面紧跟的字面量决定"块到哪儿结束"，而两个 scope 的情况不同：

    * **shot**（B1）：`{knowledge}` 之后是剧本正文段的字面量 → 精确终止；
    * **plan**（阶段 A）：`{knowledge}` 之后是 `{brief}`（长度可变），所以终止符有
      两个候选——阶段 S 注入块的**首行字面量**（`BRIEF_BLOCK_HEADER`，与
      `render_brief_block` 同源）与它后面的固定段落。取**最早出现**的那个，
      于是"知识块"与"剧本理解块"被分开计量（它们各有各的上限）。
    """
    from block_director.layer5_orchestrator.editor import EDITOR_SYSTEM_PROMPT
    from block_director.layer5_orchestrator.planner import PLAN_SYSTEM_PROMPT
    from block_director.layer5_orchestrator.understand import BRIEF_BLOCK_HEADER

    plan_after = PLAN_SYSTEM_PROMPT.split("{knowledge}")[1]
    tail_source = plan_after.split("{brief}")[1]
    #: `{brief}` 后面**可能还跟着别的占位符**（v1.6 加了 `{space}`）——
    #: 只取"占位符之后的第一个固定段落"当终止符。不退这一步时会取到
    #: 两个占位符之间的 `"\n\n"`，而那个字面量在知识块里到处都是
    #: ⇒ 定位器会在知识块**中间**收尾（实测：块被截成只有"硬约束"那一栏）。
    while True:
        stripped = tail_source.lstrip()
        if not stripped.startswith("{"):
            break
        _placeholder, _, rest = stripped[1:].partition("}")
        if not _:
            break
        tail_source = rest
    plan_tail = _literal_until_placeholder(tail_source)
    editor_after = EDITOR_SYSTEM_PROMPT.split("{knowledge}")[1]
    editor_tail = _literal_until_placeholder(editor_after)
    return {
        "plan": {"scope": "plan", "header": _header_of(PLAN_SYSTEM_PROMPT),
                 "cap_key": CAP_KEYS["plan"],
                 "terminators": [BRIEF_BLOCK_HEADER, plan_tail]},
        "shot": {"scope": "shot", "header": _header_of(EDITOR_SYSTEM_PROMPT),
                 "cap_key": CAP_KEYS["shot"],
                 "terminators": [editor_tail]},
    }


def locate_knowledge(text: str, markers: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """在**渲染后的 prompt** 里定位注入块；找不到返回 ``None``。

    优先用**模板字面量终止符**（精确）；只有模板对不上时才退回"连续吃以
    `【`/`[` 开头的段落"的启发式，并在 `locator` 里写明用了哪一套。
    """
    if not text or not markers:
        return None
    header = str(markers.get("header") or "")
    if not header:
        return None
    index = text.find(header)
    if index < 0:
        return None
    start = index + len(header)
    if text[start:start + 1] == "\n":
        start += 1
    bound = text.find(UNTRUSTED_MARK, start)
    search_end = bound if bound >= 0 else len(text)
    stop = -1
    for terminator in markers.get("terminators") or ():
        position = text.find(terminator, start)
        if position < 0 or position > search_end:
            continue
        if stop < 0 or position < stop:
            stop = position
    block = ""
    locator = "terminator"
    if stop >= 0:
        block = text[start:stop].rstrip("\n")
    else:
        locator = "paragraphs"
        kept: List[str] = []
        for paragraph in text[start:search_end].split("\n\n"):
            if not paragraph.startswith(_PARA_PREFIXES):
                break
            kept.append(paragraph)
        block = "\n\n".join(kept)
    if not block:
        return None
    return {"block": block, "start": start, "end": start + len(block),
            "tokens": estimate_tokens(block), "locator": locator}


def prompt_messages(row: Dict[str, Any]) -> List[str]:
    """`llm_trace.jsonl` 一行 → 各条消息的正文（顺序不变）。"""
    prompt = row.get("prompt")
    if isinstance(prompt, str):
        return [prompt]
    out: List[str] = []
    for message in prompt or []:
        if isinstance(message, dict):
            out.append(str(message.get("content") or ""))
        elif isinstance(message, str):
            out.append(message)
    return out


_SHOT_ID_RE = re.compile(r'"shot_id"\s*:\s*"([^"]+)"')


def shot_id_of(text: str) -> str:
    """从 B1 的 prompt 里取这一镜的 `shot_id`（模板把镜头计划整段渲染进去）。

    为什么不去 `llm_trace` 的其它字段拿：那一份逐次记录里**没有** `shot_id`
    （字段表见 `layer6_audit/audit_logger.py`），而 §4.1b 硬规则 2 只允许读
    "实际发给模型的 prompt"与 `audit_log.jsonl` 的逐次事件——镜身份就在
    prompt 里，读它不算自证。
    """
    match = _SHOT_ID_RE.search(text or "")
    return match.group(1) if match else ""


def _cap_verdict(scope: str, calls: Sequence[Dict[str, Any]],
                 cap: int, cap_key: str) -> Dict[str, Any]:
    if not calls:
        return {"scope": scope, "cap_key": cap_key, "cap": cap, "calls": 0,
                "max_tokens": None, "over": [], "status": NA, "locators": {},
                "note": (f"这一跑的 prompt 里没有一个 {scope} scope 的注入块："
                         f"token 上限无从判起（不得据此判通过）")}
    worst = max(calls, key=lambda item: item["tokens"])
    over = [{"request_id": item["request_id"], "shot_id": item.get("shot_id", ""),
             "tokens": item["tokens"]} for item in calls if item["tokens"] > cap]
    locators: Dict[str, int] = {}
    for item in calls:
        key = str(item.get("locator") or "")
        locators[key] = locators.get(key, 0) + 1
    return {"scope": scope, "cap_key": cap_key, "cap": cap, "calls": len(calls),
            "max_tokens": worst["tokens"],
            "max_request_id": worst["request_id"],
            "over": over[:20],
            "locators": locators,
            "status": FAIL if over else PASS,
            "note": (f"{len(calls)} 个注入块，最大 {worst['tokens']} tokens > "
                     f"{cap}（{cap_key}）——{len(over)} 个超限"
                     if over else
                     f"{len(calls)} 个注入块，最大 {worst['tokens']} tokens ≤ "
                     f"{cap}（{cap_key}）")}


def required_edge_drop_audit(*, graph, entries, mirror,
                             blocks_by_shot: Dict[str, str]) -> Dict[str, Any]:
    """`required_edges_dropped_by_budget`：**从 prompt 里实际缺失的 required 边**数。

    join 口径与 §4.1b 的 Q5 行同源（键值对集合相等、去空格/全半角/别名归一），
    join 键取自 `audit_log.jsonl` 的逐次事件（硬规则 2 的④），**不取**
    `shots.json` 的重推串。
    """
    if graph is None or entries is None:
        return {"id": "Q6b_required_edges_dropped_by_budget", "status": NA,
                "note": "没有 --holdout/--nodes/--edges：required 边没有来源"}
    if not mirror or mirror.get("status") != "ok":
        return {"id": "Q6b_required_edges_dropped_by_budget", "status": NA,
                "note": ("逐镜发出的查询读不出来（缺 --audit-log 或日志里没有 "
                         "retrieval_call 的 shot 事件）：required 边无法 join，"
                         "不得据此判通过")}
    wanted: Dict[str, Tuple[frozenset, List[str]]] = {}
    for entry in entries:
        query = normalise_query_pairs(entry.get("q"))
        if not query or not entry.get("must"):
            continue
        wanted[str(entry.get("id"))] = (query, list(entry["must"]))
    norm_index = build_norm_index(graph)
    matched = dropped = required_total = 0
    examples: List[Dict[str, Any]] = []
    for shot_id, queries in (mirror.get("queries") or {}).items():
        text = blocks_by_shot.get(shot_id)
        if text is None:
            continue
        mine = [normalise_query_pairs(query) for query in queries]
        for ident, (expected, must_items) in wanted.items():
            if expected not in mine:
                continue
            matched += 1
            edges = []
            for item in must_items:
                key = entry_key(item, graph)
                edge_id = norm_index.get(key) if key is not None else None
                edge = graph.by_id.get(edge_id) if edge_id else None
                if edge is not None:
                    edges.append(edge)
            for edge in edges:
                required_total += 1
                if not all(_member_present(text, member, graph.nodes)
                           for member in edge.members):
                    dropped += 1
                    if len(examples) < 5:
                        examples.append({"shot_id": shot_id, "entry": ident,
                                         "edge_id": edge.edge_id})
    if not matched:
        return {"id": "Q6b_required_edges_dropped_by_budget", "status": NA,
                "matched_shots": 0, "required_edges": 0, "dropped": 0,
                "note": ("这一跑发出的逐镜查询与 held-out 的 `q` 一条都对不上："
                         "required 边无法归属到镜头，`required_edges_dropped_by_budget` "
                         "记 not_measured（**不得**读成 0 条丢弃）。原因与 Q5 的运行侧"
                         "同源；见 knowledge_quality.json 的 Q5 行")}
    return {"id": "Q6b_required_edges_dropped_by_budget",
            "status": PASS if dropped == 0 else FAIL,
            "matched_shots": matched, "required_edges": required_total,
            "dropped": dropped, "examples": examples,
            "note": (f"{matched} 个镜头的查询 join 上了 held-out："
                     f"{required_total} 条 required 边里 {dropped} 条在真的发出的 "
                     f"prompt 里找不到（成员不全）")}


def _member_present(text: str, member, nodes) -> bool:
    from tools.holdout_score import _node_names  # noqa: PLC0415 - 与 Q6b 同源

    return any(name and name in text
               for name in _node_names(nodes.get(member.node_id),
                                       member.node_id))


def audit_trace(rows: Sequence[Dict[str, Any]], *, plan_cap: int = DEFAULT_PLAN_CAP,
                shot_cap: int = DEFAULT_SHOT_CAP, graph=None,
                entries=None, mirror=None) -> Dict[str, Any]:
    """核心：逐行读 `llm_trace.jsonl`，量**真正发出的**注入块。"""
    from block_director.layer5_orchestrator.planner import NO_KNOWLEDGE  # noqa: PLC0415

    markers = scope_markers()
    plan_calls: List[Dict[str, Any]] = []
    shot_calls: List[Dict[str, Any]] = []
    blocks_by_shot: Dict[str, str] = {}
    without = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        messages = prompt_messages(row)
        found: Optional[Dict[str, Any]] = None
        scope = ""
        for scope_name in ("plan", "shot"):
            for text in messages:
                located = locate_knowledge(text, markers[scope_name])
                if located is not None:
                    found, scope = located, scope_name
                    break
            if found is not None:
                break
        if found is None or found["block"].strip() == NO_KNOWLEDGE:
            without += 1
            continue
        record = {"request_id": str(row.get("request_id") or ""),
                  "purpose": str(row.get("purpose") or ""),
                  "tokens": int(found["tokens"]),
                  "locator": str(found["locator"])}
        if scope == "plan":
            plan_calls.append(record)
        else:
            shot_id = shot_id_of("\n".join(messages))
            record["shot_id"] = shot_id
            shot_calls.append(record)
            if shot_id and shot_id not in blocks_by_shot:
                blocks_by_shot[shot_id] = found["block"]
    plan_scope = _cap_verdict("plan", plan_calls, int(plan_cap),
                              CAP_KEYS["plan"])
    shot_scope = _cap_verdict("shot", shot_calls, int(shot_cap),
                              CAP_KEYS["shot"])
    measured = [item for item in (plan_scope, shot_scope)
                if item["status"] != NA]
    token_status = (FAIL if any(item["status"] == FAIL for item in measured)
                    else (PASS if measured else NA))
    drops = required_edge_drop_audit(graph=graph, entries=entries, mirror=mirror,
                                     blocks_by_shot=blocks_by_shot)
    return {
        "calls_with_knowledge": len(plan_calls) + len(shot_calls),
        "calls_without_knowledge": without,
        "plan_scope": plan_scope,
        "shot_scope": shot_scope,
        "token_caps": {"status": token_status,
                       "note": (plan_scope["note"] + "；" + shot_scope["note"])},
        "required_edges_dropped_by_budget": drops,
        "status": token_status,
        "complete": bool(drops["status"] != NA),
        "note": ("token 半边判硬；required 半边 " + drops["status"]),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="injection_audit")
    parser.add_argument("--llm-trace", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--shots", default="")
    parser.add_argument("--audit-log", default="")
    parser.add_argument("--holdout", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--nodes", default="knowledge/hypergraph.nodes.jsonl")
    parser.add_argument("--edges", default="knowledge/hypergraph.edges.jsonl")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--plan-cap", type=int, default=0)
    parser.add_argument("--shot-cap", type=int, default=0)
    args = parser.parse_args(list(argv[1:]) if argv else None)

    from block_director.contracts.config import AppConfig  # noqa: PLC0415

    defaults = AppConfig().rag
    plan_cap = int(args.plan_cap or getattr(defaults, "plan_prefetch_tokens",
                                            DEFAULT_PLAN_CAP))
    shot_cap = int(args.shot_cap or getattr(defaults, "max_tokens_per_call",
                                            DEFAULT_SHOT_CAP))
    trace = Path(args.llm_trace)
    if not trace.is_file():
        print(f"INCOMPLETE: {trace} 不存在——注入通道没有读数来源")
        return 2
    rows = [json.loads(line) for line in
            trace.read_text(encoding="utf-8").splitlines() if line.strip()]
    graph = load_graph(ROOT / args.nodes, ROOT / args.edges)
    entries = [json.loads(line) for line in
               (ROOT / args.holdout).read_text(encoding="utf-8").splitlines()
               if line.strip()] if (ROOT / args.holdout).is_file() else None
    mirror = run_query_mirror(args.audit_log, run_id=args.run_id)
    report = audit_trace(rows, plan_cap=plan_cap, shot_cap=shot_cap, graph=graph,
                         entries=entries, mirror=mirror)
    report["llm_trace"] = str(trace)
    report["audit_log"] = str(args.audit_log or "")
    report["run_id"] = args.run_id
    report["caps"] = {"plan": plan_cap, "shot": shot_cap, "keys": dict(CAP_KEYS)}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == PASS else 1


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
