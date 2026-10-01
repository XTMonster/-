"""`forbid` 成员的理据审计（`tools/kb_fetch/forbid_audit.py`）的对抗性用例。

缺陷的形状（2026-10-02 实测）：v10 的规则 8d 说 `forbid_<kind>=取值` 只在卡里
明确写"不要／避免／切忌"时才写，但**它只在 122 张卡上执行过**。全量重抽之后
索引里仍有 49 个 forbid 成员；逐条审下来**只有 7 条**在来源卡里找得到依据。

典型样本：`cine_move_and_axis`（讲运镜会换轴侧、**硬切**换侧禁止）被抽出了
`forbid_movement=固定` —— 那张卡从头到尾没提固定机位，"硬切"也不是运镜取值。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import forbid_audit as FA  # noqa: E402
from tools.holdout_score import load_graph  # noqa: E402

NODES = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
EDGES = ROOT / "knowledge" / "hypergraph.edges.jsonl"


class _Stub:
    """按卡 id 决定判决：写着「禁忌」的卡判 grounded，其余判 ungrounded。"""

    model_id = "stub"
    model_version = "stub"
    family = "deepseek"

    def __init__(self, grounded_cards):
        self.grounded_cards = set(grounded_cards)
        self.calls = 0

    def chat_json(self, system, user, temperature, seed, num_ctx, retries=3):
        self.calls += 1
        # 只看**卡片正文**里的「禁忌：」——提示模板本身含有"禁忌"二字，
        # 用宽松匹配会让每个探针都判 grounded（这条注记就是踩过坑留下的）。
        grounded = "禁忌：" in user
        return {"grounded": grounded, "quote": "禁忌：……" if grounded else "",
                "reason": "卡里写了" if grounded else "卡里没写"}


def test_claims_are_one_row_per_edge_member_and_card():
    """一条 `forbid` 成员 × 一张来源卡 = 一条待审主张，且主张文本逐字可读。"""
    if not (NODES.is_file() and EDGES.is_file()):
        return
    graph = load_graph(NODES, EDGES)
    cards = {str(edge.sources[0]): "卡片正文" for edge in graph.edges if edge.sources}
    items = FA.claims(graph, cards)
    assert items, "当前索引里必须有 forbid 成员（否则这条测试是空过的）"
    for item in items:
        assert item["claim"].startswith("forbid ")
        assert item["card"] in cards
        assert item["value"] and item["kind"]
    assert len({(i["edge_id"], i["kind"], i["value"]) for i in items}) >= 1


def test_a_claim_is_dropped_only_when_no_source_card_states_it():
    """**核心判据**：一张卡写了禁忌，这条主张对这个来源就成立；全都说不清才摘。"""
    items = [
        {"edge_id": "e1", "type": "LIGHT_PACK", "card": "c1", "kind": "lighting",
         "value": "正面光", "claim": "forbid lighting=正面光"},
        {"edge_id": "e1", "type": "LIGHT_PACK", "card": "c2", "kind": "lighting",
         "value": "正面光", "claim": "forbid lighting=正面光"},
        {"edge_id": "e2", "type": "MUSIC_PACK", "card": "c3", "kind": "music",
         "value": "铺底", "claim": "forbid music=铺底"},
    ]
    cards = {"c1": "禁忌：主光不要放在画面正中", "c2": "讲的是别的", "c3": "讲的是别的"}
    report = FA.audit(items, cards, _Stub(grounded_cards=()))
    # e1 有一张卡写了禁忌 → 整体保留；e2 全都说不清 → 进 ungrounded
    assert "e1" in report["grounded_edges"]
    assert "e2" in report["ungrounded_edges"]
    assert "e1" not in report["ungrounded_edges"]


def test_apply_only_touches_forbid_members_and_is_idempotent(tmp_path):
    """`--apply` 只摘 `role=forbid` 的成员，不动 allow/qualifier；再跑一次不再变。"""
    atoms = tmp_path / "atoms.jsonl"
    rows = [
        {"record": "edge", "edge_id": "e1", "sources": ["c1"], "type": "LIGHT_PACK",
         "members": [["allow", "lighting", "lighting:逆光"],
                     ["qualifier", "intensity", "intensity:high"],
                     ["forbid", "lighting", "lighting:正面光"]]},
        {"record": "edge", "edge_id": "e2", "sources": ["c2"], "type": "LIGHT_PACK",
         "members": [["allow", "lighting", "lighting:侧光"],
                     ["qualifier", "intensity", "intensity:mid"]]},
    ]
    atoms.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                     encoding="utf-8")
    report = {"ungrounded": [{"edge_id": "e1", "card": "c1", "kind": "lighting",
                              "value": "正面光", "grounded": False}],
              "kept": [], "errors": []}
    first = FA.apply(atoms, report)
    assert first["members_dropped"] == 1
    written = [json.loads(l) for l in atoms.read_text(encoding="utf-8").split("\n") if l.strip()]
    assert [m[0] for m in written[0]["members"]] == ["allow", "qualifier"]
    assert written[1]["members"] == rows[1]["members"], "别的边一个成员都不许动"
    second = FA.apply(atoms, report)
    assert second["members_dropped"] == 0, "第二次跑不该再摘（幂等）"


def test_a_grounded_claim_on_the_same_edge_protects_it():
    """正对照：同一条边上**另一张卡**写了禁忌时，那条成员必须留着。"""
    rows = [{"record": "edge", "edge_id": "e9", "sources": ["c9"], "type": "LIGHT_PACK",
             "members": [["allow", "lighting", "lighting:逆光"],
                         ["forbid", "lighting", "lighting:正面光"]]}]
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "atoms.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                        encoding="utf-8")
        report = {"ungrounded": [
            {"edge_id": "e9", "card": "c9", "kind": "lighting", "value": "正面光",
             "grounded": False},
            {"edge_id": "e9", "card": "c8", "kind": "lighting", "value": "正面光",
             "grounded": True}],
            "kept": [], "errors": []}
        result = FA.apply(path, report)
        assert result["members_dropped"] == 0


def test_apply_matches_on_the_source_card_not_on_the_merged_edge_id(tmp_path):
    """**核心修正**：按 `(来源卡, kind, 取值)` 摘，不按 `edge_id` 摘。

    审计读的是**归并后**的超边，而归并边只沿用**其中一个**原子边的 `edge_id`。
    按 edge_id 摘，只会摘掉那一张卡的原子边，**同组其它卡的原子边会把它带回来**
    （实测：审出 42 条没依据，重归并后还剩 11 条）。按卡摘才是判据的原义——
    "这张卡有没有说"。
    """
    path = tmp_path / "atoms.jsonl"
    rows = [
        # 两张卡都贡献了同一条 (type, members)，归并后只会留下 c1 的 edge_id
        {"record": "edge", "edge_id": "hx", "sources": ["c1"], "type": "EMOTION_PACK",
         "members": [["allow", "emotion", "emotion:混乱"],
                     ["forbid", "movement", "movement:orbit_cw"]]},
        {"record": "edge", "edge_id": "hy", "sources": ["c2"], "type": "EMOTION_PACK",
         "members": [["allow", "emotion", "emotion:混乱"],
                     ["forbid", "movement", "movement:orbit_cw"]]},
    ]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    report = {
        "ungrounded": [
            {"edge_id": "hx", "card": "c1", "kind": "movement", "value": "orbit_cw",
             "grounded": False},
            {"edge_id": "hx", "card": "c2", "kind": "movement", "value": "orbit_cw",
             "grounded": False},
        ],
        "kept": [], "errors": []}
    result = FA.apply(path, report)
    assert result["members_dropped"] == 2, "两张卡的原子边都要摘掉"
    written = [json.loads(l) for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]
    for row in written:
        assert all(m[0] != "forbid" for m in row["members"]), "重归并时它会被带回来"
