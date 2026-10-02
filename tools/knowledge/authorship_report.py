"""署名门：语料里的**理论**必须来自**他人著作**，不得是自撰。

用户裁决（2026-10-01）："理论不要自己写，要别人写的——专业的事情交给专业的人做"。
这条要求必须是**机器可查**的，否则它会退化成一句口号。判定口径：

* 生成卡（`knowledge/cards_generated/*.jsonl`）的 `source_ref.url` 必须是
  **http/https**（他人著作）。出现 `repo://`（本项目的自撰笔记）即判失败——
  那是"自己写的理论混进语料"。
* 手写策展卡（`block_director/knowledge/cards_*.py`）**不算理论素材**：它们是
  本项目的**实现规则**（有对应的引擎落点与测试），因此单独计数、不进"他人著作"
  分母，也不冒充理论。

    python tools/knowledge/authorship_report.py [--json out.json]
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.corpus import HANDWRITTEN_CARDS  # noqa: E402
from block_director.utils.console import force_utf8_streams  # noqa: E402

DEFAULT_CARDS_DIR = ROOT / "knowledge" / "cards_generated"
EXTERNAL_SCHEMES = ("http://", "https://")


def generated_cards(cards_dir: pathlib.Path | str = DEFAULT_CARDS_DIR) -> list:
    directory = pathlib.Path(cards_dir)
    out = []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                out.append(json.loads(line))
    return out


def run(cards_dir: pathlib.Path | str = DEFAULT_CARDS_DIR) -> dict:
    cards = generated_cards(cards_dir)
    per_license = collections.Counter()
    per_domain = collections.defaultdict(collections.Counter)
    self_written = []
    for card in cards:
        source = card.get("source_ref") or {}
        url = str(source.get("url", ""))
        license_name = str(source.get("license", "")) or "(空)"
        per_license[license_name] += 1
        kind = "他人著作" if url.startswith(EXTERNAL_SCHEMES) else "自撰"
        per_domain[str(card.get("domain", ""))][kind] += 1
        if kind == "自撰":
            self_written.append({"id": str(card.get("id", "")), "url": url,
                                 "title": str(card.get("source_ref", {}).get("title", ""))})
    handwritten = len(HANDWRITTEN_CARDS)
    passed = not self_written
    return {
        "generated_cards": len(cards),
        "external_cards": len(cards) - len(self_written),
        "self_written_cards": len(self_written),
        "handwritten_engine_rules": handwritten,
        "per_license": dict(per_license.most_common()),
        "per_domain": {domain: dict(counts) for domain, counts in sorted(per_domain.items())},
        "self_written_examples": self_written[:10],
        "passed": passed,
        "note": ("生成卡必须全部来自他人著作（http/https）；手写策展卡是本项目的实现规则，"
                 "单独计数、不冒充理论"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    # 报告里有中文（卡 id / 出处），stdout 一律 UTF-8，免得下游按 UTF-8 解码
    # 到 cp936 字节（见 block_director/utils/console.py 的实测记录）。
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="authorship_report")
    parser.add_argument("--cards-dir", default=str(DEFAULT_CARDS_DIR))
    parser.add_argument("--json", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run(args.cards_dir)
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover - 开发侧度量
    raise SystemExit(main())
