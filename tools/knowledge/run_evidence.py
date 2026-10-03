"""Q5 运行侧证据的**唯一通道**：`audit_log.jsonl` 里真实发出的逐镜查询。

§4.1b 硬规则 2（禁止自证）把判据允许读的东西写死成四类，其中"运行期到底发了
什么查询"只有一条通道——`audit_log.jsonl` 的**逐次事件**。在此之前
`tools/knowledge/quality.py` 是从 `shots.json`（**被测实现自己写的交付汇总**）
重推查询串，"允许读"的清单里没有它，而且它不是同一时刻的快照：

    2026-10-03 实测（run `b4626c726435`，6 镜）——6 镜里 **2 镜**两条串不同：
      shot_001  发出 `景别=MCU`
                导出后重推 `景别=MCU；镜头=50mm；运镜=dolly_in；特效=smoke；特效=glow`
      shot_003  发出 `景别=MCU；对白=dialogue`
                导出后重推 `景别=MCU；镜头=50mm；运镜=dolly_in；动作=look_at；动作=nod；对白=dialogue`

    原因是时序，不是笔误：逐镜检索发生在这一镜的 editor 调用**之前**（那时
    `camera`／`movements` 还没被工具调用与 framing 求解写进去），而 `shots.json`
    是**收尾时**的状态。所以"重推串"量的是另一次运行，唯一能与 held-out 的 `q`
    对拍的是当年真的发出去了的那一条。

本模块只做三件事，全部是纯函数：

* :func:`normalise_query_pairs`——`键=值；键=值` → `{(键, 值)}` 的归一化集合。
  归一化口径与 §4.1b 的 Q5 行逐字对应（**去空格 / 全半角 / 别名**），别名表用
  索引侧唯一那份（`hypergraph.VALUE_ALIASES`），两边不会各写一套。
* :func:`run_query_mirror`——把一份（或一整份）`audit_log.jsonl` 读成
  `{shot_id: [真实发出的查询串, …]}`，并在"读不出证据"时给出**具名理由**。
* 别无其它：join 的判据仍然在 `quality.q5_run_join`，这里不重写它。

审计日志是**累积**的（本机那一份 6839 个事件、162 跑）。多跑混在一份文件里时
本模块**拒绝作答**（记 `not_measured` 并列出看到的 run_id），要么给这一跑的
分片，要么用 `run_id=` 显式点名——静默挑一个是最典型的"过期/错配证据被当成
现行证据"。
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

NA = "not_measured"


def normalise_query_pairs(text: Any) -> frozenset:
    """`键=值；键=值` → 归一化后的 `{(键, 值)}` 集合。

    口径与 §4.1b 的 Q5 行逐字对应：**去空格 / 全半角 / 别名**。别名表是索引侧
    唯一那份（`hypergraph.VALUE_ALIASES`，`static` → `固定`、`甩镜` → `whip_pan`…）：
    两边都用它，join 才不会因为一边写引擎名、一边写中文别名而永远错开。
    """
    from block_director.knowledge.hypergraph import VALUE_ALIASES  # noqa: PLC0415

    pairs = set()
    for chunk in str(text or "").replace(";", "；").split("；"):
        if "=" not in chunk:
            continue
        key, _, raw = chunk.partition("=")
        key = unicodedata.normalize("NFKC", key).strip()
        value = unicodedata.normalize("NFKC", raw).strip().replace(" ", "")
        if not key or not value:
            continue
        pairs.add((key, VALUE_ALIASES.get(value, value)))
    return frozenset(pairs)


def run_query_mirror(audit_path: Any, *, run_id: str = "") -> Dict[str, Any]:
    """从 `audit_log.jsonl` 读出**这一跑真实发出**的逐镜查询。

    返回 `{"status", "queries", "run_ids", "events", "shot_events", "path", "note"}`：

    * `status == "ok"`：`queries` 是 `{shot_id: [查询串, …]}`（同一镜的重复检索
      按出现顺序去重）；
    * `status == "not_measured"`：`note` 写明**为什么**读不出来（文件不在、
      一行都解析不了、混了多跑、这一跑没有逐镜检索事件……）。

    "读不出来"一律记 `not_measured`，**永不判过**——这与
    `quality.e1_evidence_is_stale` 的处置同形（缺证据不是通过）。
    """
    detail: Dict[str, Any] = {"status": NA, "queries": {}, "edges": {},
                              "run_ids": [],
                              "events": 0, "shot_events": 0, "unparsed": 0,
                              "path": str(audit_path or ""), "note": ""}
    if not audit_path:
        detail["note"] = ("没有 --audit-log：Q5 的 join 键必须是**真实发出**的查询"
                          "（§4.1b 硬规则 2）；没有 audit_log.jsonl 的 retrieval_call "
                          "事件就没有这条通道")
        return detail
    path = Path(audit_path)
    if not path.is_file():
        detail["note"] = (f"审计日志 {path} 不存在：Q5 的 join 键读不出来"
                          f"（§4.1b 硬规则 2 只认 audit_log.jsonl 的逐次事件）")
        return detail
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        detail["note"] = f"审计日志 {path} 读不出来（{exc}）：Q5 的 join 键没有来源"
        return detail

    seen_runs: List[str] = []
    queries: Dict[str, List[str]] = {}
    #: 2026-10-03：这一镜**真的召回**了哪些超边。Q5 的实读数（诊断）要按
    #: "这条条目的期望边有没有被这一镜检索到"对齐——它比"发出的查询串与标注的
    #: `q` 逐字相等"可达得多（见 `quality.q5_retrieval_join` 的抬头）。
    recalled: Dict[str, List[str]] = {}
    events = shot_events = unparsed = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            unparsed += 1
            continue
        if not isinstance(payload, dict):
            unparsed += 1
            continue
        data = payload.get("data") or {}
        kind = str(payload.get("kind") or data.get("event") or "")
        if kind != "retrieval_call":
            continue
        events += 1
        identity = str(payload.get("run_id") or "")
        if identity and identity not in seen_runs:
            seen_runs.append(identity)
        if run_id and identity and identity != run_id:
            continue
        if str(data.get("scope") or "") != "shot":
            continue
        shot_id = str(data.get("shot_id") or "")
        query = str(data.get("query") or "").strip()
        if not shot_id or not query:
            continue
        shot_events += 1
        bucket = queries.setdefault(shot_id, [])
        if query not in bucket:
            bucket.append(query)
        edge_bucket = recalled.setdefault(shot_id, [])
        for edge_id in (data.get("edge_ids") or []):
            text = str(edge_id or "").strip()
            if text and text not in edge_bucket:
                edge_bucket.append(text)

    detail["run_ids"] = sorted(seen_runs)
    detail["events"] = events
    detail["shot_events"] = shot_events
    detail["unparsed"] = unparsed
    if not events:
        detail["note"] = (f"{path} 里没有 retrieval_call 事件"
                          f"（解析不了的行 {unparsed} 条）：这份文件证明不了"
                          f"这一跑发过什么查询")
        return detail
    if not run_id and len(seen_runs) > 1:
        detail["note"] = (f"{path} 里混了 {len(seen_runs)} 跑（run_id="
                          f"{'、'.join(seen_runs[:4])}{'…' if len(seen_runs) > 4 else ''}）："
                          f"不给 --audit-run-id 就无法判定哪一跑是这一份 shots.json 的；"
                          f"请给分片或用 --audit-run-id 点名")
        return detail
    if run_id and not shot_events:
        detail["note"] = (f"run_id={run_id} 在这份审计日志里没有逐镜检索事件："
                          f"核对该跑的 run_id 与分片")
        return detail
    if not queries:
        detail["note"] = (f"{path} 里的 retrieval_call 全是 plan scope"
                          f"（events={events}、shot scope=0）：这一跑没有逐镜检索，"
                          f"Q5 的 join 没有可用的真实查询")
        return detail
    detail["status"] = "ok"
    detail["queries"] = {key: list(value) for key, value in sorted(queries.items())}
    detail["edges"] = {key: list(value) for key, value in sorted(recalled.items())}
    if unparsed:
        detail["note"] = f"解析不了的行 {unparsed} 条（已跳过，未计入证据）"
    return detail
