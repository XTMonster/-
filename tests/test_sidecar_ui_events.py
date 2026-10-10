"""v1.7 卡 B1：`POST/GET /v1/ui/events`（环形缓冲 + 鉴权分层）。"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from collections import deque
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_server_ui_events_under_test",
        ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


def _start(monkeypatch, token: str = "",
           maxlen_override: Optional[int] = None) -> ThreadingHTTPServer:
    argv = ["--upstream-kind", "openai",
            "--upstream", "https://api.deepseek.com",
            "--model", "deepseek-v4-pro",
            "--token", token]
    config = sidecar.SidecarConfig(sidecar.parse_args(argv))
    if maxlen_override is not None:
        real_deque = deque
        monkeypatch.setattr(
            sidecar, "deque",
            lambda *args, **kwargs: real_deque(maxlen=maxlen_override))
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), sidecar.make_handler(config))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _base(httpd: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{httpd.server_address[1]}"


def _request(base: str, method: str, path: str,
             body: Optional[Dict[str, Any]] = None,
             token: str = "") -> tuple:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = (json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None else None)
    request = urllib.request.Request(base + path, data=data, headers=headers,
                                     method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(
                response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8", "replace"))


def _event(seq: int, kind: str = "state_change") -> Dict[str, Any]:
    return {"seq": seq, "ts": 0.0, "kind": kind, "state": "BUILDING",
            "shot_id": "shot_001", "payload": {"done": 1}}


def test_post_assigns_server_seq(monkeypatch):
    httpd = _start(monkeypatch)
    base = _base(httpd)
    for expected in (1, 2, 3):
        status, payload = _request(base, "POST", "/v1/ui/events",
                                   _event(seq=999))
        assert status == 200
        assert payload == {"accepted": True, "seq": expected}


def test_since_incremental(monkeypatch):
    httpd = _start(monkeypatch)
    base = _base(httpd)
    for _ in range(3):
        _request(base, "POST", "/v1/ui/events", _event(seq=0))
    status, payload = _request(base, "GET", "/v1/ui/events?since=0")
    assert status == 200
    assert [item["seq"] for item in payload["events"]] == [1, 2, 3]
    assert payload["latest_seq"] == 3
    status, payload = _request(base, "GET", "/v1/ui/events?since=2")
    assert [item["seq"] for item in payload["events"]] == [3]
    status, payload = _request(base, "GET", "/v1/ui/events?since=3")
    assert payload["events"] == [] and payload["latest_seq"] == 3


def test_unauthorized_401(monkeypatch):
    httpd = _start(monkeypatch, token="t")
    base = _base(httpd)
    assert _request(base, "GET", "/v1/ui/events")[0] == 401
    assert _request(base, "POST", "/v1/ui/events", _event(seq=1))[0] == 401
    assert _request(base, "GET", "/v1/ui/events", token="t")[0] == 200
    assert _request(base, "POST", "/v1/ui/events", _event(seq=1),
                    token="t")[0] == 200


def test_bad_shape_400(monkeypatch):
    httpd = _start(monkeypatch)
    base = _base(httpd)
    status, payload = _request(base, "POST", "/v1/ui/events",
                               {"seq": 1, "ts": 0.0})
    assert status == 400
    assert "error" in payload


def test_ring_buffer_evicts(monkeypatch):
    #: 生产 maxlen=2000 写死；用 monkeypatch 把工厂压成 3 来验环形淘汰语义
    #: （不注入生产常量，测试即判据）。
    httpd = _start(monkeypatch, maxlen_override=3)
    base = _base(httpd)
    for _ in range(5):
        _request(base, "POST", "/v1/ui/events", _event(seq=0))
    status, payload = _request(base, "GET", "/v1/ui/events?since=0")
    assert [item["seq"] for item in payload["events"]] == [3, 4, 5]
    assert payload["latest_seq"] == 5
