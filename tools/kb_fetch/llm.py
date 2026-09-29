"""极小的 JSON 模式 LLM 客户端（开发侧）。

支持三种后端：

* `deepseek` —— OpenAI 兼容端点（`/chat/completions`，`response_format=json_object`）；
* `ollama`   —— 本地 `qwen3-vl:30b`（`/api/chat`，`format=json`）；
* `scripted` —— 离线：从 JSON 文件里按 chunk_id 取预置回答，**测试专用**，
  跑测试时不碰网络。

抽取与标注必须**换族**（§2.3c 第 1 条）：抽取用 deepseek、标注用 qwen，
两边都记 `{model_id, model_version, family}`。
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.request
from typing import Dict, Optional

DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

FAMILIES = {
    "deepseek": "deepseek",
    "ollama": "qwen",
    "scripted": "scripted",
}


class LLMError(RuntimeError):
    pass


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

    def chat_json(self, system: str, user: str, temperature: float, seed: int,
                  num_ctx: int, key: str = "", retries: int = 3) -> Dict:
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
                content = reply["choices"][0]["message"]["content"]
                return json.loads(content)
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"deepseek 调用失败：{last}")


class OllamaClient:
    family = "qwen"

    def __init__(self, model_id: str = "qwen3-vl:30b"):
        self.model_id = model_id
        self.model_version = model_id

    def chat_json(self, system: str, user: str, temperature: float, seed: int,
                  num_ctx: int, key: str = "", retries: int = 2) -> Dict:
        # 本地 30B 的"思考"会吃掉大量上下文（§21.10 的实测），这里显式关掉。
        payload = {
            "model": self.model_id,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": temperature, "seed": seed, "num_ctx": num_ctx},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                reply = _post_json(f"{OLLAMA_BASE}/api/chat", payload,
                                   {"Content-Type": "application/json"}, 1800.0)
                content = reply["message"]["content"]
                self.model_version = str(reply.get("model") or self.model_id)
                return json.loads(content)
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
    raise LLMError(f"未知 provider: {provider!r}")
