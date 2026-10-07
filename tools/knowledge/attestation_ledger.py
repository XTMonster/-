"""C4 记账纪律的**机器固化**：`attestation` 报告的口径校验（诊断，不是门）。

为什么要这件事（2026-10-07，`docs/knowledge/OPEN_ITEMS_20261007.md` C4）：
`tools/knowledge/attestation.py` 量的是"这条边的槽位能不能在**它自己的来源卡正文**里
找到依据"，实测 `attested 331 / unattested 1262 / not-checkable 345`。这个数字一旦
被下游转述，有三种常见的写歪：

1. **措辞**：把 `unattested` 说成"编造/伪造"。它是**下界**——卡可以**蕴含**一个取值
   而不写出它（"把画面倒过来看"蕴含"检验平衡"），所以它只说"**未被来源佐证**"。
2. **分母**：`0.2078` 的分母是**可检槽位 1593**（＝ `attested + unattested`）；
   若换成分母＝全量槽位 **1938**，同一批数是 `0.1708`。两个分母必须**并列**出现，
   不许只报好看的那一个。
3. **上界**：`not-checkable ≤ 345`。这一桶是"词表自己就是桶名"（`intensity:mid`、
   `avg_shot_len:>8s`），正文里本来就不会出现它；它一旦涨上去，说明判据被悄悄放宽了。

本模块**不重算**判据（那是 `attestation.py` 的事），只对**报告本身**做口径校验：
给定一份 `attestation.py --json` 的产物，逐条验不变量，违规即非零退出。

**换代纪律**：`PINNED` 里钉的是**这一代索引的读数**（`attest/v1`，638 条边）。
索引换代会让这里的数字对不上——这是**故意的**：它逼着换代的人按
`docs/knowledge/REGEN_LOG_TEMPLATE.md` 显式登记，而不是把读数悄悄改掉。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Dict, List, Sequence

ATTESTED = "attested"
UNATTESTED = "unattested"
NOT_CHECKABLE = "not-checkable"
SLOT_KEYS = (ATTESTED, UNATTESTED, NOT_CHECKABLE)

#: 这一代（`attest/v1`，2026-10-07 实测）钉住的口径常量。换代必须显式改这里并登记。
PINNED = {
    "criterion_version": "attest/v1",
    "edges": 638,
    "checkable_slots": 1593,
    "total_slots": 1938,
    "not_checkable_ceiling": 345,
    "attested_share_checkable": 0.2078,
    "attested_share_total": 0.1708,
}

#: 把 `unattested` 说成"编造"的词。判据：**同一句里没有否定词**才算违规，
#: 所以"未被佐证 ≠ 编造"这种正确写法不会被误伤。
FABRICATION_WORDS = ("编造", "捏造", "伪造", "虚构", "凭空",
                     "fabricat", "made up", "hallucinat", "invented")
NEGATIONS = ("不", "非", "无", "别", "莫", "≠", "!=", "no ", "not ", "never ")
SENTENCE_SPLIT = re.compile(r"[。；;\n]")


def load_report(path: pathlib.Path) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _texts(node) -> List[str]:
    """报告里所有字符串字段（含嵌套），用于措辞检查。"""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        out: List[str] = []
        for value in node.values():
            out.extend(_texts(value))
        return out
    if isinstance(node, (list, tuple)):
        out = []
        for value in node:
            out.extend(_texts(value))
        return out
    return []


def wording_findings(report: dict) -> List[str]:
    findings: List[str] = []
    for text in _texts(report):
        for sentence in SENTENCE_SPLIT.split(text):
            lowered = sentence.lower()
            if not any(word in lowered for word in FABRICATION_WORDS):
                continue
            if any(neg in lowered for neg in NEGATIONS):
                continue
            findings.append(
                "措辞违规：把 `unattested` 说成了『编造』一类断言；一律写"
                f"『未被来源佐证』——原句：{sentence.strip()[:120]}")
    return findings


def check(report: dict) -> dict:
    """纯函数：给定一份 attestation 报告，返回 `{ok, findings, readings}`。"""
    findings: List[str] = []
    slots = report.get("slots")
    if not isinstance(slots, dict):
        findings.append("报告缺 `slots`（三桶计数），无法记账")
        slots = {}
    missing = [key for key in SLOT_KEYS if key not in slots]
    if missing:
        findings.append(f"`slots` 缺键：{missing}")
    extra = [key for key in slots if key not in SLOT_KEYS]
    if extra:
        findings.append(f"`slots` 出现未登记的新桶：{extra}（新桶必须显式登记口径）")

    attested = int(slots.get(ATTESTED, 0))
    unattested = int(slots.get(UNATTESTED, 0))
    not_checkable = int(slots.get(NOT_CHECKABLE, 0))
    total = attested + unattested + not_checkable
    checkable = attested + unattested

    if report.get("criterion_version") != PINNED["criterion_version"]:
        findings.append(
            f"`criterion_version` 是 {report.get('criterion_version')!r}，"
            f"本代钉的是 {PINNED['criterion_version']!r}——判据换代必须登记")
    if total != PINNED["total_slots"]:
        findings.append(
            f"槽位总数 {total} ≠ 钉住的 {PINNED['total_slots']}"
            "（三桶相加必须等于全量槽位数）")
    if report.get("checkable_slots") != checkable:
        findings.append(
            f"`checkable_slots` {report.get('checkable_slots')!r} ≠ "
            f"attested + unattested = {checkable}")
    if checkable != PINNED["checkable_slots"]:
        findings.append(
            f"可检槽位 {checkable} ≠ 钉住的 {PINNED['checkable_slots']}（可检分母变了）")
    if not_checkable > PINNED["not_checkable_ceiling"]:
        findings.append(
            f"`not-checkable` {not_checkable} > 钉住的上界 "
            f"{PINNED['not_checkable_ceiling']}——桶名桶在涨，判据被放宽了")
    if int(report.get("edges", 0)) != PINNED["edges"]:
        findings.append(f"边数 {report.get('edges')!r} ≠ 钉住的 {PINNED['edges']}")

    share_checkable = round(attested / checkable, 4) if checkable else None
    share_total = round(attested / total, 4) if total else None
    if report.get("attested_share") is not None and share_checkable != report["attested_share"]:
        findings.append(
            f"报告里的 `attested_share` {report['attested_share']!r} 与重算的"
            f" {share_checkable!r} 不一致（分母口径对不上）")
    #: **share 只防"回退"，不禁止"变化"**（2026-10-07 修：本工具此前把任何漂移都当违规，
    #: 于是**任何一次合法的语料/索引换代都会把这条判红**）。
    #: C4 要的是"防回退"：**低于**钉住的读数 ⇒ 红（证据支持率掉了）；
    #: **高于**它 ⇒ 只记 `improvements`（那是换代修好了绑定，不是放宽判据）。
    #: 判据/阈值/门限本身一个字没动——这里动的只是"这条工具怎么读同两个数"。
    improvements: List[str] = []
    pinned_checkable = float(PINNED["attested_share_checkable"])
    pinned_total = float(PINNED["attested_share_total"])
    if share_checkable is not None and share_checkable < pinned_checkable - 1e-9:
        findings.append(
            f"可检分母下的 share {share_checkable} **回退**到钉住的 "
            f"{pinned_checkable} 之下")
    elif share_checkable is not None and share_checkable > pinned_checkable + 1e-9:
        improvements.append(
            f"可检分母下的 share {pinned_checkable} → {share_checkable}（升）")
    if share_total is not None and share_total < pinned_total - 1e-9:
        findings.append(
            f"全量分母下的 share {share_total} **回退**到钉住的 {pinned_total} 之下")
    elif share_total is not None and share_total > pinned_total + 1e-9:
        improvements.append(
            f"全量分母下的 share {pinned_total} → {share_total}（升）")

    findings.extend(wording_findings(report))
    return {
        "ok": not findings,
        "findings": findings,
        "improvements": improvements,
        "readings": {
            "criterion_version": report.get("criterion_version"),
            "edges": report.get("edges"),
            "slots": {key: slots.get(key) for key in SLOT_KEYS},
            "checkable_denominator": checkable,
            "total_denominator": total,
            "attested_share_of_checkable": share_checkable,
            "attested_share_of_total": share_total,
            "not_checkable_ceiling": PINNED["not_checkable_ceiling"],
            "wording": "`unattested` ＝ 未被来源佐证（下界），**不是**『编造』",
        },
    }


def render(result: dict) -> str:
    r = result["readings"]
    lines = [
        "attestation 记账口径校验：" + ("pass" if result["ok"] else "FAIL"),
        f"  判据版本 : {r['criterion_version']}｜边数 : {r['edges']}",
        f"  三桶     : attested {r['slots'][ATTESTED]} / "
        f"unattested {r['slots'][UNATTESTED]} / "
        f"not-checkable {r['slots'][NOT_CHECKABLE]}"
        f"（上界 {r['not_checkable_ceiling']}）",
        f"  可检分母 : {r['checkable_denominator']}"
        f" -> share {r['attested_share_of_checkable']}",
        f"  全量分母 : {r['total_denominator']}"
        f" -> share {r['attested_share_of_total']}",
        f"  措辞     : {r['wording']}",
    ]
    for finding in result["findings"]:
        lines.append("  ✗ " + finding)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge.attestation_ledger")
    parser.add_argument("--report", required=True, help="attestation.py --json 的产物")
    parser.add_argument("--json", default="", help="校验结果落盘路径（可选）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = check(load_report(pathlib.Path(args.report)))
    if args.json:
        target = pathlib.Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8", newline="\n")
    print(render(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
