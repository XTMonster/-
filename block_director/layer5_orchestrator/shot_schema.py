"""逐镜动态严格工具 schema（G2 判据 #8）。纯计算，**不 import bpy**。

背景：v10–v13 真跑（``work/_g2_ds_run/blender_v1*.log``）的 invalid 主力是
"模型看见了合法形状，却猜错了这一镜的名字与这一动作的键"——草案 / 修复 /
精修三个阶段的 schema 都是**静态**的：角色名没有逐镜枚举，动作参数是全部键
的**并集**。于是幻觉角色名（费里德 / 优一郎 / 伊萨克 / char_a）、场外
subject、逐动作写错键（``look_at.to`` / ``stand.base_z`` / ``body_tilt.drop`` /
``turn_body.axis``）、``pace='sharp'``、``rule='balance'`` 全都活到工具层才被
拒，每拒一次就白烧一次调用。

修法（G8-B）：把 schema 变成**逐镜动态**——每个镜头用自己的在场角色枚举、
全剧组枚举与锚点名单，动作分支按 ``motion/model.py::ACTION_PARAMS`` 逐动作
生成（单一真源，不手抄）。同一份 schema 既是模型看到的工具声明、也是
``registry.execute`` 校验用的那一份（同一个对象）。

与执行层同域的纪律（"schema 放行则执行层必收"）：

* 坐标键（``from``/``from_``/``target_position``/``to``）是 **2–3 个数字**——
  ``motion/model.py::coordinate_problems`` 收 2–3 项，``tests/test_action_params_
  are_constrained.py`` 还专门钉过"minItems=3 造成执行接受、schema 拒绝的假
  invalid"（v4 真跑）。
* G8-C 的结构化目标 ``{"point": [x, y, z]}`` 才**恰好 3 项**。
* 无歧义等价键（``ACTION_PARAM_ALIASES``：``turn_head.yaw_deg`` /
  ``body_tilt.lean_deg`` / ``look_at.angle_deg``）被执行层**归一后接受**，所以
  分支键表 = ``ACTION_PARAMS[<type>]`` ∪ 该动作的别名键——schema 不与执行层
  各说各话（v5–v7 真跑的 react_invalid 主力恰恰是这些等价键被 schema 误拒）。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Sequence, Tuple

from ..cinema.framing import CAMERA_SIDES
from ..contracts.beats import (
    BEAT_VERBS,
    COMPOSITION_RULES,
    FACE_TO_VALUES,
    MAX_BEATS,
    PACE_VALUES,
    RULE_ACTIONS,
    SUBJECT_POSITIONS,
)
from ..contracts.enums import MOVEMENT_TYPES, VFX_TYPES
from ..contracts.rhythm import CURVE_VALUES
from ..contracts.plan import FRAMING_TARGET_KINDS, FRAMING_TARGET_PARTS
from ..contracts.tools import SHOT_DRAFT_TOOL
from ..motion.model import (
    ACTION_PARAM_ALIASES,
    ACTION_PARAMS,
    ACTION_TYPES,
    PROP_ACTIONS,
    TOWARD_WORDS,
    action_param_domains,
)

#: 坐标键（2–3 个数字；与 ``motion/model.py::coordinate_problems`` 同域）。
_COORDINATE_KEYS = frozenset({"from", "from_", "target_position", "to"})
#: 自由字符串键（道具名/锚点名，不是数值也不是坐标）。
_FREE_STRING_KEYS = frozenset({"prop"})
#: G8-C 的结构化目标键（look_at 专用；其余动作不认识它）。
_TARGET_KEYS = frozenset({"target"})
#: 闭集取值键 → 取值表（单一真源 = ``motion/model.py::action_param_domains``）。
_CLOSED_VALUE_KEYS = frozenset({"speed", "axis"})

#: G8-C 的结构化坐标：**恰好 3 个 number**。
_POINT_ITEMS: Dict[str, Any] = {"type": "number"}


def point_schema() -> Dict[str, Any]:
    """``{"point": [x, y, z]}`` 的取值形状（G8-C：恰好 3 个数字）。"""
    return {"type": "array", "minItems": 3, "maxItems": 3,
            "items": copy.deepcopy(_POINT_ITEMS)}


def coordinate_schema() -> Dict[str, Any]:
    """坐标键的取值形状：**2–3 个数字**（与执行层 ``coordinate_problems`` 同域）。"""
    return {"type": "array", "minItems": 2, "maxItems": 3,
            "items": copy.deepcopy(_POINT_ITEMS)}


def string_enum(values: Sequence[str]) -> Dict[str, Any]:
    """字符串枚举；**空表省略 enum**（绝不发出 ``enum: []``，G2 #8）。"""
    unique = list(dict.fromkeys(str(item) for item in (values or ())
                                if str(item)))
    if not unique:
        return {"type": "string"}
    return {"type": "string", "enum": unique}


