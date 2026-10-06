"""中转站通道（linkai.pics）的**单次 consult**——给 `tools/plan_writer.py` 当模型函数用。

为什么单独一个模块而不是塞进 `glm_consult.py`：那条通道有 `max→high→low` 的**档位阶梯**
（GLM 的"始终思考"要逐档降才能拿到正文），而中转站没有这个开关。
把两者写成同一个函数会让读者以为"可以换档"，所以这里只做**带退避的重试**，
签名与 `glm_consult.consult` 一致（便于 `plan_writer` 注入替换），但 `levels` 只被记录、不被使用。

实测（`work/_probe_linkai.py`）：`https://linkai.pics/v1` 的 `/v1/models` 列出
`codex-auto-review`／`gpt-5.5`／`gpt-5.6-{luna,sol,terra}`／`gpt-6-astra`／`gpt-6-luna`／
`gpt-6-sol`／`gpt-6.1-sol`；**必须带浏览器 UA**，否则 Cloudflare 直接 `403 code 1010`。
"""

from __future__ import annotations

import json
import sys
import time
from typing import List, Optional, Sequence, Tuple

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.glm_consult import ConsultFailed  # noqa: E402
from tools.kb_fetch import llm  # noqa: E402

DEFAULT_MODEL = llm.LINKAI_MODEL

#: **单次尝试的"无数据上限"**（秒）——它不是"总时长上限"，而是"socket 每次读的上限"。
#: 为什么必须有（2026-10-06 实测）：中转站的流式响应**没有 keepalive**，所以
#: "正在思考但没出字"与"请求被丢掉、永远不出字"在客户端**完全无法区分**。而 socket 超时是
#: **每次读**的超时 ⇒ 它实际上就是"多久没收到任何字节就放弃这次尝试"。
#: 实测（同一秒发出、同样 1.8 KB 的包、同样 `max_tokens`/`reasoning_effort`）：
#: 两个兄弟 **3.4 / 5.1 分钟**就回来了，第三个 **137 分钟零字节**（`dRead=0/40s`、`dCpu=0/40s`）。
#: 没有这个上限，那个静默请求会一直占着位置，直到调用方给的总超时——那曾经是 **6 小时**。
DEFAULT_ATTEMPT_TIMEOUT = 1800.0


def consult(messages: List[dict], *, model: str, max_tokens: int,
            levels: Sequence[str], temperature: float, timeout: float,
            api_key: Optional[str] = None,
            attempt_timeout: float = DEFAULT_ATTEMPT_TIMEOUT) -> Tuple[str, dict]:
    """要一次**有正文**的答复。**没有档位**：`levels` 原样记进 usage 只为对拍。

    `attempt_timeout` 是**每次尝试**的"无数据上限"（见上）。`timeout` 仍是**总预算**；
    两者取小：`min(timeout, attempt_timeout)`（`timeout=0` 时只看 `attempt_timeout`）。
    传 `attempt_timeout=0` 可退回"只受总预算约束"的旧行为（调用方自负其责）。
    """
    started = time.time()
    tried = []
    per_attempt = (float(attempt_timeout) if not timeout
                   else min(float(timeout), float(attempt_timeout))) if attempt_timeout \
        else float(timeout)
    for attempt in range(3):
        #: **每次尝试一个新客户端**：把上一次超时留下的 socket 彻底丢掉，不复用。
        client = llm.RelayClient(model, api_key=api_key or "", timeout=per_attempt)
        try:
            content = client.chat(messages[0]["content"], messages[1]["content"],
                                  temperature=temperature, num_ctx=max_tokens,
                                  retries=1)
        except Exception as exc:  # noqa: BLE001 - 失败要留证
            tried.append({"error": "%s: %s" % (type(exc).__name__, str(exc)[:160]),
                          "elapsed_s": round(time.time() - started, 1),
                          "attempt_timeout_s": per_attempt})
            time.sleep(2.0 * (attempt + 1))
            continue
        usage = {"model": client.model_version, "requested_model": model,
                 "max_tokens": max_tokens, "elapsed_s": round(time.time() - started, 1),
                 "usage": dict(client.last_usage), "finish_reason": "stop",
                 "levels_ignored": list(levels), "channel": "linkai-relay",
                 "attempt_timeout_s": per_attempt, "attempts": tried}
        return content, usage
    raise ConsultFailed("中转站没给出正文：" + json.dumps(tried, ensure_ascii=False), tried)
