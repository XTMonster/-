"""v1.7 卡 E2：Stage P 剧本优化双通道与采纳门（TDD §9）。

- run 内通道（driver）：POLISHING 状态迁移、一次 strict-schema 调用、
  失败一次回落原剧本＋``E_POLISH_001``（不重试）、未采纳恒原稿；
- Web 通道（sidecar）：``POST /v1/ui/script/polish`` 与
  ``POST /v1/ui/script/polish/accept`` 两端点，与 driver 共用同一套
  schema/模板/解析函数（双通道同构）。

driver 的状态机测试照 ``test_protocol_end_to_end.py`` 的 FakeModel 模式；
sidecar 端点照 ``test_sidecar_ui_readonly.py`` 的 importlib＋HTTP 模式。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from block_director.contracts.config import AppConfig
from block_director.contracts.brief import SceneBrief
from block_director.contracts.script_polish import PolishResult
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall, Usage
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator import script_polish as sp
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = "INT. 咖啡馆 - 日\n\n小明与小红隔桌对坐。\n"


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class StubBuilder:
    def build(self, plan, brief=None):
        return {"shots": len(plan.shots), "total_frames": plan.total_frames}


class StubAuditor:
    def shot_ids(self):
        return []

    def audit(self, shot_id):
        from block_director.contracts.audit import AuditResult
        return AuditResult(passed=True, target=shot_id, score=90.0)


def _polish_reply(request_id="", *, valid: bool = True) -> ChatReply:
    """构造 emit_polish 回复；``valid=False`` 时参数非法（无 rewritten）。"""
    usage = Usage(prompt_tokens=10, completion_tokens=5)
    if valid:
        arguments = json.dumps(
            {"suggestions": ["拆镜建议", "视线衔接"],
             "rewritten": "改写后的完整剧本（共用同一契约）"},
            ensure_ascii=False)
    else:
        arguments = json.dumps({"suggestions": ["坏参数"]}, ensure_ascii=False)
    call = ToolCall(id="call_polish", function=FunctionCall(
        name="emit_polish", arguments=arguments))
    return ChatReply(tool_calls=[call], usage=usage, model="fake",
                     request_id=request_id, finish_reason="tool_calls")


class FakeModel:
    """按 purpose 回复：polish 回 emit_polish，其余阶段给最小合法回复。"""

    def __init__(self, polish_ok: bool = True):
        self.polish_ok = polish_ok
        self.calls = 0

    def chat(self, payload, timeout):
        self.calls += 1
        purpose = str(getattr(payload, "purpose", "") or "")
        if purpose == "polish":
            return _polish_reply(payload.request_id, valid=self.polish_ok)
        # 其余阶段给空回复（调用数不因 polish 之外的阶段变化）。
        return ChatReply(content="停", usage=None, model="fake",
                         request_id=payload.request_id)


def _make_driver(fake, *, enabled: bool = True, tmp_path=None):
    from pathlib import Path as _Path
    directory = _Path(tmp_path) if tmp_path is not None else _Path(".")
    config = AppConfig()
    config.script_polish.enabled = enabled
    audit = AuditLogger(directory=directory)
    driver = PrevisDriver(transport=fake, audit=audit, script=SCRIPT,
                          config=config, builder=StubBuilder(),
                          auditor=StubAuditor(),
                          limits=DriverLimits(max_repairs_per_shot=1),
                          thread_factory=InlineThread)
    return driver, audit


def _polish_gate_result(driver) -> DriverState:
    """推进状态机直到跨过 UNDERSTANDING，看迁移目标是 POLISHING 还是 PLANNING。

    预置 ``brief`` 走 ``_step_understanding`` 的短路分支（``self.brief is not
    None``），从而**不发起**理解 LLM 调用、直接到 ``_polish_gate()``——
    这正是 E2 的插入点语义：理解完成（brief 已就绪）之后、规划之前由
    ``_polish_gate`` 判定是否让 POLISHING 插队。
    """
    driver._step_idle()
    # 默认 brief.enabled=true → UNDERSTANDING；但 brief 已预置 → 短路到 gate。
    if driver.state is DriverState.UNDERSTANDING:
        driver.brief = SceneBrief()
        driver._step_understanding()
    return driver.state


# ------------------------------- driver 通道 ------------------------------- #

def test_disabled_golden_zero_diff():
    """enabled=false：迁移目标恒 PLANNING，polish_result 恒 None（零行为差）。"""
    for enabled in (False, True):
        fake = FakeModel()
        driver, _audit = _make_driver(fake, enabled=enabled)
        state = _polish_gate_result(driver)
        expected = DriverState.POLISHING if enabled else DriverState.PLANNING
        assert state is expected
        if not enabled:
            assert driver.polish_result is None
            assert driver.script == SCRIPT
            # 不产生任何 polish LLM 调用
            assert not any(kind == "polish"
                           for kind in _audit.recent(200)
                           if isinstance(kind, str))


def test_disabled_run_to_planning_keeps_original():
    """关闭时跑状态机到 PLANNING：PLANNING 输入恒原稿（golden 零行为差）。"""
    fake = FakeModel()
    driver, _audit = _make_driver(fake, enabled=False)
    driver._step_idle()
    assert driver.state is DriverState.UNDERSTANDING
    driver.brief = SceneBrief()   # 预置 brief，跳过理解 LLM 调用
    driver._step_understanding()
    assert driver.state is DriverState.PLANNING
    assert driver.script == SCRIPT
    assert driver.polish_result is None


def test_polishing_runs_and_keeps_original_when_not_accepted():
    """enabled=true：POLISHING 调用一次，未采纳 → 改写稿只进 polish_result。"""
    fake = FakeModel(polish_ok=True)
    driver, audit = _make_driver(fake, enabled=True)
    state = _polish_gate_result(driver)
    assert state is DriverState.POLISHING
    driver._step_polishing()              # 发起调用
    assert driver.state is DriverState.CALLING_LLM
    driver._step_calling_llm()            # 收回复 → _finish_polish
    assert driver.state is DriverState.PLANNING
    assert driver.polish_result is not None
    assert driver.polish_result.accepted is False
    assert len(driver.polish_result.suggestions) == 2
    # 未采纳 → PLANNING 输入恒原稿（_script 不被改写）
    assert driver.script == SCRIPT
    kinds = [event.kind for event in audit.recent(200)]
    assert "polish_result" in kinds


def test_failure_fallback_once_no_retry():
    """坏 schema → 恰好一次回落＋E_POLISH_001＋不重试。"""
    fake = FakeModel(polish_ok=False)
    driver, audit = _make_driver(fake, enabled=True)
    state = _polish_gate_result(driver)
    assert state is DriverState.POLISHING
    driver._step_polishing()
    assert driver.state is DriverState.CALLING_LLM
    driver._step_calling_llm()
    assert driver.state is DriverState.PLANNING
    assert driver.polish_result is None      # 坏参数 → 没产出
    assert driver.script == SCRIPT           # 原稿没有被改写
    kinds = [event.kind for event in audit.recent(200)]
    assert "polish_degraded" in kinds
    # 不重试：polish 只调用了一次
    assert fake.calls == 1


def test_llm_error_falls_back_once():
    """传输层错误（非解析）也走一次回落，不重试。"""
    class FlakyModel:
        def __init__(self):
            self.calls = 0

        def chat(self, payload, timeout):
            self.calls += 1
            raise ConnectionError("上游 502")

    fake = FlakyModel()
    driver, audit = _make_driver(fake, enabled=True)
    driver._step_idle()
    driver.brief = SceneBrief()   # 预置 brief，跳过理解 LLM 调用
    driver._step_understanding()
    assert driver.state is DriverState.POLISHING
    driver._step_polishing()
    driver._step_calling_llm()
    assert driver.state is DriverState.PLANNING
    assert fake.calls == 1
    kinds = [event.kind for event in audit.recent(200)]
    assert "polish_degraded" in kinds


def test_polish_result_to_dict_roundtrip():
    """E1 产物补充的 to_dict 是可序列化的，且 accepted 参与往返。"""
    result = PolishResult(suggestions=["a", "b"], rewritten="R", accepted=True)
    plain = result.to_dict()
    assert plain == {"suggestions": ["a", "b"], "rewritten": "R",
                     "accepted": True}
    rebuilt = PolishResult(**plain)
    assert rebuilt == result


# ------------------------------- sidecar 通道 ------------------------------- #

def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_server_polish_under_test",
        ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


def _start(tmp_path: Path, token: str = "") -> ThreadingHTTPServer:
    argv = ["--upstream-kind", "openai",
            "--upstream", "https://api.deepseek.com",
            "--model", "deepseek-v4-pro",
            "--runs-dir", str(tmp_path / "runs"),
            "--cases-backend", "off",
            "--token", token]
    args = sidecar.parse_args(argv)
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), sidecar.make_handler(sidecar.SidecarConfig(args)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _post(base: str, path: str, body, token: str = "") -> tuple:
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"} if token else
        {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(
                response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8", "replace"))


def test_two_channels_same_shape():
    """双通道共用同一 schema 解析函数（模板/解析唯一真源）。"""
    import tools.sidecar_server as live_sidecar
    # sidecar 模块 import 的就是 driver 用的同一份构建/解析函数（单一真源）
    assert live_sidecar.build_polish_payload is sp.build_polish_payload
    assert live_sidecar.extract_polish is sp.extract_polish
    # 同一份回复经同一解析函数 → 同构产出
    reply = _polish_reply()
    parsed = sp.extract_polish(reply)
    assert parsed.suggestions == ["拆镜建议", "视线衔接"]
    assert "共用同一契约" in parsed.rewritten


def test_polish_endpoint_requires_token_and_validates_script(tmp_path):
    httpd = _start(tmp_path, token="t")
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        # 无 token → 401
        status, _ = _post(base, "/v1/ui/script/polish", {"script": "x"})
        assert status == 401
        # 空脚本 → 400
        status, payload = _post(base, "/v1/ui/script/polish",
                                {"script": "  "}, token="t")
        assert status == 400
        assert "script" in payload.get("error", "")
        # accept 缺 run_id → 400
        status, _ = _post(base, "/v1/ui/script/polish/accept", {}, token="t")
        assert status == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_polish_accept_writes_polish_json(tmp_path):
    """accept 端点把 run 目录里的 polish.json 标成 accepted=true。"""
    runs = tmp_path / "runs"
    run_dir = runs / "run_abc"
    run_dir.mkdir(parents=True)
    (run_dir / "polish.json").write_text(
        json.dumps({"suggestions": ["a"], "rewritten": "R", "accepted": False},
                   ensure_ascii=False), encoding="utf-8")
    httpd = _start(tmp_path, token="t")
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, payload = _post(base, "/v1/ui/script/polish/accept",
                                {"run_id": "run_abc"}, token="t")
        assert status == 200
        assert payload["accepted"] is True
        written = json.loads((run_dir / "polish.json")
                             .read_text(encoding="utf-8"))
        assert written["accepted"] is True
        # 不存在的 run → 404
        status, _ = _post(base, "/v1/ui/script/polish/accept",
                          {"run_id": "no_such_run"}, token="t")
        assert status == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
