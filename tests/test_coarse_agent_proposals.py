"""Coarse revisions are Agent decisions bounded by program measurements."""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest
from PIL import Image

from block_director.cinema.coarse_loop import run_coarse_revision_loop
from block_director.contracts.coarse_proposal import (
    CoarseProposalError,
    CoarseProposalRequest,
    emit_coarse_proposal_tool,
    validate_coarse_proposal,
)
from block_director.contracts.messages import (
    ChatReply,
    FunctionCall,
    ToolCall,
    Usage,
)
from block_director.layer5_orchestrator.coarse_agent import (
    AgentCoarseProposalProvider,
    failed_shot_ids,
)
from block_director.layer5_orchestrator.budget import Budget, BudgetLimits
from block_director.layer6_audit.audit_logger import AuditLogger


def _reference():
    return {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "scene",
        "characters": [{
            "name": "甲",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
        }],
        "props": [],
        "anchors": [],
        "camera_intents": [{
            "shot_id": "shot_001",
            "position": [0.0, 3.0, 1.5],
            "target": [0.0, 0.0, 1.0],
            "lens": 35.0,
            "movement": None,
        }],
        "shots": [{
            "shot_id": "shot_001",
            "order": 1,
            "duration_frames": 24,
            "characters": ["甲"],
            "actions": [],
        }],
        "revisions": [],
        "notes": [],
    }


def _report(score):
    return {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": "scene",
        "verdict": "pass" if score > 80.0 else "fail",
        "findings": [],
        "checks": [{
            "check_id": "composition",
            "shot_id": "shot_001",
            "actual": score,
            "threshold": 80.0,
            "verdict": "pass" if score > 80.0 else "fail",
        }],
        "visual_states": [],
    }


def test_failed_shot_priority_keeps_composition_failures_visible():
    """A composition failure cannot be hidden behind softer area diagnostics.

    Real node123 attempt-006 had shot_006 at 69.4 but the first prompt only
    carried shot_007/002/010.  The generic ascending ``actual`` sort mixed
    "lower is worse" composition scores with "higher is worse" subject-area
    ratios, so the Agent never received shot_006's context or frames.
    """
    report = {
        "findings": [{
            "check_id": "E_FOREGROUND_OCCLUSION",
            "shot_id": "shot_007",
            "severity": "error",
        }],
        "checks": [
            {"check_id": "subject_area", "shot_id": "shot_002",
             "actual": 0.66, "threshold": 0.55, "verdict": "fail"},
            {"check_id": "subject_area", "shot_id": "shot_005",
             "actual": 1.0, "threshold": 0.55, "verdict": "fail"},
            {"check_id": "composition", "shot_id": "shot_006",
             "actual": 69.4, "threshold": 80.0, "verdict": "fail"},
            {"check_id": "composition", "shot_id": "shot_007",
             "actual": 70.7, "threshold": 80.0, "verdict": "fail"},
            {"check_id": "subject_area", "shot_id": "shot_010",
             "actual": 0.83, "threshold": 0.55, "verdict": "fail"},
        ],
    }

    assert failed_shot_ids(report)[:3] == [
        "shot_007",
        "shot_006",
        "shot_005",
    ]


def _frames_for_shot(tmp_path):
    frames = []
    for phase, frame in (("first", 1), ("middle", 12), ("last", 24)):
        path = tmp_path / f"shot_001_{phase}.png"
        Image.new("RGB", (8, 6), (20, 40, 60)).save(path)
        frames.append({
            "shot_id": "shot_001",
            "phase": phase,
            "frame": frame,
            "path": str(path),
            "file_sha256": "a" * 64,
            "pixel_sha256": "b" * 64,
            "readable": True,
        })
    return tuple(frames)


def test_failed_coarse_without_agent_provider_is_named_blocked():
    """A deterministic prescription builder may not impersonate the Agent."""
    initial = _reference()
    rebuild_calls = []

    outcome = run_coarse_revision_loop(
        reference=initial,
        report_loader=lambda _reference: _report(70.0),
        rebuild=lambda reference: rebuild_calls.append(copy.deepcopy(reference)),
        max_revisions=3,
    )

    assert outcome["status"] == "blocked"
    assert "agent" in outcome["blocked_reason"].lower()
    assert "provider" in outcome["blocked_reason"].lower()
    assert rebuild_calls == []
    assert outcome["reference"]["revisions"] == []
    assert outcome["rounds"][0]["prescriptions"] == []


def test_agent_proposal_drives_failed_coarse_iteration():
    """The loop asks the Agent, then the program applies and remeasures."""
    requests = []
    observations = iter([_report(70.0), _report(82.0)])

    def provider(request):
        requests.append(request)
        return {
            "schema_version": "coarse-proposal/v1",
            "source": "agent",
            "provider_kind": "test_agent",
            "observation_id": request.observation_id,
            "frame_digests": request.frame_digests,
            "rag_provenance": {"injected_ids": [], "queries": []},
            "rationale": "把镜头向主体推近，保持主体占画幅。",
            "prescriptions": [{
                "prescription_id": "agent_shot_001_push",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "axis": "distance",
                "direction": "in",
                "magnitude": 0.3,
                "reason": "主观测量偏低，按当前机位推近",
                "evidence_refs": [
                    "composition:shot_001",
                    f"frame:{request.observation_id}:first",
                ],
                "current_value": {
                    "position": {"x": 0.0, "y": 3.0, "z": 1.5},
                    "target": {"x": 0.0, "y": 0.0, "z": 1.0},
                },
                "target_value": {
                    "position": {"x": 0.0, "y": 2.7, "z": 1.5},
                    "target": {"x": 0.0, "y": 0.0, "z": 1.0},
                },
                "derived_from": {
                    "check_id": "composition",
                    "verdict": "fail",
                },
            }],
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: next(observations),
        rebuild=lambda _reference: None,
        proposal_provider=provider,
        max_revisions=3,
    )

    assert outcome["status"] == "approved"
    assert len(requests) == 1
    assert requests[0].round_no == 1
    assert requests[0].report["checks"][0]["actual"] == 70.0
    assert outcome["rounds"][0]["proposal_source"] == "agent"
    assert outcome["rounds"][0]["applied_count"] == 1
    assert outcome["reference"]["camera_intents"][0]["position"] == [
        0.0,
        2.7,
        1.5,
    ]


