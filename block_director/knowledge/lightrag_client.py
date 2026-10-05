"""sidecar 的 HTTP 客户端（**只用 stdlib**：插件进程不许有新依赖）。

**住在 `block_director/` 里是有意的**：插件包的 import 图必须自足，不许反向依赖
仓库根的 `tools/`。2026-10-05 实测踩过一次——适配器从 `tools.lightrag_service` 导入，
被架构守门 `tests/test_plugin_layering.py` 当场抓出来。

线协议（与 `specs/` 的契约同源，写死在这里以便两侧对拍）：

* `GET  /health` → `{"status","index_fingerprint","lightrag_version",...}`
* `POST /query`  `{"query","top_k"}` → `{"hits":[{"case_id","score"},...]}`

只用 `urllib.request`——插件跑在 Blender 自带的 Python 里，装不了任何新包。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, List

DEFAULT_TIMEOUT = 10.0


class SidecarError(RuntimeError):
    """sidecar 不可达或回包不合约（带具名原因，供 `last_reason` 用）。"""


def _get(url: str, timeout: float) -> Dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SidecarError("sidecar_unreachable:%s" % exc) from exc
    except ValueError as exc:
        raise SidecarError("sidecar_bad_json:%s" % exc) from exc


def _post(url: str, payload: Dict, timeout: float) -> Dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - 只打本机 loopback
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SidecarError("sidecar_unreachable:%s" % exc) from exc
    except ValueError as exc:
        raise SidecarError("sidecar_bad_json:%s" % exc) from exc


def health(base_url: str, *, timeout: float = DEFAULT_TIMEOUT) -> Dict:
    return _get(base_url.rstrip("/") + "/health", timeout)


def query(base_url: str, query_text: str, *, top_k: int = 5,
          timeout: float = DEFAULT_TIMEOUT) -> List[Dict]:
    """返回 `[{"case_id":…, "score":…}, …]`（**原样**，不过滤——过滤是适配器的事）。"""
    payload = _post(base_url.rstrip("/") + "/query",
                    {"query": str(query_text), "top_k": int(top_k)}, timeout)
    hits = payload.get("hits")
    if not isinstance(hits, list):
        raise SidecarError("sidecar_bad_payload:no_hits")
    out: List[Dict] = []
    for item in hits:
        if isinstance(item, dict) and item.get("case_id") is not None:
            out.append({"case_id": str(item["case_id"]),
                        "score": float(item.get("score") or 0.0)})
    return out