def character_object_schema(full_cast: Sequence[str]) -> Dict[str, Any]:
    """``{"character": id}``：id 限制在全剧组枚举内（G8-C）。"""
    return {"type": "object", "additionalProperties": False,
            "required": ["character"],
            "properties": {"character": string_enum(full_cast)}}


def point_object_schema() -> Dict[str, Any]:
    """``{"point": [x, y, z]}``（G8-C）。"""
    return {"type": "object", "additionalProperties": False,
            "required": ["point"],
            "properties": {"point": point_schema()}}


def structured_target_schema(full_cast: Sequence[str], *,
                             extra_string_values: Sequence[str] = (),
                             ) -> Dict[str, Any]:
    """G8-C 的目标形状：裸 id 字符串（全剧组[＋额外名单]）／
    ``{"character": id}``／``{"point": [x, y, z]}`` 三选一。"""
    string_values = list(full_cast) + list(extra_string_values)
    return {"anyOf": [
        string_enum(string_values),
        character_object_schema(full_cast),
        point_object_schema(),
    ]}


def _param_value_schema(kind: str, key: str,
                        full_cast: Sequence[str]) -> Dict[str, Any]:
    """一个动作参数键的取值 schema（键表与闭集都从 ``motion/model.py`` 渲染）。"""
    domains = action_param_domains()
    if key in _CLOSED_VALUE_KEYS and key in domains:
        return {"type": "string", "enum": list(domains[key])}
    if key == "toward":
        # body_tilt / 道具动作共用：方向量或方向词；道具动作另收 G8-C 目标形状。
        branches: list = [coordinate_schema(),
                          {"type": "string", "enum": list(TOWARD_WORDS)}]
        if kind in PROP_ACTIONS:
            branches.append(character_object_schema(full_cast))
            branches.append(point_object_schema())
        return {"anyOf": branches}
    if key in _TARGET_KEYS:                 # look_at.target（G8-C 结构化目标）
        return structured_target_schema(full_cast)
    if key in _COORDINATE_KEYS:
        return coordinate_schema()
    if key in _FREE_STRING_KEYS:
        return {"type": "string"}
    return {"type": "number"}


def _action_param_keys(kind: str) -> Tuple[str, ...]:
    """动作的允许参数键 = 键表 ∪ 无歧义等价键（执行层归一后接受，schema 不误拒）。"""
    aliases = tuple(ACTION_PARAM_ALIASES.get(kind, {}))
    return tuple(ACTION_PARAMS[kind]) + aliases


def _alias_canonical(kind: str, key: str) -> str:
    """别名键 → 规范键（取值域与规范键同源）。"""
    aliases = ACTION_PARAM_ALIASES.get(kind, {})
    return aliases.get(key, key)


