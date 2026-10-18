"""Ticket 07：Blockout 端到端冒烟（真实剧本全链）。

用贵妇码头市场剧本的离线计划 fixture（``fixtures/mock_llm_responses/
plan_lady_market.json`` 若不存在则用内置四镜计划）走完整链：

  理解 -> 设计快照 -> BlockoutManifest -> 体块建场景 -> 低采样 16:9 预览
  -> 数值+视觉自检报告 -> 检查点（全局+分镜）-> 审批冻结 -> 分镜表 ->
  序列回放审查 -> 输出映射

并验证「粗排无硬伤后才进入逐分镜细排」的 gate：硬伤存在时 gate 阻止，
修复/审批后才放行。全部产物落证据目录。Blender 内不做 jsonschema 校验
（生产侧零运行时依赖），产物由本机测试链校验。

运行：blender --background --factory-startup --python tools/blender_tests/test_blockout_e2e_smoke.py -- --out <dir>
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

RESULTS: dict = {}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _plan_dict():
    """四镜贵妇码头市场（确定性离线计划，不调 LLM）。"""
    return {
        "scene_heading": "INT. 第十四街区码头市场 - 白天",
        "continuity_notes": ["贵妇入画，米迦尔/伊恩/偷盗者已在场"],
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "贵妇入画找钱",
             "intent_type": "铺垫", "shot_type": "MLS",
             "duration_frames": 120,
             "characters": ["米迦尔", "伊恩", "贵妇", "偷盗者"],
             "dialogue_ids": [],
             "prompt": "贵妇从画面左缘入画走到围栏桌边",
             "axis_note": "以偷盗者与贵妇连线建立轴线",
             "continuity_in": "开场",
             "actions": [{"type": "enter_from", "start_frame": 1,
                          "end_frame": 20,
                          "params": {"from": [-4.0, 0.0, 0.0]}}],
             "camera": {"side": "front", "lens": 35,
                        "movements": [{"type": "track_right", "amount": 0.5,
                                       "start_frame": 1, "end_frame": 120}]}},
            {"shot_id": "shot_002", "order": 2, "intent": "贵妇近景",
             "intent_type": "推进", "shot_type": "CU",
             "duration_frames": 96,
             "characters": ["贵妇"],
             "dialogue_ids": [],
             "prompt": "贵妇低头看空钱袋，懊恼疑惑",
             "axis_note": "保持轴线同侧",
             "continuity_in": "承接 shot_001 站位",
             "camera": {"side": "front", "lens": 50}},
            {"shot_id": "shot_003", "order": 3, "intent": "伊恩安慰贵妇",
             "intent_type": "推进", "shot_type": "MS",
             "duration_frames": 96,
             "characters": ["贵妇", "伊恩"],
             "dialogue_ids": [],
             "prompt": "过贵妇肩反打伊恩",
             "axis_note": "反打，仍留在轴线同侧",
             "continuity_in": "承接 shot_002 视线方向",
             "camera": {"side": "front", "lens": 35}},
            {"shot_id": "shot_004", "order": 4, "intent": "偷盗者想溜",
             "intent_type": "推进", "shot_type": "MLS",
             "duration_frames": 72,
             "characters": ["米迦尔", "伊恩", "贵妇", "偷盗者"],
             "dialogue_ids": [],
             "prompt": "四人同框，偷盗者朝右缘挪步",
             "axis_note": "保持轴线同侧",
             "continuity_in": "承接 shot_003 站位",
             "camera": {"side": "front", "lens": 35}},
        ],
    }


def _cast() -> dict:
    return {
        "米迦尔": {"position": [-2.0, 0.0, 0.0],
                  "facing": [0.0, 1.0, 0.0]},
        "伊恩": {"position": [-0.5, 0.0, 0.0],
                "facing": [0.0, 1.0, 0.0]},
        "贵妇": {"position": [1.0, -2.0, 0.0],
                "facing": [0.0, 1.0, 0.0]},
        "偷盗者": {"position": [2.5, 0.0, 0.0],
                  "facing": [0.0, -1.0, 0.0]},
    }


def _props(design) -> None:
    """设计快照里的道具由真实剧本声明驱动；这里显式补充市场道具。"""


def run_smoke(out_dir: Path) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.cinema.blockout_approval import (
        append_approval,
        evaluate_gate,
        gate_findings,
        read_approval_records,
        write_shot_table,
    )
    from block_director.cinema.blockout_report import (
        E_BLOCKOUT_EMPTY_WALL,
    )
    from block_director.layer3_engine.blockout_checkpoint import (
        save_blockout_checkpoints,
    )
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )
    from block_director.layer8_delivery.blockout_preview import (
        render_blockout_preview,
    )
    from block_director.layer8_delivery.blockout_sequence import (
        run_blockout_sequence_review,
    )
    from block_director.contracts.blockout import manifest_fingerprint
    from block_director.contracts.plan import Plan
    from block_director.cinema.spatial_design import (
        build_design_snapshot,
    )

    plan = Plan.from_dict(_plan_dict())
    design = build_design_snapshot(
        brief={"environment": []},
        plan=plan,
        cast_positions={name: entry["position"]
                        for name, entry in _cast().items()},
        scene_id="dock_market_lady")
    manifest = build_blockout_manifest(
        design=design, plan=plan, scene_id="dock_market_lady")

    build_blockout_scene(manifest, clear_scene=True)

    checks: dict = {}
    mismatches: list = []

    #: 1. 预览自检
    preview = render_blockout_preview(manifest, out_dir)
    report = preview["report"]
    checks["preview_verdict"] = report["verdict"]
    checks["preview_findings"] = len(report["findings"])
    checks["preview_frames"] = len(preview["previews"])
    if not preview["previews"]:
        mismatches.append("预览未产出渲染帧")

    #: 2. 检查点（全局 + 分镜）
    checkpoint_summary = save_blockout_checkpoints(manifest, out_dir)
    expected_checkpoints = len(manifest["checkpoints"])
    checks["checkpoint_count"] = checkpoint_summary["count"]
    if checkpoint_summary["count"] != expected_checkpoints:
        mismatches.append(
            f"检查点数 {checkpoint_summary['count']} != {expected_checkpoints}")
    for item in checkpoint_summary["checkpoints"]:
        if not Path(item["file"]).exists() or item["bytes"] == 0:
            mismatches.append(f"检查点 {item['id']} 缺失或空")

    #: 3. 审批 + 分镜表
    record1 = append_approval(
        [], manifest, out_dir, checkpoint_id="scene_01_blockout.blend",
        scope="global", shot_id=None, current_state="draft",
        approved_by="blockout-gate")
    record2 = append_approval(
        [record1], manifest, out_dir,
        checkpoint_id="scene_01_blockout.blend", scope="global",
        shot_id=None, current_state=record1["state"],
        approved_by="blockout-gate", target_state="frozen")
    rows = write_shot_table(manifest, out_dir)
    if rows != manifest["shot_table"]:
        mismatches.append("分镜表 JSON 与 manifest 不一致")

    #: 4. gate：真实预览有硬伤时必须阻止；用确定性“修复后报告”验证
    #:    重新审批/放行路径（不改阈值、不吞原始 finding）。
    gate_ok = evaluate_gate(report, read_approval_records(out_dir), manifest)
    checks["gate_ok"] = gate_ok
    if report["verdict"] == "fail" and gate_ok["passed"]:
        mismatches.append("含硬伤的粗排 gate 错误放行")
    if report["verdict"] == "pass" and not gate_ok["passed"]:
        mismatches.append(f"粗排 gate 未放行：{gate_ok['reasons']}")

    repaired_report = {"verdict": "pass", "findings": []}
    repaired_gate = evaluate_gate(
        repaired_report, read_approval_records(out_dir), manifest)
    checks["gate_after_repair"] = repaired_gate
    if not repaired_gate["passed"]:
        mismatches.append("确定性修复后 gate 未放行")

    tampered = json.loads(json.dumps(manifest))
    if tampered["cameras"]:
        tampered["cameras"][0]["position"] = [9.0, 9.0, 9.0]
        gate_bad = evaluate_gate(
            report, read_approval_records(out_dir), tampered)
        checks["gate_blocks_tamper"] = gate_bad
        if gate_bad["passed"]:
            mismatches.append("改机位后 gate 未阻止进入细排")

    #: 5. 序列回放审查 + 映射表
    sequence = run_blockout_sequence_review(manifest, out_dir)
    sequence_review = sequence["review"]
    checks["sequence_dimensions"] = sequence_review["dimensions"]
    checks["sequence_verdict"] = sequence_review["verdict"]
    if not sequence_review["checks"]:
        mismatches.append("序列审查无 checks")

    #: 6. 全类产物非空落盘
    outputs = {
        "preview_report": str(out_dir / "blockout_report.json"),
        "checkpoint_summary":
            str(out_dir / "blockout_checkpoint_summary.json"),
        "approval":
            str(out_dir / "approval" / "blockout-approval.json"),
        "shot_table": str(out_dir / "shot_table.json"),
        "sequence_review": str(out_dir / "sequence_review.json"),
        "mapping": str(out_dir / "mapping.json"),
        "manifest": str(out_dir / "blockout_manifest.json"),
        "design": str(out_dir / "spatial_design_snapshot.json"),
    }
    (out_dir / "blockout_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "spatial_design_snapshot.json").write_text(
        json.dumps(design, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "blockout_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    missing_outputs = [key for key, path in outputs.items()
                       if not Path(path).exists()]
    if missing_outputs:
        mismatches.append(f"产物缺失：{missing_outputs}")
    checks["outputs"] = outputs
    checks["manifest_fingerprint"] = manifest_fingerprint(manifest)

    checks["mismatches"] = mismatches
    return {"ok": not mismatches, "checks": checks, "outputs": outputs}


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261018-blockout-e2e-smoke"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        fresh_scene()
        RESULTS["blockout_e2e_smoke"] = run_smoke(out_dir)
    except Exception as exc:  # noqa: BLE001 - 冒烟归一为结果记录
        RESULTS["blockout_e2e_smoke"] = {
            "ok": False, "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=5),
        }

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
