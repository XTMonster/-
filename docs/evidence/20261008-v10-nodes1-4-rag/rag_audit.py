"""把一跑里**真正注入提示**的 RAG 三栏量出来：谁上去了、谁被 token 上限砍掉了。

读 `runs/llm_trace.jsonl`（`prompt` 是逐字的消息列表），按栏标题切块计数，
不猜、不重跑检索。
"""
from __future__ import annotations

import io
import json
import re
import sys

LANES = ("【硬约束（禁/许）】", "【经验建议（软）】", "参考案例（仅参考）")


def message_text(prompt) -> str:
    if isinstance(prompt, str):
        return prompt
    parts = []
    for msg in prompt or []:
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    path = sys.argv[1] if len(sys.argv) > 1 else "runs/llm_trace.jsonl"
    rows = [json.loads(line) for line in
            io.open(path, encoding="utf-8") if line.strip()]
    print(f"trace rows: {len(rows)}")
    for index, row in enumerate(rows, 1):
        text = message_text(row.get("prompt"))
        if "参考资料" not in text and not any(l in text for l in LANES):
            continue
        start = text.find("参考资料")
        block = text[start:start + 6000] if start >= 0 else text
        stats = {}
        for lane in LANES:
            pos = block.find(lane)
            if pos < 0:
                stats[lane] = "缺席"
                continue
            rest = block[pos + len(lane):]
            stop = min([p for p in
                        (rest.find("【"), rest.find("（来自"),
                         rest.find("\n\n\n")) if p >= 0] or [len(rest)])
            body = rest[:stop]
            bullets = [line for line in body.split("\n") if line.strip()]
            stats[lane] = f"{len(bullets)} 行 / {len(body)} 字符"
        print(f"\n#{index} purpose={row.get('purpose')} "
              f"duration={row.get('duration_s')}s "
              f"truncated={row.get('truncated')}")
        for lane, value in stats.items():
            print(f"   {lane}: {value}")
        first = re.search(r"\[[^\]]*\]\s*\[[A-Z_]+\][^\n]*", block)
        if first:
            print("   例:", first.group(0)[:150])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
