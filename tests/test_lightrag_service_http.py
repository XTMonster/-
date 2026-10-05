"""P7：sidecar 的 HTTP 服务层（**索引可注入**，所以这一层能离线测）。

三条不变量：

1. `/health` 回**索引指纹**与上游版本——插件据此决定要不要查（fail closed）；
2. `/query` 回合约形状 `{"hits":[{"case_id","score"},…]}`，且**只绑本机**；
3. 指纹不匹配时**拒绝服务**（503 ＋ 具名原因），而不是拿脏索引给出"看起来正常"的答案。
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.lightrag_service import serve as sv  # noqa: E402


class _StubIndex:
    """替身索引：真实实现的接口面（`search` ＋ `fingerprint` ＋ `version`）。"""

    def __init__(self, *, fingerprint: str = "fp-1", fail: bool = False) -> None:
        self.fingerprint = fingerprint
        self.version = "1.5.7"
        self.fail = fail
        self.calls = []

    def search(self, query: str, top_k: int):
        self.calls.append((query, top_k))
        if self.fail:
            raise RuntimeError("index broken")
        return [("case_1", 0.9), ("case_2", 0.4)][:top_k]


def _start(index, **kwargs):
    server = sv.make_server(index, port=0, **kwargs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        #: 503/500 也是**合约的一部分**（fail closed / 具名错误），要能读到回包。
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post(url: str, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_health_reports_the_fingerprint_and_the_upstream_version():
    server, base = _start(_StubIndex())
    try:
        status, payload = _get(base + "/health")
        assert status == 200
        assert payload["status"] == "ok"
        assert payload["index_fingerprint"] == "fp-1"
        assert payload["lightrag_version"] == "1.5.7"
    finally:
        server.shutdown()


def test_query_returns_hits_in_the_contract_shape():
    index = _StubIndex()
    server, base = _start(index)
    try:
        status, payload = _post(base + "/query", {"query": "越轴", "top_k": 2})
        assert status == 200
        assert payload["hits"] == [{"case_id": "case_1", "score": 0.9},
                                   {"case_id": "case_2", "score": 0.4}]
        assert index.calls == [("越轴", 2)]
    finally:
        server.shutdown()


def test_a_mismatched_expected_fingerprint_makes_the_service_refuse():
    """fail closed：指纹对不上就 503 ＋ 具名原因，**绝不**拿脏索引出数。"""
    server, base = _start(_StubIndex(fingerprint="fp-1"),
                          expected_fingerprint="fp-OTHER")
    try:
        status, payload = _get(base + "/health")
        assert status == 503 and payload["reason"].startswith("index_fingerprint_mismatch")
        status, payload = _post(base + "/query", {"query": "x", "top_k": 1})
        assert status == 503 and payload["reason"].startswith("index_fingerprint_mismatch")
    finally:
        server.shutdown()


def test_the_server_binds_loopback_only():
    server, _base = _start(_StubIndex())
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.shutdown()


def test_an_index_error_becomes_a_named_500_not_a_silent_empty_list():
    server, base = _start(_StubIndex(fail=True))
    try:
        status, payload = _post(base + "/query", {"query": "x", "top_k": 1})
        assert status == 500
        assert payload["reason"].startswith("index_error:")
    finally:
        server.shutdown()


def test_a_query_timeout_becomes_a_named_500_not_a_silent_empty_list():
    """2026-10-05：`LightRAGIndex.search` 现在因超时抛 `TimeoutError`（常驻循环 ＋
    `query_timeout`）。服务层必须把它翻成具名的 `index_error:TimeoutError`——
    "卡死"与"没结果"是两件不同的事，绝不能都变成 `{"hits":[]}`。"""

    class _SlowIndex:
        fingerprint = "fp-1"
        version = "1.5.7"

        def search(self, query: str, top_k: int):
            raise TimeoutError("lightrag 检索超时（2 s）")

    server, base = _start(_SlowIndex())
    try:
        status, payload = _post(base + "/query", {"query": "x", "top_k": 1})
        assert status == 500
        assert payload["reason"] == "index_error:TimeoutError"
    finally:
        server.shutdown()
