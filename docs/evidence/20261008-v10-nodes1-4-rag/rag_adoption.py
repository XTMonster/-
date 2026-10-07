"""量"知识有没有被用上"：把每一镜**注入过的禁项**和**该镜最终选的机位**对起来。

两个来源都在同一跑的产物里：
  * `runs/llm_trace.jsonl` 的 `editor` 行 —— 那一镜提示里的【硬约束（禁/许）】栏；
  * 同一条 trace 的 `response.tool_calls` —— 那一镜提交的草稿。
不重跑、不调模型。
"""
from __future__ import annotations

import io
import json
import re
import sys

FORBID_RE = re.compile(r"禁=\{([^}]*)\}")


def prompt_text(prompt) -> str:
    if isinstance(prompt, str):
        return prompt
    out = []
    for msg in prompt or []:
        if isinstance(msg, dict) and isinstance(msg.get("content"), str):
            out.append(msg["content"])
    return "\n".join(out)


def arguments(row) -> dict:
    response = row.get("response") or {}
    for call in response.get("tool_calls") or []:
        raw = call.get("arguments") if isinstance(call, dict) else None
        if not raw:
            continue
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            continue
    return {}


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    path = sys.argv[1] if len(sys.argv) > 1 else "runs/llm_trace.jsonl"
    rows = [json.loads(line) for line in io.open(path, encoding="utf-8")
            if line.strip()]
    hits = misses = 0
    for row in rows:
        if row.get("purpose") != "editor":
            continue
        text = prompt_text(row.get("prompt"))
        lane = text.split("【硬约束（禁/许）】")[-1] if "【硬约束（禁/许）】" in text else ""
        forbids = set()
        for chunk in FORBID_RE.findall(lane):
            forbids |= {item.strip() for item in chunk.split(",") if item.strip()}
        draft = arguments(row)
        camera = draft.get("camera") or {}
        moves = [str((m or {}).get("type")) for m in camera.get("movements") or []]
        shot_type = str(draft.get("shot_type") or "")
        chosen = {f"movement:{m}" for m in moves if m} | (
            {f"shot_size:{shot_type}"} if shot_type else set())
        violated = sorted(forbids & chosen)
        if forbids:
            hits += 1 if not violated else 0
            misses += 1 if violated else 0
        print(f"{draft.get('shot_id') or '?':<9} type={shot_type:<4} "
              f"moves={','.join(moves) or '-':<16} 禁={sorted(forbids) or []} "
              f"{'违反=' + str(violated) if violated else 'OK'}")
    print(f"\n带禁项的镜：{hits + misses}　未违反 {hits}　违反(记在审计里) {misses}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
