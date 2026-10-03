"""场景可用范围：模型看得见（计划提示）＋ 越界有告警（构建期）。

现场（2026-10-04，`work/_drift_probe.py` ＋ `docs/evidence/20261004-walk-handover/`）：
`walk_to` 的 `target_position` 是**绝对**位置，而计划提示里从来没写"这场戏多大"
⇒ 模型把目的地写到 8–9.5 m、再经一串接力把角色带到 25 m 之外。

本文件钉三件事：① 提示里真的带着 `config.scene.extent_m` 的数字，而且说清
"绝对位置不是相对位移"；② 越界判定是纯函数、边界取闭区间；③ 配置校验拦住
非正的范围（0 或负数＝"哪儿都不能站"）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.schedule import out_of_bounds  # noqa: E402
from block_director.contracts.config import AppConfig, SceneConfig  # noqa: E402
from block_director.layer5_orchestrator.planner import (  # noqa: E402
    build_plan_payload,
    space_block,
)

SCRIPT = "INT. 码头 - 日\n\n米迦尔：上船。\n"


def test_the_prompt_carries_the_configured_range():
    config = AppConfig()
    config.scene.extent_m = 9.0
    payload = build_plan_payload(SCRIPT, config)
    system = payload.messages[0].content
    assert "场景空间" in system
    block = system.split("场景空间", 1)[1].split("需要更多细节", 1)[0]
    assert "9" in block, block
    assert "12" not in block, block          # 默认值不许漏进这一段的数字里
    assert "绝对位置" in system and "不是相对位移" in system


def test_without_a_config_the_default_range_still_appears():
    """`config=None`（纯单测路径）也必须给出一段有效的空间约束。"""
    system = build_plan_payload(SCRIPT, None).messages[0].content
    assert "场景空间" in system
    assert "12" in system


def test_the_block_is_pure_and_uses_the_same_number_everywhere():
    text = space_block(6.5)
    assert text.count("6.5") >= 2          # X 与 Y 两处
    assert "硬约束" in text


def test_out_of_bounds_uses_a_closed_range():
    assert out_of_bounds([12.0, -12.0], 12.0) is False     # 正好在边界上＝在范围内
    assert out_of_bounds([12.5, 0.0], 12.0) is True
    assert out_of_bounds([0.0, -12.5], 12.0) is True
    assert out_of_bounds([3.0, 4.0], 12.0) is False
    assert out_of_bounds([3.0], 12.0) is False             # 缺 Y 的坏数据不算越界
    assert out_of_bounds([99.0, 0.0], 0.0) is False        # 没给范围就不判


def test_a_non_positive_range_is_a_config_error():
    config = AppConfig()
    config.scene = SceneConfig(extent_m=0.0)
    codes = [issue.code for issue in config.validate()]
    assert "CFG_214" in codes, codes
    config.scene = SceneConfig(extent_m=-3.0)
    assert "CFG_214" in [issue.code for issue in config.validate()]


def test_the_default_is_positive_and_in_the_generated_spec():
    """#16 的漂移门：默认值必须与 `specs/config.default.yaml` 一致。"""
    import yaml

    spec = yaml.safe_load(
        (ROOT / "specs" / "config.default.yaml").read_text(encoding="utf-8"))
    assert float(spec["scene"]["extent_m"]) == float(AppConfig().scene.extent_m)