def test_fixture_proposal_requires_explicit_opt_in():
    """Offline fixture output must be visible and cannot silently pass as Agent."""
    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: _report(70.0),
        rebuild=lambda _reference: None,
        proposal_provider=lambda request: {
            "schema_version": "coarse-proposal/v1",
            "source": "offline_fixture",
            "observation_id": request.observation_id,
            "prescriptions": [],
        },
            max_revisions=2,
    )

    assert outcome["status"] == "blocked"
    assert "offline_fixture" in outcome["blocked_reason"]


def test_agent_provider_blocks_before_text_only_fallback_when_frames_are_missing():
    class MustNotCallTransport:
        model = "vision-director"

        def chat(self, payload):
            raise AssertionError(f"transport must not be called: {payload}")

    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-1",
        reference=_reference(),
        report={
            **_report(70.0),
            "visual_states": [],
        },
        frames=(),
    )
    provider = AgentCoarseProposalProvider(
        transport=MustNotCallTransport(),
        knowledge=None,
    )

    with pytest.raises(
        CoarseProposalError,
        match="visual_evidence_incomplete.*shot_001.*first.*middle.*last",
    ) as raised:
        provider(request=request)
    assert raised.value.code == "visual_evidence_incomplete"


def test_agent_provider_names_a_missing_tool_call_as_protocol_error(tmp_path):
    frames = _frames_for_shot(tmp_path)

    class TextOnlyTransport:
        model = "vision-director"

        def chat(self, payload):
            return ChatReply(content="I would move the camera.", tool_calls=[])

    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-1",
        reference=_reference(),
        report=_report(70.0),
        frames=tuple(frames),
    )

    with pytest.raises(CoarseProposalError) as raised:
        AgentCoarseProposalProvider(
            transport=TextOnlyTransport(),
            knowledge=None,
        )(request=request)

    assert raised.value.code == "agent_proposal_protocol_error"
    assert "emit_coarse_proposal" in str(raised.value)


def test_agent_provider_names_invalid_tool_json_as_protocol_error(tmp_path):
    class InvalidJsonTransport:
        model = "vision-director"

        def chat(self, payload):
            return ChatReply(
                tool_calls=[ToolCall(
                    id="call-invalid-json",
                    function=FunctionCall(
                        name="emit_coarse_proposal",
                        arguments="{not valid json",
                    ),
                )],
            )

    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-invalid-json",
        reference=_reference(),
        report=_report(70.0),
        frames=_frames_for_shot(tmp_path),
    )

    with pytest.raises(CoarseProposalError) as raised:
        AgentCoarseProposalProvider(
            transport=InvalidJsonTransport(),
            knowledge=None,
        )(request=request)

    assert raised.value.code == "agent_proposal_protocol_error"
    assert raised.value.recoverable is True
    assert "arguments are invalid" in str(raised.value)


def test_malformed_tool_json_is_retried_on_the_same_observation(tmp_path):
    """A bad tool serialization must preserve the rendered observation.

    Re-rendering and re-planning after one malformed model reply throws away
    the exact visual evidence the Agent was asked to improve.  The retry stays
    on the same observation and receives the named protocol failure in
    ``previous_rounds``.
    """
    frames = _frames_for_shot(tmp_path)

    class RecoveringTransport:
        model = "director-test"

        def __init__(self):
            self.payloads = []

        def chat(self, payload):
            self.payloads.append(payload)
            if len(self.payloads) == 1:
                return ChatReply(
                    tool_calls=[ToolCall(
                        id="bad-json",
                        function=FunctionCall(
                            name="emit_coarse_proposal",
                            arguments=(
                                '{"schema_version":"coarse-proposal/v1",'
                                '"reason":"broken"'
                            ),
                        ),
                    )],
                )
            return ChatReply(
                tool_calls=[ToolCall(
                    id="fixed-json",
                    function=FunctionCall(
                        name="emit_coarse_proposal",
                        arguments=json.dumps({
                            "schema_version": "coarse-proposal/v1",
                            "reason": "按协议错误反馈重新提交",
                            "prescriptions": [{
                                "prescription_id": "retry-valid",
                                "scope": "camera",
                                "shot_id": "shot_001",
                                "entity": "cam_shot_001",
                                "component": "distance",
                                "target_value": {
                                    "position": {
                                        "x": 0.0, "y": 2.7, "z": 1.5,
                                    },
                                    "target": {
                                        "x": 0.0, "y": 0.0, "z": 1.0,
                                    },
                                },
                                "reason": "保持目标点并沿视线推近",
                                "evidence_refs": ["composition:shot_001"],
                            }],
                        }, ensure_ascii=False),
                    ),
                )],
            )

    transport = RecoveringTransport()
    report_count = 0
    rebuilt = []

    def load_report(_reference):
        nonlocal report_count
        report_count += 1
        return {
            "observation_id": f"obs-{report_count}",
            "complete": True,
            "report": _report(70.0 if report_count == 1 else 82.0),
            "frames": frames,
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=load_report,
        rebuild=lambda reference: rebuilt.append(copy.deepcopy(reference)),
        proposal_provider=AgentCoarseProposalProvider(
            transport=transport,
        ),
        max_revisions=2,
        max_proposal_rejections=2,
    )

    assert outcome["status"] == "approved"
    assert report_count == 2
    assert len(rebuilt) == 1
    assert len(transport.payloads) == 2
    assert outcome["rounds"][0]["disposition"] == "proposal_rejected"
    assert outcome["rounds"][0]["provider_error"]["code"] == (
        "agent_proposal_protocol_error")
    assert outcome["proposal_rejection_count"] == 1

    second_parts = transport.payloads[1].messages[1].content
    text = next(
        part["text"] for part in second_parts if part.get("type") == "text")
    compact = json.loads(text.split("\n", 1)[1])
    retry = compact["previous_rounds"][-1]
    assert retry["proposal_rejected"] is True
    assert "arguments are invalid" in retry["rejection_reason"]


