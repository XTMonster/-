"""v1.5 §5.4 / 卡 P4-T4：破例辩护对拍（声明 vs 实测）的纯函数与交付字段。

红线口径（本用例一并在断言里钉住）：

* 对拍**只记录、不设门**——它不参与任何通过/不通过判定（设门属 OPEN_ITEMS
  D11 的议题，须用户裁决）；这里的断言只检查"算得对、写得全、不猜"。
* `shots.json` 收新字段，`prompts.md` **不含**引擎内部键（P15 纪律）；
* 没有审核结果时写"四个空集"，不是省略、更不是编一个通过的结论。
"""

from __future__ import annotations

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.beats import (
    RuleJustification,
    reconcile_justifications,
)
from block_director.contracts.enums import Severity
from block_director.contracts.plan import Plan
from block_director.delivery.manifest import build_manifest
from block_director.delivery.prompts import render_prompt_sheet
from block_director.layer5_orchestrator.driver import PrevisDriver

AUDIT_KEYS = ("declared_breaks", "declared_follows", "detected_violations",
              "undeclared_violations", "declared_but_clean")


def _plan() -> Plan:
    return Plan.from_dict({
        "scene_heading": "INT. 码头 - 日", "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "对峙",
             "shot_type": "MS", "duration_frames": 48,
             "characters": ["char_001"],
             "beats": [{"t": 0.0, "subject": "char_001", "verb": "stand"},
                       {"t": 0.5, "subject": "char_001", "verb": "turn_head",
                        "face_to": "camera"}],
             "composition": {"rule": "thirds",
                             "subject_position": "left_third"},
             "rule_justifications": [
                 {"rule": "R001", "action": "follow"},
                 {"rule": "R011", "action": "break",
                  "reason": "关系破裂，故意越轴", "precedent": "《闪灵》"}]}]})


# ---------------------------------------------------------------- 纯函数
def test_diff_sets_are_exact():
    result = reconcile_justifications(
        [{"rule": "R001", "action": "break", "reason": "x"},
         {"rule": "R005", "action": "follow"}],
        ["R001", "R011"])
    assert result["declared_breaks"] == ["R001"]
    assert result["declared_follows"] == ["R005"]
    assert result["detected_violations"] == ["R001", "R011"]
    #: 没说就破的（R011）与被声明且真破的（R001）分开。
    assert result["undeclared_violations"] == ["R011"]
    assert result["declared_but_clean"] == []


def test_declared_but_clean_is_the_other_side():
    """声明破例、审核器却没报它 ⇒ 进 `declared_but_clean`，不进 undeclared。"""
    result = reconcile_justifications(
        [{"rule": "R019", "action": "break", "reason": "有意"}], [])
    assert result["declared_but_clean"] == ["R019"]
    assert result["undeclared_violations"] == []
    assert result["detected_violations"] == []


def test_accepts_dataclass_and_dict_and_is_deterministic():
    items = [RuleJustification(rule="R001", action="break", reason="y"),
             {"rule": "R001", "action": "break", "reason": "重复"},
             {"rule": "", "action": "break"}]
    first = reconcile_justifications(items, ["R001", "R001", ""])
    second = reconcile_justifications(items, ["R001", "R001", ""])
    assert first == second, "同一输入必须逐字节相同"
    assert first["declared_breaks"] == ["R001"], "同 rule 只留一条"
    assert first["detected_violations"] == ["R001"], "空 rule 不入集"
    assert first["undeclared_violations"] == []


def test_empty_inputs_yield_empty_sets_not_none():
    result = reconcile_justifications([], [])
    assert set(result) == set(AUDIT_KEYS)
    assert all(result[key] == [] for key in AUDIT_KEYS)


# ------------------------------------------------------- AuditResult 兼容
def test_audit_result_dict_is_unchanged_without_reconciliation():
    plain = AuditResult(passed=True, target="shot_001")
    assert "justification_audit" not in plain.to_dict(), \
        "没跑对拍的旧路径必须逐字节不变（NFR-4）"


def test_audit_result_dict_carries_reconciliation_when_present():
    result = AuditResult(
        passed=False, target="shot_001",
        errors=[AuditError(rule="R011", message="越轴",
                           severity=Severity.ERROR)])
    result.justification_audit = reconcile_justifications([], ["R011"])
    payload = result.to_dict()
    assert payload["justification_audit"]["undeclared_violations"] == ["R011"]


# ------------------------------------------------------------ 交付清单
def test_shots_json_carries_new_fields_and_empty_audit_by_default():
    manifest = build_manifest(_plan(), generated_at="t")
    shot = manifest["shots"][0]
    assert shot["beats"][0]["verb"] == "stand"
    assert shot["composition"]["rule"] == "thirds"
    assert shot["rule_justifications"][1]["action"] == "break"
    #: 没有 build_summary ⇒ 没审过 ⇒ 四个空集（"查过、两边都空"），不省略也不编。
    assert set(shot["justification_audit"]) == set(AUDIT_KEYS)
    assert all(shot["justification_audit"][key] == [] for key in AUDIT_KEYS)


def test_shots_json_reads_reconciliation_from_build_results():
    reconciliation = reconcile_justifications(
        [{"rule": "R001", "action": "break", "reason": "越轴换侧"}],
        ["R001", "R011"])
    manifest = build_manifest(
        _plan(), generated_at="t",
        build_summary={"results": [{"shot_id": "shot_001",
                                    "justification_audit": reconciliation}]})
    audit = manifest["shots"][0]["justification_audit"]
    assert audit["declared_breaks"] == ["R001"]
    assert audit["undeclared_violations"] == ["R011"]
    assert audit["declared_but_clean"] == []


def test_prompts_md_does_not_leak_internal_keys():
    sheet = render_prompt_sheet(_plan())
    for key in ("rule_justifications", "justification_audit",
                "undeclared_violations", "declared_breaks", "composition"):
        assert key not in sheet, f"prompts.md 不该出现引擎内部键 {key}"


# ------------------------------------------- 驱动器把对拍写进交付结果
def test_driver_records_reconciliation_into_build_results():
    """`_record_justification_audit` 是唯一的写入点；找不到 result 就跳过。"""
    driver = PrevisDriver.__new__(PrevisDriver)
    driver.build_summary = {"results": [{"shot_id": "shot_001"},
                                        {"shot_id": "shot_002"}]}
    reconciliation = reconcile_justifications([], ["R011"])
    driver._record_justification_audit("shot_002", reconciliation)
    assert "justification_audit" not in driver.build_summary["results"][0]
    assert driver.build_summary["results"][1]["justification_audit"] == \
        reconciliation
    #: 结果集不存在时是"静默跳过"而不是抛异常：交付层会用四个空集兜底。
    driver.build_summary = {}
    driver._record_justification_audit("shot_001", reconciliation)
