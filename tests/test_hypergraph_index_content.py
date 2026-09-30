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
REJECTS_FILE = ROOT / "knowledge" / "hypergraph.rejects.jsonl"


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


def test_the_reject_ledger_adds_up():
    """manifest 的账必须与落盘文件逐条对得上，且恒等式 `raw = valid + dup + rejects` 成立。

    这条是 P14-5 的 Q0 判据：只写个汇总数字、明细却放在别处（或反过来）时，
    外部无法判断索引到底被门挡掉了多少东西。
    """
    edges = _read_jsonl(EDGES_FILE)
    rejects = _read_jsonl(REJECTS_FILE)
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    assert manifest["rejects"] == len(rejects), (
        f"manifest 说 rejects={manifest['rejects']}，rejects 文件却有 {len(rejects)} 行")
    assert len(edges) == manifest["valid_unique"]
    assert manifest["raw_edges"] == (manifest["valid_unique"] + manifest["duplicates"]
                                     + manifest["rejects"])


def test_forbid_kinds_are_real_nodes():
    """禁忌成员必须能在节点表里解析出来，否则渲染/检索都拿不到它的名字。"""
    node_ids = {node["node_id"] for node in _read_jsonl(NODES_FILE)}
    for edge in _read_jsonl(EDGES_FILE):
        for member in edge["members"]:
            assert member[2] in node_ids, f"{edge['edge_id']} 的成员 {member[2]} 不在节点表里"


def test_retrieval_actually_returns_a_forbid_carrying_edge():
    """§2.3 的"闭合输出"必须能从检索侧拿到：命中就整条返回，禁忌一起带出来。

    只看索引文件是不够的——`forbid` 成员存在但检索路径把它们丢掉，Q6b/Q7 一样是 0。
    这里用**解析出来的查询串**（节点名反推，不手写）走一遍真实的 `Hypergraph.retrieve`。
    """
    from block_director.knowledge.hypergraph import Hypergraph, Node, HyperEdge, parse_query

    nodes = {row["node_id"]: Node.from_dict(row) for row in _read_jsonl(NODES_FILE)}
    edges = [HyperEdge.from_dict(row) for row in _read_jsonl(EDGES_FILE)]
    graph = Hypergraph(list(nodes.values()), edges)

    # **单一真源**：键表从 schema 渲染，不在这里再抄一份。抄的那份曾经少了
    # `intensity` 等 kind，于是测试自己构造出"说不出强度"的**弱查询**，再用它
    # 断言"这条边召不回自己"——那是测试的缺陷，不是索引的缺陷。
    from block_director.knowledge import hypergraph as hg

    zh = {kind: key for key, kind in hg.QUERY_KEYS.items()}
    checked = 0
    missed = []
    for edge in edges:
        if not edge.forbids:
            continue
        # 用这条边**自己的**成员拼一个 SceneContract 串：它讲的东西查询里全有，
        # 召回率低就说明"闭合输出"在检索侧被丢了，而不是查询没写对。
        parts = []
        # allow／qualifier／forbid **都要**写进查询：门⑨ 的口径就是"must 里每个
        # 可查询槽位都能在 q 里逐字找到"，漏掉 qualifier 会让近邻边无法区分。
        for member in list(edge.allows) + list(edge.qualifiers) + list(edge.forbids):
            key = zh.get(member.kind)
            name = nodes[member.node_id].name or member.node_id
            item = f"{key}={name}" if key else None
            if item and item not in parts:
                parts.append(item)
        if not parts:
            continue
        checked += 1
        query = "；".join(parts[:5])
        parse_query(query)
        selected, text, _trace = graph.retrieve(query, top_k=20)
        hit = [item for item in selected if item.edge_id == edge.edge_id]
        if not hit or not hit[0].forbids:
            missed.append(edge.edge_id)
            continue
        for member in hit[0].forbids:
            assert (nodes[member.node_id].name or member.node_id) in text, \
                "渲染出来的注入文本里没有禁忌成员"
    assert checked >= 1, "索引里没有带禁忌的边（见上一个用例）"
    assert not missed, f"有 {len(missed)}/{checked} 条带禁忌的边召不回自己：{missed[:3]}"
