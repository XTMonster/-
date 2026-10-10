"""G2 判据 #8：*_invalid 事件带 reason+category，分类器覆盖 v10-v13 真跑逐字行。"""

from __future__ import annotations

import json

import pytest

from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer5_orchestrator.driver import default_registry
from block_director.layer5_orchestrator.invalid_category import classify_invalid
from block_director.layer5_orchestrator.offline import demo_draft_dict
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME

from stage_helpers import is_understand, understand_reply
from test_driver_react import (
    PLAN_REPLY,
    ScriptedTransport,
    StubAuditor,
    make_driver,
)

#: 每一行都是 work/_g2_ds_run/blender_v1{0,1,2,3}.log 里 ``_invalid:`` 之后
#: 的**逐字原文**（含 draft 的 ``shot_xxx: `` 前缀，与驱动器落进 message 的
#: 文本一字不差）。六类全都要有覆盖。
LOG_LINES = [
    # ---- no_tool（3 条）--------------------------------------------
    ("回复中没有工具调用", "no_tool"),                       # v10 repair
    ("回复中没有工具调用", "no_tool"),                       # v12 react
    ("回复中没有工具调用", "no_tool"),                       # v13 react
    # ---- gate（2 条）-----------------------------------------------
    ("shot_002: 草案让角色在 shot_002 绕到两人连线的另一侧（连线转角 ≥90°），"
     "而那一镜只有单人，观众看不见这次换位（R001）。"
     "请把换位放进双人同框的镜头，或不要跨线。", "gate"),      # v10 draft
    ("草案让角色在 shot_012 绕到两人连线的另一侧（连线转角 ≥90°），"
     "而那一镜只有单人，观众看不见这次换位（R001）。"
     "请把换位放进双人同框的镜头，或不要跨线。", "gate"),      # v10 repair
    # ---- cast（6 条）-----------------------------------------------
    ("shot_003: 第 6 个拍点的 target='米迦尔' 既不在角色表也不在锚点表里",
     "cast"),                                                # v11 draft
    ("第 2 个拍点的 subject='伊恩' 不在本镜角色里", "cast"),   # v10 repair
    ("第 1 个拍点的 target='画面中心' 既不在角色表也不在锚点表里",
     "cast"),                                                # v11 repair
    ("第 1 个拍点的 target='伊恩' 既不在角色表也不在锚点表里；"
     "第 3 个拍点的 subject='伊恩' 不在本镜角色里", "cast"),   # v12 react
    ("第 1 个拍点的 target='left_third' 既不在角色表也不在锚点表里",
     "cast"),                                                # v11 repair
    ("第 2 个拍点的 target='银币' 既不在角色表也不在锚点表里；"
     "第 3 个拍点的 target='银币' 既不在角色表也不在锚点表里；"
     "第 4 个拍点的 subject='米迦尔' 不在本镜角色里；"
     "第 5 个拍点的 subject='米迦尔' 不在本镜角色里", "cast"),  # v12 repair
    # ---- enum（6 条）-----------------------------------------------
    ("shot_006: 第 1 个拍点的 pace='sharp' 不在闭集内（slow、normal、brisk）",
     "enum"),                                                # v10 draft
    ("walk_to 的 speed 只能是 run/walk（当前 'normal'）", "enum"),  # v10 react
    ("emit_shot_draft: <tool_observation>参数校验失败: args.beats[2].pace "
     "取值必须是 ['slow', 'normal', 'brisk'] 之一，实际 'sharp'。"
     "请修正后重试。</tool_observation>", "enum"),            # v10 react
    ("E_MOTION_001：无法理解的 toward 取值：'forward_up'；"
     "look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']",
     "enum"),                                                # v11 react
    ("shot_008: composition.rule='balance' 不在闭集内（thirds、center、"
     "symmetry、diagonal、frame_within_frame、lead_room）", "enum"),  # v12 draft
    ("place_prop 不认识的参数 ['to']；允许的键是 ['prop', 'angle_deg', 'toward']；"
     "look_at 不认识的参数 ['to']；允许的键是 ['yaw_deg', 'pitch_deg']；"
     "look_at 不认识的参数 ['to']；允许的键是 ['yaw_deg', 'pitch_deg']；"
     "walk_to 的 speed 只能是 run/walk（当前 0.4）；"
     "look_at 不认识的参数 ['to']；允许的键是 ['yaw_deg', 'pitch_deg']",
     "enum"),                                                # v13 react
    # ---- param_key（5 条）------------------------------------------
    ("look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']；"
     "look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']",
     "param_key"),                                           # v10 repair
    ("hand_to 不认识的参数 ['to']；允许的键是 ['prop', 'angle_deg', 'toward']",
     "param_key"),                                           # v10 react
    ("emit_shot_draft: <tool_observation>参数校验失败: "
     "args.actions[1].params 不允许出现字段 target。请修正后重试。"
     "</tool_observation>", "param_key"),                    # v11 react
    ("stand 不认识的参数 ['base_z']；允许的键是 ['drop', 'leg_fold_deg', 'lean_deg']",
     "param_key"),                                           # v13 react
    ("emit_shot_draft: <tool_observation>参数校验失败: "
     "args.camera 不允许出现字段 type。请修正后重试。</tool_observation>",
     "param_key"),                                           # v12 react
    # ---- shape（5 条）----------------------------------------------
    ("shot_012: walk_to 的 from 必须是坐标（2–3 个数字的数组，当前 'screen_right'）",
     "shape"),                                               # v11 draft
    ("shot_012: 第 1 个拍点缺少 subject；第 2 个拍点缺少 subject；"
     "第 3 个拍点缺少 subject；第 4 个拍点缺少 subject", "shape"),  # v12 draft
    ("enter_from 的 from 必须是坐标（2–3 个数字的数组，当前 'screen_left'）",
     "shape"),                                               # v13 react
    ("emit_shot_draft: <tool_observation>参数校验失败: "
     "args.actions[0] 缺少必填字段 action_type；"
     "args.actions[1] 缺少必填字段 action_type；"
     "args.actions[2] 缺少必填字段 action_type；"
     "args.actions[3] 缺少必填字段 action_type；"
     "args.actions[4] 缺少必填字段 action_type；"
     "args.actions[5] 缺少必填字段 action_type；"
     "args.actions[6] 缺少必填字段 action_type。请修正后重试。"
     "</tool_observation>", "shape"),                        # v12 repair
    ("enter_from 的 from_ 必须是坐标（2–3 个数字的数组，当前 'screen_left'）",
     "shape"),                                               # v13 react
]


