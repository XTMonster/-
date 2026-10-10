"""sidecar 的 strict 工具调用面 ＋ 探针判定逻辑（G2 判据 #8，卡 G8-E）。

sidecar 侧判据：

- ``--strict-tools`` 是 opt-in；关着的时候转发体逐字节与之前一致；
- 启动门：探针缺失 / verdict≠pass / 模型不一致 / supported_keywords 缺关键字 /
  非 OpenAI 兼容上游，一律拒绝启动（退出码 2），绝不静默退回非严格模式；
- 开着的时候：每个 function 加 ``strict:true``、parameters 走 ``to_strict``、
  请求打 ``/beta`` 端点、回包的工具参数先 ``strip_nulls`` 再回给插件。

探针侧把"关键字归类 / malformed_rate / verdict / anyOf 停下"这些纯判定钉住；
网络用 stub 替身，测试里一个字节都不发出去。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "tools")):
    if extra not in sys.path:
        sys.path.insert(0, extra)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_module("bd_sidecar_server_strict_under_test",
                       ROOT / "tools" / "sidecar_server.py")
probe = _load_module("bd_probe_strict_tools_under_test",
                     ROOT / "tools" / "probe_strict_tools.py")


def _probe_file(tmp_path: Path, **overrides: Any) -> Path:
    data = {
        "model": "deepseek-v4-pro",
        "endpoint": "https://api.deepseek.com/beta/chat/completions",
        "verdict": "pass",
        "supported_keywords": list(sidecar.SCHEMA_KEYWORD_UNIVERSE),
        "rejected_keywords": [],
        "malformed_rate": 0.0,
        "error": None,
    }
    data.update(overrides)
    path = tmp_path / "strict_probe.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _strict_argv(tmp_path: Path, probe_file: Optional[Path] = None,
                 **extra: Any) -> List[str]:
    argv = [
        "--upstream-kind", "openai",
        "--upstream", "https://api.deepseek.com",
        "--model", "deepseek-v4-pro",
        "--strict-tools",
    ]
    if probe_file is not None:
        argv += ["--strict-probe", str(probe_file)]
    for key, value in extra.items():
        argv += [f"--{key.replace('_', '-')}", str(value)]
    return argv


def _config(tmp_path: Path, argv: Optional[List[str]] = None) -> Any:
    args = sidecar.parse_args(argv if argv is not None
                               else _strict_argv(tmp_path, _probe_file(tmp_path)))
    return sidecar.SidecarConfig(args)


def _payload() -> Dict[str, Any]:
    return {
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "emit_shot_draft",
                "description": "draft",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["shot_id"],
                    "properties": {
                        "shot_id": {"type": "string"},
                        "shot_type": {"type": "string"},
                    },
                },
            },
        }],
        "tool_choice": "required",
        "temperature": 0.0,
        "seed": 0,
        "max_tokens": 8192,
    }


# --------------------------------------------------------------------------- #
# 启动门：缺探针 / 判 fail / 模型不一致 / 缺关键字 / 非 OpenAI 上游
# --------------------------------------------------------------------------- #
def test_missing_probe_refuses_to_start(tmp_path, capsys):
    args = sidecar.parse_args(
        ["--strict-tools", "--upstream-kind", "openai"])
    config = sidecar.SidecarConfig(args)
    with pytest.raises(sidecar.StrictStartupRefused) as exc:
        sidecar.check_strict_startup(args, config)
    assert "--strict-probe" in str(exc.value)

    # 主入口同样拒绝：退出码 2，stderr 带原因。
    with pytest.raises(SystemExit) as system_exit:
        sidecar.main(["--strict-tools", "--upstream-kind", "openai"])
    assert system_exit.value.code == 2
    assert "sidecar startup refused" in capsys.readouterr().err


def test_failing_probe_refuses_to_start(tmp_path):
    probe_file = _probe_file(tmp_path, verdict="fail",
                             error="提供方拒绝 minItems")
    args = sidecar.parse_args(_strict_argv(tmp_path, probe_file))
    config = sidecar.SidecarConfig(args)
    with pytest.raises(sidecar.StrictStartupRefused) as exc:
        sidecar.check_strict_startup(args, config)
    assert "verdict" in str(exc.value) and "minItems" in str(exc.value)


def test_probe_model_mismatch_refuses_to_start(tmp_path):
    probe_file = _probe_file(tmp_path, model="deepseek-chat")
    args = sidecar.parse_args(_strict_argv(tmp_path, probe_file))
    config = sidecar.SidecarConfig(args)
    with pytest.raises(sidecar.StrictStartupRefused) as exc:
        sidecar.check_strict_startup(args, config)
    assert "deepseek-chat" in str(exc.value)
    assert "deepseek-v4-pro" in str(exc.value)


def test_unsupported_keyword_refuses_to_start(tmp_path):
    supported = sorted(set(sidecar.SCHEMA_KEYWORD_UNIVERSE) - {"maxItems"})
    probe_file = _probe_file(tmp_path, supported_keywords=supported,
                             rejected_keywords=["maxItems"])
    args = sidecar.parse_args(_strict_argv(tmp_path, probe_file))
    config = sidecar.SidecarConfig(args)
    with pytest.raises(sidecar.StrictStartupRefused) as exc:
        sidecar.check_strict_startup(args, config)
    assert "maxItems" in str(exc.value)


def test_strict_with_an_ollama_upstream_refuses_to_start(tmp_path):
    probe_file = _probe_file(tmp_path)
    args = sidecar.parse_args(
        ["--strict-tools", "--strict-probe", str(probe_file)])
    assert args.upstream_kind == "ollama"     # 默认 upstream 是 127.0.0.1:11434
    config = sidecar.SidecarConfig(args)
    with pytest.raises(sidecar.StrictStartupRefused) as exc:
        sidecar.check_strict_startup(args, config)
    assert "OpenAI" in str(exc.value) and "ollama" in str(exc.value)


def test_strict_startup_accepts_a_passing_probe(tmp_path):
    probe_file = _probe_file(tmp_path)
    args = sidecar.parse_args(_strict_argv(tmp_path, probe_file))
    config = sidecar.SidecarConfig(args)
    sidecar.check_strict_startup(args, config)   # 不抛 = 通过


# --------------------------------------------------------------------------- #
# 转发体：strict 开/关两条路
# --------------------------------------------------------------------------- #
def test_forwarded_body_carries_strict_and_converted_schemas(tmp_path):
    config = _config(tmp_path)
    body = sidecar._openai_body(config, _payload())
    function = body["tools"][0]["function"]
    assert function["strict"] is True
    parameters = function["parameters"]
    assert parameters["additionalProperties"] is False
    assert parameters["required"] == ["shot_id", "shot_type"]
    assert parameters["properties"]["shot_id"]["type"] == "string"
    assert parameters["properties"]["shot_type"]["type"] == ["string", "null"]


def test_flag_off_forwarded_body_is_byte_identical_to_before():
    config = sidecar.SidecarConfig(sidecar.parse_args([]))
    payload = _payload()
    body = sidecar._openai_body(config, payload)
    # 关着的时候 tools 是**同一个对象**透传：没有 strict 键、没有 to_strict。
    assert body["tools"] is payload["tools"]
    assert "strict" not in body["tools"][0]["function"]
    assert body["tools"][0]["function"]["parameters"] == \
        payload["tools"][0]["function"]["parameters"]
    assert body["model"] == config.model
    assert body["seed"] == 0 and body["temperature"] == 0.0
    assert body["max_tokens"] == 8192


def test_strict_uses_the_beta_base_url_and_never_doubles_it(tmp_path, monkeypatch):
    captured: Dict[str, Any] = {}

    def fake_post(url, body, timeout, headers=None):
        captured["url"] = url
        return 200, json.dumps({
            "choices": [{"message": {"role": "assistant",
                                     "content": None,
                                     "tool_calls": []},
                         "finish_reason": "stop"}]})

    monkeypatch.setattr(sidecar, "_post_json", fake_post)
    sidecar.call_upstream(_config(tmp_path), _payload())
    assert captured["url"] == "https://api.deepseek.com/beta/chat/completions"

    config = sidecar.SidecarConfig(sidecar.parse_args(
        _strict_argv(tmp_path, _probe_file(tmp_path),
                     upstream="https://api.deepseek.com/beta")))
    sidecar.call_upstream(config, _payload())
    assert captured["url"] == "https://api.deepseek.com/beta/chat/completions"

    # 关着：走普通端点，一个字节都不多。
    plain = sidecar.SidecarConfig(sidecar.parse_args(
        ["--upstream-kind", "openai",
         "--upstream", "https://api.deepseek.com"]))
    sidecar.call_upstream(plain, _payload())
    assert captured["url"] == "https://api.deepseek.com/chat/completions"


def test_reply_arguments_come_back_with_nulls_stripped(tmp_path, monkeypatch):
    canned = json.dumps({
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "emit_shot_draft",
                        "arguments": '{"shot_id": null, "shot_type": null}',
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                  "total_tokens": 15},
    })
    monkeypatch.setattr(sidecar, "_post_json",
                        lambda url, body, timeout, headers=None: (200, canned))
    reply = sidecar.call_upstream(_config(tmp_path), _payload())
    args = json.loads(reply.tool_calls[0].function.arguments)
    assert args == {"shot_id": None}     # 必填键的 null 保留
    assert "shot_type" not in args       # 可选键的 null 剥掉


def test_malformed_strict_arguments_are_passed_through_untouched(tmp_path,
                                                                 monkeypatch):
    """坏 JSON 不吞不修（issue #1069 的量测口径在探针侧），原样透传。"""
    canned = json.dumps({
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "emit_shot_draft",
                                 "arguments": '{"shot_id: "x"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    })
    monkeypatch.setattr(sidecar, "_post_json",
                        lambda url, body, timeout, headers=None: (200, canned))
    reply = sidecar.call_upstream(_config(tmp_path), _payload())
    assert reply.tool_calls[0].function.arguments == '{"shot_id: "x"}'


# --------------------------------------------------------------------------- #
# 探针的纯判定逻辑（网络用 stub）
# --------------------------------------------------------------------------- #
def test_classify_attempts_is_conservative():
    assert probe.classify_attempts([(200, False), (200, False)]) == "supported"
    assert probe.classify_attempts([(400, True), (200, False)]) == "rejected"
    assert probe.classify_attempts([(None, False), (500, False)]) == "undecided"


def test_malformed_rate_and_case_passed_measure_tool_call_replies():
    attempts = [
        {"status": 200, "tool_call": True, "args_parse_ok": True,
         "args_valid": True},
        {"status": 200, "tool_call": True, "args_parse_ok": False},
        {"status": 200, "tool_call": False, "args_parse_ok": None},
        {"status": 400, "tool_call": False, "args_parse_ok": None},
    ]
    assert probe.malformed_rate(attempts) == 0.5
    assert probe.case_passed(attempts) is True
    assert probe.case_passed([
        {"status": 400, "tool_call": False, "args_parse_ok": None,
         "args_valid": None},
    ]) is False


def _fake_backend(replies: Dict[str, str]) -> Any:
    def fake(url, body, headers, timeout):
        tool_name = body["tools"][0]["function"]["name"]
        if tool_name.startswith("probe_kw_"):
            return 200, json.dumps({
                "choices": [{"message": {"role": "assistant", "content": None},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                          "total_tokens": 2},
            })
        arguments = replies.get(tool_name)
        if arguments is None:
            return 400, json.dumps(
                {"error": {"message": f"schema rejected for {tool_name}"}})
        return 200, json.dumps({
            "choices": [{"message": {"role": "assistant", "content": None,
                                     "tool_calls": [{
                                         "id": "call_1", "type": "function",
                                         "function": {
                                             "name": tool_name,
                                             "arguments": arguments}}]},
                         "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "total_tokens": 2},
        })
    return fake


def test_run_probe_reports_no_key_truthfully(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DS_OFFICIAL_KEY", raising=False)

    def must_not_be_called(url, body, headers, timeout):
        raise AssertionError("没有密钥就不许发请求")

    summary = probe.run_probe(probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT,
                              3, 512, 120.0, "", must_not_be_called)
    assert summary["verdict"] == "fail"
    assert "DEEPSEEK_API_KEY" in summary["error"]
    assert summary["supported_keywords"] == []


def test_run_probe_stops_and_reports_when_anyof_is_rejected():
    def fake(url, body, headers, timeout):
        tool_name = body["tools"][0]["function"]["name"]
        if tool_name == "probe_kw_anyOf":
            return 400, json.dumps(
                {"error": {"message": "anyOf is not supported in strict mode"}})
        if tool_name.startswith("probe_kw_"):
            return 200, json.dumps(
                {"choices": [{"message": {"role": "assistant",
                                          "content": None},
                              "finish_reason": "stop"}]})
        raise AssertionError(f"anyOf 被拒后不该再发用例调用：{tool_name}")

    summary = probe.run_probe(probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT,
                              3, 512, 120.0, "sk-not-a-real-key", fake)
    assert summary["verdict"] == "fail"
    assert "anyOf" in summary["rejected_keywords"]
    assert summary["stopped_reason"]
    assert summary["cases"] == {}


def test_root_keywords_are_not_blamed_for_a_targeted_probe_rejection():
    """null_array_anyof 被拒 ≠ 根 object 的 type/properties/required 被拒。"""

    def fake(url, body, headers, timeout):
        tool_name = body["tools"][0]["function"]["name"]
        if tool_name == "probe_kw_null_array_anyof":
            return 400, json.dumps(
                {"error": {"message": "anyOf with array branch rejected"}})
        if tool_name.startswith("probe_kw_"):
            return 200, json.dumps(
                {"choices": [{"message": {"role": "assistant",
                                          "content": None},
                              "finish_reason": "stop"}]})
        return 400, json.dumps(
            {"error": {"message": "case rejected"}})

    summary = probe.run_probe(probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT,
                              3, 512, 120.0, "sk-not-a-real-key", fake)
    assert "null" in summary["rejected_keywords"]
    for keyword in ("type", "properties", "required", "additionalProperties"):
        assert keyword in summary["supported_keywords"], \
            f"{keyword} 被 4xx 探针冤枉成 rejected：{summary['keyword_probes'][keyword]}"


def test_type_union_null_rejections_are_diagnostic_only():
    """旧编码 ["array","null"]/["object","null"] 被拒只作诊断，不翻 null 的盘。

    to_strict 已不再产出这两个联合（可空 array/object 走 anyOf+null），
    所以它们的 400 记录进 attempts（diagnostic=true）但 null 的归类只由
    null_scalar / null_array_anyof / null_object_anyof / null_anyof_append 决定。
    """
    replies = {
        "probe_enum": '{"mood": "calm"}',
        "probe_const": '{"kind": "person"}',
        "probe_anyof": '{"pet": {"kind": "cat", "lives": 9}}',
        "probe_nested": '{"outer": {"a": 1, "b": null}}',
        "probe_array": '{"tags": ["alpha", "beta"]}',
        "emit_shot_draft": '{"shot_id": "shot_001"}',
    }
    backend = _fake_backend(replies)

    def fake(url, body, headers, timeout):
        name = body["tools"][0]["function"]["name"]
        if name in ("probe_kw_null_array", "probe_kw_null_object"):
            return 400, json.dumps(
                {"error": {"message": f"unknown variant for {name}"}})
        return backend(url, body, headers, timeout)

    summary = probe.run_probe(probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT,
                              3, 512, 120.0, "sk-not-a-real-key", fake)
    assert summary["verdict"] == "pass"
    assert "null" in summary["supported_keywords"]
    attempts = summary["keyword_probes"]["null"]["attempts"]
    for variant in ("null_array", "null_object"):
        variant_attempts = [a for a in attempts if a["variant"] == variant]
        assert variant_attempts
        for attempt in variant_attempts:
            assert attempt["status"] == 400
            assert attempt["diagnostic"] is True
    # 判定用的变体确实不含诊断变体：四种 to_strict 编码全部 200。
    verdict_attempts = [a for a in attempts if not a["diagnostic"]]
    assert {a["variant"] for a in verdict_attempts} == {
        "null_scalar", "null_array_anyof", "null_object_anyof",
        "null_anyof_append"}
    assert all(a["status"] == 200 for a in verdict_attempts)


def test_run_probe_verdict_and_malformed_rate_with_a_successful_backend():
    replies = {
        "probe_enum": '{"mood": "calm"}',
        "probe_const": '{"kind": "person"}',
        "probe_anyof": '{"pet": {"kind": "cat", "lives": 9}}',
        "probe_nested": '{"outer": {"a": 1, "b": null}}',
        "probe_array": '{"tags": ["alpha", "beta"]}',
        "emit_shot_draft": '{"shot_id": "shot_001"}',
    }
    summary = probe.run_probe(probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT,
                              3, 512, 120.0, "sk-not-a-real-key",
                              _fake_backend(replies))
    assert summary["verdict"] == "pass"
    assert summary["rejected_keywords"] == []
    assert summary["undecided_keywords"] == []
    assert sorted(summary["supported_keywords"]) == \
        sorted(probe.SCHEMA_KEYWORD_UNIVERSE)
    assert summary["malformed_rate"] == 0.0
    assert all(case["passed"] for case in summary["cases"].values())


def test_run_probe_counts_malformed_arguments_and_fails_the_case():
    replies = {
        "probe_enum": '{"mood": "calm"}',
        "probe_const": '{"kind": "person"}',
        "probe_anyof": '{"pet": {"kind": "cat", "lives": 9}}',
        "probe_nested": '{"outer": {"a": 1, "b": null}}',
        # issue #1069 的形状：键名缺引号 → json.loads 失败。
        "probe_array": '{"tags: ["alpha", "beta"]}',
        "emit_shot_draft": '{"shot_id": "shot_001"}',
    }
    summary = probe.run_probe(probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT,
                              3, 512, 120.0, "sk-not-a-real-key",
                              _fake_backend(replies))
    assert summary["verdict"] == "fail"
    assert summary["malformed_rate"] == 1.0 / 6.0
    assert summary["cases"]["array_items"]["passed"] is False
    assert "failed_cases" in summary["error"]


def test_the_api_key_never_leaks_into_the_summary():
    fake = _fake_backend({
        "probe_enum": '{"mood": "calm"}',
        "probe_const": '{"kind": "person"}',
        "probe_anyof": '{"pet": {"kind": "cat", "lives": 9}}',
        "probe_nested": '{"outer": {"a": 1, "b": null}}',
        "probe_array": '{"tags": ["alpha", "beta"]}',
        "emit_shot_draft": '{"shot_id": "shot_001"}',
    })
    key = "sk-top-secret-123"
    summary = probe.run_probe(probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT,
                              3, 512, 120.0, key, fake)
    dumped = json.dumps(summary, ensure_ascii=False)
    assert key not in dumped


# --------------------------------------------------------------------------- #
# G8-H：真实运行会转发的每一个 function schema（取自代码，不手抄）
# --------------------------------------------------------------------------- #
def test_forwarded_tool_cases_cover_every_forwarded_function():
    cases = {case["name"]: case for case in probe.forwarded_tool_cases()}
    # 阶段工具：plan / brief / 两种草案形状 / review / 三个控制工具。
    for name in ("forward_emit_plan", "forward_emit_scene_brief",
                 "forward_emit_shot_draft_static",
                 "forward_emit_shot_draft_per_shot", "forward_submit_review",
                 "forward_request_self_review", "forward_finish_shot",
                 "forward_abort", "forward_estimate_shot_duration",
                 "forward_search_knowledge"):
        assert name in cases, f"缺转发用例 {name}"
    # 查询/动作/相机工具：全部来自 tool_bindings 的 registry.add。
    binding_names = {"tool_" + name for name in probe.binding_schemas()}
    assert {"forward_tool_place_character", "forward_tool_character_action",
            "forward_tool_move_camera", "forward_tool_reframe",
            "forward_tool_check_visibility"} <= set(cases)
    assert {"forward_" + name for name in binding_names} <= set(cases)


def test_forwarded_tool_schemas_come_from_the_code_sources():
    from block_director.layer5_orchestrator.planner import plan_parameters
    from block_director.layer5_orchestrator.understand import (
        EMIT_BRIEF_TOOL_PARAMETERS,
    )
    from block_director.layer5_orchestrator.review import REVIEW_TOOL_PARAMETERS
    from block_director.layer5_orchestrator.timing_tool import (
        ESTIMATE_DURATION_PARAMETERS,
    )
    from block_director.knowledge.tool import SEARCH_KNOWLEDGE_PARAMETERS

    cases = {case["name"]: case for case in probe.forwarded_tool_cases()}
    assert cases["forward_emit_plan"]["schema"] == plan_parameters(0)
    assert (cases["forward_emit_scene_brief"]["schema"]
            == EMIT_BRIEF_TOOL_PARAMETERS)
    assert cases["forward_submit_review"]["schema"] == REVIEW_TOOL_PARAMETERS
    assert (cases["forward_estimate_shot_duration"]["schema"]
            == ESTIMATE_DURATION_PARAMETERS)
    assert (cases["forward_search_knowledge"]["schema"]
            == SEARCH_KNOWLEDGE_PARAMETERS)
    # 基线来自 tool_bindings 的 AST 提取：枚举值表与纯模块同源。
    action = cases["forward_tool_character_action"]["schema"]
    assert action["properties"]["action_type"]["enum"] == list(
        probe.ACTION_TYPES)


def test_per_shot_enums_are_injected_into_forwarded_schemas():
    cases = {case["name"]: case for case in probe.forwarded_tool_cases()}
    per_shot = cases["forward_emit_shot_draft_per_shot"]["schema"]
    assert per_shot["properties"]["characters"]["items"] == {
        "type": "string", "enum": list(probe.PROBE_SHOT_CHARACTERS)}
    look_at = cases["forward_tool_look_at"]["schema"]
    assert look_at["properties"]["character_id"] == {
        "type": "string", "enum": list(probe.PROBE_SHOT_CHARACTERS)}
    assert look_at["properties"]["target"] == {
        "type": "string", "enum": list(probe.PROBE_FULL_CAST)}
    # 静态模板不受逐镜枚举污染（同一份 BASE_DRAFT 的深拷贝纪律）。
    static = cases["forward_emit_shot_draft_static"]["schema"]
    assert static["properties"]["characters"]["items"] == {"type": "string"}


def _accepting_backend(replies, reject=(), undecided=()):
    """探针后端的替身：关键字 200、用例按 replies 给工具调用、转发工具可指定
    400（reject）或 500（undecided），其余 200。"""

    def fake(url, body, headers, timeout):
        tool_name = body["tools"][0]["function"]["name"]
        if tool_name.startswith("probe_kw_"):
            return 200, json.dumps({
                "choices": [{"message": {"role": "assistant",
                                         "content": None},
                             "finish_reason": "stop"}]})
        if tool_name in reject:
            return 400, json.dumps(
                {"error": {"message": f"schema rejected for {tool_name}"}})
        if tool_name in undecided:
            return 500, json.dumps({"error": {"message": "upstream exploded"}})
        arguments = replies.get(tool_name, "{}")
        return 200, json.dumps({
            "choices": [{"message": {"role": "assistant", "content": None,
                                     "tool_calls": [{
                                         "id": "call_1", "type": "function",
                                         "function": {"name": tool_name,
                                                      "arguments": arguments}}]},
                         "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "total_tokens": 2},
        })

    return fake


_VALID_CASE_REPLIES = {
    "probe_enum": '{"mood": "calm"}',
    "probe_const": '{"kind": "person"}',
    "probe_anyof": '{"pet": {"kind": "cat", "lives": 9}}',
    "probe_nested": '{"outer": {"a": 1, "b": null}}',
    "probe_array": '{"tags": ["alpha", "beta"]}',
    "emit_shot_draft": '{"shot_id": "shot_001"}',
}


def test_run_probe_forwarded_tools_all_accepted_passes():
    summary = probe.run_probe(
        probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT, 3, 512, 120.0,
        "sk-not-a-real-key", _accepting_backend(_VALID_CASE_REPLIES),
        tool_attempts=1, probe_forwarded_tools=True)
    assert summary["verdict"] == "pass"
    assert summary["forwarded_tools"]
    assert all(record["classified"] == "supported"
               for record in summary["forwarded_tools"].values())
    assert all(record["attempts"][0]["status"] == 200
               for record in summary["forwarded_tools"].values())


def test_run_probe_forwarded_tool_rejection_fails_the_verdict():
    summary = probe.run_probe(
        probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT, 3, 512, 120.0,
        "sk-not-a-real-key",
        _accepting_backend(_VALID_CASE_REPLIES, reject=("emit_plan",)),
        tool_attempts=1, probe_forwarded_tools=True)
    assert summary["verdict"] == "fail"
    assert summary["forwarded_tools"]["forward_emit_plan"]["classified"] \
        == "rejected"
    assert "rejected_tools" in summary["error"]
    error_text = summary["forwarded_tools"]["forward_emit_plan"]["attempts"][0][
        "error_text"]
    assert error_text and "schema rejected for emit_plan" in error_text


def test_run_probe_forwarded_tool_undecided_fails_the_verdict():
    summary = probe.run_probe(
        probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT, 3, 512, 120.0,
        "sk-not-a-real-key",
        _accepting_backend(_VALID_CASE_REPLIES, undecided=("submit_review",)),
        tool_attempts=1, probe_forwarded_tools=True)
    assert summary["verdict"] == "fail"
    assert summary["forwarded_tools"]["forward_submit_review"]["classified"] \
        == "undecided"
    assert "undecided_tools" in summary["error"]


def test_run_probe_skips_forwarded_tools_unless_requested():
    """默认关着：既有调用点（只传 7 个位置参数）连一个转发请求都不发。"""
    seen: List[str] = []

    def fake(url, body, headers, timeout):
        tool_name = body["tools"][0]["function"]["name"]
        seen.append(tool_name)
        if tool_name.startswith("probe_kw_"):
            return 200, json.dumps({
                "choices": [{"message": {"role": "assistant",
                                         "content": None},
                             "finish_reason": "stop"}]})
        return 200, json.dumps({
            "choices": [{"message": {"role": "assistant", "content": None,
                                     "tool_calls": [{
                                         "id": "call_1", "type": "function",
                                         "function": {
                                             "name": tool_name,
                                             "arguments": _VALID_CASE_REPLIES.get(
                                                 tool_name, "{}")}}]},
                         "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "total_tokens": 2},
        })

    summary = probe.run_probe(probe.DEFAULT_MODEL, probe.DEFAULT_ENDPOINT,
                              3, 512, 120.0, "sk-not-a-real-key", fake)
    assert summary["verdict"] == "pass"
    assert summary["forwarded_tools"] == {}
    forwarded_names = {"emit_plan", "emit_scene_brief", "submit_review",
                       "request_self_review", "finish_shot", "abort",
                       "estimate_shot_duration", "search_knowledge",
                       "place_character", "move_camera", "reframe"}
    assert not (set(seen) & forwarded_names)
