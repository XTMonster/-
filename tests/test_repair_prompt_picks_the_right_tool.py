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
