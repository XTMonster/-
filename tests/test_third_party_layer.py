"""门⑦ 换代 gen1→gen2 的**输入工件**：层要具名、要被 pin、**夹具字节不许动**。

裁决（GLM-5.3，`docs/evidence/20261006-gate7-disambiguation/规格一致性.json`）：
"增量层必须具名为被 pin 的独立输入工件并登记 gen1→gen2，否则是无 pin 的影子输入"；
而"用 A 的机制"＝**夹具字节不动**。

这条守门钉四件事：① 层与它的源**逐位一致**（`--check` 可复算）；
② gen1 与 gen2 的 `holdout` 指纹**逐位相同**（夹具没被动过）；③ 层的计数与裁决类别**如实**；
④ **绝不冒充 `human`**。
"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import common  # noqa: E402
from tools.knowledge import build_third_party_layer as layer  # noqa: E402

LAYER = ROOT / "fixtures" / "knowledge_holdout.third_party.jsonl"
MANIFEST = ROOT / "fixtures" / "knowledge_holdout.third_party.manifest.json"
GENERATIONS = ROOT / "fixtures" / "knowledge_holdout.generations.json"
FIXTURE = ROOT / "fixtures" / "knowledge_holdout.jsonl"


def test_the_layer_and_the_registry_reproduce_from_their_source():
    assert layer.main(["--check"]) == 0, "层／登记必须能从源逐位复算（漂移即红）"


def test_gen1_and_gen2_pin_the_same_fixture_bytes():
    registry = json.loads(GENERATIONS.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in registry["generations"]}
    fixture_sha = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert by_id["gen1"]["inputs"]["holdout"] == fixture_sha
    assert by_id["gen2"]["inputs"]["holdout"] == fixture_sha, (
        "gen2 **必须**与 gen1 pin 同一份夹具字节——这正是'用 A 的机制'那条")
    assert by_id["gen2"]["inputs"]["third_party"] == hashlib.sha256(
        LAYER.read_bytes()).hexdigest(), "层自己要进 pin"
    assert registry["current"] == "gen2"


def test_the_layer_records_the_real_counts_including_the_two_drops():
    rows = [row for row in common.read_jsonl(LAYER) if row]
    assert len(rows) == 212
    counts = collections.Counter(str(row["verdict"]) for row in rows)
    assert dict(counts) == {"accepted": 194, "amended": 16, "rejected": 2}, (
        "**drop 不是 0**：这一轮是 194/16/2 —— 台账里'keep 201/flag 11/drop 0'那句是更早一轮的口径")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["counts"]["selected"] == 212
    assert manifest["source"]["model"], "产出方（模型）必须自述"
    assert manifest["source"]["prompt_sha256"], "提示指纹必须自述"


def test_the_layer_never_claims_human():
    for row in common.read_jsonl(LAYER):
        assert str(row["reviewed_by"]) == "third-party", (
            "第三方代裁**不许**写成 human（那是伪造记录）")
