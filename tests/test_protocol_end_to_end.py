"""真实 HTTP 端到端：sidecar 与直连两种模式跑同一条链。

§2.4 声称"两种模式都是一等公民，同一套核心代码同时服务两者"。前面的测试只
覆盖到契约层（编解码、错误码映射），驱动器跑的一直是**离线传输**。这里补上
真正缺的那一环：用本地假服务端（标准库 http.server，不联网、不需要 Key）同时
说 sidecar 线协议与 OpenAI 兼容协议，把整条链（计划 → 修复 → 自我审核）跑完，
并断言两种模式得到**同一份计划**。
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Tuple

import pytest

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.config import AppConfig
from block_director.contracts.enums import (
    Capability,
    Severity,
    TransportMode,
)
from block_director.contracts.messages import (
    ChatReply,
    FunctionCall,
    ToolCall,
    Usage,
)
from block_director.contracts.transport import (
    OpenAICompatibleTransport,
    SidecarTransport,
)
from block_director.knowledge.client import KnowledgeClient
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.review import REVIEW_TOOL_NAME
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.transport_factory import make_transport
from block_director.layer6_audit.audit_logger import AuditLogger

SCRIPT = "INT. 咖啡馆 - 日\n\n小明与小红隔桌对坐。\n"

PLAN = {
    "scene_heading": "INT. 咖啡馆 - 日",
    "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "建立关系",
         "shot_type": "MLS", "duration_frames": 48,
         "characters": ["char_001", "char_002"]},
        {"shot_id": "shot_002", "order": 2, "intent": "给出反应",
         "shot_type": "MCU", "duration_frames": 48,
         "characters": ["char_001"]},
    ]}


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class FakeModel:
    """按 purpose 决定回什么：计划 → 修复 → 自我审核。"""

    def __init__(self) -> None:
        self.chat_calls = 0

    @staticmethod
    def reply_for(purpose: str, request_id: str = "",
                  text: str = "") -> Tuple[ChatReply, int, int]:
        usage = Usage(prompt_tokens=120, completion_tokens=30)
        if purpose == "understand":
            # 阶段 S：空理解（合法结构、不含推断）
            call = ToolCall(id="call_brief", function=FunctionCall(
                name="emit_scene_brief",
                arguments=json.dumps({"notes": ["协议自检：空理解"]},
                                     ensure_ascii=False)))
            return ChatReply(tool_calls=[call], usage=usage, model="fake",
                             request_id=request_id,
                             finish_reason="tool_calls"), 0, 0
        if purpose == "plan":
            call = ToolCall(id="call_plan", function=FunctionCall(
                name=PLAN_TOOL_NAME, arguments=json.dumps(PLAN, ensure_ascii=False)))
            return ChatReply(tool_calls=[call], usage=usage, model="fake",
                             request_id=request_id, finish_reason="tool_calls"), 1, 0
        if purpose == "editor":
            # 阶段 B1：逐镜草案。给个空草案即可——这里验证的是协议与链路，
            # 场景质量由场景侧的测试负责。
            match = re.search(r"shot_\d+", text)
            shot_id = match.group(0) if match else PLAN["shots"][0]["shot_id"]
            call = ToolCall(id="call_editor", function=FunctionCall(
                name="emit_shot_draft",
                arguments=json.dumps({"shot_id": shot_id})))
            return ChatReply(tool_calls=[call], usage=usage, model="fake",
                             request_id=request_id, finish_reason="tool_calls"), 0, 0
        if purpose == "repair":
            call = ToolCall(id="call_repair", function=FunctionCall(
                name="setup_camera",
                arguments=json.dumps({"shot_id": "shot_001",
                                      "shot_type": "MCU"})))
            return ChatReply(tool_calls=[call], usage=usage, model="fake",
                             request_id=request_id, finish_reason="tool_calls"), 0, 1
        if purpose == "review":
            call = ToolCall(id="call_review", function=FunctionCall(
                name=REVIEW_TOOL_NAME,
                arguments=json.dumps({"verdict": "ok", "notes": "表达清楚"})))
            return ChatReply(tool_calls=[call], usage=usage, model="fake",
                             request_id=request_id, finish_reason="tool_calls"), 0, 0
        return ChatReply(content="停", usage=usage, model="fake",
                         request_id=request_id), 0, 0


class FakeServer:
    """同时实现 sidecar 线协议与 OpenAI 兼容协议。"""

    def __init__(self, *, capabilities=("llm", "bm25"), token: str = "",
                 retrieve_payload: Dict[str, Any] | None = None):
        self.model = FakeModel()
        self.capabilities = list(capabilities)
        self.token = token
        # v1.4 §2.3 / §2.3b：检索面是三条通道 ＋ trace（不是只有 cards）。
        self.retrieve_payload = retrieve_payload if retrieve_payload is not None else {
            "cards": [{"id": "c1", "domain": "axis_theory", "title": "轴线",
                       "content": "…"}],
            "edges": [{"edge_id": "hg:abc", "type": "EMOTION_PACK",
                       "members": [["allow", "emotion", "emotion:荒诞"],
                                   ["forbid", "movement", "movement:固定机位"]],
                       "forbid": [["forbid", "movement", "movement:固定机位"]],
                       "weight": 1.0, "source_span": {}, "source_kind": "theory",
                       "hardness": "hard", "occurrences": 1, "confidence": 0.7}],
            "cases": [{"case_id": "case_1", "case_type": "lesson", "title": "t",
                       "excerpt": "e", "beat_sequence": [], "source_ref": {},
                       "score": 0.4}],
            "trace": {"query": "", "backend": "hypergraph", "lanes": 2,
                      "seeds": ["emotion:荒诞"], "scores": {"hg:abc": 0.9}},
        }
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            # -- 读请求 -------------------------------------------------- #
            def _body(self) -> Dict[str, Any]:
                length = int(self.headers.get("Content-Length", 0))
                return json.loads(self.rfile.read(length) or b"{}")

            def _send(self, status: int, payload: Dict[str, Any]):
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                outer.requests.append({"path": self.path, "body": {},
                                       "headers": dict(self.headers)})
                if self.path == "/health":
                    self._send(200, {"status": "ok", "version": "1.2.0",
                                     "capabilities": outer.capabilities})
                    return
                self._send(404, {"error": "not found"})

            def do_POST(self):
                body = self._body()
                outer.requests.append({"path": self.path, "body": body,
                                       "headers": dict(self.headers)})
                if outer.token:
                    if self.headers.get("Authorization") != f"Bearer {outer.token}":
                        self._send(401, {"error": "unauthorized"})
                        return
                if self.path == "/v1/cancel":
                    self._send(200, {"cancelled": True})
                    return
                if self.path == "/v1/retrieve":
                    self._send(200, outer.retrieve_payload)
                    return
                if self.path == "/v1/chat":              # sidecar 线协议
                    reply, _r, _d = outer.model.reply_for(
                        str(body.get("purpose", "")), body.get("request_id", ""),
                        text=json.dumps(body, ensure_ascii=False))
                    outer.model.chat_calls += 1
                    self._send(200, reply.to_dict())
                    return
                if self.path == "/v1/chat/completions":  # OpenAI 兼容协议
                    reply, _r, _d = outer.model.reply_for(
                        outer._purpose(body),
                        text=json.dumps(body, ensure_ascii=False))
                    outer.model.chat_calls += 1
                    self._send(200, outer._openai_body(reply))
                    return
                self._send(404, {"error": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    # -- OpenAI 请求里没有 purpose 字段，靠系统提示的特征词还原 ---------- #
    @staticmethod
    def _purpose(body: Dict[str, Any]) -> str:
        text = json.dumps(body.get("messages", []), ensure_ascii=False)
        tool_names = [item.get("function", {}).get("name", "")
                      for item in body.get("tools", []) or []]
        if "emit_shot_draft" in tool_names:
            return "editor"
        if "emit_scene_brief" in tool_names:
            return "understand"
        if "emit_plan" in tool_names:
            return "plan"
        if "分镜计划" in text:
            return "plan"
        if "执行导演" in text:
            return "editor"
        if "未通过校验" in text:
            return "repair"
        if "审核" in text:
            return "review"
        return "other"

    @staticmethod
    def _openai_body(reply: ChatReply) -> Dict[str, Any]:
        message: Dict[str, Any] = {"role": "assistant",
                                   "content": reply.content}
        if reply.tool_calls:
            message["tool_calls"] = [
                {"id": call.id, "type": "function",
                 "function": {"name": call.function.name,
                              "arguments": call.function.arguments}}
                for call in reply.tool_calls]
        return {"model": "fake",
                "choices": [{"message": message,
                             "finish_reason": reply.finish_reason or "stop"}],
                "usage": (reply.usage.to_dict() if reply.usage else None)}

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def paths(self) -> list:
        return [item["path"] for item in self.requests]


class FlakyAuditor:
    """第一镜第一次判失败：逼出一次真实 HTTP 上的 B4 修复。"""

    def __init__(self):
        self.audited = []

    def shot_ids(self):
        return ["shot_001", "shot_002"]

    def audit(self, shot_id):
        self.audited.append(shot_id)
        if shot_id == "shot_001" and self.audited.count("shot_001") == 1:
            return AuditResult(passed=False, target=shot_id, score=60.0, errors=[
                AuditError(rule="R001", code="E_AXIS_001", message="越轴",
                           severity=Severity.ERROR, target=shot_id,
                           suggestion="同侧机位")])
        return AuditResult(passed=True, target=shot_id, score=88.0)


class StubBuilder:
    def build(self, plan, brief=None):
        return {"shots": len(plan.shots), "total_frames": plan.total_frames}


def run_chain(transport, tmp_path, *, self_review: bool = True):
    config = AppConfig()
    config.orchestration.self_review = self_review
    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(transport=transport, audit=audit, script=SCRIPT,
                          config=config, builder=StubBuilder(),
                          auditor=FlakyAuditor(),
                          limits=DriverLimits(max_repairs_per_shot=1),
                          thread_factory=InlineThread)
    state = driver.run_to_completion()
    return driver, state, audit


def read_trace(directory):
    path = directory / "llm_trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# 1. sidecar 模式跑完整条链
# --------------------------------------------------------------------------- #
def expected_calls(shots: int, repairs: int = 1) -> int:
    """一次运行的**预期调用数**（v1.4 勘误 1：不得写死 7）。

    链路 = 剧本理解 1 + 计划 1 + 单镜草案 N + 修复 R + 自我审核 N。
    夹具里恰好有一镜失败一次（R = 1），修复成功后再审一次。
    """
    return 1 + 1 + shots + repairs + shots


def test_sidecar_mode_runs_the_whole_chain(tmp_path):
    with FakeServer(token="secret-token") as server:
        transport = SidecarTransport(base_url=server.base_url,
                                     token="secret-token", timeout=5.0)
        driver, state, audit = run_chain(transport, tmp_path)
        kinds = [event.kind for event in driver.audit.recent(200)]
        trace = read_trace(tmp_path)
        paths = server.paths()

    assert state is DriverState.DONE
    assert len(driver.plan.shots) == 2
    assert "shot_audit" in kinds and "llm_call" in kinds
    calls = expected_calls(len(driver.plan.shots))
    assert driver.snapshot()["llm_calls"] == calls
    assert paths.count("/v1/chat") == calls
    assert all(item["headers"].get("Authorization") == "Bearer secret-token"
               for item in server.requests if item["path"].startswith("/v1/"))
    assert len(trace) == calls and all(item["prompt"] for item in trace)
    assert [item["purpose"] for item in trace] == [
        "understand", "plan", "editor", "editor", "repair", "review", "review"]
    assert driver.budget.state.total_tokens > 0      # usage 在协议里传回来了


def test_direct_mode_runs_the_whole_chain(tmp_path):
    with FakeServer() as server:
        transport = OpenAICompatibleTransport(
            base_url=f"{server.base_url}/v1", api_key="sk-test", timeout=5.0)
        driver, state, _audit = run_chain(transport, tmp_path)
        paths = server.paths()

    assert state is DriverState.DONE
    assert paths.count("/v1/chat/completions") == expected_calls(2)
    assert "/v1/chat" not in paths
    assert driver.budget.state.total_tokens > 0


# --------------------------------------------------------------------------- #
# 2. 两种模式得到同一份计划（§2.4 的承诺）
# --------------------------------------------------------------------------- #
def test_both_modes_produce_the_same_plan(tmp_path):
    with FakeServer() as server:
        sidecar, side_state, _ = run_chain(
            SidecarTransport(base_url=server.base_url, timeout=5.0),
            tmp_path / "side")
    with FakeServer() as server:
        direct, direct_state, _ = run_chain(
            OpenAICompatibleTransport(base_url=f"{server.base_url}/v1",
                                      timeout=5.0),
            tmp_path / "direct")

    assert side_state is direct_state is DriverState.DONE
    assert sidecar.plan.to_dict() == direct.plan.to_dict()
    assert sidecar.snapshot()["audits"] == direct.snapshot()["audits"]
    assert sidecar.snapshot()["repairs"] == direct.snapshot()["repairs"]


# --------------------------------------------------------------------------- #
# 3. §2.5 的传输选择策略在真实 HTTP 上成立
# --------------------------------------------------------------------------- #
def test_auto_prefers_a_live_sidecar():
    with FakeServer() as server:
        config = AppConfig()
        config.llm.transport = TransportMode.AUTO
        config.llm.sidecar_url = server.base_url
        transport, mode = make_transport(config)
    assert mode == "sidecar" and isinstance(transport, SidecarTransport)
    assert "/health" in server.paths()


def test_auto_falls_back_to_direct_when_the_sidecar_is_down():
    config = AppConfig()
    config.llm.transport = TransportMode.AUTO
    config.llm.sidecar_url = "http://127.0.0.1:9"      # 必然不可达
    config.llm.base_url = "http://127.0.0.1:9/v1"
    config.llm.api_key = "sk-test"
    transport, mode = make_transport(config)
    assert mode == "direct"


def test_sidecar_capabilities_come_from_health():
    with FakeServer(capabilities=("llm", "bm25", "vector")) as server:
        status = SidecarTransport(base_url=server.base_url, timeout=5.0).health()
    assert status.ok and Capability.VECTOR in status.capabilities


def test_retrieve_carries_three_lanes_over_real_http():
    """§2.3 / §2.3b：真实的线协议上，检索面是三条通道 ＋ 可重放的 trace。"""
    with FakeServer(capabilities=("llm", "bm25", "hypergraph")) as server:
        transport = SidecarTransport(base_url=server.base_url, timeout=5.0)
        events = []
        client = KnowledgeClient(transport, audit=events.append)
        response = client.retrieve("情绪=荒诞；运镜=固定", top_k=3)
        cards_only = transport.retrieve("情绪=荒诞", top_k=3)
    assert [card.id for card in response.cards] == ["c1"]
    assert response.edges[0].forbid == [["forbid", "movement", "movement:固定机位"]]
    assert response.cases[0].case_id == "case_1"
    assert response.trace["backend"] == "hypergraph"
    assert response.trace["lanes"] == 2
    # 旧调用点仍只拿卡片，行为不变。
    assert [card.id for card in cards_only] == ["c1"]
    # 记账与留痕：一次调用一条事件，且分列（§2.4）。
    assert client.retrieval_calls == 1
    assert events[0]["forbid_members"] == 1
    assert events[0]["lanes"] == 2


# --------------------------------------------------------------------------- #
# 4. 协议级失败被如实上报，且不静默降级
# --------------------------------------------------------------------------- #
def test_sidecar_http_error_maps_to_an_llm_error_code(tmp_path):
    from block_director.contracts.errors import ErrorCode
    from block_director.contracts.transport import TransportError
    from block_director.contracts.messages import ChatPayload

    with FakeServer(token="right-token") as server:
        wrong = SidecarTransport(base_url=server.base_url, token="wrong", timeout=5.0)
        with pytest.raises(TransportError) as excinfo:
            wrong.chat(ChatPayload(messages=[]), timeout=5.0)
    # §2.5 的映射：4xx 是"请求/格式类" → E_LLM_002；5xx 才是 E_LLM_001
    assert excinfo.value.code is ErrorCode.LLM_002
    assert excinfo.value.http_status == 401
