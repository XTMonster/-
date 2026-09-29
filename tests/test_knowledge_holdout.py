"""P14-1 的词表与 held-out 生成（执行文档 v1.4 §2.3c/§4.1b）。

离线：标注后端用 scripted，覆盖门用 `tools/check_holdout.py` 的**真实**判定。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from block_director.contracts.knowledge import Card
from block_director.knowledge import hypergraph as hg
from tools import check_holdout
from tools.kb_fetch import common, holdout_gen, vocabulary


def card(card_id: str, domain: str, title: str, content: str, tags=(), keywords=(),
         emotion: str = "") -> Card:
    return Card(id=card_id, domain=domain, title=title, content=content,
                tags=list(tags), keywords=list(keywords), emotion=emotion)


CARDS = [
    card("gen_cine_0001", "cinematography", "低机位与权力",
         "低机位拍摄让被摄者显得高大；仰角超过十五度观众会察觉到机位在表达权力。",
         tags=["低机位", "仰拍"], keywords=["低机位", "权力"], emotion="压迫"),
    card("gen_edit_0001", "editing", "短镜硬切",
         "荒诞的段落用短镜硬切，节奏取 short，平均镜头长度落在 1-3s。",
         tags=["短镜", "快切"], keywords=["整体节奏"]),
    card("gen_cine_0002", "cinematography", "长焦压缩",
         "85mm 长焦压缩空间，适合把人物从背景里剥离出来。",
         tags=["特写"], keywords=["85mm", "焦段"]),
]

#: `VALUE_DOMAINS` 里有枚举的 kind（`example_shot` 是自由文本，不在此列）。
ENUM_KINDS = tuple(kind for kind, values in hg.VALUE_DOMAINS.items() if values is not None)

#: 门③ 要求词表覆盖全部 14 个查询 kind；取值必须与 `q` 里真正用到的完全一致。
FULL_VOCAB = {
    "emotion": ["荒诞"], "action": ["跺脚"], "movement": ["固定"], "shot_size": ["特写"],
    "lens": ["50mm"], "pacing": ["short"], "vfx": ["petrify"], "sfx": ["心跳"],
    "camera_angle": ["平视"], "lighting": ["逆光"], "composition_rule": ["rule_of_thirds"],
    "axis_topic": ["关系轴"], "genre": ["film"], "beat_type": ["establish"],
    # 两类的取值永远不可能出现在 q 里（没有对应查询键），只作占位
    "character": [], "object": [],
}


# --------------------------------------------------------------------------- 词表


def test_vocabulary_covers_every_kind_and_stays_closed():
    nodes = vocabulary.build_nodes(CARDS)
    kinds = {node["type"] for node in nodes}
    for kind in ENUM_KINDS:
        assert kind in kinds, kind
    # 枚举型的取值必须与 §2.3d T3 完全一致（不许多、不许少）
    for node in nodes:
        domain = hg.VALUE_DOMAINS.get(node["type"])
        if domain is not None and node["type"] != "composition_rule":
            assert node["value"] in domain, node

def test_vocabulary_picks_up_card_values_and_lenses():
    nodes = {node["node_id"]: node for node in vocabulary.build_nodes(CARDS)}
    assert "movement:pan_left" in nodes          # 枚举型运镜
    assert "lens:85mm" in nodes                  # 正文里的焦段
    assert "emotion:压抑" in nodes or "lighting:顶光" in nodes
    vocab = vocabulary.vocab_payload(list(nodes.values()))
    assert "shot_size" in vocab and "MS" in vocab["shot_size"]
    assert all(isinstance(v, list) and v for v in vocab.values())


# --------------------------------------------------------------------------- 标注校验


def test_holdout_entry_validation_accepts_a_wellformed_entry():
    raw = {"from_card": "gen_cine_0001",
           "q": "情绪=荒诞；运镜=固定",
           "must": ["EMOTION_PACK:emotion=荒诞,intensity=high,forbid_movement=固定"],
           "top1": ["EMOTION_PACK:emotion=荒诞,intensity=high,forbid_movement=固定"],
           "never": ["LIGHT_PACK:lighting=逆光,intensity=low"],
           "expect_movements": ["whip_pan"]}
    entry, reason = holdout_gen.validate_entry(raw, {"gen_cine_0001"})
    assert reason == ""
    assert entry["from_card"] == "gen_cine_0001"
    assert entry["expect_movements"] == ["whip_pan"]


@pytest.mark.parametrize("mutate,reason", [
    (lambda e: e.update(from_card="gen_missing"), "unknown_from_card"),
    (lambda e: e.update(must=[]), "must_size"),
    (lambda e: e.update(must=e["must"] * 4), "must_size"),
    (lambda e: e.update(top1=["SHOT_PATTERN:shot_size=CU"]), "top1_not_subset"),
    (lambda e: e.update(never=e["must"]), "never_overlaps_must"),
    (lambda e: e.update(must=["NOT_A_TYPE:emotion=x"], top1=["NOT_A_TYPE:emotion=x"]),
     "bad_type"),
    (lambda e: e.update(must=["EMOTION_PACK:emotion=荒诞"],
                        top1=["EMOTION_PACK:emotion=荒诞"]), "missing_slots"),
])
def test_holdout_entry_validation_rejects_broken_entries(mutate, reason):
    raw = {"from_card": "gen_cine_0001", "q": "情绪=荒诞",
           "must": ["EMOTION_PACK:emotion=荒诞,intensity=high"],
           "top1": ["EMOTION_PACK:emotion=荒诞,intensity=high"], "never": []}
    mutate(raw)
    entry, got = holdout_gen.validate_entry(raw, {"gen_cine_0001"})
    assert entry is None
    assert reason in got


def test_holdout_generation_writes_annotator_metadata(tmp_path, monkeypatch):
    holdout = tmp_path / "holdout.jsonl"
    cards_json = tmp_path / "cards.json"
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(holdout_gen, "HOLDOUT", holdout)
    monkeypatch.setattr(holdout_gen, "CARDS_JSON", cards_json)
    monkeypatch.setattr(holdout_gen, "MANIFEST", manifest)

    scripted = tmp_path / "scripted.json"
    scripted.write_text(json.dumps({"responses": {
        "gen_cine_0001": {"entries": [
            {"from_card": "gen_cine_0001", "q": "情绪=荒诞；运镜=固定",
             "must": ["EMOTION_PACK:emotion=荒诞,intensity=high"],
             "top1": ["EMOTION_PACK:emotion=荒诞,intensity=high"], "never": []}]},
        "gen_edit_0001": {"entries": [
            {"from_card": "gen_edit_0001", "q": "节奏=short",
             "must": ["EDIT_RHYTHM:pacing=short,avg_shot_len=1-3s"],
             "top1": ["EDIT_RHYTHM:pacing=short,avg_shot_len=1-3s"], "never": []}]},
        "gen_cine_0002": {"entries": [
            {"from_card": "gen_cine_0002", "q": "镜头=85mm",
             "must": ["SHOT_PATTERN:shot_size=特写,lens=85mm,headroom_policy=board"],
             "top1": ["SHOT_PATTERN:shot_size=特写,lens=85mm,headroom_policy=board"],
             "never": []}]},
    }}, ensure_ascii=False), encoding="utf-8")

    vocab = vocabulary.vocab_payload(vocabulary.build_nodes(CARDS))
    cards = [{"id": c.id, "domain": c.domain, "title": c.title, "content": c.content,
              "tags": list(c.tags), "keywords": list(c.keywords), "emotion": c.emotion}
             for c in CARDS]
    client = holdout_gen.llm.make_client("scripted", "qwen-fake", str(scripted))
    entries, rejects = holdout_gen.run(cards, vocab, client, batch_size=1)
    assert len(entries) == 3
    assert all(e["annotator"]["family"] == "scripted" for e in entries)
    assert all(e["independence"] == "strong" for e in entries)
    assert [e["id"] for e in entries] == ["hq_0001", "hq_0002", "hq_0003"]
    assert json.loads(manifest.read_text(encoding="utf-8"))["entries"] == 3
    assert json.loads(cards_json.read_text(encoding="utf-8")) == sorted(
        c.id for c in CARDS)


# --------------------------------------------------------------------------- 覆盖门


#: 一条覆盖全部 14 个查询 kind 的 q（门③ 要求每个词表取值都被用到）
Q_ALL = ("情绪=荒诞；动作=跺脚；运镜=固定；景别=特写；镜头=50mm；节奏=short；"
         "特效=petrify；音效=心跳；机位=平视；光线=逆光；构图=rule_of_thirds；"
         "轴线=关系轴；题材=film；桥段=establish")

SPEC_BY_TYPE = {
    "EMOTION_PACK": "EMOTION_PACK:emotion=荒诞,intensity=high,forbid_shot_size=特写",
    "SHOT_PATTERN": "SHOT_PATTERN:shot_size=特写,lens=50mm,headroom_policy=board",
    "AXIS_RULE": "AXIS_RULE:pair=any_two,axis_side=left",
    "TROPE": "TROPE:genre=film,emotion=荒诞",
    "EDIT_RHYTHM": "EDIT_RHYTHM:pacing=short,avg_shot_len=1-3s",
    "LIGHT_PACK": "LIGHT_PACK:lighting=逆光,intensity=high",
}


def _write_full_fixture(path: pathlib.Path, per_type: int = 40,
                        emotion_pack: int = 60) -> list:
    """6 类边各 `per_type` 条（EMOTION_PACK 取 `emotion_pack` 条，因为它独占禁忌）。"""
    lines = []
    counter = 0
    for etype, spec in SPEC_BY_TYPE.items():
        count = emotion_pack if etype == "EMOTION_PACK" else per_type
        for index in range(count):
            counter += 1
            # EMOTION_PACK 是唯一允许 `forbid` 成员的边类型（§2.3 的边表），
            # 因此 Q7 的冲突条目全部由它贡献：每张卡出两条（两种禁忌各一条）。
            specs = [spec]
            if etype == "EMOTION_PACK":
                specs.append("EMOTION_PACK:emotion=荒诞,intensity=high,"
                             "forbid_movement=固定")
            entry = {
                "id": f"hq_{counter:04d}",
                "from_card": f"gen_{etype.lower()}_{index:04d}",
                "q": Q_ALL,
                "must": specs,
                "top1": [specs[0]],
                "never": [],
                "annotator": {"model_id": "qwen3-vl:30b", "family": "qwen",
                              "model_version": "30b"},
                "independence": "strong",
                "expect_movements": ["固定"],
            }
            if counter <= 120:
                entry["review"] = {"reviewed_by": "human", "verdict": "accepted"}
            lines.append(json.dumps(entry, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [json.loads(line)["from_card"] for line in lines]


def _vocab_payload(kinds: dict) -> dict:
    return {"_fingerprint": "test-fingerprint", "kinds": kinds}


def test_coverage_gates_pass_on_a_complete_fixture(tmp_path, capsys):
    holdout = tmp_path / "holdout.jsonl"
    vocab = tmp_path / "vocab.json"
    cards = tmp_path / "cards.json"
    card_ids = _write_full_fixture(holdout, per_type=40)
    vocab.write_text(json.dumps(_vocab_payload(FULL_VOCAB), ensure_ascii=False),
                     encoding="utf-8")
    cards.write_text(json.dumps(sorted(card_ids)), encoding="utf-8")
    code = check_holdout.main([str(holdout), "--min-entries", "240", "--min-per-type", "30",
                               "--min-cards-per-type", "10", "--min-forbid", "60",
                               "--min-human-review", "120", "--vocab", str(vocab),
                               "--cards", str(cards), "--json"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["overall"] == check_holdout.PASS
    assert report["gate_5_forbid"]["q7_conflicts"] == 60
    assert report["gate_6_sources"]["missing_count"] == 0
    assert report["gate_3_seed_coverage"]["status"] == check_holdout.PASS
    assert report["gate_7_human_review"]["status"] == check_holdout.PASS


def test_coverage_gates_fail_when_a_card_has_no_entry(tmp_path, capsys):
    holdout = tmp_path / "holdout.jsonl"
    vocab = tmp_path / "vocab.json"
    cards = tmp_path / "cards.json"
    card_ids = _write_full_fixture(holdout, per_type=40)
    sparse = {k: list(v) for k, v in FULL_VOCAB.items()}
    sparse["shot_size"] = ["特写", "中景"]
    vocab.write_text(json.dumps(_vocab_payload(sparse), ensure_ascii=False),
                     encoding="utf-8")
    cards.write_text(json.dumps(sorted(set(card_ids) | {"gen_never_queried"})),
                     encoding="utf-8")
    code = check_holdout.main([str(holdout), "--min-entries", "240", "--min-per-type", "30",
                               "--min-cards-per-type", "10", "--min-forbid", "60",
                               "--min-human-review", "120", "--vocab", str(vocab),
                               "--cards", str(cards), "--json"])
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["gate_6_sources"]["status"] == check_holdout.FAIL
    assert "gen_never_queried" in report["gate_6_sources"]["missing_cards"]
    # 词表里没被任何 q 用到的取值同样必须让门③变红
    assert report["gate_3_seed_coverage"]["status"] == check_holdout.FAIL
    assert "中景" in report["gate_3_seed_coverage"]["missing_values"]["shot_size"]


def test_holdout_requires_independent_annotation_channel(tmp_path, capsys):
    """R49 第 1 条：缺 annotator / family 的集合不得作为 oracle。"""
    holdout = tmp_path / "holdout.jsonl"
    holdout.write_text(json.dumps({
        "id": "hq_0001", "from_card": "c1", "q": "情绪=荒诞",
        "must": ["EMOTION_PACK:emotion=荒诞,intensity=high"],
        "top1": ["EMOTION_PACK:emotion=荒诞,intensity=high"], "never": [],
        "annotator": {"model_id": "qwen"},  # 缺 family/model_version = 换族证据链断裂
        "independence": "strong",
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    code = check_holdout.main([str(holdout), "--json"])
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["gate_2_format"]["status"] == check_holdout.FAIL
    assert any("annotator" in problem for problem in report["gate_2_format"]["problems"])


def test_human_review_gate_cannot_be_faked_by_an_agent(tmp_path, capsys):
    """协议 §5.5：Q5/Q7 条目必须带**人**的裁决；agent 自评不算（这里 agent 署名）。"""
    holdout = tmp_path / "holdout.jsonl"
    vocab = tmp_path / "vocab.json"
    cards = tmp_path / "cards.json"
    card_ids = _write_full_fixture(holdout, per_type=40)
    lines = holdout.read_text(encoding="utf-8").splitlines()
    patched = []
    for line in lines:  # 把"人裁决"改签成一个 agent 名字
        record = json.loads(line)
        if record.get("review"):
            record["review"] = {"reviewed_by": "codex-agent", "verdict": "accepted"}
        patched.append(json.dumps(record, ensure_ascii=False))
    holdout.write_text("\n".join(patched) + "\n", encoding="utf-8")
    vocab.write_text(json.dumps(_vocab_payload(FULL_VOCAB), ensure_ascii=False),
                     encoding="utf-8")
    cards.write_text(json.dumps(sorted(card_ids)), encoding="utf-8")
    code = check_holdout.main([str(holdout), "--min-entries", "240", "--min-per-type", "30",
                               "--min-cards-per-type", "10", "--min-forbid", "60",
                               "--min-human-review", "120", "--vocab", str(vocab),
                               "--cards", str(cards), "--json"])
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["gate_7_human_review"]["status"] == check_holdout.FAIL
    assert report["gate_7_human_review"]["human_reviewed"] == 0
