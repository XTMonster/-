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

from _fixtures import two_shot_plan  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.config import VlmReviewConfig  # noqa: E402
from block_director.contracts.enums import ErrorCode  # noqa: E402
from block_director.contracts.errors import TransportError  # noqa: E402
from block_director.contracts.messages import ChatReply  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    ensure_collections,
)
from block_director.layer3_engine.shot_auditor import BpyShotAuditor  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
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
    return {"ok": (record["status"] == "ok" and record["score"] == 4
                   and record["frames"] == ["first", "middle", "last"]
                   and len(parts) == 3 and before == after
                   and len(files) == 3),
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

    passed = [key for key, value in RESULTS.items() if value.get("ok")]
    failed = [key for key, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
