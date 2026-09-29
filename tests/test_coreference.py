"""§4.3 共指消解（v1.3 P0-3 接线）。

v1.2 里 ``resolve_coreferences`` / ``apply_mapping`` **既没有任何生产调用方，
也没有任何测试**——整个 §4.3 是死代码。这里补上行为测试，并钉住
"真实链路可用的那个入口"确实被导出。
"""

from __future__ import annotations

import block_director.layer1_input as layer1
from block_director.layer1_input import (
    apply_deterministic_coreferences,
    apply_mapping,
    collect_names,
    parse_text,
    resolve_coreferences,
)


def test_the_wired_entry_point_is_public():
    """真实链路（tools/run_headless.py、tools/run_export.py）从这里导入它。"""
    assert "apply_deterministic_coreferences" in layer1.__all__
    assert callable(layer1.apply_deterministic_coreferences)


def test_whitespace_variants_are_merged_without_an_llm():
    """写法归一化（"小 明" / "小明 "）不需要模型参与，必须自动合并。"""
    script = parse_text("INT. 咖啡馆 - 日\n\n小 明坐下。\n\n小明\n你还在听吗。\n")
    speakers = [d.character for scene in script.scenes for d in scene.dialogues]
    assert speakers == ["小明"]
    # 幂等：再跑一次不应有新的改写
    assert apply_deterministic_coreferences(script) == 0


def test_pronouns_are_not_guessed_without_a_cluster_fn():
    """没有 cluster_fn 时只做确定性合并，代词原样保留——不做无依据的猜测。"""
    script = parse_text(
        "INT. 房间 - 日\n\n小明坐下。\n\n小明\n我走了。\n\n他点头。\n")
    mapping = resolve_coreferences(script)
    assert "他" not in mapping
    assert mapping["小明"] == "小明"


def test_an_injected_cluster_fn_can_merge_aliases():
    """代词/昵称合并要模型参与，因此以 cluster_fn 注入（layer1 不依赖 layer5）。"""
    script = parse_text(
        "INT. 房间 - 日\n\n小明\n你还在听吗。\n\n明\n我在。\n")
    assert set(collect_names(script)) == {"小明", "明"}

    mapping = resolve_coreferences(
        script, cluster_fn=lambda names, text: {"明": "小明"})
    assert mapping["明"] == "小明"

    assert apply_mapping(script, mapping) >= 1
    speakers = [d.character for scene in script.scenes for d in scene.dialogues]
    assert speakers == ["小明", "小明"]


def test_a_failing_cluster_fn_does_not_break_parsing():
    """消解失败不该阻断解析——退回确定性结果即可。"""
    script = parse_text("INT. 房间 - 日\n\n小明\n你还在听吗。\n")

    def boom(names, text):
        raise RuntimeError("模型挂了")

    mapping = resolve_coreferences(script, cluster_fn=boom)
    assert mapping["小明"] == "小明"
