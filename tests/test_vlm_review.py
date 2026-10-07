"""VLM 评审外回路（执行文档 v1.5 §5.5 / 卡 P6-T1）——纯 Python 单测。

判据逐字来自 TDD §5.5 与卡 P6-T1：

* ``vlm_review.enabled=false`` ⇒ **零行为差**（默认关，跑不到评审）；
* 每镜首/中/末帧 + intent + composition 声明 → VLM 1–5 分 + 一句理由；
* 结果**只进 shots.json 与面板**，不参与任何门（不改 passed/score/errors）；
* 评委不可用（超时/429/524）⇒ **跳过该镜并记录**，重试一次后放弃；
* 单测用 mock transport（不联网、不烧额度）。

本文件不依赖 bpy：rubric / 取帧号 / 请求装配 / 响应解析 / 重试策略全在
``block_director/contracts/vlm_review.py``。
"""

from __future__ import annotations

import base64
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.audit import AuditResult  # noqa: E402
from block_director.contracts.config import AppConfig, VlmReviewConfig  # noqa: E402
from block_director.contracts.enums import MessageRole, Purpose, ToolChoice  # noqa: E402
from block_director.contracts.errors import TransportError  # noqa: E402
from block_director.contracts.enums import ErrorCode  # noqa: E402
from block_director.contracts.messages import ChatReply  # noqa: E402
from block_director.contracts.vlm_review import (  # noqa: E402
    FRAME_LABELS,
    REVIEW_RUBRIC,
    REVIEW_SCHEMA_VERSION,
    VlmReviewError,
    build_review_payload,
    frame_data_uri,
    frame_indices,
    parse_review_reply,
    review_shot,
    summarise_reviews,
)

#: 1×1 透明 PNG（67 字节）——只验证编码，不验证画面。
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB"
    "/AGtB6AoAAAAAElFTkSuQmCC")


class MockTransport:
    """按脚本回话的假评委：`script` 里每项要么是 ChatReply，要么是异常类。"""

    def __init__(self, script) -> None:
        self.script = list(script)
        self.calls = []

    def chat(self, payload, timeout: float = 120.0) -> ChatReply:
        self.calls.append(payload)
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def _reply(text: str) -> ChatReply:
    return ChatReply(content=text)


def _frames(n: int = 3):
    return [(label, f"data:image/png;base64,{_PNG_BYTES.hex()}")
            for label in FRAME_LABELS[:n]]


# --------------------------------------------------------------- 默认关 = 零差
def test_vlm_review_is_off_by_default():
    cfg = AppConfig()
    assert isinstance(cfg.vlm_review, VlmReviewConfig)
    assert cfg.vlm_review.enabled is False
    assert cfg.errors() == []


def test_audit_result_without_a_review_has_no_new_key():
    """默认关时审核结果的形状与升级前逐字节一致（NFR-4）。"""
    plain = AuditResult(passed=True, level="rule", score=81.0)
    assert "vlm_review" not in plain.to_dict()
    assert set(plain.to_dict()) == {
        "passed", "level", "target", "score", "errors", "warnings",
        "suggestions"}


def test_a_review_never_touches_the_gate_fields():
    """VLM 判词不是门：挂上去以后 passed/score/errors 一个都不许动。"""
    result = AuditResult(passed=False, level="rule", score=41.0)
    before = {key: result.to_dict()[key]
              for key in ("passed", "score", "errors", "warnings")}
    result.vlm_review = {"status": "ok", "score": 5, "reason": "很好",
                         "attempts": 1, "schema": REVIEW_SCHEMA_VERSION}
    after = {key: result.to_dict()[key]
             for key in ("passed", "score", "errors", "warnings")}
    assert before == after
    assert result.to_dict()["vlm_review"]["score"] == 5


# --------------------------------------------------------------------- 取帧号
def test_frame_indices_picks_first_middle_last():
    assert dict(frame_indices(10, 19)) == {"first": 10, "middle": 14, "last": 19}
    assert dict(frame_indices(1, 48)) == {"first": 1, "middle": 24, "last": 48}