def test_offline_fixture_names_an_empty_proposal(tmp_path):
    from block_director.layer5_orchestrator.coarse_agent import (
        OfflineFixtureCoarseProposalProvider,
    )

    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-1",
        reference=_reference(),
        report={
            **_report(70.0),
            "findings": [],
            "checks": [],
            "verdict": "fail",
        },
        frames=(),
    )

    with pytest.raises(CoarseProposalError) as raised:
        OfflineFixtureCoarseProposalProvider()(request=request)

    assert raised.value.code == "offline_fixture_no_prescriptions"


def test_offline_fixture_does_not_stack_distance_on_empty_wall_repair(tmp_path):
    from block_director.layer5_orchestrator.coarse_agent import (
        OfflineFixtureCoarseProposalProvider,
    )

    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-empty-wall",
        reference=_reference(),
        report={
            **_report(0.0),
            "verdict": "fail",
            "findings": [{
                "check_id": "E_BLOCKOUT_EMPTY_WALL",
                "shot_id": "shot_001",
                "severity": "error",
                "message": "subject is outside the frame",
            }],
            "checks": [{
                "check_id": "on_screen",
                "shot_id": "shot_001",
                "actual": 0.0,
                "threshold": 0.05,
                "verdict": "fail",
            }],
        },
        frames=(),
    )

    proposal = OfflineFixtureCoarseProposalProvider()(request=request)

    assert [
        row["prescription_id"] for row in proposal["prescriptions"]
    ] == ["p_coarse_shot_001_empty_wall"]


