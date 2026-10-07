"""契约层枚举（执行文档 v1.2 单一真源）。

枚举的 ``value`` 即为 HTTP/JSON 与配置文件中的字面量，改动即破坏兼容性。
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Tuple


class StrEnum(str, Enum):
    """Python 3.11 ``enum.StrEnum`` 的兼容实现（目标运行时含 3.11 与 3.13）。"""

    def __str__(self) -> str:  # pragma: no cover - 便利方法
        return str(self.value)


# --------------------------------------------------------------------------- #
# §2.5 LLM 会话
# --------------------------------------------------------------------------- #
class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Purpose(StrEnum):
    """LLM 调用用途（§3.4 / §7.1 / §12.6 预算按用途分别核算）。"""

    UNDERSTAND = "understand"  # 阶段 S：剧本理解（SceneBrief，v1.3 §3.2）
    PLAN = "plan"        # 阶段 A：分镜计划
    EDITOR = "editor"    # 阶段 B1：单镜结构化生成
    REPAIR = "repair"    # 阶段 B4：定向修复
    REACT = "react"      # 阶段 B5：受限 ReAct
    REVIEW = "review"    # Level 2 self_review（§7.10 异步）


class ToolChoice(StrEnum):
    AUTO = "auto"
    REQUIRED = "required"
    NONE = "none"


# --------------------------------------------------------------------------- #
# §2.4 / §6.1 / §15.3 运行与交付配置
# --------------------------------------------------------------------------- #
class TransportMode(StrEnum):
    AUTO = "auto"        # 按 /health 自动选择（默认）
    DIRECT = "direct"    # 进程内 SDK
    SIDECAR = "sidecar"  # 独立进程 HTTP


class RagBackend(StrEnum):
    HYPERGRAPH = "hypergraph"  # 默认（v1.4 §2.3）：超图 RAG，跑在 sidecar
    BM25 = "bm25"        # sidecar 不可用时的内置兜底（须在 trace 标 degraded）
    VECTOR = "vector"    # 需能力协商通过
    DIGEST = "digest"    # 兜底


class RenderBackend(StrEnum):
    WORKBENCH = "workbench"  # 默认；headless 可用
    EEVEE = "eevee"          # headless 可用；Z Pass（depth）需要它
    VIEWPORT = "viewport"    # OpenGL；仅 GUI（§15.3 实测约束）


class Appearance(StrEnum):
    CLAY = "clay"
    FLAT = "flat"
    COLOR_CODED = "color_coded"


class DeliveryPreset(StrEnum):
    HD16X9 = "hd16x9"
    FHD16X9 = "fhd16x9"
    SQUARE = "square"
    VERTICAL = "vertical"


class VideoCodec(StrEnum):
    H264 = "H264"
    H265 = "H265"
    AV1 = "AV1"
    PRORES = "PRORES"


class CRF(StrEnum):
    NONE = "NONE"
    LOSSLESS = "LOSSLESS"
    PERC_LOSSLESS = "PERC_LOSSLESS"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    VERYLOW = "VERYLOW"


class AuditLevel(StrEnum):
    STRICT = "strict"
    STANDARD = "standard"
    LENIENT = "lenient"


class OrchestrationMode(StrEnum):
    PLAN_STRUCTURED = "plan_structured"  # 默认；§7.1 四段式
    REACT_ONLY = "react_only"            # 兼容 v1.0 行为


class Capability(StrEnum):
    """sidecar ``/health`` 的能力协商标识（§2.5）。"""

    LLM = "llm"
    BM25 = "bm25"
    VECTOR = "vector"
    PDF = "pdf"
    #: v1.4 §2.3：超图检索。只加这一个——L3（案例层）的开/关**只**由
    #: ``rag.cases_backend`` 表达，不再新增 ``lightrag`` 能力位。
    HYPERGRAPH = "hypergraph"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ShotType(StrEnum):
    """九种景别（执行文档 v1.2 §10.5）。"""

    ECU = "ECU"    # 大特写
    CU = "CU"      # 特写
    MCU = "MCU"    # 中近景
    MS = "MS"      # 中景
    MLS = "MLS"    # 中远景
    LS = "LS"      # 全景
    ELS = "ELS"    # 大远景
    OTS = "OTS"    # 过肩
    POV = "POV"    # 主观


SHOT_TYPES = tuple(t.value for t in ShotType)


# --------------------------------------------------------------------------- #
# §10.2 / 附录 B 运镜封闭清单（v1.3）
# --------------------------------------------------------------------------- #
class Movement(StrEnum):
    """24 种运镜的 id。

    **单一真源**：``cinema/camera_motion.py`` 的分组表（平移/旋转/变焦/环绕/
    跟拍/手持）必须与这份清单完全一致，``tests/test_camera_motion.py`` 对拍。
    放在 contracts 是因为知识卡的 ``engine_support``、工具 schema 的 ``enum``
    与 SDL 的 ``movements[].type`` 都要引用同一个词表。
    """

    DOLLY_IN = "dolly_in"
    DOLLY_OUT = "dolly_out"
    TRACK_LEFT = "track_left"
    TRACK_RIGHT = "track_right"
    CRANE_UP = "crane_up"
    CRANE_DOWN = "crane_down"
    PUSH_THROUGH = "push_through"
    DOLLY_ZOOM = "dolly_zoom"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    WHIP_PAN_LEFT = "whip_pan_left"
    WHIP_PAN_RIGHT = "whip_pan_right"
    ORBIT_CW = "orbit_cw"
    ORBIT_CCW = "orbit_ccw"
    CRANE_ARC_UP = "crane_arc_up"
    CRANE_ARC_DOWN = "crane_arc_down"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    HANDHELD = "handheld"
    STEADICAM = "steadicam"
    FOLLOW_SUBJECT = "follow_subject"
    LEAD_SUBJECT = "lead_subject"


MOVEMENT_TYPES = tuple(m.value for m in Movement)


class EngineSupport(StrEnum):
    """知识卡的能力标注（v1.3 诉求 5）。

    ``implemented``＝引擎真的能做；``approximated``＝用确定性近似（手持/斯坦
    尼康/甩镜）；``unsupported``＝做不到，必须如实说明。**不允许**把做不到
    包装成已支持（§6.3）。
    """

    IMPLEMENTED = "implemented"
    APPROXIMATED = "approximated"
    UNSUPPORTED = "unsupported"


ENGINE_SUPPORT_LEVELS = tuple(level.value for level in EngineSupport)


class VfxType(StrEnum):
    """白模特效代理的类型（v1.3 §3.6）。"""

    FLAME = "flame"
    GLOW = "glow"
    SPARK = "spark"
    SMOKE = "smoke"


VFX_TYPES = tuple(item.value for item in VfxType)


class CrowdMode(StrEnum):
    """群众代理的行为模式（v1.3 §3.6）。"""

    STATIC = "static"
    WALK = "walk"


CROWD_MODES = tuple(item.value for item in CrowdMode)


# --------------------------------------------------------------------------- #
# §21.2 错误码
# --------------------------------------------------------------------------- #
class ErrorCode(StrEnum):
    PARSE_001 = "E_PARSE_001"
    SDL_001 = "E_SDL_001"
    SDL_002 = "E_SDL_002"
    AXIS_001 = "E_AXIS_001"
    SPACE_001 = "E_SPACE_001"
    CAM_001 = "E_CAM_001"
    EXEC_001 = "E_EXEC_001"
    LLM_001 = "E_LLM_001"
    LLM_002 = "E_LLM_002"
    LLM_003 = "E_LLM_003"
    TOOL_001 = "E_TOOL_001"
    TOOL_002 = "E_TOOL_002"
    TOOL_003 = "E_TOOL_003"
    DELIV_001 = "E_DELIV_001"
    DELIV_002 = "E_DELIV_002"
    CORR_001 = "E_CORR_001"
    SCRIPT_001 = "E_SCRIPT_001"
    BRIEF_001 = "E_BRIEF_001"
    #: v1.4：分镜表声明的镜数超过 ``orchestration.max_shots`` 上限
    SCRIPT_002 = "E_SCRIPT_002"
    #: v1.4 BW-1：未知的姿态参数键（不许静默取默认）
    MOTION_001 = "E_MOTION_001"
    #: v1.6 A2：计划 characters 含角色表外 id（占位符）
    CAST_001 = "E_CAST_001"


# --------------------------------------------------------------------------- #
# §21.7 渲染引擎标识映射（实测：5.x 无 BLENDER_EEVEE_NEXT）
# --------------------------------------------------------------------------- #
class Engine(StrEnum):
    """逻辑引擎名；上层只用这个，不直接写 Blender 的引擎字符串。"""

    EEVEE = "eevee"
    WORKBENCH = "workbench"
    CYCLES = "cycles"


_ENGINE_TABLE: Dict[Engine, Tuple[str, str]] = {
    # 逻辑引擎 -> (Blender < 5.0 的标识, Blender >= 5.0 的标识)
    Engine.EEVEE: ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"),
    Engine.WORKBENCH: ("BLENDER_WORKBENCH", "BLENDER_WORKBENCH"),
    Engine.CYCLES: ("CYCLES", "CYCLES"),
}


def resolve_engine_identifier(engine: Engine,
                              blender_version: Tuple[int, ...]) -> str:
    """把逻辑引擎名解析为当前 Blender 版本的实际标识（§21.7）。

    >>> resolve_engine_identifier(Engine.EEVEE, (4, 2, 0))
    'BLENDER_EEVEE_NEXT'
    >>> resolve_engine_identifier(Engine.EEVEE, (5, 2, 0))
    'BLENDER_EEVEE'
    """
    legacy, modern = _ENGINE_TABLE[engine]
    return modern if tuple(blender_version) >= (5, 0, 0) else legacy


# --------------------------------------------------------------------------- #
# §15.8 分辨率预设
# --------------------------------------------------------------------------- #
RESOLUTION_PRESETS: Dict[DeliveryPreset, Tuple[int, int]] = {
    DeliveryPreset.HD16X9: (1280, 720),
    DeliveryPreset.FHD16X9: (1920, 1080),
    DeliveryPreset.SQUARE: (1024, 1024),
    DeliveryPreset.VERTICAL: (720, 1280),
}


def resolution_for(preset: DeliveryPreset) -> Tuple[int, int]:
    """返回预设对应的 (width, height)。"""
    return RESOLUTION_PRESETS[preset]