def test_frame_indices_collapses_a_single_frame_shot():
    """单帧镜头只取一张——同一个帧号不许重复渲染两次。"""
    pairs = frame_indices(7, 7)
    assert pairs == [("first", 7)]


def test_frame_indices_is_order_tolerant():
    assert dict(frame_indices(19, 10)) == dict(frame_indices(10, 19))


# ------------------------------------------------------------------- data URI
def test_frame_data_uri_round_trips_the_bytes(tmp_path):
    path = tmp_path / "f.png"
    path.write_bytes(_PNG_BYTES)
    uri = frame_data_uri(path)
    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == _PNG_BYTES


def test_frame_data_uri_marks_jpeg(tmp_path):
    path = tmp_path / "f.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    assert frame_data_uri(path).startswith("data:image/jpeg;base64,")


# ------------------------------------------------------------------ 请求装配
def test_payload_carries_rubric_text_and_every_frame():
    payload = build_review_payload(
        shot_id="shot_007", frames=_frames(), intent="她回头",
        composition={"rule": "lead_room"})
    assert payload.purpose is Purpose.REVIEW
    assert payload.tool_choice is ToolChoice.NONE
    assert payload.temperature == 0.0
    system, user = payload.messages
    assert system.role is MessageRole.SYSTEM
    assert "5." in system.content and REVIEW_RUBRIC[5][:6] in system.content
    assert user.role is MessageRole.USER
    images = [part for part in user.content if part["type"] == "image_url"]
    assert len(images) == 3, "首/中/末三帧一帧都不能少"
    assert "shot_007" in user.content[0]["text"]
    assert "lead_room" in user.content[0]["text"]


def test_empty_frames_are_refused():
    with pytest.raises(VlmReviewError):
        build_review_payload(shot_id="shot_001", frames=[])


def test_vision_payload_validates_against_the_openapi_schema():
    """契约层与规格同批放宽（否则 sidecar 线协议载不动图片）。"""
    yaml = pytest.importorskip("yaml")
    jsonschema = pytest.importorskip("jsonschema")
    spec = yaml.safe_load((ROOT / "specs" / "openapi.yaml").read_text("utf-8"))
    payload = build_review_payload(shot_id="shot_001", frames=_frames(),
                                   intent="建立", composition={}).to_dict()
    root = {"$ref": "#/components/schemas/ChatRequest",
            "components": spec["components"]}
    errors = list(jsonschema.Draft202012Validator(root).iter_errors(payload))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]


# ------------------------------------------------------------------ 响应解析
@pytest.mark.parametrize("text,score", [
    ('{"score": 4, "reason": "构图稳"}', 4),
    ('```json\n{"score": 1, "reason": "主体出画"}\n```', 1),
    ('我认为：{"score": 5, "reason": "有意图"} 完毕', 5),
    ('{"score": 3}', 3),
    ('{"score": 3.0, "reason": "合格"}', 3),
])
def test_parse_review_accepts_well_formed_replies(text, score):
    parsed = parse_review_reply(_reply(text))
    assert parsed["score"] == score
    assert isinstance(parsed["reason"], str)


@pytest.mark.parametrize("text", [
    "",
    "   ",
    "没有 JSON",
    '{"score": 0, "reason": "越界"}',
    '{"score": 6, "reason": "越界"}',
    '{"score": 3.5, "reason": "非整数"}',
    '{"reason": "缺分数"}',
    '{"score": true}',
    '{"score": [3]}',
])
def test_parse_review_rejects_unusable_replies(text):
    with pytest.raises(VlmReviewError):
        parse_review_reply(_reply(text))


# ------------------------------------------------------------------ 重试策略
def test_review_succeeds_on_the_first_try():
    transport = MockTransport([_reply('{"score": 4, "reason": "稳"}')])
    record = review_shot(transport, shot_id="shot_001", frames=_frames())
    assert record["status"] == "ok" and record["score"] == 4
    assert record["attempts"] == 1
    assert record["schema"] == REVIEW_SCHEMA_VERSION
    assert len(transport.calls) == 1