@pytest.mark.parametrize("index", range(len(LOG_LINES)))
def test_classify_verbatim_v10_v13_lines(index):
    reason, expected = LOG_LINES[index]
    assert classify_invalid(reason) == expected, reason


#: 卡 G8-DF 修订 2 的分类词表：每个词条一行（category, 标记），按
#: ``invalid_category._RULE_TABLE`` 的顺序首命中胜；全部是朴素子串匹配，
#: 没有正则。每个标记都必须有一条参数化断言。
CARD_MARKERS = [
    ("no_tool", "没有工具调用"),
    ("gate", "R001"),
    ("gate", "连线"),
    ("gate", "跨线"),
    ("gate", "工具调用次数超限"),
    ("cast", "角色表外"),
    ("cast", "不在本镜角色"),
    ("cast", "既不在角色表"),
    ("cast", "找不到角色"),
    ("enum", "闭集"),
    ("enum", "取值必须是"),
    ("enum", "toward 取值"),
    ("enum", "只能是"),
    ("param_key", "不认识的参数"),
    ("param_key", "不允许出现字段"),
    ("shape", "必须是坐标"),
    ("shape", "至少需要"),
    ("shape", "最多"),
    ("shape", "类型应为"),
    ("shape", "缺少必填"),
    ("shape", "必须是数字"),
    ("shape", "缺少 rule"),
    ("shape", "缺少 subject"),
]


@pytest.mark.parametrize("expected, marker", CARD_MARKERS,
                         ids=[f"{cat}-{i}" for i, (cat, _)
                              in enumerate(CARD_MARKERS)])
def test_classify_each_card_marker(expected, marker):
    # 标记嵌在自然文案中间也要命中对应类别（证明是子串匹配而非锚定匹配）。
    assert classify_invalid(f"参数校验失败：{marker}，请修正后重试。") == expected


def test_classify_falls_back_to_other_for_unknown_text():
    # 真跑里出现的、七类都不覆盖的文案：一律落 other，不猜。
    assert classify_invalid("guard accept 声明格式错误：格式不对") == "other"
    assert classify_invalid("emit_shot_draft 只在单镜阶段被接受") == "other"
    assert classify_invalid("计划解析失败: 坏 JSON") == "other"


