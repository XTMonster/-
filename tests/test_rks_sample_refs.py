"""`tools/run_tests_rks.py` 的 `sample_ref` 必须点名**真实存在**的探针。

§B.2 L5 要求每次运行的 RK 判定结果里带上"是哪条探针度量的"。这条信息
很容易腐烂成一句"P14 (pending)"——看起来有出处，实际指向不存在的东西。
所以这里做两件事：① 每个 RK 的 `sample_ref` 里的 `.py` 路径必须在仓库里
真的存在；② 不允许再出现 `pending` 这种"计划里的探针"当出处（19 条 RK
现在都有实体探针/用例）。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_tests_rks import RK_TABLE, build_report, rks_for_check  # noqa: E402

_PATH_RE = re.compile(r"[\w./-]+\.py")


def test_table_covers_every_rk_once():
    ids = [row[0] for row in RK_TABLE]
    assert ids == [f"RK-{index}" for index in range(1, 20)]
    assert len(set(ids)) == len(ids)


def test_sample_refs_name_existing_probe_files():
    for rk_id, _expected, sample_ref in RK_TABLE:
        paths = _PATH_RE.findall(sample_ref)
        assert paths, f"{rk_id} 的 sample_ref 没有点名任何探针文件：{sample_ref!r}"
        for path in paths:
            assert (ROOT / path).exists(), f"{rk_id} 指向不存在的探针：{path}"


def test_sample_refs_have_no_pending_placeholders():
    stale = [row[0] for row in RK_TABLE if "pending" in row[2].lower()]
    assert stale == [], f"这些 RK 的出处还是计划里的占位符：{stale}"


def test_check_names_map_back_to_their_rk():
    """探针里 check 名的命名约定必须真的能映射回 RK 编号（否则 measured 会漏）。"""
    assert rks_for_check("rk14_head_is_not_occluded") == {"RK-14"}
    assert rks_for_check("RK-11") == {"RK-11"}
    assert rks_for_check("bake_creates_keyframes") == set()


def test_measured_but_failing_is_not_a_pass():
    """跑过探针 ≠ 通过：`--failed` 点名的 RK 必须记 `pass: False`。

    v1.5 起 RK-13 由 held-out 真判（`tools/holdout_score.py` 退出码 0/1），
    如果只按"这条 RK 的名字出现在检查清单里"就记 pass，那 Q1/Q2 明明没达标
    也会写成一个通过——这正是 §4.1b 要堵的"用跑过代替达标"。
    """
    report = build_report("ut", ["RK-13", "RK-7"], ["RK-13"])
    by_id = {item["rk_id"]: item for item in report["rks"]}
    assert by_id["RK-13"]["status"] == "measured"
    assert by_id["RK-13"]["pass"] is False
    assert by_id["RK-7"]["pass"] is True
    assert report["failed_checks"] == ["RK-13"]
