"""v1.7 卡 B7：`POST /v1/ui/chat`（捷径/注入/历史封顶/持久化/写保护）。"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_server_chat_under_test",
        ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


def _start(tmp_path: Path) -> ThreadingHTTPServer:
    args = sidecar.parse_args(
        ["--upstream-kind", "openai",
         "--upstream", "https://api.deepseek.com",
         "--model", "deepseek-v4-pro",
         "--runs-dir", str(tmp_path / "runs"),
         "--knowledge-dir", str(tmp_path / "knowledge"),
         "--cases-backend", "off"])
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), sidecar.make_handler(sidecar.SidecarConfig(args)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _post(base: str, path: str, body: Dict[str, Any]) -> tuple:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(
                response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8", "replace"))


def _spy(monkeypatch) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    def fake(config, payload):
        calls.append(dict(payload))
        return sidecar.ChatReply(content="好的")

    monkeypatch.setattr(sidecar, "call_upstream", fake)
    return calls


def _chat(base: str, message: str) -> tuple:
    return _post(base, "/v1/ui/chat",
                 {"session_id": "s1", "message": message})


def _push_state(base: str, run_id: str = "") -> None:
    payload = {"done": 1, "total": 13}
    if run_id:
        payload["run_id"] = run_id
    _post(base, "/v1/ui/events", {
        "seq": 0, "ts": 0.0, "kind": "state_change", "state": "BUILDING",
        "shot_id": "shot_001", "payload": payload})


def test_shortcut_no_upstream(monkeypatch, tmp_path):
    httpd = _start(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    calls = _spy(monkeypatch)
    _push_state(base)
    status, payload = _chat(base, "现在跑到哪了")
    assert status == 200
    assert payload["source"] == "shortcut"
    assert "状态" in payload["reply"]
    assert calls == []


def test_shortcut_empty_buffer(monkeypatch, tmp_path):
    httpd = _start(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    calls = _spy(monkeypatch)
    status, payload = _chat(base, "现在进度如何")
    assert status == 200
    assert payload["reply"] == "还没有运行事件"
    assert calls == []


def test_injection_shape(monkeypatch, tmp_path):
    httpd = _start(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    calls = _spy(monkeypatch)
    status, payload = _chat(base, "怎么导出视频")
    assert status == 200
    assert payload["reply"] == "好的"
    assert len(calls) == 1
    system = calls[0]["messages"][0]["content"]
    assert "BlockDirector" in system
    assert "【检索结果】" in system
    assert calls[0]["messages"][-1]["content"] == "怎么导出视频"


def test_history_capped_at_10(monkeypatch, tmp_path):
    httpd = _start(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    history = tmp_path / "runs" / "_idle" / "chat.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text("".join(
        json.dumps({"user": f"q{i}", "assistant": f"a{i}"},
                   ensure_ascii=False) + "\n" for i in range(15)),
        encoding="utf-8")
    calls = _spy(monkeypatch)
    _chat(base, "继续")
    messages = calls[0]["messages"]
    #: 1 system + 10 轮 × 2 + 1 当前 user = 22（钉死条数，防上下文膨胀）。
    assert len(messages) == 22


def test_persistence_appends(monkeypatch, tmp_path):
    httpd = _start(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    _spy(monkeypatch)
    _chat(base, "问题一")
    _chat(base, "问题二")
    idle = tmp_path / "runs" / "_idle" / "chat.jsonl"
    assert idle.exists()
    assert len(idle.read_text(encoding="utf-8").splitlines()) == 2
    _push_state(base, run_id="run_x")
    _chat(base, "问题三")
    run_file = tmp_path / "runs" / "run_x" / "chat.jsonl"
    assert len(run_file.read_text(encoding="utf-8").splitlines()) == 1


def test_write_request_fixed_reply(monkeypatch, tmp_path):
    httpd = _start(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    calls = _spy(monkeypatch)
    status, payload = _chat(base, "帮我改第 3 镜")
    assert status == 200
    assert "只读" in payload["reply"]
    assert payload["source"] == "write_guard"
    assert calls == []
