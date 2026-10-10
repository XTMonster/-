"""v1.7 卡 B4：`GET /v1/ui/knowledge/stats`（逐文件数行口径）。"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_server_knowledge_stats_under_test",
        ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


def _start(knowledge_dir: Path) -> ThreadingHTTPServer:
    args = sidecar.parse_args(
        ["--upstream-kind", "openai",
         "--upstream", "https://api.deepseek.com",
         "--model", "deepseek-v4-pro",
         "--knowledge-dir", str(knowledge_dir),
         "--cases-backend", "off"])
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), sidecar.make_handler(sidecar.SidecarConfig(args)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _stats(httpd: ThreadingHTTPServer) -> dict:
    url = (f"http://127.0.0.1:{httpd.server_address[1]}"
           "/v1/ui/knowledge/stats")
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "body": exc.read().decode("utf-8")}


def _lines(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f'{{"i": {n}}}' for n in range(count)) + "\n",
                    encoding="utf-8")


def test_counts_lines(tmp_path):
    knowledge = tmp_path / "knowledge"
    _lines(knowledge / "cards_generated" / "a.jsonl", 3)
    _lines(knowledge / "cards_generated" / "b.jsonl", 2)
    _lines(knowledge / "hypergraph.edges.jsonl", 7)
    _lines(knowledge / "cases" / "part-000.jsonl", 4)
    _lines(knowledge / "cases" / "part-001.jsonl", 3)
    httpd = _start(knowledge)
    payload = _stats(httpd)
    assert payload["cards"] == 5
    assert payload["edges"] == 7
    assert payload["cases"] == 7
    assert "cards_note" in payload


def test_missing_dirs_zero(tmp_path):
    httpd = _start(tmp_path / "empty_knowledge")
    payload = _stats(httpd)
    assert payload == {"cards": 0, "edges": 0, "cases": 0,
                       "cards_note": payload["cards_note"]}


def test_clue_source_excluded(tmp_path):
    knowledge = tmp_path / "knowledge"
    _lines(knowledge / "cases" / "part-000.jsonl", 4)
    _lines(knowledge / "cases.clue_source.jsonl", 99)
    httpd = _start(knowledge)
    assert _stats(httpd)["cases"] == 4
