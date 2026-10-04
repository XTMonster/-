"""S1a：qualifier 闭集的**惰性键**（`docs/knowledge/PLAN_HYPERGRAPH_v3.md`）。

这一步**判据一个字不动**——只往 `QUALIFIER_KINDS` 里加 `seq_phase`／`carry_shots`。
正因为它不动判据，"门①–⑩ 原样过"就是**恒真式**（红队第 ③ 轮正是拿这一条把
v2 的谓词打掉的）。所以本文件钉的是可判的那三件事：

* **正面（S1a 的谓词）**：trace 里必须**出现**这两个键名（值可 null）；
* **鉴别力**：把键从闭集里撤掉 ⇒ trace 里必须**跟着消失**——否则"出现两个键"
  只是一句同义反复；
* **不变性**：旧契约串仍**逐字**可解析（往闭集里加两个不在 `QUERY_KEYS` 里的
  qualifier，不许影响任何既有查询的解析结果）；
* **代际**：schema 指纹必须换代（S0 那半"加了常量 ⇒ 缓存失效"＋这一半
  "加了常量 ⇒ trace 看得见"，两半合起来才真的堵死静默 no-op）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402

#: S1a 之后必须出现的那两个键名（计划 v3 的 S1a 行逐字点名）。
LAZY_KEYS = ("seq_phase", "carry_shots")

#: 一条既有契约串——"正面"那一半的对照物。
OLD_CONTRACT = "景别=MCU；运镜=固定；对白=dialogue"


def _node(node_id, name=None):
    kind, _, value = node_id.partition(":")
    return hg.Node(node_id, kind, name or value, value=value)


def _edge(members, *, occurrences=1, confidence=0.7):
    return hg.HyperEdge.from_dict({
        "type": hg.EMOTION_PACK,
        "members": [list(item) for item in members],
        "source_kind": "theory", "hardness": "hard",
        "occurrences": occurrences, "confidence": confidence,
        "confidence_max": confidence,
    })


def _scene():
    """一条**一定进注入**的边：它同时带一个 qualifier（`intensity`）。"""
    nodes = [_node("movement:固定", "固定"), _node("shot_size:MS"),
             _node("intensity:high"), _node("emotion:荒诞")]
    edge = _edge([("allow", "emotion", "emotion:荒诞"),
                  ("allow", "shot_size", "shot_size:MS"),
                  ("allow", "movement", "movement:固定"),
                  ("qualifier", "intensity", "intensity:high")])
    return hg.Hypergraph(nodes, [edge]), edge


QUERY = "景别=MS；运镜=固定"


# --------------------------------------------------------------------------- 正面


def test_the_trace_names_both_lazy_qualifiers():
    """**S1a 的谓词**：trace 里必须出现这两个键名（值可 null）。"""
    graph, _edge_ = _scene()
    _edges, _text, trace = graph.retrieve(QUERY, top_k=1, token_limit=10 ** 6)
    table = trace.to_dict()["qualifiers"]
    for key in LAZY_KEYS:
        assert key in table, f"trace 里没有 qualifier 键 `{key}`：{sorted(table)}"
    #: S1a 阶段**值还没有生产者**（上游抽取层在 S2）——所以是 null 而不是缺键。
    assert table["seq_phase"] is None and table["carry_shots"] is None


def test_the_table_carries_every_name_of_the_closed_set():
    table = hg.qualifier_table()
    assert set(table) == set(hg.QUALIFIER_KINDS)
    assert all(value is None for value in table.values())


def test_an_injected_edge_reports_the_qualifier_it_actually_carries():
    """键是闭集生产的，值必须由**真的注入了什么**生产——两者缺一不可。"""
    graph, _edge_ = _scene()
    _edges, _text, trace = graph.retrieve(QUERY, top_k=1, token_limit=10 ** 6)
    table = trace.to_dict()["qualifiers"]
    assert table["intensity"] == ["high"], "注入的边带了 intensity，值必须摊出来"
    assert table["axis_side"] is None, "没出现的分项必须是 null，不能凭空给值"


def test_a_seed_miss_still_reports_the_whole_table():
    """查不到种子时提前 return，也要带上完整的键表（否则"键必须出现"就漏了一路）。"""
    graph, _edge_ = _scene()
    _edges, _text, trace = graph.retrieve("景别=CU", top_k=1, token_limit=10 ** 6)
    assert trace.seed_miss is True
    table = trace.to_dict()["qualifiers"]
    for key in LAZY_KEYS:
        assert key in table


# --------------------------------------------------------------------------- 鉴别力


def test_dropping_the_keys_from_the_closed_set_drops_them_from_the_trace(
        monkeypatch):
    """撤掉闭集里的键 ⇒ trace 里必须跟着消失。

    这条是**鉴别力**证明：没有它，"trace 里有两个键"可能只是 `qualifier_table()`
    自己写了两个字面量，与闭集无关（那就是又一条恒真式）。
    """
    graph, _edge_ = _scene()
    monkeypatch.setattr(
        hg, "QUALIFIER_KINDS",
        tuple(kind for kind in hg.QUALIFIER_KINDS if kind not in LAZY_KEYS))
    _edges, _text, trace = graph.retrieve(QUERY, top_k=1, token_limit=10 ** 6)
    table = trace.to_dict()["qualifiers"]
    for key in LAZY_KEYS:
        assert key not in table, "闭集里没有的键，trace 里也不许出现"


# --------------------------------------------------------------------------- 不变性


def test_the_old_contract_string_still_parses_verbatim():
    """正面：加键不许动**解析**。旧契约串逐字解出来的两半必须与从前一致。"""
    forward, forbid = hg.parse_query_full(OLD_CONTRACT)
    assert forward == {"shot_size": ["MCU"], "movement": ["固定"],
                       "scene_type": ["dialogue"]}
    assert forbid == {}
    assert hg.parse_query_full("禁运镜=固定") == ({}, {"movement": ["固定"]})


def test_a_new_qualifier_is_not_accidentally_a_query_key():
    """两个新键是**只读标签**，不是查询入口——顺手钉住它们没被塞进查询键。"""
    for key in LAZY_KEYS:
        assert key not in hg.QUERY_KEYS.values()
        assert key not in hg.FORBID_QUERY_KEYS.values()


def test_the_lazy_value_domains_are_explicitly_deferred():
    """门⑨ 要求每个 qualifier 都在 `VALUE_DOMAINS` 里——**显式 None 也算**。

    S1a 只加键；**取值域**归 S2 的上游抽取层冻结（计划：S2 输出"冻结词表"）。
    所以这里断言的是"延后是**写下来的**"，不是"不设枚举无所谓"：S2 落地时
    这条会红，逼着人把词表填进来，而不是让它悄悄留在 None 上。
    """
    for key in LAZY_KEYS:
        assert key in hg.VALUE_DOMAINS, f"{key} 没进门⑨ 的覆盖面"
        assert hg.VALUE_DOMAINS[key] is None, (
            f"{key} 的取值域应当留到 S2 冻结；现在改了就要同时更新这条用例与计划")


# --------------------------------------------------------------------------- 代际


def test_the_schema_generation_key_moved_with_the_two_keys():
    """代际钥匙：S0 那代是 `hg/v2+02fb5b9fe343`，加了两个键必须换成新的。

    闭集再改时**同步更新这个字面量**（这是有意的：换代词条要有人签字）。
    本次签字：`e70870ea3034`（S1a）→ **`1a90c089bb8f`**（P14-106）——**闭集一个字
    没动**，动的是**指纹的覆盖面**：`VALUE_DOMAINS`／`REQUIRED_MEMBERS`／
    `OPTIONAL_MEMBERS` 这三组"决定收不收"的闭集以前不在载荷里，于是给
    `seq_phase` 填取值域时会静默命中旧批次（与 S0 修的洞同形，深一层）。
    证据与守门见 `tests/test_hypergraph_determinism.py` 的"覆盖"一节。
    """
    assert hg.schema_version_with_fingerprint() == "hg/v2+1a90c089bb8f"
