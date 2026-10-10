"""E2：DeepSeek strict 工具调用实测探针（G2 判据 #8，卡 G8-E）。

DeepSeek strict 模式（Beta）要求 ``base_url=https://api.deepseek.com/beta``、
每个 function 带 ``strict: true``，服务端会**先校验 schema**——不支持的 JSON
Schema 写法/关键字直接返回错误。所以"启用前先探针"不是仪式：探针没通过，
sidecar 必须拒绝以 strict 模式启动（绝不静默退回非严格模式）。

本探针测两类事实：

1. **关键字支持**：对 ``strict_schema.SCHEMA_KEYWORD_UNIVERSE`` 逐条发最小
   schema，看服务端是收下（2xx）还是拒绝（4xx）。4xx = 该关键字不可用；
2. **六类调用**（每类至少 3 次）：plain enum / const / 带 const 判别式的 anyOf /
   嵌套 object / array items / 真实 ``EMIT_SHOT_DRAFT_PARAMETERS`` 经
   ``to_strict`` 后的 schema。每次记录 HTTP 状态、拒绝文本、arguments 能否
   ``json.loads``（GitHub deepseek-ai/DeepSeek-V3 issue #1069 记录过 strict
   模式偶发坏 JSON）、``validate_args`` 对**原 schema** 是否通过、usage。

``null`` 关键字不只有一种写法：``to_strict`` 对**标量**（string/number/
integer/boolean）产出 ``["<type>", "null"]`` 联合，对 **array/object（含隐式
object）** 产出 ``{"anyOf": [<原 schema>, {"type": "null"}]}``，对**本来就是
anyOf** 的字段追加 ``{"type": "null"}`` 分支。``null`` 的判定只取这三组
``to_strict`` **实际会产出**的编码；DeepSeek beta 拒收的旧编码
``["array","null"]`` / ``["object","null"]`` 型联合照发照记，但标
``diagnostic``，**不进判定**（证据：
``docs/evidence/20261010-015527-strict-probe/strict_probe.json`` 三次全 400）。

密钥只从环境变量 ``DEEPSEEK_API_KEY``（否则 ``DS_OFFICIAL_KEY``）读，绝不打印、
绝不写入结果文件。anyOf 被服务端拒绝时**停下并如实报告**——不把 schema 改写成
别的形状（改形状要用户裁决）。

用法：

    python tools/probe_strict_tools.py
    python tools/probe_strict_tools.py --model deepseek-v4-pro --attempts 3
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.append(str(TOOLS_DIR))

from strict_schema import (  # noqa: E402
    SCHEMA_KEYWORD_UNIVERSE,
    make_nullable,
    strip_nulls,
    to_strict,
)
from block_director.cinema.framing import CAMERA_SIDES  # noqa: E402
from block_director.contracts.enums import (  # noqa: E402
    MOVEMENT_TYPES,
    SHOT_TYPES,
)
from block_director.layer5_orchestrator.editor import (  # noqa: E402
    EMIT_SHOT_DRAFT_PARAMETERS,
)
from block_director.layer5_orchestrator.control_tools import (  # noqa: E402
    ABORT_PARAMETERS,
    FINISH_SHOT_PARAMETERS,
    REQUEST_SELF_REVIEW_PARAMETERS,
)
from block_director.layer5_orchestrator.planner import (  # noqa: E402
    plan_parameters,
)
from block_director.layer5_orchestrator.review import (  # noqa: E402
    REVIEW_TOOL_PARAMETERS,
)
from block_director.layer5_orchestrator.shot_schema import (  # noqa: E402
    BASE_DRAFT_PARAMETERS,
    CHARACTER_TOOL_NAMES,
    character_tool_parameters,
    emit_shot_draft_schema,
)
from block_director.layer5_orchestrator.timing_tool import (  # noqa: E402
    ESTIMATE_DURATION_PARAMETERS,
)
from block_director.layer5_orchestrator.tool_schema import validate_args  # noqa: E402
from block_director.layer5_orchestrator.understand import (  # noqa: E402
    EMIT_BRIEF_TOOL_PARAMETERS,
)
from block_director.knowledge.tool import (  # noqa: E402
    SEARCH_KNOWLEDGE_PARAMETERS,
)
from block_director.motion.model import ACTION_TYPES  # noqa: E402

DEFAULT_ENDPOINT = "https://api.deepseek.com/beta/chat/completions"
DEFAULT_MODEL = "deepseek-v4-pro"
#: 为什么默认这个型号：tools/sidecar_server.py 与 fixtures/*.config.yaml 里
#: **没有** DeepSeek 的 model 配置（sidecar 默认是 ollama 的 qwen3-vl:30b，
#: fixtures/local_sidecar.config.yaml 是 glm-5.3），按任务书"不清楚就用
#: deepseek-v4-pro 并说明"；最近一次官方 DeepSeek 通道验收
#: （docs/evidence/20261009-v16-acceptance）用的正是它。可用 --model 覆盖。
MODEL_SOURCE = (
    "tools/sidecar_server.py 与 fixtures/*.config.yaml 没有 DeepSeek 模型配置；"
    "按任务书默认 deepseek-v4-pro（docs/evidence/20261009-v16-acceptance 的"
    "官方通道型号），可用 --model 覆盖"
)

#: 这些关键字的判定不靠单独 schema，而是"所有探针共用的根 object"
#: （type=object + properties + required + additionalProperties=false）：
#: 只要任一探针请求被收下（2xx），这四个就都被覆盖到。
ROOT_KEYWORDS = ("type", "properties", "required", "additionalProperties")


def _tool_definition(name: str, description: str, schema: Dict[str, Any],
                     *, strict: bool = True) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "strict": strict,
            "parameters": schema,
        },
    }


def keyword_probe_schema(keyword: str) -> Dict[str, Any]:
    """给一个关键字做"能隔离到它"的最小属性 schema。"""
    if keyword == "items":
        prop: Dict[str, Any] = {"type": "array", "items": {"type": "string"}}
    elif keyword == "enum":
        prop = {"type": "string", "enum": ["a", "b"]}
    elif keyword == "const":
        prop = {"type": "string", "const": "a"}
    elif keyword == "anyOf":
        prop = {"anyOf": [{"type": "string", "const": "a"}, {"type": "integer"}]}
    elif keyword == "minimum":
        prop = {"type": "number", "minimum": 0}
    elif keyword == "maximum":
        prop = {"type": "number", "maximum": 10}
    elif keyword == "minItems":
        prop = {"type": "array", "items": {"type": "string"}, "minItems": 1}
    elif keyword == "maxItems":
        prop = {"type": "array", "items": {"type": "string"}, "maxItems": 3}
    elif keyword == "null":
        prop = {"type": ["string", "null"]}
    else:
        raise ValueError(f"没有为关键字 {keyword!r} 定义探针 schema")
    return {
        "type": "object",
        "properties": {"x": prop},
        "required": ["x"],
        "additionalProperties": False,
    }


def keyword_probe_variants(keyword: str
                           ) -> List[Tuple[str, Dict[str, Any], bool]]:
    """一个关键字的探针变体（属性 schema 层面）；返回
    ``(变体名, 属性 schema, diagnostic)``。

    ``diagnostic=True`` 的变体照发照记，但不参与该关键字的归类（判定只取
    ``to_strict`` 实际产出的编码）。
    """
    if keyword == "null":
        # 判定侧 = to_strict 实际产出的四种可空编码（用
        # make_nullable(to_strict(...)) 现场推导，与转换器同源、不会漂移）：
        # scalar type 联合、anyOf 包 array、anyOf 包 object、anyOf 追加 null。
        # 诊断侧 = 旧编码的 type 联合（DeepSeek beta 拒收 unknown variant
        # `array`/`object`，见 evidence/20261010-015527-strict-probe）；
        # to_strict 已不再产出它们，所以它们不翻 ``null`` 的盘，只留证据。
        return [
            ("null_scalar",
             make_nullable(to_strict({"type": "string"})), False),
            ("null_array_anyof",
             make_nullable(to_strict({"type": "array",
                                      "items": {"type": "string"}})), False),
            ("null_object_anyof",
             make_nullable(to_strict({
                 "type": "object", "additionalProperties": False,
                 "required": ["k"],
                 "properties": {"k": {"type": "string"}}})), False),
            ("null_anyof_append",
             make_nullable(to_strict({
                 "anyOf": [{"type": "string"}, {"type": "integer"}]})), False),
            ("null_array", {"type": ["array", "null"]}, True),
            ("null_object", {"type": ["object", "null"]}, True),
        ]
    return [(keyword, keyword_probe_schema(keyword), False)]


def case_definitions() -> List[Dict[str, Any]]:
    """六类探针用例；``schema`` 是**原 schema**，探针发的是 ``to_strict`` 后的。"""
    return [
        {
            "name": "plain_enum",
            "tool": "probe_enum",
            "prompt": 'Call the "probe_enum" tool now with mood exactly equal to '
                      '"calm". Do not reply with text.',
            "schema": {
                "type": "object", "additionalProperties": False,
                "required": ["mood"],
                "properties": {"mood": {"type": "string",
                                        "enum": ["calm", "tense"]}},
            },
        },
        {
            "name": "const",
            "tool": "probe_const",
            "prompt": 'Call the "probe_const" tool now with kind exactly equal to '
                      '"person". Do not reply with text.',
            "schema": {
                "type": "object", "additionalProperties": False,
                "required": ["kind"],
                "properties": {"kind": {"type": "string", "const": "person"}},
            },
        },
        {
            "name": "anyof_const_discriminator",
            "tool": "probe_anyof",
            "prompt": 'Call the "probe_anyof" tool now describing a cat with 9 '
                      'lives (kind must be "cat"). Do not reply with text.',
            "schema": {
                "type": "object", "additionalProperties": False,
                "required": ["pet"],
                "properties": {
                    "pet": {
                        "anyOf": [
                            {"type": "object", "additionalProperties": False,
                             "required": ["kind", "lives"],
                             "properties": {
                                 "kind": {"type": "string", "const": "cat"},
                                 "lives": {"type": "integer"}}},
                            {"type": "object", "additionalProperties": False,
                             "required": ["kind", "fetch"],
                             "properties": {
                                 "kind": {"type": "string", "const": "dog"},
                                 "fetch": {"type": "boolean"}}},
                        ],
                    },
                },
            },
        },
        {
            "name": "nested_object",
            "tool": "probe_nested",
            "prompt": 'Call the "probe_nested" tool now with outer.a equal to 1. '
                      'Do not reply with text.',
            "schema": {
                "type": "object", "additionalProperties": False,
                "required": ["outer"],
                "properties": {
                    "outer": {
                        "type": "object", "additionalProperties": False,
                        "required": ["a"],
                        "properties": {"a": {"type": "integer"},
                                       "b": {"type": "string"}},
                    },
                },
            },
        },
        {
            "name": "array_items",
            "tool": "probe_array",
            "prompt": 'Call the "probe_array" tool now with tags exactly '
                      '["alpha", "beta"]. Do not reply with text.',
            "schema": {
                "type": "object", "additionalProperties": False,
                "required": ["tags"],
                "properties": {"tags": {"type": "array",
                                        "items": {"type": "string"}}},
            },
        },
        {
            "name": "real_emit_shot_draft",
            "tool": "emit_shot_draft",
            "prompt": 'Call the "emit_shot_draft" tool now with exactly '
                      '{"shot_id": "shot_001"}; set every other property to null '
                      'as the schema requires. Do not reply with text.',
            "schema": EMIT_SHOT_DRAFT_PARAMETERS,
        },
    ]


# --------------------------------------------------------------------------- #
# 真实运行会转发的每一个 function 的原 schema（G8-H：只取代码、不手抄）
# --------------------------------------------------------------------------- #
#: 角色/相机/查询工具的基线 schema 唯一真源在 ``tool_bindings.py``，但那个模块
#: 顶层 ``import bpy``（纯 Python 探针 import 不了）。用 AST 把
#: ``registry.add(..., parameters={...})`` 的字面量**从源码里取出来**，再用
#: 纯模块里可 import 的名字表求值——两份 schema 都不会有。
_BINDINGS_PATH = ROOT / "block_director" / "layer3_engine" / "tool_bindings.py"


def _eval_schema_expr(node: ast.AST, namespace: Dict[str, Any]) -> Any:
    """求值 ``parameters={...}`` 的字面量表达式（只认字面量与 ``list(<名字>)``）。"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_schema_expr(item, namespace) for item in node.elts]
    if isinstance(node, ast.Dict):
        return {_eval_schema_expr(key, namespace): _eval_schema_expr(value, namespace)
                for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.Name):
        if node.id not in namespace:
            raise ValueError(
                f"tool_bindings schema 表达式引用了未登记的名字 {node.id!r}")
        return namespace[node.id]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "list" and len(node.args) == 1
            and not node.keywords):
        value = _eval_schema_expr(node.args[0], namespace)
        return list(value) if isinstance(value, (dict, set)) else list(value)
    raise ValueError(
        f"tool_bindings schema 出现不支持的表达式：{ast.unparse(node)}")


