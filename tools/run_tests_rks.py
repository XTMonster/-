"""Aggregate the independent-measurement (RK) verdicts into rks.json.

v1.4 SS B.2 L5: every run of ``tools/run_tests.ps1`` writes
``docs/evidence/<run-id>/rks.json``. Each entry is
``{rk_id, pass, measured, expected, sample_ref}``.

Honesty rule (SS 4.1b): an RK that this suite cannot measure is written with
``"pass": null`` and ``"status": "not_measured"`` -- never as a pass. The
``sample_ref`` column names the probe / contract test that actually measures it
(or the phase that will).

Pure Python, no bpy.

用法::

  python tools/run_tests_rks.py --run-id <id> --evidence-dir <dir> \
      [--checks rk6_no_floating_no_sinking,rk16_crowd_visibility,...]

``--checks`` 是**本轮实际跑过的探针 check 名**（`tools/run_tests.ps1` 从每个
探针的 ``BD_TEST_RESULT`` 里收集 `passed` 数组），另加 pytest 侧的 RK 名
（``RK-11``/``RK-12``/``RK-18``/``RK-19``）。脚本按名字**推导**哪些 RK 被测到
——``measured`` 因此是聚合结果，而不是手填的常量（§B.2 L5 的要求）。
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.utils.console import force_utf8_streams  # noqa: E402


#: rk_id -> (expected, sample_ref). "expected" is the acceptance line from the
#: spec; sample_ref 必须**点名**度量它的探针/用例（§B.2 L5），并且这些路径
#: 必须真的存在——`tests/test_rks_sample_refs.py` 会把它们逐条对拍文件系统，
#: 免得它在实现换文件之后退化成一句"曾经有过的计划"。
RK_TABLE = [
    ("RK-1", "每个启用标签的角色恰好 1 对 BD_Label_*，ink >= 200 px",
     "tools/blender_tests/test_label_layout.py [rk1_one_pair_per_character, "
     "rk1_ink_stroke_and_components]"),
    ("RK-2", "标签配对交叠率 <= 5%",
     "tools/blender_tests/test_label_layout.py [rk2_overlap_and_offsets]"),
    ("RK-3", "对视夹角 <= 35 度，过肩遮挡 >= 5%",
     "tools/blender_tests/test_scene_contract.py [rk3_two_characters_face_each_other, "
     "rk3_over_the_shoulder_occludes_the_background]"),
    ("RK-4", "eye_protrusion in [0.012, 0.020]，左右眼各 >= 1 簇 >= 9 px",
     "tools/blender_tests/test_character_geometry.py [rk4_eyes_render_as_two_clusters, "
     "rk4_input_contract]"),
    ("RK-5", "相邻采样帧标签高度变化率 <= 5%",
     "tools/blender_tests/test_label_layout.py [rk5_label_size_is_continuous]"),
    ("RK-6", "站立 min_z in [-0.02, +0.02]，行走 >= -0.02",
     "tools/blender_tests/test_phase2_motion.py [rk6_no_floating_no_sinking, "
     "rk6_missing_mesh_is_a_failure]"),
    ("RK-7", "声明 / pin 前原始响应 / pin 后计划三方一致",
     "tests/test_dialogue_three_way.py [RK-7]"),
    ("RK-8", "躯干主惯性轴与 +Z 夹角 = 目标倾角 +-3 度",
     "tools/blender_tests/test_phase2_motion.py [rk8_body_tilt_matches_the_registered_angle]"),
    ("RK-9", "operator 路径注入 builder，产物与 CLI 一致",
     "tools/blender_tests/test_operator_end_to_end.py [rk9_operator_path_builds_and_exports]"),
    ("RK-10", "构图门通过率 >= 70%（分母 = 非空且非 ELS/LS）",
     "tools/blender_tests/test_composition_gate.py "
     "[rk10_gate_passes_and_threshold_has_one_source, "
     "rk10_breaking_the_framing_drops_the_rate]"),
    ("RK-11", "声明 N 镜 -> 产出 N 镜；总帧数 == sum(frames_from_seconds)",
     "tests/test_shotlist_render.py [RK-11]"),
    ("RK-12", "重放产物与入库基线逐字段一致，零 LLM 调用",
     "tools/blender_tests/test_replay.py [RK-12]"),
    ("RK-13", "K1-K4 + Q0-Q7 + E1-E3",
     "tools/holdout_score.py + tools/knowledge/quality.py [held-out 已落地；"
     "run_tests.ps1 按它的退出码判 measured；人审 10-15% 仍未做]"),
    ("RK-14", "头球可见比例 >= 99%；neck_gap = 0 +- 0.005",
     "tools/blender_tests/test_character_geometry.py [rk14_head_is_not_occluded]"),
    ("RK-15", "含头部景别上边距 >= 8% 画面高",
     "tools/blender_tests/test_character_geometry.py [rk15_headroom_is_at_least_eight_percent]"),
    ("RK-16", "群众/特效可见性：掩膜内 median|delta| >= 0.05，外侧 < 1/255",
     "tools/blender_tests/test_crowd_vfx.py [rk16_crowd_visibility]"),
    ("RK-17", "同参数两次运镜逐帧差 <= 1e-6",
     "tools/blender_tests/test_camera_motion.py [rk17_camera_determinism]"),
    ("RK-18", "llm_calls <= max(ceiling, formula)；retrieval_calls <= (2+N)*lanes",
     "P9.4 tests/test_budget_gate.py + audit_log.jsonl 逐次计数"),
    ("RK-19", "相邻两镜同角色银幕方向翻转（两镜都显式声明）必须报 R019",
     "P9.4 tests/test_rule_checker_subjects.py"),
]


def build_report(run_id: str, checks: list, failed: list = ()) -> dict:
    measured = measured_rks(checks)
    failed_set = {str(item) for item in failed or ()}
    rks = []
    for rk_id, expected, sample_ref in RK_TABLE:
        hit = rk_id in measured
        bad = rk_id in failed_set
        rks.append({
            "rk_id": rk_id,
            #: 度量到但**没达标**的必须记 False——不能因为"跑过这条探针"就算过。
            "pass": False if bad else (True if hit else None),
            "status": "measured" if hit else "not_measured",
            "measured": bool(hit),
            "expected": expected,
            "sample_ref": sample_ref,
        })
    return {
        "run_id": run_id,
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "note": ("pass=null 表示本轮套件未度量该 RK（不得据此判通过，"
                 "见 v1.4 SS 4.1b 硬规则 1）。"),
        "checks": list(checks),
        "failed_checks": sorted(failed_set),
        "measured_rks": sorted(measured),
        "rks": rks,
    }


def rks_for_check(name: str) -> set:
    """把一个 check 名映射到 RK 编号。

    * ``rk6_xxx`` → ``RK-6``；``rk17_xxx`` → ``RK-17``（探针 check 的命名约定）；
    * ``RK-11`` 这类大写名直接原样认；
    * 其余名字（``bake_creates_keyframes`` 之类）不映射到任何 RK。
    """
    text = str(name or "").strip()
    upper = text.upper()
    if upper.startswith("RK-") and upper[3:].split("_")[0].isdigit():
        return {"RK-" + upper[3:].split("_")[0]}
    lower = text.lower()
    if lower.startswith("rk"):
        digits = ""
        for char in lower[2:]:
            if char.isdigit():
                digits += char
            else:
                break
        if digits:
            return {f"RK-{digits}"}
    return set()


def measured_rks(checks) -> set:
    found = set()
    for name in checks or []:
        found |= rks_for_check(name)
    return found


def parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run_tests_rks")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--evidence-dir", default="")
    parser.add_argument("--checks", default="",
                        help="本轮跑过的 check 名（逗号分隔；含 pytest 侧的 RK 名）")
    parser.add_argument("--failed", default="",
                        help="其中没达标的 check 名（逗号分隔）：它们的 pass 记 False，"
                             "而不是「跑过就算过」")
    return parser.parse_args(argv[1:])


def main(argv=None) -> int:
    # `rks.json` 与它的 stdout 副本都带中文；stdout 固定 UTF-8，别让它随控制台变
    # （见 block_director/utils/console.py 的实测记录）。
    force_utf8_streams()
    args = parse_args(argv or sys.argv)
    checks = [item.strip() for item in str(args.checks).split(",") if item.strip()]
    failed = [item.strip() for item in str(args.failed).split(",") if item.strip()]
    report = build_report(args.run_id, checks, failed)
    if args.evidence_dir:
        target = Path(args.evidence_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "rks.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
