"""把 OpenAPI 规格与 Python 契约绑死（执行文档 v1.2 §16.5）。

两层校验：
1. schema 的属性名集合 == 数据类字段集合（防字段漂移）。
2. 用 jsonschema 把 Python 对象序列化后的载荷对照 schema 做真实校验
   （防类型 / 枚举 / 必填项漂移）。
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from block_director.contracts.enums import Capability, MessageRole, Purpose, ToolChoice
from block_director.contracts.health import HealthStatus
from block_director.contracts.knowledge import Card
from block_director.contracts.messages import (
    ChatPayload,
    ChatReply,
    FunctionCall,
    Message,
    ToolCall,
    Usage,
)
from block_director.contracts.operations import (
    CancelRequest,
    CancelResponse,
    EmbedRequest,
    EmbedResponse,
    RetrieveRequest,
    RetrieveResponse,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "specs" / "openapi.yaml"

# schema 名 -> Python 数据类
SCHEMA_TO_MODEL = {
    "FunctionCall": FunctionCall,
    "ToolCall": ToolCall,
    "Message": Message,
    "Usage": Usage,
    "ChatRequest": ChatPayload,
    "ChatResponse": ChatReply,
    "Card": Card,
    "HealthResponse": HealthStatus,
    "EmbedRequest": EmbedRequest,
    "EmbedResponse": EmbedResponse,
    "RetrieveRequest": RetrieveRequest,
    "RetrieveResponse": RetrieveResponse,
    "CancelRequest": CancelRequest,
    "CancelResponse": CancelResponse,
}

EXPECTED_PATHS = {"/health", "/v1/chat", "/v1/embed", "/v1/retrieve", "/v1/cancel"}


@pytest.fixture(scope="module")
def spec() -> Dict[str, Any]:
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


def _validator(doc: Dict[str, Any], schema_name: str):
    jsonschema = pytest.importorskip("jsonschema")
    root = {"$ref": f"#/components/schemas/{schema_name}", "components": doc["components"]}
    return jsonschema.Draft202012Validator(root)


def test_spec_declares_all_endpoints(spec):
    assert set(spec["paths"]) == EXPECTED_PATHS


def test_spec_uses_openapi_31(spec):
    assert spec["openapi"].startswith("3.1")
    assert spec["info"]["version"] == "1.3.0"


def test_schema_properties_match_dataclass_fields(spec):
    schemas = spec["components"]["schemas"]
    for name, model in SCHEMA_TO_MODEL.items():
        assert name in schemas, f"OpenAPI 缺少 schema: {name}"
        declared = set(schemas[name].get("properties", {}))
        actual = {f.name for f in fields(model)}
        assert declared == actual, f"{name} 字段漂移: spec={declared} code={actual}"


def test_required_fields_exist_in_properties(spec):
    for name, schema in spec["components"]["schemas"].items():
        required = set(schema.get("required", []))
        assert required <= set(schema.get("properties", {})), \
            f"{name} 的 required 含有未声明字段"


def _sample_payloads() -> Dict[str, Dict[str, Any]]:
    call = ToolCall(id="call_1",
                    function=FunctionCall(name="place_character",
                                          arguments='{"character_id": "char_001"}'))
    return {
        "FunctionCall": call.function.to_dict(),
        "ToolCall": call.to_dict(),
        "Message": Message(role=MessageRole.TOOL, content="ok",
                           tool_call_id="call_1", name="place_character").to_dict(),
        "Usage": Usage(1, 2, 3).to_dict(),
        "ChatRequest": ChatPayload(
            messages=[Message(role=MessageRole.SYSTEM, content="sys")],
            tools=[{"type": "function", "function": {"name": "f"}}],
            tool_choice=ToolChoice.REQUIRED, temperature=0.2,
            purpose=Purpose.REPAIR, max_tokens=512).to_dict(),
        "ChatResponse": ChatReply(content=None, tool_calls=[call],
                                  usage=Usage(1, 1, 2), request_id="r1",
                                  model="gpt-4o", finish_reason="tool_calls").to_dict(),
        "Card": Card(id="axis_001", domain="axis_theory", title="180 度轴线",
                     content="...", keywords=["轴线"], rules=["..."],
                     parameters={"threshold": 180}, examples=["..."],
                     related=["axis_002"], engine_support="implemented",
                     emotion="对峙", tags=["轴线", "越轴"]).to_dict(),
        "HealthResponse": HealthStatus(
            status="ok", version="1.3.0",
            capabilities=[Capability.LLM, Capability.BM25]).to_dict(),
        "EmbedRequest": EmbedRequest(texts=["a", "b"]).to_dict(),
        "EmbedResponse": EmbedResponse(vectors=[[0.1, 0.2], [0.3, 0.4]], dim=2).to_dict(),
        "RetrieveRequest": RetrieveRequest(query="越轴", domain="axis_theory",
                                           top_k=5).to_dict(),
        "RetrieveResponse": RetrieveResponse(cards=[
            Card(id="c1", domain="d", title="t", content="x")]).to_dict(),
        "CancelRequest": CancelRequest(request_id="r1").to_dict(),
        "CancelResponse": CancelResponse(cancelled=True).to_dict(),
    }


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_TO_MODEL))
def test_python_payloads_validate_against_spec(spec, schema_name):
    payload = _sample_payloads()[schema_name]
    validator = _validator(spec, schema_name)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def test_invalid_payload_is_rejected(spec):
    """反向验证：枚举越界必须被 schema 拦下（证明校验确实生效）。"""
    bad = ChatPayload(messages=[]).to_dict()
    bad["tool_choice"] = "sometimes"
    assert list(_validator(spec, "ChatRequest").iter_errors(bad))
