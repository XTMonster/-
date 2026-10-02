"""零原子卡的**有界补抽**：它是"不可复现的抽取器"与"门⑥ 的覆盖率"之间的那一层。

实测病因（2026-10-02）：`tools/kb_fetch/build_hypergraph.py` 里没有原子边缓存，
每次构建都会**重新调一次模型**。同一份语料连建两次得到
`edges 662 / atoms 2527` 与 `edges 667 / atoms 2484`——产物不逐字节一致；
而一次语料扩容之后的构建里，**462 张卡整轮一条边都没拿到**，
门⑥ 的 `expressible_share` 从 96.3% 掉到 80.4%。也就是说那条门当时量的不是
"语料能不能表达"，而是"这一轮抽样运气如何"。

这一层**不放宽任何判据**：只对"零原子边"的卡换一次取样再抽几轮，
词表、门限、判据一个字都没动，没救回来的卡照旧进 `excluded`。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import build_hypergraph as bh  # noqa: E402


def _cards():
    return [
        {"id": "c1", "domain": "cinematography", "title": "one", "content": "body one",
         "source_span": {"chunk_id": "chunk#1", "start": 0, "end": 10}},
        {"id": "c2", "domain": "cinematography", "title": "two", "content": "body two",
         "source_span": {"chunk_id": "chunk#2", "start": 0, "end": 10}},
    ]


def _edge(source_card: str) -> dict:
    return {"source_card": source_card, "type": "EMOTION_PACK",
            "members": [["allow", "emotion", "emotion:荒诞"],
                        ["qualifier", "intensity", "intensity:high"]],
            "source_kind": "theory", "hardness": "hard", "confidence": 0.7}


class _FlakyClient:
    """第一次（主轮）整批不回边；补抽那一轮（不同温度）才给 c2 一条边。"""

    model_id = "fake"
    family = "fake"
    model_version = "fake"

    def __init__(self, first_pass_edges_for=(), later_edges_for=("c2",)):
        self.calls = []
        self._first = set(first_pass_edges_for)
        self._later = set(later_edges_for)

    def chat_json(self, system, user, temperature, seed, num_ctx, key=None):
        cards = re.findall(r"^### (\S+?)（", user, re.M)
        self.calls.append({"key": key, "temperature": temperature, "keys": cards})
        wanted = self._first if temperature == 0.0 else self._later
        return {"edges": [_edge(card) for card in cards if card in wanted]}


def test_backfill_recovers_cards_the_first_draw_missed():
    client = _FlakyClient()
    atoms, rejects, log = bh.extract(_cards(), {}, client, concurrency=1)
    assert bh.cards_without_atoms(_cards(), atoms) == ["c1", "c2"]

    atoms, report = bh.backfill_empty_cards(_cards(), {}, client, atoms, rejects, log,
                                            concurrency=1, rounds=3)
    assert report["cards_empty_before"] == 2
    assert report["recovered"] == 1
    assert bh.cards_without_atoms(_cards(), atoms) == ["c1"]
    assert report["rounds"][0]["atoms_added"] == 1


def test_backfill_only_touches_the_empty_cards():
    """主轮已经拿到边的卡**不许**被重抽——补抽不是"整库再来一遍"。"""
    client = _FlakyClient(first_pass_edges_for=("c1",))
    atoms, rejects, log = bh.extract(_cards(), {}, client, concurrency=1)
    assert bh.cards_without_atoms(_cards(), atoms) == ["c2"]
    client.calls.clear()
    bh.backfill_empty_cards(_cards(), {}, client, atoms, rejects, log,
                            concurrency=1, rounds=1)
    asked = {card for call in client.calls for card in call["keys"]}
    assert asked == {"c2"}, asked


def test_backfill_uses_a_different_temperature_than_the_main_round():
    """同温同提示会把同一份失败逐字重放（缺口轮的已知坑）。"""
    client = _FlakyClient()
    atoms, rejects, log = bh.extract(_cards(), {}, client, concurrency=1)
    main = {call["temperature"] for call in client.calls}
    client.calls.clear()
    bh.backfill_empty_cards(_cards(), {}, client, atoms, rejects, log,
                            concurrency=1, rounds=1)
    backfill = {call["temperature"] for call in client.calls}
    assert main == {0.0}
    assert backfill == {bh.BACKFILL_TEMPERATURE}
    assert bh.BACKFILL_TEMPERATURE != 0.0


def test_backfill_stops_when_a_round_recovers_nothing():
    client = _FlakyClient(later_edges_for=())
    atoms, rejects, log = bh.extract(_cards(), {}, client, concurrency=1)
    before = len(client.calls)
    atoms, report = bh.backfill_empty_cards(_cards(), {}, client, atoms, rejects, log,
                                            concurrency=1, rounds=5)
    assert len(report["rounds"]) == 1, "一轮没救回任何卡就该停，不许空转"
    assert report["recovered"] == 0
    assert len(client.calls) > before


def test_backfill_entries_stay_extraction_batches():
    """补抽批次仍是**抽取批次**：status 只有那三种，否则 Q0 的 `processed` 会失真。"""
    client = _FlakyClient()
    atoms, rejects, log = bh.extract(_cards(), {}, client, concurrency=1)
    bh.backfill_empty_cards(_cards(), {}, client, atoms, rejects, log,
                            concurrency=1, rounds=1)
    assert {entry["status"] for entry in log} == {"done"}
    assert all(entry.get("backfill_round") == 1
               for entry in log if entry.get("backfill_round"))
    #: chunk 计数必须把补抽抽过的 chunk 计进 processed
    processed, total = bh.chunk_counts(_cards(), log, atoms)
    assert (processed, total) == (2, 2)


def test_rematch_carries_the_backfill_ledger_over(tmp_path, monkeypatch):
    """`--rematch` 只重跑第 2 段，**不许**把第 1 段的补抽账丢掉。

    同一形状的缺陷上一轮已经在 `refresh` 上发生过一次（`tests/test_build_ledger.py`
    的注释）：`rematch` 建一份全新的 merge_report，上一轮的账就此消失，manifest
    于是声称"整库一次抽成"。补抽账同理。
    """
    atoms = tmp_path / "atoms.jsonl"
    atoms.write_text("", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"extractor": {"model_id": "fake",
                                                  "family": "fake",
                                                  "model_version": "fake"},
                                     "batches": []}), encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"merge": {"backfill": {
        "rounds": [{"round": 1, "asked": 97, "atoms_added": 52, "still_empty": 47}],
        "cards_empty_before": 97, "cards_empty_after": 20, "recovered": 77}}}),
        encoding="utf-8")
    for name, value in (("ATOMS", atoms), ("MANIFEST", manifest), ("REPORT", report),
                        ("EDGES", tmp_path / "edges.jsonl"),
                        ("REJECTS", tmp_path / "rejects.jsonl"),
                        ("ATOM_REJECTS", tmp_path / "atom_rejects.jsonl")):
        monkeypatch.setattr(bh, name, value)
    monkeypatch.setattr(bh, "nodes_from_vocab", lambda: {})
    monkeypatch.setattr(bh, "merge_edges", lambda *a, **k: ([], {
        "windows": 0, "groups": 0, "merged_edges": 0, "multi_card_edges": 0,
        "forbid_wins": 0, "dropped_optional": 0, "over_budget_dropped": 0,
        "forbid_members": 0, "max_arity": 0, "dropped_groups": [], "alternatives": 0}))

    bh.rematch(_cards(), {})
    written = json.loads(manifest.read_text(encoding="utf-8"))["merge"]["backfill"]
    assert written["rounds"] == [{"round": 1, "asked": 97, "atoms_added": 52,
                                  "still_empty": 47}]
    assert written["recovered"] == 77
    assert written["cards_empty_after"] == 2, "空卡数必须按**本次写出去的**原子边现算"


def test_shipped_manifest_records_the_backfill_ledger():
    """入库 manifest 必须留下 `merge.backfill` 的账（"没写"与"没跑"要分得开）。"""
    manifest = ROOT / "knowledge" / "hypergraph.manifest.json"
    if not manifest.is_file():
        pytest.skip("索引未入库")
    merge = json.loads(manifest.read_text(encoding="utf-8")).get("merge") or {}
    ledger = merge.get("backfill")
    assert isinstance(ledger, dict), (
        "manifest 没有 `merge.backfill`：抽取器不可复现，"
        "零原子卡的补抽过程必须可对账（见 tests/test_hypergraph_backfill.py 的说明）")
    for key in ("rounds", "cards_empty_before", "cards_empty_after", "recovered"):
        assert key in ledger, f"backfill 账缺 `{key}`"


def test_the_ledger_stays_true_when_the_backfill_is_switched_off():
    """`--backfill-rounds 0`（关掉补抽）**仍然是一笔正确的账**。

    2026-10-02 实测到的形状：原先 `cards_empty_before` 写的是"第一轮问了多少张"，
    轮数为 0 时那个值停在初始的 0，于是同一份报告同时写着
    `cards_empty_before: 0`、`cards_empty_after: 2`、`recovered: -2` —— 自相矛盾，
    而 `recovered` 是负数这件事**没有任何门会去查**。判据：这两个数都必须是
    "进入这一层时"与"跑完之后"的**实际**零原子卡数。
    """
    client = _FlakyClient()
    atoms, rejects, log = bh.extract(_cards(), {}, client, concurrency=1)
    assert bh.cards_without_atoms(_cards(), atoms) == ["c1", "c2"]
    _, report = bh.backfill_empty_cards(_cards(), {}, client, atoms, rejects, log,
                                        concurrency=1, rounds=0)
    assert report["rounds"] == [], "0 轮就什么都不该跑"
    assert report["cards_empty_before"] == 2
    assert report["cards_empty_after"] == 2
    assert report["recovered"] == 0, (
        f"关掉补抽却被记成救回了东西（或救回负数）：{report}")
