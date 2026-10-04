"""修复提示词必须说清"哪一类问题用哪一个工具"（v1.5）。

现场（2026-10-03 的 64 镜真跑，`docs/evidence/20261003_chunked_long3/`）：审计红的
主导项是 `R003`（同角色动作时间重叠，**383 次**），而修复回合**修不动它**——

* `rule_checker._action_ranges()` 读的是**计划**里的动作表（`context.plan.shots[].actions`）；
* 场景工具 `character_action` 只写 Blender 场景（`MotionBlender.bake(clear=False)`，
  **叠加**），一个字都不写回计划；
* 能改计划动作表的只有 `emit_shot_draft`（`merge_draft` 会**整份替换** `actions`）。

而旧提示词只写"必须调用工具**实际修改场景**"——把模型引向场景工具，于是每次修复都
再叠一段动画、`R003` 照旧红，一盏灯烧到降级（126 次修复调用 / 101 次 `shot_degraded`）。

这与 `R011` 当初付过的代价同形（"没有工具能改对白时序 ⇒ R011 不可修"），修法也一样：
**告诉模型该用哪个工具**，不动规则、不动工具集语义。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.audit import AuditError, AuditResult  # noqa: E402
from block_director.contracts.tools import CONTROL_TOOL_NAMES  # noqa: E402
from block_director.layer5_orchestrator import repair as R  # noqa: E402
from block_director.layer5_orchestrator.driver import default_registry  # noqa: E402


def _result():
    return AuditResult(passed=False, level="rule",
                       errors=[AuditError(rule="R003", message="动作时间重叠")])


def test_the_prompt_names_the_draft_resubmission_path():
    text = R.REPAIR_SYSTEM_PROMPT
    assert "emit_shot_draft" in text, "时间轴类问题必须点名重新提交草案这条路径"
    assert "R003" in text and "R011" in text
    #: 反面对照：必须说清"用场景工具修不动时间轴"，否则模型还是会走老路。
    assert "character_action" in text and "叠加" in text


def test_the_repair_payload_really_offers_that_tool():
    """提示词点名的工具必须在这一次请求的工具集里——否则等于叫模型去够空气。"""
    payload = R.build_repair_payload(_result(), default_registry())
    names = [tool["function"]["name"] for tool in payload.tools]
    assert "emit_shot_draft" in names
    #: 计划的唯一入口仍然是阶段 A（§7.1）：修复回合不给 emit_plan。
    assert "emit_plan" not in names
    system = payload.messages[0].content
    assert "emit_shot_draft" in system
    assert "动作时间重叠" in system


def test_the_repair_prompt_carries_the_action_and_movement_tables():
    """参数表与运镜单位表必须进修复提示——否则"重提草案"必然被退回（long19 实测）。

    现场（2026-10-04 的 64 镜真跑 `docs/evidence/20261004_chunked_long19/`）：
    修复回合**确实**调了 `emit_shot_draft`（工具集没有错），但草案被拒——
    `body_tilt 不认识的参数 ['lean_deg']`、`turn_head ['direction_deg']`：
    模型手上没有那张表，只能自己发明键名。结果 R003 一直红到收尾
    （shot_052 / shot_053 的修复回合审计结论**逐字相同**，最后按上限降级）。

    编辑器提示早就带着这两张表（`editor.render_action_params` /
    `render_movement_units`，都由 `motion/model.py` 与 `cinema/camera_motion.py`
    生成），修复提示却漏了——这一条钉住"两边用的是同一份"。
    """
    from block_director.layer5_orchestrator.editor import (
        render_action_params,
        render_movement_units,
    )

    payload = R.build_repair_payload(_result(), default_registry())
    system = payload.messages[0].content
    assert "action_params" not in system and "movement_units" not in system, (
        "占位符必须被真的替换掉")
    #: 两份表逐字进提示（与编辑器同一份实现，不是各抄一遍）。
    assert render_action_params() in system
    assert render_movement_units() in system
    #: 反面对照：`body_tilt` 那一行必须带着**它自己的允许键**（long19 里模型
    #: 恰恰在这一行上写了表外的键名，整条草案被退回）。
    assert "`body_tilt`：`angle_deg`" in system


# --------------------------------------------------------------------------- #
# v1.6（2026-10-04，long10 实测）：**纯时间轴审计要收窄工具集**
#
# 提示词早就写着"用场景工具修不动时间轴"，可 long10 的 117 次修复调用里
# `get_scene_state` 86 / `check_composition` 65 / `check_visibility` 40，
# 而 `emit_shot_draft` 只有 **7** 次——模型照旧去点那些改不动的东西，
# 于是 R003 一直红到降级（终审 49 个未过镜头里 **38 个**都有 R003）。
# 修法：审计**全是**时间轴类时，这一次请求的工具集只留
# `emit_shot_draft` ＋ 控制类工具；混合审计（例：R003 ＋ 构图低分）保持全量，
# 否则会把构图那一半也一起关掉。
# --------------------------------------------------------------------------- #
def _timeline_audit():
    return AuditResult(passed=False, level="rule",
                       errors=[AuditError(rule="R003", message="动作时间重叠")])


def _mixed_audit():
    return AuditResult(passed=False, level="rule",
                       errors=[AuditError(rule="R003", message="动作时间重叠"),
                               AuditError(rule="COMPOSITION", message="构图分低")])


def _names(payload):
    return {tool["function"]["name"] for tool in payload.tools}


def _registry_with_a_scene_tool():
    """`default_registry()` 只有 emit_plan/draft/控制类工具——场景工具由
    `register_all_scene_tools` 另装（那条路要 bpy，纯 pytest 不给）。这里手加
    一个同名工具，用来证明"收窄"确实按规则发生、而不是因为注册表本来就小。
    """
    registry = default_registry()
    registry.add(name="character_action", description="改动作",
                 parameters={"type": "object", "additionalProperties": False,
                             "properties": {}},
                 handler=lambda: "已执行")
    return registry


def test_a_pure_timeline_audit_narrows_the_tool_set():
    registry = _registry_with_a_scene_tool()
    payload = R.build_repair_payload(_timeline_audit(), registry)
    names = _names(payload)
    assert "emit_shot_draft" in names
    assert names <= set(CONTROL_TOOL_NAMES) | {"emit_shot_draft"}, sorted(names)
    #: 反面对照：改不动计划表的那些工具**不摆出来**（摆出来就还会被点）。
    assert "character_action" not in names
    assert "get_scene_state" not in names
    assert "check_composition" not in names
    assert "emit_plan" not in names
    full = {tool["function"]["name"]
            for tool in registry.schemas_except("emit_plan")}
    assert names < full, "收窄后必须比全量工具集真少"
    system = payload.messages[0].content
    assert "全部是时间轴类" in system


def test_a_mixed_audit_keeps_the_scene_tools():
    registry = _registry_with_a_scene_tool()
    names = _names(R.build_repair_payload(_mixed_audit(), registry))
    assert "emit_shot_draft" in names
    assert "character_action" in names          # 构图那一半还要靠它
    assert "emit_plan" not in names
    assert names == {tool["function"]["name"]
                     for tool in registry.schemas_except("emit_plan")}


def test_a_spatial_audit_is_left_alone():
    registry = _registry_with_a_scene_tool()
    audit = AuditResult(passed=False, level="rule",
                        errors=[AuditError(rule="R001", message="越轴")])
    names = _names(R.build_repair_payload(audit, registry))
    assert "character_action" in names and "emit_shot_draft" in names
    assert names == {tool["function"]["name"]
                     for tool in registry.schemas_except("emit_plan")}


def test_the_prompt_names_the_shot_being_repaired():
    """场景摘要里的"当前镜头"是 `SceneContext` 的构建期默认值（第一镜）。

    long10 的 7 次 `emit_shot_draft` 里有 **2** 次把 `shot_id` 写成了
    `shot_001`——正是那条过期摘要值，于是真正要修的 `shot_043` 一直没被改。
    提示词里必须写死"本次要修的镜头"。
    """
    payload = R.build_repair_payload(_timeline_audit(), default_registry(),
                                     shot_id="shot_043")
    system = payload.messages[0].content
    assert "本次要修的镜头" in system
    assert "shot_043" in system


def test_without_a_shot_id_nothing_is_invented():
    system = R.build_repair_payload(_timeline_audit(),
                                    default_registry()).messages[0].content
    assert "本次要修的镜头" not in system
