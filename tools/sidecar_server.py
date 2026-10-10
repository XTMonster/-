"""sidecar 参考实现（执行文档 v1.2 §2.5）。

插件侧早就有 `SidecarTransport` 与 `specs/openapi.yaml`，"sidecar 是可选的一等
公民"只差这一半：**没有人提供这个服务**。本文件用标准库把它补齐——零依赖、
只监听回环地址，并承担插件不该承担的两件事：

1. **供应商差异**：本地模型（Ollama）需要 `num_ctx` 与 `think: false` 这类
   原生参数；OpenAI 兼容层表达不了它们。实测：qwen3-vl:30b 的默认 `num_ctx`
   是 4096，思维链会把预算全部吃掉，`finish_reason` 直接是 `length`——把它当
"模型不听话"会误导排查方向。
2. **检索**：BM25 语料本来就在插件侧，sidecar 只是把它暴露成 `/v1/retrieve`，
   让"向量检索必须由 sidecar 提供"（§6.1）有落点。

用法：
  python tools/sidecar_server.py --upstream http://127.0.0.1:11434 \\
      --model qwen3-vl:30b --num-ctx 32768 --think off --max-tokens 8192
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
#: strict 转换的单一真源（tools/strict_schema.py，纯函数、不碰 bpy）；本文件
#: 与 tools/probe_strict_tools.py 都 import 它，不各自抄一份 nullable 规则。
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.append(str(TOOLS_DIR))

from block_director.contracts.enums import Capability  # noqa: E402
from block_director.contracts.errors import (  # noqa: E402
    ErrorCode,
    TransportError,
)
from block_director.contracts.knowledge import (  # noqa: E402
    Card,
    Case,
    HyperEdge as HyperEdgeDTO,
)
from block_director.contracts.messages import (  # noqa: E402
    ChatReply,
    FunctionCall,
    ToolCall,
)
from block_director.contracts.operations import RetrieveResponse  # noqa: E402
from block_director.knowledge import default_retriever  # noqa: E402
#: L3 案例层的**单一真源**在包里（§3.1 的落点 `block_director/knowledge/cases.py`）；
#: sidecar 只做装配与 wire 转换，不再维护一份自己的 CaseLane（两份实现必然漂）。
from block_director.knowledge.cases import (  # noqa: E402
    CASE_BACKENDS,
    CaseIndex,
    load_index as load_case_index,
)
from block_director.knowledge.hypergraph import (  # noqa: E402
    HyperEdge,
    Hypergraph,
    Node,
    RetrievalTrace,
)
from strict_schema import (  # noqa: E402
    SCHEMA_KEYWORD_UNIVERSE,
    strip_nulls,
    to_strict,
)

CONTRACT_VERSION = "1.3.0"
LOOPBACK = "127.0.0.1"
DEFAULT_KNOWLEDGE_DIR = ROOT / "knowledge"
#: CLI 的 choices 引用包里的取值表，避免 sidecar 与 `cases.py` 各写一份。
CASE_LANES = CASE_BACKENDS


class StrictStartupRefused(Exception):
    """``--strict-tools`` 的启动前置不满足：sidecar 拒绝启动（退出码 2）。

    探针没通过就绝不静默退回非严格模式——G2 判据 #8 的整点是"先证明提供方
    真的能按 schema 约束解码，再启用"，退回等于把阈值又交回模型抽样方差。
    """


class SidecarConfig:
    def __init__(self, args) -> None:
        self.upstream = args.upstream.rstrip("/")
        self.model = args.model
        self.kind = args.upstream_kind
        self.num_ctx = args.num_ctx
        self.think = args.think
        #: 思考强度（`--reasoning-effort`，默认空 ⇒ **不发这个键**）。只对
        #: `--upstream-kind openai` 的 `_openai_body` 生效；实测新模型认它、
        #: 不认 `thinking.level`（`work/_probe_qwen_thinking.py`）。
        self.reasoning_effort = str(getattr(args, "reasoning_effort", "") or "")
        #: `tool_choice` 的翻译策略（见 `_openai_body` 的注释）：
        #: `passthrough`（默认，逐字节透传）/ `auto`（把 required 与对象改写成 auto）/
        #: `drop`（整格不发）。之所以要它：**思考模式**的上游拒收 `required`。
        self.tool_choice_mode = str(getattr(args, "tool_choice_mode", "passthrough")
                                    or "passthrough")
        #: strict 工具调用（G2 判据 #8，卡 G8-E）：探针通过后 opt-in。
        #: 默认关——关着的时候转发体逐字节与之前一致。
        self.strict_tools = bool(getattr(args, "strict_tools", False))
        self.strict_probe = str(getattr(args, "strict_probe", "") or "").strip()
        self.max_tokens = args.max_tokens
        self.temperature = args.temperature
        self.seed = args.seed
        self.token = args.token
        #: 上游 API 密钥**只从环境变量读**（`--upstream-api-key-env` 给变量名）：
        #: 云端 OpenAI 兼容端点（智谱 GLM 等）必须带 `Authorization: Bearer <key>`，
        #: 而本地 Ollama 不需要。密钥绝不写进仓库，也不进日志。
        self.upstream_api_key = ""
        key_env = str(getattr(args, "upstream_api_key_env", "") or "").strip()
        if key_env:
            self.upstream_api_key = os.environ.get(key_env, "")
            if not self.upstream_api_key:
                raise SystemExit(
                    "环境变量 %s 为空：云端上游需要它来带 Authorization 头" % key_env)
        self.timeout = args.timeout
        self.knowledge_dir = Path(args.knowledge_dir)
        self.cases_backend = args.cases_backend
        #: L3 的相关性过滤（`off` / `llm`）；`make_case_filter` 按它装配。
        self.cases_filter = str(getattr(args, "cases_filter", "off"))
        # 能力位**由实际加载结果决定**（见 main()）：宣告了却用不了，
        # 插件就会"以为能用"，那是 §2.3 明令禁止的静默失败。
        self.capabilities = [Capability.LLM, Capability.BM25]
        if self.kind == "ollama":
            # Ollama 的原生接口是 {host}/api/chat，OpenAI 兼容层在 {host}/v1
            if self.upstream.endswith("/v1"):
                self.upstream = self.upstream[:-3]


def detect_kind(upstream: str) -> str:
    return "ollama" if (":11434" in upstream or "/api" in upstream) else "openai"


# --------------------------------------------------------------------------- #
# 知识索引（v1.4 §2.3 / §2.3b）
#
# 超图与案例**都只在 sidecar 里装配**：插件侧零新依赖的承诺靠这一段兑现。
# 两个索引都缺失时必须显式降级（能力位不宣告 / `cases_degraded=true`），
# 不许"宣告了 hypergraph 却回空数组"。
# --------------------------------------------------------------------------- #
def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_hypergraph_index(knowledge_dir: Path) -> Optional[Hypergraph]:
    """读 ``knowledge/hypergraph.{nodes,edges}.jsonl``；缺任一文件返回 ``None``。"""
    nodes_path = knowledge_dir / "hypergraph.nodes.jsonl"
    edges_path = knowledge_dir / "hypergraph.edges.jsonl"
    if not (nodes_path.is_file() and edges_path.is_file()):
        return None
    nodes = [Node.from_dict(row) for row in read_jsonl(nodes_path)]
    edges = [HyperEdge.from_dict(row) for row in read_jsonl(edges_path)]
    return Hypergraph(nodes, edges)


def load_provenance(knowledge_dir: Path) -> Dict[str, Any]:
    """索引的六元指纹片段（§2.3：trace 必须能指向"这份索引从哪来"）。"""
    path = knowledge_dir / "hypergraph.manifest.json"
    if not path.is_file():
        return {}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    extractor = manifest.get("extractor") or {}
    return {
        "corpus_fingerprint": str(manifest.get("fingerprint", "")),
        "extractor_model_id": str(extractor.get("model_id", "")),
        "schema_version": str(manifest.get("schema_version", "")),
    }


def with_digest_fallback(cards: Sequence[Card]) -> List[Card]:
    """§2.3 第 1 步：**无种子 → 走 digest 兜底，不得静默返回空**。

    种子全空时把顶层摘要卡补进卡片通道（按 id 去重，已有的关键词命中一条不丢），
    调用方据此还能给出非空注入块；trace 里另置 ``digest_fallback = true``。
    """
    from block_director.knowledge.corpus import digest_cards

    seen = {card.id for card in cards}
    extra = [card for card in digest_cards() if card.id not in seen]
    return list(cards) + extra


# --------------------------------------------------------------------------- #
# 上游调用
# --------------------------------------------------------------------------- #
def _post_json(url: str, body: Dict[str, Any], timeout: float,
               headers: Optional[Dict[str, str]] = None
               ) -> Tuple[int, str]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _ollama_body(config: "SidecarConfig", payload: Dict[str, Any]
                 ) -> Dict[str, Any]:
    options: Dict[str, Any] = {"num_ctx": config.num_ctx,
                               "temperature": payload.get("temperature",
                                                          config.temperature)}
    seed = payload.get("seed", config.seed)
    if seed is not None:
        options["seed"] = int(seed)
    limit = payload.get("max_tokens") or config.max_tokens
    if limit:
        options["num_predict"] = int(limit)
    body: Dict[str, Any] = {"model": config.model,
                            "messages": payload.get("messages", []),
                            "stream": False, "options": options}
    if payload.get("tools"):
        body["tools"] = payload["tools"]
    if config.think == "off":
        body["think"] = False
    elif config.think == "on":
        body["think"] = True
    return body


def _ollama_reply(data: Dict[str, Any]) -> ChatReply:
    """Ollama 原生响应 → 我们的 ChatReply。

    注意两点差异：tool_calls 的 ``arguments`` 在原生接口里是**对象**（不是
    JSON 字符串），且思维链字段叫 ``thinking``。
    """
    message = data.get("message") or {}
    calls: List[ToolCall] = []
    for index, raw in enumerate(message.get("tool_calls") or []):
        function = raw.get("function") or {}
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {}, ensure_ascii=False)
        calls.append(ToolCall(id=str(raw.get("id") or f"call_{index}"),
                              function=FunctionCall(
                                  name=str(function.get("name", "")),
                                  arguments=arguments)))
    usage = None
    if data.get("prompt_eval_count") is not None or data.get("eval_count"):
        from block_director.contracts.messages import Usage

        usage = Usage(prompt_tokens=int(data.get("prompt_eval_count") or 0),
                      completion_tokens=int(data.get("eval_count") or 0))
    done_reason = str(data.get("done_reason") or "")
    return ChatReply(content=message.get("content"),
                     tool_calls=calls,
                     reasoning=message.get("thinking"),
                     usage=usage, model=data.get("model"),
                     finish_reason="length" if done_reason == "length" else
                     ("tool_calls" if calls else "stop"))


def _openai_reply(data: Dict[str, Any]) -> ChatReply:
    from block_director.contracts.transport import parse_chat_response

    return parse_chat_response(data)


def _upstream_headers(config: "SidecarConfig") -> Dict[str, str]:
    """云端上游的鉴权头。

    §4.4 步骤 2 的 sidecar 命令此前指向本机 Ollama，所以不需要鉴权；用户裁决
    "别用本地模型了" 之后上游换成智谱 GLM 这类 OpenAI 兼容端点，**必须**带
    `Authorization: Bearer <key>`，否则上游回 401、整条真实模型通路跑不起来
    （Q5/E2 就只能一直记 `not_measured`）。密钥由 `--upstream-api-key-env` 指名的
    环境变量提供：不进仓库、不进日志、不进 `knowledge_trace`。
    """
    key = str(getattr(config, "upstream_api_key", "") or "")
    return {"Authorization": f"Bearer {key}"} if key else {}


#: Authorization 头行（含换行）的正则：上游正文理论不带我们的密钥，但网关/
#: 代理可能把请求头回显进错误正文；§2.5 的纪律是"密钥绝不进日志"，所以
#: 502 的正文摘录在序列化前必须抹掉这一类痕迹。
_AUTHORIZATION_HEADER_RE = re.compile(
    r"authorization\s*:\s*[^\r\n]*", re.IGNORECASE)


def sanitize_upstream_body(text: str, config: "SidecarConfig") -> str:
    """从上游错误正文里抹掉密钥与 Authorization 头痕迹，其余字符原样保留。

    只做确定性红化（``[REDACTED]``）：抹掉配置里的密钥字面量、以及任何
    ``Authorization: ...`` 头行。不做任何改写/截断之外的改动——截断由调用方
    按 2000 字符上限执行。
    """
    out = str(text or "")
    key = str(getattr(config, "upstream_api_key", "") or "")
    if key:
        out = out.replace(key, "[REDACTED]")
    return _AUTHORIZATION_HEADER_RE.sub("[REDACTED]", out)


def upstream_error_payload(exc: "TransportError",
                           config: "SidecarConfig") -> Dict[str, Any]:
    """502 的载荷：带上游状态与正文摘录，且**整个序列化后 ≤2000 字符**。

    插件的 ``SidecarTransport._call`` 只保留 sidecar 响应正文的前 2000 字符
    （``body=text[:2000]``）：载荷超过 2000 字符时，插件拿到的是**被截断的
    JSON**，连 ``upstream_http_status`` 都解析不出来（G8-H 真跑实证——上游
    5xx 的大正文让 502 总长越过插件窗口，``json.loads`` 失败、字段全丢）。
    所以摘录随序列化大小回缩，保证 502 正文在插件窗口内永远是完整 JSON。
    """
    base = {"error": str(exc), "code": str(exc.code),
            "upstream_http_status": exc.http_status}
    excerpt = sanitize_upstream_body(str(exc.body or ""), config)
    limit = 2000
    while True:
        payload = {**base, "upstream_body_excerpt": excerpt[:limit]}
        if len(json.dumps(payload, ensure_ascii=False)) <= 2000:
            return payload
        limit = max(0, limit - 64)


def log_reply_parse_failure(text: str, exc: "TransportError",
                            status: Optional[int] = None) -> None:
    """上游 200、但回复解析/截断判定失败：把关键事实写 stderr（key-free）。

    ``parse_chat_response`` 在 ``finish_reason=length`` 时抛
    ``TransportError``（正文只留**头部** 2000 字符，``finish_reason`` 与
    ``usage`` 都在尾部）——这一条日志补上头部截断丢掉的事实：终止原因、
    思考链长度、工具调用数与每个 arguments 的截断位置、completion_tokens。
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        data = None
    record: Dict[str, Any] = {"upstream_reply": "parse_failed",
                              "http_status": status,
                              "error": str(exc)}
    if isinstance(data, dict):
        choices = data.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(
            choice.get("message"), dict) else {}
        calls = message.get("tool_calls") or []
        record["finish_reason"] = choice.get("finish_reason")
        record["content_chars"] = len(str(message.get("content") or ""))
        record["reasoning_chars"] = len(
            str(message.get("reasoning_content") or ""))
        record["tool_calls"] = [{
            "name": str((call.get("function") or {}).get("name") or ""),
            "arguments_chars": len(
                str((call.get("function") or {}).get("arguments") or "")),
        } for call in calls if isinstance(call, dict)]
        usage = data.get("usage")
        if isinstance(usage, dict):
            record["completion_tokens"] = usage.get("completion_tokens")
    print(json.dumps(record, ensure_ascii=False),
          file=sys.stderr, flush=True)