def test_coarse_loop_preserves_a_typed_provider_blocked_code():
    from block_director.cinema.coarse_loop import run_coarse_revision_loop

    class MissingFramesProvider:
        provider_kind = "agent_model"

        def __call__(self, request):
            raise CoarseProposalError(
                "visual_evidence_incomplete: shot_001[first,middle,last]",
                code="visual_evidence_incomplete",
            )

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: _report(70.0),
        rebuild=lambda _reference: None,
        proposal_provider=MissingFramesProvider(),
        max_revisions=2,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "visual_evidence_incomplete"
    assert outcome["rounds"][0]["provider_error"]["code"] == (
        "visual_evidence_incomplete")


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    [
        (
            "unknown_shot",
            lambda item: item.update({"shot_id": "shot_999"}),
        ),
        (
            "scope_out_of_contract",
            lambda item: item.update({"scope": "character"}),
        ),
        (
            "foreign_camera_entity",
            lambda item: item.update({"entity": "cam_shot_999"}),
        ),
        (
            "nan_coordinate",
            lambda item: item["target_value"]["position"].update({
                "x": float("nan"),
            }),
        ),
        (
            "infinite_number",
            lambda item: item.update({
                "component": "position.y",
                "target_value": float("inf"),
            }),
        ),
    ],
)
def test_coarse_loop_rejects_invalid_agent_prescriptions(
    case_id, mutate,
):
    """Malformed Agent authority never mutates or rebuilds the scene."""
    del case_id
    rebuild_calls = []

    def proposal(request):
        item = {
            "prescription_id": "invalid-agent-change",
            "scope": "camera",
            "shot_id": "shot_001",
            "entity": "cam_shot_001",
            "component": "distance",
            "target_value": {
                "position": {"x": 0.0, "y": 2.5, "z": 1.5},
                "target": {"x": 0.0, "y": 0.0, "z": 1.0},
            },
            "reason": "test invalid authority",
            "evidence_refs": ["composition:shot_001"],
        }
        mutate(item)
        return {
            "schema_version": "coarse-proposal/v1",
            "source": "agent",
            "provider_kind": "agent_model",
            "observation_id": request.observation_id,
            "reason": "invalid proposal fixture",
            "prescriptions": [item],
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: _report(70.0),
        rebuild=lambda reference: rebuild_calls.append(copy.deepcopy(reference)),
        proposal_provider=proposal,
        max_revisions=2,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "agent_proposal_rejected"
    assert outcome["rounds"][0]["proposal_rejected"] is True
    assert rebuild_calls == []


def test_coarse_loop_rejects_an_empty_agent_proposal():
    rebuild_calls = []

    class EmptyProposalProvider:
        provider_kind = "agent_model"

        def __call__(self, request):
            return {
                "schema_version": "coarse-proposal/v1",
                "source": "agent",
                "provider_kind": self.provider_kind,
                "observation_id": request.observation_id,
                "reason": "empty is not a revision",
                "prescriptions": [],
            }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: _report(70.0),
        rebuild=lambda reference: rebuild_calls.append(copy.deepcopy(reference)),
        proposal_provider=EmptyProposalProvider(),
        max_revisions=2,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "agent_proposal_rejected"
    assert "non-empty" in outcome["blocked_reason"]
    assert rebuild_calls == []


def test_rejected_agent_proposal_is_retried_with_history_on_same_observation():
    """A malformed proposal is recoverable agent feedback, not a dead run.

    Real node123 evidence: the director proposed ``entity="camera"`` for
    ``shot_007``.  The deterministic validator correctly rejected it, but the
    loop immediately blocked the whole plan attempt and re-ran planning.  The
    next agent call needs the named rejection and must happen against the same
    rendered observation; a bad tool argument must not trigger another render.
    """
    load_count = 0
    provider_calls = []
    rebuild_calls = []

    def load_report(_reference):
        nonlocal load_count
        load_count += 1
        return _report(70.0 if load_count == 1 else 82.0)

    def provider(request):
        provider_calls.append(copy.deepcopy(request.history))
        if len(provider_calls) == 1:
            prescription = {
                "prescription_id": "bad-camera-entity",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "camera",
                "component": "position.y",
                "target_value": 3.2,
                "reason": "抬高机位",
                "evidence_refs": ["frame:first"],
            }
        else:
            prescription = {
                "prescription_id": "retry-with-exact-camera-id",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "target_value": {
                    "position": {"x": 0.0, "y": 2.7, "z": 1.5},
                    "target": {"x": 0.0, "y": 0.0, "z": 1.0},
                },
                "reason": "按拒绝反馈改用精确相机 id 并推近",
                "evidence_refs": ["composition:shot_001"],
            }
        return {
            "schema_version": "coarse-proposal/v1",
            "source": "agent",
            "provider_kind": "test_agent",
            "observation_id": request.observation_id,
            "reason": "局部相机修正",
            "prescriptions": [prescription],
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=load_report,
        rebuild=lambda reference: rebuild_calls.append(
            copy.deepcopy(reference)),
        proposal_provider=provider,
        max_revisions=2,
        max_proposal_rejections=2,
    )

    assert outcome["status"] == "approved"
    assert load_count == 2, "拒绝处方不得重复观察同一物理版本"
    assert len(provider_calls) == 2
    assert provider_calls[0] == ()
    rejection = provider_calls[1][-1]
    assert rejection["disposition"] == "proposal_rejected"
    assert rejection["proposal_rejected"] is True
    assert "does not belong to shot_001" in rejection["rejection_reason"]
    assert rejection["prescriptions"][0]["entity"] == "camera"
    assert rejection["prescriptions"][0]["rejected"] is True
    assert len(rebuild_calls) == 1
    assert outcome["proposal_rejection_count"] == 1
    assert outcome["rounds"][0]["proposal_rejected"] is True
    assert outcome["rounds"][1]["applied_count"] == 1


def test_rejection_limit_is_consecutive_per_observation_not_run_cumulative():
    """One recoverable rejection on each observation must not exhaust the loop.

    The cumulative count is useful evidence, but the retry ceiling belongs to
    the currently rendered observation.  Otherwise two ordinary agent-argument
    slips on different physical candidates would block a run before either
    candidate could be measured.
    """
    observations = iter([_report(70.0), _report(75.0), _report(82.0)])
    proposals = []

    def provider(request):
        proposals.append(copy.deepcopy(request.history))
        shot_number = len(proposals)
        if shot_number in (1, 3):
            prescription = {
                "prescription_id": f"bad-camera-entity-{shot_number}",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "camera",
                "component": "position.y",
                "target_value": 3.4,
                "reason": "故意使用泛化相机名称以触发校验失败",
                "evidence_refs": ["composition:shot_001"],
            }
        else:
            position_y = 2.8 if shot_number == 2 else 2.6
            prescription = {
                "prescription_id": f"exact-camera-{shot_number}",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "target_value": {
                    "position": {"x": 0.0, "y": position_y, "z": 1.5},
                    "target": {"x": 0.0, "y": 0.0, "z": 1.0},
                },
                "reason": "按拒绝反馈改用精确相机 id",
                "evidence_refs": ["composition:shot_001"],
            }
        return {
            "schema_version": "coarse-proposal/v1",
            "source": "agent",
            "provider_kind": "test_agent",
            "observation_id": request.observation_id,
            "reason": "跨观察连续恢复探针",
            "prescriptions": [prescription],
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _reference: next(observations),
        rebuild=lambda _reference: None,
        proposal_provider=provider,
        max_revisions=3,
        max_proposal_rejections=2,
    )

    assert outcome["status"] == "approved"
    assert len(proposals) == 4
    assert outcome["proposal_rejection_count"] == 2
    assert sum(
        bool(row.get("proposal_rejected"))
        for row in outcome["rounds"]
    ) == 2


def test_agent_provider_records_the_actual_reply_identity_and_usage(tmp_path):
    frames = _frames_for_shot(tmp_path)

    class FakeKnowledge:
        def __init__(self):
            self.calls = []

        def block_for_shot(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return "粗排知识"

    class FakeTransport:
        model = "configured-model"
        provider = "configured-provider"

        def chat(self, payload):
            assert any(
                part.get("type") == "image_url"
                for part in payload.messages[1].content
            )
            return ChatReply(
                tool_calls=[ToolCall(
                    id="call-1",
                    function=FunctionCall(
                        name="emit_coarse_proposal",
                        arguments=json.dumps({
                            "schema_version": "coarse-proposal/v1",
                            "reason": "adjust",
                            "prescriptions": [{
                                "prescription_id": "p1",
                                "scope": "camera",
                                "shot_id": "shot_001",
                                "entity": "cam_shot_001",
                                "component": "distance",
                                "target_value": {
                                    "position": {"x": 0, "y": 2.5, "z": 1.5},
                                    "target": {"x": 0, "y": 0, "z": 1},
                                },
                                "reason": "test",
                                "evidence_refs": ["composition:shot_001"],
                            }],
                        }),
                    ),
                )],
                usage=Usage(100, 50, 150),
                request_id="request-1",
                model="reply-model",
                finish_reason="tool_calls",
            )

    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-1",
        reference=_reference(),
        report=_report(70.0),
        frames=tuple(frames),
    )
    knowledge = FakeKnowledge()
    proposal = AgentCoarseProposalProvider(
        transport=FakeTransport(),
        knowledge=knowledge,
    )(request=request)

    provider = proposal["provider"]
    assert provider["model"] == "reply-model"
    assert provider["configured_model"] == "configured-model"
    assert provider["transport_provider"] == "configured-provider"
    assert provider["usage"] == {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }
    assert provider["finish_reason"] == "tool_calls"
    assert provider["request_id"] == "request-1"
    assert provider["tool_call_id"] == "call-1"
    assert set(provider["frame_digests"]) == {
        "shot_001:first",
        "shot_001:middle",
        "shot_001:last",
    }
    assert knowledge.calls
    assert {
        call[1]["stage"] for call in knowledge.calls
    } == {"coarse"}


def test_coarse_provenance_binds_each_trace_event_to_its_own_shot(tmp_path):
    frames = []
    for shot_id in ("shot_001", "shot_002"):
        for phase, frame in (("first", 1), ("middle", 12), ("last", 24)):
            path = tmp_path / f"{shot_id}_{phase}.png"
            Image.new("RGB", (8, 6), (20, 40, 60)).save(path)
            frames.append({
                "shot_id": shot_id,
                "phase": phase,
                "frame": frame,
                "path": str(path),
                "file_sha256": "a" * 64,
                "pixel_sha256": "b" * 64,
                "readable": True,
            })

    class CumulativeKnowledge:
        def __init__(self):
            self.events = []

        def block_for_shot(self, _shot_type, _intent="", _actions=(),
                           shot_id="", **_kwargs):
            number = len(self.events) + 1
            self.events.append({
                "retrieval_event_id": f"retrieval-{number:04d}",
                "stage": "coarse",
                "scope": "shot",
                "shot_id": shot_id,
                "hit_card_ids": [f"card-{shot_id}"],
                "injected_card_ids": [f"card-{shot_id}"],
                "actual_injected_tokens": number * 5,
                "drops": [],
                "actual_backend": "bm25",
                "degraded": False,
                "injected": True,
            })
            return f"block-{shot_id}"

        def trace_payload(self):
            return {
                "backend": "bm25",
                "degraded": False,
                "degraded_reason": "",
                "retrieval_events": copy.deepcopy(self.events),
                "shot_scope": {"cumulative": len(self.events)},
            }

    class FakeTransport:
        def chat(self, _payload):
            return ChatReply(tool_calls=[ToolCall(
                id="coarse-provenance",
                function=FunctionCall(
                    name="emit_coarse_proposal",
                    arguments=json.dumps({
                        "schema_version": "coarse-proposal/v1",
                        "reason": "adjust",
                        "prescriptions": [{
                            "prescription_id": "p1",
                            "scope": "camera",
                            "shot_id": "shot_001",
                            "entity": "cam_shot_001",
                            "component": "distance",
                            "target_value": {
                                "position": {"x": 0, "y": 2.5, "z": 1.5},
                                "target": {"x": 0, "y": 0, "z": 1},
                            },
                            "reason": "test",
                            "evidence_refs": ["composition:shot_001"],
                        }],
                    }),
                ),
            )])

    reference = _reference()
    reference["shots"].append({
        "shot_id": "shot_002",
        "order": 2,
        "duration_frames": 24,
        "characters": ["甲"],
        "actions": [],
    })
    report = _report(70.0)
    report["checks"].append({
        "check_id": "composition",
        "shot_id": "shot_002",
        "actual": 68.0,
        "threshold": 80.0,
        "verdict": "fail",
    })
    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-two-shots",
        reference=reference,
        report=report,
        frames=tuple(frames),
    )

    proposal = AgentCoarseProposalProvider(
        transport=FakeTransport(),
        knowledge=CumulativeKnowledge(),
    )(request=request)

    provenance = proposal["knowledge_provenance"]
    first_events = provenance["per_shot_events"]["shot_001"]
    second_events = provenance["per_shot_events"]["shot_002"]
    assert len(first_events) == len(second_events) == 1
    assert [event["shot_id"] for event in first_events] == ["shot_001"]
    assert [event["shot_id"] for event in second_events] == ["shot_002"]
    assert {
        event["retrieval_event_id"] for event in provenance["events"]
    } == {"retrieval-0001", "retrieval-0002"}
    assert provenance["event_count"] == 2
    assert provenance["summary"]["actual_injected_tokens"] == 15
    assert set(provenance["summary"]["hit_card_ids"]) == {
        "card-shot_001", "card-shot_002"}