def _action_branch(kind: str, subject: Dict[str, Any],
                   full_cast: Sequence[str]) -> Dict[str, Any]:
    """一个动作类型的分支：``action_type`` 用 ``const``（判别式），``params``
    只列该动作的键（``additionalProperties: False``）。"""
    properties: Dict[str, Any] = {
        "character_id": subject,
        #: DeepSeek strict 要求每个 schema 节点带 type / anyOf / $ref 之一；
        #: 裸 ``const`` 判别式会 400（2026-10-10 实测）。补上它本就有的
        #: ``type: string``，只加类型、不放宽任何取值。
        "action_type": {"type": "string", "const": kind},
        "start_frame": {"type": "integer", "minimum": 1},
        "end_frame": {"type": "integer", "minimum": 1},
    }
    #: 顶层 ``target_position`` 只属于行走类（构建器只在这里读它——见
    #: ``shot_builder.action_requests``）；其余动作写了就是死键，显式拒收。
    if kind in ("walk_to", "run_to"):
        properties["target_position"] = coordinate_schema()
    properties["params"] = action_params_schema(kind, full_cast)
    return {"type": "object", "additionalProperties": False,
            "required": ["character_id", "action_type"],
            "properties": properties}


def action_params_schema(kind: str, full_cast: Sequence[str]) -> Dict[str, Any]:
    """一个动作类型的 ``params`` 对象：只列该动作的键，取值域同源。"""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            key: _param_value_schema(kind, _alias_canonical(kind, key), full_cast)
            for key in _action_param_keys(kind)
        },
    }


def any_action_params_schema(full_cast: Sequence[str]) -> Dict[str, Any]:
    """不与 ``action_type`` 绑定时的 ``params``：各动作参数对象的 ``anyOf``。

    G8-H（2026-10-10 实测）：``character_action`` 的基线 ``params`` 是
    ``{"type": "object"}``（无 properties），DeepSeek strict 报
    ``An object with no properties is not allowed.``。这里把执行层本来就只
    接受的键表写成显式形状——只收紧到执行层既有的口径，不放宽；具体
    "键属于哪个动作"仍由执行层 ``unknown_action_params`` 按 ``action_type``
    复核。
    """
    return {"anyOf": [action_params_schema(kind, full_cast)
                      for kind in ACTION_TYPES]}


def actions_items_schema(subject: Dict[str, Any],
                         full_cast: Sequence[str]) -> Dict[str, Any]:
    """``actions[]`` 的 items：每动作一个分支的 ``anyOf``（从 ``ACTION_PARAMS``
    生成，不手抄）。"""
    return {"anyOf": [_action_branch(kind, subject, full_cast)
                      for kind in ACTION_TYPES]}


def beat_target_schema(full_cast: Sequence[str],
                       anchors: Sequence[str]) -> Dict[str, Any]:
    """拍点 ``target``：裸 id = 全剧组角色 ∪ 锚点名，另收 G8-C 结构化目标。"""
    return structured_target_schema(full_cast, extra_string_values=anchors)


