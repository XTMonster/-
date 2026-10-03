"""意图轴必须留在**真实运行**的证据里（v1.5 §2.3d T3 / `ACCEPTANCE_STATUS.md` §五十）。

为什么钉在证据上而不是只钉在生产者上：契约串的生产者可以是对的，而**接线断了**
（计划里没这个字段、`shots.json` 不落盘、发出的那一刻镜头对象还没带上它），
链上照样全绿——这正是这一轮之前"意图轴从来不在发出的查询里"的状态。
所以这条用例读**提交进库的真实运行**（`docs/evidence/20261003_intent/`）逐条对拍，
同时拿修复前那一跑（`docs/evidence/20261003_real_ds/`）当**反向对照**：
它必须**没有** `意图=`，否则"这条轴是这次改动带来的"就不成立。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import VALUE_DOMAINS  # noqa: E402
from tools.knowledge.quality import plan_query_of_shot  # noqa: E402

AFTER = ROOT / "docs" / "evidence" / "20261003_intent"
BEFORE = ROOT / "docs" / "evidence" / "20261003_real_ds"
INTENTS = set(VALUE_DOMAINS["intent"])


def _shot_queries(directory):
    rows = []
    for line in (directory / "audit_log.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        data = event.get("data") or {}
        if event.get("kind") == "retrieval_call" and data.get("scope") == "shot":
            rows.append((str(data.get("shot_id")), str(data.get("query") or "")))
    return rows


def test_every_emitted_shot_query_carries_a_closed_set_intent():
    queries = _shot_queries(AFTER)
    assert len(queries) >= 6, queries
    for shot_id, query in queries:
        pairs = dict(part.split("=", 1) for part in query.split("；") if "=" in part)
        assert "意图" in pairs, f"{shot_id} 发出的串里没有意图轴：{query}"
        assert pairs["意图"] in INTENTS, f"{shot_id} 的意图不在闭集里：{pairs['意图']}"


def test_the_run_before_the_axis_really_had_no_intent():
    """反向对照：修复前那一跑必须没有 `意图=`（否则上面的断言没有鉴别力）。"""
    queries = _shot_queries(BEFORE)
    assert queries, "反向对照的证据目录不存在或读不到"
    assert all("意图=" not in query for _shot_id, query in queries)


def test_the_exported_shots_agree_with_what_was_emitted():
    """`shots.json` 的 `intent_type` 必须与发出的串**同值**。

    **注意不能要求整串相等**：`shots.json` 是运行结束时的快照（相机已解算，
    于是多出 `镜头=`/计划排的 `运镜=`），而逐镜检索发生在 editor 调用**之前**——
    这正是 §4.1b 硬规则 2 把 join 键定在 audit 上、把重推串只当诊断的原因
    （见 `tests/test_q5_audit_channel.py`）。意图轴不受这个时序影响：
    它在**检索前**就在计划上。
    """
    payload = json.loads((AFTER / "export" / "shots.json").read_text(encoding="utf-8"))
    emitted = dict(_shot_queries(AFTER))
    assert payload["shots"], "导出里没有镜头记录"
    for record in payload["shots"]:
        shot_id = str(record["shot_id"])
        assert record["intent_type"] in INTENTS, record
        derived = plan_query_of_shot(record)
        assert f"意图={record['intent_type']}" in derived, derived
        assert f"意图={record['intent_type']}" in emitted[shot_id], (
            f"{shot_id}: 发出 {emitted[shot_id]} 与导出的意图 {record['intent_type']} 不一致")
