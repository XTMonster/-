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

    python -m tools.kb_fetch.case_search_zh --provider glm --model glm-5.3 \\
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
#: 出现这些词就丢弃——**元话术**（"本摘录未涉及景别…"）。为什么它是一条硬规则：
#: 2026-10-03 实测，glm-5.3 在"摘要形状"的提示词下会给**没有任何内容**的碎片
#: （`Lecture 1.` / `4.` / 版权页）写出"仅含编号，未涉及景别、运镜或剪辑"这类句子
#: ——那等于把 `景别/运镜/剪辑` 这些**查询里的工艺词**灌进垃圾文档，BM25 于是让
#: 它们比真案例更容易被中文查询命中（E1 的 top-3 因此被 1900 年代散句占满）。
#: 线索是**检索键**；键里出现"我没讲什么"这种自述，只会制造假命中。
META_WORDS = ("摘录", "本段", "本文", "文中", "书中", "这篇文章", "该文",
              "未涉及", "不涉及", "未提及", "未包含", "不含", "未给出", "未说明")

#: 提示词的形状 = **查询的形状**（v2，2026-10-03）。v1 写的是"把它改写成一句中文线索"，
#: 模型于是写成**摘要**（"本片讲的是什么"）；而产品的查询是**导演的追问**
#: （"这一镜要怎么拍"）。两条文本的词表因此对不上：v1 的线索里几乎不含
#: `推镜/跟拍/低角度/视线/留白` 这类**查询一定会说的工艺词**，BM25 只能靠
#: 单字（的/在/面/下）把 1900 年代散句顶到 top-3（实测 3/18 = 0.1667）。
#: v2 把线索固定成"**先说'要拍什么'，再说'摘录里的做法/规律'**"这一形状，
#: 并允许（且只允许）在摘录真的讲到时使用工艺词；摘录不含工艺信息时**给空串**。
SYSTEM = (
    "你是分镜知识库的检索线索标注员。给你一条**英文影评/制作分析摘录**，"
    "请把它改写成**一句中文检索线索**——**形状要像导演会拿来问这一镜的那句话的答案**：\n"
    "先说'要拍/要表现什么'（景别、机位、运镜、画面里发生的事、要传达的情绪或节奏），"
    "再说'这条摘录给出的做法、规律或例子'。\n"
    "硬规则：\n"
    "1. **只搬运摘录里已有的信息**（画面、景别、机位、运镜、剪辑、节奏、声音、构图、"
    "表演、调度…），不要评论、不要补充外部知识、不要写成观后感；\n"
    "2. 摘录若**不含任何拍摄工艺信息**（例如只有讲次编号、目录行、人名、书名、"
    "版权或页眉页脚），`zh` 必须给**空串**——宁可没有线索，也不许硬编；\n"
    "3. 直接写内容本身：不许出现'摘录/本段/本文/文中/书中/这篇文章'，也不许写"
    "'未涉及/不涉及/未提及/不含'这类**元话术**；\n"
    "4. 只用**陈述句**，**不要**出现'必须/禁止/不得/务必/一定要'这类要求或禁令；\n"
    "5. " + f"{MIN_CHARS}–{MAX_CHARS} 字，一句，不要标点堆砌，不要列点；\n"
    "6. 优先用中文拍摄现场会说的**工艺词**（特写/中景/全景、推镜/拉镜/摇镜/跟拍/升降、"
    "低角度/俯拍、侧光/逆光、构图/留白、视线匹配、轴线、节奏、剪辑…），"
    "但**只能用在摘录真的讲到它的时候**；\n"
    "只输出 JSON：{\"zh\": \"<中文线索；摘录不含工艺信息时给空串>\"}"
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
    return make_line(client, case)[0]


def classify(zh: str) -> str:
    """一条线索文本 → 被丢弃的具名原因（`""` = 合格）。**与 :func:`make_line` 同源**。"""
    if not zh:
        return "empty（摘录不含工艺信息，按规则给空串）"
    if not (MIN_CHARS <= len(zh) <= MAX_CHARS):
        return f"length（{len(zh)} 字，带宽 {MIN_CHARS}–{MAX_CHARS}）"
    if any(word in zh for word in CONSTRAINT_WORDS):
        return "constraint（含约束词，E3）"
    if any(word in zh for word in META_WORDS):
        return "meta（元话术：" + "、".join(w for w in META_WORDS if w in zh) + "）"
    if not re.search(r"[\u4e00-\u9fff]", zh):
        return "not-chinese"
    return ""


def make_line(client, case: dict) -> tuple:
    """一条案例 → （线索行或 None, 丢弃原因）。原因用于**如实记账**（谁被丢掉、为什么）。"""
    excerpt = str(case.get("excerpt") or "").strip()
    if not excerpt:
        return None, "excerpt-empty"
    source = case.get("source_ref") or {}
    user = ("【摘录】\n%s\n\n【出处标题】%s\n\n【原语言】英文"
            % (excerpt[:800], str(source.get("title") or "")[:120]))
    try:
        reply = client.chat_json(SYSTEM, user, 0.0, 0, 1024)
    except Exception as exc:  # noqa: BLE001 - 这一条的失败不该拖死整批
        #: **瞬时失败与规则丢弃必须分开记**（2026-10-03 实测：14 并发下 810 条里
        #: 204 条 `call-failed`，占 25%——把它们和 273 条"摘录不含工艺信息"混在
        #: 一个 `dropped` 里，覆盖率就被失败悄悄拉低）。带上异常类型与首句，
        #: 才分得清"上游限流"与"模型恒空正文"。
        return None, f"call-failed（{type(exc).__name__}：{str(exc)[:60]}）"
    zh = str(reply.get("zh") or "").strip()
    zh = re.sub(r"\s+", "", zh)
    reason = classify(zh)
    if reason:
        return None, reason
    return {"case_id": str(case.get("case_id")), "zh": zh}, ""


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.case_search_zh")
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--provider", default="glm")
    #: 用户裁决（2026-10-04）：GLM 只用 `glm-5.3`（只有它还有额度）。
    parser.add_argument("--model", default="glm-5.3")
    parser.add_argument("--scripted", default="")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dropped-out", default="",
                        help="把被丢弃的条目与**具名原因**写到这个文件（缺省不写）")
    #: 定向重跑：**只**重跑上一轮"瞬时失败"的那些条目。为什么需要它——空串丢弃是
    #: 规则要求的（摘录真没有工艺信息），重跑它们只是白烧调用；而 `call-failed`
    #: 是上游抖动，重跑就能回收（2026-10-03 实测：204 条 call-failed 把 810 条的
    #: 覆盖率从应有的 ~60% 压到 41%，低于产物下界）。
    parser.add_argument("--retry-from", default="",
                        help="从这份丢弃账（--dropped-out 的产物）里挑要重跑的 case_id")
    parser.add_argument("--retry-reasons", default="call-failed",
                        help="配合 --retry-from：只重跑原因以这些前缀开头的条目（逗号分隔）")
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
    if args.retry_from:
        prefixes = tuple(part.strip() for part in str(args.retry_reasons).split(",")
                         if part.strip())
        prior: Dict[str, str] = {}
        retry_path = pathlib.Path(args.retry_from)
        if retry_path.is_file():
            for row in load_cases(retry_path):
                prior[str(row.get("case_id"))] = str(row.get("reason") or "")
        todo = [case for case in todo
                if str(case.get("case_id")) in prior
                and prior[str(case.get("case_id"))].startswith(prefixes)]
        print(json.dumps({"retry_from": str(retry_path), "reasons": list(prefixes),
                          "retry_todo": len(todo)}, ensure_ascii=False))
    if args.limit:
        todo = todo[:args.limit]
    print(json.dumps({"cases": len(cases), "resumed": len(done), "todo": len(todo),
                      "cases_sha256": digest[:16]}, ensure_ascii=False))

    client = llm.make_client(args.provider, args.model, args.scripted)
    rows: List[dict] = list(done.values())
    dropped = 0
    dropped_rows: List[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for case, result, reason in pool.map(
                lambda case: (case, *make_line(client, case)), todo):
            if result is None:
                dropped += 1
                dropped_rows.append({"case_id": str(case.get("case_id")),
                                     "reason": reason,
                                     "excerpt": str(case.get("excerpt") or "")[:200]})
                continue
            rows.append({**result, "cases_sha256": digest, "model": client.model_id,
                         "family": client.family, "prompt_sha256": prompt_sha()})
    rows.sort(key=lambda row: str(row["case_id"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                        encoding="utf-8", newline="\n")
    if args.dropped_out:
        dropped_path = pathlib.Path(args.dropped_out)
        dropped_path.parent.mkdir(parents=True, exist_ok=True)
        dropped_rows.sort(key=lambda row: row["case_id"])
        dropped_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in dropped_rows),
            encoding="utf-8", newline="\n")
    print(json.dumps({"written": len(rows), "dropped": dropped,
                      "coverage": round(len(rows) / max(1, len(cases)), 4),
                      "path": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
