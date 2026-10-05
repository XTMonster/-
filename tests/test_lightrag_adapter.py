"""P7：插件侧的 LightRAG 适配器（契约 `retrieve(query, *, top_k, cases)`）。

三条不变量（都对着本项目踩过的坑写）：

1. **返回的是 `cases` 的子序列**：服务端返回的 id 只要不在传入的案例集合里，
   就丢弃并具名记账——`docs/adr/0014` 的"陈旧化陷阱"正是在这里。
2. **服务不可达时降级要留痕**：`last_reason` 写具名原因（`sidecar_unreachable`），
   由上层回落默认路由；返回空列表而不是"成功的空结果"。
3. **回路要真的走 HTTP**：测试用一个 stdlib 起的桩服务端，不 mock 掉网络层
   （否则"接线对不对"这件事根本没被验过）。
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.knowledge import Case  # noqa: E402
from block_director.knowledge import lightrag_client as lc  # noqa: E402
from block_director.knowledge import lightrag_adapter as la  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    hits: list = []
    reply: dict = {"hits": [{"case_id": "case_1", "score": 0.9},
                            {"case_id": "case_ghost", "score": 0.8}]}

    def log_message(self, *args):  # 静音
        pass

    def _send(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        _Handler.hits.append(("GET", self.path))
        self._send({"status": "ok", "index_fingerprint": "fp", "lightrag_version": "1.5.7"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) or b"{}"
        _Handler.hits.append(("POST", self.path, json.loads(raw.decode("utf-8"))))
        self._send(_Handler.reply)


def _serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


def _case(case_id: str) -> Case:
    return Case(case_id=case_id, case_type="narrative", title="t", excerpt="e",
                source_ref={})


def test_the_client_round_trips_health_and_query():
    server, base = _serve()
    try:
        health = lc.health(base)
        assert health["status"] == "ok"
        hits = lc.query(base, "越轴怎么办", top_k=3)
        assert hits[0]["case_id"] == "case_1"
        #: 请求体里必须带 query 与 top_k（契约）。
        posted = [item for item in _Handler.hits if item[0] == "POST"][-1]
        assert posted[2]["query"] == "越轴怎么办" and posted[2]["top_k"] == 3
    finally:
        server.shutdown()


def test_the_adapter_returns_only_cases_it_was_given():
    server, base = _serve()
    try:
        adapter = la.make_lightrag_adapter(base_url=base)
        cases = [_case("case_1"), _case("case_2")]
        out = adapter.retrieve("越轴", top_k=3, cases=cases)
        assert [case.case_id for case in out] == ["case_1"]
        assert adapter.last_reason == "unknown_id_dropped:1"   # 幽灵 id 具名记账
    finally:
        server.shutdown()


def test_an_unreachable_service_degrades_with_a_named_reason():
    adapter = la.make_lightrag_adapter(base_url="http://127.0.0.1:1")   # 没人监听
    out = adapter.retrieve("越轴", top_k=3, cases=[_case("case_1")])
    assert out == []
    assert adapter.last_reason.startswith("sidecar_unreachable:")


def test_the_manifest_mismatch_fails_closed_with_its_own_reason():
    server, base = _serve()
    try:
        adapter = la.make_lightrag_adapter(base_url=base, expected_fingerprint="别的指纹")
        out = adapter.retrieve("越轴", top_k=3, cases=[_case("case_1")])
        assert out == []
        assert adapter.last_reason.startswith("index_fingerprint_mismatch")
    finally:
        server.shutdown()
