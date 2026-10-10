"""v1.7 卡 B3：静态文件服务（`GET /` 与 `/static/*`，免鉴权 + 穿越防护）。"""

from __future__ import annotations

import importlib.util
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_server_static_under_test",
        ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


def _start(tmp_path: Path, token: str = "") -> ThreadingHTTPServer:
    args = sidecar.parse_args(
        ["--upstream-kind", "openai",
         "--upstream", "https://api.deepseek.com",
         "--model", "deepseek-v4-pro",
         "--web-root", str(tmp_path),
         "--token", token])
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), sidecar.make_handler(sidecar.SidecarConfig(args)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _get(base: str, path: str) -> tuple:
    try:
        with urllib.request.urlopen(base + path, timeout=10) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def test_index_200_no_auth(tmp_path):
    (tmp_path / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    httpd = _start(tmp_path, token="t")
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    status, text = _get(base, "/")
    assert status == 200
    assert "<html>ok</html>" in text


def test_traversal_400(tmp_path):
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    httpd = _start(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    assert _get(base, "/static/../sidecar_server.py")[0] == 400
    assert _get(base, "/static/%2e%2e/x")[0] == 400


def test_unknown_suffix_404(tmp_path):
    (tmp_path / "x.exe").write_bytes(b"MZ")
    httpd = _start(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    assert _get(base, "/static/x.exe")[0] == 404


def test_missing_404(tmp_path):
    httpd = _start(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    assert _get(base, "/static/nope.txt")[0] == 404
    assert _get(base, "/")[0] == 404


def test_ui_get_requires_auth_401(tmp_path):
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    httpd = _start(tmp_path, token="t")
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    #: 分层不被静态分支吃掉：静态免鉴权、UI 事件仍 401。
    assert _get(base, "/")[0] == 200
    assert _get(base, "/v1/ui/events")[0] == 401
