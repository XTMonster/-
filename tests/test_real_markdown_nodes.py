"""真实剧本格式（第四集.md 的节点写法）必须能被解析层结构化。

用户真实剧本的写法是 markdown 节点标题 + 代码围栏裹着分镜表::

    ## 节点1（约16s）

    ```text
    【角色锚】米迦尔：…伊恩：…偷盗者：…
    镜头 1（约5s）：
    - 景别视角：大远景，低机位平视。
    - 主体动作：米迦尔与伊恩站立不动…
    - 音频：米迦尔（说）：{伊恩，这里就交给我吧！}
    ```

历史回归点（2026-10-21 实测）：``NODE_HEADER_RE`` 要求 ``节点N：``（有冒号），
``normalize_inline_shot_script`` 的节点正则不接受 ``##`` 前缀，导致这类节点
既进不了 ``parse_shot_list``，围栏又把 Fountain 场景标题挡住 —— 最终解析出
0 镜 / 0 角色 / 0 对白，离线自检直接退化成 2 镜占位计划。
"""

from __future__ import annotations

import pathlib

from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer1_input import parse_script
from block_director.layer5_orchestrator.ruler_observation import build_observation

ROOT = pathlib.Path(__file__).resolve().parents[1]
REAL = ROOT / "work" / "node123_real.md"


def test_real_node_markdown_extracts_shots_cast_and_dialogue():
    assert REAL.exists(), "从第四集.md 抽取的节点 1-3 测试材料必须存在"
    script = parse_script(REAL)
    declared = list(getattr(script, "declared_shots", []) or [])
    # 节点 1（4 镜）+ 节点 2（3 镜）+ 节点 3（4 镜）= 11 镜
    assert len(declared) == 11, (
        f"真实格式应抽出 11 个镜头声明，实际 {len(declared)}")
    assert [d.declared_seconds for d in declared] == [
        5.0, 4.0, 3.5, 3.5, 3.5, 4.5, 4.0, 4.0, 4.0, 4.0, 4.0]
    assert set(script.cast_declarations) == {"米迦尔", "伊恩", "偷盗者"}
    assert script.dialogue_count >= 4, (
        "节点 1 有四句对白，至少这些台词必须进入对白表")


def test_real_node_markdown_does_not_need_llm_structure_fallback():
    """围栏 + 节点标题不应让解析退回 needs_llm_structure=True。"""
    script = parse_script(REAL)
    assert script.needs_llm_structure is False


def test_real_node_markdown_keeps_shot_visual_fields():
    """镜头的景别/构图/运镜字段要保留（它们是导演写死的声明）。"""
    script = parse_script(REAL)
    first = script.declared_shots[0]
    assert "大远景" in (first.field("拍摄距离") or "")
    assert "构图技巧" in first.fields
    assert (first.field("拍摄手法") or "").strip()


def test_real_three_nodes_bind_declared_shots_by_global_plan_order():
    """跨节点重复的局部镜号必须按全片计划顺序对齐，不能互相覆盖。

    节点 1/2/3 都从“镜头 1”重新编号；``shot_001`` 对应全片第一条声明，
    应拿到节点 1 的 5 秒 / ELS / 三人，而不是节点 3 的 4 秒 / MCU / 单人。
    """
    script = parse_script(REAL)
    declared = list(script.declared_shots)
    plan = Plan(scene_heading="第十四街区码头市场")
    plan.shots = [
        ShotPlan(
            shot_id=f"shot_{index:03d}",
            intent=f"节点 {decl.node_number} 镜头 {decl.shot_number}",
            shot_type=decl.shot_type or "MS",
            duration_frames=int(round(float(decl.declared_seconds) * 24)),
            order=index,
            characters=list(decl.characters),
            declared_shot_number=int(decl.shot_number),
        )
        for index, decl in enumerate(declared, start=1)
    ]

    observation = build_observation(plan=plan, parsed=script, fps=24)
    specs = {item["shot_id"]: item for item in observation["shot_specs"]}
    first = specs["shot_001"]["declared"]
    assert first == {
        "seconds": 5.0,
        "frames": 120,
        "shot_type": "ELS",
        "characters": ["米迦尔", "伊恩", "偷盗者"],
    }
    assert [specs[f"shot_{i:03d}"]["declared"]["seconds"]
            for i in range(1, 12)] == [
                5.0, 4.0, 3.5, 3.5, 3.5, 4.5, 4.0, 4.0, 4.0, 4.0, 4.0]