def binding_schemas() -> Dict[str, Dict[str, Any]]:
    """``tool_bindings.py`` 里 ``registry.add`` 的工具基线 schema（按工具名）。"""
    text = _BINDINGS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    namespace: Dict[str, Any] = {
        "ACTION_TYPES": list(ACTION_TYPES),
        "SHOT_TYPES": list(SHOT_TYPES),
        "CAMERA_SIDES": list(CAMERA_SIDES),
        "MOVEMENT_TYPES": list(MOVEMENT_TYPES),
    }
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Name)
                        and target.id == "INTERACTION_ACTIONS"):
                    namespace["INTERACTION_ACTIONS"] = _eval_schema_expr(
                        node.value, namespace)
    schemas: Dict[str, Dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add"):
            continue
        name: Optional[str] = None
        parameters: Optional[Dict[str, Any]] = None
        for keyword in node.keywords:
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                name = keyword.value.value
            elif keyword.arg == "parameters":
                parameters = _eval_schema_expr(keyword.value, namespace)
        if name and parameters is not None:
            schemas[str(name)] = parameters
    return schemas


#: 逐镜 schema 的代表性枚举（探针输入，不是 schema 抄本）：真实运行里
#: repair/react 用"本镜在场角色 / 全剧组 / 锚点名"渲染 enum；这里取一个非平凡
#: 实例，让"enum 注入 + 结构化目标 anyOf"这条最复杂的转发形状被实测覆盖。
PROBE_SHOT_CHARACTERS: Sequence[str] = ("主角", "对手")
PROBE_FULL_CAST: Sequence[str] = ("主角", "对手", "旁观者")
PROBE_ANCHORS: Sequence[str] = ("门口", "柜台")


def _tool_prompt(tool: str) -> str:
    return (f'Call the "{tool}" tool now with a minimal schema-valid payload. '
            "Every optional field may be omitted. Do not reply with text.")


def forwarded_tool_cases() -> List[Dict[str, Any]]:
    """sidecar 真实运行会转发的每一个 function 的**原 schema**。

    单一真源纪律：

    * 阶段工具的 schema 直接 import（``planner`` / ``understand`` /
      ``shot_schema`` / ``review`` / ``control_tools`` / ``timing_tool`` /
      ``knowledge.tool``）；
    * 查询/动作/相机工具的基线 schema 用 :func:`binding_schemas` 从
      ``tool_bindings.py`` 源码提取；
    * 角色工具与 ``emit_shot_draft`` 按真实路径注入**逐镜 enum**
      （``shot_schema.character_tool_parameters`` /
      ``emit_shot_draft_schema``）——sidecar 在 repair/react 里看到的正是
      这份带枚举的形状。
    """
    cases: List[Dict[str, Any]] = [
        {"name": "forward_emit_plan", "tool": "emit_plan",
         "prompt": ('Call the "emit_plan" tool now with exactly one minimal '
                    'shot in shots[]. Do not reply with text.'),
         "schema": plan_parameters(0)},
        {"name": "forward_emit_scene_brief", "tool": "emit_scene_brief",
         "prompt": _tool_prompt("emit_scene_brief"),
         "schema": EMIT_BRIEF_TOOL_PARAMETERS},
        # 计划阶段的 B1 工具表发的是静态 BASE_DRAFT；editor/repair/react 发的是
        # 逐镜版本。两种形状都会被转发，都探。
        {"name": "forward_emit_shot_draft_static", "tool": "emit_shot_draft",
         "prompt": _tool_prompt("emit_shot_draft"),
         "schema": BASE_DRAFT_PARAMETERS},
        {"name": "forward_emit_shot_draft_per_shot", "tool": "emit_shot_draft",
         "prompt": _tool_prompt("emit_shot_draft"),
         "schema": emit_shot_draft_schema(
             PROBE_SHOT_CHARACTERS, PROBE_FULL_CAST, PROBE_ANCHORS)},
        {"name": "forward_submit_review", "tool": "submit_review",
         "prompt": _tool_prompt("submit_review"),
         "schema": REVIEW_TOOL_PARAMETERS},
        {"name": "forward_request_self_review", "tool": "request_self_review",
         "prompt": _tool_prompt("request_self_review"),
         "schema": REQUEST_SELF_REVIEW_PARAMETERS},
        {"name": "forward_finish_shot", "tool": "finish_shot",
         "prompt": _tool_prompt("finish_shot"),
         "schema": FINISH_SHOT_PARAMETERS},
        {"name": "forward_abort", "tool": "abort",
         "prompt": _tool_prompt("abort"),
         "schema": ABORT_PARAMETERS},
        {"name": "forward_estimate_shot_duration", "tool": "estimate_shot_duration",
         "prompt": _tool_prompt("estimate_shot_duration"),
         "schema": ESTIMATE_DURATION_PARAMETERS},
        {"name": "forward_search_knowledge", "tool": "search_knowledge",
         "prompt": _tool_prompt("search_knowledge"),
         "schema": SEARCH_KNOWLEDGE_PARAMETERS},
    ]
    bindings = binding_schemas()
    for name in sorted(bindings):
        parameters = bindings[name]
        if name in CHARACTER_TOOL_NAMES:
            parameters = character_tool_parameters(
                name, parameters, PROBE_SHOT_CHARACTERS, PROBE_FULL_CAST)
        cases.append({"name": f"forward_tool_{name}", "tool": name,
                      "prompt": _tool_prompt(name), "schema": parameters})
    return cases


def _http_post(url: str, body: Dict[str, Any], headers: Dict[str, str],
               timeout: float) -> Tuple[Optional[int], str]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"network error: {type(exc).__name__}: {exc}"


def classify_attempts(attempts: Sequence[Tuple[Optional[int], bool]]
                      ) -> str:
    """把同一关键字的多次尝试归成 supported / rejected / undecided。"""
    statuses = {status for status, _rejected in attempts}
    if any(status is not None and 400 <= status < 500
           for status, _rejected in attempts):
        return "rejected"          # 服务端 4xx 至少一次：保守判拒绝
    if any(status is not None and 200 <= status < 300
           for status, _rejected in attempts):
        return "supported"
    return "undecided"             # 全是网络错误/5xx：无法下结论


def malformed_rate(case_attempts: Sequence[Dict[str, Any]]) -> float:
    """strict 输出里 arguments 坏 JSON 的比例（issue #1069 的实测口径）。"""
    total = 0
    malformed = 0
    for attempt in case_attempts:
        if not attempt.get("tool_call"):
            continue
        total += 1
        if not attempt.get("args_parse_ok"):
            malformed += 1
    return (malformed / total) if total else 0.0


def case_passed(case_attempts: Sequence[Dict[str, Any]]) -> bool:
    return any(
        attempt.get("status") is not None
        and 200 <= attempt["status"] < 300
        and attempt.get("tool_call")
        and attempt.get("args_parse_ok")
        and attempt.get("args_valid")
        for attempt in case_attempts
    )


def _keyword_probe_body(model: str, variant_name: str, keyword: str,
                        prop: Dict[str, Any],
                        max_tokens: int) -> Dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "probe"}],
        "tools": [_tool_definition(
            f"probe_kw_{variant_name}", f"keyword probe for {keyword}",
            {"type": "object", "properties": {"x": prop},
             "required": ["x"], "additionalProperties": False})],
        "tool_choice": "auto",
        "temperature": 0,
        "stream": False,
        "max_tokens": max_tokens,
    }


