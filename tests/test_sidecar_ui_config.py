"""v1.7 卡 B2：`GET/PUT /v1/ui/config`、`PUT /v1/ui/secret`（key 掩码）。"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

from block_director.contracts.config import AppConfig
from block_director.utils import secret_store
from block_director.utils.secret_store import mask_key

ROOT = Path(__file__).resolve().parents[1]


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_server_ui_config_under_test",
        ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


def _start(monkeypatch, token: str = "",
           config_path: Optional[Path] = None) -> ThreadingHTTPServer:
    argv = ["--upstream-kind", "openai",
            "--upstream", "https://api.deepseek.com",
            "--model", "deepseek-v4-pro",
            "--token", token]
    if config_path is not None:
        argv += ["--config", str(config_path)]
    args = sidecar.parse_args(argv)
    config = sidecar.SidecarConfig(args)
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), sidecar.make_handler(config))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _request(base: str, method: str, path: str, body: Optional[str] = None,
             content_type: str = "application/json",
             token: str = "") -> tuple:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = content_type
    data = body.encode("utf-8") if body is not None else None
    request = urllib.request.Request(base + path, data=data, headers=headers,
                                     method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8", "replace")
            return response.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _yaml_body(**updates: Any) -> str:
    payload: Dict[str, Any] = {
        "llm": {"provider": "deepseek", "model": "deepseek-v4-pro",
                "api_key": ""},
        "ui": {"enabled": True},
    }
    for key, value in updates.items():
        section, _, field = key.partition("_")
        payload.setdefault(section, {})[field] = value
    return sidecar.dump_yaml(payload)


def test_put_config_error_refused(monkeypatch, tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("", encoding="utf-8")
    httpd = _start(monkeypatch, config_path=target)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    status, raw = _request(base, "PUT", "/v1/ui/config",
                           _yaml_body(budget_max_cost_usd=-1),
                           content_type="text/yaml")
    assert status == 400
    assert "CFG_010" in raw
    assert target.read_text(encoding="utf-8") == ""


def test_put_config_accepts_json(monkeypatch, tmp_path):
    target = tmp_path / "config.yaml"
    httpd = _start(monkeypatch, config_path=target)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    json_body = json.dumps({"llm": {"provider": "deepseek",
                                    "model": "deepseek-v4-pro"}})
    status, _raw = _request(base, "PUT", "/v1/ui/config", json_body,
                            content_type="application/json")
    assert status == 200
    after_json = target.read_text(encoding="utf-8")
    yaml_body = _yaml_body()
    status, _raw = _request(base, "PUT", "/v1/ui/config", yaml_body,
                            content_type="text/yaml")
    assert status == 200
    after_yaml = target.read_text(encoding="utf-8")
    assert AppConfig.load(target).llm.provider == "deepseek"
    assert after_json == after_yaml


def test_put_config_strips_key(monkeypatch, tmp_path):
    target = tmp_path / "config.yaml"
    httpd = _start(monkeypatch, config_path=target)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    status, _raw = _request(base, "PUT", "/v1/ui/config",
                            _yaml_body(llm_api_key="sk-live-secret"),
                            content_type="text/yaml")
    assert status == 200
    saved_text = target.read_text(encoding="utf-8")
    assert "sk-live-secret" not in saved_text
    assert AppConfig.load(target).llm.api_key == ""


def test_secret_response_no_plaintext(monkeypatch, tmp_path):
    httpd = _start(monkeypatch)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    target = tmp_path / "secrets.json"
    monkeypatch.setattr(
        sidecar, "save_secret",
        lambda provider, api_key, path=None: secret_store.save_secret(
            provider, api_key, target))
    status, raw = _request(
        base, "PUT", "/v1/ui/secret",
        json.dumps({"provider": "deepseek", "api_key": "sk-secret-12345678"}))
    assert status == 200
    assert "sk-secret-12345678" not in raw


def test_get_config_masked(monkeypatch, tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text(sidecar.dump_yaml({
        "llm": {"provider": "testprov", "api_key": "sk-plain-12345678"},
    }), encoding="utf-8")
    monkeypatch.delenv("BLOCKDIRECTOR_API_KEY", raising=False)
    monkeypatch.delenv("TESTPROV_API_KEY", raising=False)
    monkeypatch.setattr(secret_store, "load_secrets",
                        lambda path=None: {})
    httpd = _start(monkeypatch, config_path=target)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    status, raw = _request(base, "GET", "/v1/ui/config")
    assert status == 200
    payload = json.loads(raw)
    assert payload["llm"]["api_key"] == mask_key("sk-plain-12345678")
    assert "sk-plain-12345678" not in raw


def test_unauthorized_401(monkeypatch, tmp_path):
    httpd = _start(monkeypatch, token="t", config_path=tmp_path / "c.yaml")
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    assert _request(base, "GET", "/v1/ui/config")[0] == 401
    assert _request(base, "PUT", "/v1/ui/config",
                    _yaml_body())[0] == 401
    assert _request(base, "PUT", "/v1/ui/secret",
                    json.dumps({"provider": "x", "api_key": "k"}))[0] == 401
