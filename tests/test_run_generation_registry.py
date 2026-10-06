"""**每份已入库运行都必须解析到「已登记代」**（门⑦ gen1→gen2 那次裁决给的最小跳）。

裁决原话（`docs/evidence/20261006-gate7-disambiguation/规格一致性.json`）：
"断言每份运行解析到**已登记代**、链头 pin 覆盖**旧夹具＋增量层**"。

这条守门是**只读**的：它不改那 20 份历史清单（那正是 `repin()` 拒绝的洗白），
只是要求"每份运行 pin 的输入集合"能在 `fixtures/knowledge_holdout.generations.json`
里找到**逐项相等**的那一代——历史运行 pin 的只是夹具 ⇒ 落在 **gen1**；
将来 pin 了夹具＋第三方层的运行 ⇒ 落在 **gen2**；pin 了没登记过的输入 ⇒ **解析不到**（要报出来）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import extract_run_evidence as X  # noqa: E402

GENERATIONS = ROOT / "fixtures" / "knowledge_holdout.generations.json"
REGISTRY = json.loads(GENERATIONS.read_text(encoding="utf-8"))


def _manifests():
    for path in sorted((ROOT / "docs" / "evidence").glob("*/run_manifest.json")):
        yield path, json.loads(path.read_text(encoding="utf-8"))


def test_every_committed_run_resolves_to_a_registered_generation():
    unresolved, resolved = [], {}
    for path, manifest in _manifests():
        generation, why = X.resolve_generation(manifest.get("pins") or {}, GENERATIONS)
        if generation is None:
            unresolved.append((str(path.relative_to(ROOT)), why))
        else:
            resolved.setdefault(generation, []).append(path.parent.name)
    assert not unresolved, ("这些运行解析不到已登记代：%s" % unresolved)
    assert resolved, "一份运行清单都没有？那这条守门是空转"
    #: 真正的不变式是"**解析到的代名都在登记表里**"（不是"必须是某一代"）：
    #: 历史 20 份里 19 份落在 gen1、1 份（`20261003_real`）落在**已退役的** gen0-20261003
    #: （它 pin 的夹具内容没保留，只有指纹）——登记表必须把它显式收进来，
    #: 而不是把陌生 pin 当成 gen1 混过去。
    registered = {item["id"] for item in REGISTRY["generations"]}
    assert set(resolved) <= registered, "出现了登记表以外的代名：%s" % sorted(resolved)
    assert "gen1" in resolved, "现行夹具那一代必须至少有一份运行在用"


def test_the_registry_itself_is_well_formed():
    ids = [item["id"] for item in REGISTRY["generations"]]
    assert REGISTRY["current"] in ids
    assert len(ids) == len(set(ids)), "代名不许重复"
    for item in REGISTRY["generations"]:
        assert item["inputs"], "每一代都要写清自己的输入集合"
        for name, digest in item["inputs"].items():
            assert len(str(digest)) == 64, "%s 的 %s 不是 sha256" % (item["id"], name)


def test_the_generation_chain_is_linear_and_recorded():
    """gen2 必须**写明它从哪一代来**、为什么换、以及还没做完的三步（不许静默换代）。"""
    by_id = {item["id"]: item for item in REGISTRY["generations"]}
    transition = by_id["gen2"].get("transition") or {}
    assert transition.get("from") == "gen1"
    assert transition.get("reason"), "换代理由必须写下来"
    assert transition.get("counts"), "换代要带上计数（keep/flag/drop 各多少）"
    assert transition.get("pending"), "还没做完的步骤要列出来（不许让读者以为已经完工）"
