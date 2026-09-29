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


#: rk_id -> (expected, sample_ref). "expected" is the acceptance line from the
#: spec; sample_ref names where it is measured (probe / test) or "P<n> pending".
RK_TABLE = [
    ("RK-1", "每个启用标签的角色恰好 1 对 BD_Label_*，ink >= 200 px",
     "P12 tools/blender_tests/test_label_layout.py (pending)"),
    ("RK-2", "标签配对交叠率 <= 5%",
     "P12 tools/blender_tests/test_label_layout.py (pending)"),
    ("RK-3", "对视夹角 <= 35 度，过肩遮挡 >= 5%",
     "P11 tools/blender_tests/test_scene_contract.py (pending)"),
    ("RK-4", "eye_protrusion in [0.012, 0.020]，左右眼各 >= 1 簇 >= 9 px",
     "P10 probe (pending)"),
    ("RK-5", "相邻采样帧标签高度变化率 <= 5%",
     "P12 tools/blender_tests/test_label_layout.py (pending)"),
    ("RK-6", "站立 min_z in [-0.02, +0.02]，行走 >= -0.02",
     "P12 tools/blender_tests/test_phase2_motion.py (pending)"),
    ("RK-7", "声明 / pin 前原始响应 / pin 后计划三方一致",
     "P11 tests (pending)"),
    ("RK-8", "躯干主惯性轴与 +Z 夹角 = 目标倾角 +-3 度",
     "P12 probe (pending)"),
    ("RK-9", "operator 路径注入 builder，产物与 CLI 一致",
     "P9.5 tools/blender_tests/test_operator_end_to_end.py (pending)"),
    ("RK-10", "构图门通过率 >= 70%（分母 = 非空且非 ELS/LS）",
     "P16 (pending)"),
    ("RK-11", "声明 N 镜 -> 产出 N 镜；总帧数 == sum(frames_from_seconds)",
     "P13 tests/test_shotlist_render.py (pending)"),
    ("RK-12", "重放产物与入库基线逐字段一致，零 LLM 调用",
     "P9.4 tools/blender_tests/test_replay.py"),
    ("RK-13", "K1-K4 + Q0-Q7 + E1-E3",
     "P14 (pending)"),
    ("RK-14", "头球可见比例 >= 99%；neck_gap = 0 +- 0.005",
     "P10 probe (pending)"),
    ("RK-15", "含头部景别上边距 >= 8% 画面高",
     "P10 probe (pending)"),
    ("RK-16", "群众/特效可见性：掩膜内 median|delta| >= 0.05，外侧 < 1/255",
     "P12 tools/blender_tests/test_crowd_vfx.py (pending)"),
    ("RK-17", "同参数两次运镜逐帧差 <= 1e-6",
     "P12 tools/blender_tests/test_camera_motion.py (pending)"),
    ("RK-18", "llm_calls <= max(ceiling, formula)；retrieval_calls <= (2+N)*lanes",
     "P9.4 tests/test_budget_gate.py + audit_log.jsonl 逐次计数"),
    ("RK-19", "相邻两镜同角色银幕方向翻转（两镜都显式声明）必须报 R019",
     "P9.4 tests/test_rule_checker_subjects.py"),
]


def build_report(run_id: str, checks: list) -> dict:
    measured = measured_rks(checks)
    rks = []
    for rk_id, expected, sample_ref in RK_TABLE:
        hit = rk_id in measured
        rks.append({
            "rk_id": rk_id,
            "pass": True if hit else None,
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
    return parser.parse_args(argv[1:])


def main(argv=None) -> int:
    args = parse_args(argv or sys.argv)
    checks = [item.strip() for item in str(args.checks).split(",") if item.strip()]
    report = build_report(args.run_id, checks)
    if args.evidence_dir:
        target = Path(args.evidence_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "rks.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
