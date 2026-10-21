"""R10（Ticket 07）：粗排 gate 的 axis_continuity 与 framing_target 两类 check。

spec §2.2 R10 明确四类 check 缺一不可（shot_sequence / walk_path /
axis_continuity / framing_target）。本文件钉死后两类：

* axis_continuity：跨镜机位不得静默越 180° 轴（复用 ``cinema/axis.py``
  判据，与 ``blockout_sequence`` 同一份，不另抄）；
* framing_target：剧本声明的拍对象（角色/道具）必须落在画面内（复用缺陷 A
  的局部主体框口径）；出画 -> error finding；缺证据 -> unresolved 不猜。
"""

from __future__ import annotations

from block_director.cinema.blockout_report import (
    E_BLOCKOUT_AXIS_FLIP,
    E_BLOCKOUT_FRAMING_TARGET_OFF_SCREEN,
    E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED,
    build_blockout_report,
)
from block_director.cinema.pipeline_gates import coarse_gate


def _manifest(**overrides):
    """两镜双人对话：默认两镜同侧机位（无越轴）。"""
    doc = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "dock_market",
        "primitives": [
            {"id": "char_米迦尔", "kind": "character", "shape": "box",
             "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "size": {"x": 0.5, "y": 0.5, "z": 1.7},
             "color": "#8f8f8f", "z_anchor": "foot",
             "asset_ref": None, "provenance": "plan_intent",
             "source": {"type": "character", "id": "米迦尔"}},
            {"id": "char_伊恩", "kind": "character", "shape": "box",
             "position": {"x": 0.9, "y": 0.0, "z": 0.0},
             "size": {"x": 0.5, "y": 0.5, "z": 1.7},
             "color": "#8f8f8f", "z_anchor": "foot",
             "asset_ref": None, "provenance": "plan_intent",
             "source": {"type": "character", "id": "伊恩"}},
            {"id": "prop_银币", "kind": "prop", "shape": "box",
             "position": {"x": 0.9, "y": 0.5, "z": 1.0},
             "size": {"x": 0.3, "y": 0.3, "z": 0.03},
             "color": "#8f8f8f", "z_anchor": "center",
             "asset_ref": "prop_银币", "provenance": "plan_intent",
             "source": {"type": "prop", "id": "银币"}},
        ],
        "cameras": [
            {"shot_id": "shot_001", "camera_id": "cam_shot_001",
             "position": [0.0, 5.0, 1.6], "target": [0.0, 0.0, 1.0],
             "lens_mm": 35.0, "fov_deg": 54.4, "movements": [],
             "start_frame": 1, "end_frame": 24,
             "provenance": "algorithmic_measurement", "resolved": True},
            {"shot_id": "shot_002", "camera_id": "cam_shot_002",
             "position": [0.0, 5.0, 2.2], "target": [0.0, 0.0, 1.0],
             "lens_mm": 35.0, "fov_deg": 54.4, "movements": [],
             "start_frame": 25, "end_frame": 48,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "shot_table": [
            {"shot_id": "shot_001", "order": 1, "start_frame": 1,
             "end_frame": 24, "camera_id": "cam_shot_001",
             "character_ids": ["米迦尔", "伊恩"], "prop_ids": ["银币"],
             "transition_overlap_frames": 0,
             "enter_exit": {"enter": [], "exit": []},
             "downstream_map": {"reference_video": "shot_001.mp4"}},
            {"shot_id": "shot_002", "order": 2, "start_frame": 25,
             "end_frame": 48, "camera_id": "cam_shot_002",
             "character_ids": ["米迦尔", "伊恩"], "prop_ids": [],
             "transition_overlap_frames": 0,
             "enter_exit": {"enter": [], "exit": []},
             "downstream_map": {"reference_video": "shot_002.mp4"}},
        ],
        "asset_registry": [],
        "scene_prop_ids": [],
        "checkpoints": [],
        "notes": [],
        "routes": [],
    }
    doc.update(overrides)
    return doc


def _expected(*, framing_target=None):
    return {
        "scene_heading": "第十四街区码头市场",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "双人对话",
             "shot_type": "MS", "duration_frames": 24,
             "characters": ["米迦尔", "伊恩"], "actions": [],
             "framing_target": framing_target},
            {"shot_id": "shot_002", "order": 2, "intent": "反打",
             "shot_type": "MS", "duration_frames": 24,
             "characters": ["米迦尔", "伊恩"], "actions": [],
             "framing_target": None},
        ],
    }


def _report(manifest, expected, per_shot=None):
    if per_shot is None:
        #: R2 空计划漏洞：expected 声明了主体的镜不得以 empty=True 占位
        #: （新判据会把"声明拍对象但场景空"拦下）。声明角色的镜给真实
        #: 渲染数值，计划空镜才允许 empty 豁免。
        per_shot = []
        for row in manifest.get("shot_table") or []:
            shot_id = str(row.get("shot_id") or "")
            exp = next((s for s in expected["shots"]
                        if s["shot_id"] == shot_id), {})
            if exp.get("characters") or exp.get("framing_target"):
                per_shot.append({
                    "shot_id": shot_id,
                    "composition_score": 92.0,
                    "visible_ratio": 1.0,
                    "foreground_occlusion_ratio": 0.0,
                    "max_subject_area_ratio": 0.4,
                    "on_screen_ratio": 0.4,
                    "off_screen": False,
                    "design_diff": {"max_deviation_m": 0.05},
                    "frames": [],
                })
            else:
                per_shot.append({"shot_id": shot_id, "empty": True,
                                 "frames": []})
    return build_blockout_report(
        manifest=manifest, per_shot=per_shot,
        manifest_fingerprint="fp1", expected=expected)


