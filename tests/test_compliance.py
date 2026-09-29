"""剧本落实审核（v1.3 R015 / R016）。

验收基准仍是用户那份 6 镜、声明 33 秒的分镜表。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from block_director.contracts.plan import Plan
from block_director.layer1_input import parse_script
from block_director.layer5_orchestrator.compliance import (
    check_compliance,
    compliance_report,
)

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "fixtures" / "shotlist_market.md"

DECLARED_FRAMES = {1: 120, 2: 144, 3: 96, 4: 144, 5: 120, 6: 168}


def _script():
    return parse_script(MARKET)


def _plan(shots):
    return Plan.from_dict({"scene_heading": "第十四街区码头市场 - 午后",
                           "shots": shots})


def _plan_from_declarations(script, *, texts: bool = True):
    """按声明造一份**完全落实**的计划——用来当"干净"基线。"""
    shots = []
    for index, item in enumerate(script.declared_shots, start=1):
        dialogues = []
        if texts:
            for dialogue in item.dialogues:
                dialogues.append({"character_id": dialogue.character,
                                  "text": dialogue.text,
                                  "start_frame": 1, "end_frame": 10})
        shots.append({
            "shot_id": f"shot_{index:03d}", "order": index,
            "intent": item.field("作用") or "落实分镜表",
            "shot_type": item.shot_type or "MS",
            "duration_frames": DECLARED_FRAMES[item.shot_number],
            "characters": list(item.characters), "dialogues": dialogues})
    return _plan(shots)


# --------------------------------------------------------------------------- #
# 干净路径
# --------------------------------------------------------------------------- #
def test_a_faithful_plan_passes():
    script = _script()
    findings = check_compliance(_plan_from_declarations(script), script)
    errors = [item for item in findings if item.is_error]
    assert errors == [], [item.message for item in errors]


def test_report_records_declared_versus_actual():
    script = _script()
    report = compliance_report(_plan_from_declarations(script), script)
    assert report["ok"] is True
    assert report["declared_shot_count"] == 6
    assert report["plan_shot_count"] == 6
    assert report["declared_total_seconds"] == pytest.approx(33.0)
    assert report["plan_total_seconds"] == pytest.approx(33.0)
    assert report["rows"][0]["declared_frames"] == 120
    assert report["rows"][5]["plan_frames"] == 168


# --------------------------------------------------------------------------- #
# 真正要抓的三类偏差
# --------------------------------------------------------------------------- #
def test_shot_count_mismatch_is_an_error():
    """v1.2 实测把 6 个镜号压成了 2 个——这条必须拦住。"""
    script = _script()
    plan = _plan_from_declarations(script).to_dict()
    plan["shots"] = plan["shots"][:2]
    findings = check_compliance(Plan.from_dict(plan), script)
    count_errors = [item for item in findings
                    if item.is_error and "个镜号" in item.message]
    assert count_errors and "6" in count_errors[0].message
    assert "2" in count_errors[0].message


def test_duration_stretch_is_an_error():
    """v1.2 实测把声明 33 秒拉成 39.5 秒。"""
    script = _script()
    plan = _plan_from_declarations(script).to_dict()
    plan["shots"][1]["duration_frames"] = 240      # 声明 6 秒 → 被拉到 10 秒
    findings = check_compliance(Plan.from_dict(plan), script)
    duration_errors = [item for item in findings
                       if item.is_error and "镜号2" in item.message]
    assert duration_errors
    assert "144 帧" in duration_errors[0].message
    assert "240 帧" in duration_errors[0].message


def test_rewritten_dialogue_is_an_error():
    """v1.2 实测把"伊恩，这里就交给我吧！"改写成了"我是米迦尔。"。"""
    script = _script()
    plan = _plan_from_declarations(script).to_dict()
    plan["shots"][1]["dialogues"] = [
        {"character_id": "char_001", "text": "我是米迦尔。",
         "start_frame": 1, "end_frame": 10}]
    findings = check_compliance(Plan.from_dict(plan), script)
    messages = [item.message for item in findings if item.is_error]
    assert any("伊恩，这里就交给我吧！" in text for text in messages)
    assert any("剧本没有的台词" in item.message for item in findings
               if not item.is_error)


def test_shot_type_difference_is_only_a_warning():
    """景别是从「拍摄距离」映射来的，映射本身有损，因此只告警。"""
    script = _script()
    plan = _plan_from_declarations(script).to_dict()
    plan["shots"][0]["shot_type"] = "LS"           # 声明是近景（MCU）
    findings = check_compliance(Plan.from_dict(plan), script)
    assert not [item for item in findings if item.is_error]
    warnings = [item for item in findings if not item.is_error]
    assert warnings and "近景" in warnings[0].message


def test_missing_declared_dialogue_is_an_error():
    script = _script()
    plan = _plan_from_declarations(script, texts=False).to_dict()
    findings = check_compliance(Plan.from_dict(plan), script)
    assert len([item for item in findings if item.is_error]) == 6  # 六句台词


# --------------------------------------------------------------------------- #
# 边界
# --------------------------------------------------------------------------- #
def test_a_narrative_script_produces_no_findings():
    """没有分镜表就没有声明——绝不凭空发明约束。"""
    script = parse_script(ROOT / "fixtures" / "script_simple.fountain")
    plan = _plan([{"shot_id": "shot_001", "order": 1, "intent": "x",
                   "shot_type": "MS", "duration_frames": 24}])
    assert check_compliance(plan, script) == []
    assert compliance_report(plan, script)["ok"] is True


def test_no_plan_produces_no_findings():
    assert check_compliance(None, _script()) == []


# --------------------------------------------------------------------------- #
# 接线：驱动器必须在收尾时做这件事，并写进审计日志
# --------------------------------------------------------------------------- #
class _InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class _StubBuilder:
    def __init__(self):
        self.built = []

    def build(self, plan, brief=None):
        self.built.append(plan)
        return {"shots": len(plan.shots), "total_frames": plan.total_frames}


def test_driver_reports_compliance_in_the_snapshot_and_the_audit_log(tmp_path):
    """离线传输只给 2 个镜头，而剧本声明了 6 个——审核必须抓出来。"""
    import json

    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer5_orchestrator.offline import OfflineTransport
    from block_director.layer6_audit.audit_logger import AuditLogger

    script = _script()
    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(
        transport=OfflineTransport(), audit=audit,
        script=MARKET.read_text(encoding="utf-8"), parsed_script=script,
        builder=_StubBuilder(), thread_factory=_InlineThread)
    driver.run_to_completion()

    report = driver.snapshot()["compliance"]
    assert report is not None
    assert report["declared_shot_count"] == 6
    assert report["plan_shot_count"] == 2

    records = [json.loads(line) for line
               in audit.audit_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    kinds = [record["kind"] for record in records]
    assert "script_compliance" in kinds
    event = next(record for record in records
                 if record["kind"] == "script_compliance")
    assert event["data"]["declared_shot_count"] == 6
    assert event["data"]["findings"]


def test_driver_skips_compliance_for_narrative_scripts(tmp_path):
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer5_orchestrator.offline import OfflineTransport
    from block_director.layer6_audit.audit_logger import AuditLogger

    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(
        transport=OfflineTransport(), audit=audit,
        script="INT. 房间 - 日\n\n两人说话。\n",
        parsed_script=parse_script(ROOT / "fixtures" / "script_simple.fountain"),
        builder=_StubBuilder(), thread_factory=_InlineThread)
    driver.run_to_completion()
    assert driver.snapshot()["compliance"] is None


# --------------------------------------------------------------------------- #
# R013：阶段 S 读出来的注视关系必须被落实（v1.3 §3.5）
# --------------------------------------------------------------------------- #
def _gaze_plan(pairs):
    shots = [{"shot_id": "shot_001", "order": 1, "intent": "对峙",
              "shot_type": "MS", "duration_frames": 48,
              "characters": ["甲", "乙"]},
             {"shot_id": "shot_002", "order": 2, "intent": "反应",
              "shot_type": "MCU", "duration_frames": 48,
              "characters": ["乙"]}]
    if pairs is not None:
        shots[0]["gaze"] = [{"from": source, "to": target}
                            for source, target in pairs]
    return _plan(shots)


def test_r013_warns_when_the_gaze_is_not_implemented():
    from block_director.contracts.brief import SceneBrief

    brief = SceneBrief.from_dict({"gaze": [
        {"from": "甲", "to": "乙", "scope": ["镜号1"]},
        {"from": "乙", "to": "甲", "scope": ["镜号1"]}]})
    findings = check_compliance(_gaze_plan([("甲", "乙")]), None, brief=brief)
    assert [item.rule for item in findings] == ["R013"]
    assert findings[0].severity.value == "warning"
    assert "乙→甲" in findings[0].message


def test_r013_ignores_a_gaze_between_people_who_are_not_both_in_the_shot():
    """单人特写里要求搭档的视线，等于要求引擎拍一个不在场的人。"""
    from block_director.contracts.brief import SceneBrief

    brief = SceneBrief.from_dict({"gaze": [
        {"from": "甲", "to": "乙", "scope": ["all"]},
        {"from": "乙", "to": "甲", "scope": ["all"]}]})
    # shot_002 只有乙：那一镜里谁的视线都无处落实（甲不在画面里）→ 不判
    findings = check_compliance(_gaze_plan([("甲", "乙")]), None, brief=brief)
    assert [item.target for item in findings] == ["shot_001"]
    assert "乙→甲" in findings[0].message


def test_r013_is_silent_when_every_gaze_is_implemented():
    from block_director.contracts.brief import SceneBrief

    brief = SceneBrief.from_dict({"gaze": [
        {"from": "甲", "to": "乙", "scope": ["镜号1"]}]})
    assert check_compliance(_gaze_plan([("甲", "乙")]), None, brief=brief) == []


def test_r013_becomes_an_error_under_strict_audit():
    from block_director.contracts.brief import SceneBrief
    from block_director.contracts.enums import AuditLevel

    brief = SceneBrief.from_dict({"gaze": [
        {"from": "甲", "to": "乙", "scope": ["镜号1"]}]})
    findings = check_compliance(_gaze_plan([]), None, brief=brief,
                                audit_level=AuditLevel.STRICT)
    assert findings and findings[0].severity.value == "error"


def test_r013_is_independent_of_a_shot_list():
    """叙事剧本没有分镜表声明，但注视关系同样要审。"""
    from block_director.contracts.brief import SceneBrief

    brief = SceneBrief.from_dict({"gaze": [
        {"from": "甲", "to": "乙", "scope": ["all"]}]})
    findings = check_compliance(_gaze_plan([]), None, brief=brief)
    # scope=all 覆盖两个镜头，但只有 shot_001 两人都在场 → 只判它
    assert [item.rule for item in findings] == ["R013"]
    assert {item.target for item in findings} == {"shot_001"}


def test_report_records_the_brief_source():
    from block_director.contracts.brief import SceneBrief

    brief = SceneBrief.from_dict({"notes": ["x"]})
    report = compliance_report(_gaze_plan([]), None, brief=brief)
    assert report["brief_source"] == "llm"
    assert report["ok"] is True


class _GazeTransport:
    """阶段 S 说"两人互相看"，B1 却只写了一头——R013 必须抓出来。"""

    def __init__(self):
        self.purposes = []

    def chat(self, payload, timeout=120.0):
        import json

        from block_director.contracts.messages import (
            ChatReply, FunctionCall, ToolCall)

        purpose = str(payload.purpose)
        self.purposes.append(purpose)
        if purpose == "understand":
            name = "emit_scene_brief"
            args = {"gaze": [{"from": "甲", "to": "乙", "scope": ["镜号1"]},
                             {"from": "乙", "to": "甲", "scope": ["镜号1"]}]}
        elif purpose == "plan":
            name = "emit_plan"
            args = {"shots": [{"shot_id": "shot_001", "order": 1,
                               "intent": "对峙", "shot_type": "MS",
                               "duration_frames": 48,
                               "characters": ["甲", "乙"]}]}
        elif purpose == "editor":
            name = "emit_shot_draft"
            args = {"shot_id": "shot_001",
                    "gaze": [{"from": "乙", "to": "甲"}]}
        else:
            name, args = "abort", {"reason": "测试到此为止"}
        return ChatReply(tool_calls=[ToolCall(
            id=f"c{len(self.purposes)}",
            function=FunctionCall(name=name,
                                  arguments=json.dumps(args,
                                                       ensure_ascii=False)))])

    def cancel(self, request_id):
        return None


def test_driver_reports_a_gaze_the_planning_stage_failed_to_implement(tmp_path):
    """这是诉求 2/3 的核心：剧本说两人互看，落实侧只写了一头 → R013。

    同时验证"B1 自己给的注视不会被理解覆盖"——否则这条规则就变成了
    自己对自己打勾，永远发现不了问题。
    """
    import json

    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer6_audit.audit_logger import AuditLogger

    transport = _GazeTransport()
    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(transport=transport, audit=audit,
                          script="镜号1", builder=_StubBuilder(),
                          thread_factory=_InlineThread)
    driver.run_to_completion()

    assert driver.plan.shots[0].gaze == [{"from": "乙", "to": "甲"}]
    report = driver.snapshot()["compliance"]
    rules = [item["rule"] for item in report["findings"]]
    assert rules == ["R013"]
    assert "甲→乙" in report["findings"][0]["message"]
    assert report["ok"] is True                  # WARNING 不阻断交付

    records = [json.loads(line) for line
               in audit.audit_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    assert any(record["kind"] == "brief_received" for record in records)
    assert any(record["kind"] == "script_compliance" for record in records)


# --------------------------------------------------------------------------- #
# 台词是"声明"，模型不得改写或搬运（v1.3 P3 的落实侧）
# --------------------------------------------------------------------------- #
MARKET_PLAN = {"scene_heading": "第十四街区码头市场 - 午后", "shots": [
    {"shot_id": "shot_001", "order": 1, "intent": "建立场景",
     "shot_type": "MCU", "duration_frames": DECLARED_FRAMES[1],
     "characters": []},
    {"shot_id": "shot_002", "order": 2, "intent": "米迦尔请战",
     "shot_type": "CU", "duration_frames": DECLARED_FRAMES[2],
     "characters": ["米迦尔", "伊恩"]},
    {"shot_id": "shot_003", "order": 3, "intent": "伊恩回应",
     "shot_type": "MCU", "duration_frames": DECLARED_FRAMES[3],
     "characters": ["伊恩"]},
    {"shot_id": "shot_004", "order": 4, "intent": "施法准备",
     "shot_type": "CU", "duration_frames": DECLARED_FRAMES[4],
     "characters": ["米迦尔"]},
    {"shot_id": "shot_005", "order": 5, "intent": "银币变金",
     "shot_type": "MS", "duration_frames": DECLARED_FRAMES[5],
     "characters": ["偷盗者"]},
    {"shot_id": "shot_006", "order": 6, "intent": "喜剧反转",
     "shot_type": "MCU", "duration_frames": DECLARED_FRAMES[6],
     "characters": ["偷盗者"]}]}


class _RewritingTransport:
    """故意让草案改写台词，看计划侧的钉子守不守得住。"""

    def __init__(self, plan_dict):
        self.plan_dict = plan_dict
        self.editor_calls = 0

    def chat(self, payload, timeout=120.0):
        import json

        from block_director.contracts.messages import (
            ChatReply, FunctionCall, ToolCall)
        from block_director.layer5_orchestrator.editor import EDITOR_TOOL_NAME
        from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME

        purpose = str(payload.purpose)
        if purpose == "plan":
            name, args = PLAN_TOOL_NAME, self.plan_dict
        elif purpose == "editor":
            self.editor_calls += 1
            name = EDITOR_TOOL_NAME
            args = {"shot_id": f"shot_{self.editor_calls:03d}",
                    "actions": [],
                    "dialogues": [{"character_id": "米迦尔",
                                   "text": "我是米迦尔。",
                                   "start_frame": 1, "end_frame": 40}]}
        else:                                   # review / repair / react
            name = "abort"
            args = {"reason": "测试不需要后续回合"}
        return ChatReply(tool_calls=[ToolCall(
            id="c", function=FunctionCall(name=name,
                                          arguments=json.dumps(args)))])

    def cancel(self, request_id):
        return None


def test_declared_dialogue_is_pinned_and_survives_a_rewriting_draft():
    """真实模型实测把镜号 3 的台词写进了 shot_002、把镜号 4 换成自创一句。

    钉住之后，计划里的台词必须逐字等于剧本声明，落实审核不应再有 R016 错误。
    """
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer6_audit.audit_logger import AuditLogger

    script = _script()
    driver = PrevisDriver(
        transport=_RewritingTransport(MARKET_PLAN), audit=AuditLogger(),
        script=MARKET.read_text(encoding="utf-8"), parsed_script=script,
        builder=_StubBuilder(), thread_factory=_InlineThread)
    driver.run_to_completion()

    plan = driver.plan
    for index, item in enumerate(script.declared_shots):
        declared_texts = [d.text for d in item.dialogues]
        actual_texts = [entry["text"]
                        for entry in (plan.shots[index].dialogues or [])]
        if not declared_texts:
            continue          # 剧本没声明台词时，草案仍是唯一来源
        assert actual_texts == declared_texts, f"镜号{item.shot_number}"

    errors = [finding for finding in check_compliance(plan, script)
              if finding.is_error]
    # 剧本没声明台词的镜头（镜号 1/5）会被草案塞进一句，这是 WARNING；
    # ERROR 必须为 0——那才是"剧本声明的台词没有被落实"。
    assert errors == [], [item.message for item in errors]