def test_review_retries_once_after_a_transport_error():
    transport = MockTransport([
        TransportError(ErrorCode.LLM_001, "连接失败: 524"),
        _reply('{"score": 2, "reason": "主体压边"}'),
    ])
    record = review_shot(transport, shot_id="shot_002", frames=_frames())
    assert record["status"] == "ok" and record["score"] == 2
    assert record["attempts"] == 2
    assert len(transport.calls) == 2, "恰好重试一次"


def test_review_gives_up_after_the_retry_and_records_the_skip():
    transport = MockTransport([
        TransportError(ErrorCode.LLM_001, "连接失败: 524"),
        TransportError(ErrorCode.LLM_001, "连接失败: 429"),
    ])
    record = review_shot(transport, shot_id="shot_003", frames=_frames())
    assert record["status"] == "skipped"
    assert record["attempts"] == 2
    assert "score" not in record, "跳过不许写成 0 分（那是静默降级）"
    assert "429" in record["error"]
    assert len(transport.calls) == 2


def test_review_without_frames_skips_without_calling_the_judge():
    transport = MockTransport([_reply('{"score": 5, "reason": "不该被调用"}')])
    record = review_shot(transport, shot_id="shot_004", frames=[])
    assert record["status"] == "skipped" and record["attempts"] == 0
    assert transport.calls == []


def test_a_judge_that_only_chats_json_at_us_is_retried_then_skipped():
    """模型回了一堆白话但没有合法 JSON（offline 替身就是这样）⇒ 跳过。"""
    transport = MockTransport([_reply("这一镜整体还行，给 4 分吧")])
    record = review_shot(transport, shot_id="shot_005", frames=_frames())
    assert record["status"] == "skipped"
    assert len(transport.calls) == 2


# ---------------------------------------------------------------------- 汇总
def test_summary_separates_scored_shots_from_skips():
    reviews = {
        "shot_001": {"status": "ok", "score": 4},
        "shot_002": {"status": "ok", "score": 2},
        "shot_003": {"status": "skipped", "reason": "评委不可用"},
    }
    summary = summarise_reviews(reviews)
    assert summary["reviewed"] == 2
    assert summary["skipped"] == 1
    assert summary["skipped_shots"] == ["shot_003"]
    assert summary["mean_score"] == 3.0
    assert summarise_reviews({})["mean_score"] is None


def test_rubric_covers_every_level_of_the_five_point_scale():
    assert sorted(REVIEW_RUBRIC) == [1, 2, 3, 4, 5]
    assert all(text.strip() for text in REVIEW_RUBRIC.values())


def test_manifest_only_grows_the_key_when_a_review_exists():
    """shots.json 的默认形状不许因为"开着这个功能"而变（缺省关零差）。"""
    from block_director.delivery.manifest import build_manifest

    plan = _mini_plan()
    plain = build_manifest(plan)
    assert "vlm_review" not in plain["shots"][0]
    reviewed = build_manifest(plan, build_summary={
        "results": [{"shot_id": "shot_001", "vlm_review": {
            "status": "ok", "score": 5, "reason": "有意图", "attempts": 1}}]})
    assert reviewed["shots"][0]["vlm_review"]["score"] == 5
    stripped = {k: v for k, v in reviewed["shots"][0].items()
                if k != "vlm_review"}
    assert stripped == plain["shots"][0], "除新键外逐字段相同"


def test_manifest_writes_the_skip_verbatim():
    from block_director.delivery.manifest import build_manifest

    manifest = build_manifest(_mini_plan(), build_summary={
        "results": [{"shot_id": "shot_001", "vlm_review": {
            "status": "skipped", "reason": "评委不可用（重试一次后放弃）",
            "error": "TransportError: 524", "attempts": 2}}]})
    entry = manifest["shots"][0]["vlm_review"]
    assert entry["status"] == "skipped"
    assert "score" not in entry
    assert "524" in entry["error"]


def _mini_plan():
    from block_director.contracts.plan import Plan, ShotPlan

    return Plan(shots=[ShotPlan.from_dict({
        "shot_id": "shot_001", "order": 1, "intent": "一镜",
        "shot_type": "MS", "duration_frames": 48,
        "characters": ["char_001"]})], scene_heading="INT. 码头 - 日")
