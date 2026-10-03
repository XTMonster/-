"""管线第 7 步：入库（§2.3c 的 `import_cards.py`）。

产物：

* `knowledge/cards_generated/<domain>.jsonl` —— **运行时**投影（stdlib 可解析，
  由 `block_director/knowledge/corpus.py` 合并进 `CARDS`）；
* `knowledge/cards_generated/<domain>.yaml` —— 同一次运行、同一份内存列表写出的
  人类/审计副本（计划书字面要求的 `*.yaml`）；两份由测试断言逐字段相等；
* `work/import_report.json` ＋ `knowledge/cards_generated/import_report.json`
  —— K1–K5 的计数与判定（前者是管线中间产物，后者随仓库入库接受审计）。

计数口径（§2.3c）：`cards_candidates`（过完去重、进入许可与出处门的候选项）、
`cards_kept`、`cards_deduped`、`cards_rejected`。K4 = kept / (candidates + deduped)。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Dict, List, Optional, Sequence, Tuple

import yaml

try:
    from . import common
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common  # type: ignore

ANNOTATED = common.WORK / "annotated.jsonl"
CHUNKS = common.WORK / "chunks.jsonl"
REPORT = common.WORK / "import_report.json"
COMMITTED_REPORT = common.CARDS_DIR / "import_report.json"

DOMAIN_PREFIX = {
    "cinematography": "cine",
    "axis_theory": "axis",
    "composition": "comp",
    "blocking": "block",
    "performance": "perf",
    "storyboard": "story",
    "editing": "edit",
    "anime": "anime",
    "production": "prod",
}

K3_MIN_PER_DOMAIN = 60
K3_MIN_SHARE = 0.05
K4_MIN_RATIO = 0.60


class LiteralStr(str):
    """让 `quote` 在 YAML 里以 `|` 块标量出现（正文与引用块分离，§2.3d）。"""


class _Dumper(yaml.SafeDumper):
    pass


def _represent_literal(dumper: yaml.SafeDumper, data: LiteralStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


_Dumper.add_representer(LiteralStr, _represent_literal)


def _candidates(annotated: Sequence[Dict]) -> List[Dict]:
    """把每个 chunk 的卡片摊平成候选条目（带出处与引用块）。"""
    chunk_index = {record["chunk_id"]: record for record in common.read_jsonl(CHUNKS)}
    out: List[Dict] = []
    for record in annotated:
        current = chunk_index.get(record["chunk_id"], {})
        for card in record["cards"]:
            start, end = common.locate_quote(card["quote"],
                                             current.get("text", ""))
            # K5 的主题配额按"来源主题"记账；三个"缺口域"（editing/storyboard/anime）
            # 的卡片本身就属于对应主题，即使来源没显式写 theme 也计入。
            theme = current.get("theme", "") or record.get("theme", "")
            topic = theme or (record["domain"]
                              if record["domain"] in common.TOPIC_QUOTAS else "")
            out.append({
                "domain": record["domain"],
                "topic": topic,
                "title": card["title"],
                "content": card["content"],
                "quote": card["quote"],
                "keywords": list(card.get("keywords", [])),
                "rules": list(card.get("rules", [])),
                "tags": list(card.get("tags", [])),
                "emotion": card.get("emotion", ""),
                "source_ref": record["source_ref"],
                "chunk_id": record["chunk_id"],
                "source_span": {"chunk_id": record["chunk_id"], "start": start, "end": end},
                "provenance_kind": _provenance_kind(record["source_ref"]),
            })
    return out


def _provenance_kind(source_ref: Dict) -> str:
    """§2.3 的"来源权威度"字段：来源介质（与 `source_kind` 不是一个东西）。"""
    if str(source_ref.get("url", "")).startswith("repo://"):
        return "权威文档"   # 自撰笔记：本项目的权威文档（0.9）
    return "网络语料"


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text)).lower()


def dedupe_cards(cards: Sequence[Dict], simhash_fn=common.simhash64) -> Tuple[List[Dict], List[Dict]]:
    kept: List[Dict] = []
    dropped: List[Dict] = []
    exact: Dict[str, str] = {}
    sims: List[Tuple[int, str]] = []
    for card in cards:
        key = _norm(card["content"])
        sim = simhash_fn(key)
        if key in exact:
            dropped.append({**card, "dup_of": exact[key], "dup_kind": "exact"})
            continue
        near = next((ident for ident, dist in ((i, common.hamming(sim, s)) for s, i in sims)
                     if dist <= common.SIMHASH_MAX_HAMMING), "")
        if near:
            dropped.append({**card, "dup_of": near, "dup_kind": "simhash"})
            continue
        exact[key] = card["title"]
        sims.append((sim, card["title"]))
        kept.append(card)
    return kept, dropped


def gate(card: Dict) -> Tuple[bool, str]:
    #: 出处＋许可走 `common.source_and_licence_ok`（唯一实现）；卡片级的那几条
    #: （quote 可回查、标题/正文非空、域在闭集里）才是这一步特有的判据。
    ok, reason = common.source_and_licence_ok(card.get("source_ref"))
    if not ok:
        return False, reason
    ok, reason = common.quote_check(str(card.get("quote", "")))
    if not ok:
        return False, reason
    if not str(card.get("content", "")).strip() or not str(card.get("title", "")).strip():
        return False, "empty_title_or_content"
    if card.get("domain") not in common.DOMAINS:
        return False, f"unknown_domain:{card.get('domain')}"
    return True, ""


def card_identity(card: Dict) -> str:
    """卡片的**稳定身份**：域 ＋ 出处段落 ＋ 正文 sha256。

    id 是序号（`gen_cine_0007`），序号会随语料长大而整体下移——那样一来
    任何引用旧 id 的产物（held-out 条目的 `from_card`、评测证据）就会**指向
    另一张卡**，而且是静默地指错。所以 id 不能由排序决定：先认身份，
    身份在旧账里就沿用旧 id，只有真正的新卡才发新号。
    """
    return "|".join([
        str(card.get("domain", "")),
        str(card.get("chunk_id", "")),
        common.sha256_text(str(card.get("content", ""))),
    ])


def existing_ids(cards_dir: pathlib.Path | None = None) -> Dict[str, str]:
    """上一次入库的 `身份 -> id`。读的就是随仓库入库的那份产物。"""
    directory = pathlib.Path(cards_dir or common.CARDS_DIR)
    out: Dict[str, str] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.jsonl")):
        for row in common.read_jsonl(path):
            ident, ident_id = card_identity(row), str(row.get("id", ""))
            if ident_id and ident not in out:
                out[ident] = ident_id
    return out


def _prefix_of(card_id: str) -> str:
    """`gen_cine_0007` -> `cine`。"""
    return card_id[len("gen_"):].rsplit("_", 1)[0]


def _finalise(cards: Sequence[Dict],
              previous: Optional[Dict[str, str]] = None) -> List[Dict]:
    previous = dict(existing_ids() if previous is None else previous)
    counters: Dict[str, int] = {}
    claimed: Dict[str, str] = {}
    for ident, ident_id in previous.items():
        if not ident_id.startswith("gen_"):
            continue
        claimed.setdefault(ident_id, ident)
        prefix = _prefix_of(ident_id)
        tail = ident_id.rsplit("_", 1)[1]
        if tail.isdigit():
            counters[prefix] = max(counters.get(prefix, 0), int(tail))
    assigned: set = set()
    out: List[Dict] = []
    for card in sorted(cards, key=lambda c: (c["domain"], c["content"])):
        prefix = DOMAIN_PREFIX[card["domain"]]
        ident = card_identity(card)
        reused = previous.get(ident, "")
        if reused and claimed.get(reused) == ident and reused not in assigned:
            card_id = reused
        else:
            while True:
                counters[prefix] = counters.get(prefix, 0) + 1
                card_id = f"gen_{prefix}_{counters[prefix]:04d}"
                if card_id not in claimed and card_id not in assigned:
                    break
            claimed[card_id] = ident
        assigned.add(card_id)
        out.append({
            "id": card_id,
            "domain": card["domain"],
            "title": card["title"],
            "content": card["content"],
            # 生成卡的检索面 = `title + content`（＋ emotion）。
            # 关键词只留前 3 个（去掉与标题重复的）。它们**不进检索面**——
            # 见 `knowledge/retriever.py::_searchable`：模型自写的关键词没有经过
            # 人工审阅，实测会把生成卡抬到人工专题卡之前（"三分法 构图" 下
            # gen_cine_0050 以 25.90 压过 comp_thirds；"越轴" 下 axis_cross 掉到第 10）。
            "keywords": ([k for k in dict.fromkeys(card.get("keywords", []))
                          if k not in card.get("title", "")][:3]
                         or [str(card["title"])[:12]]),
            "rules": list(card.get("rules", [])),
            "parameters": {},
            "examples": [],
            "related": [],
            "engine_support": "",
            "emotion": card.get("emotion", ""),
            "tags": [t for t in dict.fromkeys(card.get("tags", []))
                     if t not in card.get("title", "")][:3],
            "topic": card.get("topic", ""),
            "quote": card.get("quote", ""),
            "source_ref": dict(card.get("source_ref", {})),
            "chunk_id": card.get("chunk_id", ""),
            "source_span": dict(card.get("source_span", {})),
            "provenance_kind": card.get("provenance_kind", "生成卡片"),
        })
    return out


def _write_domain_files(entries: Sequence[Dict]) -> Dict[str, int]:
    by_domain: Dict[str, List[Dict]] = {d: [] for d in common.DOMAINS}
    for entry in entries:
        by_domain[entry["domain"]].append(entry)
    # 按 id 落盘：老卡的位置不动，新卡追加在尾部——既让 diff 可读，
    # 也让"语料长大"这件事在产物里是**追加**而不是整份重排。
    for items in by_domain.values():
        items.sort(key=lambda entry: entry["id"])

    common.CARDS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in common.CARDS_DIR.glob("*.jsonl"):
        if stale.stem not in by_domain:
            stale.unlink()
    written: Dict[str, int] = {}
    for domain, items in by_domain.items():
        jsonl_path = common.CARDS_DIR / f"{domain}.jsonl"
        common.write_jsonl(jsonl_path, items)
        yaml_payload = []
        for item in items:
            copy = dict(item)
            copy["quote"] = LiteralStr(item["quote"])
            yaml_payload.append(copy)
        text = yaml.dump(yaml_payload, Dumper=_Dumper, allow_unicode=True,
                         sort_keys=False, default_flow_style=False, width=1000)
        (common.CARDS_DIR / f"{domain}.yaml").write_text(
            f"# 生成卡片：{domain}（自动生成，请勿手改；见 docs/knowledge/LICENSES.md）\n{text}",
            encoding="utf-8", newline="\n")
        written[domain] = len(items)
    return written


def build_report(entries: Sequence[Dict], candidates: int, deduped: int,
                 rejected: int, docs: Dict[str, int],
                 size_gate: Optional[Dict] = None) -> Dict:
    kept = len(entries)
    per_domain: Dict[str, int] = {d: 0 for d in common.DOMAINS}
    for entry in entries:
        per_domain[entry["domain"]] = per_domain.get(entry["domain"], 0) + 1
    handwritten = _handwritten_counts()
    merged = {domain: per_domain.get(domain, 0) + handwritten.get(domain, 0)
              for domain in common.DOMAINS}
    topics: Dict[str, int] = {t: 0 for t in common.TOPIC_QUOTAS}
    for entry in entries:
        topic = str(entry.get("topic", ""))
        if topic in topics:
            topics[topic] += 1

    k1 = 1.0 if candidates and not any(
        common.source_ref_problems(e["source_ref"]) for e in entries) else 0.0
    # K1/K2 的分母是 cards_candidates（含被拒项），所以必须在门里逐条统计。
    return {
        # §2.3c 的入库体积门（单文件 ≤512 KB、总量 ≤20 MB）；超限即构建失败。
        "size_gate": size_gate if size_gate is not None
        else common.check_size_gate(common.CARDS_DIR),
        "counts": {
            "cards_candidates": candidates,
            "cards_kept": kept,
            "cards_deduped": deduped,
            "cards_rejected": rejected,
            **docs,
        },
        "per_domain": per_domain,
        "per_domain_merged": merged,
        "handwritten_per_domain": dict(handwritten),
        "topics": topics,
        "K1_source_ref_complete": k1,
        "K4_dedupe_ratio": (kept / (candidates + deduped)) if (candidates + deduped) else 0.0,
    }


def evaluate(report: Dict) -> Tuple[bool, List[str]]:
    problems: List[str] = []
    counts = report["counts"]
    size_gate = report.get("size_gate") or {}
    if not size_gate.get("passed", True):
        for name, size in sorted((size_gate.get("oversize") or {}).items()):
            problems.append(f"体积门: {name} 单文件 {size} B > "
                            f"{common.MAX_CARD_FILE_BYTES} B（改用摘要＋出处）")
        total = int(size_gate.get("total_bytes") or 0)
        if total > common.MAX_CARDS_TOTAL_BYTES:
            problems.append(f"体积门: 生成卡总量 {total} B > "
                            f"{common.MAX_CARDS_TOTAL_BYTES} B")
    if report["K1_source_ref_complete"] < 1.0:
        problems.append("K1: source_ref 六字段未全非空")
    if counts.get("K2_license_ratio", 1.0) < 1.0:
        problems.append("K2: 许可合规率 < 100%")
    if report["K4_dedupe_ratio"] < K4_MIN_RATIO:
        problems.append(f"K4: 去重有效率 {report['K4_dedupe_ratio']:.3f} < {K4_MIN_RATIO}")
    # K3 的分母是**整份语料**（手写卡 ＋ 生成卡）——§2.3c 的"现在是 5 域 132 张"
    # 明确把手写卡算进语料，九域覆盖说的是语料，不是单次导入的产物。
    merged = report.get("per_domain_merged") or report["per_domain"]
    total = sum(merged.values())
    if total < 1:
        problems.append("K3: 没有卡片入库")
    else:
        for domain, count in merged.items():
            if count < K3_MIN_PER_DOMAIN:
                problems.append(f"K3: {domain} 只有 {count} 张（< {K3_MIN_PER_DOMAIN}）")
            if count / total < K3_MIN_SHARE:
                problems.append(f"K3: {domain} 占比 {count / total:.3f}（< {K3_MIN_SHARE}）")
    return (not problems), problems


def _handwritten_counts() -> Dict[str, int]:
    """手写卡的逐域计数（懒导入，避免与正在写盘的生成卡形成循环）。"""
    try:
        from block_director.knowledge.corpus import HANDWRITTEN_CARDS
    except Exception:  # pragma: no cover - 换环境时不该因此失败
        return {}
    counts: Dict[str, int] = {}
    for card in HANDWRITTEN_CARDS:
        counts[card.domain] = counts.get(card.domain, 0) + 1
    return counts


def run(annotated: Sequence[Dict], docs: Optional[Dict[str, int]] = None) -> Dict:
    raw = _candidates(annotated)
    deduped_cards, dropped = dedupe_cards(raw)

    candidates = len(deduped_cards)
    rejected = 0
    reject_detail: List[Dict] = []
    licensed: List[Dict] = []
    license_ok = 0
    source_ok = 0
    for card in deduped_cards:
        ok, reason = gate(card)
        if common.license_allowed(str(card["source_ref"].get("license", ""))):
            license_ok += 1
        if not common.source_ref_problems(card["source_ref"]):
            source_ok += 1
        if ok:
            licensed.append(card)
        else:
            rejected += 1
            reject_detail.append({"title": card["title"], "domain": card["domain"],
                                  "reason": reason})

    entries = _finalise(licensed)
    per_domain = _write_domain_files(entries)
    report = build_report(entries, candidates, len(dropped), rejected, docs or {},
                          size_gate=common.check_size_gate(common.CARDS_DIR))
    report["counts"]["K2_license_ratio"] = (license_ok / candidates) if candidates else 0.0
    report["K1_source_ref_complete"] = (source_ok / candidates) if candidates else 0.0
    report["per_domain"] = per_domain
    report["rejects"] = reject_detail[:20]
    report["dedupe_examples"] = [{"title": c["title"], "dup_of": c["dup_of"]} for c in dropped[:10]]
    passed, problems = evaluate(report)
    report["passed"] = passed
    report["problems"] = problems
    common.dump_json(REPORT, report)
    common.dump_json(COMMITTED_REPORT, report)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.import_cards")
    parser.add_argument("--docs-deduped", type=int, default=0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    annotated = common.read_jsonl(ANNOTATED)
    report = run(annotated, {"docs_deduped": args.docs_deduped})
    print(json.dumps({k: v for k, v in report.items() if k not in ("rejects",)},
                     ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