# --------------------------------------------------------------------------- #
# 静态模板（无逐镜上下文）：角色字段是自由字符串，动作分支照旧逐动作严格。
# 它只服务旧调用点（``default_registry`` 的基线、单测）；真正发给模型的
# 载荷一律用 :func:`emit_shot_draft_schema` 的逐镜版本。
# --------------------------------------------------------------------------- #
def base_draft_parameters() -> Dict[str, Any]:
    """v1.5 草案 schema 模板：词汇与闭集不变，``actions`` 改成逐动作 ``anyOf``。"""
    open_string: Dict[str, Any] = {"type": "string"}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["shot_id"],
        "properties": {
            "shot_id": {"type": "string"},
            "shot_type": {"type": "string"},
            "characters": {"type": "array",
                           "items": {"type": "string"}},
            "actions": {
                "type": "array",
                "maxItems": 12,
                "items": actions_items_schema(open_string, ()),
            },
            "dialogues": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["character_id", "text", "start_frame",
                                 "end_frame"],
                    "properties": {
                        "character_id": {"type": "string"},
                        "text": {"type": "string"},
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1},
                    },
                },
            },
            "camera": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "side": {"type": "string", "enum": list(CAMERA_SIDES)},
                    "lens": {"type": "number", "minimum": 8, "maximum": 300},
                    "movements": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["type", "amount"],
                            "properties": {
                                "type": {"type": "string",
                                         "enum": list(MOVEMENT_TYPES)},
                                "amount": {"type": "number", "minimum": 0,
                                           "maximum": 180},
                                "start_frame": {"type": "integer", "minimum": 1},
                                "end_frame": {"type": "integer", "minimum": 1},
                                "seed": {"type": "integer", "minimum": 0},
                                "subject": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "gaze": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["from", "to"],
                    "properties": {
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                    },
                },
            },
            "vfx": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "type"],
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": list(VFX_TYPES)},
                        #: 与 v1.5 模板逐字节一致：vfx 坐标**恰好 3 项**
                        #: （不是行走类参数那样的 2–3 项）。
                        "position": point_schema(),
                        "size": point_schema(),
                        "start_frame": {"type": "integer", "minimum": 1},
                        "end_frame": {"type": "integer", "minimum": 1},
                    },
                },
            },
            "beats": {
                "type": "array",
                "maxItems": MAX_BEATS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["t", "subject", "verb"],
                    "properties": {
                        "t": {"type": "number", "minimum": 0, "maximum": 1},
                        "subject": {"type": "string"},
                        "verb": {"type": "string", "enum": list(BEAT_VERBS)},
                        "target": {"type": "string"},
                        "face_to": {"type": "string",
                                    "enum": list(FACE_TO_VALUES)},
                        "pace": {"type": "string", "enum": list(PACE_VALUES)},
                        "curve": {"type": "string", "enum": list(CURVE_VALUES)},
                        "react": {"type": "string"},
                    },
                },
            },
            "composition": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "rule": {"type": "string", "enum": list(COMPOSITION_RULES)},
                    "subject_position": {"type": "string",
                                         "enum": list(SUBJECT_POSITIONS)},
                },
            },
            #: T3：这一镜拍谁（角色/局部部位/道具）。kind/part 是闭集，
            #: 表外值 schema 直接拒收；ref 是全剧组/道具名的自由字符串。
            "framing_target": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "ref", "part"],
                "properties": {
                    "kind": {"type": "string",
                             "enum": list(FRAMING_TARGET_KINDS)},
                    "ref": {"type": "string"},
                    "part": {"type": "string",
                             "enum": list(FRAMING_TARGET_PARTS)},
                    "anchor_offset": {"type": "array", "minItems": 3,
                                      "maxItems": 3,
                                      "items": {"type": "number"}},
                },
            },
            "rule_justifications": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["rule", "action"],
                    "properties": {
                        "rule": {"type": "string"},
                        "action": {"type": "string",
                                   "enum": list(RULE_ACTIONS)},
                        "reason": {"type": "string"},
                        "precedent": {"type": "string"},
                    },
                },
            },
            "prompt": {"type": "string"},
        },
    }


#: 静态模板（旧调用点与单测的入口；模块内唯一一份，其余一律深拷贝）。
BASE_DRAFT_PARAMETERS: Dict[str, Any] = base_draft_parameters()


def emit_shot_draft_schema(shot_characters: Sequence[str],
                           full_cast: Sequence[str],
                           anchors: Sequence[str]) -> Dict[str, Any]:
    """这一镜的 ``emit_shot_draft`` schema（**深拷贝**模板后注入逐镜枚举）。

    * ``characters[]`` / ``actions[].character_id`` / ``dialogues[].character_id`` /
      ``beats[].subject``：本镜在场角色枚举（空镜省略 enum，绝不发空枚举）；
    * ``beats[].target``：全剧组 ∪ 锚点名的裸 id 或 G8-C 结构化目标；
    * 动作分支里的 ``look_at.target`` / 道具 ``toward``：全剧组枚举 ＋
      ``{"character"}/{"point"}``（G8-C 的精确形状）。
    """
    schema = copy.deepcopy(BASE_DRAFT_PARAMETERS)
    subject = string_enum(shot_characters)
    properties = schema["properties"]
    properties["characters"]["items"] = subject
    dialogues = properties["dialogues"]["items"]["properties"]
    dialogues["character_id"] = subject
    properties["actions"]["items"] = actions_items_schema(subject, full_cast)
    beats = properties["beats"]["items"]["properties"]
    beats["subject"] = subject
    beats["target"] = beat_target_schema(full_cast, anchors)
    return schema


