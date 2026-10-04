"""声明 vs 交付：逐镜对拍"分镜表声明的拍摄手法"与"交付的相机运动"（零 LLM）。

    python docs/evidence/20261004-declared-vs-delivered/probe.py \
        docs/evidence/20261004_chunked_long17

两边都在同一份交付产物里：`export/shots.json` 的 `declared.technique`（声明侧）与
`movements[].kind`（交付侧）；逐镜检索串里的 `运镜=` 作为交叉验证（它由计划声明派生）。
"""

from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

#: 引擎的运镜词表里没有"固定"（锁机位＝不动），而剧本/查询词表用的是"固定"。
FIXED = {"固定", "static", "fixed"}


def movements(shot: dict) -> list:
    return [str((item or {}).get("kind") or (item or {}).get("type") or "")
            for item in (shot.get("movements") or [])]


def emitted_techniques(run: pathlib.Path) -> dict:
    """逐镜检索串里的 `运镜=` —— 它是**计划声明**的直接派生，用来交叉验证声明侧。"""
    out = {}
    for line in (run / "audit_log.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("kind") != "retrieval_call":
            continue
        data = record.get("data") or {}
        if str(data.get("scope")) != "shot" or not data.get("shot_id"):
            continue
        match = re.search(r"运镜=([^；]*)", str(data.get("query") or ""))
        out[str(data["shot_id"])] = match.group(1) if match else ""
    return out


def main(argv) -> int:
    run = pathlib.Path(argv[1] if len(argv) > 1 else "docs/evidence/20261004_chunked_long17")
    shots = json.loads((run / "export/shots.json").read_text(encoding="utf-8"))["shots"]
    declared = emitted_techniques(run)
    declared_values = collections.Counter(declared.values())
    sources = collections.Counter()
    for shot in shots:
        for item in shot.get("movements") or []:
            sources[str((item or {}).get("source") or "（缺）")] += 1
    moved = [shot["shot_id"] for shot in shots if movements(shot)]
    fixed_but_moved, missed = [], []
    for shot in shots:
        shot_id = shot["shot_id"]
        want = declared.get(shot_id, "")
        got = movements(shot)
        if want in FIXED and got:
            fixed_but_moved.append((shot_id, got))
        elif want and want not in FIXED and want not in got:
            missed.append((shot_id, want, got))
    print(f"逐镜检索串里的运镜分布: {dict(declared_values.most_common())}")
    print(f"交付里有相机运动的镜头: {len(moved)}/{len(shots)}")
    print(f"movements[].source: {dict(sources.most_common())}")
    print(f"**声明固定却有运动: {len(fixed_but_moved)}**")
    print(f"声明非固定却漏掉: {len(missed)}")
    for row in fixed_but_moved[:5]:
        print("   例:", row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
