"""极小的 JSON 模式 LLM 客户端（开发侧）。

支持三种后端：

* `deepseek` —— OpenAI 兼容端点（`/chat/completions`，`response_format=json_object`）；
* `ollama`   —— 本地 `qwen3-vl:30b`，**只走 OpenAI 兼容端点 `/v1/chat/completions`**；
* `scripted` —— 离线：从 JSON 文件里按 chunk_id 取预置回答，**测试专用**，
  跑测试时不碰网络。

抽取与标注必须**换族**（§2.3c 第 1 条）：抽取用 deepseek、标注用 qwen，
两边都记 `{model_id, model_version, family}`。

**端点与上下文（执行文档 v1.4 §6 的"端点陷阱"，本机实测，证据见 `work/probe_*.py`）**：

* `qwen3-vl:30b` 是**思考模型**：它先写 thinking 再写正文。答案要 >1000 completion
  tokens 才出得来。
* Ollama 的 OpenAI 兼容端点 `/v1/chat/completions` **不认 `num_ctx`**，用模型**上次
  加载时**的上下文（默认 4096）。于是 prompt ＋ thinking 直接撑爆 4096 →
  `finish_reason=length`、`content` 为空。
* 原生 `/api/chat` 的 `options.num_ctx` 才真正设置上下文；`think:false` 在本机被忽略
  （模型照样思考），但**只要上下文够大**，它思考完就会写出正文（实测 ctx=8192 时
  42 s／次拿到内容；ctx=4096 时恒空）。

所以本地客户端走 `/api/chat` ＋ 显式 `options.num_ctx`，并把「`content` 为空」判成
**调用失败**（可重试）——绝不把空串喂给 `json.loads`，也绝不把空结果写成空边/空标注。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request
from typing import Dict, Optional

DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
#: 智谱 GLM（OpenAI 兼容端点，`/api/paas/v4/chat/completions`）。§2.3c 的换族要求是
#: "标注 family ≠ 抽取 family"（抽取走 deepseek），GLM 是独立厂商族 → `independence: strong`。
#: 密钥只从环境变量读：**绝不写进仓库**（`GLM_API_KEY`）。
GLM_BASE = os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
GLM_API_KEY = os.environ.get("GLM_API_KEY", "")
#: 思考开关与预算（用户裁决"思考强度直接拉满"）。
#: 实测（raw 探针）：`glm-4.7` 关思考时 6 卡/批 ≈ 40 秒、通过率 0.94–1.0；
#: 开思考且 `max_tokens=32768` 时**思考 6.5k–6.9k token、正文 12–14k 字符**、
#: `finish_reason=stop`，12 卡/批约 5 分钟——质量优先就走这条。
#: `max_tokens=16384` 会**截断**（实测思考 15068 token、正文被切断）。
#: 思考档位。用户要"拉满"，但实测**上限档跑不完**：`glm-5.3-flash` + `level=max`
#: 在 3 张卡的小批上思考 12.4 分钟、烧掉整整 32768 个 completion token
#: （`reasoning_tokens=32306`、`finish_reason=length`）、**正文一个字都没有** ⇒
#: 每一次调用都是失败。`enabled`（不开 level）实测：`glm-4.6` 上 3 张卡思考 9.5k
#: token、4.7 分钟、`finish_reason=stop`、正文 3607 字符 ✓。
#: 所以默认取"能跑完的最高档" = `enabled`；`GLM_THINKING=max|high|low|disabled`
#: 仍可显式切换（`glm-5.3` 那类只认 `{"type":"enabled","level":"…"}`）。
GLM_THINKING = os.environ.get("GLM_THINKING", "enabled").strip().lower()
GLM_MAX_TOKENS = int(os.environ.get("GLM_MAX_TOKENS", "32768"))
#: 单次调用的读超时。默认 1800 秒是给"思考拉满"的模型留的；但实测一次 31 分钟的
#: 长跑会**卡在一次调用上**（进程 CPU 60 秒增量为 0），而客户端 `retries=3` 意味着
#: 最坏情况要等 90 分钟才放弃。批处理通道（如 `tools/holdout_pool.py --provider glm`）
#: 可以把 `GLM_TIMEOUT` 调小，让坏调用快速失败并被记成一条 reject 而不是拖死整轮。
GLM_TIMEOUT = float(os.environ.get("GLM_TIMEOUT", "1800"))

#: **第三方裁决通道**：阿里云百炼（DashScope）的 OpenAI 兼容端点。
#: 用户 2026-10-05 指示："如果需要人工裁决，这边我想用第三方的ai进行裁决"，
#: 并指定 `qwen3.8-max-0902`（实测：端点 `dashscope.aliyuncs.com/compatible-mode/v1`，
#: key 有**按模型的白名单**（`qwen3-max` 会被 403 拒），见 `work/_probe_qwen_endpoint.py`／
#: `work/_list_qwen_models.py`）。它既不是抽取器（deepseek）也不是标注器（zhipu），
#: 所以拿它做复核／裁决时 `independence` 是**真·第三方**。密钥只从 `QWEN_API_KEY` 读。
QWEN_BASE = os.environ.get("QWEN_BASE_URL",
                           "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "")
QWEN_TIMEOUT = float(os.environ.get("QWEN_TIMEOUT", "900"))

#: 本地思考模型的**思考税**实测（v1.4 §6 那条风险）没法用官方开关关掉：
#: `/no_think`（写进 user 或 system）、`think: false`、精简词表都试过，`num_predict`
#: 2048 时一律 `content_len=0 / thinking_len≈3400 / done_reason=length`；把预算加到
#: 6144 也一样（thinking 16000 字符、content 仍为空）。
#:
#: 但给 `/api/chat` 补一个 **assistant 预填**（JSON 的开头）就能直接绕开：
#: 实测同模型同 prompt → `4.7s / eval_count=355 / content_len=962 / thinking_len=0 /
#: done_reason=stop`。因此这里留一个**默认关闭**的开关：只有显式设了
#: `OLLAMA_ASSISTANT_PREFILL` 才追加这个 assistant 回合，既有调用行为不变。
OLLAMA_PREFILL = os.environ.get("OLLAMA_ASSISTANT_PREFILL", "")

FAMILIES = {
    "deepseek": "deepseek",
    "ollama": "qwen",
    "glm": "zhipu",
    "qwen": "qwen",
    "scripted": "scripted",
}


class LLMError(RuntimeError):
    pass


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL)


def parse_json_content(content: str) -> Dict:
    """把模型返回的正文解析成 JSON 对象；空正文**立即判失败**。

    空串（或只有空白／只有代码围栏）是"端点陷阱"的典型症状，必须当成调用失败
    抛出，交给调用方的重试逻辑——而不是让 `json.loads("")` 抛一个语焉不详的
    `JSONDecodeError`，更不是"返回 {} 当作成功"。
    """
    text = (content or "").strip()
    if not text:
        raise LLMError("模型返回的空正文（endpoint trap：内容可能全在 thinking 字段里）")
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group("body").strip()
        if not text:
            raise LLMError("模型返回的代码围栏内为空")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型返回的不是合法 JSON：{exc.msg}（前 120 字：{text[:120]!r}）") from exc
    if not isinstance(payload, dict):
        raise LLMError(f"模型返回的 JSON 顶层不是对象：{type(payload).__name__}")
    return payload


def _post_json(url: str, payload: Dict, headers: Dict[str, str], timeout: float) -> Dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - 网络分支
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise LLMError(f"HTTP {exc.code}: {detail}") from exc


class ScriptedClient:
    """离线替身：`responses` 是 {chunk_id: {"cards": [...]}}。"""

    family = "scripted"

    def __init__(self, model_id: str, path: pathlib.Path):
        self.model_id = model_id
        self.model_version = "scripted"
        payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        self.responses: Dict[str, Dict] = payload.get("responses", payload)

    def chat_json(self, system: str, user: str, temperature: float, seed: int,
                  num_ctx: int, key: str = "", retries: int = 1) -> Dict:
        if key and key in self.responses:
            payload = self.responses[key]
            # 预置回答既可以是卡片数组（抽取用），也可以是完整的响应对象
            # （如 held-out 的 {"entries": [...]}）。
            return payload if isinstance(payload, dict) else {"cards": payload}
        return {"cards": []}


class DeepSeekClient:
    family = "deepseek"

    def __init__(self, model_id: str = "deepseek-chat", api_key: Optional[str] = None):
        self.model_id = model_id
        self.model_version = model_id
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise LLMError("缺少 DEEPSEEK_API_KEY")
        self._seen_model = ""
        self.last_usage: Dict[str, int] = {}

    def chat_json(self, system: str, user: str, temperature: float, seed: int,
                  num_ctx: int, key: str = "", retries: int = 5) -> Dict:
        payload = {
            "model": self.model_id,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "seed": seed,
            #: 4096 是**不够的**（2026-10-03 实测）：`extract/v18` 要求每个成员再带一句
            #: 逐字原句，回复长度随之上涨，最大的那一批（8 张卡 × 数条边 × 中文原句）
            #: 会被**截断**——`batch 238` 连续 5 次重试都返回非法 JSON，
            #: Q0 的 `processed != total` 因此判红，那 8 张卡整批丢掉。
            #: `decode` 那一行本来就写着 `ctx=8192`，这里与它对齐。
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
        }
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                reply = _post_json(f"{DEEPSEEK_BASE}/chat/completions", payload,
                                   {"Content-Type": "application/json",
                                    "Authorization": f"Bearer {self.api_key}"}, 180.0)
                self._seen_model = str(reply.get("model") or self.model_id)
                self.model_version = self._seen_model
                usage = reply.get("usage") or {}
                self.last_usage = {
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                }
                choices = reply.get("choices") or []
                if not choices:
                    raise LLMError("上游没有返回 choices")
                message = choices[0].get("message") or {}
                return parse_json_content(message.get("content") or "")
            except Exception as exc:  # noqa: BLE001
                last = exc
                #: **解析失败要换一次取样**（2026-10-03 实测）：`extract/v18` 要求每个成员
                #: 再带一句逐字原句之后，模型偶发把 `members` 数组写坏（`[[…]]` 少一个成员
                #: 就闭合）。`temperature=0` 下 5 次重试会**逐字重放同一个坏回复**，
                #: 于是整整一批卡（8 张）无谓地丢掉、Q0 的 `processed != total` 判红。
                #: 传输错误仍然按原温度重试（那一类与"取样"无关），
                #: 只有**解析失败**才把温度往上抬一点——与 `holdout_pool` 的缺口轮同一理由：
                #: 只换取样，不改判据。
                if isinstance(exc, LLMError) and "不是合法 JSON" in str(exc):
                    payload["temperature"] = min(float(temperature) + 0.2 * (attempt + 1), 1.0)
                #: 实测：多进程并发打 GLM 会拿到 `HTTP 429 code=1302`（并发上限）。
                #: 429 一律**长退避**，否则整批会被限流吃掉（实测 4 个并发进程时
                #: 单进程的产出从 18 条/批掉到 1.5 条/批）。
                throttled = "429" in str(exc)
                time.sleep((20.0 if throttled else 1.5) * (attempt + 1))
        raise LLMError(f"deepseek({self.model_id}) 调用失败：{last}")


class GLMClient:
    """智谱 GLM（OpenAI 兼容端点）。标注通道的第二族：`family = "zhipu"`。

    与本地 30B 的区别（实测）：它不吃"思考税"、指令遵循好得多，也不需要预填；
    接口形状与 DeepSeek 一致（`choices[0].message.content`），因此复用 `parse_json_content`
    与"空正文即判失败"的纪律。
    """

    family = "zhipu"

    #: 用户裁决（2026-10-04）：GLM 只用 `glm-5.3`（智谱按模型分别计费，只有它还有额度）。
    def __init__(self, model_id: str = "glm-5.3", api_key: str = ""):
        self.model_id = model_id
        self.model_version = model_id
        self.api_key = api_key or GLM_API_KEY
        self.thinking = GLM_THINKING
        self.max_tokens = GLM_MAX_TOKENS
        self.last_usage: Dict[str, int] = {}

    @property
    def decode_tag(self) -> str:
        """解码条件的可读指纹——进续跑指纹与 `annotator.decode`，避免混解。"""
        return f"thinking={self.thinking};max_tokens={self.max_tokens}"

    def _thinking_payload(self) -> Dict:
        """`glm-5.3-flash`／`glm-5.3` 这类"始终思考"的模型只认
        `{"type":"enabled","level":"low|high|max"}`（实测 `{"type":"max"}` 会 400）。"""
        if self.thinking == "disabled":
            return {"type": "disabled"}
        if self.thinking in ("low", "high", "max"):
            return {"type": "enabled", "level": self.thinking}
        return {"type": "enabled"}

    def chat_json(self, system: str, user: str, temperature: float, seed: int,
                  num_ctx: int, key: str = "", retries: int = 3) -> Dict:
        if not self.api_key:
            raise LLMError("缺少 GLM_API_KEY（只从环境变量读，绝不写进仓库）")
        payload = {
            "model": self.model_id,
            "stream": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            #: 每张卡 4 条 × 一批 12 张 ≈ 48 条，32k 预算给思考＋正文都留足。
            "max_tokens": self.max_tokens,
            #: 默认档是 `GLM_THINKING` 的缺省值 `enabled`（`{"type":"enabled"}`）——
            #: 实测 `level=max` 在 `glm-5.3-flash` 上 3 卡小批思考 12.4 分钟、
            #: 正文一个字都没有（`finish_reason=length`），所以取"能跑完的最高档"。
            #: `glm-4.7` 实测：开思考时 reasoning 6.5k–6.9k token、正文 12–14k 字符、
            #: `finish_reason=stop`；关思考（`{"type":"disabled"}`）~40 秒出结果、
            #: 通过率 0.94–1.0。
            "thinking": self._thinking_payload(),
        }
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                reply = _post_json(f"{GLM_BASE}/chat/completions", payload,
                                   {"Content-Type": "application/json",
                                    #: 思考拉满时单次调用会超过 5 分钟（实测 6 卡一批就
                                    #: 打穿了 300 秒的读超时）——给到 30 分钟。
                                    "Authorization": f"Bearer {self.api_key}"}, GLM_TIMEOUT)
                choices = reply.get("choices") or []
                if not choices:
                    raise LLMError("上游没有返回 choices")
                usage = reply.get("usage") or {}
                self.last_usage = {
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                }
                self.model_version = str(reply.get("model") or self.model_id)
                message = choices[0].get("message") or {}
                return parse_json_content(message.get("content") or "")
            except Exception as exc:  # noqa: BLE001
                last = exc
                #: "该模型始终思考，不支持关闭思考"（code 1210）→ 换成 max 档再来，
                #: 免得"换了新一代模型"被当成调用失败。
                if "1210" in str(exc) and self.thinking == "disabled":
                    self.thinking = "max"
                    payload["thinking"] = self._thinking_payload()
                    continue
                #: 并发打 GLM 会拿到 `HTTP 429`（1302 速率 / 1305 模型忙）：长退避。
                time.sleep((20.0 if "429" in str(exc) else 1.5) * (attempt + 1))
        #: 错误串必须带型号：`1113` 的字面是「余额不足 **或** 无可用资源包」，而智谱的
        #: 资源包**按模型分别计费**——不带型号的日志会被读成"整个账户没钱"。
        #: 2026-10-04 就是这么误判过一次（把 `glm-4.7` 的 429 当成了这条 key 耗尽，
        #: 而本账号的包其实是 `glm-5.3` 的），见 `docs/knowledge/ACCEPTANCE_STATUS.md` §七十八。
        raise LLMError(f"glm({self.model_id}) 调用失败：{last}")


class QwenClient:
    """阿里云百炼（DashScope）兼容模式 —— **第三方裁决通道**（`family = "qwen"`）。

    接口形状与 `GLMClient` 一致（`chat_json` ＋ `last_usage` ＋ `decode_tag`），
    所以调用方不必为它写第二套。与 GLM 的两处差别：

    * 端点是 OpenAI 兼容的 `/chat/completions`，但**key 有按模型的白名单**——
      不在包内的型号会被 `403 access_denied`（实测 `qwen3-max` 如此，
      `qwen3.8-max-0902` 可用）；所以这条通道**不许静默换型号**，失败就具名抛。
    * 它是**思考模型**（`reasoning_tokens` 与正文分开），所以 `num_ctx` 只当
      `max_tokens` 用，正文仍走 `parse_json_content`（空正文立刻判失败）。
    """

    family = "qwen"

    def __init__(self, model_id: str = "qwen3.8-max-0902", api_key: str = ""):
        self.model_id = str(model_id or "qwen3.8-max-0902")
        self.model_version = self.model_id
        self.api_key = api_key or QWEN_API_KEY
        self.last_usage: Dict[str, int] = {}

    @property
    def decode_tag(self) -> str:
        """解码条件的可读指纹（这条通道没有档位开关，如实写）。"""
        return "thinking=default;max_tokens=num_ctx"

    def chat_json(self, system: str, user: str, temperature: float, seed: int,
                  num_ctx: int, key: str = "", retries: int = 3) -> Dict:
        if not self.api_key:
            raise LLMError("缺少 QWEN_API_KEY（只从环境变量读，绝不写进仓库）")
        payload = {
            "model": self.model_id, "stream": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature, "max_tokens": int(num_ctx),
        }
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                reply = _post_json(f"{QWEN_BASE}/chat/completions", payload,
                                   {"Content-Type": "application/json",
                                    "Authorization": f"Bearer {self.api_key}"},
                                   QWEN_TIMEOUT)
                choices = reply.get("choices") or []
                if not choices:
                    raise LLMError("上游没有返回 choices")
                usage = reply.get("usage") or {}
                self.last_usage = {
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0)}
                self.model_version = str(reply.get("model") or self.model_id)
                message = choices[0].get("message") or {}
                return parse_json_content(message.get("content") or "")
            except Exception as exc:  # noqa: BLE001 - 失败要具名，且不许静默换型号
                last = exc
                time.sleep((20.0 if "429" in str(exc) else 1.5) * (attempt + 1))
        raise LLMError(f"qwen({self.model_id}) 调用失败：{last}")


class OllamaClient:
    """本地标注器。走 `/api/chat` ＋ 显式 `num_ctx`（见模块 docstring 的实测结论）。"""

    family = "qwen"

    def __init__(self, model_id: str = "qwen3-vl:30b", num_ctx: int = 8192,
                 num_predict: int = 6144, prefill: str = ""):
        self.model_id = model_id
        self.model_version = model_id
        #: 上下文必须**显式**给：OpenAI 兼容端点的默认 4096 会把思考模型截在半路。
        self.num_ctx = int(num_ctx)
        self.num_predict = int(num_predict)
        #: assistant 预填（默认取 `OLLAMA_ASSISTANT_PREFILL`）；空串＝不预填。
        self.prefill = str(prefill if prefill is not None else "") or OLLAMA_PREFILL
        self.last_usage: Dict[str, int] = {}

    def chat_json(self, system: str, user: str, temperature: float, seed: int,
                  num_ctx: int, key: str = "", retries: int = 2) -> Dict:
        payload = {
            "model": self.model_id,
            "stream": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "options": {
                # 调用点传进来的 num_ctx 优先（它可以按任务调大），否则用构造时的值。
                "num_ctx": max(int(num_ctx or 0), self.num_ctx),
                "num_predict": self.num_predict,
                "temperature": temperature,
                "seed": seed,
                #: 实测：temperature=0 且不给重复惩罚时，本地 30B 在长 prompt 上会
                #: 退化成复读机，Ollama 直接 `HTTP 500: prediction aborted, token
                #: repeat limit reached`（一条条目都拿不到）。1.15 是常用档位。
                "repeat_penalty": 1.15,
                "repeat_last_n": 256,
            },
        }
        if self.prefill:
            # 预填助手回合＝把答案的开头替模型写好，思考税直接归零（见模块顶部实测）。
            payload["messages"].append({"role": "assistant", "content": self.prefill})
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                reply = _post_json(f"{OLLAMA_BASE}/api/chat", payload,
                                   {"Content-Type": "application/json"}, 1800.0)
                message = reply.get("message") or {}
                self.last_usage = {
                    "prompt_tokens": int(reply.get("prompt_eval_count") or 0),
                    "completion_tokens": int(reply.get("eval_count") or 0),
                }
                self.model_version = str(reply.get("model") or self.model_id)
                # 空 content 在这里就会抛 LLMError，被下面的 except 接住并重试。
                content = message.get("content") or ""
                if not content.strip() and (message.get("thinking") or ""):
                    raise LLMError(
                        "本地模型只产出 thinking 而没有正文（num_ctx 不足："
                        f"{payload['options']['num_ctx']}）")
                if self.prefill:
                    # 预填**不会**被回显：Ollama 只回新生成的续写（实测 head 是
                    # `\n  {\n "from_card": …`，tail 是 `]}`）。所以先按原文解析，
                    # 失败就把预填贴回去再解析——两次都失败才算这次调用失败。
                    try:
                        return parse_json_content(content)
                    except LLMError:
                        return parse_json_content(self.prefill + content)
                return parse_json_content(content)
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(2.0 * (attempt + 1))
        raise LLMError(f"ollama({self.model_id}) 调用失败：{last}")


def make_client(provider: str, model: str = "", scripted: str = ""):
    provider = provider.lower()
    if provider == "scripted":
        if not scripted:
            raise LLMError("scripted 后端需要 --scripted <json>")
        return ScriptedClient(model or "scripted", pathlib.Path(scripted))
    if provider == "deepseek":
        return DeepSeekClient(model or "deepseek-chat")
    if provider == "ollama":
        return OllamaClient(model or "qwen3-vl:30b")
    if provider == "glm":
        return GLMClient(model or "glm-5.3")
    if provider == "qwen":
        return QwenClient(model or "qwen3.8-max-0902")
    raise LLMError(f"未知 provider: {provider!r}")
