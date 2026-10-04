"""§79.3: 量"修复回合里改动类工具的比例与它的收益"。

从真跑的 audit_log.jsonl 里重建每一个**修复回合**（llm_request(purpose=repair)
到下一次请求之间），统计：

  - 这一回合调了哪些工具、几次、成功几次；
  - 有没有**成功执行**的**改动类**工具（MUTATING_TOOLS）；
  - 这一回合之后**同一镜**的那条新 shot_audit 有没有变好。

只读，不改任何东西。用法：

    python work/_repair_yield.py docs/evidence/20261004_chunked_long16/audit_log.jsonl
"""

from __future__ import annotations

import collections
import io
import json
import re
import sys

sys.path.insert(0, ".")

from block_director.contracts.tools import MUTATING_TOOLS, READ_ONLY_TOOLS  # noqa: E402

SHOT_RE = re.compile(r"(shot_\d+)")


def main(path: str) -> None:
    events = [json.loads(line) for line in io.open(path, encoding="utf-8")
              if line.strip()]
    rounds = []
    current = None            # 当前还没收尾的修复回合
    purpose = None
    audits_by_shot = collections.defaultdict(list)
    audit_seq = []            # (index, shot, passed, score)

    for index, event in enumerate(events):
        kind = event.get("kind")
        data = event.get("data") or {}
        if kind == "llm_request":
            purpose = str(data.get("purpose") or "")
            if purpose == "repair":
                shot = SHOT_RE.search(str(event.get("message") or ""))
                current = {
                    "index": index,
                    "shot": shot.group(1) if shot else "",
                    "tools": [],
                    "mutating_ok": 0,
                    "read_only_ok": 0,
                    "failed": 0,
                    "history": purpose,
                }
                rounds.append(current)
            else:
                current = None
            continue
        if kind == "shot_audit":
            shot = str(data.get("shot") or "")
            passed = bool(data.get("passed"))
            score = data.get("composition_score")
            audits_by_shot[shot].append((index, passed, score))
            audit_seq.append((index, shot, passed, score))
            # 把这条审计挂到**它之前最近的那个**同镜修复回合上
            for candidate in reversed(rounds):
                if candidate["index"] < index and candidate["shot"] == shot:
                    candidate.setdefault("audit_after", (passed, score, index))
                    break
            continue
        if kind == "tool_call" and current is not None:
            name = str(data.get("tool") or "")
            ok = bool(data.get("ok"))
            current["tools"].append(name)
            if not ok:
                current["failed"] += 1
            elif name in MUTATING_TOOLS:
                current["mutating_ok"] += 1
            elif name in READ_ONLY_TOOLS:
                current["read_only_ok"] += 1

    if not rounds:
        print("没有修复回合")
        return

    tool_counter = collections.Counter()
    for item in rounds:
        tool_counter.update(item["tools"])

    print(f"修复回合数: {len(rounds)}")
    print(f"回合里工具调用总数: {sum(len(r['tools']) for r in rounds)}")
    print()
    print("=== 工具名分布（修复回合内） ===")
    mut_hits = 0
    for name, count in tool_counter.most_common():
        tag = "改动" if name in MUTATING_TOOLS else (
            "只读" if name in READ_ONLY_TOOLS else "其它")
        print(f"  {name:24s} {count:5d}  [{tag}]")
    print()

    with_mut = [r for r in rounds if r["mutating_ok"] > 0]
    without = [r for r in rounds if r["mutating_ok"] == 0]
    mut_hits = sum(r["mutating_ok"] for r in rounds)

    def outcome(rows):
        done = [r for r in rows if "audit_after" in r]
        passed = sum(1 for r in done if r["audit_after"][0])
        return len(rows), len(done), passed

    print("=== 有没有真的动手 ===")
    for label, rows in (("有改动类工具成功", with_mut),
                        ("一次改动都没有", without)):
        n, done, passed = outcome(rows)
        print(f"  {label}: {n} 回合"
              f"（其中 {done} 回合看到了复核结果，{passed} 回合通过）")

    print()
    print(f"改动类工具成功执行的总次数: {mut_hits}")
    print()
    print("=== 只看构图的回合：复核前后的分 ===")
    deltas = []
    for item in rounds:
        if "audit_after" not in item:
            continue
        after_passed, after_score, _ = item["audit_after"]
        if after_score is None:
            continue
        before = None
        for index, passed, score in reversed(audits_by_shot[item["shot"]]):
            if index < item["index"]:
                before = score
                break
        if before is None:
            continue
        deltas.append((item, before, after_score, after_passed))
    improved = sum(1 for _, b, a, _ in deltas if a > b + 1e-9)
    worsened = sum(1 for _, b, a, _ in deltas if a < b - 1e-9)
    same = len(deltas) - improved - worsened
    print(f"  可对比的回合: {len(deltas)}；变好 {improved}、变差 {worsened}、"
          f"没动 {same}")
    if deltas:
        mean = sum(a - b for _, b, a, _ in deltas) / len(deltas)
        print(f"  平均 Δ构图分: {mean:+.2f}")
    print()
    print("=== 有改动却没通过的回合（诊断） ===")
    for item in with_mut:
        if item.get("audit_after") and not item["audit_after"][0]:
            names = collections.Counter(item["tools"])
            print(f"  {item['shot']}: {dict(names)} -> 仍未通过"
                  f"（分 {item['audit_after'][1]}）")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1
         else "docs/evidence/20261004_chunked_long16/audit_log.jsonl")
