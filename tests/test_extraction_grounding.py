"""**逐槽位依据：记账，不弃边**——三代"硬弃边"实测全败之后的落地口径。

背景（2026-10-02，`work/zz_v1{4,5,6,7}_build.txt`）：v14 只回查**一条**边级 `quote`，
于是**模板边**泛滥——全库 2909 个「卡 × 原子边」只有 743 个不同成员集、**55.9%**
的链接属于"被 ≥10 张卡共用"的成员集（最多的一条被 167 张卡共用），独立复核面板
（DeepSeek＋GLM 两族）拿卡去判，**92% 判"这张卡不支持它"**。看起来修法是"要求每个
槽位各自给一句逐字依据，回查不到就弃边"。三代都这么做了，三代都塌库：

    v14 基线（只有边级 quote）            raw_edges 700
    v15（成员四元组 ＋ 必填槽位要有依据）  raw_edges 616
    v16（＋ 依据里要出现取值本身）         raw_edges  32   atom_rejects 10958
    v17（原子只写本卡讲到的成员）          raw_edges  25

根因不是模型不听话——它**照做**了（四元组带上了、句子逐字在卡里）。是 schema 的必填
槽位本来就有一部分是**推断**出来的：讲"留出前方空间"的卡被补成 `景别=LS／机位=平视`，
卡里根本没有那句话可引。v16 那 10958 条拒收里 **10228 条（93%）** 正是
`member_evidence_does_not_mention_value`。所以"逐槽位依据"只能当**记账**：
`extractor.member_grounding` 逐槽位标 `quoted` / `inferred` / `fabricated`，
让复核判据看得见"这条边有几个槽位是推断出来的"，而不是让抽取器自己把边丢掉。

这条口径与 v14 的门**逐条等价**（`VALIDATION_RULES_VERSION` 仍留在 `gate/v2`），
多出来的只有一本账。逐条实测见 `docs/knowledge/ACCEPTANCE_STATUS.md` §二十九。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import build_hypergraph as bh  # noqa: E402

CARD_TEXT = "检验构图是否平衡时，把画面倒过来看，可更清楚地看出线条与重量的分布关系。"


def _cards(text: str = CARD_TEXT) -> dict:
    return {"c1": {"id": "c1", "domain": "composition", "title": "倒置画面检验构图",
                   "content": text,
                   "source_span": {"chunk_id": "chunk#1", "start": 0, "end": len(text)}}}


def _raw(members) -> dict:
    return {"source_card": "c1", "type": "STAGING_PACK",
            "members": members, "source_kind": "theory", "hardness": "hard",
            "quote": "把画面倒过来看"}


def _node_index():
    """真节点表——`node_surfaces` 要有真实取值才谈得上"依据里必须提到它"。"""
    return bh.NodeIndex(bh.nodes_from_vocab())


def test_members_without_evidence_are_recorded_as_inferred_not_dropped():
    """没给依据的成员 ⇒ **照样入库**，但每个槽位都记成 `inferred`。

    这是被 v15/v16 的实测逼出来的一条：v14 的提示词根本不产四元组，如果"缺依据就
    弃边"，索引会从 700 条边塌到 25 条。"""
    raw = _raw([["qualifier", "composition_rule", "composition_rule:balance"],
                ["allow", "shot_size", "shot_size:MS"],
                ["qualifier", "camera_angle", "camera_angle:平视"]])
    edge, reason = bh.to_edge(raw, _cards(), _node_index())
    assert edge is not None, reason
    grounding = (edge.extractor or {}).get("member_grounding")
    assert set(grounding) == {"qualifier/composition_rule", "allow/shot_size",
                              "qualifier/camera_angle"}
    assert set(grounding.values()) == {"inferred"}
    assert (edge.extractor or {}).get("member_quotes") == {}


def test_evidence_that_is_not_in_the_named_card_is_recorded_as_fabricated():
    """引一句卡里**没有**的话 ⇒ 不弃边，但那个槽位标成 `fabricated`（不许冒充依据）。"""
    raw = _raw([["qualifier", "composition_rule", "composition_rule:balance", "三分法要留出前方空间"],
                ["allow", "shot_size", "shot_size:MS", "分布关系"],
                ["qualifier", "camera_angle", "camera_angle:平视", "线条与重量的分布"]])
    edge, reason = bh.to_edge(raw, _cards(), _node_index())
    assert edge is not None, reason
    grounding = (edge.extractor or {}).get("member_grounding") or {}
    #: 第一项卡里没有 ⇒ fabricated；第二、三项逐字在卡里 ⇒ 至少不是 fabricated。
    assert grounding["qualifier/composition_rule"] == "fabricated"
    assert "fabricated" not in (grounding["allow/shot_size"],
                                 grounding["qualifier/camera_angle"])


def test_verbatim_evidence_that_never_names_the_value_is_recorded_as_inferred():
    """依据**逐字在卡里**但**没提到这个取值** ⇒ 不弃边，标 `inferred`。

    这一条正是 v16 塌库的那 93%：必填槽位是推断出来的，卡里没有那句话可引。"""
    raw = _raw([["qualifier", "composition_rule", "composition_rule:balance", "构图是否平衡"],
                ["allow", "shot_size", "shot_size:MS", "分布关系"],
                ["qualifier", "camera_angle", "camera_angle:平视", "画面倒过来看"]])
    edge, reason = bh.to_edge(raw, _cards(), _node_index())
    assert edge is not None, reason
    grounding = (edge.extractor or {}).get("member_grounding") or {}
    assert grounding["qualifier/composition_rule"] == "quoted", "依据里有'平衡'"
    assert grounding["qualifier/camera_angle"] == "inferred", "依据里没有'平视'"


