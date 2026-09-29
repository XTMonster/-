"""入库超图索引的**内容**回归（不是格式，是"它到底有没有知识"）。

为什么需要这个文件：`tests/test_hypergraph_schema.py` 证明每条边**形式合法**，
`tools/holdout_score.py` 证明**检索**能跑——两件事都可能在"索引里一条禁忌都没有"
时全绿。规格 §2.3 的旗舰例子（"荒诞 → 甩镜＋冲击帧＋短镜硬切，且**禁**固定机位"）
恰恰靠 `forbid` 成员承载；§4.1b 又写死 Q7 的分母 = "与某条 `forbid` 冲突的条目数 ≥ 60"。
索引里 `forbid` 恒为 0 时，Q3 的分子恒为 0、Q7 没有可拦截对象——这是**判失败**，
不是"通过"。

所以这里对**入库的** `knowledge/hypergraph.edges.jsonl` 直接下断言：索引必须真的
含禁忌成员、真的含 arity ≥ 3 的 n 元边。缺文件就是缺交付物，**不 skip**。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EDGES_FILE = ROOT / "knowledge" / "hypergraph.edges.jsonl"
NODES_FILE = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
MANIFEST_FILE = ROOT / "knowledge" / "hypergraph.manifest.json"


def _read_jsonl(path: pathlib.Path) -> list:
    assert path.is_file(), f"缺交付物：{path}"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _forbid_count(edge: dict) -> int:
    return sum(1 for member in edge["members"] if member[0] == "forbid")


def test_the_index_carries_forbidden_members():
    """没有禁忌 = 知识库里最贵的那一半没进来（§2.3 的旗舰例子就是禁忌）。"""
    edges = _read_jsonl(EDGES_FILE)
    assert edges, "索引为空"
    with_forbid = [edge for edge in edges if _forbid_count(edge) > 0]
    assert with_forbid, (
        "168 条边里一条 forbid 成员都没有：跨卡归并没生效，Q3/Q7 恒不可判"
    )


def test_the_index_has_true_n_ary_edges():
    """超图的意义在 arity ≥ 3；全是 arity=2 的边等价于一张二元图。"""
    edges = _read_jsonl(EDGES_FILE)
    wide = [edge for edge in edges if len(edge["members"]) >= 3]
    assert wide, "没有一条 arity ≥ 3 的超边——第 2 段归并没把耦合合起来"


def test_forbidden_members_appear_only_where_the_schema_allows_them():
    """§2.3 的边表：只有 EMOTION_PACK 允许 `forbid`，且 kind ∈ {movement, shot_size, vfx}。"""
    allowed = {"movement", "shot_size", "vfx"}
    for edge in _read_jsonl(EDGES_FILE):
        for member in edge["members"]:
            if member[0] != "forbid":
                continue
            assert edge["type"] == "EMOTION_PACK", f"{edge['edge_id']} 越界带 forbid"
            assert member[1] in allowed, f"{edge['edge_id']} 的 forbid kind 非法：{member[1]}"


def test_manifest_merge_block_matches_the_edges_on_disk():
    """manifest 的汇总要么为真，要么不存在——不得自报一个对不上的数字。"""
    edges = _read_jsonl(EDGES_FILE)
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    block = manifest.get("merge")
    assert isinstance(block, dict), "manifest 缺 `merge` 段（第 2 段归并的留痕）"
    assert block["forbid_members"] == sum(_forbid_count(edge) for edge in edges)
    assert block["max_arity"] == max(len(edge["members"]) for edge in edges)


def test_forbid_kinds_are_real_nodes():
    """禁忌成员必须能在节点表里解析出来，否则渲染/检索都拿不到它的名字。"""
    node_ids = {node["node_id"] for node in _read_jsonl(NODES_FILE)}
    for edge in _read_jsonl(EDGES_FILE):
        for member in edge["members"]:
            assert member[2] in node_ids, f"{edge['edge_id']} 的成员 {member[2]} 不在节点表里"