def _check(report, check_id):
    return next(c for c in report["checks"] if c["check_id"] == check_id)


def _findings(report, check_id):
    return [f for f in report["findings"] if f["check_id"] == check_id]


# ---------------------------------------------------------------------------
# axis_continuity

def test_same_side_cameras_pass_axis_continuity():
    report = _report(_manifest(), _expected())
    assert _check(report, "axis_continuity")["verdict"] == "pass"
    assert _findings(report, E_BLOCKOUT_AXIS_FLIP) == []
    assert coarse_gate(report)["passed"] is True


def test_crossed_camera_fails_axis_continuity():
    """对抗：后镜机位跨到轴线另一侧（无中性镜桥接）-> fail。"""
    manifest = _manifest()
    manifest["cameras"][1]["position"] = [0.0, -5.0, 1.6]
    report = _report(manifest, _expected())
    assert _check(report, "axis_continuity")["verdict"] == "fail"
    flipped = _findings(report, E_BLOCKOUT_AXIS_FLIP)
    assert flipped and flipped[0]["severity"] == "error"
    assert coarse_gate(report)["passed"] is False


# ---------------------------------------------------------------------------
# framing_target

def test_declared_prop_target_in_frame_passes():
    """拍对象（银币）投影在画面内 -> pass。"""
    expected = _expected(framing_target={
        "kind": "prop", "ref": "银币", "part": "none"})
    per_shot = [
        {"shot_id": "shot_001", "empty": False,
         "composition_score": 90.0, "visible_ratio": 1.0,
         "on_screen_ratio": 0.5, "foreground_occlusion_ratio": 0.0,
         "max_subject_area_ratio": 0.2, "off_screen": False,
         "frames": [],
         "framing_target": {"kind": "prop", "ref": "银币", "part": "none",
                            "on_screen_ratio": 0.5,
                            "visible_ratio": 1.0,
                            "provenance": "block_projection"}},
        {"shot_id": "shot_002", "empty": False,
         "composition_score": 90.0, "visible_ratio": 1.0,
         "on_screen_ratio": 0.5, "foreground_occlusion_ratio": 0.0,
         "max_subject_area_ratio": 0.2, "off_screen": False,
         "frames": []},
    ]
    report = _report(_manifest(), expected, per_shot)
    assert _check(report, "framing_target")["verdict"] == "pass"
    assert _findings(report, E_BLOCKOUT_FRAMING_TARGET_OFF_SCREEN) == []
    assert coarse_gate(report)["passed"] is True


def test_declared_prop_target_out_of_frame_fails():
    """对抗：拍对象出画 -> error finding，粗排 gate fail。"""
    expected = _expected(framing_target={
        "kind": "prop", "ref": "银币", "part": "none"})
    per_shot = [
        {"shot_id": "shot_001", "empty": False,
         "composition_score": 90.0, "visible_ratio": 1.0,
         "on_screen_ratio": 0.5, "foreground_occlusion_ratio": 0.0,
         "max_subject_area_ratio": 0.2, "off_screen": True,
         "frames": [],
         "framing_target": {"kind": "prop", "ref": "银币", "part": "none",
                            "on_screen_ratio": 0.0,
                            "visible_ratio": 1.0,
                            "provenance": "block_projection"}},
        {"shot_id": "shot_002", "empty": True, "frames": []},
    ]
    report = _report(_manifest(), expected, per_shot)
    assert _check(report, "framing_target")["verdict"] == "fail"
    off = _findings(report, E_BLOCKOUT_FRAMING_TARGET_OFF_SCREEN)
    assert off and off[0]["severity"] == "error"
    assert coarse_gate(report)["passed"] is False


def test_missing_target_evidence_is_unresolved_not_guessed():
    """计划声明拍对象但证据缺失 -> unresolved（不猜通过）。"""
    expected = _expected(framing_target={
        "kind": "prop", "ref": "银币", "part": "none"})
    report = _report(_manifest(), expected)
    assert _check(report, "framing_target")["verdict"] == "unresolved"
    assert _findings(report, E_BLOCKOUT_FRAMING_TARGET_OFF_SCREEN) == []


def test_declared_target_without_evidence_blocks_coarse_gate():
    """声明拍对象但粗排拿不到投影证据：计划与场景脱节，粗排 gate 必须拦下。

    用户红线：粗排验证分镜/路线/拍摄对象必须有效，不得把'声明拍对象却
    无证据'的镜头放行进细排死循环（真跑 full2 四镜 unresolved 仍 approved）。
    """
    expected = _expected(framing_target={
        "kind": "prop", "ref": "银币", "part": "none"})
    report = _report(_manifest(), expected)
    check = _check(report, "framing_target")
    assert check["verdict"] == "unresolved"
    # unresolved 不再是'零阻塞'：粗排 gate 必须因缺少证据而 blocked。
    assert coarse_gate(report)["passed"] is False
    assert _findings(report, E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED)


def test_no_target_declared_passes_with_note():
    """未声明拍对象 -> 不适用，check 记 pass（四类 check 仍齐全）。"""
    report = _report(_manifest(), _expected())
    check = _check(report, "framing_target")
    assert check["verdict"] == "pass"
    assert "未声明" in check["note"]
    assert {c["check_id"] for c in report["checks"]} >= {
        "shot_sequence", "walk_path", "axis_continuity", "framing_target"}