def call_upstream(config: "SidecarConfig", payload: Dict[str, Any]
                  ) -> ChatReply:
    """把插件侧的请求转发给上游模型。"""

    if config.kind == "ollama":
        status, text = _post_json(f"{config.upstream}/api/chat",
                                  _ollama_body(config, payload),
                                  config.timeout)
        if not 200 <= status < 300:
            #: 错误上报：状态与红化后的正文摘录直接写 stderr（绝不带密钥），
            #: 502 响应的字段即使后续链路再丢，这里也有一份可观测的现场。
            print(json.dumps(
                {"upstream_error": status,
                 "body_excerpt": sanitize_upstream_body(text, config)[:500]},
                ensure_ascii=False), file=sys.stderr, flush=True)
            raise TransportError(_code_for(status),
                                 f"上游返回 {status}", http_status=status,
                                 body=text[:2000])
        return _ollama_reply(json.loads(text))
    url = f"{config.upstream}/chat/completions"
    if getattr(config, "strict_tools", False):
        # DeepSeek strict（Beta）要求 base_url 带 /beta 段；其余拼接规则不变。
        url = f"{strict_upstream_base(config.upstream)}/chat/completions"
    status, text = _post_json(url, _openai_body(config, payload), config.timeout,
                              _upstream_headers(config))
    if not 200 <= status < 300:
        print(json.dumps(
            {"upstream_error": status,
             "body_excerpt": sanitize_upstream_body(text, config)[:500]},
            ensure_ascii=False), file=sys.stderr, flush=True)
        raise TransportError(_code_for(status), f"上游返回 {status}",
                             http_status=status, body=text[:2000])
    try:
        reply = _openai_reply(json.loads(text))
    except TransportError as exc:
        log_reply_parse_failure(text, exc, status)
        #: ``parse_chat_response`` 抛的 TransportError 不带 http_status（上游
        #: 明明是 200，只是回复被截断）；重抛时补上真实状态，让 502 的
        #: ``upstream_http_status`` 是 200 而不是 null（G8-H 真跑实证）。
        raise TransportError(exc.code, str(exc), http_status=status,
                             body=exc.body) from exc
    if getattr(config, "strict_tools", False):
        reply = _strip_reply_nulls(reply, payload)
    return reply


