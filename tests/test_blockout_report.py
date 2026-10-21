"""Ticket 04：Blockout 自检报告生成器（纯层，不 import bpy）。

钉死：逐镜数值证据 -> 版本化 BlockoutReport；判定语义（composition > 80
pass / 可见比例与画面占比阈值 / 空墙 finding）；错误 finding -> verdict fail；
同一输入两次构建逐位一致；报告过 Ticket 02 的 report Schema。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import jsonschema

from block_director.cinema.blockout_report import (
    BLOCKOUT_REPORT_SCHEMA,
    COMPOSITION_PASS,
    E_BLOCKOUT_EMPTY_WALL,
    E_BLOCKOUT_FRAMING_TARGET_OCCLUDED,
    E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH,
    build_blockout_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _report_schema() -> dict:
    path = (ROOT / "block_director" / "contracts" / "blockout" / "schema"
            / "blockout-report.v1.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_shot() -> dict:
    return {
        "shot_id": "shot_001",
        "composition_score": 92.0,
        "visible_ratio": 1.0,
        "foreground_occlusion_ratio": 0.0,
        "max_subject_area_ratio": 0.4,
        "on_screen_ratio": 0.4,
        "off_screen": False,
        "design_diff": {"max_deviation_m": 0.05},
        "frames": [{"frame": 1, "png": "preview/shot_001_f001.png"}],
    }


def _report(per_shot=None, notes=None):
    return build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=per_shot if per_shot is not None else [_clean_shot()],
        manifest_fingerprint="abc123",
        notes=notes)


def test_module_is_pure_no_bpy():
    source = ROOT / "block_director" / "cinema" / "blockout_report.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("bpy" in (alias.name or "") for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert "bpy" not in (node.module or "")


def test_clean_shot_passes_schema_and_verdict():
    report = _report()
    assert report["schema_version"] == BLOCKOUT_REPORT_SCHEMA
    assert report["verdict"] == "pass"
    jsonschema.validate(instance=report, schema=_report_schema())


def test_occlusion_low_produces_empty_wall_finding_and_fail():
    shot = _clean_shot()
    shot["visible_ratio"] = 0.1
    report = _report([shot])
    assert report["verdict"] == "fail"
    empty = [f for f in report["findings"]
             if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert empty and empty[0]["severity"] == "error"
    occlusion = [c for c in report["checks"] if c["check_id"] == "occlusion"]
    assert occlusion and occlusion[0]["verdict"] == "fail"


def test_foreground_occlusion_is_hard_error_even_with_high_composition():
    shot = _clean_shot()
    shot["foreground_occlusion_ratio"] = 0.75
    report = _report([shot])
    check = [c for c in report["checks"]
             if c["check_id"] == "foreground_occlusion"]
    finding = [f for f in report["findings"]
               if f["check_id"] == "E_FOREGROUND_OCCLUSION"]
    assert check and check[0]["verdict"] == "fail"
    assert finding and finding[0]["severity"] == "error"
    assert report["verdict"] == "fail"


def test_low_on_screen_ratio_produces_empty_wall_finding():
    shot = _clean_shot()
    shot["on_screen_ratio"] = 0.01
    report = _report([shot])
    empty = [f for f in report["findings"]
             if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert empty


def test_off_screen_warning_and_no_error():
    shot = _clean_shot()
    shot["off_screen"] = True
    report = _report([shot])
    warn = [f for f in report["findings"] if f["check_id"] == "off_screen"]
    assert warn and warn[0]["severity"] == "warning"
    assert report["verdict"] == "pass"  # warning 不推翻 verdict


def test_off_screen_with_low_on_screen_is_empty_wall_error():
    """完全出画 + 画面占比近零 = 相机对空墙（硬伤），不降级为 warning。"""
    shot = _clean_shot()
    shot["off_screen"] = True
    shot["on_screen_ratio"] = 0.01
    report = _report([shot])
    empty = [f for f in report["findings"]
             if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert empty and empty[0]["severity"] == "error"
    assert report["verdict"] == "fail"


def test_empty_shot_is_exempt_and_pass():
    """空镜合法：无主体 -> 空镜豁免 pass，不报空墙，不因无证据误判 fail。"""
    shot = {
        "shot_id": "shot_empty",
        "empty": True,
        "frames": [{"frame": 1, "png": "preview/shot_empty_f0001.png"}],
    }
    report = _report([shot])
    empty_check = [c for c in report["checks"]
                   if c["check_id"] == "empty_shot"]
    assert empty_check and empty_check[0]["verdict"] == "pass"
    assert not [f for f in report["findings"]
                if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert report["verdict"] == "pass"
    jsonschema.validate(instance=report, schema=_report_schema())


def test_declared_subject_shot_that_renders_empty_is_not_exempt():
    """计划声明拍对象但场景无体块 -> 空镜豁免不适用，必须出 error finding。

    R2 空计划漏洞（final5）：模型计划 framing_target=金弹 / characters=[]，
    白模场景没有任何主体，粗排预览把该镜判 ``empty`` -> 若走空镜豁免，
    脱轨计划零 finding 通过粗排门。修复：只要 expected（plan）侧声明了
    拍对象（角色或道具），``empty`` 就不再豁免，记 E_BLOCKOUT_EMPTY_WALL。
    """
    shot = {
        "shot_id": "shot_002",
        "empty": True,
        "frames": [{"frame": 1, "png": "preview/shot_002_f0001.png"}],
    }
    expected = {
        "shots": [{
            "shot_id": "shot_002", "characters": [],
            "framing_target": {"kind": "prop", "ref": "金弹", "part": "none"},
        }],
    }
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot], manifest_fingerprint="abc123", expected=expected)
    empty_wall = [f for f in report["findings"]
                  if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert empty_wall and empty_wall[0]["severity"] == "error"
    exempt = [c for c in report["checks"] if c["check_id"] == "empty_shot"]
    assert not exempt, "声明拍对象的镜不得走空镜豁免"
    declared = [c for c in report["checks"]
                if c["check_id"] == "declared_subject_empty"]
    assert declared and declared[0]["verdict"] == "fail"
    assert report["verdict"] == "fail"


def test_declared_role_shot_that_renders_empty_is_not_exempt():
    """expected 侧声明角色但场景空 -> 同样不得空镜豁免。"""
    shot = {
        "shot_id": "shot_001",
        "empty": True,
        "frames": [{"frame": 1, "png": "preview/shot_001_f0001.png"}],
    }
    expected = {
        "shots": [{"shot_id": "shot_001", "characters": ["米迦尔"],
                   "framing_target": None}],
    }
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot], manifest_fingerprint="abc123", expected=expected)
    empty_wall = [f for f in report["findings"]
                  if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert empty_wall and empty_wall[0]["severity"] == "error"
    assert report["verdict"] == "fail"


def test_missing_values_are_unresolved_not_guessed():
    shot = _clean_shot()
    shot["visible_ratio"] = None
    shot["on_screen_ratio"] = None
    shot["composition_score"] = None
    report = _report([shot])
    unresolved = [c for c in report["checks"] if c["verdict"] == "unresolved"]
    assert len(unresolved) >= 3


def test_two_builds_are_byte_identical():
    first = json.dumps(_report(), ensure_ascii=False, sort_keys=True)
    second = json.dumps(_report(), ensure_ascii=False, sort_keys=True)
    assert first == second


def test_composition_threshold_reads_from_single_source():
    assert COMPOSITION_PASS == 80.0


def test_composition_exactly_at_threshold_is_reported_as_fail():
    """粗排报告与运行门槛同源：80.0 不算过，82.0 才过。"""
    shot = _clean_shot()
    shot["composition_score"] = 80.0
    exact = _report([shot])
    check = next(c for c in exact["checks"]
                 if c["check_id"] == "composition")
    assert check["verdict"] == "fail"

    shot["composition_score"] = 82.0
    above = _report([shot])
    check = next(c for c in above["checks"]
                 if c["check_id"] == "composition")
    assert check["verdict"] == "pass"


def _skip_expected(responsibility: dict) -> dict:
    """带分工声明的 plan（dict 形状，与真实 emit_plan 同源）。"""
    return {
        "scene_heading": "港口市场",
        "shots": [{
            "shot_id": "shot_001", "order": 1, "intent": "银币特写",
            "shot_type": "CU", "duration_frames": 48,
            "characters": ["米迦尔"], "actions": [],
            "responsibility": responsibility,
            "framing_target": {"kind": "prop", "ref": "银币",
                               "part": "none", "anchor_offset": None},
        }],
    }


def test_skip_white_model_exempts_empty_wall_and_area_findings():
    """C：J3 语义——skip_white_model 镜不产白模主体，空墙/面积/拍物无投影
    三类硬伤 finding 不得用同一把尺硬报；证据 check 仍照常记录数值。"""
    shot = _clean_shot()
    shot["visible_ratio"] = 0.1
    shot["on_screen_ratio"] = 0.01
    shot["max_subject_area_ratio"] = 0.8
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_skip",
        expected=_skip_expected({
            "white_model": [], "prompt": ["分镜师"],
            "ref_image": ["美术组"], "skip_white_model": True,
        }))
    hard = [f for f in report["findings"]
            if f["check_id"] in (
                E_BLOCKOUT_EMPTY_WALL,
                "E_SUBJECT_AREA_OVERFLOW",
                "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED")]
    assert not hard, f"skip 镜不应报主体类硬伤 finding，实际 {hard}"
    #: 数值证据仍在 checks 里（不猜、不隐瞒）
    by_id = {c["check_id"]: c for c in report["checks"]}
    assert by_id["occlusion"]["actual"] == 0.1
    assert by_id["on_screen"]["actual"] == 0.01
    assert by_id["subject_area"]["verdict"] == "fail"
    #: 豁免原因显式留痕
    skip_check = [c for c in report["checks"]
                  if c["check_id"] == "skip_white_model"]
    assert skip_check and skip_check[0]["verdict"] == "pass"
    assert "豁免" in skip_check[0]["note"]


def test_non_skip_shot_still_reports_empty_wall_findings():
    """守卫：skip_white_model=false（或未声明）时三类硬伤照旧报，防过宽豁免。

    R2 修正（final16）：拍对象为道具/局部部位的镜按取景意图豁免空墙
    （与 subject_area 同语义）；本守卫改用**整身角色拍对象**（part=none）
    验证豁免不过宽——整身镜的可见比/出画占比仍是空墙硬伤。
    """
    shot = _clean_shot()
    shot["visible_ratio"] = 0.1
    shot["on_screen_ratio"] = 0.01
    shot["max_subject_area_ratio"] = 0.8
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_noskip",
        expected={
            "scene_heading": "港口市场",
            "shots": [{
                "shot_id": "shot_001", "order": 1, "intent": "中景",
                "shot_type": "MS", "duration_frames": 48,
                "characters": ["米迦尔"], "actions": [],
                "responsibility": {
                    "white_model": ["位置", "机位"], "prompt": [],
                    "ref_image": [], "skip_white_model": False,
                },
                "framing_target": {"kind": "character", "ref": "米迦尔",
                                   "part": "none"},
            }],
        })
    hard = [f for f in report["findings"]
            if f["check_id"] in (
                E_BLOCKOUT_EMPTY_WALL,
                "E_SUBJECT_AREA_OVERFLOW")]
    assert len(hard) >= 2, f"非 skip 镜必须照报硬伤，实际 {hard}"


def test_prop_framing_target_intent_exempts_subject_area_overflow():
    """R2：拍对象为道具（银币特写）时面积判据豁免 overflow finding。

    ECU 拍银币＝银币填满画面是取景意图，不是"白模关系不可读"；数值照记
    check，但不得产生 E_SUBJECT_AREA_OVERFLOW 硬伤（旧实现把合法道具特写
    报成面积溢出，粗排 gate 因此阻塞、白模视频不产出）。
    """
    shot = _clean_shot()
    shot["max_subject_area_ratio"] = 0.95
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_prop_intent",
        expected={
            "scene_heading": "港口市场",
            "shots": [{
                "shot_id": "shot_001", "order": 1, "intent": "银币特写",
                "shot_type": "ECU", "duration_frames": 48,
                "characters": ["偷盗者"], "actions": [],
                "framing_target": {"kind": "prop", "ref": "银币",
                                   "part": "none"},
            }],
        })
    overflow = [f for f in report["findings"]
                if f["check_id"] == "E_SUBJECT_AREA_OVERFLOW"]
    assert not overflow, f"道具拍对象镜不应报面积溢出，实际 {overflow}"
    by_id = {c["check_id"]: c for c in report["checks"]}
    assert by_id["subject_area"]["actual"] == 0.95
    #: verdict 照判 fail（数值照记不隐瞒），豁免的只是硬伤 finding
    assert by_id["subject_area"]["verdict"] == "fail"
    assert "取景意图" in by_id["subject_area"].get("note", "")


def test_character_part_framing_target_intent_exempts_area_overflow():
    """R2：拍对象为局部部位（手部特写）同样豁免面积溢出，语义与道具一致。"""
    shot = _clean_shot()
    shot["max_subject_area_ratio"] = 0.9
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_hand_intent",
        expected={
            "scene_heading": "港口市场",
            "shots": [{
                "shot_id": "shot_001", "order": 1, "intent": "打响指",
                "shot_type": "CU", "duration_frames": 48,
                "characters": ["米迦尔"], "actions": [],
                "framing_target": {"kind": "character", "ref": "米迦尔",
                                   "part": "hand"},
            }],
        })
    overflow = [f for f in report["findings"]
                if f["check_id"] == "E_SUBJECT_AREA_OVERFLOW"]
    assert not overflow, f"局部拍对象镜不应报面积溢出，实际 {overflow}"
    by_id = {c["check_id"]: c for c in report["checks"]}
    assert by_id["subject_area"]["verdict"] == "fail"


def test_whole_body_framing_target_keeps_area_overflow_hard_gate():
    """守卫：整身角色拍对象（part=none）不豁免，面积溢出照旧硬伤防过宽。"""
    shot = _clean_shot()
    shot["max_subject_area_ratio"] = 0.9
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_body_intent",
        expected={
            "scene_heading": "港口市场",
            "shots": [{
                "shot_id": "shot_001", "order": 1, "intent": "中景",
                "shot_type": "MS", "duration_frames": 48,
                "characters": ["米迦尔"], "actions": [],
                "framing_target": {"kind": "character", "ref": "米迦尔",
                                   "part": "none"},
            }],
        })
    overflow = [f for f in report["findings"]
                if f["check_id"] == "E_SUBJECT_AREA_OVERFLOW"]
    assert overflow and overflow[0]["severity"] == "error"


def _intent_expected(shot_id="shot_001", kind="character", part="hand",
                     ref="偷盗者") -> dict:
    """带拍对象声明的 plan 形状（与真实 emit_plan 的 framing_target 同源）。"""
    return {
        "scene_heading": "港口市场",
        "shots": [{
            "shot_id": shot_id, "order": 1, "intent": "局部特写",
            "shot_type": "CU", "duration_frames": 48,
            "characters": [ref], "actions": [],
            "framing_target": {"kind": kind, "ref": ref, "part": part,
                               "anchor_offset": None},
        }],
    }


def test_local_part_framing_target_exempts_empty_wall_findings():
    """R2：拍对象为角色局部部位（手部特写）时，整身框可见比/出画占比
    不是"空墙"的尺子——粗排用整身 box 采样，局部特写相机贴得近时整身
    大部分出画面/被同帧道具遮挡，错误触发 E_BLOCKOUT_EMPTY_WALL 死循环
    （final16 shot_002/003：coarse_best_score=-133，50 轮 strafe/retarget
    仍不收敛）。语义与 subject_area 豁免一致：数值照记 check、verdict
    照判，但不产生空墙 error finding（不动 VISIBLE_RATIO_MIN 阈值）。
    """
    shot = _clean_shot()
    shot["visible_ratio"] = 0.3333
    shot["on_screen_ratio"] = 0.1341
    shot["max_subject_area_ratio"] = 1.0
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_local_hand",
        expected=_intent_expected(kind="character", part="hand",
                                  ref="偷盗者"))
    empty = [f for f in report["findings"]
             if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert not empty, f"局部拍对象镜不应报空墙硬伤，实际 {empty}"
    by_id = {c["check_id"]: c for c in report["checks"]}
    #: 数值照记、verdict 照判（不猜、不隐瞒）
    assert by_id["occlusion"]["actual"] == 0.3333
    assert by_id["occlusion"]["verdict"] == "fail"
    assert "取景" in by_id["occlusion"].get("note", "") \
        or "豁免" in by_id["occlusion"].get("note", "")
    assert by_id["subject_area"]["verdict"] == "fail"
    #: 报告 verdict 仍如实 fail（check 未全过），但无 error finding
    assert report["verdict"] == "fail"


def test_declared_local_subject_zero_visibility_is_a_hard_error():
    """局部主体在画内不等于真实可见：射线可见比为 0 必须阻塞。

    final16 shot_002 的局部手部投影框构图良好（86.7），但巨块银币把
    相机到手部的射线全部挡住。旧报告的 ``intent_exempt`` 只看整身可见比
    与局部取景意图，不检查局部主体自身可见性，于是“主体完全不可见”仍能
    通过构图门。新判据要求声明拍对象的局部可见比与投影证据同时成立。
    """
    shot = _clean_shot()
    shot["composition_score"] = 86.7
    shot["visible_ratio"] = 0.0
    shot["on_screen_ratio"] = 0.17
    shot["framing_target"] = {
        "kind": "character", "ref": "偷盗者", "part": "hand",
        "on_screen_ratio": 0.17,
        "visible_ratio": 0.0,
        "provenance": "coarse_block_approximation",
    }
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_local_invisible",
        expected=_intent_expected(kind="character", part="hand",
                                  ref="偷盗者"))

    occluded = [f for f in report["findings"]
                if f["check_id"] == E_BLOCKOUT_FRAMING_TARGET_OCCLUDED]
    assert occluded and occluded[0]["severity"] == "error"
    target_check = next(c for c in report["checks"]
                        if c["check_id"] == "framing_target")
    assert target_check["verdict"] == "fail"
    assert target_check["visible_ratio"] == 0.0
    assert report["verdict"] == "fail"


def test_prop_framing_target_exempts_empty_wall_findings():
    """R2：拍对象为道具（银币特写）同样豁免空墙硬伤，语义与局部部位一致。"""
    shot = _clean_shot()
    shot["visible_ratio"] = 0.2
    shot["on_screen_ratio"] = 0.02
    shot["max_subject_area_ratio"] = 0.95
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_prop_empty",
        expected=_intent_expected(kind="prop", part="none", ref="银币"))
    empty = [f for f in report["findings"]
             if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert not empty, f"道具拍对象镜不应报空墙硬伤，实际 {empty}"
    by_id = {c["check_id"]: c for c in report["checks"]}
    assert by_id["occlusion"]["verdict"] == "fail"
    assert by_id["on_screen"]["verdict"] == "fail"
    assert by_id["on_screen"].get("note", "")


def test_whole_body_framing_target_keeps_empty_wall_hard_gate():
    """守卫：整身角色拍对象（part=none）不豁免，空墙硬伤照旧防过宽。"""
    shot = _clean_shot()
    shot["visible_ratio"] = 0.3
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_body_empty",
        expected=_intent_expected(kind="character", part="none"))
    empty = [f for f in report["findings"]
             if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert empty and empty[0]["severity"] == "error"


def test_declared_subject_missing_stays_empty_wall_hard_for_local_part():
    """守卫：豁免只针对"体块在、尺子量错"；拍对象体块根本没建成（空镜）
    仍是真硬伤，局部部位声明不得豁免——防豁免过宽掩盖主体丢失。"""
    shot = {
        "shot_id": "shot_001", "empty": True,
        "frames": [{"frame": 1, "png": "preview/shot_001_f0001.png"}],
    }
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot], manifest_fingerprint="fp_local_missing",
        expected=_intent_expected(kind="character", part="hand"))
    empty = [f for f in report["findings"]
             if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert empty and empty[0]["severity"] == "error"
    assert report["verdict"] == "fail"


def test_skip_white_model_exempts_unresolved_framing_target():
    """拍对象声明但 preview 无投影证据：skip 镜豁免 unresolved，不拦粗排。"""
    shot = {
        "shot_id": "shot_001", "empty": False,
        "composition_score": 90.0, "visible_ratio": 1.0,
        "on_screen_ratio": 0.5, "foreground_occlusion_ratio": 0.0,
        "max_subject_area_ratio": 0.2, "off_screen": False,
        "design_diff": {"max_deviation_m": 0.05},
        "frames": [],
        #: 无 framing_target 投影证据（props 无坐标，preview 不产 block）
    }
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_skip_ft",
        expected=_skip_expected({
            "white_model": [], "prompt": ["分镜师"],
            "ref_image": ["美术组"], "skip_white_model": True,
        }))
    unresolved = [f for f in report["findings"]
                  if f["check_id"] == "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED"]
    assert not unresolved, f"skip 镜不应报拍物无投影，实际 {unresolved}"
    ft = [c for c in report["checks"] if c["check_id"] == "framing_target"]
    assert ft and ft[0]["verdict"] == "pass"
    assert "豁免" in ft[0]["note"]


def test_skip_white_model_exempts_off_screen_framing_target():
    """拍对象投影出画：skip 镜同样豁免（与 unresolved 同一族判据）。"""
    shot = {
        "shot_id": "shot_001", "empty": False,
        "composition_score": 90.0, "visible_ratio": 1.0,
        "on_screen_ratio": 0.5, "foreground_occlusion_ratio": 0.0,
        "max_subject_area_ratio": 0.2, "off_screen": True,
        "design_diff": {"max_deviation_m": 0.05},
        "frames": [],
        "framing_target": {"kind": "prop", "ref": "银币", "part": "none",
                           "on_screen_ratio": 0.0,
                           "provenance": "block_projection"},
    }
    report = build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=[shot],
        manifest_fingerprint="fp_skip_ft_off",
        expected=_skip_expected({
            "white_model": [], "prompt": ["分镜师"],
            "ref_image": ["美术组"], "skip_white_model": True,
        }))
    off = [f for f in report["findings"]
           if f["check_id"] == "E_BLOCKOUT_FRAMING_TARGET_OFF_SCREEN"]
    assert not off, f"skip 镜不应报拍对象出画，实际 {off}"
    ft = [c for c in report["checks"] if c["check_id"] == "framing_target"]
    assert ft and ft[0]["verdict"] == "pass"


def test_shot_scoped_evaluation_ignores_unrendered_manifest_rows():
    manifest = {
        "schema_version": "blockout-manifest/v1",
        "primitives": [],
        "cameras": [
            {
                "shot_id": "shot_001",
                "camera_id": "cam_shot_001",
                "position": [0.0, 5.0, 1.6],
                "target": [0.0, 0.0, 1.0],
                "start_frame": 1,
                "end_frame": 24,
            },
            {
                "shot_id": "shot_002",
                "camera_id": "cam_shot_002",
                "position": [5.0, 0.0, 1.6],
                "target": [0.0, 0.0, 1.0],
                "start_frame": 25,
                "end_frame": 48,
            },
        ],
        "shot_table": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "start_frame": 1,
                "end_frame": 24,
                "character_ids": ["甲"],
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "start_frame": 25,
                "end_frame": 48,
                "character_ids": ["乙"],
            },
        ],
        "routes": [],
    }
    expected = {
        "shots": [{
            "shot_id": "shot_001",
            "order": 1,
            "duration_frames": 24,
            "characters": ["甲"],
        }],
    }

    report = build_blockout_report(
        manifest=manifest,
        per_shot=[_clean_shot()],
        manifest_fingerprint="scoped",
        expected=expected,
    )

    assert not [
        finding for finding in report["findings"]
        if finding["check_id"] == E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH
    ]
    assert not [
        check for check in report["checks"]
        if check.get("shot_id") == "shot_002"
    ]
