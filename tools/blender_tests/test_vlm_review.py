"""v1.5 P6-T1：VLM 评审外回路的**引擎侧**落地（需要 Blender）。

纯 Python 半边（rubric / 解析 / 重试 / 跳过）在 `tests/test_vlm_review.py`；
这里验必须开 Blender 才看得见的四件事：

1. `vlm_review.enabled=false` ⇒ `audit()` 的结果与升级前**逐字节相同**
   （没有新键、没有渲染、没有调用）；
2. 打开之后真的渲染**首/中/末三帧**（三张 data URI 进了请求），场景现场
   （当前相机 / 帧 / 输出路径）被还原；
3. 评审判词**不动门**：同一镜的 passed / score / errors 与关着的时候逐字相同；
4. 评委不可用 ⇒ 跳过并记录（`status="skipped"`、`attempts=2`、**没有 score**）；
   `max_shots` 到顶的镜也如实记跳过。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_vlm_review.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
import bmesh  # noqa: E402

from _fixtures import two_shot_plan  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.config import VlmReviewConfig  # noqa: E402
from block_director.contracts.enums import ErrorCode  # noqa: E402
from block_director.contracts.errors import TransportError  # noqa: E402
from block_director.contracts.messages import ChatReply  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    ensure_collections,
)
from block_director.layer3_engine.frustum_sampler import (  # noqa: E402
    SamplingError,
)
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.shot_auditor import BpyShotAuditor  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.settings import reset_config, set_config  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


class MockJudge:
    """假评委：按脚本回话，并记下每一次请求（不联网、不烧额度）。"""

    def __init__(self, script=None) -> None:
        self.script = list(script or [])
        self.calls: list = []

    def chat(self, payload, timeout: float = 120.0) -> ChatReply:
        self.calls.append(payload)
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    scene.render.resolution_percentage = 100
    ensure_collections(scene)
    return scene


def built():
    fresh_scene()
    plan = two_shot_plan()
    build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
    return plan


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _judge_reply(score=4, reason="构图稳"):
    return ChatReply(content=json.dumps({"score": score, "reason": reason},
                                        ensure_ascii=False))


def _enabled_auditor(transport, vlm_review=None, **kwargs):
    config = vlm_review or VlmReviewConfig()
    config.enabled = True
    return BpyShotAuditor(vlm_review=config, vlm_transport=transport, **kwargs)


# --------------------------------------------------------------------------- #
# 1. 缺省关：结果形状与升级前逐字节一致，且一次渲染/调用都没有
# --------------------------------------------------------------------------- #
def t_disabled_review_is_byte_identical():
    built()
    judge = MockJudge([_judge_reply()])
    auditor = BpyShotAuditor()          # 不接 vlm_review，等价于 enabled=False
    result = auditor.audit("shot_001")
    payload = result.to_dict()
    return {"ok": ("vlm_review" not in payload
                   and getattr(result, "vlm_review", None) is None
                   and judge.calls == []
                   and auditor.vlm_enabled is False),
            "keys": sorted(payload),
            "judge_calls": len(judge.calls),
            "enabled": auditor.vlm_enabled}


# --------------------------------------------------------------------------- #
# 2. 打开：真的取到首/中/末三帧，且现场被还原
# --------------------------------------------------------------------------- #
def t_enabled_review_renders_three_frames():
    built()
    judge = MockJudge([_judge_reply(score=4, reason="留白合适")])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = _enabled_auditor(judge, vlm_frame_dir=Path(tmp))
        scene = bpy.context.scene
        before = (getattr(scene.camera, "name", None), int(scene.frame_current),
                  str(scene.render.filepath))
        result = auditor.audit("shot_001")
        after = (getattr(scene.camera, "name", None), int(scene.frame_current),
                 str(scene.render.filepath))
        files = sorted(path.name for path in (Path(tmp) / "vlm_review").glob("*.png"))

    record = result.vlm_review
    parts = [part for part in judge.calls[0].messages[1].content
             if part["type"] == "image_url"]
    grid_files = {f"shot_001_{label}_grid.png"
                  for label in ("first", "middle", "last")}
    return {"ok": (record["status"] == "ok" and record["score"] == 4
                   and record["frames"] == ["first", "middle", "last"]
                   and len(parts) == 3 and before == after
                   and len(files) == 6
                   and grid_files <= set(files)),
            "record": record, "image_parts": len(parts),
            "files": files, "scene_restored": before == after,
            "purpose": str(judge.calls[0].purpose)}


# --------------------------------------------------------------------------- #
# 3. 判词不是门：同一镜的判定字段与关着的时候逐字相同
# --------------------------------------------------------------------------- #
def t_the_review_never_moves_the_gate():
    built()
    plain = BpyShotAuditor().audit("shot_001")
    built()                                    # 同一份计划重建一次，几何确定
    judge = MockJudge([_judge_reply(score=1, reason="很差")])
    with tempfile.TemporaryDirectory() as tmp:
        reviewed = _enabled_auditor(judge, vlm_frame_dir=Path(tmp)).audit("shot_001")
    keys = ("passed", "score", "errors", "warnings", "justification_audit")
    left = {key: plain.to_dict().get(key) for key in keys}
    right = {key: reviewed.to_dict().get(key) for key in keys}
    return {"ok": (left == right and reviewed.vlm_review["score"] == 1
                   and reviewed.passed == plain.passed),
            "off": left, "on": right,
            "review": reviewed.vlm_review}


# --------------------------------------------------------------------------- #
# 4. 评委不可用 ⇒ 跳过并记录；max_shots 到顶也如实记跳过
# --------------------------------------------------------------------------- #
def t_unavailable_judge_is_recorded_as_a_skip():
    built()
    judge = MockJudge([TransportError(ErrorCode.LLM_001, "连接失败: 524"),
                       TransportError(ErrorCode.LLM_001, "连接失败: 429")])
    with tempfile.TemporaryDirectory() as tmp:
        result = _enabled_auditor(judge, vlm_frame_dir=Path(tmp)).audit("shot_001")
    record = result.vlm_review
    return {"ok": (record["status"] == "skipped" and record["attempts"] == 2
                   and "score" not in record and "429" in record["error"]
                   and len(judge.calls) == 2
                   and result.passed is not None),
            "record": record, "judge_calls": len(judge.calls)}


def t_max_shots_caps_the_review_but_records_it():
    built()
    judge = MockJudge([_judge_reply(score=5, reason="很好")])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = _enabled_auditor(judge, vlm_frame_dir=Path(tmp),
                                   vlm_review=_cap_one())
        first = auditor.audit("shot_001")
        second = auditor.audit("shot_002")
        summary = auditor.vlm_summary()
    return {"ok": (first.vlm_review["status"] == "ok"
                   and second.vlm_review["status"] == "skipped"
                   and "max_shots" in second.vlm_review["reason"]
                   and len(judge.calls) == 1
                   and summary["reviewed"] == 1 and summary["skipped"] == 1),
            "first": first.vlm_review, "second": second.vlm_review,
            "summary": summary, "judge_calls": len(judge.calls)}


def _cap_one():
    config = VlmReviewConfig()
    config.enabled = True
    config.max_shots = 1
    return config


# --------------------------------------------------------------------------- #
# 卡 V3：能力探测 / 逐轮记录 / v2 激活 / 事件（新增 check，既有 5 条不动）
# --------------------------------------------------------------------------- #
def _image_refusal():
    """模型拒收图像输入：错误文案命中能力探测闭集（does not support image）。"""
    return TransportError(ErrorCode.LLM_001,
                          "主模型不支持图像输入：does not support image")


def t_vision_capable_false_skips_without_any_call():
    built()
    config = VlmReviewConfig()
    config.enabled = True
    config.vision_capable = "false"
    judge = MockJudge([_judge_reply()])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = BpyShotAuditor(vlm_review=config, vlm_transport=judge,
                                 vlm_frame_dir=Path(tmp))
        result = auditor.audit("shot_001")
    record = result.vlm_review
    return {"ok": (record["status"] == "skipped"
                   and record["reason"]
                   == "主模型不支持图像输入（配置 vision_capable=false）"
                   and record["round"] == 1
                   and judge.calls == []
                   and len(auditor.vlm_history.get("shot_001", ())) == 1),
            "record": record, "judge_calls": len(judge.calls)}


def t_auto_probe_flips_to_cached_false():
    built()
    judge = MockJudge([_image_refusal(), _image_refusal()])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = _enabled_auditor(judge, vlm_frame_dir=Path(tmp))
        first = auditor.audit("shot_001")
        calls_after_first = len(judge.calls)
        second = auditor.audit("shot_002")
    events = [event for event in auditor.vlm_events
              if event.get("kind") == "vlm_capability"]
    return {"ok": (first.vlm_review["status"] == "skipped"
                   and second.vlm_review["status"] == "skipped"
                   and second.vlm_review["reason"]
                   == "主模型不支持图像输入（自动探测）"
                   and calls_after_first == 2
                   and len(judge.calls) == 2
                   and len(events) == 1
                   and events[0]["supports_image"] is False
                   and "does not support image" in events[0]["evidence"]),
            "first": first.vlm_review, "second": second.vlm_review,
            "events": events, "judge_calls": len(judge.calls)}


def t_reviewing_one_shot_twice_bumps_rounds_and_bypasses_max_shots():
    built()
    judge = MockJudge([_judge_reply(score=4, reason="第一轮"),
                       _judge_reply(score=3, reason="第二轮")])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = _enabled_auditor(judge, vlm_frame_dir=Path(tmp),
                                   vlm_review=_cap_one())
        first = auditor.audit("shot_001")
        second = auditor.audit("shot_001")
    rounds = second.vlm_review["rounds"]
    return {"ok": (first.vlm_review["status"] == "ok"
                   and second.vlm_review["status"] == "ok"
                   and first.vlm_review["round"] == 1
                   and second.vlm_review["round"] == 2
                   and len(rounds) == 2
                   and [item["round"] for item in rounds] == [1, 2]
                   and second.vlm_review["disposition"]["status"] == "clear"
                   and len(judge.calls) == 2),
            "first": first.vlm_review, "second": second.vlm_review,
            "judge_calls": len(judge.calls)}


def t_max_rounds_per_shot_caps_the_same_shot():
    built()
    config = VlmReviewConfig()
    config.enabled = True
    config.max_rounds_per_shot = 1
    judge = MockJudge([_judge_reply(score=4, reason="第一轮")])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = BpyShotAuditor(vlm_review=config, vlm_transport=judge,
                                 vlm_frame_dir=Path(tmp))
        first = auditor.audit("shot_001")
        second = auditor.audit("shot_001")
    return {"ok": (first.vlm_review["status"] == "ok"
                   and second.vlm_review["status"] == "skipped"
                   and "max_rounds_per_shot" in second.vlm_review["reason"]
                   and second.vlm_review["round"] == 2
                   and len(judge.calls) == 1),
            "first": first.vlm_review, "second": second.vlm_review,
            "judge_calls": len(judge.calls)}


def t_v2_request_names_subjects_and_tools():
    built()
    judge = MockJudge([_judge_reply()])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = _enabled_auditor(judge, vlm_frame_dir=Path(tmp))
        auditor.audit("shot_001")
    system = judge.calls[0].messages[0].content
    return {"ok": (all(token in system for token in
                       ("char_001", "char_002", "move_camera", "reframe",
                        "emit_shot_draft"))
                   and auditor.vlm_reviews["shot_001"]["schema"]
                   == "vlm-review/v2"),
            "system": system, "record": auditor.vlm_reviews["shot_001"]}


def t_guard_summary_reaches_the_user_message():
    built()
    judge = MockJudge([_judge_reply(), _judge_reply()])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = _enabled_auditor(judge, vlm_frame_dir=Path(tmp))
        auditor.audit("shot_001")
        auditor.audit("shot_002")
    texts = ["\n".join(part["text"] for part in call.messages[1].content
                       if part["type"] == "text")
             for call in judge.calls]
    return {"ok": ("几何测量事实：" in texts[0]
                   and "framing_too_loose" in texts[0]
                   and "char_001" in texts[0] and "char_002" in texts[0]
                   and "edge_clip" in texts[1]
                   and "thirds_deviation" not in texts[1]),
            "shot_001_text": texts[0], "shot_002_text": texts[1]}


# --------------------------------------------------------------------------- #
# 卡 V12：scene_digest 接进评审提示（新增 check，既有 11 条不动）
# --------------------------------------------------------------------------- #
def t_scene_digest_attached_when_guard_sampling_succeeds():
    built()
    result = BpyShotAuditor().audit("shot_001")
    digest = result.scene_digest
    framing_subjects = sorted(
        (digest or {}).get("framing", {}).get("subjects", {}) or {})
    spatial_frames = (digest or {}).get("spatial", {}).get("frames", []) or []
    return {"ok": (digest is not None
                   and "framing" in digest and "spatial" in digest
                   and framing_subjects == ["char_001", "char_002"]
                   and len(spatial_frames) == 3
                   and "scene_digest" in result.to_dict()),
            "framing_subjects": framing_subjects,
            "spatial_frame_count": len(spatial_frames)}


def t_vlm_user_text_carries_the_geometry_facts_section():
    built()
    judge = MockJudge([_judge_reply()])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = _enabled_auditor(judge, vlm_frame_dir=Path(tmp))
        auditor.audit("shot_001")
    text = "\n".join(part["text"] for part in judge.calls[0].messages[1].content
                     if part["type"] == "text")
    return {"ok": ("几何测量事实：" in text
                   and "占画高" in text
                   and "相机 pos=" in text
                   and "char_001" in text and "char_002" in text),
            "text": text}


def t_mesh_visibility_reaches_the_user_message():
    built()
    judge = MockJudge([_judge_reply()])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = _enabled_auditor(judge, vlm_frame_dir=Path(tmp))
        auditor.audit("shot_001")
    text = "\n".join(part["text"] for part in judge.calls[0].messages[1].content
                     if part["type"] == "text")
    return {"ok": ("几何可见性" in text
                   and "可见顶点" in text
                   and "被遮挡面积比" in text
                   and any(part in text for part in ("腿", "躯干", "头"))
                   and "九宫格偏差" in text
                   and "未声明前景遮挡" in text),
            "text": text}

def t_real_occluder_per_part_attribution():
    """真实挡板 → occlusion 告警 → ``evidence["occlusion_by_part"]`` 端到端。

    交接清单第 4 项：面级 per-part 归因只进过 VLM 评委提示，没进结构化
    ``GuardWarning.evidence``。此探针在标准两镜场景里放一块带
    ``bd_sdl_id`` 的道具挡板（相机与角色之间），跑 ``BpyShotAuditor().audit``
    （不接 VLM judge），断言 occlusion 告警的 evidence 里 ``occlusion_by_part``
    非空、至少一个部位带 ``"道具:stall_01"`` 类别归因。
    """
    built()
    mesh = bpy.data.meshes.new("probe_occluder_mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    occluder = bpy.data.objects.new("probe_occluder", mesh)
    bpy.context.scene.collection.objects.link(occluder)
    occluder.location = (0.0, -1.8, 1.3)
    occluder.scale = (1.2, 0.6, 0.5)
    occluder["bd_element_type"] = "prop"
    occluder["bd_sdl_id"] = "stall_01"
    bpy.context.view_layer.update()
    try:
        result = BpyShotAuditor().audit("shot_001")
    finally:
        bpy.data.objects.remove(occluder, do_unlink=True)
        bpy.data.meshes.remove(mesh, do_unlink=True)
    occ = [w for w in (result.guard_warnings or [])
           if w.type == "occlusion"]
    per_part = {}
    for warning in occ:
        per_part.update(warning.evidence.get("occlusion_by_part", {}))
    attributed = {
        part: by_class.get("道具:stall_01", 0.0)
        for part, by_class in per_part.items()
        if isinstance(by_class, dict)}
    return {"ok": (occ
                   and per_part
                   and any(value > 0.0 for value in attributed.values())),
            "occlusion_count": len(occ),
            "occlusion_by_part": per_part,
            "visible_ratios": [
                warning.evidence.get("visible_ratio")
                for warning in occ]}




def t_declared_occlusion_semantics_reaches_the_user_message():
    """计划里 ``rule="occlusion"`` 的声明要变成评委读到的"已声明前景遮挡"。

    这是 af448dd 的缺口：提示词让模型声明刻意前景遮挡，代码却把
    ``occlusion_declared`` 写死为 False，声明通道从未接上。
    """
    plan = built()
    shot = next(item for item in plan.shots if item.shot_id == "shot_001")
    shot.rule_justifications.append(
        {"rule": "occlusion", "action": "follow"})
    judge = MockJudge([_judge_reply()])
    with tempfile.TemporaryDirectory() as tmp:
        auditor = _enabled_auditor(judge, vlm_frame_dir=Path(tmp))
        auditor.audit("shot_001")
    text = "\n".join(part["text"] for part in judge.calls[0].messages[1].content
                     if part["type"] == "text")
    return {"ok": ("几何可见性" in text
                   and "已声明前景遮挡" in text
                   and "未声明前景遮挡" not in text),
            "text": text}


def t_occlusion_evidence_reaches_guard_warning():
    """面级 per-part 遮挡归因要进结构化 ``GuardWarning.evidence``。

    交接清单第 4 项：``mesh_visibility_report.parts[*].occlusion_by_class``
    只进过 VLM 评委提示文本，没有进 ``evidence["occlusion_by_part"]``。
    这里放一个真实遮挡物（带 ``bd_element_type="prop"`` 与
    ``bd_sdl_id``），跑完整 ``audit()``，断言 occlusion 告警的 evidence
    真的带上面级部位归因（``{部位: {类别: 面积比}}``）。
    """
    import bmesh

    built()
    #: 真实几何立方体（空 mesh 无法被 ray_cast 命中——test_frustum_sampler
    #: 的 ``_cube`` 同款做法），放在 char_001 正前方 1.4 m 处，横跨采样点
    #: 射线路径（躯干 3×2 + 头球 3）。
    mesh = bpy.data.meshes.new("occluder_probe_mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    occluder = bpy.data.objects.new("occluder_probe", mesh)
    bpy.context.scene.collection.objects.link(occluder)
    cam_pos = get_context().camera_for("shot_001").matrix_world.translation
    subject_pos = (-0.5, 0.0, 0.0)
    occluder.location = tuple(
        cam_pos[i] + (subject_pos[i] - cam_pos[i]) * 0.7
        for i in range(3))
    occluder.scale = (2.0, 2.0, 1.0)
    occluder["bd_element_type"] = "prop"
    occluder["bd_sdl_id"] = "stall_probe"
    bpy.context.view_layer.update()
    try:
        result = BpyShotAuditor().audit("shot_001")
    finally:
        bpy.data.objects.remove(occluder, do_unlink=True)
    occ = [w for w in (result.guard_warnings or [])
           if getattr(w, "type", "") == "occlusion"]
    if not occ:
        return {"ok": False,
                "reason": "没有 occlusion 告警（遮挡物未生效或阈值未触发）",
                "guard_warnings": [str(w) for w in (result.guard_warnings or [])]}
    evidence = occ[0].evidence
    by_part = evidence.get("occlusion_by_part") or {}
    has_class = any(
        isinstance(v, dict) and v.get("道具:stall_probe", 0.0) > 0.0
        for v in by_part.values())
    return {"ok": (isinstance(by_part, dict) and bool(by_part)
                   and has_class),
            "warning": str(occ[0]),
            "evidence": evidence,
            "occlusion_by_part": by_part}


def t_guard_disabled_means_no_digest():
    from block_director.contracts.config import AppConfig

    config = AppConfig()
    config.guard.enabled = False
    set_config(config)
    try:
        built()
        result = BpyShotAuditor().audit("shot_001")
    finally:
        reset_config()
    payload = result.to_dict()
    return {"ok": (result.scene_digest is None
                   and "scene_digest" not in payload
                   and result.guard_frames_sampled == 0),
            "keys": sorted(payload)}


def t_perspective_lock_leaves_no_digest_and_records_the_error():
    built()
    camera = get_context().camera_for("shot_001")
    camera.data.type = "ORTHO"
    result = BpyShotAuditor().audit("shot_001")
    payload = result.to_dict()
    error = result.guard_sampling_error
    #: 卡 V12 第二个合取「判定字段与改动前相同」：正交相机下 sample_shot 先抛
    #: SamplingError，guard 层对判定零贡献（guard_warnings 为空 ⇒ 不会追加任何
    #: finding、不会翻 passed）。这里把「零贡献」精确钉死，而不是只钉摘要缺失。
    return {"ok": (result.scene_digest is None
                   and "scene_digest" not in payload
                   and isinstance(error, dict)
                   and error.get("code") == "E_GUARD_001"
                   and "PERSP" in error.get("message", "")
                   and result.guard_warnings == []
                   and result.guard_frames_sampled == 0),
            "guard_sampling_error": error,
            "guard_warnings": result.guard_warnings,
            "guard_frames_sampled": result.guard_frames_sampled,
            "keys": sorted(payload)}


def t_spatial_sampling_failure_records_error_without_changing_verdicts():
    import block_director.layer3_engine.shot_auditor as auditor_mod

    built()
    baseline = BpyShotAuditor().audit("shot_001")
    built()                                    # 同一份计划重建一次，几何确定
    original = auditor_mod.sample_spatial

    def boom(shot_id, frames):
        raise SamplingError("空间采样失败（测试注入）")

    auditor_mod.sample_spatial = boom
    try:
        result = BpyShotAuditor().audit("shot_001")
    finally:
        auditor_mod.sample_spatial = original
    verdict_keys = ("passed", "score", "errors", "warnings",
                    "guard_warnings")
    return {"ok": (result.scene_digest is None
                   and isinstance(result.guard_sampling_error, dict)
                   and result.guard_sampling_error.get("code")
                   == "E_GUARD_001"
                   and {key: baseline.to_dict().get(key) for key in verdict_keys}
                   == {key: result.to_dict().get(key) for key in verdict_keys}),
            "baseline_error": baseline.guard_sampling_error,
            "result_error": result.guard_sampling_error}


def main() -> int:
    capture_main_thread()
    check("disabled_review_is_byte_identical", t_disabled_review_is_byte_identical)
    check("enabled_review_renders_three_frames",
          t_enabled_review_renders_three_frames)
    check("the_review_never_moves_the_gate", t_the_review_never_moves_the_gate)
    check("unavailable_judge_is_recorded_as_a_skip",
          t_unavailable_judge_is_recorded_as_a_skip)
    check("max_shots_caps_the_review_but_records_it",
          t_max_shots_caps_the_review_but_records_it)
    check("vision_capable_false_skips_without_any_call",
          t_vision_capable_false_skips_without_any_call)
    check("auto_probe_flips_to_cached_false",
          t_auto_probe_flips_to_cached_false)
    check("reviewing_one_shot_twice_bumps_rounds_and_bypasses_max_shots",
          t_reviewing_one_shot_twice_bumps_rounds_and_bypasses_max_shots)
    check("max_rounds_per_shot_caps_the_same_shot",
          t_max_rounds_per_shot_caps_the_same_shot)
    check("v2_request_names_subjects_and_tools",
          t_v2_request_names_subjects_and_tools)
    check("guard_summary_reaches_the_user_message",
          t_guard_summary_reaches_the_user_message)
    check("scene_digest_attached_when_guard_sampling_succeeds",
          t_scene_digest_attached_when_guard_sampling_succeeds)
    check("vlm_user_text_carries_the_geometry_facts_section",
          t_vlm_user_text_carries_the_geometry_facts_section)
    check("mesh_visibility_reaches_the_user_message",
          t_mesh_visibility_reaches_the_user_message)
    check("declared_occlusion_semantics_reaches_the_user_message",
          t_declared_occlusion_semantics_reaches_the_user_message)
    check("real_occluder_per_part_attribution",
          t_real_occluder_per_part_attribution)
    check("occlusion_evidence_reaches_guard_warning",
          t_occlusion_evidence_reaches_guard_warning)
    check("guard_disabled_means_no_digest",
          t_guard_disabled_means_no_digest)
    check("perspective_lock_leaves_no_digest_and_records_the_error",
          t_perspective_lock_leaves_no_digest_and_records_the_error)
    check("spatial_sampling_failure_records_error_without_changing_verdicts",
          t_spatial_sampling_failure_records_error_without_changing_verdicts)

    passed = [key for key, value in RESULTS.items() if value.get("ok")]
    failed = [key for key, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