def _openai_body(config: "SidecarConfig", payload: Dict[str, Any]
                 ) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": config.model,
                            "messages": payload.get("messages", []),
                            "temperature": payload.get("temperature",
                                                       config.temperature)}
    seed = payload.get("seed", config.seed)
    if seed is not None:
        body["seed"] = int(seed)
    if payload.get("tools"):
        body["tools"] = _strict_tools(payload["tools"]) \
            if getattr(config, "strict_tools", False) else payload["tools"]
    if payload.get("tool_choice"):
        #: **供应商差异（2026-10-07 实测）**：阿里云百炼（DashScope 兼容口）在
        #: **思考模式**下拒收 `tool_choice=required`／对象：
        #:
        #:     <400> InternalError.Algo.InvalidParameter: The tool_choice parameter
        #:     does not support being set to required or object in thinking mode
        #:
        #: 插件发的正是 `required`（`contracts/transport.py:229`），而 sidecar 把上游
        #: 任何非 2xx 都翻译成 502 ⇒ 计划调用 0.7 s 就失败（现场见
        #: `docs/evidence/20261007-v15-bailian/`）。这一格就是那条翻译：
        #: **默认 `passthrough`**（一个字节都不改），只有显式 `--tool-choice-mode auto`
        #: 才把 `required`／对象改写成 `auto`——"思考模式"与"强制工具调用"在这家上游
        #: 互斥；用户 2026-10-07 的指令是"思考强度拉到最大"，所以这里保思考、
        #: 把"必须调工具"交给提示词（驱动的 `plan_attempts`/`draft_invalid` 仍然守着
        #: "没调工具就重问"）。
        mode = str(getattr(config, "tool_choice_mode", "passthrough")
                   or "passthrough")
        choice = payload["tool_choice"]
        if mode == "auto" and (choice == "required" or isinstance(choice, dict)):
            body["tool_choice"] = "auto"
        elif mode == "drop":
            body.pop("tool_choice", None)
        else:
            body["tool_choice"] = choice
    limit = payload.get("max_tokens") or config.max_tokens
    if limit:
        body["max_tokens"] = int(limit)
    #: **思考强度**（opt-in，默认不发）：用户 2026-10-07「新模型思考强度拉到最大」。
    #: 这一格属于**供应商差异**，所以归 sidecar（插件侧保持零新依赖）——
    #: 实测在 `qwen3.8-max-0902` 上，`reasoning_effort` 才是真旋钮
    #: （`thinking.level` 会被忽略：`work/_probe_qwen_thinking.py`）。
    #: 默认空串 ⇒ **一个字节都不加**，历史运行不受影响。
    effort = str(getattr(config, "reasoning_effort", "") or "").strip()
    if effort:
        body["reasoning_effort"] = effort
    return body


