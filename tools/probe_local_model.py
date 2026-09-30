"""OpenAI 兼容端点的端到端探针（执行文档 v1.2 §19.3 / §21.7）。

用途：对任意 OpenAI 兼容端点跑一次真实调用，回答三个问题：

1. 我们构造的 `emit_plan` 请求，这个模型是否真的会按工具调用回？
2. 延迟量级是多少（决定预算与超时该设多大）？
3. 返回的结构化参数能否直接过 `Plan.from_dict` 与 §5.2 校验？

只读探针：不发文件、不改场景、不落盘（除非显式给 --out）。

**`--model` 是必填的**：默认值曾经写死成 `qwen3-vl:30b`，而本地 Ollama 路线已在
2026-10-01 停用（加载即 `HTTP 500 token repeat limit`；`ollama pull` 还把 C 盘
吃到过 4.1 GB）。留一个跑不起来的默认值会让"验收命令"看起来可跑、实际必炸，
所以这里不给默认值——要跑什么端点，自己写清楚。

用法：
  python tools/probe_local_model.py --model glm-4.7-flash \
      --base-url https://open.bigmodel.cn/api/paas/v4 \
      [--script fixtures/script_simple.fountain] [--out <json>]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.enums import Purpose  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.contracts.transport import OpenAICompatibleTransport  # noqa: E402
from block_director.layer5_orchestrator.editor import build_editor_payload  # noqa: E402
from block_director.layer5_orchestrator.planner import build_plan_payload  # noqa: E402

DEFAULT_SCRIPT = "INT. 公寓客厅 - 夜\n\n林可坐在沙发上打电话。\n\n林可\n你还在听吗。\n"


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="probe_local_model")
    parser.add_argument("--base-url", default="",
                        help="OpenAI 兼容端点；留空则读 $env:OPENAI_BASE_URL")
    parser.add_argument("--model", required=True,
                        help="**必填**：不给默认值——写死的本地模型已于 2026-10-01 停用")
    parser.add_argument("--script", default="")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--out", default="")
    return parser.parse_args(argv)


def main(argv) -> int:
    args = parse_args(argv)
    script = (Path(args.script).read_text(encoding="utf-8", errors="replace")
              if args.script and Path(args.script).exists() else DEFAULT_SCRIPT)
    transport = OpenAICompatibleTransport(base_url=args.base_url, api_key="",
                                          model=args.model,
                                          timeout=args.timeout)
    report = {"base_url": args.base_url, "model": args.model}

    plan_payload = build_plan_payload(script)
    started = time.time()
    try:
        reply = transport.chat(plan_payload, timeout=args.timeout)
    except Exception as exc:                       # noqa: BLE001 - 探针要报实情
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(report, ensure_ascii=False))
        return 1
    report["plan_seconds"] = round(time.time() - started, 1)
    report["plan_tool_calls"] = [call.function.name for call in reply.tool_calls]
    report["usage"] = reply.usage.to_dict() if reply.usage else None

    plan = None
    call = next((c for c in reply.tool_calls
                 if c.function.name == "emit_plan"), None)
    if call is None:
        report["plan_error"] = ("模型没有调用 emit_plan；"
                                f"content={ (reply.content or '')[:200]!r}")
    else:
        try:
            plan = Plan.from_dict(call.function.parsed_arguments())
            report["plan_shots"] = len(plan.shots)
            report["plan_shot_types"] = [str(shot.shot_type) for shot in plan.shots]
            report["plan_total_frames"] = plan.total_frames
        except Exception as exc:                   # noqa: BLE001
            report["plan_error"] = f"{type(exc).__name__}: {exc}"

    if plan is not None and plan.shots:
        editor_payload = build_editor_payload(plan.shots[0], plan, shot_order=1,
                                              scene_text=script)
        started = time.time()
        try:
            draft_reply = transport.chat(editor_payload, timeout=args.timeout)
            report["editor_seconds"] = round(time.time() - started, 1)
            report["editor_tool_calls"] = [c.function.name
                                           for c in draft_reply.tool_calls]
            draft_call = next((c for c in draft_reply.tool_calls
                               if c.function.name == "emit_shot_draft"), None)
            report["editor_ok"] = draft_call is not None
            if draft_call is not None:
                draft = draft_call.function.parsed_arguments()
                report["editor_actions"] = len(draft.get("actions", []))
                report["editor_dialogues"] = len(draft.get("dialogues", []))
        except Exception as exc:                   # noqa: BLE001
            report["editor_error"] = f"{type(exc).__name__}: {exc}"

    report["ok"] = bool(report.get("plan_shots"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8", newline="\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
