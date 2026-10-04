"""E1 的**词表对齐探针**（草稿区，只读；不碰 knowledge/ 下任何产物）。

它回答一个零 LLM、可复算的问题：**查询里点名的工艺词，在检索键（中文线索）里
到底有没有对应词？** 为什么这个量能预判 E1（2026-10-04 实测）：

* 查询是导演散文（"…浅景深、逆光、留白…"），线索是每条案例的中文改写；
* BM25 只认**词面**：查询点名的词若在整个线索库里一次都不出现，那条案例
  **数学上不可能**被这条查询召回——与"排序好不好"无关；
* 实测（随带的这一份 739 条线索）：`景深` 被 23 条查询点名、**0 条线索**含它；
  `越轴` 15/0、`逆光` 15/0、`留白` 11/0、`侧光` 11/0、`升降` 2/0。

用法::

    python work/e1_vocab_probe.py --cases-dir knowledge --project <project.bdproj>
    python work/e1_vocab_probe.py --cases-dir work/e1_probe_v2/knowledge --project …
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys
from typing import Dict, List

#: `docs/evidence/<run-id>/probe.py` ⇒ **三级**才是仓库根（`parents[0]` 是本目录）。
#: 原先写的是 `parents[1]`（= `docs/evidence`），于是 README 里那条复算命令会把
#: `--project docs/evidence/...` 拼成 `docs/evidence/docs/evidence/...` 而当场报
#: `FileNotFoundError`——一份跑不起来的证据脚本等于没有证据。
ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.cases import load_index  # noqa: E402

#: 查询侧（产品侧）会说的工艺词。**这份表只用于诊断**，不改任何产物；
#: 它按"仓库里已有的词表"分组：景别取 `contracts/enums.SHOT_TYPES` 的中文注释，
#: 运镜取 `MOVEMENT_TYPES` 的中文动作面，其余取产品提示词里真出现过的说法。
CRAFT_WORDS: Dict[str, List[str]] = {
    "景别": ["大远景", "远景", "全景", "中远景", "中景", "中近景", "近景", "特写",
             "大特写", "过肩", "主观镜头"],
    "运镜": ["推镜", "拉镜", "摇镜", "移镜", "跟拍", "升降", "环绕", "甩镜",
             "手持", "变焦", "固定机位", "稳定器", "空镜", "长镜头"],
    "光线": ["顺光", "侧光", "逆光", "顶光", "底光", "硬光", "柔光", "低调",
             "高调", "轮廓光"],
    "构图": ["三分", "居中", "留白", "头部空间", "视线空间", "前景", "后景",
             "景深", "浅景深", "框架构图", "对称"],
    "轴线": ["轴线", "越轴", "银幕方向", "180 度"],
    "剪辑": ["跳切", "叠化", "闪回", "匹配剪辑", "切出", "切入", "蒙太奇"],
    "走位": ["走位", "调度", "交错", "入画", "出画"],
}


def queries_from_project(path: pathlib.Path) -> List[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: List[str] = []
    for scene in payload.get("scenes") or []:
        for shot in scene.get("shots") or []:
            text = str(shot.get("prompt") or "").strip()
            if text and "剧本《" not in text and text not in out:
                out.append(text)
    return out


def report(cases_dir: pathlib.Path, queries: List[str]) -> dict:
    index = load_index(cases_dir, backend="hybrid")
    clues = [str(value) for value in index.search_zh.values()]
    missing: Dict[str, List[str]] = {}
    coverage: Dict[str, Dict[str, int]] = {}
    for group, words in CRAFT_WORDS.items():
        for word in words:
            asked = sum(1 for query in queries if word in query)
            if not asked:
                continue
            in_clues = sum(1 for clue in clues if word in clue)
            coverage[f"{group}/{word}"] = {"queries": asked, "clues": in_clues}
            if not in_clues:
                missing.setdefault(group, []).append(f"{word}({asked})")
    # 同一个词在查询里点名、在线索里没有 ⇒ 这条查询**不可达**那个概念
    asked_total = sum(item["queries"] for item in coverage.values())
    unreachable = sum(item["queries"] for item in coverage.values()
                      if not item["clues"])
    return {"cases_dir": str(cases_dir), "cases": len(index.cases),
            "clues": len(index.search_zh), "queries": len(queries),
            "mentions": asked_total, "mentions_without_any_clue_word": unreachable,
            "coverage": coverage, "missing_by_group": missing}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="e1-vocab-probe")
    parser.add_argument("--cases-dir", default="knowledge")
    parser.add_argument("--project", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    queries = queries_from_project(ROOT / args.project)
    payload = report(ROOT / args.cases_dir, queries)
    print(json.dumps(payload, ensure_ascii=False,
                     indent=2 if args.json else None))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