def _case_body(model: str, tool_name: str, strict_schema: Dict[str, Any],
               prompt: str, max_tokens: int) -> Dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system",
             "content": "You must call the given tool exactly once with a "
                        "schema-valid payload. Never reply with plain text."},
            {"role": "user", "content": prompt},
        ],
        "tools": [_tool_definition(tool_name, "strict probe case",
                                   strict_schema)],
        "tool_choice": "auto",
        "temperature": 0,
        "stream": False,
        "max_tokens": max_tokens,
    }


def _add_usage(total: Dict[str, int], usage: Optional[Dict[str, Any]]) -> None:
    if not isinstance(usage, dict):
        return
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            total[key] += int(value)


def _case_attempt(status: Optional[int], text: str,
                  original_schema: Dict[str, Any]) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "status": status,
        "rejected": status is not None and not 200 <= status < 300,
        "error_text": text[:500] if status is not None
                      and not 200 <= status < 300 else None,
        "tool_call": False,
        "args_parse_ok": None,
        "args_valid_raw": None,
        "args_valid": None,
        "arguments": None,
        "usage": None,
    }
    if status is None or not 200 <= status < 300:
        return record
    try:
        data = json.loads(text)
        message = ((data.get("choices") or [{}])[0].get("message") or {})
        calls = message.get("tool_calls") or []
        record["usage"] = data.get("usage")
        if not calls:
            return record
        record["tool_call"] = True
        arguments = str((calls[0].get("function") or {}).get("arguments", ""))
        record["arguments"] = arguments
        try:
            parsed = json.loads(arguments or "{}")
        except (json.JSONDecodeError, TypeError):
            record["args_parse_ok"] = False
            return record
        record["args_parse_ok"] = True
        if isinstance(parsed, dict):
            record["args_valid_raw"] = (validate_args(original_schema, parsed)
                                        == [])
            stripped = strip_nulls(json.loads(json.dumps(parsed)),
                                   original_schema)
            record["args_valid"] = (validate_args(original_schema, stripped)
                                    == [])
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        # 响应形状坏了：如实记为"这次没产出可判读的工具调用"，不吞成通过。
        record["tool_call"] = record.get("tool_call", False)
    return record


