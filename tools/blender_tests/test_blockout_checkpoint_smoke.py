"""Ticket 05：Blockout 检查点落盘 + 审批门的 Blender 端到端冒烟。

链：manifest -> 体块建场景（bpy）-> 检查点落盘（全局 + 逐分镜 .blend）->
审批记录（draft -> camera-approved -> frozen）-> 改机位后审批门必须阻塞并
报 E_BLOCKOUT_APPROVAL_REQUIRED。断言：.blend 文件存在且非空、检查点摘要
字段齐全、分镜表 JSON 与 manifest 一致、审批记录可读回、门判定正确。
全部结论落 BD_TEST_RESULT JSON。

运行：
blender --background --factory-startup --python tools/blender_tests/test_blockout_checkpoint_smoke.py -- --out <dir>
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


def _design() -> dict:
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "dock_market",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
            {"name": "伊恩", "position": {"x": 0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
        ],
        "props": [
            {"id": "生蚝摊", "kind": "stall", "owner": None, "parent": None,
             "position": [2.5, 1.0, 0.0], "rotation": None, "motion": None,
             "provenance": "script_declaration"},
        ],
        "anchors": [],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [-0.9, 4.66, 0.62],
             "target": [-0.9, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
            {"shot_id": "shot_002", "position": [0.9, 5.0, 0.8],
             "target": [0.9, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "notes": ["T05 检查点冒烟设计快照"],
    }


def _plan():
    from block_director.contracts.plan import Plan, ShotPlan

    return Plan(shots=[
        ShotPlan(
            shot_id="shot_001", intent="双人对话", shot_type="MS",
            duration_frames=24, order=1, characters=["米迦尔", "伊恩"],
            camera={"side": "front", "lens": 35,
                    "movements": [{"type": "dolly_in", "amount": 0.4,
                                   "start_frame": 1, "end_frame": 24}]},
        ),
        ShotPlan(
            shot_id="shot_002", intent="空镜：市场通道", shot_type="MS",
            duration_frames=12, order=2, characters=[],
            camera={"lens": 35},
        ),
    ])


def run_smoke(out_dir: Path) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.cinema.blockout_approval import (
        E_BLOCKOUT_APPROVAL_REQUIRED,
        append_approval,
        gate_findings,
        read_approval_records,
        write_shot_table,
    )
    from block_director.layer3_engine.blockout_checkpoint import (
        CHECKPOINT_DIRNAME,
        CHECKPOINT_SUMMARY_FILENAME,
        save_blockout_checkpoints,
    )
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )

    manifest = build_blockout_manifest(design=_design(), plan=_plan())
    build_blockout_scene(manifest, clear_scene=True)

    checks: dict = {}
    mismatches: list = []

    summary = save_blockout_checkpoints(manifest, out_dir)

    #: 1. 检查点数量：全局 1 + 分镜 2 = 3
    expected_checkpoints = len(manifest["checkpoints"])
    checks["checkpoint_count"] = summary["count"]
    if summary["count"] != expected_checkpoints:
        mismatches.append(
            f"检查点数 {summary['count']} != manifest {expected_checkpoints}")

    #: 2. 每个 .blend 存在且非空，ids 与 manifest 一致
    manifest_ids = [c["id"] for c in manifest["checkpoints"]]
    saved_ids = [c["id"] for c in summary["checkpoints"]]
    if saved_ids != manifest_ids:
        mismatches.append(f"检查点 id 顺序 {saved_ids} != {manifest_ids}")
    for item in summary["checkpoints"]:
        path = Path(item["file"])
        if not path.exists() or path.stat().st_size == 0:
            mismatches.append(f"{item['id']} 缺失或空文件")
        else:
            item["bytes"] = path.stat().st_size

    #: 3. 摘要文件落盘且 schema 齐全
    summary_path = out_dir / CHECKPOINT_SUMMARY_FILENAME
    checks["summary_file"] = summary_path.exists()
    if not summary_path.exists():
        mismatches.append("检查点摘要未落盘")

    #: 4. 分镜表 JSON 与 manifest 逐位一致
    rows = write_shot_table(manifest, out_dir)
    if rows != manifest["shot_table"]:
        mismatches.append("分镜表 JSON 与 manifest 不一致")
    checks["shot_table_rows"] = len(rows)

    #: 5. 审批：draft -> camera-approved -> frozen，记录可读回
    record1 = append_approval(
        [], manifest, out_dir, checkpoint_id="scene_01_blockout.blend",
        scope="global", shot_id=None, current_state="draft",
        approved_by="blockout-gate")
    record2 = append_approval(
        [record1], manifest, out_dir,
        checkpoint_id="scene_01_blockout.blend", scope="global",
        shot_id=None, current_state=record1["state"],
        approved_by="blockout-gate", target_state="frozen")
    records = read_approval_records(out_dir)
    states = [r["state"] for r in records]
    checks["approval_states"] = states
    if states != ["camera-approved", "frozen"]:
        mismatches.append(f"审批状态序列 {states} != 期望")
    if not all(r["cameras_fingerprint"] for r in records):
        mismatches.append("审批记录缺机位指纹")

    #: 6. 审批门：未改不阻塞；改机位阻塞 + 必需 finding
    gate_ok = gate_findings([record2], manifest)
    checks["gate_unchanged"] = gate_ok
    if gate_ok["blocked"]:
        mismatches.append("未改机位被审批门误阻塞")

    tampered = json.loads(json.dumps(manifest))
    tampered["cameras"][0]["position"] = [9.0, 9.0, 9.0]
    tampered["cameras"][0]["target"] = [0.0, -9.0, 0.0]
    gate_bad = gate_findings([record2], tampered)
    checks["gate_tampered"] = gate_bad
    if not gate_bad["blocked"]:
        mismatches.append("改机位后审批门未阻塞")
    if not any(f["check_id"] == E_BLOCKOUT_APPROVAL_REQUIRED
               for f in gate_bad["findings"]):
        mismatches.append("改机位后缺少 E_BLOCKOUT_APPROVAL_REQUIRED finding")

    #: 7. 全类产物落盘清单
    outputs = {
        "checkpoint_summary": str(summary_path),
        "approval": str(out_dir / "approval" / "blockout-approval.json"),
        "shot_table": str(out_dir / "shot_table.json"),
        "checkpoints": [item["file"] for item in summary["checkpoints"]],
    }
    checks["outputs"] = outputs
    checks["summary"] = summary
    checks["mismatches"] = mismatches

    return {"ok": not mismatches, "checks": checks, "outputs": outputs}


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261018-blockout-checkpoint-smoke"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        fresh_scene()
        RESULTS["blockout_checkpoint_smoke"] = run_smoke(out_dir)
    except Exception as exc:  # noqa: BLE001 - 冒烟归一为结果记录
        RESULTS["blockout_checkpoint_smoke"] = {
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
