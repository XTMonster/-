"""P5：L1/L2 的**影子构建**——把 P4 的草稿喂进现役的 `to_edge`。

一行都不改 `tools/kb_fetch/build_hypergraph.py`：那个 134 KB 的模块是**判据执行
环境**（门①–⑩、九条校验、归并窗口都在它与 `block_director/knowledge/hypergraph.py`
里），已被 `tests/plan_v4_instruments.sha256.json` 冻结。重建要换的是**语料与抽取
实现**，不是那些门——所以本模块只做"草稿 → 现役 `to_edge` → 落影子目录"。

v4 里"卡片"＝ **知识片段**（P4 的 `Segment`）。草稿带 `source.span`，按 span 反查
它所在的片段，把片段当卡片（`content` ＝ 片段正文、`source_span` ＝ 该段的偏移）。
这不是换概念，而是让 `to_edge` 的**成员级依据**检查真的有东西可查：
依据必须逐字出自那一段，否则记 `fabricated`。

**它是口径差的正主**：P4 的 `validate_draft` 只查 type/role/kind，自由文本取值
（实测样本里的 `pacing:followed the singer`）过得了它；到了这里，取值词表由
`to_edge` → `hg.HyperEdge` 那套现役判据把关，拒收会带具名原因。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

try:
    from . import common  # type: ignore
    from . import extract_segmented as ex  # type: ignore
    from . import build_hypergraph as bh  # type: ignore
    from . import vocabulary as vocab_mod  # type: ignore
except ImportError:  # pragma: no cover - 直跑
    from tools.kb_fetch import common  # type: ignore
    from tools.kb_fetch import extract_segmented as ex  # type: ignore
    from tools.kb_fetch import build_hypergraph as bh  # type: ignore
    from tools.kb_fetch import vocabulary as vocab_mod  # type: ignore

from block_director.knowledge import card_factory  # noqa: E402
from block_director.knowledge import hypergraph as hg  # noqa: E402

EDGES_NAME = "hypergraph.edges.jsonl"
REPORT_NAME = "build_report.json"


def _card_id(source_ref: Dict, span: Tuple[int, int]) -> str:
    digest = hashlib.sha256(str(source_ref.get("sha256") or source_ref.get("url") or "")
                            .encode("utf-8")).hexdigest()[:12]
    return "seg:%s:%d-%d" % (digest, span[0], span[1])


def segment_cards(corpus_dir: pathlib.Path,
                  *, max_chars: int = ex.DEFAULT_MAX_CHARS) -> Dict[str, Dict]:
    """把影子语料的每一段变成一个"卡片"，键＝`seg:<digest>:<start>-<end>`。

    键里带 span，所以 `draft_to_raw` 能按草稿的 `source.span` **精确**反查——
    查不到就是 `no_segment_for_span`，不许退化成"就近找个段贴上"。
    """
    cards: Dict[str, Dict] = {}
    for record in ex.load_records(pathlib.Path(corpus_dir)):
        source_ref = dict(record.get("source_ref") or {})
        for segment in ex.segment_text(str(record.get("text") or ""),
                                       source_ref=source_ref, max_chars=max_chars):
            card_id = _card_id(source_ref, segment.span)
            cards[card_id] = {
                "id": card_id,
                "content": segment.text,
                "source_ref": source_ref,
                "domain": record.get("domain"),
                #: `to_edge` 要它；缺了会判 `unlocatable_source_span`。
                "source_span": {"start": segment.span[0], "end": segment.span[1]},
            }
    return cards


def draft_to_raw(draft: Dict, *, cards: Dict[str, Dict]
                 ) -> Tuple[Optional[Dict], str]:
    """草稿 → `to_edge` 认的原始边形状。查不到片段就**具名拒收**。"""
    source = draft.get("source") or {}
    span = source.get("span")
    if not isinstance(span, (list, tuple)) or len(span) != 2:
        return None, "no_span:%r" % (span,)
    key_span = (int(span[0]), int(span[1]))
    card_id = _card_id(source, key_span)
    if card_id not in cards:
        return None, "no_segment_for_span:%d-%d" % key_span
    members = []
    for item in draft.get("members") or []:
        if not isinstance(item, (list, tuple)):
            return None, "bad_member:%r" % (item,)
        members.append(tuple(item))
    raw = {"type": draft.get("type"), "source_card": card_id, "members": members,
           "confidence": draft.get("confidence"),
           "source_kind": draft.get("source_kind") or "theory"}
    for key, value in (draft.get("qualifiers") or {}).items():
        raw.setdefault(key, value)
    return raw, ""


def hg_to_edge(raw: Dict, cards: Dict[str, Dict], node_index=None):
    """薄壳：直接调现役 `to_edge`（闭集＋词表的**单一真源**），不改它。

    `node_index` 给了才做**取值词表**解析：词表外的成员被丢掉，必填被丢 ⇒
    整条边判 `missing_required` 并在原因里带 `dropped=`。不给就只查闭集与必填结构
    （`tests/test_build_shadow.py::test_without_a_node_index_the_value_vocabulary_is_NOT_checked`
    把这个差别钉住）。
    """
    return bh.to_edge(raw, cards, node_index)


def card_objects(cards: Dict[str, Dict]) -> List:
    """片段卡 → 现役 `Card` 对象（`vocabulary.build_nodes` 要**属性**访问）。

    用仓库自己的 `card_factory.make_card`，不另造一种卡片形状。
    """
    out = []
    for card_id, card in cards.items():
        text = str(card.get("content") or "")
        title = next((line.strip() for line in text.splitlines() if line.strip()), "")[:60]
        out.append(card_factory.make_card(
            str(card_id), str(card.get("domain") or "unspecified"),
            title or str(card_id), text, []))
    return out


def build_vocab(cards: Dict[str, Dict]) -> Tuple[List[Dict], Dict[str, List[str]]]:
    """在**新语料**上建 v4 词表。**只调纯函数，不调 `vocabulary.run()`。**

    注意 `lens` 一类的开放值是从**卡片正文**里汇出来的（`vocabulary._LENS_RE`），
    所以这里必须把片段正文喂进去——只跑受控表会少掉这些取值（实测：只跑受控表
    176 个节点、带正文 180 个）。

    为什么不用 `vocabulary.run()`：它**有副作用**——会把结果写进
    `knowledge/hypergraph.vocab.json`、`knowledge/hypergraph.nodes.jsonl` 与
    `fixtures/knowledge_holdout.vocab.json` 三处**现役**产物。2026-10-05 实测踩过一次：
    影子构建把现役词表覆盖了，全量 pytest 当场三条红。重建期间现役知识产物必须
    逐字节不动（计划 §3.1 的"保留 3 项"），所以这里只调 `build_nodes()` ＋
    `vocab_payload()` 两个纯函数，写盘只写影子目录。
    （守门：`tests/test_build_shadow.py::test_building_the_shadow_vocab_does_not_touch_the_shipped_artifacts`。）
    """
    nodes = vocab_mod.build_nodes(card_objects(cards))
    return nodes, vocab_mod.vocab_payload(nodes)


def node_index(nodes: Sequence[Dict]):
    """现役 `NodeIndex`：把模型写的成员解析到真实节点上。"""
    table = {str(node["node_id"]): hg.Node.from_dict(dict(node)) for node in nodes}
    return bh.NodeIndex(table)


def build_shadow(drafts_path: pathlib.Path, *, corpus_dir: pathlib.Path,
                 out_dir: pathlib.Path,
                 max_chars: int = ex.DEFAULT_MAX_CHARS,
                 with_vocab: bool = True) -> Dict:
    """跑一次影子构建：读草稿 → 建片段卡 → 逐条过 `to_edge` → 落影子目录。"""
    cards = segment_cards(corpus_dir, max_chars=max_chars)
    nodes: List[Dict] = []
    index = None
    if with_vocab:
        #: 在**新语料**上建 v4 词表，并把 `NodeIndex` 交给 `to_edge`——取值词表关
        #: 到这一步才是活的（不接它的时候那条关根本不跑，见测试里钉住的那条）。
        nodes, vocab = build_vocab(cards)
        index = node_index(nodes)
    else:
        vocab = {}
    drafts: List[Dict] = []
    if pathlib.Path(drafts_path).is_file():
        for line in pathlib.Path(drafts_path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                drafts.append(json.loads(line))

    edges: List[Dict] = []
    rejects: List[Dict] = []
    for draft in drafts:
        raw, reason = draft_to_raw(draft, cards=cards)
        if raw is None:
            rejects.append({"reason": reason, "draft": draft})
            continue
        edge, why = hg_to_edge(raw, cards, index)
        if edge is None:
            rejects.append({"reason": why, "draft": draft, "source_card": raw["source_card"]})
            continue
        edges.append(edge.to_dict() if hasattr(edge, "to_dict") else edge.__dict__)

    report = {
        "generated_by": "tools/kb_fetch/build_shadow.py",
        "drafts_path": str(drafts_path),
        "corpus_dir": str(corpus_dir),
        "cards": len(cards),
        "vocab_nodes": len(nodes),
        "drafts_seen": len(drafts),
        "kept": len(edges),
        "rejected": len(rejects),
        #: 账目必须闭合。
        "closes": (len(edges) + len(rejects)) == len(drafts),
        "reject_reasons": _reason_histogram(rejects),
        "rejects": rejects,
    }
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    common.write_jsonl(out_dir / EDGES_NAME, edges)
    if with_vocab:
        #: 影子词表也落盘：它是"换了语料就整体换代"的钥匙之一。
        common.write_jsonl(out_dir / "hypergraph.nodes.jsonl", nodes)
        common.dump_json(out_dir / "hypergraph.vocab.json", {
            "nodes": nodes, "vocab": vocab,
            "_fingerprint": vocab_mod.vocab_fingerprint(vocab),
            "_generated_by": "tools/kb_fetch/build_shadow.py",
            "_corpus_dir": str(corpus_dir),
        })
    common.dump_json(out_dir / REPORT_NAME, report)
    return report


def _reason_histogram(rejects: Sequence[Dict]) -> Dict[str, int]:
    """按**原因前缀**归类（`bad_type:X` → `bad_type`），供拒绝率读数用。"""
    histogram: Dict[str, int] = {}
    for item in rejects:
        head = str(item.get("reason") or "unknown").split(":", 1)[0]
        histogram[head] = histogram.get(head, 0) + 1
    return dict(sorted(histogram.items()))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.build_shadow")
    parser.add_argument("--drafts", required=True, help="P4 的 extract_segmented.jsonl")
    parser.add_argument("--corpus", default=str(common.WORK / "corpus_v4"))
    parser.add_argument("--out", required=True, help="影子构建目录，例如 work/knowledge_v4")
    parser.add_argument("--max-chars", type=int, default=ex.DEFAULT_MAX_CHARS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = build_shadow(pathlib.Path(args.drafts), corpus_dir=pathlib.Path(args.corpus),
                          out_dir=pathlib.Path(args.out), max_chars=args.max_chars)
    print(json.dumps({key: report[key] for key in
                      ("cards", "drafts_seen", "kept", "rejected", "closes",
                       "reject_reasons")}, ensure_ascii=False))
    return 0 if report["closes"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
