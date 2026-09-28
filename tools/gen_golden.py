"""生成派生 Golden 夹具（执行文档 v1.2 §21.4）。

人工维护的是 `fixtures/mock_llm_responses/` 里的两份"期望输出"：
`plan_simple.json`（阶段 A 的拍摄清单）与 `drafts_simple.json`（阶段 B1 的
逐镜草案）。本脚本把它们合并后展开成两份派生夹具：

- `fixtures/expected_sdl_simple.json` —— 计划经 SDL 组装 + §5.2 校验（含帧号
  回填）后的完整 SDL；
- `fixtures/tool_transcript_simple.jsonl` —— 一次真实运行会留下的审计记录
  （`plan_received` + 一条 `place_character`），供 replay 回归使用。

这样"期望"与"实际"永远由同一份计划推导，改计划只需重跑本脚本。

用法：
  python tools/gen_golden.py          # 写入
  python tools/gen_golden.py --check  # 只校验是否漂移（CI/测试用）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.plan import Plan            # noqa: E402
from block_director.layer2_sdl import build_sdl, validate_sdl  # noqa: E402

FIXTURES = ROOT / "fixtures"
PLAN_FILE = FIXTURES / "mock_llm_responses" / "plan_simple.json"
DRAFTS_FILE = FIXTURES / "mock_llm_responses" / "drafts_simple.json"
SDL_FILE = FIXTURES / "expected_sdl_simple.json"
TRANSCRIPT_FILE = FIXTURES / "tool_transcript_simple.jsonl"

#: 记录进夹具的那次"用户手动调整"：把林可往右挪一点。
#: 数值是刻意选的——它跑在 build_scene 之后，用来证明重放会把工具调用重新落实。
USER_EDIT = {"character_id": "char_001", "position": [1.2, 0.0, 0.0]}


def load_plan() -> Plan:
    return Plan.from_dict(json.loads(PLAN_FILE.read_text(encoding="utf-8")))


def load_drafts() -> list:
    payload = json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))
    return list(payload.get("drafts", []))


def merged_plan() -> Plan:
    """计划 + 逐镜草案 = 执行引擎真正吃到的计划（§7.1 的 A → B1）。"""
    from block_director.layer5_orchestrator.editor import ShotDraft, merge_draft

    plan = load_plan()
    for draft in load_drafts():
        plan = merge_draft(plan, ShotDraft.from_dict(draft))
    return plan


def expected_sdl(plan: Plan) -> dict:
    """计划 → SDL → §5.2 校验（校验会回填缺失的帧号）。"""
    sdl = build_sdl(plan, project_name=plan.scene_heading)
    validate_sdl(sdl)
    return sdl.to_dict()


def expected_transcript(plan: Plan) -> str:
    """一条一次真实运行会留下的审计记录（不含时间戳，保证逐字符可比）。"""
    records = [
        {"kind": "plan_received",
         "message": f"分镜计划完成：{len(plan.shots)} 个镜头",
         "level": "info",
         "data": {"plan": plan.to_dict(),
                  "shots": [shot.to_dict() for shot in plan.shots],
                  "total_frames": plan.total_frames}},
        {"kind": "tool_call",
         "message": "place_character -> ok",
         "level": "info",
         "data": {"tool": "place_character", "ok": True, "args": dict(USER_EDIT)}},
    ]
    return "\n".join(json.dumps(record, ensure_ascii=False)
                     for record in records) + "\n"


def render() -> dict:
    plan = merged_plan()
    return {
        SDL_FILE: json.dumps(expected_sdl(plan), ensure_ascii=False, indent=2) + "\n",
        TRANSCRIPT_FILE: expected_transcript(merged_plan()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="gen_golden")
    parser.add_argument("--check", action="store_true",
                        help="只校验夹具是否与计划一致，不写入")
    args = parser.parse_args()

    drifted = []
    for path, content in render().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if args.check:
            if current != content:
                drifted.append(path.name)
            continue
        # newline="\n"：与 .gitattributes 的 eol=lf 保持一致（见 gen_specs.py）
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"[OK] 已写入 {path.relative_to(ROOT)}")

    if args.check:
        if drifted:
            print(f"[DRIFT] 夹具与计划不一致：{', '.join(drifted)}；"
                  f"请运行 python tools/gen_golden.py")
            return 1
        print("[OK] Golden 夹具与 fixtures/mock_llm_responses/plan_simple.json 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
