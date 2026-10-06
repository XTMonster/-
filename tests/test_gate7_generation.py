"""门⑦ 换代 gen2：**层只贴裁决、不改夹具字节、也不动 oracle 的内容**。

裁决（`docs/evidence/20261006-gate7-disambiguation/规格一致性.json`）：gate 的输入一旦含这一层
就是**另一代**；用 A 的机制（夹具字节不动）。这条守门钉四件事：
① 贴上去的裁决**取代**该条目的原复核记录（第三方的裁决就是对面板那一层的再裁）；
② **夹具文件的字节一个都不动**；③ 层里 `amended` 的 `fix` **不在这里生效**（`fixes_applied=False`）；
④ `inputs → 代名` 的解析**逐项相等才算**，多/少一项都回 `none`（不许"看着像"）。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_holdout as ch  # noqa: E402

REGISTRY = ROOT / "fixtures" / "knowledge_holdout.generations.json"
LAYER = ROOT / "fixtures" / "knowledge_holdout.third_party.jsonl"
FIXTURE = ROOT / "fixtures" / "knowledge_holdout.jsonl"


def _entry(ident, *, review=None, q="动作=上下场；桥段=coverage；强度=high；禁运镜=lead_subject"):
    #: `must` 里带一个 `forbid_*` 成员 ⇒ 这条才算"需要人裁"（`gate_entries` 只对
    #: `hits or expect_movements` 的条目计复核类别），与真夹具的形状一致。
    spec = ("ACTION_BEAT:action=上下场,beat_type=coverage,intensity=high,"
            "forbid_movement=lead_subject")
    record = {"id": ident, "from_card": "gen_x", "q": q,
              "must": [spec],
              "top1": [spec],
              "never": ["ACTION_BEAT:action=拿起,beat_type=insert,intensity=mid"],
              "annotator": {"model_id": "glm-4.7", "model_version": "glm-4.7",
                            "family": "zhipu"},
              "independence": "strong", "pilot": False}
    if review:
        record["review"] = review
    return record


def _layer(tmp_path, rows):
    path = tmp_path / "layer.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                    encoding="utf-8")
    return path


def test_the_layer_supersedes_the_panel_review_and_is_counted(tmp_path):
    panel = {"reviewed_by": "llm-panel", "verdict": "accepted", "agreement": True,
             "source": {"models": ["deepseek-chat", "glm-5.3"], "prompt_sha256": "abc"}}
    entries = [_entry("hq_0001", review=panel), _entry("hq_0002", review=panel)]
    layer = _layer(tmp_path, [{"entry_id": "hq_0001", "verdict": "accepted",
                               "reviewed_by": "third-party", "reason": "ok", "fix": "",
                               "agreement": True,
                               "source": {"model": "kimi-k3", "prompt_sha256": "def"}}])
    report = ch.apply_third_party_layer(entries, layer)
    assert report["applied"] == 1 and report["layer_records"] == 1
    assert report["fixes_applied"] is False, "层的 fix 不许在这里生效"
    assert entries[0]["review"]["reviewed_by"] == "third-party"
    assert entries[1]["review"]["reviewed_by"] == "llm-panel", "没被层覆盖的条目原样"
    _status, detail = ch.gate_entries(entries)
    assert detail["problem_count"] == 0, (
        "合成条目必须先是**合法**条目（缺字段会被 gate_entries 记成 problem 并跳过，"
        "那样 reviewed_by_class 会是空的——我上一版就是这么错的）")
    assert detail["reviewed_by_class"] == {"llm-panel": 1, "third-party": 1}


def test_the_layer_never_touches_the_fixture_bytes(tmp_path):
    before = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    entries = [_entry("hq_0122")]
    ch.apply_third_party_layer(entries, LAYER)
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == before, (
        "**夹具文件一个字节都不许动**——这正是'用 A 的机制'那条")


def test_an_amended_fix_is_recorded_but_not_applied(tmp_path):
    entries = [_entry("hq_0001", q="动作=上下场")]
    layer = _layer(tmp_path, [{"entry_id": "hq_0001", "verdict": "amended",
                               "reviewed_by": "third-party", "reason": "改 q",
                               "fix": "动作=拿起", "agreement": False,
                               "source": {"model": "kimi-k3", "prompt_sha256": "x"}}])
    ch.apply_third_party_layer(entries, layer)
    assert entries[0]["q"] == "动作=上下场", "fix 是**记录**，不是本轮生效的改写"
    assert entries[0]["review"]["fix"] == "动作=拿起"


def test_generation_lookup_requires_an_exact_input_set():
    fixture_sha = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    layer_sha = hashlib.sha256(LAYER.read_bytes()).hexdigest()
    assert ch.resolve_generation_id({"holdout": fixture_sha}, REGISTRY) == "gen1"
    assert ch.resolve_generation_id(
        {"holdout": fixture_sha, "third_party": layer_sha}, REGISTRY) == "gen2"
    assert ch.resolve_generation_id(
        {"holdout": fixture_sha, "third_party": "0" * 64}, REGISTRY) == "none", (
        "多 pin 了一个没登记过的输入 ⇒ 解析不到，**不许**当 gen2")
    assert ch.resolve_generation_id({"holdout": "0" * 64}, REGISTRY) == "none"


def test_the_committed_layer_is_what_makes_the_gate_gen2():
    """入库的两份工件必须真的构成 gen2（不然登记表就是空话）。"""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    current = [item for item in registry["generations"] if item["id"] == registry["current"]][0]
    assert current["inputs"]["third_party"] == hashlib.sha256(LAYER.read_bytes()).hexdigest()
    assert current["inputs"]["holdout"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
