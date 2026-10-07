"""Hooks follow the selected session model, never an assumed provider/model.

All credentials below are synthetic. No test contacts a model endpoint or reads
the user's real config; PowerShell receives a complete event/config fixture.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "docs" / "agents" / "hooks"
ROUTER = HOOKS / "selected-model.ps1"
CONFIG = """
model = "old-default"
model_provider = "selected"
[model_providers.decoy]
base_url = "https://wrong.invalid/v1"
wire_api = "chat"
experimental_bearer_token = "wrong-token"
[model_providers.selected]
base_url = "https://selected.invalid/v1"
wire_api = "responses"
experimental_bearer_token = "selected-token"
"""


def _call(function, **payload):
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        f". '{ROUTER.as_posix()}'; "
        "$p = [Console]::In.ReadToEnd() | ConvertFrom-Json; "
        f"& {{ {function} }} | ConvertTo-Json -Depth 15 -Compress"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        input=json.dumps(payload, ensure_ascii=True),
        capture_output=True, encoding="utf-8", timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.lstrip("\ufeff"))


def _route(event, config=CONFIG):
    return _call(
        "Resolve-SelectedModelRoute -HookEvent $p.event -ConfigText $p.config",
        event={"model_provider": "selected", **event}, config=config,
    )


@pytest.mark.parametrize("selected", ["chosen-a", "chosen-b", "future-model-42"])
def test_event_model_wins_over_global_default(selected):
    route = _route({"model": selected})
    assert route["Ok"] is True
    assert route["Model"] == selected
    assert route["Provider"] == "selected"
    assert route["BaseUrl"] == "https://selected.invalid/v1"
    assert route["ApiKey"] == "selected-token"


def test_provider_override_selects_only_its_own_credentials():
    route = _route({"model": "other-choice", "model_provider": "decoy"})
    assert route["Provider"] == "decoy"
    assert route["ApiKey"] == "wrong-token"
    assert route["WireApi"] == "chat"


def test_missing_event_model_does_not_guess_the_default():
    route = _route({})
    assert route["Ok"] is False
    assert route["Error"] == "selected model missing from hook event"
    assert not route.get("ApiKey")


def test_unknown_provider_does_not_borrow_another_key():
    route = _route({"model": "chosen-a", "model_provider": "missing"})
    assert route["Ok"] is False
    assert route["Error"] == "selected provider is not configured"
    assert not route.get("ApiKey")


def test_missing_effective_provider_never_guesses_from_global_config():
    route = _call(
        "Resolve-SelectedModelRoute -HookEvent $p.event -ConfigText $p.config",
        event={"model": "same-name-on-two-providers"}, config=CONFIG,
    )
    assert route["Ok"] is False
    assert route["Error"] == "effective provider missing from hook event"
    assert not route.get("ApiKey")


def test_omitted_wire_api_uses_responses_default():
    route = _route({"model": "chosen-a"}, CONFIG.replace('wire_api = "responses"', ""))
    assert route["Ok"] is True
    assert route["WireApi"] == "responses"


def test_missing_selected_token_does_not_borrow_first_token():
    route = _route(
        {"model": "chosen-a"},
        CONFIG.replace('experimental_bearer_token = "selected-token"', ""),
    )
    assert route["Ok"] is False
    assert route["Error"] == "selected provider credential unavailable"
    assert "wrong-token" not in json.dumps(route)


@pytest.mark.parametrize("wire,endpoint", [
    ("responses", "/responses"),
    ("chat", "/chat/completions"),
])
def test_request_uses_selected_model_and_matching_wire_api(wire, endpoint):
    request = _call(
        "New-SelectedModelRequest -Route $p.route "
        "-Instructions $p.instructions -PromptText $p.prompt",
        route={"Model": "chosen-b", "BaseUrl": "https://selected.invalid/v1/",
               "WireApi": wire},
        instructions="classify", prompt="review this",
    )
    assert request["Url"] == "https://selected.invalid/v1" + endpoint
    assert request["Body"]["model"] == "chosen-b"
    assert ("input" in request["Body"]) == (wire == "responses")
    assert ("messages" in request["Body"]) == (wire == "chat")


@pytest.mark.parametrize("wire,body", [
    ("chat", {"choices": [{"finish_reason": "stop",
                          "message": {"content": '{"kinds":["review"]}'}}]}),
    ("responses", {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": '{"kinds":["review"]}'},
    ]}]}),
])
def test_response_text_supports_both_provider_protocols(wire, body):
    text = _call(
        "Get-SelectedModelResponseText -WireApi $p.wire -ResponseBody $p.body",
        wire=wire, body=json.dumps(body),
    )
    assert json.loads(text) == {"kinds": ["review"]}


def test_routing_contract_is_dynamic_and_subagents_inherit():
    text = (HOOKS / "model-routing.md").read_text(encoding="utf-8")
    assert "当前会话选择的模型" in text
    assert "省略 `model`" in text
    assert "不固定" in text
    assert "**主线 DeepSeek**" not in text
    assert "**只在 DeepSeek 上做**" not in text


def test_semantic_hook_has_no_fixed_deepseek_request_or_first_token_lookup():
    script = (HOOKS / "inject-context.ps1").read_text(encoding="utf-8")
    assert "Resolve-SelectedModelRoute" in script
    assert "New-SelectedModelRequest" in script
    assert "https://api.deepseek.com" not in script
    assert "'deepseek-chat'" not in script
    assert "DEEPSEEK_API_KEY" not in script


def test_router_remains_ascii_for_windows_powershell_51():
    assert ROUTER.read_bytes().isascii()


def test_selected_env_key_never_falls_back_to_embedded_or_other_token(monkeypatch):
    config = CONFIG + 'env_key = "HOOK_TEST_SELECTED_TOKEN"\n'
    monkeypatch.setenv("HOOK_TEST_SELECTED_TOKEN", "environment-token")
    assert _route({"model": "chosen-c"}, config)["ApiKey"] == "environment-token"
    monkeypatch.delenv("HOOK_TEST_SELECTED_TOKEN")
    unavailable = _route({"model": "chosen-c"}, config)
    assert unavailable["Ok"] is False
    assert not unavailable.get("ApiKey")


def test_stream_requires_completed_event_not_just_a_valid_json_delta():
    delta = 'data: {"type":"response.output_text.delta","delta":"{\\"kinds\\":[]}"}\n\n'
    result = _call(
        "try { Get-SelectedModelResponseText -WireApi 'responses' "
        "-ResponseBody $p.body; } catch { 'REJECTED' }",
        body=delta,
    )
    assert result == "REJECTED"


@pytest.mark.parametrize("status", ["queued", "in_progress", "failed", None])
def test_responses_rejects_non_success_terminal_status(status):
    body = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": '{"kinds":["review"]}'},
    ]}]}
    if status is not None:
        body["status"] = status
    result = _call(
        "try { Get-SelectedModelResponseText -WireApi 'responses' "
        "-ResponseBody $p.body; } catch { 'REJECTED' }",
        body=json.dumps(body),
    )
    assert result == "REJECTED"


@pytest.mark.parametrize("reason", ["length", "content_filter", "tool_calls", None])
def test_chat_rejects_non_success_terminal_reason(reason):
    choice = {"message": {"content": '{"kinds":["review"]}'}}
    if reason is not None:
        choice["finish_reason"] = reason
    result = _call(
        "try { Get-SelectedModelResponseText -WireApi 'chat' "
        "-ResponseBody $p.body; } catch { 'REJECTED' }",
        body=json.dumps({"choices": [choice]}),
    )
    assert result == "REJECTED"


@pytest.mark.parametrize("wire", ["responses", "chat"])
def test_actual_hook_routes_two_session_choices_without_changing_config(tmp_path, wire):
    """Drive the real hook through an HTTP boundary, not a request-building mock."""
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append((self.path, self.headers["Authorization"], payload))
            verdict = '{"kinds":["review"]}'
            if wire == "responses":
                body = "data: " + json.dumps({
                    "type": "response.completed",
                    "response": {"status": "completed", "output": [
                        {"type": "message", "content": [
                            {"type": "output_text", "text": verdict},
                        ]},
                    ]},
                }) + "\n\n"
                content_type = "text/event-stream"
            else:
                body = json.dumps({"choices": [{
                    "finish_reason": "stop", "message": {"content": verdict},
                }]})
                content_type = "application/json"
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        pack = tmp_path / "hooks"
        pack.mkdir()
        for path in HOOKS.iterdir():
            if path.suffix in (".ps1", ".md"):
                shutil.copy2(path, pack / path.name)
        config = CONFIG.replace(
            "https://selected.invalid/v1", f"http://127.0.0.1:{server.server_port}/v1",
        ).replace('wire_api = "responses"', f'wire_api = "{wire}"')
        config_path = tmp_path / "config.toml"
        config_path.write_text(config, encoding="utf-8")
        env = dict(os.environ, CODEX_HOME=str(tmp_path))
        env.pop("CODEX_CLASSIFY_STUB", None)
        for model in ("choice-first", "choice-after-switch"):
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(pack / "inject-context.ps1")],
                input=json.dumps({"hook_event_name": "UserPromptSubmit",
                                  "model": model, "model_provider": "selected",
                                  "prompt": "plain words"}),
                capture_output=True, encoding="utf-8", env=env, timeout=15,
            )
            assert proc.returncode == 0, proc.stderr
            output = json.loads(proc.stdout.lstrip("\ufeff"))
            context = output["hookSpecificOutput"]["additionalContext"]
            assert "semantic:review" in context
            assert "--out work/_panel_review/" in context
            assert "当前会话选择的模型" in context
            assert "selected-token" not in proc.stdout + proc.stderr
        assert [entry[2]["model"] for entry in captured] == [
            "choice-first", "choice-after-switch",
        ]
        endpoint = "/v1/responses" if wire == "responses" else "/v1/chat/completions"
        assert all(entry[0] == endpoint for entry in captured)
        assert all(entry[1] == "Bearer selected-token" for entry in captured)
        assert config_path.read_text(encoding="utf-8") == config
        logged = (pack / "classify.log").read_text(encoding="utf-8")
        assert "selected-token" not in logged and "wrong-token" not in logged
        assert "choice-after-switch" in logged
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
