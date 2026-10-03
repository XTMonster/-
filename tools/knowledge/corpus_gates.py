"""§2.3c 的 **K1–K4**：语料合规与覆盖——RK-13 的**前置**，此前只有构建期算过，验收链从没查过。

为什么单开这一支
================
文档把 K1–K4 写成 RK-13 的**前置**（§4.1 的 RK-13 行）：

* **K1 出处完整性 = 100%**：生成卡的 `source_ref` 六个字段
  （`url/title/author/license/retrieved_at/sha256`）一个都不能空；
* **K2 许可合规率 = 100%**：许可必须落在白名单里；
* **K3 覆盖**：九域**每域 ≥60 张**，且**任一域 ≥5%**；
* **K4 去重有效率 ≥60%**：`cards_kept / (cards_candidates + cards_deduped)`
  （§4.1b 的算术修正：`cards_rejected` 已含在 `cards_candidates` 内，不得重复计入）。

它们的**计算**在 `tools/kb_fetch/import_cards.py` 里，但那只在**重跑导入**时才发生，
而验收链读的是入库产物：卡被重新生成、报告没跟着更新、或者有人手改过语料，
链上**没有任何东西会红**。这就是本项目反复踩的同一个形状——"规则写了、机器没查"。

判据怎么做到"不读自报"
====================
* **K1 / K2 / K3 全部从入库语料重算**（`knowledge/cards_generated/*.jsonl`
  ＋ 手写策展卡），一个字都不读构建期报告；
* **K4 的两项**：① 分子分母本身是构建期账（被去掉的重复文档不在入库语料里，
  无法反推），但**必须与语料对得上**——账本说的 `cards_kept` 要等于入库卡数，
  分母要有下界（§4.1b：`cards_candidates ≥ 540`）；② **另有一条独立判据**：
  入库语料里**不许存在完全重复的卡**（同一 `source_ref.sha256` ＋ 同一
  `source_span` 的文本区间出现两次），否则"去重"这件事本身没发生。两条都过才算。

用法::

    python tools/knowledge/corpus_gates.py                 # 打印四门的账
    python tools/knowledge/corpus_gates.py --json out.json # 落盘

退出码：0 全过 / 1 有门失败 / 2 证据缺失（**不得当通过**，§4.1b 硬规则 1）。
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.corpus import DOMAINS, HANDWRITTEN_CARDS  # noqa: E402
from tools.kb_fetch import common  # noqa: E402

PASS, FAIL, NA = "pass", "fail", "not_measured"

#: §4.1b 的分母下界：`cards_candidates ≥ 540`（与 K3 的"每域 ≥60 × 9"自洽）。
MIN_CANDIDATES = 540
#: §2.3c：每域 ≥60 张。
MIN_PER_DOMAIN = 60
#: §2.3c：任一域占比 ≥5%。
MIN_DOMAIN_SHARE = 0.05
#: §2.3c：去重有效率 ≥60%。
MIN_DEDUPE_RATIO = 0.60

DEFAULT_CARDS_DIR = ROOT / "knowledge" / "cards_generated"
DEFAULT_REPORT = DEFAULT_CARDS_DIR / "import_report.json"


def load_generated(cards_dir: Any = DEFAULT_CARDS_DIR) -> List[Dict[str, Any]]:
    """入库的生成卡（`*.jsonl`）。坏行**抛错**，不静默跳过。"""
    directory = pathlib.Path(cards_dir)
    cards: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.jsonl")):
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number} 不是合法 JSON：{exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{number} 不是对象")
            cards.append(payload)
    return cards


def _status(ok: bool) -> str:
    return PASS if ok else FAIL


def k1_source_ref(cards: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """K1：`source_ref` 六字段全非空。**分母为 0 判失败**（§4.1b 硬规则 1）。"""
    detail = {"id": "K1_source_ref_complete", "line": 1.0, "candidates_floor": MIN_CANDIDATES}
    if not cards:
        return {**detail, "status": FAIL, "numerator": 0, "denominator": 0,
                "value": None,
                "note": "生成卡为 0：分母无意义，按 §4.1b 硬规则 1 判失败"}
    bad = []
    for card in cards:
        problems = common.source_ref_problems(card.get("source_ref") or {})
        if problems:
            bad.append({"id": str(card.get("id", "")),
                        "missing": problems[:3]})
    good = len(cards) - len(bad)
    return {**detail, "status": _status(not bad and len(cards) >= 1),
            "numerator": good, "denominator": len(cards),
            "value": round(good / len(cards), 4),
            "examples": bad[:5],
            "note": (f"{len(cards)} 张生成卡的 source_ref 六字段全部非空"
                     if not bad else
                     f"{len(bad)}/{len(cards)} 张卡缺出处字段（K1 要求 100%）")}


def k2_license(cards: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """K2：许可必须落在白名单里（`common.LICENSE_WHITELIST`）。"""
    detail = {"id": "K2_license_ratio", "line": 1.0, "candidates_floor": MIN_CANDIDATES}
    if not cards:
        return {**detail, "status": FAIL, "numerator": 0, "denominator": 0,
                "value": None,
                "note": "生成卡为 0：分母无意义，按 §4.1b 硬规则 1 判失败"}
    outside = [{"id": str(card.get("id", "")),
                "license": str((card.get("source_ref") or {}).get("license", ""))}
               for card in cards
               if not common.license_allowed(
                   str((card.get("source_ref") or {}).get("license", "")))]
    good = len(cards) - len(outside)
    return {**detail, "status": _status(not outside),
            "numerator": good, "denominator": len(cards),
            "value": round(good / len(cards), 4),
            "examples": outside[:5],
            "whitelist": sorted(common.LICENSE_WHITELIST),
            "note": (f"{len(cards)} 张卡的许可全部在白名单内"
                     if not outside else
                     f"{len(outside)} 张卡的许可不在白名单（K2 要求 100%）")}


def k3_domain_floor(cards: Sequence[Dict[str, Any]],
                    handwritten: Sequence[Any] = HANDWRITTEN_CARDS
                    ) -> Dict[str, Any]:
    """K3：九域**每域 ≥60 张**且**任一域 ≥5%**（手写策展卡计入语料，§2.3c）。

    分母是**整份语料**（生成 ＋ 手写）——§2.3c 的"5 域 132 张"就是把手写卡算进
    语料的口径；K3 说的是语料覆盖，不是"单次导入产出了多少"。
    """
    counts: Dict[str, int] = collections.Counter(
        str(card.get("domain", "")) for card in cards)
    for card in handwritten:
        counts[str(getattr(card, "domain", ""))] += 1
    total = sum(counts.values())
    detail = {"id": "K3_domain_floor", "line": 1.0, "total": total,
              "min_per_domain": MIN_PER_DOMAIN, "min_share": MIN_DOMAIN_SHARE,
              "declared_domains": list(DOMAINS)}
    if total <= 0:
        return {**detail, "status": FAIL, "numerator": 0, "denominator": 0,
                "value": None,
                "note": "语料为空：分母无意义，按 §4.1b 硬规则 1 判失败"}
    missing = [name for name in DOMAINS if counts.get(name, 0) <= 0]
    thin = [{"domain": name, "cards": counts.get(name, 0)}
            for name in DOMAINS if 0 < counts.get(name, 0) < MIN_PER_DOMAIN]
    shares = {name: round(counts.get(name, 0) / total, 4) for name in DOMAINS}
    under = [{"domain": name, "share": share}
             for name, share in shares.items() if share < MIN_DOMAIN_SHARE]
    ok = not missing and not thin and not under and total >= MIN_CANDIDATES
    return {**detail, "status": _status(ok),
            "numerator": len(DOMAINS) - len(missing) - len(thin),
            "denominator": len(DOMAINS),
            "per_domain": {name: counts.get(name, 0) for name in DOMAINS},
            "per_domain_share": shares,
            "min_domain": min(counts.get(name, 0) for name in DOMAINS),
            "min_share": (min(shares.values()) if shares else 0.0),
            "missing_domains": missing, "thin_domains": thin,
            "under_share": under,
            "note": (f"九域覆盖：{total} 张，最小域 {min(counts.get(n, 0) for n in DOMAINS)} 张，"
                     f"最小占比 {min(shares.values()):.4f}"
                     if ok else
                     f"K3 不达标：缺域 {missing}、不足 {MIN_PER_DOMAIN} 张 {thin}、"
                     f"占比不足 {MIN_DOMAIN_SHARE} {under}")}


def exact_duplicates(cards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """入库语料里**完全重复**的卡：同一 `source_ref.sha256` ＋ 同一 `source_span`。

    这是 K4 的**独立**那一半：构建期账本说"去掉了多少重复"，而这一条直接问
    "入库的语料里还有没有重复"。手改语料、或去重没跑，都会在这里显形。
    """
    seen: Dict[tuple, str] = {}
    dupes: List[Dict[str, Any]] = []
    for card in cards:
        source = card.get("source_ref") or {}
        span = card.get("source_span") or {}
        key = (str(source.get("sha256", "")), str(source.get("url", "")),
               span.get("start"), span.get("end"), span.get("chunk_id"))
        if not key[0]:
            continue                      # 没有 sha256 的卡由 K1 负责报
        first = seen.get(key)
        if first is not None:
            dupes.append({"id": str(card.get("id", "")), "duplicate_of": first})
        else:
            seen[key] = str(card.get("id", ""))
    return dupes


def k4_dedupe(cards: Sequence[Dict[str, Any]],
              report_path: Any = DEFAULT_REPORT) -> Dict[str, Any]:
    """K4：去重有效率 ≥60%，且账本必须与入库语料对得上。

    三件事一起判（**全部要过**）：
    ① 账本在（缺 ⇒ `not_measured`，链上按"缺证据"处理）；
    ② 账本的 `cards_kept` 等于入库生成卡数，且 `cards_candidates ≥ 540`
       （§4.1b 的分母下界）——账本说一套、语料是另一套就判失败；
    ③ 入库语料里**没有完全重复的卡**（:func:`exact_duplicates`），
       否则"去重"这件事本身没有发生。
    """
    path = pathlib.Path(report_path)
    detail = {"id": "K4_dedupe_ratio", "line": MIN_DEDUPE_RATIO,
              "candidates_floor": MIN_CANDIDATES, "kept_in_corpus": len(cards)}
    if not path.is_file():
        return {**detail, "status": NA, "numerator": 0, "denominator": 0,
                "value": None,
                "note": f"缺构建期账本 {path}：K4 的分母（被去掉的重复文档数）"
                        f"不在入库语料里，读不到就**判不了**（缺证据不是通过）"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {**detail, "status": NA, "numerator": 0, "denominator": 0,
                "value": None, "note": f"账本读不出来（{exc}）"}
    counts = payload.get("counts") or {}
    kept = int(counts.get("cards_kept") or 0)
    candidates = int(counts.get("cards_candidates") or 0)
    deduped = int(counts.get("cards_deduped") or 0)
    denominator = candidates + deduped
    value = (kept / denominator) if denominator else None
    dupes = exact_duplicates(cards)
    problems: List[str] = []
    if kept != len(cards):
        problems.append(f"账本说 cards_kept={kept}，入库语料实际 {len(cards)} 张"
                        f"（账对不上语料）")
    if denominator < MIN_CANDIDATES:
        problems.append(f"分母 {denominator} < {MIN_CANDIDATES}（§4.1b 的下界）")
    if value is None or value < MIN_DEDUPE_RATIO:
        problems.append(f"去重有效率 {value} < {MIN_DEDUPE_RATIO}")
    if dupes:
        problems.append(f"入库语料里还有 {len(dupes)} 张完全重复的卡"
                        f"（例：{dupes[0]['id']} 与 {dupes[0]['duplicate_of']}）")
    return {**detail, "status": _status(not problems),
            "numerator": kept, "denominator": denominator,
            "value": (round(value, 4) if value is not None else None),
            "cards_candidates": candidates, "cards_deduped": deduped,
            "cards_rejected": int(counts.get("cards_rejected") or 0),
            "exact_duplicates_in_corpus": len(dupes),
            "problems": problems,
            "note": (f"去重有效率 {value:.4f}（kept {kept} / ({candidates} ＋ {deduped})），"
                     f"入库语料无完全重复卡" if not problems else
                     "K4 不达标：" + "；".join(problems))}


def corpus_metrics(cards_dir: Any = DEFAULT_CARDS_DIR,
                   report_path: Any = DEFAULT_REPORT,
                   cards: Optional[Sequence[Dict[str, Any]]] = None
                   ) -> List[Dict[str, Any]]:
    """四门的账（顺序固定，便于链上与用例对拍）。"""
    rows = list(cards) if cards is not None else load_generated(cards_dir)
    return [k1_source_ref(rows), k2_license(rows),
            k3_domain_floor(rows), k4_dedupe(rows, report_path)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge-corpus-gates")
    parser.add_argument("--cards-dir", default=str(DEFAULT_CARDS_DIR))
    parser.add_argument("--import-report", default=str(DEFAULT_REPORT))
    parser.add_argument("--out", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    metrics = corpus_metrics(args.cards_dir, args.import_report)
    statuses = {item["status"] for item in metrics}
    report = {"metrics": metrics,
              "overall": (FAIL if FAIL in statuses
                          else NA if NA in statuses else PASS)}
    if args.out:
        target = pathlib.Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in metrics:
            print(f"[{item['status']:>13}] {item['id']}: {item.get('note', '')}")
        print(f"overall: {report['overall']}")
    return 0 if report["overall"] == PASS else (2 if report["overall"] == NA else 1)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