def _code_for(status: int) -> ErrorCode:
    return ErrorCode.LLM_001 if 500 <= status <= 599 else ErrorCode.LLM_002


# --------------------------------------------------------------------------- #
# strict 工具调用（G2 判据 #8，卡 G8-E）
#
# 提供方（DeepSeek）的 strict 模式要求：base_url 带 /beta 段、每个 function
# 带 ``strict: true``、每个 object 全量必填 + additionalProperties=false。
# 原 schema 的"可选字段"因此被 ``to_strict`` 改成可空，收包时再用
# ``strip_nulls`` 按原 schema 剥掉，插件侧拿到的形状与关掉 strict 时一致。
# 启用前置由 :func:`check_strict_startup` 把关：探针 verdict 不是 pass、模型
# 对不上、或 supported_keywords 缺本仓 schema 用到的关键字，一律退出码 2。
# --------------------------------------------------------------------------- #
def strict_upstream_base(upstream: str) -> str:
    """strict（Beta）要求的 base URL：沿用配置给的 base，补上 /beta 段。"""
    base = str(upstream).rstrip("/")
    if base.endswith("/beta"):
        return base
    return base + "/beta"


def _strict_tools(tools: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把转发给上游的工具改写成 strict 形状；不改动入参（返回新列表）。"""
    converted: List[Dict[str, Any]] = []
    for tool in tools:
        item = dict(tool)
        function = tool.get("function")
        if isinstance(function, dict):
            new_function = dict(function)
            parameters = function.get("parameters")
            if isinstance(parameters, dict):
                new_function["parameters"] = to_strict(parameters)
            new_function["strict"] = True
            item["function"] = new_function
        converted.append(item)
    return converted


def _strip_reply_nulls(reply: ChatReply, payload: Dict[str, Any]
                       ) -> ChatReply:
    """把 strict 输出的可选字段 null 剥掉，恢复原 schema 的形状再回给插件。"""
    schemas: Dict[str, Dict[str, Any]] = {}
    for tool in payload.get("tools") or []:
        function = tool.get("function") or {}
        name = function.get("name")
        parameters = function.get("parameters")
        if name and isinstance(parameters, dict):
            schemas[str(name)] = parameters
    calls: List[ToolCall] = []
    for call in reply.tool_calls:
        schema = schemas.get(call.function.name)
        arguments = call.function.arguments
        if schema is not None:
            try:
                args = json.loads(arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                args = None  # 坏 JSON 原样透传（探针的 malformed_rate 量它）
            if isinstance(args, dict):
                strip_nulls(args, schema)
                arguments = json.dumps(args, ensure_ascii=False)
        calls.append(ToolCall(
            id=call.id, type=call.type,
            function=FunctionCall(name=call.function.name, arguments=arguments)))
    return ChatReply(content=reply.content, tool_calls=calls,
                     reasoning=reply.reasoning, usage=reply.usage,
                     request_id=reply.request_id, model=reply.model,
                     finish_reason=reply.finish_reason)


def check_strict_startup(args, config) -> None:
    """``--strict-tools`` 的启动门；任何一条不满足就抛 StrictStartupRefused。"""
    if not getattr(args, "strict_tools", False):
        return
    if config.kind != "openai":
        raise StrictStartupRefused(
            f"strict tools 需要 OpenAI 兼容上游（DeepSeek Beta 端点），"
            f"当前 kind={config.kind}")
    probe_path = str(getattr(args, "strict_probe", "") or "").strip()
    if not probe_path:
        raise StrictStartupRefused(
            "--strict-tools 需要 --strict-probe <path>：先跑 "
            "tools/probe_strict_tools.py 拿到实测探针")
    path = Path(probe_path)
    if not path.is_file():
        raise StrictStartupRefused(f"strict 探针文件不存在：{path}")
    try:
        probe = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StrictStartupRefused(
            f"strict 探针读不了：{path}（{type(exc).__name__}: {exc}）") from exc
    verdict = str(probe.get("verdict") or "")
    if verdict != "pass":
        detail = str(probe.get("error") or probe.get("stopped_reason") or "").strip()
        raise StrictStartupRefused(
            f"探针 verdict={verdict!r} 不是 pass"
            + (f"：{detail}" if detail else ""))
    probe_model = str(probe.get("model") or "")
    if probe_model != config.model:
        raise StrictStartupRefused(
            f"探针模型 {probe_model!r} ≠ 配置模型 {config.model!r}")
    supported = set(probe.get("supported_keywords") or [])
    missing = sorted(set(SCHEMA_KEYWORD_UNIVERSE) - supported)
    if missing:
        raise StrictStartupRefused(
            f"探针 supported_keywords 缺本仓工具 schema 需要的 {missing}；"
            f"提供方不支持/未实测这些关键字，strict 模式下拒绝转发")


# --------------------------------------------------------------------------- #
# HTTP 服务
# --------------------------------------------------------------------------- #
#: 相关性过滤器的提示词（2026-10-03）。与 `tools/kb_fetch/case_search_zh.py` 同一纪律：
#: 只做判断、不产出内容；判据是"能不能指导**这一镜怎么拍**"，不是"气氛像不像"。
CASE_FILTER_SYSTEM = (
    "你是分镜预演工具的知识检索过滤员。给你一条导演的镜头查询与若干条候选参考案例，"
    "请**剔除明显与这一镜无关的**，其余的保留。\n"
    "判据：能沾上这一镜的拍法（景别/机位/运镜/构图/光线/剪辑节奏/表演调度）就保留——"
    "哪怕只是同一类手法、同一类场面；**明显**是气氛描写、剧情叙述、演员轶事、"
    "或讲的完全是另一回事的才剔除。\n"
    "**不确定就保留**（宁可留一条弱相关的，也不要让导演拿不到参考）。"
    "只输出 JSON：{\"keep\":[\"<保留的案例 id>\", ...]}"
)


def make_case_filter(config: "SidecarConfig"):
    """按上游配置装配 L3 的**相关性过滤器**；`off` 或没有上游时返回 ``None``。

    为什么装在这里而不是插件里：上游（模型、密钥、超时）是 sidecar 的职责
    （`--upstream*` 那一组参数），插件侧保持零新依赖。过滤器**只做减法**——
    `CaseIndex._filtered` 会把不属于入参的结果剔掉，所以它不可能"造"出案例来。
    """
    if getattr(config, "cases_filter", "off") != "llm":
        return None
    url = chat_completions_url(str(config.upstream))

    def _filter(query: str, cases):
        listing = "\n".join(f"{case.case_id}｜{str(case.excerpt)[:160]}" for case in cases)
        payload = {
            "model": config.model,
            "messages": [{"role": "system", "content": CASE_FILTER_SYSTEM},
                         {"role": "user",
                          "content": f"查询：{query}\n\n候选：\n{listing}"}],
            "temperature": 0.0, "seed": 0, "max_tokens": 512, "stream": False,
        }
        if config.kind == "ollama":
            payload["think"] = config.think == "on"
        else:
            payload["thinking"] = {"type": "disabled"}
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {config.upstream_api_key}"}
                        if config.upstream_api_key else {})})
        with urllib.request.urlopen(request, timeout=float(config.timeout)) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
        text = str(((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        match = re.search(r"\{.*\}", text, re.S)
        keep = set(str(item) for item in (json.loads(match.group(0)).get("keep") or [])) \
            if match else set()
        return [case for case in cases if str(case.case_id) in keep]

    return _filter


#: 已经带版本段的上游前缀（`…/v1`、GLM 的 `…/api/paas/v4`）：直接在后面接
#: `/chat/completions`。**实测踩过**：不判这一条就会拼出 `…/paas/v4/v1/chat/completions`，
#: 每次调用都 404，而过滤器失败是**静默回退**到未过滤结果——E1 数字看着"没变化"，
#: 实际是过滤器一次都没跑（`work/zz_e1_filtered_measure.py` 的第一次运行）。
_VERSIONED = re.compile(r"/v\d+$")


def chat_completions_url(upstream: str) -> str:
    """上游地址 → OpenAI 兼容的 chat completions 端点（Ollama 与云端共用一条规则）。"""
    base = str(upstream).rstrip("/")
    if _VERSIONED.search(base):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def make_handler(config: "SidecarConfig"):
    retriever = default_retriever()
    # 索引**装配在这里**，能力位跟着实际结果走（§2.3：宣告了就必须能用）。
    hypergraph = load_hypergraph_index(config.knowledge_dir)
    if hypergraph is not None and Capability.HYPERGRAPH not in config.capabilities:
        config.capabilities.append(Capability.HYPERGRAPH)
    case_lane: CaseIndex = load_case_index(config.knowledge_dir,
                                           config.cases_backend,
                                           case_filter=make_case_filter(config))
    provenance = load_provenance(config.knowledge_dir)
    cancelled: set = set()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):        # 静音：日志走 stdout 的显式记录
            return

        # -- 工具 ---------------------------------------------------------- #
        def _json(self, status: int, payload: Dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _authorised(self) -> bool:
            if not config.token:
                return True
            return self.headers.get("Authorization") == f"Bearer {config.token}"

        def _body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        # -- 路由 ---------------------------------------------------------- #
        def do_GET(self):
            if self.path != "/health":
                self._json(404, {"error": "not found"})
                return
            self._json(200, {"status": "ok", "version": CONTRACT_VERSION,
                             "capabilities": [str(item)
                                              for item in config.capabilities]})

        def do_POST(self):
            if not self._authorised():
                self._json(401, {"error": "unauthorized"})
                return
            try:
                body = self._body()
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return
            try:
                self._route(body)
            except TransportError as exc:
                #: G8-H：上游的 HTTP 状态与正文摘录必须**穿过 sidecar** 到达插件
                #: 审计（此前两跳都只留 ``str(exc)``，`TransportError.__str__`
                #: 丢弃 body，于是 502 背后的上游 4xx/5xx 不可观测）。摘录在
                #: 序列化前红化密钥与 Authorization 头，并由
                #: ``upstream_error_payload`` 保证整个 502 正文 ≤2000 字符
                #: （插件侧只留前 2000 字符，超了会被截成坏 JSON、字段全丢）。
                self._json(502, upstream_error_payload(exc, config))
            except Exception as exc:                     # noqa: BLE001
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        def _route(self, body: Dict[str, Any]) -> None:
            if self.path == "/v1/chat":
                self._json(200, call_upstream(config, body).to_dict())
                return
            if self.path == "/v1/retrieve":
                self._json(200, _retrieve_payload(body).to_dict())
                return
            if self.path == "/v1/embed":
                self._json(501, {"error": "本 sidecar 未配置向量嵌入；"
                                          "§6.1 允许退回 bm25"})
                return
            if self.path == "/v1/cancel":
                with lock:
                    cancelled.add(str(body.get("request_id", "")))
                self._json(200, {"cancelled": True})
                return
            self._json(404, {"error": "not found"})

    def _card_payload(card: Card) -> Dict[str, Any]:
        return card.to_dict()

    def _edge_payload(edge: HyperEdge) -> HyperEdgeDTO:
        """超图内部对象 → 线协议 DTO。**整条**搬运，含全部 forbid。"""
        return HyperEdgeDTO(
            edge_id=edge.edge_id,
            type=edge.type,
            members=[member.to_dict() for member in edge.members],
            forbid=[member.to_dict() for member in edge.forbids],
            weight=edge.weight,
            source_span=dict(edge.source_span),
            source_kind=edge.source_kind,
            hardness=edge.hardness,
            occurrences=edge.occurrences,
            confidence=edge.confidence,
        )

    def _retrieve_payload(body: Dict[str, Any]) -> RetrieveResponse:
        """三条通道一次返回：卡片正文 ＋ 超边 ＋ 参考案例 ＋ trace（§2.3/§2.3b）。"""
        query = str(body.get("query", ""))
        domain = body.get("domain")
        top_k = int(body.get("top_k", 5) or 5)
        cards = retriever.retrieve(query, domain, top_k)
        edges: List[HyperEdgeDTO] = []
        #: **唯一生产者**：降级路的 trace 也走 `RetrievalTrace`，不许手抄一份。
        #: 手抄那份当场漂过——S1a 给 dataclass 加 `qualifiers` 惰性键表时，
        #: 降级路没有它；`forbid_promoted` 更是从来没抄进去过。两份字面量
        #: 迟早漂（本仓在 `camera.side`／`MOVEMENT_TYPES`／`QUALIFIER_KINDS`
        #: 上已经栽过三次）。守门见
        #: `tests/test_sidecar_retrieve.py::test_the_degraded_trace_has_the_same_shape_as_the_real_one`。
        trace: Dict[str, Any] = RetrievalTrace(query=query, seed_miss=True).to_dict()
        backend = "bm25"
        if hypergraph is not None:
            selected, _text, hg_trace = hypergraph.retrieve(query, top_k=top_k)
            edges = [_edge_payload(edge) for edge in selected]
            trace = hg_trace.to_dict()
            backend = "hypergraph"
            if trace.get("seed_miss"):
                # §2.3 第 1 步：无种子 → digest 兜底并留痕，不得静默返回空。
                cards = with_digest_fallback(cards)
                trace["digest_fallback"] = True
        #: §2.3b 的**两通道路由**：超图那条恒用 `query`（约束串），案例层用
        #: `analogy_query`（散文）。**路由的判据在插件侧**（没有类比查询时它把
        #: `cases_top_k` 发成 0），这里保持对直连调用方的兼容：
        #: `analogy_query` 缺省时沿用 `query`，但 `cases_top_k=0` 就是**不查**。
        analogy = str(body.get("analogy_query") or "").strip() or query
        wanted_cases = int(body.get("cases_top_k", 3) or 3)
        cases = case_lane.retrieve(analogy, top_k=wanted_cases) if wanted_cases > 0 else []
        trace.update({
            "backend": backend,
            "lanes": case_lane.lanes,
            "cases_backend": case_lane.effective,
            "cases_requested_backend": case_lane.requested,
            "cases_degraded": bool(case_lane.degraded),
            "cases_degraded_reason": case_lane.reason,
            #: §2.3b：trace 必记 L3 的索引指纹（与超图的六元指纹分开落盘）。
            "lightrag_index_fingerprint": case_lane.lightrag_index_fingerprint,
            "cases_index_fingerprint": case_lane.fingerprint,
            "provenance": dict(provenance),
        })
        return RetrieveResponse(cards=cards, edges=edges, cases=cases, trace=trace)

    return Handler


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="sidecar_server")
    parser.add_argument("--host", default=LOOPBACK,
                        help="监听地址；§2.5 要求只监听回环")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--upstream", default="http://127.0.0.1:11434")
    parser.add_argument("--upstream-kind", choices=("auto", "ollama", "openai"),
                        default="auto")
    parser.add_argument("--model", default="qwen3-vl:30b")
    parser.add_argument("--num-ctx", type=int, default=32768,
                        help="Ollama 的上下文窗口；默认 4096 会装不下思维链")
    parser.add_argument("--think", choices=("off", "on", "default"),
                        default="off",
                        help="思维链：结构化工具调用任务关掉更省预算")
    parser.add_argument("--reasoning-effort", default="",
                        help="OpenAI 兼容上游的 `reasoning_effort`（如 `max`，用户 2026-10-07"
                             "「新模型思考强度拉到最大」）；默认空 = 不发这个键，"
                             "历史行为一字不变（`thinking.level` 在新模型上会被忽略："
                             "work/_probe_qwen_thinking.py）")
    parser.add_argument("--tool-choice-mode", choices=("passthrough", "auto", "drop"),
                        default="passthrough",
                        help="`tool_choice` 的供应商翻译：passthrough（默认，逐字节透传）/"
                             "auto（把 required 与对象改写成 auto——百炼等上游在**思考模式**"
                             "下拒收 required，见 _openai_body 的注释）/ drop（整格不发）")
    parser.add_argument("--strict-tools", action="store_true",
                        help="strict 工具调用（G2 判据 #8，DeepSeek Beta）：转发体给每个 "
                             "function 加 strict:true、parameters 转 to_strict、走 /beta "
                             "端点、回包 strip_nulls。启动要求 --strict-probe 的探针 "
                             "verdict=pass、模型一致、supported_keywords 覆盖本仓 schema "
                             "用到的关键字，否则退出码 2（绝不静默退回非严格模式）")
    parser.add_argument("--strict-probe", default="",
                        help="tools/probe_strict_tools.py 产出的实测探针 JSON 路径"
                             "（--strict-tools 时必填）")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="抽取/规划要求确定性，默认 0（v1.4 §2.3d T6）")
    parser.add_argument("--seed", type=int, default=0,
                        help="解码随机种子，默认 0（v1.4 §2.3d T6）")
    parser.add_argument("--knowledge-dir", default=str(DEFAULT_KNOWLEDGE_DIR),
                        help="知识索引目录（hypergraph.*.jsonl / cases.jsonl）")
    parser.add_argument("--cases-backend", choices=CASE_LANES, default="lightrag",
                        help="L3 案例通道（§2.3b）；lightrag 不可用时降级 hybrid")
    parser.add_argument("--cases-filter", choices=("off", "llm"), default="off",
                        help="L3 案例的相关性过滤（2026-10-03 加）：llm 用上游模型把"
                             "明显无关的案例剔除。**默认 off**：三次实测都不如不过滤"
                             "（离线实验 3/7=0.429 看着好，但走真正的产品路径两次都更差——"
                             "宽提示 1/11=0.091，严提示把 6 条查询里的 5 条清空成 0/1，"
                             "见 ACCEPTANCE_STATUS.md §三十二）。过滤器只做减法，"
                             "失败时退回未过滤结果并在 trace 里记账。")
    parser.add_argument("--token", default="")
    parser.add_argument("--upstream-api-key-env", default="",
                        help="上游 API 密钥所在的**环境变量名**（不传密钥本身）。"
                             "云端 OpenAI 兼容端点（智谱 GLM 等）必须给；"
                             "本地 Ollama 留空。密钥不进仓库、不进日志。")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--once", action="store_true",
                        help="处理一个请求后退出（测试用）")
    args = parser.parse_args(argv)
    if args.upstream_kind == "auto":
        args.upstream_kind = detect_kind(args.upstream)
    if args.host not in (LOOPBACK, "localhost"):
        parser.error("§2.5 要求 sidecar 只监听回环地址（127.0.0.1）")
    return args


def main(argv) -> int:
    args = parse_args(argv)
    config = SidecarConfig(args)
    try:
        check_strict_startup(args, config)
    except StrictStartupRefused as exc:
        print(f"sidecar startup refused: {exc}", file=sys.stderr)
        raise SystemExit(2)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(config))
    print(json.dumps({"sidecar": "listening", "host": args.host,
                      "port": server.server_address[1],
                      "upstream": config.upstream, "kind": config.kind,
                      "model": config.model, "num_ctx": config.num_ctx,
                      "think": config.think,
                      "strict_tools": config.strict_tools,
                      "temperature": config.temperature,
                      "seed": config.seed,
                      "knowledge_dir": str(config.knowledge_dir),
                      "cases_backend": config.cases_backend,
                      "capabilities": [str(item) for item in config.capabilities],
                      "url": f"http://{args.host}:{args.port}"},
                     ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