def test_naming_the_value_is_what_separates_quoted_from_inferred():
    """判据是"依据里有没有提到这个取值"：提到 ⇒ `quoted`，没提到 ⇒ `inferred`。

    这条同时钉住两向：`camera_angle:平视` 的 surface 是"平视／眼平／eye_level"，
    依据写"画面倒过来看"就不算提到了它。"""
    raw = _raw([["qualifier", "composition_rule", "composition_rule:balance", "构图是否平衡"],
                ["allow", "shot_size", "shot_size:MS", "分布关系"],
                ["qualifier", "camera_angle", "camera_angle:平视", "画面倒过来看"]])
    edge, reason = bh.to_edge(raw, _cards(), _node_index())
    assert edge is not None, reason
    grounding = (edge.extractor or {}).get("member_grounding") or {}
    assert grounding["qualifier/camera_angle"] == "inferred"
    #: 换成把"平视"写进去 ⇒ 同一个槽位变成 `quoted`。
    raw2 = _raw([["qualifier", "composition_rule", "composition_rule:balance", "构图是否平衡"],
                 ["allow", "shot_size", "shot_size:MS", "分布关系"],
                 ["qualifier", "camera_angle", "camera_angle:平视", "平视看构图"]])
    edge2, reason2 = bh.to_edge(raw2, _cards(text=CARD_TEXT + "平视看构图。"), _node_index())
    assert edge2 is not None, reason2
    assert (edge2.extractor or {}).get("member_grounding")["qualifier/camera_angle"] == "quoted"


def test_evidence_that_names_every_value_is_accepted_and_recorded():
    """每个槽位的依据都提到了那个取值 ⇒ 收下，并把依据存进 `extractor.member_quotes`。"""
    raw = _raw([["qualifier", "composition_rule", "composition_rule:balance", "构图是否平衡"],
                ["allow", "shot_size", "shot_size:MS", "分布关系"],
                ["qualifier", "camera_angle", "camera_angle:平视", "平视看平衡"]])
    edge, reason = bh.to_edge(raw, _cards(text=CARD_TEXT + "中景看平衡，平视看平衡。"),
                              _node_index())
    assert edge is not None, reason
    quotes = (edge.extractor or {}).get("member_quotes") or {}
    assert set(quotes) == {"qualifier/composition_rule", "qualifier/camera_angle"}
    #: 存的是**原文**（带标点），不是去空白后的比对串——人要能读它。
    assert quotes["qualifier/composition_rule"] == "构图是否平衡"


def test_the_rejected_generations_are_recorded_and_the_prompt_is_back_on_v14():
    """被实测否决的三代必须**留档**，且提示词与版本号回到 v14 口径。

    这一条防的是"下一个人再走一遍同一条死路"：v15/v16/v17 的实测数字写在模块里
    （`PROMPT_VERSION` 上方那张表），提示词里**不许**再出现"每个成员都要自带出处"
    这种逼模型填槽位的硬规则。
    """
    prompt = bh.SYSTEM_PROMPT
    assert "每个成员都要自带出处" not in prompt, "被否决的硬规则又回到提示词里了"
    assert "必须写全" in prompt, "v14 的必填成员口径丢了"
    assert bh.PROMPT_VERSION == "extract/v14"
    assert bh.VALIDATION_RULES_VERSION == "gate/v2", (
        "记账不弃边 ⇒ 门与 v2 逐条等价；换版本号会让 manifest 自报一个它没用过的门")
    module = (ROOT / "tools" / "kb_fetch" / "build_hypergraph.py").read_text(encoding="utf-8")
    for marker in ("v15", "v16", "v17", "member_evidence_does_not_mention_value",
                   "10958", "10228", "616"):
        assert marker in module, f"被否决的实测没留档：{marker}"


def test_the_template_edge_metric_is_kept_within_the_recorded_baseline():
    """模板边的**指标**必须留在已记录的基线上——它是 §29 那条未决问题的度量面。

    背景：一条成员集被几十张互不相干的卡共用，就说明那些槽位是模型填的默认值
    （v14 索引里 11 组 ≥40，最大 167）。三代"硬弃边"都栽在这件事上，所以这一轮
    **没有**把 40 当门限（那会要求一次还没有的抽取口径），而是把实测值钉成基线：
    任何**回退**（指标变差）当场红，改进则要求同步把基线调低——数字一直是明账。

    真正的修法写在 `ACCEPTANCE_STATUS.md` §二十九：把"每个成员由哪张卡贡献"做成
    provenance（`member_grounding` 已经是它的第一半），再让复核判据与 schema 对齐。
    """
    import json

    edges_path = ROOT / "knowledge" / "hypergraph.edges.jsonl"
    if not edges_path.is_file():
        import pytest

        pytest.skip("索引未入库")
    from collections import Counter

    #: 实测基线（2026-10-02，v14 口径索引：700 条边 / 167 张卡共用）——只许降。
    RECORDED_WORST_SHARE = 170
    counts = Counter()
    for line in edges_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        edge = json.loads(line)
        counts[(edge["type"], tuple(sorted(m[2] for m in edge["members"])))] += len(
            edge.get("sources") or [])
    assert counts, "索引里一条边都没有——这条度量失去了对象"
    worst_set, worst_share = counts.most_common(1)[0]
    assert worst_share <= RECORDED_WORST_SHARE, (
        "最热成员集被 %d 张卡共用，超过已记录基线 %d——模板边在恶化：%s"
        % (worst_share, RECORDED_WORST_SHARE, worst_set))
    shared = sum(value for value in counts.values() if value >= 10) / sum(counts.values())
    assert shared <= 0.70, (
        "被 ≥10 张卡共用的成员集占了链接的 %.1f%%（基线 56.1%%）——模板边在恶化"
        % (100 * shared))