def test_agent_provider_records_usage_against_the_shared_run_budget(tmp_path):
    frames = _frames_for_shot(tmp_path)

    class FakeTransport:
        model = "configured-model"

        def chat(self, payload):
            return ChatReply(
                tool_calls=[ToolCall(
                    id="call-budget",
                    function=FunctionCall(
                        name="emit_coarse_proposal",
                        arguments=json.dumps({
                            "schema_version": "coarse-proposal/v1",
                            "reason": "budget accounting",
                            "prescriptions": [{
                                "prescription_id": "p-budget",
                                "scope": "camera",
                                "shot_id": "shot_001",
                                "entity": "cam_shot_001",
                                "component": "distance",
                                "target_value": {
                                    "position": {
                                        "x": 0.0, "y": 2.5, "z": 1.5},
                                    "target": {
                                        "x": 0.0, "y": 0.0, "z": 1.0},
                                },
                                "reason": "test budget",
                                "evidence_refs": ["composition:shot_001"],
                            }],
                        }),
                    ),
                )],
                usage=Usage(100, 50, 150),
                request_id="request-budget",
                model="reply-model",
            )

    budget = Budget(BudgetLimits(
        max_llm_calls=5,
        max_tokens=1000,
        max_cost_usd=0.0,
        max_wall_seconds=0.0,
    ))
    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-budget",
        reference=_reference(),
        report=_report(70.0),
        frames=tuple(frames),
    )

    AgentCoarseProposalProvider(
        transport=FakeTransport(),
        budget=budget,
    )(request=request)

    assert budget.state.llm_calls == 1
    assert budget.state.prompt_tokens == 100
    assert budget.state.completion_tokens == 50
    assert budget.state.total_tokens == 150