def run_probe(model: str, endpoint: str, attempts: int, max_tokens: int,
              timeout: float, api_key: str,
              http_post: Callable[..., Tuple[Optional[int], str]],
              tool_attempts: int = 1, probe_forwarded_tools: bool = False,
              ) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "model": model,
        "endpoint": endpoint,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "model_source": MODEL_SOURCE,
        "attempts_per_case": attempts,
        "supported_keywords": [],
        "rejected_keywords": [],
        "undecided_keywords": [],
        "malformed_rate": 0.0,
        "verdict": "fail",
        "stopped_reason": None,
        "cases": {},
        "forwarded_tools": {},
        "keyword_probes": {},
        "total_usage": {"prompt_tokens": 0, "completion_tokens": 0,
                        "total_tokens": 0},
        "error": None,
    }
    if not api_key:
        summary["error"] = ("环境里没有 DEEPSEEK_API_KEY / DS_OFFICIAL_KEY；"
                            "未发起任何请求，结果不可能被伪造")
        return summary
    headers = {"Authorization": f"Bearer {api_key}"}

    # ---- 1. 关键字探针（先跑：anyOf 被拒就立刻停，不浪费预算） ----
    all_statuses: List[Tuple[Optional[int], bool]] = []
    for keyword in SCHEMA_KEYWORD_UNIVERSE:
        if keyword in ROOT_KEYWORDS:
            continue
        attempts_records: List[Dict[str, Any]] = []
        for variant_name, prop, diagnostic in keyword_probe_variants(keyword):
            for index in range(attempts):
                body = _keyword_probe_body(model, variant_name, keyword, prop,
                                           max_tokens)
                status, text = http_post(endpoint, body, headers, timeout)
                attempts_records.append({
                    "attempt": index + 1,
                    "variant": variant_name,
                    "diagnostic": diagnostic,
                    "status": status,
                    "rejected": status is not None and 400 <= status < 500,
                    "error_text": text[:500] if status is not None
                                  and not 200 <= status < 300 else None,
                })
                all_statuses.append((status,
                                     status is not None
                                     and 400 <= status < 500))
                if status is not None and 200 <= status < 300:
                    try:
                        data = json.loads(text)
                        _add_usage(summary["total_usage"], data.get("usage"))
                    except (json.JSONDecodeError, TypeError):
                        pass
        summary["keyword_probes"][keyword] = {
            "classified": classify_attempts(
                [(rec["status"], rec["rejected"]) for rec in attempts_records
                 if not rec.get("diagnostic")]),
            "attempts": attempts_records,
        }
    # 根 object（type/properties/required/additionalProperties）由**每一个**探针
    # 共用：只要任一请求被收下（2xx），就证明这四个写法可用。4xx 的锅归给那个
    # 探针自己的目标构造（如旧编码的 null_array type 联合），不能冤枉根
    # object——所以根关键字只有 supported / undecided 两态，绝不因别的探针
    # 被拒而误判 rejected。
    root_class = ("supported"
                  if any(status is not None and 200 <= status < 300
                         for status, _rejected in all_statuses)
                  else "undecided")
    for keyword in ROOT_KEYWORDS:
        summary["keyword_probes"][keyword] = {
            "classified": root_class,
            "attempts": [],   # 由每个探针共用的根 object 覆盖
        }

    for keyword, probe in summary["keyword_probes"].items():
        bucket = {"supported": "supported_keywords",
                  "rejected": "rejected_keywords",
                  "undecided": "undecided_keywords"}[probe["classified"]]
        summary[bucket].append(keyword)
    summary["supported_keywords"] = sorted(summary["supported_keywords"])
    summary["rejected_keywords"] = sorted(summary["rejected_keywords"])
    summary["undecided_keywords"] = sorted(summary["undecided_keywords"])

    if "anyOf" in summary["rejected_keywords"]:
        summary["stopped_reason"] = (
            "提供方拒绝 anyOf：按卡 G8-E 停在这里如实报告，"
            "不把 schema 改写成别的形状（改形状要用户裁决）")
        summary["error"] = summary["stopped_reason"]
        return summary

    # ---- 2. 六类调用探针 ----
    for case in case_definitions():
        original_schema = case["schema"]
        strict_schema = to_strict(original_schema)
        case_attempts: List[Dict[str, Any]] = []
        for index in range(attempts):
            body = _case_body(model, case["tool"], strict_schema,
                              case["prompt"], max_tokens)
            status, text = http_post(endpoint, body, headers, timeout)
            record = _case_attempt(status, text, original_schema)
            record["attempt"] = index + 1
            if isinstance(record.get("usage"), dict):
                _add_usage(summary["total_usage"], record["usage"])
            case_attempts.append(record)
        summary["cases"][case["name"]] = {
            "passed": case_passed(case_attempts),
            "attempts": case_attempts,
        }

    summary["malformed_rate"] = malformed_rate(
        [attempt for case in summary["cases"].values()
         for attempt in case["attempts"]])

    # ---- 3. 真实运行会转发的每一个 function schema（G8-H） ----
    # 判据与六类用例不同：这里测的是"schema 在请求时刻被服务端接受"（2xx），
    # 不是"模型有没有产出合法工具调用"——后者是抽样方差，前者是确定性拒绝。
    # 4xx = 该工具的 strict 形状被服务端拒收；5xx/网络 = 无法下结论。
    if probe_forwarded_tools:
        for case in forwarded_tool_cases():
            attempts_records: List[Dict[str, Any]] = []
            strict_schema = to_strict(case["schema"])
            for index in range(max(1, int(tool_attempts))):
                body = _case_body(model, case["tool"], strict_schema,
                                  case["prompt"], max_tokens)
                status, text = http_post(endpoint, body, headers, timeout)
                if status is not None and 200 <= status < 300:
                    try:
                        data = json.loads(text)
                        _add_usage(summary["total_usage"], data.get("usage"))
                    except (json.JSONDecodeError, TypeError):
                        pass
                attempts_records.append({
                    "attempt": index + 1,
                    "status": status,
                    "rejected": status is not None and 400 <= status < 500,
                    "error_text": text[:500] if status is not None
                                  and not 200 <= status < 300 else None,
                })
            summary["forwarded_tools"][case["name"]] = {
                "classified": classify_attempts(
                    [(rec["status"], rec["rejected"])
                     for rec in attempts_records]),
                "attempts": attempts_records,
            }

    rejected_tools = [name for name, probe in summary["forwarded_tools"].items()
                      if probe["classified"] == "rejected"]
    undecided_tools = [name for name, probe in summary["forwarded_tools"].items()
                       if probe["classified"] == "undecided"]
    failed_cases = [name for name, case in summary["cases"].items()
                    if not case["passed"]]
    if (not summary["rejected_keywords"]
            and not summary["undecided_keywords"]
            and not rejected_tools
            and not undecided_tools
            and not failed_cases):
        summary["verdict"] = "pass"
        return summary
    reasons = []
    if summary["rejected_keywords"]:
        reasons.append(f"rejected_keywords={summary['rejected_keywords']}")
    if summary["undecided_keywords"]:
        reasons.append(f"undecided_keywords={summary['undecided_keywords']}")
    if rejected_tools:
        reasons.append(f"rejected_tools={rejected_tools}")
    if undecided_tools:
        reasons.append(f"undecided_tools={undecided_tools}")
    if failed_cases:
        reasons.append(f"failed_cases={failed_cases}")
        first_rejection = next(
            (attempt.get("error_text")
             for name in failed_cases
             for attempt in summary["cases"][name]["attempts"]
             if attempt.get("error_text")), None)
        if first_rejection:
            reasons.append(f"first_rejection={first_rejection[:300]}")
    tool_rejection = next(
        (attempt.get("error_text")
         for name in rejected_tools
         for attempt in summary["forwarded_tools"][name]["attempts"]
         if attempt.get("error_text")), None)
    if tool_rejection:
        reasons.append(f"first_tool_rejection={tool_rejection[:300]}")
    summary["error"] = "；".join(reasons)
    return summary


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="probe_strict_tools")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="被探针的模型（默认 deepseek-v4-pro，见 model_source）")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                        help="DeepSeek strict 的 Beta 端点")
    parser.add_argument("--attempts", type=int, default=3,
                        help="每个用例/关键字至少重复几次（默认 3）")
    parser.add_argument("--tool-attempts", type=int, default=1,
                        help="每个转发工具 schema 重复几次（默认 1：schema 的"
                             "接受/拒绝在请求时刻是确定性的，与抽样方差无关）")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out", default="",
                        help="结果 JSON 路径；默认 docs/evidence/<时间戳>-strict-probe/"
                             "strict_probe.json")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DS_OFFICIAL_KEY")
    if not api_key:
        print("no DEEPSEEK_API_KEY / DS_OFFICIAL_KEY in environment; "
              "probe not run", file=sys.stderr)
    out_path = Path(args.out) if args.out else (
        ROOT / "docs" / "evidence"
        / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-strict-probe"
        / "strict_probe.json")
    summary = run_probe(args.model, args.endpoint, args.attempts,
                        args.max_tokens, args.timeout, api_key or "",
                        _http_post, tool_attempts=args.tool_attempts,
                        probe_forwarded_tools=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps({
        "out": str(out_path),
        "model": summary["model"],
        "endpoint": summary["endpoint"],
        "verdict": summary["verdict"],
        "supported_keywords": summary["supported_keywords"],
        "rejected_keywords": summary["rejected_keywords"],
        "undecided_keywords": summary["undecided_keywords"],
        "forwarded_tools": {name: probe["classified"]
                            for name, probe in summary["forwarded_tools"].items()},
        "malformed_rate": summary["malformed_rate"],
        "error": summary["error"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
