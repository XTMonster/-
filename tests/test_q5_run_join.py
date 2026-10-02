"""Q5 的**运行侧 join**（§4.1b 第二步）：真的能算，且算不出来时如实说原因。

背景：Q5 以前只实现了第一步（夹具下界）。第二步是"把真实运行里逐镜的
`SceneContract` 查询串与本条 `q` 按**键值对集合相等**对起来"——没有这一步，
夹具再全也只是个摆设。本文件钉住四件事：

* 逐镜查询串由**同一个生产者**（`scene_contract.shot_constraint_query`）产出，
  测试拿 `shots.json` 的真实字段形状复算一遍（`镜头` 由取景求解器后补，
  `对白=dialogue`、运镜走 `movements[].kind`）；
* 别名/全半角归一后 `static` 与 `固定` 是同一个值（否则一边写引擎名、一边写
  中文别名的 oracle 永远 join 不上，这是实测踩过的死值）；
* 分母为 0 记 `not_measured` 并**报出真实发出的契约串**，绝不当成"通过"；
* 判据是**相等**，子集匹配只作诊断单独记账（放宽判据不许偷偷变成分子）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import quality as Q  # noqa: E402


def _shot(shot_id, *, shot_type="MCU", lens=50.0, movements=(), actions=(),
          dialogues=()) -> dict:
    return {
        "shot_id": shot_id,
        "shot_type": shot_type,
        "camera": {"lens": lens},
        "movements": [{"kind": kind} for kind in movements],
        "action_types": list(actions),
        "dialogue_ids": list(dialogues),
    }


def _write(tmp_path: pathlib.Path, shots) -> pathlib.Path:
    path = tmp_path / "shots.json"
    path.write_text(json.dumps({"shots": shots}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def test_the_plan_query_comes_from_the_same_producer_as_the_contract():
    """正对照：`shots.json` 的字段被折成契约串，且折法与引擎同源。"""
    record = _shot("shot_001", shot_type="CU", lens=85.0,
                   movements=["dolly_in"], dialogues=["d1"])
    assert Q.plan_query_of_shot(record) == "景别=CU；镜头=85mm；运镜=dolly_in；对白=dialogue"


def test_a_shot_without_a_lens_or_extras_is_only_the_shot_size():
    """负对照：没有焦距、没有运镜/动作/对白时，契约串只剩景别——不许伪造键。"""
    assert Q.plan_query_of_shot(_shot("shot_002", shot_type="ELS", lens=None)) == "景别=ELS"


def test_a_locked_off_shot_is_static_and_can_satisfy_the_expectation(tmp_path):
    """一条运镜都没排 = 机位锁死 = 词表里的 `固定`；作者期望 `固定` 时命中。"""
    shots = _write(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0)])
    entries = [{"id": "hq_1", "q": "景别=MS；镜头=50mm", "expect_movements": ["固定"]}]
    report = Q.q5_run_join(entries, shots)
    assert report["denominator"] == 1
    assert report["numerator"] == 1
    assert report["status"] == Q.PASS


def test_equality_join_honours_movement_aliases(tmp_path):
    """`static` / `fixed` 与中文规范值 `固定` 归一后算同一个值（实测踩过的死值）。"""
    shots = _write(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0,
                                    movements=["static"])])
    entries = [{"id": "hq_1", "q": "景别=MS；镜头=50mm；运镜=static",
                "expect_movements": ["固定"]}]
    report = Q.q5_run_join(entries, shots)
    assert report["denominator"] == 1
    assert report["numerator"] == 1


def test_a_shot_that_declares_no_movement_does_not_satisfy_the_expectation(tmp_path):
    """负对照：作者期望 `dolly_in`、而这一镜一条运镜都没排 → 分子不进。"""
    shots = _write(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0)])
    entries = [{"id": "hq_1", "q": "景别=MS；镜头=50mm", "expect_movements": ["dolly_in"]}]
    report = Q.q5_run_join(entries, shots)
    assert report["denominator"] == 1
    assert report["numerator"] == 0
    assert report["status"] == Q.FAIL


def test_zero_matches_is_not_measured_and_names_the_queries(tmp_path):
    """分母为 0：记 `not_measured`，并把真实发出的契约串报出来。"""
    shots = _write(tmp_path, [_shot("shot_001", shot_type="MCU", lens=50.0,
                                    dialogues=["d1"])])
    entries = [{"id": "hq_1", "q": "景别=MCU；镜头=50mm", "expect_movements": ["固定"]}]
    report = Q.q5_run_join(entries, shots)
    assert report["status"] == Q.NA
    assert report["denominator"] == 0
    # 相等判据 0 命中，但子集判据命中 1 条——两个数**分开**报，不许混。
    assert report["subset_denominator"] == 1
    assert report["plan_queries"] == ["景别=MCU；镜头=50mm；对白=dialogue"]
    assert "not_measured" in report["note"]


def test_entries_without_expect_movements_never_enter_the_join(tmp_path):
    """没有 `expect_movements` 的条目（其余 2800+ 条）不是 Q5 的样本。"""
    shots = _write(tmp_path, [_shot("shot_001")])
    entries = [{"id": "hq_1", "q": "景别=MCU；镜头=50mm"}]
    report = Q.q5_run_join(entries, shots)
    assert report["fixture_entries"] == 0
    assert report["denominator"] == 0


def test_the_shipped_plan_shaped_entries_are_really_plan_shaped():
    """入库 oracle 里那一批必须是**计划形状**（键 ⊆ 生产者会产出的键）。"""
    from tools.holdout_score import load_holdout

    entries = load_holdout(ROOT / "fixtures" / "knowledge_holdout.jsonl")
    shaped = [entry for entry in entries if Q._normalise_query_pairs(entry.get("q"))]
    shaped = [entry for entry in shaped
              if {key for key, _value in Q._normalise_query_pairs(entry["q"])}
              <= set(Q.PLAN_QUERY_KEYS)]
    # §4.1b 的 Q5 夹具侧下界是 30；这一批就是它能用的全部样本。
    assert len(shaped) >= Q.MIN_Q5_FIXTURE_ITEMS