def test_agent_provider_refuses_to_call_when_budget_is_exhausted(tmp_path):
    frames = _frames_for_shot(tmp_path)

    class ForbiddenTransport:
        model = "configured-model"

        def chat(self, payload):
            raise AssertionError("transport must not be called after exhaustion")

    budget = Budget(BudgetLimits(
        max_llm_calls=1,
        max_tokens=0,
        max_cost_usd=0.0,
        max_wall_seconds=0.0,
    ))
    budget.record_llm(None)
    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-exhausted",
        reference=_reference(),
        report=_report(70.0),
        frames=tuple(frames),
    )

    with pytest.raises(CoarseProposalError) as caught:
        AgentCoarseProposalProvider(
            transport=ForbiddenTransport(),
            budget=budget,
        )(request=request)

    assert caught.value.code == "coarse_budget_exhausted"
    assert budget.state.llm_calls == 1


def test_agent_provider_counts_a_failed_transport_attempt(tmp_path):
    frames = _frames_for_shot(tmp_path)

    class ExplodingTransport:
        model = "configured-model"

        def chat(self, payload):
            raise TimeoutError("synthetic transport timeout")

    budget = Budget(BudgetLimits(
        max_llm_calls=5,
        max_tokens=0,
        max_cost_usd=0.0,
        max_wall_seconds=0.0,
    ))
    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-failed",
        reference=_reference(),
        report=_report(70.0),
        frames=tuple(frames),
    )

    with pytest.raises(TimeoutError, match="synthetic transport timeout"):
        AgentCoarseProposalProvider(
            transport=ExplodingTransport(),
            budget=budget,
        )(request=request)

    assert budget.state.llm_calls == 1
    assert budget.state.total_tokens == 0


def test_agent_provider_writes_coarse_call_to_the_unified_llm_trace(tmp_path):
    frames = _frames_for_shot(tmp_path)

    class FakeTransport:
        model = "configured-model"

        def chat(self, payload):
            return ChatReply(
                tool_calls=[ToolCall(
                    id="call-trace",
                    function=FunctionCall(
                        name="emit_coarse_proposal",
                        arguments=json.dumps({
                            "schema_version": "coarse-proposal/v1",
                            "reason": "adjust",
                            "prescriptions": [{
                                "prescription_id": "p-trace",
                                "scope": "camera",
                                "shot_id": "shot_001",
                                "entity": "cam_shot_001",
                                "component": "distance",
                                "target_value": {
                                    "position": {
                                        "x": 0.0, "y": 2.5, "z": 1.5},
                                    "target": {
                                        "x": 0.0, "y": 0.0, "z": 1.0},
                                },
                                "reason": "test trace",
                                "evidence_refs": ["composition:shot_001"],
                            }],
                        }),
                    ),
                )],
                request_id="request-trace",
                model="reply-model",
            )

    audit = AuditLogger(directory=tmp_path)
    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-trace",
        reference=_reference(),
        report=_report(70.0),
        frames=tuple(frames),
    )
    AgentCoarseProposalProvider(
        transport=FakeTransport(),
        audit=audit,
    )(request=request)

    raw = audit.trace_path.read_text(encoding="utf-8").strip()
    record = json.loads(raw)
    assert record["purpose"] == "coarse"
    assert record["request_id"] == "request-trace"
    assert record["tool_calls"] == ["emit_coarse_proposal"]
    assert record["response"]["tool_calls"][0]["name"] == (
        "emit_coarse_proposal")
    assert "previous_rounds" in record["prompt"][1]["content"]
    assert "data:image/" not in raw


def test_agent_prompt_contains_previous_round_decisions(tmp_path):
    frames = _frames_for_shot(tmp_path)

    class CaptureTransport:
        model = "director-test"

        def __init__(self):
            self.payload = None

        def chat(self, payload):
            self.payload = payload
            return ChatReply(content="missing tool call")

    transport = CaptureTransport()
    request = CoarseProposalRequest(
        round_no=2,
        observation_id="obs-round-2",
        reference=_reference(),
        report=_report(70.0),
        frames=tuple(frames),
        history=({
            "round_no": 1,
            "disposition": "revert",
            "candidate_score": 62.5,
            "best_score_before": 70.0,
            "best_score_after": 70.0,
            "candidate_fingerprint": "candidate-1",
            "prescriptions": [{
                "prescription_id": "previous-push",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "target_value": {
                    "position": {"x": 0.0, "y": 2.7, "z": 1.5},
                },
                "applied": True,
                "no_op": False,
            }],
        },),
    )

    with pytest.raises(CoarseProposalError, match="no emit_coarse_proposal"):
        AgentCoarseProposalProvider(transport=transport)(request=request)

    user_content = transport.payload.messages[1].content
    text = next(part["text"] for part in user_content
                if part.get("type") == "text")
    compact = json.loads(text.split("\n", 1)[1])

    assert compact["previous_rounds"] == [{
        "round_no": 1,
        "disposition": "revert",
        "candidate_score": 62.5,
        "best_score_before": 70.0,
        "best_score_after": 70.0,
        "candidate_fingerprint": "candidate-1",
        "candidate_reference_repeated": False,
        "cycle_detected": False,
        "provider_kind": "",
        "reason": "",
        "proposal_rejected": False,
        "rejection_reason": "",
        "prescriptions": [{
            "prescription_id": "previous-push",
            "shot_id": "shot_001",
            "entity": "cam_shot_001",
            "component": "distance",
            "target_value": {
                "position": {"x": 0.0, "y": 2.7, "z": 1.5},
            },
            "applied": True,
            "no_op": False,
            "rejected": False,
            "reason": "",
            "after": None,
        }],
    }]


