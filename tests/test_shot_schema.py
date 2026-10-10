"""G2 判据 #8（卡 G8-B）：逐镜动态严格工具 schema。

现场（v10–v13 真跑，``work/_g2_ds_run/blender_v1*.log``）的 invalid 主力：

* 幻觉角色名（费里德 / 优一郎 / 伊萨克 / char_a）；
* 场外 subject（拍点 subject 写全剧组里、但不在本镜的角色）；
* 逐动作写错键（``look_at.to`` / ``stand.base_z`` / ``body_tilt.drop`` /
  ``turn_body.axis``）；
* 闭集外取值（``pace='sharp'`` / ``composition.rule='balance'``）。

修法：``shot_schema`` 按（本镜在场角色 / 全剧组 / 锚点）生成**这一镜**的
schema——角色枚举逐镜、动作分支按 ``ACTION_PARAMS`` 逐动作（``const`` 判别
式）。同一份 schema 既是模型看到的工具声明、也是 ``registry.execute`` 校验
用的那一份（同一个对象）。本文件把这些都钉死。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from strict_schema import to_strict  # noqa: E402

from block_director.contracts.audit import AuditError, AuditResult  # noqa: E402
from block_director.contracts.beats import validate_beats  # noqa: E402
from block_director.contracts.enums import Purpose  # noqa: E402
from block_director.contracts.messages import (  # noqa: E402
    ChatReply,
    FunctionCall,
    ToolCall,
)
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.layer5_orchestrator.driver import (  # noqa: E402
    default_registry,
)
from block_director.layer5_orchestrator.editor import (  # noqa: E402
    EDITOR_TOOL_NAME,
    build_editor_payload,
    extract_draft,
)
from block_director.layer5_orchestrator.react import build_react_payload  # noqa: E402
from block_director.layer5_orchestrator.repair import build_repair_payload  # noqa: E402
from block_director.layer5_orchestrator.shot_schema import (  # noqa: E402
    BASE_DRAFT_PARAMETERS,
    CHARACTER_TOOL_NAMES,
    character_tool_parameters,
    emit_shot_draft_schema,
    shot_tool_overrides,
    string_enum,
)
from block_director.layer5_orchestrator.tool_registry import (  # noqa: E402
    ToolRegistry,
)
from block_director.layer5_orchestrator.tool_schema import validate_args  # noqa: E402
from block_director.motion.model import ACTION_TYPES  # noqa: E402

SHOT_CHARS = ["甲", "乙"]
FULL_CAST = ["甲", "乙", "丙"]
ANCHORS = ["door", "摊位"]


def _schema():
    return emit_shot_draft_schema(SHOT_CHARS, FULL_CAST, ANCHORS)


def _action(action_type, *, character_id="甲", params=None, **extra):
    item = {"character_id": character_id, "action_type": action_type,
            "start_frame": 1, "end_frame": 24}
    if params is not None:
        item["params"] = params
    item.update(extra)
    return item


def _problems(draft):
    return validate_args(_schema(), draft)


# --------------------------------------------------------------------------- #
# 1. v10–v13 的每一类 invalid 都必须在**校验期**被逐镜 schema 拒收
# --------------------------------------------------------------------------- #
def test_hallucinated_names_are_rejected_by_the_per_shot_enums():
    schema = _schema()
    assert validate_args(
        schema, {"shot_id": "s", "characters": ["费里德"]})
    actions = validate_args(schema, {"shot_id": "s", "actions": [
        _action("nod", character_id="优一郎")]})
    assert any("优一郎" in item for item in actions)
    beats = validate_args(schema, {"shot_id": "s", "beats": [
        {"t": 0.5, "subject": "伊萨克", "verb": "walk_to"}]})
    assert any("伊萨克" in item for item in beats)
    target = validate_args(schema, {"shot_id": "s", "beats": [
        {"t": 0.5, "subject": "甲", "verb": "walk_to",
         "target": "char_a"}]})
    assert any("char_a" in item for item in target)
    dialogues = validate_args(schema, {"shot_id": "s", "dialogues": [
        {"character_id": "伊萨克", "text": "……",
         "start_frame": 1, "end_frame": 10}]})
    assert any("伊萨克" in item for item in dialogues)


def test_per_action_wrong_keys_are_rejected_with_a_discriminator_naming_the_action():
    schema = _schema()
    cases = [
        ("look_at", {"to": "甲"}, "look_at"),
        ("stand", {"base_z": 0.2}, "stand"),
        ("body_tilt", {"drop": 0.2}, "body_tilt"),
        ("turn_body", {"axis": "x"}, "turn_body"),
    ]
    for action_type, params, name in cases:
        problems = validate_args(schema, {"shot_id": "s", "actions": [
            _action(action_type, params=params)]})
        assert problems, (action_type, params)
        text = "；".join(problems)
        assert f"action_type={name}" in text, (action_type, text)
        assert name in text, (action_type, text)


def test_closed_value_vocabulary_stays_closed():
    problems = _problems({"shot_id": "s", "beats": [
        {"t": 0.5, "subject": "甲", "verb": "walk_to",
         "pace": "sharp"}]})
    assert any("pace" in item and "sharp" in item for item in problems)
    problems = _problems({"shot_id": "s",
                          "composition": {"rule": "balance"}})
    assert any("rule" in item and "balance" in item for item in problems)


def test_off_shot_character_is_a_valid_beat_target_but_not_a_subject():
    schema = _schema()
    off_target = {"shot_id": "s", "beats": [
        {"t": 0.5, "subject": "甲", "verb": "walk_to", "target": "丙"}]}
    assert validate_args(schema, off_target) == []
    structured = {"shot_id": "s", "beats": [
        {"t": 0.5, "subject": "甲", "verb": "look_at",
         "target": {"character": "丙"}}]}
    assert validate_args(schema, structured) == []
    point = {"shot_id": "s", "beats": [
        {"t": 0.5, "subject": "甲", "verb": "look_at",
         "target": {"point": [1.0, 2.0, 0.0]}}]}
    assert validate_args(schema, point) == []
    off_subject = {"shot_id": "s", "beats": [
        {"t": 0.5, "subject": "丙", "verb": "walk_to"}]}
    problems = validate_args(schema, off_subject)
    assert any("subject" in item and "丙" in item for item in problems)


def test_g8c_structured_targets_pass_and_illegal_ones_stay_rejected():
    schema = _schema()
    look = {"shot_id": "s", "actions": [
        _action("look_at", params={"target": {"character": "丙"}})]}
    assert validate_args(schema, look) == []
    look_point = {"shot_id": "s", "actions": [
        _action("look_at", params={"target": {"point": [1, 2, 3]}})]}
    assert validate_args(schema, look_point) == []
    off_cast = {"shot_id": "s", "actions": [
        _action("look_at", params={"target": "费里德"})]}
    assert any("费里德" in item for item in validate_args(schema, off_cast))
    hand = {"shot_id": "s", "actions": [
        _action("hand_to", params={"prop": "银币",
                                   "toward": {"character": "丙"}})]}
    assert validate_args(schema, hand) == []
    hand_point = {"shot_id": "s", "actions": [
        _action("hand_to", params={"prop": "银币",
                                   "toward": {"point": [1, 2, 3]}})]}
    assert validate_args(schema, hand_point) == []
    hand_word = {"shot_id": "s", "actions": [
        _action("hand_to", params={"prop": "银币", "toward": "left"})]}
    assert validate_args(schema, hand_word) == []
    hand_vector = {"shot_id": "s", "actions": [
        _action("hand_to", params={"prop": "银币", "toward": [1, 0]})]}
    assert validate_args(schema, hand_vector) == []
    bare_camera = {"shot_id": "s", "actions": [
        _action("hand_to", params={"prop": "银币", "toward": "camera"})]}
    bare_camera_problems = validate_args(schema, bare_camera)
    assert bare_camera_problems, "camera 不是方向词闭集，必须被拒"
    assert any("toward" in item for item in bare_camera_problems)


def test_legal_draft_passes_end_to_end():
    legal = {
        "shot_id": "s",
        "characters": ["甲", "乙"],
        "actions": [
            _action("walk_to", target_position=[1.0, 0.0],
                    params={"speed": "walk"}),
            _action("look_at", character_id="乙",
                    params={"target": {"character": "丙"}}),
            _action("hand_to", character_id="乙",
                    params={"prop": "银币",
                            "toward": {"point": [1.0, 2.0, 0.0]}}),
            _action("body_tilt", params={"angle_deg": 12, "axis": "x"}),
            #: 无歧义等价键：执行层归一后接受，schema 不误拒（v5–v7 的
            #: react_invalid 主力恰恰是这些等价键被 schema 拒）。
            _action("turn_head", params={"yaw_deg": 15}),
        ],
        "dialogues": [{"character_id": "甲", "text": "……",
                       "start_frame": 2, "end_frame": 10}],
        "beats": [
            {"t": 0.0, "subject": "甲", "verb": "walk_to", "target": "丙",
             "face_to": "camera", "pace": "normal"},
            {"t": 0.5, "subject": "乙", "verb": "look_at",
             "target": {"character": "甲"}},
        ],
        "camera": {"side": "front", "lens": 35},
        "composition": {"rule": "thirds", "subject_position": "left_third"},
    }
    assert validate_args(_schema(), legal) == []


def test_extract_draft_passes_full_cast_so_off_shot_targets_are_legal():
    def reply(beats):
        return ChatReply(tool_calls=[ToolCall(
            id="c", function=FunctionCall(
                name=EDITOR_TOOL_NAME,
                arguments=json.dumps({"shot_id": "shot_001", "beats": beats},
                                     ensure_ascii=False)))])

    draft = extract_draft(
        reply([{"t": 0.5, "subject": "甲", "verb": "walk_to",
                "target": "丙"}]), "shot_001",
        characters=["甲", "乙"], anchors=["door"],
        full_cast=["甲", "乙", "丙"])
    assert draft.beats[0]["target"] == "丙"
    with pytest.raises(ValueError) as excinfo:
        extract_draft(
            reply([{"t": 0.5, "subject": "丙", "verb": "walk_to"}]),
            "shot_001", characters=["甲", "乙"], anchors=["door"],
            full_cast=["甲", "乙", "丙"])
    assert "subject" in str(excinfo.value) and "丙" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 2. 空镜：省略 enum，绝不发空枚举
# --------------------------------------------------------------------------- #
def _all_enums(node):
    if isinstance(node, dict):
        if "enum" in node:
            yield node["enum"]
        for value in node.values():
            yield from _all_enums(value)
    elif isinstance(node, list):
        for item in node:
            yield from _all_enums(item)


def test_empty_shot_cast_omits_the_enum_instead_of_emitting_an_empty_one():
    schema = emit_shot_draft_schema([], FULL_CAST, ANCHORS)
    assert "enum" not in schema["properties"]["characters"]["items"]
    assert "enum" not in schema["properties"]["beats"]["items"][
        "properties"]["subject"]
    branch = schema["properties"]["actions"]["items"]["anyOf"][0]
    assert "enum" not in branch["properties"]["character_id"]
    assert "enum" not in schema["properties"]["dialogues"]["items"][
        "properties"]["character_id"]
    assert all(enum != [] for enum in _all_enums(schema)), \
        "逐镜 schema 里绝不允许出现空枚举"
    assert string_enum([]) == {"type": "string"}
    #: 空镜草案仍合法（subject 枚举缺省 = 不设限，与 validate_beats 的
    #: "未知剧组跳过成员检查"同口径）。
    assert validate_args(
        schema, {"shot_id": "s", "beats": [
            {"t": 0.5, "subject": "任意", "verb": "walk_to",
             "target": "door"}]}) == []


# --------------------------------------------------------------------------- #
# 3. 载荷携带逐镜枚举 + "同一个对象"校验
# --------------------------------------------------------------------------- #
def _plan() -> Plan:
    return Plan.from_dict({
        "shots": [{"shot_id": "shot_001", "order": 1, "intent": "x",
                   "shot_type": "MS", "duration_frames": 48,
                   "characters": SHOT_CHARS}],
        "environment": {"anchors": [{"name": "door", "depth": "bg",
                                     "relation": "behind 甲"},
                                    {"name": "摊位", "depth": "bg",
                                     "relation": "behind 乙"}]},
    })


def _draft_params(tools):
    for tool in tools:
        if tool["function"]["name"] == EDITOR_TOOL_NAME:
            return tool["function"]["parameters"]
    raise AssertionError(f"{EDITOR_TOOL_NAME} 不在工具表里")


def test_editor_payload_carries_the_per_shot_enums():
    payload = build_editor_payload(
        _plan().shots[0], _plan(), characters=SHOT_CHARS,
        full_cast=FULL_CAST, scene_text="甲走向摊位。")
    parameters = payload.tools[0]["function"]["parameters"]
    assert parameters["properties"]["characters"]["items"]["enum"] == SHOT_CHARS
    assert parameters["properties"]["beats"]["items"]["properties"][
        "subject"]["enum"] == SHOT_CHARS
    target = parameters["properties"]["beats"]["items"]["properties"]["target"]
    assert target["anyOf"][0]["enum"] == FULL_CAST + ANCHORS


def test_repair_and_react_payloads_carry_the_per_shot_enums():
    registry = default_registry()
    overrides = shot_tool_overrides(registry, SHOT_CHARS, FULL_CAST, ANCHORS)
    for name, parameters in overrides.items():
        registry.override_parameters(name, parameters)
    audit = AuditResult(passed=False, target="shot_001", errors=[
        AuditError(rule="R001", code="E_AXIS_001", message="越轴",
                   target="shot_001")])
    repair = build_repair_payload(audit, registry, shot_id="shot_001",
                                  roster=FULL_CAST)
    repair_params = _draft_params(repair.tools)
    assert repair_params["properties"]["characters"]["items"]["enum"] \
        == SHOT_CHARS
    react = build_react_payload(_plan().shots[0], audit, registry=registry)
    react_params = _draft_params(react.tools)
    assert react_params["properties"]["characters"]["items"]["enum"] \
        == SHOT_CHARS
    assert react_params["properties"]["beats"]["items"]["properties"][
        "subject"]["enum"] == SHOT_CHARS


def test_the_seen_schema_is_the_validating_schema_object():
    """载荷里的 emit_shot_draft schema 与 registry.execute 校验用 schema
    必须是**同一个 dict 对象**——不存在"载荷放行、执行校验拒绝"或反过来。"""
    registry = default_registry()
    overrides = shot_tool_overrides(registry, SHOT_CHARS, FULL_CAST, ANCHORS)
    for name, parameters in overrides.items():
        registry.override_parameters(name, parameters)
    audit = AuditResult(passed=False, target="shot_001", errors=[
        AuditError(rule="R001", code="E_AXIS_001", message="越轴",
                   target="shot_001")])
    payload = build_repair_payload(audit, registry, shot_id="shot_001",
                                   roster=FULL_CAST)
    seen = _draft_params(payload.tools)
    assert seen is registry.get(EDITOR_TOOL_NAME).parameters
    bad = registry.execute(EDITOR_TOOL_NAME, {
        "shot_id": "shot_001",
        "actions": [{"character_id": "费里德", "action_type": "nod",
                     "start_frame": 1, "end_frame": 10}],
    })
    assert not bad.ok and "费里德" in bad.content
    good = registry.execute(EDITOR_TOOL_NAME, {
        "shot_id": "shot_001",
        "actions": [{"character_id": "甲", "action_type": "nod",
                     "start_frame": 1, "end_frame": 10}],
    })
    assert good.ok


# --------------------------------------------------------------------------- #
# 4. 角色工具（repair / react 与草案同台给模型）
# --------------------------------------------------------------------------- #
def _tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(
        name="character_action", description="c",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id", "action_type",
                                 "start_frame", "end_frame"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "action_type": {"type": "string",
                                        "enum": list(ACTION_TYPES)},
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1},
                        "params": {"type": "object"}}},
        handler=lambda **kwargs: "ok")
    registry.add(
        name="look_at", description="l",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id", "start_frame", "end_frame"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "target": {"type": "string"},
                        "target_position": {"type": "array", "minItems": 3,
                                            "maxItems": 3,
                                            "items": {"type": "number"}},
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1}}},
        handler=lambda **kwargs: "ok")
    registry.add(
        name="place_character", description="p",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id"],
                    "properties": {"character_id": {"type": "string"}}},
        handler=lambda **kwargs: "ok")
    registry.add(
        name="check_visibility", description="v",
        parameters={"type": "object", "additionalProperties": False,
                    "properties": {"character_id": {"type": "string"}}},
        handler=lambda **kwargs: "ok")
    #: move_character / face_character / interact_with 的基线形状照抄
    #: ``layer3_engine/tool_bindings.py::register_action_tools``（无 bpy 镜像）。
    registry.add(
        name="move_character", description="m",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id", "target_position",
                                 "start_frame", "end_frame"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "target_position": {"type": "array", "minItems": 3,
                                            "maxItems": 3,
                                            "items": {"type": "number"}},
                        "speed": {"type": "string",
                                  "enum": ["walk", "run"]},
                        "style": {"type": "string"},
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1}}},
        handler=lambda **kwargs: "ok")
    registry.add(
        name="face_character", description="f",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "target": {"type": "string"},
                        "target_position": {"type": "array", "minItems": 3,
                                            "maxItems": 3,
                                            "items": {"type": "number"}}}},
        handler=lambda **kwargs: "ok")
    registry.add(
        name="interact_with", description="i",
        parameters={"type": "object", "additionalProperties": False,
                    "required": ["character_id", "prop_id", "interaction_type",
                                 "start_frame", "end_frame"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "prop_id": {"type": "string"},
                        "interaction_type": {
                            "type": "string",
                            "enum": ["sit", "stand", "take", "open", "push"]},
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1}}},
        handler=lambda **kwargs: "ok")
    return registry


def test_character_tools_get_shot_and_full_cast_enums():
    registry = _tool_registry()
    overrides = shot_tool_overrides(registry, SHOT_CHARS, FULL_CAST, ANCHORS)
    for name, parameters in overrides.items():
        registry.override_parameters(name, parameters)
    assert registry.get("character_action").parameters["properties"][
        "character_id"]["enum"] == SHOT_CHARS
    look = registry.get("look_at").parameters["properties"]
    assert look["character_id"]["enum"] == SHOT_CHARS
    assert look["target"]["enum"] == FULL_CAST
    assert registry.get("place_character").parameters["properties"][
        "character_id"]["enum"] == FULL_CAST
    assert registry.get("check_visibility").parameters["properties"][
        "character_id"]["enum"] == FULL_CAST
    #: 逐镜覆盖不得改写注册基线（深拷贝，下一镜还能再换枚举）。
    base = {"type": "object", "additionalProperties": False,
            "required": ["character_id"],
            "properties": {"character_id": {"type": "string"}}}
    patched = character_tool_parameters(
        "place_character", base, SHOT_CHARS, FULL_CAST)
    assert base["properties"]["character_id"] == {"type": "string"}
    assert patched["properties"]["character_id"]["enum"] == FULL_CAST


# --------------------------------------------------------------------------- #
# 5. 驱动器真的把逐镜 schema 装进 repair / react 载荷
# --------------------------------------------------------------------------- #
def test_driver_wires_per_shot_schemas_into_repair_and_react():
    from block_director.layer5_orchestrator.control_tools import FINISH_SHOT
    from block_director.layer5_orchestrator.driver import (
        DriverLimits,
        PrevisDriver,
    )
    from block_director.layer5_orchestrator.offline import demo_plan_dict
    from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
    from block_director.layer6_audit.audit_logger import AuditLogger
    from stage_helpers import is_understand, understand_reply

    SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"

    class InlineThread:
        def __init__(self, target, name=""):
            self._target = target

        def start(self):
            self._target()

    class Transport:
        def __init__(self):
            self.payloads = []
            self._editor = 0

        def _call(self, name, args):
            return ChatReply(tool_calls=[ToolCall(
                id=f"c{len(self.payloads)}",
                function=FunctionCall(name=name,
                                      arguments=json.dumps(args)))] )

        def chat(self, payload, timeout=120.0):
            self.payloads.append(payload)
            if is_understand(payload):
                return understand_reply(payload.request_id)
            if payload.purpose is Purpose.PLAN:
                return self._call(PLAN_TOOL_NAME, demo_plan_dict(SCRIPT))
            if payload.purpose is Purpose.EDITOR:
                from block_director.layer5_orchestrator.offline import (
                    demo_draft_dict,
                )
                draft = demo_draft_dict(self._editor)
                self._editor += 1
                return self._call(EDITOR_TOOL_NAME, draft)
            if payload.purpose is Purpose.REPAIR:
                #: 默认注册表没有这个工具 → 工具不存在 → 修不动 → 走 B5。
                return self._call("setup_camera", {})
            return self._call(FINISH_SHOT, {"summary": "完成"})

        def cancel(self, request_id):
            return None

    class StubBuilder:
        def build(self, plan, brief=None):
            return {"shots": len(plan.shots)}

    class StubAuditor:
        def __init__(self):
            self.audited = []

        def shot_ids(self):
            return ["shot_001", "shot_002"]

        def audit(self, shot_id):
            self.audited.append(shot_id)
            if shot_id == "shot_001" and self.audited.count("shot_001") <= 2:
                return AuditResult(passed=False, target=shot_id, score=55.0,
                                   errors=[AuditError(
                                       rule="COMPOSITION", code="E_CAM_001",
                                       message="构图分低", target=shot_id)])
            return AuditResult(passed=True, target=shot_id, score=88.0)

    transport = Transport()
    driver = PrevisDriver(
        transport=transport, audit=AuditLogger(), script=SCRIPT,
        builder=StubBuilder(), auditor=StubAuditor(),
        limits=DriverLimits(max_repairs_per_shot=1),
        thread_factory=InlineThread)
    driver.run_to_completion()

    shot_001 = demo_plan_dict(SCRIPT)["shots"][0]
    repair = [p for p in transport.payloads if p.purpose is Purpose.REPAIR]
    react = [p for p in transport.payloads if p.purpose is Purpose.REACT]
    assert repair and react, "这一跑必须同时经过 repair 与 react"
    for payload in repair + react:
        parameters = _draft_params(payload.tools)
        assert parameters["properties"]["characters"]["items"]["enum"] \
            == shot_001["characters"]


# --------------------------------------------------------------------------- #
# 6. strict 形状守卫：to_strict 之后每个节点都必须有 type / anyOf / $ref
# --------------------------------------------------------------------------- #
def _strict_schema_nodes(schema, path="root"):
    """按 properties / items / anyOf 三条通道走完 strict schema，
    产出 ``(路径, 节点)``；每一个被产出的 dict 本身都是一个 JSON Schema 段。"""
    if not isinstance(schema, dict):
        return
    yield path, schema
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for key, sub in properties.items():
            if isinstance(sub, dict):
                yield from _strict_schema_nodes(sub, f"{path}.{key}")
    items = schema.get("items")
    if isinstance(items, dict):
        yield from _strict_schema_nodes(items, f"{path}[]")
    for index, branch in enumerate(schema.get("anyOf") or []):
        if isinstance(branch, dict):
            yield from _strict_schema_nodes(branch, f"{path}[anyOf:{index}]")


def test_every_strict_schema_node_has_type_anyof_or_ref():
    """DeepSeek strict 要求每个 schema 节点带 type / anyOf / $ref 之一。

    2026-10-10 实测：裸 ``{"const": kind}`` 判别式在 ``to_strict`` 之后原样
    保留，DeepSeek strict 直接 400
    "one of `type`, `anyOf`, `$ref` field is required"（证据
    ``docs/evidence/20261010-025602-strict-probe/strict_probe.json`` 的
    ``real_emit_shot_draft`` 三次全 400）。这条守卫把发给模型的每一份 schema
    （静态模板 / 逐镜草案 / 每个角色工具）的每一个节点都钉成必须有这三者之一。
    """
    registry = _tool_registry()
    cases = [
        ("base", BASE_DRAFT_PARAMETERS),
        ("per_shot", emit_shot_draft_schema(SHOT_CHARS, FULL_CAST, ANCHORS)),
    ]
    for name in CHARACTER_TOOL_NAMES:
        spec = registry.get(name)
        assert spec is not None, f"{name} 不在默认注册表里"
        cases.append((name, character_tool_parameters(
            name, spec.parameters, SHOT_CHARS, FULL_CAST)))
    for label, schema in cases:
        for path, node in _strict_schema_nodes(to_strict(schema)):
            assert "type" in node or "anyOf" in node or "$ref" in node, (
                f"{label} 的 strict schema 在 {path} 处有既无 type、又无 "
                f"anyOf/$ref 的节点：{json.dumps(node, ensure_ascii=False)}")


def test_no_strict_object_is_left_without_properties():
    """DeepSeek strict 拒收没有 properties 的 object（G8-H 实测）。

    ``character_action`` 的基线 ``params`` 是 ``{"type": "object"}``，探针
    ``docs/evidence/20261010-041156-strict-probe`` 里 DeepSeek 返回
    ``An object with no properties is not allowed.``。发给模型的每一份 schema
    都不能再出现这种节点。
    """
    registry = _tool_registry()
    cases = [
        ("base", BASE_DRAFT_PARAMETERS),
        ("per_shot", emit_shot_draft_schema(SHOT_CHARS, FULL_CAST, ANCHORS)),
    ]
    for name in CHARACTER_TOOL_NAMES:
        spec = registry.get(name)
        cases.append((name, character_tool_parameters(
            name, spec.parameters, SHOT_CHARS, FULL_CAST)))
    for label, schema in cases:
        for path, node in _strict_schema_nodes(to_strict(schema)):
            types = node.get("type")
            is_object = types == "object" or (
                isinstance(types, list) and "object" in types)
            if is_object:
                assert node.get("properties"), (
                    f"{label} 的 strict schema 在 {path} 处有无 properties 的 "
                    f"object：{json.dumps(node, ensure_ascii=False)}")


def test_character_action_params_follow_the_action_param_tables():
    """``character_action.params`` 只收执行层认识的键，不认识的键在解析期就拒。"""
    spec = _tool_registry().get("character_action")
    schema = character_tool_parameters(
        "character_action", spec.parameters, SHOT_CHARS, FULL_CAST)
    ok = {"character_id": SHOT_CHARS[0], "action_type": "look_at",
          "start_frame": 1, "end_frame": 10,
          "params": {"yaw_deg": 30.0}}
    assert validate_args(schema, ok) == []
    #: `amount` 不属于任何动作（真跑实测过 body_tilt + {"amount": 15}）。
    bad = dict(ok, params={"amount": 15})
    assert validate_args(schema, bad), "任何动作都不认识的 amount 必须在解析期被拒"