def test_r002_is_not_gate_unless_another_marker_matches():
    # 词表只收 R001 这个字面量：R0xx 正则已删，R002 不能靠编号形状混进 gate。
    assert classify_invalid("R002 something") == "other"
    # 若同一句里真带了 gate 词条（"连线"），那它按词条命中 gate——这不是靠 R002。
    assert classify_invalid("R002 连线") == "gate"


def test_rule_order_prefers_gate_over_cast():
    # 同一句里既有 R001 又有"角色"字样时，gate 优先。
    assert classify_invalid("绕到另一侧（R001），单人镜里角色看不见换位") == "gate"


def test_rule_order_prefers_enum_over_param_key():
    # 混合文案：闭集违规排在"不认识的参数"之前。
    assert classify_invalid(
        "walk_to 的 speed 只能是 run/walk（当前 0.4）；"
        "look_at 不认识的参数 ['to']") == "enum"


# --------------------------------------------------------------------------- #
# 驱动器侧：repair_invalid / draft_invalid 事件真的带 reason+category
# --------------------------------------------------------------------------- #
def test_repair_invalid_event_carries_reason_and_category():
    registry = default_registry()
    registry.add(name="look_at", description="调整视线",
                 parameters={"type": "object", "additionalProperties": False,
                             "properties": {"yaw_deg": {"type": "number"}}},
                 handler=lambda **kw: "已调整视线")
    registry.add(name="setup_camera", description="重设机位",
                 parameters={"type": "object"},
                 handler=lambda **kw: "机位已重设")
    transport = ScriptedTransport([
        PLAN_REPLY,
        ("look_at", {"toward": "camera"}),              # B4：非法参数键
        ("setup_camera", {"shot_id": "shot_001"}),      # 续轮：真的动手
        ("setup_camera", {"shot_id": "shot_001"}),      # B5 第 1 步
        None,                                           # B5 停止
    ])
    driver = make_driver(transport, StubAuditor(fail_times=3),
                         registry=registry)
    driver.run_to_completion()

    events = [event for event in driver.audit.recent(400)
              if event.kind == "repair_invalid"]
    assert events, "非法参数键的修复回复必须记 repair_invalid"
    event = events[0]
    assert event.message.startswith("look_at: ")
    assert event.data["reason"] == event.message
    assert event.data["category"] == "param_key"


class BadDraftTransport:
    """B1 的单镜草案放一个角色表外的角色，逼出 draft_invalid。"""

    #: 计划里带真实角色名，角色表才非空（空表 = "没有角色表可查"，跳过核验）。
    PLAN_WITH_CAST = (PLAN_TOOL_NAME, {"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
         "duration_frames": 24, "characters": ["小明"]},
        {"shot_id": "shot_002", "order": 2, "intent": "y", "shot_type": "CU",
         "duration_frames": 24, "characters": ["小明"]}]})

    def __init__(self):
        self.calls = 0
        self.payloads = []
        self._editor_index = 0
        self._script_index = 0

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            return understand_reply(payload.request_id)
        self.calls += 1
        self.payloads.append(payload)
        if str(payload.purpose) == "editor":
            draft = demo_draft_dict(self._editor_index)
            draft["characters"] = ["伊萨克"]        # 不在角色表 → CAST_001
            self._editor_index += 1
            call = ToolCall(
                id=f"draft_{self.calls}",
                function=FunctionCall(
                    name="emit_shot_draft",
                    arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(tool_calls=[call], request_id=payload.request_id)
        item = self.PLAN_WITH_CAST if self._script_index == 0 else None
        self._script_index += 1
        if item is None:
            return ChatReply(content="没有动作", tool_calls=[],
                             request_id=payload.request_id)
        name, args = item
        call = ToolCall(id=f"c{self.calls}",
                        function=FunctionCall(name=name,
                                              arguments=json.dumps(args)))
        return ChatReply(tool_calls=[call], request_id=payload.request_id)

    def cancel(self, request_id):
        return None


def test_draft_invalid_event_carries_reason_and_category():
    driver = make_driver(BadDraftTransport(), StubAuditor(fail_times=3))
    driver.run_to_completion()

    events = [event for event in driver.audit.recent(400)
              if event.kind == "draft_invalid"]
    assert events, "角色表外的草案必须记 draft_invalid"
    event = events[0]
    assert event.message.startswith("shot_001: ")
    assert event.data["reason"] == event.message
    assert event.data["category"] == "cast"