def test_agent_prompt_exposes_rejected_entity_feedback_and_exact_camera_id(
    tmp_path,
):
    class CaptureTransport:
        model = "director-test"

        def __init__(self):
            self.payload = None

        def chat(self, payload):
            self.payload = payload
            return ChatReply(content="missing tool call")

    transport = CaptureTransport()
    request = CoarseProposalRequest(
        round_no=2,
        observation_id="obs-after-rejection",
        reference=_reference(),
        report=_report(70.0),
        frames=tuple(_frames_for_shot(tmp_path)),
        history=({
            "round_no": 1,
            "disposition": "proposal_rejected",
            "proposal_rejected": True,
            "rejection_reason": (
                "camera entity 'camera' does not belong to shot_001"),
            "prescriptions": [{
                "prescription_id": "bad-camera-entity",
                "shot_id": "shot_001",
                "entity": "camera",
                "component": "position.y",
                "target_value": 3.2,
                "rejected": True,
                "reason": "抬高机位",
            }],
        },),
    )

    with pytest.raises(CoarseProposalError, match="no emit_coarse_proposal"):
        AgentCoarseProposalProvider(transport=transport)(request=request)

    user_content = transport.payload.messages[1].content
    text = next(part["text"] for part in user_content
                if part.get("type") == "text")
    compact = json.loads(text.split("\n", 1)[1])

    assert compact["camera_entities"] == {"shot_001": "cam_shot_001"}
    rejection = compact["previous_rounds"][0]
    assert rejection["proposal_rejected"] is True
    assert "does not belong" in rejection["rejection_reason"]
    assert rejection["prescriptions"][0]["rejected"] is True


def test_agent_tool_schema_only_offers_known_camera_and_character_entities():
    schema = emit_coarse_proposal_tool(_reference())
    entity = schema["function"]["parameters"]["properties"][
        "prescriptions"]["items"]["properties"]["entity"]

    assert entity["enum"] == ["甲", "cam_shot_001"]
    assert "camera" not in entity["enum"]


def test_agent_tool_schema_enforces_component_specific_target_values():
    """The tool contract must agree with the deterministic validator.

    The previous schema offered number/object/vector for every component.
    ``distance`` therefore advertised a scalar even though the applier
    requires an absolute camera position, while a valid x/y/z target matched
    both the vector and generic-object branches of ``oneOf``.  Real node123
    runs exposed both sides of that mismatch.
    """
    schema = emit_coarse_proposal_tool(_reference())["function"]["parameters"]
    validator = jsonschema.Draft202012Validator(schema)

    def proposal(component, scope, target_value):
        return {
            "schema_version": "coarse-proposal/v1",
            "reason": "schema contract probe",
            "prescriptions": [{
                "prescription_id": f"probe-{component}",
                "scope": scope,
                "shot_id": "shot_001",
                "entity": (
                    "甲" if scope == "character" else "cam_shot_001"),
                "component": component,
                "target_value": target_value,
                "reason": "probe",
                "evidence_refs": ["composition:shot_001"],
            }],
        }

    valid_vector = {"x": 0.0, "y": 0.0, "z": 1.0}
    valid_distance = {
        "position": {"x": 0.0, "y": 2.7, "z": 1.5},
        "target": valid_vector,
    }
    valid = [
        proposal("target", "camera", valid_vector),
        proposal("character_position", "character", valid_vector),
        proposal("distance", "camera", valid_distance),
        proposal("strafe", "camera", valid_distance),
        proposal("position.y", "camera", 2.7),
        proposal("position.z", "camera", 1.5),
    ]
    for item in valid:
        validator.validate(item)

    invalid = [
        proposal("distance", "camera", 2.9),
        proposal("strafe", "camera", 0.4),
        proposal("target", "character", valid_vector),
        proposal("position.y", "camera", valid_vector),
        proposal(
            "distance",
            "camera",
            {"x": 0.0, "y": 2.7, "z": 1.5},
        ),
    ]
    for item in invalid:
        assert not validator.is_valid(item), item


def test_agent_tool_schema_exposes_optional_exact_candidate_ids():
    schema = emit_coarse_proposal_tool(_reference())
    prescription = schema["function"]["parameters"]["properties"][
        "prescriptions"]["items"]
    candidate_ids = prescription["properties"]["candidate_ids"]

    assert "candidate_ids" not in prescription["required"]
    assert candidate_ids == {
        "type": "array",
        "minItems": 1,
        "items": {"type": "string", "minLength": 1},
        "description": (
            "逐字引用失败镜 correction_candidates 中的 candidate_id；"
            "没有候选时省略。"),
    }


def test_validate_coarse_proposal_preserves_candidate_references():
    proposal = {
        "schema_version": "coarse-proposal/v1",
        "reason": "repair the reviewed framing",
        "prescriptions": [{
            "prescription_id": "repair-001",
            "scope": "character",
            "shot_id": "shot_001",
            "entity": "甲",
            "component": "character_position",
            "target_value": {"x": 0.5, "y": 0.0, "z": 0.0},
            "reason": "restore readable framing",
            "evidence_refs": ["correction-reframe"],
            "candidate_ids": ["correction-reframe"],
        }],
    }

    validated = validate_coarse_proposal(
        proposal, reference=_reference())

    assert validated["prescriptions"][0]["candidate_ids"] == [
        "correction-reframe"]


def test_validate_coarse_proposal_rejects_bad_candidate_id_shapes():
    proposal = {
        "schema_version": "coarse-proposal/v1",
        "reason": "repair the reviewed framing",
        "prescriptions": [{
            "prescription_id": "repair-001",
            "scope": "character",
            "shot_id": "shot_001",
            "entity": "甲",
            "component": "character_position",
            "target_value": {"x": 0.5, "y": 0.0, "z": 0.0},
            "reason": "restore readable framing",
            "evidence_refs": ["correction-reframe"],
            "candidate_ids": "correction-reframe",
        }],
    }

    with pytest.raises(CoarseProposalError, match="candidate_ids"):
        validate_coarse_proposal(proposal, reference=_reference())


