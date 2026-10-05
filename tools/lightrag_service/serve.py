"""sidecar 的 HTTP 服务层：**只绑本机**，把索引的 top-k 交给插件。

索引是**注入**的（任何有 `search(query, top_k)`／`fingerprint`／`version` 的对象），
所以这一层能离线测——LightRAG 本体只在 `build_index.py` 里出现。

线协议（与 `block_director/knowledge/lightrag_client.py` 两侧对拍）：

* `GET  /health` → `{"status","index_fingerprint","lightrag_version"}`
* `POST /query`  `{"query","top_k"}` → `{"hits":[{"case_id","score"},...]}`

**fail closed**：给了 `expected_fingerprint` 而索引对不上 ⇒ 两个端点都回
`503` ＋ 具名 `reason`（`index_fingerprint_mismatch`），**绝不拿脏索引出数**。
索引自己抛错 ⇒ `500` ＋ `index_error:<类型>`，也不伪装成"成功空列表"。
"""

from __future__ import annotations

import json
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

#: 只绑环回——这是个只给本机插件用的服务。
HOST = "127.0.0.1"


def _mismatch_reason(index: Any, expected: str) -> Optional[str]:
    if not expected:
        return None
    got = str(getattr(index, "fingerprint", "") or "")
    if got != expected:
        return "index_fingerprint_mismatch:%s!=%s" % (got, expected)
    return None


def make_handler(index: Any, *, expected_fingerprint: str = "") -> type:
    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # 静音：sidecar 的日志由调用方自己留
            pass

        def _send(self, payload: Dict, code: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _guarded(self) -> bool:
            reason = _mismatch_reason(index, expected_fingerprint)
            if reason:
                self._send({"status": "refused", "reason": reason}, 503)
                return False
            return True

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") != "/health":
                self._send({"status": "refused",
                            "reason": "unknown_path:%s" % self.path}, 404)
                return
            if not self._guarded():
                return
            self._send({"status": "ok",
                        "index_fingerprint": str(getattr(index, "fingerprint", "") or ""),
                        "lightrag_version": str(getattr(index, "version", "") or "")})

        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != "/query":
                self._send({"status": "refused",
                            "reason": "unknown_path:%s" % self.path}, 404)
                return
            if not self._guarded():
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads((self.rfile.read(length) or b"{}").decode("utf-8"))
            except ValueError as exc:
                self._send({"status": "refused", "reason": "bad_request:%s" % exc}, 400)
                return
            query = str(payload.get("query") or "")
            top_k = int(payload.get("top_k") or 5)
            try:
                hits = index.search(query, top_k)
            except Exception as exc:  # noqa: BLE001 - 索引故障要具名，不许静默空列表
                self._send({"status": "error",
                            "reason": "index_error:%s" % type(exc).__name__}, 500)
                return
            self._send({"hits": [{"case_id": str(case_id), "score": float(score)}
                                 for case_id, score in hits]})

    return _Handler


def make_server(index: Any, *, port: int = 8765,
                expected_fingerprint: str = "") -> ThreadingHTTPServer:
    """建服务。**只绑 `127.0.0.1`**——这是给本机插件用的口。"""
    return ThreadingHTTPServer((HOST, int(port)),
                               make_handler(index,
                                            expected_fingerprint=expected_fingerprint))


def main(argv: Optional[list] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="lightrag_service.serve")
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--expected-fingerprint", default="")
    parser.add_argument("--mode", default="naive",
                        choices=("naive", "local", "global", "hybrid", "mix"),
                        help="上游检索模式；non-naive 需要**非空图谱**")
    parser.add_argument("--query-timeout", type=float, default=None,
                        help="单次 /query 的超时秒数（默认取索引的 DEFAULT_QUERY_TIMEOUT）；"
                             "超时 ⇒ 500 index_error:TimeoutError，绝不伪装成空列表")
    args = parser.parse_args(list(argv) if argv is not None else None)

    from . import build_index as bi  # noqa: PLC0415 - 重模块（要 lightrag）延后导入
    kwargs = {"mode": args.mode}
    if args.query_timeout is not None:
        kwargs["query_timeout"] = float(args.query_timeout)
    index = bi.LightRAGIndex(pathlib.Path(args.index_dir), **kwargs)
    server = make_server(index, port=args.port,
                         expected_fingerprint=args.expected_fingerprint)
    print(json.dumps({"status": "serving", "host": HOST, "port": args.port,
                      "mode": index.mode, "index_fingerprint": index.fingerprint},
                     ensure_ascii=False))
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        #: 停掉索引自持的常驻事件循环（没有它也只是留下一条守护线程，但退出要干净）。
        close = getattr(index, "close", None)
        if callable(close):
            close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
