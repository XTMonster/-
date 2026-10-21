"""final16b 冻结基准 -> 细排 -> 白模视频（零 LLM，bpy 侧）。

回归 ``docs/evidence/20261020-market-coin-coarse-gate-pass-final16b/``：
粗排 gate 已通过且 baseline 已冻结，本探针把冻结基准接进细排编排器
（``run_detail_pipeline``），逐镜审核 + 全片回放后渲染
``final_video.mp4``。这验证的是"粗排通过 -> 白模预演视频必产出"这一
整机闭环；任何 gate 未过都不允许出片。

运行：
  blender --background --factory-startup --python
    tools/blender_tests/test_final16b_detail_render.py -- --out <dir>
    [--baseline <coarse_world_baseline.json>]
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

DEFAULT_BASELINE = (ROOT / "docs" / "evidence"
                    / "20261021-final16-coarse-r2-10-r6full" / "coarse"
                    / "coarse_world_baseline.json")
FINAL16_STDOUT = (ROOT / "docs" / "evidence"
                  / "20261020-market-real-final16" / "stdout.log")

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False,
                         "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=5)}


def _final16_payload() -> dict:
    """从真跑 stdout.log 提取 BLOCKDIRECTOR_RESULT 的 JSON 负载。"""
    assert FINAL16_STDOUT.exists(), f"缺 final16 证据：{FINAL16_STDOUT}"
    text = FINAL16_STDOUT.read_text(encoding="utf-8", errors="replace")
    import re
    match = re.search(r"BLOCKDIRECTOR_RESULT (.*)", text)
    assert match, "stdout.log 里没有 BLOCKDIRECTOR_RESULT"
    raw = match.group(1)
    raw = raw[: raw.rfind("}") + 1]
    return json.loads(raw)


def _plan() -> dict:
    """与 final16 真跑逐字一致的 plan（含 framing_target/responsibility）。"""
    payload = _final16_payload()
    return payload["plan"]


def main():
    argv = list(sys.argv)
    out_root = ROOT / "docs" / "evidence" / "20261020-final16b-detail-render"
    baseline_path = DEFAULT_BASELINE
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out_root = Path(args[args.index("--out") + 1])
        if "--baseline" in args:
            baseline_path = Path(args[args.index("--baseline") + 1])
    out_root = out_root.resolve()
    if not baseline_path.is_absolute():
        baseline_path = (ROOT / baseline_path).resolve()
    else:
        baseline_path = baseline_path.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)

    from block_director.layer5_orchestrator.detail_pipeline import (
        run_detail_pipeline,
    )

    def detail_render():
        assert baseline_path.exists(), f"缺 baseline：{baseline_path}"
        baseline = json.loads(
            baseline_path.read_text(encoding="utf-8"))
        plan = _plan()
        detail = run_detail_pipeline(
            baseline=baseline, plan=plan, out_dir=out_root,
            render_video=True)
        report_path = out_root / "detail_pipeline_report.json"
        report_path.write_text(
            json.dumps(detail, ensure_ascii=False, indent=2),
            encoding="utf-8")

        final_path = out_root / "final_video.mp4"
        detail_ok = detail.get("gates", {}).get("detail") == "pass"
        seq_ok = detail.get("gates", {}).get("sequence") == "pass"
        final_ok = detail.get("gates", {}).get("final") == "pass"
        video_final = bool(detail.get("final"))
        video_exists = final_path.exists() and final_path.stat().st_size > 0
        video = detail.get("video") or {}
        return {
            "ok": (detail_ok and seq_ok and final_ok and video_final
                   and video_exists),
            "gates": detail.get("gates"),
            "final": video_final,
            "baseline": str(baseline_path),
            "final_video": str(final_path),
            "video": {
                "rendered": video.get("rendered"),
                "full_path": video.get("full_path"),
                "final_path": video.get("final_path"),
                "failed_shots": video.get("failed_shots"),
                "shot_videos": video.get("shot_videos"),
            },
        }

    check("final16b_detail_render", detail_render)

    passed = [name for name, result in RESULTS.items()
              if result.get("ok") is True]
    failed = [name for name, result in RESULTS.items()
              if result.get("ok") is not True]
    print("BD_TEST_RESULT " + json.dumps({
        "ok": not failed, "out": str(out_root),
        "passed": passed, "failed": failed,
        "checks": RESULTS,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
