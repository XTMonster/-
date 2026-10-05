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
from dataclasses import dataclass
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
#: 计划 P5 要的**五件产物**里，影子构建以前只落了三件（边／节点／词表）。
#: 这两件是补上的：manifest（六元指纹 ＋ 计数 ＋ 抽取通道身份）与 rejects（拒收账）。
MANIFEST_NAME = "hypergraph.manifest.json"
REJECTS_NAME = "hypergraph.rejects.jsonl"

#: 抽取通道的**实际**身份：v4 的构建期 LLM 是 `extract_segmented.DeepSeekClient`
#: （`model="deepseek-chat"`、`temperature=0.0`、`max_tokens=4096`）。
#: 解码条件照实写——**不抄**现役那份 `temperature=0;seed=0;ctx=8192`：
#: 云端 DeepSeek 没有 `seed`／`ctx` 这两个旋钮，把没发生的事写进指纹就是伪造留痕。
EXTRACTOR_MODEL = "deepseek-chat"
EXTRACTOR_FAMILY = "deepseek"
EXTRACTOR_DECODE = "temperature=0;max_tokens=4096"


@dataclass(frozen=True)
class _Extractor:
    """`fingerprint_components` 只要 `model_id` 与 `model_version` 两个属性。"""

    model_id: str = EXTRACTOR_MODEL
    model_version: str = EXTRACTOR_MODEL


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


def shadow_manifest(*, cards: Dict[str, Dict], edges: Sequence[Dict],
                    rejects: Sequence[Dict], drafts: Sequence[Dict],
                    vocab: Optional[Dict[str, List[str]]] = None,
                    corpus_dir: Optional[pathlib.Path] = None,
                    prompt_version: str = ex.PROMPT_VERSION,
                    chunker_version: str = ex.CHUNKER_VERSION,
                    decode: str = EXTRACTOR_DECODE,
                    model_id: str = EXTRACTOR_MODEL) -> Dict:
    """v4 影子的 **manifest**（计划 P5 的第五件产物）。**纯函数**，可离线测。

    为什么必须有它（2026-10-05 实测的缺口）：影子构建以前只落三件（边／节点／词表），
    而计划 P5 的 DoD 写着"`knowledge_v4/` **五件产物**生成"、P5③ 还点名
    "manifest 记 `PROMPT_VERSION=="extract/v19-seg"`＋corpus digest"。
    缺 manifest 的后果不是文档问题：`quality.q0_build_gate`（构建门）读它拿
    `raw_edges/valid_unique/duplicates/rejects` 四个计数，`sidecar_server.load_provenance`
    读它的 `fingerprint`／`extractor.model_id`／`schema_version`，门⑧ 读它的
    `extractor.family`（换族判据），插件的 `hypergraph.manifest_fingerprint` 也读它——
    **没有它，P10 的切换根本没法做**。

    指纹的生产者**不重复实现**：分量走 `build_hypergraph.fingerprint_components`
    （八元，`CACHE_KEY_FIELDS` 是它的机械防线），封盖走 `fingerprint_of`——
    与现役产物同一套代码，只是把语料／提示词／解码条件换成本代的**实际值**。
    """
    components = bh.fingerprint_components(
        list(cards.values()), _Extractor(model_id=model_id, model_version=model_id),
        prompt_version=str(prompt_version), chunker_version=str(chunker_version),
        decode=str(decode),
        vocabulary_fingerprint=(vocab_mod.vocab_fingerprint(vocab)
                                if vocab else ""))
    sealed = bh.fingerprint_of(components)
    #: 语料**自己的**摘要（`work/corpus_v4/MANIFEST.json` 的 `corpus_digest`）与
    #: 指纹里的 `corpus_sha256`（卡片级、`build_hypergraph.corpus_digest` 现算）**不是一回事**：
    #: 前者认的是"抓下来的那份语料"，后者认的是"喂进抽取的那些片段"。两个都记，别互相冒充。
    corpus_id = ""
    if corpus_dir is not None:
        path = pathlib.Path(corpus_dir) / "MANIFEST.json"
        if path.is_file():
            try:
                corpus_id = str(json.loads(path.read_text(encoding="utf-8"))
                                .get("corpus_digest") or "")
            except (OSError, ValueError):
                corpus_id = ""
    return {
        "generated_by": "tools/kb_fetch/build_shadow.py::shadow_manifest",
        "fingerprint": sealed,
        "cache_key": components,
        "extractor": {"model_id": str(model_id), "family": EXTRACTOR_FAMILY,
                      "model_version": str(model_id)},
        "prompt_version": str(prompt_version),
        "decode": str(decode),
        "chunker_version": str(chunker_version),
        "schema_version": str(hg.schema_version_with_fingerprint()),
        "validation_rules_version": str(bh.VALIDATION_RULES_VERSION),
        "corpus_digest": corpus_id,
        "corpus_dir": str(corpus_dir) if corpus_dir is not None else "",
        "cards": len(cards),
        #: 计数口径与 `quality.q0_build_gate` 对齐：`raw_edges` ＝ 进过 `to_edge` 的**草稿**数，
        #: `valid_unique` ＝ 落盘边数，`rejects` ＝ 被拒草稿数。
        "raw_edges": len(drafts),
        "valid_unique": len(edges),
        #: 影子管线里**没有去重阶段**：`closes` 是逐条对上的（见 `build_report.json`）。
        #: 写 0 是"这条路没做去重"，不是"去重后一条都没丢"——`unit` 一并说明。
        "duplicates": 0,
        "rejects": len(rejects),
        "total_chunks": len(drafts),
        "processed_chunks": len(edges) + len(rejects),
        "unit": "draft（v4 影子的构建单位是「分段 → 草稿」，不是现役的卡）",
        "closes": (len(edges) + len(rejects)) == len(drafts),
    }


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
        #: 用 `common.read_jsonl`（只按 `\n` 切）——`splitlines()` 会按 Unicode 行边界
        #: 切开 JSON 字符串（`\u2028` 一类），把一份好文件读成"坏行"。
        drafts = common.read_jsonl(pathlib.Path(drafts_path))

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
    #: **五件里的另外两件**（2026-10-05 补）：manifest 与拒收账。
    #: 落盘顺序无所谓，但 `rejects.jsonl` 的行数必须与 manifest 的 `rejects` 相等——
    #: `quality.q0_build_gate` 拿这两处对拍，对不上就判 FAIL（账不对）。
    manifest = shadow_manifest(cards=cards, edges=edges, rejects=rejects, drafts=drafts,
                               vocab=(vocab if with_vocab else None), corpus_dir=corpus_dir)
    common.dump_json(out_dir / MANIFEST_NAME, manifest)
    common.write_jsonl(out_dir / REJECTS_NAME, rejects)
    report["manifest_fingerprint"] = manifest["fingerprint"]
    report["corpus_digest"] = manifest["corpus_digest"]
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
    parser.add_argument("--out", required=True,
                        help="影子构建目录（由调用方点名；见 §3.3 的 P10 门）")
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
