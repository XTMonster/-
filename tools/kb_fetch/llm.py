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
            "max_tokens": 4096,
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
                #: 实测：多进程并发打 GLM 会拿到 `HTTP 429 code=1302`（并发上限）。
                #: 429 一律**长退避**，否则整批会被限流吃掉（实测 4 个并发进程时
                #: 单进程的产出从 18 条/批掉到 1.5 条/批）。
                throttled = "429" in str(exc)
                time.sleep((20.0 if throttled else 1.5) * (attempt + 1))
        raise LLMError(f"deepseek 调用失败：{last}")


class GLMClient:
    """智谱 GLM（OpenAI 兼容端点）。标注通道的第二族：`family = "zhipu"`。

    与本地 30B 的区别（实测）：它不吃"思考税"、指令遵循好得多，也不需要预填；
    接口形状与 DeepSeek 一致（`choices[0].message.content`），因此复用 `parse_json_content`
    与"空正文即判失败"的纪律。
    """

    family = "zhipu"

    def __init__(self, model_id: str = "glm-4.7", api_key: str = ""):
        self.model_id = model_id
        self.model_version = model_id
        self.api_key = api_key or GLM_API_KEY
        self.last_usage: Dict[str, int] = {}

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
            #: 每张卡 4 条 × 一批 6 张 ≈ 24 条条目，4096 会截断；给足 8192。
            "max_tokens": 8192,
            #: 实测（`work` 里的 raw 探针）：`glm-4.7` 默认是**思考模型**——不关思考时
            #: 整段 `max_tokens` 都花在 `reasoning_content` 上、`content` 恒为空
            #: （`finish_reason=length`；4096 与 8192 都一样）。`{"thinking":
            #: {"type": "disabled"}}` 是**它唯一有效的关闭开关**（布尔写法会 400）：
            #: 关掉后 `finish_reason=stop`、`reasoning_len=0`、正文直接给 JSON。
            "thinking": {"type": "disabled"},
        }
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                reply = _post_json(f"{GLM_BASE}/chat/completions", payload,
                                   {"Content-Type": "application/json",
                                    "Authorization": f"Bearer {self.api_key}"}, 300.0)
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
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"glm 调用失败：{last}")


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
        raise LLMError(f"ollama 调用失败：{last}")


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
        return GLMClient(model or "glm-4.7")
    raise LLMError(f"未知 provider: {provider!r}")
