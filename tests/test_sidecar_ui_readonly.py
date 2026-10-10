"""v1.7 卡 B6：四个只读端点一次注册。"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from block_director.contracts.assistant import CLIP_BY_STATE
from block_director.contracts.rule_catalog import RULES
from block_director.contracts.target_models import load_table

ROOT = Path(__file__).resolve().parents[1]


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_server_readonly_under_test",
        ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


def _start(tmp_path: Path, token: str = "",
           config_path: Path | None = None) -> ThreadingHTTPServer:
    argv = ["--upstream-kind", "openai",
            "--upstream", "https://api.deepseek.com",
            "--model", "deepseek-v4-pro",
            "--runs-dir", str(tmp_path / "runs"),
            "--cases-backend", "off",
            "--token", token]
    if config_path is not None:
        argv += ["--config", str(config_path)]
    args = sidecar.parse_args(argv)
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), sidecar.make_handler(sidecar.SidecarConfig(args)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _get(base: str, path: str, token: str = "") -> tuple:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(base + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(
                response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8", "replace"))


def test_state_map(tmp_path):
    httpd = _start(tmp_path, token="t")
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    status, payload = _get(base, "/v1/ui/state_map", token="t")
    assert status == 200
    assert payload == dict(CLIP_BY_STATE)
    assert _get(base, "/v1/ui/state_map")[0] == 401


def test_rules(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        sidecar.dump_yaml({"audit": {"rules_disabled": ["R009"]}}),
        encoding="utf-8")
    httpd = _start(tmp_path, token="t", config_path=config_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    status, payload = _get(base, "/v1/ui/rules", token="t")
    assert status == 200
    assert payload["rules"] == list(RULES)
    assert payload["disabled"] == ["R009"]
    assert _get(base, "/v1/ui/rules")[0] == 401


def test_target_models(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        sidecar.dump_yaml({"delivery": {"target_model": "kling"}}),
        encoding="utf-8")
    httpd = _start(tmp_path, token="t", config_path=config_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    status, payload = _get(base, "/v1/ui/target_models", token="t")
    assert status == 200
    assert set(payload["models"]) == set(load_table())
    assert payload["current"] == "kling"
    assert _get(base, "/v1/ui/target_models")[0] == 401


def test_shots_positive_and_negatives(tmp_path):
    shots = tmp_path / "runs" / "run_01" / "export" / "shots.json"
    shots.parent.mkdir(parents=True)
    shots.write_text(json.dumps({"shots": [{"shot_id": "shot_001"}]}),
                     encoding="utf-8")
    httpd = _start(tmp_path, token="t")
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    status, payload = _get(base, "/v1/ui/shots?run=run_01", token="t")
    assert status == 200
    assert payload["shots"][0]["shot_id"] == "shot_001"
    assert _get(base, "/v1/ui/shots?run=missing", token="t")[0] == 404
    assert _get(base, "/v1/ui/shots?run=..", token="t")[0] == 400
    assert _get(base, "/v1/ui/shots?run=%20")[0] == 401