def test_agent_prompt_pairs_each_failed_shot_with_candidate_ids(tmp_path):
    class CaptureTransport:
        model = "director-test"

        def __init__(self):
            self.payload = None

        def chat(self, payload):
            self.payload = payload
            return ChatReply(content="missing tool call")

    report = _report(70.0)
    report["correction_candidates"] = [{
        "candidate_id": "correction-reframe",
        "shot_id": "shot_001",
        "kind": "subject_cut_by_edge",
        "subject": "甲",
        "source": "both",
        "severity": "error",
        "suggested_tool": "reframe",
        "evidence": "edge_clip_ratio=0.2；VLM: 第1帧",
    }]
    transport = CaptureTransport()
    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-candidate-context",
        reference=_reference(),
        report=report,
        frames=_frames_for_shot(tmp_path),
    )

    with pytest.raises(CoarseProposalError, match="no emit_coarse_proposal"):
        AgentCoarseProposalProvider(transport=transport)(request=request)

    user_content = transport.payload.messages[1].content
    text = next(part["text"] for part in user_content
                if part.get("type") == "text")
    compact = json.loads(text.split("\n", 1)[1])

    assert compact["correction_candidates"]["shot_001"][0][
        "candidate_id"] == "correction-reframe"
    assert "逐字引用" in transport.payload.messages[0].content


def test_agent_prompt_exposes_legal_entities_per_failed_shot(tmp_path):
    class CaptureTransport:
        model = "director-test"

        def __init__(self):
            self.payload = None

        def chat(self, payload):
            self.payload = payload
            return ChatReply(content="missing tool call")

    transport = CaptureTransport()
    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-legal-entities",
        reference=_reference(),
        report=_report(70.0),
        frames=tuple(_frames_for_shot(tmp_path)),
    )

    with pytest.raises(CoarseProposalError, match="no emit_coarse_proposal"):
        AgentCoarseProposalProvider(transport=transport)(request=request)

    user_content = transport.payload.messages[1].content
    text = next(part["text"] for part in user_content
                if part.get("type") == "text")
    compact = json.loads(text.split("\n", 1)[1])

    assert compact["legal_entities_by_shot"] == {
        "shot_001": {
            "camera": ["cam_shot_001"],
            "character": ["甲"],
        },
    }


def test_agent_prompt_contains_each_failed_shots_effective_staging(tmp_path):
    reference = _reference()
    reference["shots"].append({
        "shot_id": "shot_002",
        "order": 2,
        "duration_frames": 24,
        "characters": ["甲"],
        "actions": [],
    })
    reference["camera_intents"].append({
        "shot_id": "shot_002",
        "position": [0.0, -3.0, 1.5],
        "target": [0.0, 0.0, 1.0],
        "lens": 35.0,
        "movement": None,
    })
    reference["shot_staging"] = {
        "shot_001": {
            "甲": {
                "position": {"x": 1.5, "y": 0.0, "z": 0.0},
                "provenance": "agent_local_revision",
                "reason": "第一镜右移",
            },
        },
        "shot_002": {
            "甲": {
                "position": {"x": -1.5, "y": 0.0, "z": 0.0},
                "provenance": "agent_local_revision",
                "reason": "第二镜左移",
            },
        },
    }
    report = _report(70.0)
    report["checks"].append({
        "check_id": "composition",
        "shot_id": "shot_002",
        "actual": 65.0,
        "threshold": 80.0,
        "verdict": "fail",
    })
    world_state = {
        "schema_version": "runtime-world/v1",
        "characters": {},
        "cameras": {},
        "render_staging": {
            "shot_001": {
                "characters": {
                    "甲": {
                        "planned_position": {
                            "x": 1.5, "y": 0.0, "z": 0.0,
                        },
                        "actual_origin": [1.5, 0.0, 0.8],
                    },
                },
                "restore_verified": True,
            },
            "shot_002": {
                "characters": {
                    "甲": {
                        "planned_position": {
                            "x": -1.5, "y": 0.0, "z": 0.0,
                        },
                        "actual_origin": [-1.5, 0.0, 0.8],
                    },
                },
                "restore_verified": True,
            },
        },
    }
    frames = []
    for shot_id in ("shot_001", "shot_002"):
        for phase, frame in (("first", 1), ("middle", 12), ("last", 24)):
            path = tmp_path / f"{shot_id}_{phase}.png"
            Image.new("RGB", (8, 6), (20, 40, 60)).save(path)
            frames.append({
                "shot_id": shot_id,
                "phase": phase,
                "frame": frame,
                "path": str(path),
                "file_sha256": "a" * 64,
                "pixel_sha256": "b" * 64,
                "readable": True,
            })

    class CaptureTransport:
        model = "director-test"

        def __init__(self):
            self.payload = None

        def chat(self, payload):
            self.payload = payload
            return ChatReply(content="missing tool call")

    transport = CaptureTransport()
    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-test",
        reference=reference,
        report=report,
        world_state=world_state,
        frames=tuple(frames),
    )

    with pytest.raises(CoarseProposalError, match="no emit_coarse_proposal"):
        AgentCoarseProposalProvider(transport=transport)(request=request)

    user_content = transport.payload.messages[1].content
    text = next(part["text"] for part in user_content
                if part.get("type") == "text")
    compact = json.loads(text.split("\n", 1)[1])

    effective = compact["effective_characters_by_shot"]
    assert effective["shot_001"][0]["position"] == {
        "x": 1.5, "y": 0.0, "z": 0.0,
    }
    assert effective["shot_002"][0]["position"] == {
        "x": -1.5, "y": 0.0, "z": 0.0,
    }
    assert effective["shot_001"][0]["position_provenance"] == (
        "agent_local_revision")
    assert compact["staging_audit"]["shot_001"]["restore_verified"] is True

