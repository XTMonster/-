"""Q5 的运行侧 join 只能读**真实发出**的查询（§4.1b 硬规则 2）。

为什么单开一个文件（2026-10-03 实测，run `b4626c726435`）：`shots.json` 的
`camera`/`movements` 是**运行结束时的状态**，而逐镜检索发生在每一次 editor
调用**之前**——6 镜里有 **2 镜**两条串不同：

    shot_001  发出 `景别=MCU`
              导出后重推 `景别=MCU；镜头=50mm；运镜=dolly_in；特效=smoke；特效=glow`
    shot_003  发出 `景别=MCU；对白=dialogue`
              导出后重推 `景别=MCU；镜头=50mm；运镜=dolly_in；动作=look_at；动作=nod；对白=dialogue`

（发出侧取自 `audit_log.jsonl` 的 `retrieval_call.data.query`；重推侧取自
`docs/evidence/20261003_real/export/shots.json` + `shot_constraint_query()`。）
`shots.json` 是被测实现自己写的**汇总**字段，拿它重推 join 键就是把"另一次
运行"当成"这一次"——§4.1b 硬规则 2 明列允许的通道只有 `audit_log.jsonl` 的
**逐次事件**。所以：emitted = join 键；derived = 漂移诊断。

同一节还钉住两条判据边界：**相等**（subset 只作诊断，不许悄悄进分子）与
**分母为 0 判失败**（硬规则 1；夹具侧不足 30 条那一档仍按 §4.1b 第一步记
`not_measured`，那一档规范原文写死了）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import quality as Q  # noqa: E402

LIVE_MANIFEST = ROOT / "knowledge" / "hypergraph.manifest.json"
LIVE_CASES = ROOT / "knowledge" / "cases.jsonl"


def _live_knowledge() -> dict:
    from block_director.knowledge.cases import manifest_fingerprint as cases_fp
    from block_director.knowledge.hypergraph import manifest_fingerprint as hg_fp

    return {"hypergraph_fingerprint": hg_fp(LIVE_MANIFEST.parent),
            "cases_index_fingerprint": cases_fp(LIVE_CASES.parent),
            "cases_backend": "hybrid"}


def _shot(record_id, *, shot_type="MCU", lens=50.0, movements=(), dialogues=()):
    """一镜的 `shots.json` 记录（形状与 `delivery/manifest.py` 一致）。"""
    return {"shot_id": record_id, "shot_type": shot_type,
            "camera": {"lens": lens},
            "movements": [{"kind": kind} for kind in movements],
            "dialogue_ids": [f"d{index}" for index in range(len(dialogues))]}


def _write_shots(tmp_path, shots, *, knowledge="live"):
    path = tmp_path / "shots.json"
    payload = {"shots": shots}
    payload["knowledge"] = _live_knowledge() if knowledge == "live" else knowledge
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_audit(tmp_path, events, *, name="audit_log.jsonl"):
    """把 `retrieval_call` 事件写成 `audit_log.jsonl` 的**形状**（一行一事件）。"""
    path = tmp_path / name
    lines = []
    for event in events:
        payload = {"kind": "retrieval_call", "level": "info",
                   "message": "检索：卡片 5 / 超边 5 / 案例 0",
                   "run_id": event.get("run_id", "ut-run"),
                   "data": {"event": "retrieval_call",
                            "scope": event.get("scope", "shot"),
                            "shot_id": event.get("shot_id"),
                            "query": event.get("query", ""),
                            "backend": "hypergraph", "cards": 5, "edges": 5}}
        lines.append(json.dumps(payload, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _join(entries, shots, audit, **kwargs):
    return Q.q5_run_join(entries, shots, audit_path=audit,
                         manifest_path=LIVE_MANIFEST, cases_path=LIVE_CASES,
                         **kwargs)


# --------------------------------------------------------------- 通道：发出的串


def test_the_join_uses_the_query_that_was_actually_sent(tmp_path):
    """正对照：join 键是 audit 里的 `data.query`，不是从 `shots.json` 重推的串。

    oracle 写的一条 `q` 与**发出**串相等、另一条与**重推**串相等——只有前者
    能进分母。这一条用例把"通道"钉死：换回重推实现，两条断言同时红。
    """
    shots = _write_shots(tmp_path, [_shot("shot_001", shot_type="MCU", lens=50.0,
                                          movements=["dolly_in"])])
    audit = _write_audit(tmp_path, [{"shot_id": "shot_001", "query": "景别=MCU"}])
    entries = [
        {"id": "hq_sent", "q": "景别=MCU", "expect_movements": ["dolly_in"]},
        {"id": "hq_derived",
         "q": "景别=MCU；镜头=50mm；运镜=dolly_in", "expect_movements": ["dolly_in"]},
    ]
    report = _join(entries, shots, audit)
    assert report["channel"] == "audit"
    assert report["denominator"] == 1
    assert [item["entry"] for item in report["matched_shots"]] == ["hq_sent"]
    assert report["numerator"] == 1 and report["status"] == Q.PASS


def test_the_rederived_query_is_a_drift_diagnostic_and_never_a_join_key(tmp_path):
    """负对照：`shots.json` 重推出来的串与发出串不同时，必须**记漂移**、且不参与 join。

    这正是 2026-10-03 那一跑的形状（shot_001 / shot_003）。重推串如果被当成
    join 键，这条用例的 `denominator` 会变成 1——那是"另一次运行"的数。
    """
    shots = _write_shots(tmp_path, [_shot("shot_001", shot_type="MCU", lens=50.0,
                                          movements=["dolly_in"])])
    audit = _write_audit(tmp_path, [{"shot_id": "shot_001", "query": "景别=MCU"}])
    entries = [{"id": "hq_derived",
                "q": "景别=MCU；镜头=50mm；运镜=dolly_in",
                "expect_movements": ["dolly_in"]}]
    report = _join(entries, shots, audit)
    assert report["denominator"] == 0
    assert report["drift"] == [{
        "shot_id": "shot_001",
        "emitted": "景别=MCU",
        "derived": "景别=MCU；镜头=50mm；运镜=dolly_in",
    }]
    # 重推串仍然如实报出来（信息量保留），但它不是 join 键。
    assert "景别=MCU；镜头=50mm；运镜=dolly_in" in report["plan_queries"]
    assert report["emitted_queries"] == {"shot_001": ["景别=MCU"]}


def test_events_from_other_runs_are_never_mixed_in(tmp_path):
    """审计日志是**累积**的（本机那份 6.8k 事件、162 跑）：不给 run_id 时不许瞎猜。"""
    shots = _write_shots(tmp_path, [_shot("shot_001")])
    audit = _write_audit(tmp_path, [
        {"run_id": "run-a", "shot_id": "shot_001", "query": "景别=MCU"},
        {"run_id": "run-b", "shot_id": "shot_001", "query": "景别=CU"},
    ])
    entries = [{"id": "hq_1", "q": "景别=MCU", "expect_movements": ["固定"]}]
    mixed = _join(entries, shots, audit)
    assert mixed["status"] == Q.NA and mixed["channel"] == "absent"
    assert "run_id" in mixed["note"] and mixed["run_ids"] == ["run-a", "run-b"]

    # 给了 filter 就能用，而且只算那一跑的事件。
    picked = _join(entries, shots, audit, run_id="run-a")
    assert picked["channel"] == "audit"
    assert picked["denominator"] == 1 and picked["numerator"] == 1


def test_without_an_audit_log_the_run_side_is_not_evidence(tmp_path):
    """没有 `--audit-log` ⇒ 运行侧**没有**可用通道：记 `not_measured`，永不判过。"""
    shots = _write_shots(tmp_path, [_shot("shot_001")])
    entries = [{"id": "hq_1", "q": "景别=MCU", "expect_movements": ["固定"]}]
    report = Q.q5_run_join(entries, shots, manifest_path=LIVE_MANIFEST,
                           cases_path=LIVE_CASES)
    assert report["status"] == Q.NA
    assert report["channel"] == "absent"
    assert "audit_log.jsonl" in report["note"]
    assert "retrieval_call" in report["note"]


def test_a_run_with_knowledge_off_is_not_measured_not_a_pass(tmp_path):
    """这一跑压根没检索（RAG 关掉）：没有发出过查询 ⇒ 测不了，不许判过。"""
    shots = _write_shots(tmp_path, [_shot("shot_001")])
    audit = _write_audit(tmp_path, [{"scope": "plan", "shot_id": None,
                                     "query": "景别=MCU；剧本……"}])
    entries = [{"id": "hq_1", "q": "景别=MCU", "expect_movements": ["固定"]}]
    report = _join(entries, shots, audit)
    assert report["status"] == Q.NA and report["channel"] == "absent"
    assert "逐镜" in report["note"]


# --------------------------------------------------------------- 判据：相等与分母


def test_the_join_is_equality_and_subset_stays_a_diagnostic(tmp_path):
    """§4.1b 的 join 判据是**键值对集合相等**：子集命中只报数、不进分子。"""
    shots = _write_shots(tmp_path, [_shot("shot_001", shot_type="CU", lens=85.0,
                                          dialogues=["a"])])
    audit = _write_audit(tmp_path, [
        {"shot_id": "shot_001", "query": "景别=CU；镜头=85mm；对白=dialogue"}])
    entries = [{"id": "hq_subset", "q": "景别=CU；镜头=85mm",
                "expect_movements": ["固定"]}]
    report = _join(entries, shots, audit)
    assert report["denominator"] == 0 and report["subset_denominator"] == 1
    assert report["numerator"] == 0


def test_a_zero_denominator_after_a_measured_run_is_a_failure(tmp_path):
    """硬规则 1：这次运行**真的发过**逐镜查询，但一条都对不上 ⇒ 分母 0 ⇒ 判失败。

    夹具侧不足 30 条那一档是规范原文写死的 `not_measured`（见下一个用例）；
    这一档不同：证据齐、跑过、量出来是 0——记 `not_measured` 就违反硬规则 1。
    """
    shots = _write_shots(tmp_path, [_shot("shot_001", shot_type="MCU", lens=50.0)])
    audit = _write_audit(tmp_path, [{"shot_id": "shot_001", "query": "景别=MCU"}])
    entries = [{"id": "hq_1", "q": "景别=MS；镜头=35mm", "expect_movements": ["固定"]}]
    report = _join(entries, shots, audit)
    assert report["status"] == Q.FAIL
    assert report["denominator"] == 0
    assert "硬规则 1" in report["note"]


def test_the_fixture_floor_keeps_the_spec_wording(tmp_path):
    """§4.1b 第一步：带 `expect_movements` 的条目 < 30 ⇒ `not_measured`，不得判过。"""
    shots = _write_shots(tmp_path, [_shot("shot_001")])
    audit = _write_audit(tmp_path, [{"shot_id": "shot_001", "query": "景别=MCU"}])
    entries = [{"id": f"hq_{index}", "q": "景别=MCU",
                "expect_movements": ["固定"]} for index in range(5)]
    metric = Q.q5_movement_hit(entries, shots, audit_path=audit,
                               manifest_path=LIVE_MANIFEST, cases_path=LIVE_CASES)
    assert metric["status"] == Q.NA
    assert metric["fixture_items"] == 5
    assert "夹具" in metric["note"]


def test_a_stale_run_never_shows_up_as_a_pass_in_the_metric(tmp_path):
    """上一代索引跑出来的证据：分子分母照报，状态 `not_measured` ＋ `stale_evidence`。"""
    shots = _write_shots(tmp_path, [_shot("shot_001")],
                         knowledge={"hypergraph_fingerprint": "0" * 64,
                                    "cases_index_fingerprint": "1" * 64,
                                    "cases_backend": "hybrid"})
    audit = _write_audit(tmp_path, [{"shot_id": "shot_001", "query": "景别=MCU"}])
    entries = [{"id": f"hq_{index}", "q": "景别=MCU",
                "expect_movements": ["固定"]} for index in range(30)]
    metric = Q.q5_movement_hit(entries, shots, audit_path=audit,
                               manifest_path=LIVE_MANIFEST, cases_path=LIVE_CASES)
    assert metric["status"] == Q.NA
    assert metric["run_stale_evidence"] is True
    assert metric["run_denominator"] == 30     # 算术照报


# --------------------------------------------------------------- 真实产物（对拍）


def test_the_committed_real_run_drift_is_reproducible():
    """盘上那一跑的重推/发出漂移必须还能复算（证据文件是提交进去的）。

    这条用例是"Q5 通道选错"这件事的**活证据**：它读提交里的 `shots.json` 与
    `audit_log.jsonl` 分片，复算 2 镜漂移。文件缺失时用例判红——不是跳过：
    §4.1a 要求真实运行的证据入库（`tests/test_acceptance_fixtures_present.py`
    同一口径）。
    """
    run_dir = ROOT / "docs" / "evidence" / "20261003_real_glm"
    shots = run_dir / "export" / "shots.json"
    audit = run_dir / "audit_log.jsonl"
    assert shots.is_file(), f"真实运行的 shots.json 不在库里：{shots}"
    assert audit.is_file(), f"真实运行的 audit_log.jsonl 分片不在库里：{audit}"
    payload = json.loads(shots.read_text(encoding="utf-8"))
    mirror = Q.run_query_mirror(audit)
    assert mirror["status"] == "ok", mirror["note"]
    drift = Q.q5_query_drift(payload.get("shots") or [], mirror["queries"])
    assert len(drift) >= 2, drift
    assert {item["shot_id"] for item in drift} >= {"shot_001", "shot_003"}
    # 夹具侧与运行侧的两个数必须都能报出来（不是 not_measured 的沉默）。
    entries = [json.loads(line) for line in
               (ROOT / "fixtures" / "knowledge_holdout.jsonl").read_text(
                   encoding="utf-8").splitlines() if line.strip()]
    report = Q.q5_run_join(entries, shots, audit_path=audit,
                           manifest_path=LIVE_MANIFEST, cases_path=LIVE_CASES)
    assert report["channel"] == "audit"
    assert report["fixture_entries"] >= Q.MIN_Q5_FIXTURE_ITEMS
    assert report["status"] in (Q.PASS, Q.FAIL), report["note"]
