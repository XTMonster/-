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

from tools.run_tests_rks import RK_TABLE, rks_for_check  # noqa: E402

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