# --------------------------------------------------------------------------- #
# 角色工具（repair / react 与 emit_shot_draft 同台给模型）
# --------------------------------------------------------------------------- #
#: 主体是本镜角色的工具（执行层 ``_require_character_in_shot`` 同口径）。
SUBJECT_CHARACTER_TOOLS: Tuple[str, ...] = (
    "character_action", "move_character", "look_at", "face_character",
    "interact_with",
)
#: character_id 可以是任何剧组角色的工具（执行层 ``_require_character`` 同口径）。
CAST_CHARACTER_TOOLS: Tuple[str, ...] = ("place_character", "check_visibility")
#: ``target`` 是另一个**剧组角色 id** 的工具（执行层 ``_require_character`` 同口径）。
TARGET_CHARACTER_TOOLS: Tuple[str, ...] = ("look_at", "face_character")

#: 需要逐镜枚举注入的全部角色工具（repair / react 载荷里出现才需要覆盖）。
CHARACTER_TOOL_NAMES: Tuple[str, ...] = (
    *SUBJECT_CHARACTER_TOOLS, *CAST_CHARACTER_TOOLS)


def character_tool_parameters(name: str, parameters: Dict[str, Any],
                              shot_characters: Sequence[str],
                              full_cast: Sequence[str]) -> Dict[str, Any]:
    """一份角色工具参数的**深拷贝**，只注入逐镜枚举；其余形状照抄注册基线
    （``tool_bindings`` 是唯一真源，这里不重写工具形状）。"""
    out = copy.deepcopy(dict(parameters or {}))
    properties = out.get("properties")
    if not isinstance(properties, dict):
        return out
    if name in SUBJECT_CHARACTER_TOOLS and "character_id" in properties:
        properties["character_id"] = string_enum(shot_characters)
    elif name in CAST_CHARACTER_TOOLS and "character_id" in properties:
        properties["character_id"] = string_enum(full_cast)
    if name in TARGET_CHARACTER_TOOLS and "target" in properties:
        properties["target"] = string_enum(full_cast)
    if name == "character_action" and "params" in properties:
        properties["params"] = any_action_params_schema(full_cast)
    return out


def shot_tool_overrides(registry, shot_characters: Sequence[str],
                        full_cast: Sequence[str],
                        anchors: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """这一镜的工具 schema 覆盖表：``emit_shot_draft`` 用完整逐镜 schema，
    角色工具用"基线参数 ＋ 逐镜枚举"（未注册的工具自然缺席，不越权注册）。"""
    overrides: Dict[str, Dict[str, Any]] = {}
    spec = registry.get(SHOT_DRAFT_TOOL)
    if spec is not None:
        overrides[SHOT_DRAFT_TOOL] = emit_shot_draft_schema(
            shot_characters, full_cast, anchors)
    for name in CHARACTER_TOOL_NAMES:
        spec = registry.get(name)
        if spec is None:
            continue
        overrides[name] = character_tool_parameters(
            name, spec.parameters, shot_characters, full_cast)
    return overrides


__all__ = [
    "BASE_DRAFT_PARAMETERS",
    "point_schema",
    "coordinate_schema",
    "string_enum",
    "structured_target_schema",
    "beat_target_schema",
    "actions_items_schema",
    "emit_shot_draft_schema",
    "character_tool_parameters",
    "shot_tool_overrides",
    "CHARACTER_TOOL_NAMES",
    "SUBJECT_CHARACTER_TOOLS",
    "CAST_CHARACTER_TOOLS",
    "TARGET_CHARACTER_TOOLS",
]
