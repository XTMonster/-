"""契约层：与 Blender 无关的纯 Python 定义，可在 Blender 内外复用。

设计约束（执行文档 v1.2）：
1. 本包**不得** import bpy —— 必须能在系统 Python 与 Blender Python 下同样工作。
2. 本包是"单一真源"：``specs/openapi.yaml`` 中的 schema 必须与本处数据类一致，
   由 ``tests/test_openapi_matches_contracts.py`` 强制校验（§16.5）。
3. 纯标准库实现，零第三方依赖（YAML 解析仅在配置加载时可选用）。
"""

from __future__ import annotations

from .enums import (
    Appearance,
    AuditLevel,
    Capability,
    DeliveryPreset,
    Engine,
    ErrorCode,
    MessageRole,
    OrchestrationMode,
    Purpose,
    RagBackend,
    RenderBackend,
    Severity,
    ShotType,
    SHOT_TYPES,
    ToolChoice,
    TransportMode,
    VideoCodec,
    resolve_engine_identifier,
)
from .errors import TransportError, error_for_http_status, user_message
from .health import HealthStatus
from .knowledge import Card
from .plan import Plan, ShotPlan
from .audit import AuditError, AuditResult
from .cast import CastMember, SceneSpec
from .sdl import (
    SDL_VERSION,
    SDLCamera,
    SDLEnvironment,
    SDLProject,
    SDLScene,
    SDLShot,
)
from .messages import (
    ChatPayload,
    ChatReply,
    FunctionCall,
    Message,
    ToolCall,
    Usage,
    assistant_message,
    tool_message,
    validate_conversation,
)
from .operations import (
    CancelRequest,
    CancelResponse,
    EmbedRequest,
    EmbedResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from .config import (
    AppConfig,
    AnimationConfig,
    AuditConfig,
    BudgetConfig,
    CharacterConfig,
    DeliveryConfig,
    DialogueConfig,
    Issue,
    LLMConfig,
    OrchestrationConfig,
    RagConfig,
    UIConfig,
    default_config_path,
)
from .transport import (
    DirectTransport,
    LLMTransport,
    OpenAICompatibleTransport,
    SidecarTransport,
    build_chat_body,
    parse_chat_response,
    select_transport,
)

__all__ = [
    "Appearance", "AuditLevel", "Capability", "DeliveryPreset", "Engine",
    "ErrorCode", "MessageRole", "OrchestrationMode", "Purpose", "RagBackend",
    "RenderBackend", "Severity", "ToolChoice", "TransportMode", "VideoCodec",
    "ShotType", "SHOT_TYPES",
    "resolve_engine_identifier",
    "TransportError", "error_for_http_status", "user_message",
    "HealthStatus", "Card",
    "Plan", "ShotPlan",
    "AuditError", "AuditResult",
    "CastMember", "SceneSpec",
    "SDLProject", "SDLScene", "SDLShot", "SDLCamera", "SDLEnvironment",
    "SDL_VERSION",
    "ChatPayload", "ChatReply", "FunctionCall", "Message", "ToolCall", "Usage",
    "assistant_message", "tool_message", "validate_conversation",
    "CancelRequest", "CancelResponse", "EmbedRequest", "EmbedResponse",
    "RetrieveRequest", "RetrieveResponse",
    "AppConfig", "AnimationConfig", "AuditConfig", "BudgetConfig",
    "CharacterConfig", "DeliveryConfig", "DialogueConfig", "Issue", "LLMConfig",
    "OrchestrationConfig", "RagConfig", "UIConfig", "default_config_path",
    "LLMTransport", "DirectTransport", "SidecarTransport", "select_transport",
    "OpenAICompatibleTransport", "build_chat_body", "parse_chat_response",
]
