"""给 L3 案例生成**中文检索线索**（只做检索键，不替换作者的原文）。

为什么需要它（2026-10-02 实测，`ACCEPTANCE_STATUS.md` §三十.4）：产品的查询是**中文
散文**（"米迦尔自信面朝画面左侧，推镜缓入…"），而 L3 的 810 篇案例**含中文的 0 篇**
——`CaseIndex._text` 只吃作者写的字（英文 `excerpt` ＋ 出处标题），BM25 对中文查询
**恒 0 命中**，E1 连分母都没有。同语言对照（英文查询打英文语料）也只有 0–1/18，
说明"查询与语料对不上"是独立于语言的第二层缺口。

本工具为每个案例生成一句**中文检索线索**：它**只是检索键**，用来把中文查询和这条
案例接上；返回给模型/用户的仍然是作者的英文原文摘录（`excerpt`），一个字都不改。

纪律：

* **换族**：抽取器是 DeepSeek，所以这里走 GLM（与 `holdout_pool` 同一条通道）；
* **不是我们写的理论**：这条线索是**翻译/改写作者自己的摘录**，不是新观点；提示词
  明确要求"只搬运，不评论"；
* **不许带约束**：出现 `禁止/必须/不得/务必` 的线索**丢弃**（L3 不许产出约束，
  §2.3b 的 E3）——这条在产出侧机械检查，不靠模型自觉；
* **可复算**：文件记 `cases_sha256`（`knowledge/cases.jsonl` 的字节摘要）与
  `prompt_sha256`；案例层一变，旧线索文件**作废**（`CaseIndex` 拒用，见那里的注释）。

用法::

    python -m tools.kb_fetch.case_search_zh --provider glm --model glm-4.7 \\
        --out knowledge/cases.search_zh.jsonl --workers 6
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import re
import sys
from typing import Dict, List, Optional, Sequence

try:
    from . import common
    from . import llm
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common, llm  # type: ignore

CASES = common.KNOWLEDGE / "cases.jsonl"
OUT = common.KNOWLEDGE / "cases.search_zh.jsonl"

#: 线索的长度带宽（太短没有信息量、太长会盖过原文摘录）。
MIN_CHARS = 8
MAX_CHARS = 90
#: 出现这些词就丢弃——L3 **不许**产出约束（E3）。机械检查，不靠模型自觉。
CONSTRAINT_WORDS = ("禁止", "必须", "不得", "务必", "一定要")

SYSTEM = (
    "你是分镜知识库的检索线索标注员。给你一条**英文影评/制作分析摘录**，"
    "请把它改写成**一句中文检索线索**，用来把中文的拍摄查询和这条摘录接上。\n"
    "硬规则：\n"
    "1. **只搬运摘录里已有的信息**（画面、景别、机位、运镜、剪辑、节奏、声音、构图、"
    "表演、调度…），不要评论、不要补充外部知识、不要写成观后感；\n"
    "2. 只用**陈述句**，**不要**出现'必须/禁止/不得/务必'这类要求或禁令；\n"
    "3. " + f"{MIN_CHARS}–{MAX_CHARS} 字，一句，不要标点堆砌，不要列点；\n"
    "4. 不要写片名之外的专有名词堆砌，重点是**可被查询命中的工艺词**。\n"
    "只输出 JSON：{\"zh\": \"<中文线索>\"}"
)


def cases_digest(path: pathlib.Path) -> str:
    """`cases.jsonl` 的**字节**摘要——案例一变，旧线索文件就作废。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_sha() -> str:
    return hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest()


def load_cases(path: pathlib.Path) -> List[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def line_for(client, case: dict) -> Optional[dict]:
    """一条案例 → 一条线索（不合格返回 None，**不编**）。"""
    excerpt = str(case.get("excerpt") or "").strip()
    if not excerpt:
        return None
    source = case.get("source_ref") or {}
    user = ("【摘录】\n%s\n\n【出处标题】%s\n\n【原语言】英文"
            % (excerpt[:800], str(source.get("title") or "")[:120]))
    try:
        reply = client.chat_json(SYSTEM, user, 0.0, 0, 1024)
    except Exception:  # noqa: BLE001 - 这一条的失败不该拖死整批
        return None
    zh = str(reply.get("zh") or "").strip()
    zh = re.sub(r"\s+", "", zh)
    if not (MIN_CHARS <= len(zh) <= MAX_CHARS):
        return None
    if any(word in zh for word in CONSTRAINT_WORDS):
        return None        # E3：L3 不许产出约束
    if not re.search(r"[\u4e00-\u9fff]", zh):
        return None        # 必须是中文线索
    return {"case_id": str(case.get("case_id")), "zh": zh}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.case_search_zh")
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--provider", default="glm")
    parser.add_argument("--model", default="glm-4.7")
    parser.add_argument("--scripted", default="")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(list(argv) if argv is not None else None)

    cases_path = pathlib.Path(args.cases)
    out_path = pathlib.Path(args.out)
    cases = load_cases(cases_path)
    digest = cases_digest(cases_path)

    done: Dict[str, dict] = {}
    if out_path.is_file():                       # 断点续跑：同代文件里已有的直接复用
        for row in load_cases(out_path):
            if row.get("cases_sha256") == digest and row.get("zh"):
                done[str(row["case_id"])] = row
    todo = [case for case in cases if str(case.get("case_id")) not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(json.dumps({"cases": len(cases), "resumed": len(done), "todo": len(todo),
                      "cases_sha256": digest[:16]}, ensure_ascii=False))

    client = llm.make_client(args.provider, args.model, args.scripted)
    rows: List[dict] = list(done.values())
    dropped = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for result in pool.map(lambda case: line_for(client, case), todo):
            if result is None:
                dropped += 1
                continue
            rows.append({**result, "cases_sha256": digest, "model": client.model_id,
                         "family": client.family, "prompt_sha256": prompt_sha()})
    rows.sort(key=lambda row: str(row["case_id"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                        encoding="utf-8", newline="\n")
    print(json.dumps({"written": len(rows), "dropped": dropped,
                      "coverage": round(len(rows) / max(1, len(cases)), 4),
                      "path": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
