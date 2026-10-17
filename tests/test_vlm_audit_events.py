"""卡 V4：审计事件登记（vlm_capability / vlm_review_round）+ trace 图像占位。

R-7：新审计事件类型先登记进 ``contracts/audit.py`` 再用；trace 落盘时消息里的
``data:`` 图像只记占位（mime / 解码字节数 / sha256），不写 base64 明文。
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from block_director.contracts.audit import (
    V16_EVENT_FIELDS,
    missing_event_fields,
    redact_image_parts,
)
from block_director.contracts.messages import (
    ChatPayload,
    ChatReply,
    Message,
    MessageRole,
)
from block_director.layer6_audit.audit_logger import (
    AuditLogger,
    render_messages,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-white-model-frame"
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")
PNG_URI = f"data:image/png;base64,{PNG_B64}"


def image_message(uri: str = PNG_URI) -> dict:
    return {"role": "user",
            "content": [{"type": "text", "text": "第一帧"},
                        {"type": "image_url", "image_url": {"url": uri}}]}


def make_payload() -> ChatPayload:
    return ChatPayload(messages=[
        Message(role=MessageRole.SYSTEM, content="评这个镜头"),
        Message(role=MessageRole.USER, content=[
            {"type": "text", "text": "【first】"},
            {"type": "image_url", "image_url": {"url": PNG_URI}},
        ]),
    ])


def read_trace(tmp_path):
    path = tmp_path / "llm_trace.jsonl"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# 事件登记（R-7）
# --------------------------------------------------------------------------- #
def test_vlm_events_are_registered_with_card_fields():
    assert V16_EVENT_FIELDS["vlm_capability"] == (
        "model", "supports_image", "evidence")
    assert V16_EVENT_FIELDS["vlm_review_round"] == (
        "shot_id", "round", "schema", "raw", "parsed")


def test_missing_event_fields_lists_missing_keys():
    assert missing_event_fields("vlm_capability", {}) == [
        "model", "supports_image", "evidence"]
    assert missing_event_fields("vlm_capability", {"model": "glm-5.3"}) == [
        "supports_image", "evidence"]
    assert missing_event_fields("vlm_capability", {
        "model": "glm-5.3", "supports_image": True, "evidence": {}}) == []
    assert missing_event_fields("vlm_review_round", {}) == [
        "shot_id", "round", "schema", "raw", "parsed"]
    assert missing_event_fields("vlm_review_round", {"shot_id": "s1"}) == [
        "round", "schema", "raw", "parsed"]
    assert missing_event_fields("vlm_review_round", {
        "shot_id": "s1", "round": 1, "schema": "vlm-review/v2",
        "raw": {}, "parsed": {}}) == []


def test_unregistered_event_is_flagged_not_silently_accepted():
    assert missing_event_fields("no_such_vlm_event", {}) == ["<unregistered>"]


# --------------------------------------------------------------------------- #
# 决策树投影 / 方案 B / 数值层 事件登记（per_shot_decision_tree_design §3.6.4 T）
# --------------------------------------------------------------------------- #
def test_tree_projection_events_are_registered_with_card_fields():
    assert V16_EVENT_FIELDS["draft_projected"] == (
        "shot_id", "stage", "records")
    assert V16_EVENT_FIELDS["react_projected"] == (
        "shot_id", "stage", "tool", "records")
    assert V16_EVENT_FIELDS["repair_projected"] == (
        "shot_id", "stage", "tool", "records", "repair_invalid")
    #: 构建/投影异常不得静默放行：未登记会让回放链抛 ReplayError。
    assert V16_EVENT_FIELDS["projection_error"] == (
        "shot_id", "stage", "tool")


def test_per_shot_previz_events_are_registered_with_card_fields():
    assert V16_EVENT_FIELDS["scene_prepared"] == (
        "characters", "cameras", "props", "crowd", "prepared_at")
    assert V16_EVENT_FIELDS["shot_iteration"] == (
        "shot_id", "round", "action", "result", "warnings", "protected")
    assert V16_EVENT_FIELDS["shot_advanced"] == (
        "shot_id", "next_shot_id", "decision_trees_evicted")


def test_opt_events_are_registered_with_card_fields():
    assert V16_EVENT_FIELDS["opt_candidate"] == (
        "shot_id", "round", "stage", "x", "clamped", "value", "reason")
    assert V16_EVENT_FIELDS["opt_result"] == (
        "shot_id", "round", "stage", "x0", "value0", "best_x", "best_value",
        "step_scale", "calls", "method_choice", "method_reason", "method",
        "improved", "refit_by")
    assert V16_EVENT_FIELDS["opt_rejected"] == (
        "shot_id", "key", "attempt", "reason")


def test_shot_version_and_adversarial_events_are_registered():
    assert V16_EVENT_FIELDS["shot_version_saved"] == (
        "shot_id", "version", "reason", "path")
    assert V16_EVENT_FIELDS["shot_version_restored"] == (
        "shot_id", "version", "reason")
    assert V16_EVENT_FIELDS["shot_version_restore_failed"] == (
        "shot_id", "version", "reason")
    assert V16_EVENT_FIELDS["adversarial_review"] == (
        "shot_id", "version", "disposition", "issues", "rationale")


def test_new_tree_events_pass_missing_field_check():
    #: 形状齐备时 missing_event_fields 返回空；缺键时逐键列出。
    assert missing_event_fields("draft_projected", {
        "shot_id": "s1", "stage": "draft", "records": []}) == []
    assert missing_event_fields("draft_projected", {}) == [
        "shot_id", "stage", "records"]
    assert missing_event_fields("scene_prepared", {}) == [
        "characters", "cameras", "props", "crowd", "prepared_at"]
    assert missing_event_fields("opt_result", {}) == [
        "shot_id", "round", "stage", "x0", "value0", "best_x", "best_value",
        "step_scale", "calls", "method_choice", "method_reason", "method",
        "improved", "refit_by"]
    assert missing_event_fields("opt_result", {
        "shot_id": "s1", "round": 1, "stage": "draft", "x0": {"x": 0.0},
        "value0": -1.0, "best_x": {"x": 0.0}, "best_value": -1.0,
        "step_scale": {"x": 1.0}, "calls": 1, "method_choice": "auto",
        "method_reason": "agent 选择", "method": "auto", "improved": False,
        "refit_by": "agent"}) == []


# --------------------------------------------------------------------------- #
# openapi 同步口径（§3.6.4 T 登记顺序）：
# 审计事件不进 sidecar wire 协议 —— openapi 只对拍 contracts 传输层数据类
# （test_openapi_matches_contracts.SCHEMA_TO_MODEL），不在其中声明审计事件。
# 这条断言防止未来有人把审计事件误写进 openapi（wire 协议语义外）。
# --------------------------------------------------------------------------- #
def test_audit_events_are_not_part_of_sidecar_wire_protocol():
    from pathlib import Path
    import yaml
    spec = yaml.safe_load(
        Path(__file__).resolve().parents[1].joinpath(
            "specs", "openapi.yaml").read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    for kind in V16_EVENT_FIELDS:
        assert kind not in schemas, (
            f"{kind} 是审计事件，不应进 sidecar wire 协议 schemas")
# --------------------------------------------------------------------------- #
# redact_image_parts（纯函数）
# --------------------------------------------------------------------------- #
def test_redact_replaces_data_url_with_placeholder():
    messages = [image_message()]
    out = redact_image_parts(messages)
    part = out[0]["content"][1]
    assert part == {
        "type": "image_url",
        "image_url": {
            "redacted": True,
            "mime": "image/png",
            "bytes": len(PNG_BYTES),
            "sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
        },
    }
    # 原对象未变（深拷贝保证）
    assert messages[0]["content"][1]["image_url"]["url"] == PNG_URI


def test_redact_keeps_http_urls_and_text_parts():
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "说明"},
        {"type": "image_url",
         "image_url": {"url": "https://cdn.example/frame.png"}},
        {"type": "image_url",
         "image_url": {"url": "http://cdn.example/frame.jpg"}},
    ]}]
    out = redact_image_parts(messages)
    assert out[0]["content"][0] == {"type": "text", "text": "说明"}
    assert out[0]["content"][1] == messages[0]["content"][1]
    assert out[0]["content"][2] == messages[0]["content"][2]


def test_redact_accepts_message_objects_and_keeps_original():
    message = Message(role=MessageRole.USER, content=[
        {"type": "image_url", "image_url": {"url": PNG_URI}}])
    out = redact_image_parts([message])
    assert isinstance(out[0], Message)
    assert out[0].content[0]["image_url"]["redacted"] is True
    assert message.content[0]["image_url"]["url"] == PNG_URI


def test_redact_string_content_untouched():
    messages = [{"role": "system", "content": "你是导演"}]
    out = redact_image_parts(messages)
    assert out is not messages
    assert out[0]["content"] == "你是导演"


def test_redact_bad_base64_raises_value_error():
    with pytest.raises(ValueError):
        redact_image_parts([image_message("data:image/png;base64,!!!")])
    # 缺 ";base64," 分隔同样无法解码
    with pytest.raises(ValueError):
        redact_image_parts([image_message("data:image/png;base64")])


def test_redact_empty_payload_yields_zero_bytes_and_empty_sha256():
    out = redact_image_parts([image_message("data:image/png;base64,")])
    meta = out[0]["content"][1]["image_url"]
    assert meta == {"redacted": True, "mime": "image/png", "bytes": 0,
                    "sha256": hashlib.sha256(b"").hexdigest()}


def test_redact_keeps_non_dict_parts_and_string_image_url():
    odd = {"role": "user", "content": [
        "bare string part",
        {"type": "image_url",
         "image_url": "data:image/png;base64,AAAA"},
        {"type": "text", "text": "ok"},
    ]}
    out = redact_image_parts([odd])
    assert out[0]["content"][0] == "bare string part"
    assert out[0]["content"][1] == odd["content"][1]


def test_redact_return_value_is_independent_from_input():
    messages = [image_message()]
    out = redact_image_parts(messages)
    out[0]["content"][0]["text"] = "改掉"
    assert messages[0]["content"][0]["text"] == "第一帧"


# --------------------------------------------------------------------------- #
# render_messages 接线 + 端到端落盘
# --------------------------------------------------------------------------- #
def test_render_messages_redacts_data_uris_before_dump():
    rendered = render_messages(make_payload())
    assert rendered[0]["content"] == "评这个镜头"
    dumped = rendered[1]["content"]
    assert "base64," not in dumped
    assert '"redacted": true' in dumped


def test_end_to_end_trace_contains_placeholder_not_base64(tmp_path):
    payload = make_payload()
    audit = AuditLogger(directory=tmp_path)
    audit.log_llm("vlm_review", ChatReply(content="ok"), 1.0, "req_v4",
                  payload=payload)
    raw = (tmp_path / "llm_trace.jsonl").read_text(encoding="utf-8")
    assert "base64," not in raw
    record = read_trace(tmp_path)[0]
    parts = json.loads(record["prompt"][1]["content"])
    assert parts[1]["image_url"] == {
        "redacted": True, "mime": "image/png", "bytes": len(PNG_BYTES),
        "sha256": hashlib.sha256(PNG_BYTES).hexdigest()}
    assert record["truncated"] is False
    # 发给模型的真实请求对象不被改写
    assert payload.messages[1].content[1]["image_url"]["url"] == PNG_URI


def test_end_to_end_redaction_happens_before_truncation(tmp_path):
    audit = AuditLogger(directory=tmp_path, trace_max_chars=50)
    audit.log_llm("vlm_review", ChatReply(content="ok"), 1.0, "req_v4b",
                  payload=make_payload())
    raw = (tmp_path / "llm_trace.jsonl").read_text(encoding="utf-8")
    assert "base64," not in raw
    record = read_trace(tmp_path)[0]
    assert record["truncated"] is True
