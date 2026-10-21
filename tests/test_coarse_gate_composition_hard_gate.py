"""粗排 gate 的构图硬门（R2：门槛不下放，低分必须 blocked/回溯）。

2026-10-21 DeepSeek 真跑实锤：4 镜 composition 20/20/77/77（阈值 80）全
fail，但 ``coarse_gate`` 只拦 error finding，软指标放行 -> approved/frozen，
细排 4 镜全未过 80。本测试钉死：任何非空镜 composition 不严格 >80，
粗排 gate 必须 blocked（进入回溯，而不是放行进细排）。
"""

from __future__ import annotations

from block_director.cinema.pipeline_gates import coarse_gate


def _report(compositions, *, empty_shots=()):
    checks = []
    for shot_id, score in compositions.items():
        checks.append({
            "check_id": "composition", "shot_id": shot_id,
            "actual": score, "threshold": 80.0,
            "verdict": ("pass" if isinstance(score, (int, float))
                        and score > 80.0 else "fail"),
        })
    for shot_id in empty_shots:
        checks.append({
            "check_id": "empty_shot", "shot_id": shot_id,
            "actual": 0, "threshold": 0, "verdict": "pass",
        })
    return {"verdict": "fail", "checks": checks, "findings": []}


def test_coarse_gate_all_composition_pass():
    report = _report({
        "shot_001": 81.0, "shot_002": 90.0, "shot_003": 84.5,
    })
    decision = coarse_gate(report)
    assert decision["passed"] is True
    assert decision["reasons"] == []


def test_coarse_gate_blocks_when_any_nonempty_shot_fails_composition():
    """2026-10-21 真跑形状：77.7 / 20 / 77.4 / 20 -> 必须 blocked。"""
    report = _report({
        "shot_001": 77.7, "shot_002": 20.0,
        "shot_003": 77.4, "shot_004": 20.0,
    })
    decision = coarse_gate(report)
    assert decision["passed"] is False
    assert any("构图" in reason for reason in decision["reasons"])


def test_coarse_gate_exact_80_is_fail_not_pass():
    """用户 2026-10-18 裁决：构图分必须严格高于 80，等于不算过。"""
    report = _report({"shot_001": 80.0})
    decision = coarse_gate(report)
    assert decision["passed"] is False


def test_coarse_gate_empty_shots_are_exempt():
    """空镜（无被摄主体）不适用构图判据，不构成 fail。"""
    report = _report({}, empty_shots=("shot_001", "shot_002"))
    decision = coarse_gate(report)
    assert decision["passed"] is True


def test_coarse_gate_error_finding_still_blocks():
    """既有 error 硬门不回退：即使构图全过，error finding 仍 blocked。"""
    report = _report({"shot_001": 85.0})
    report["findings"] = [{
        "check_id": "E_BLOCKOUT_EMPTY_WALL", "shot_id": "shot_001",
        "severity": "error", "message": "主体丢失",
    }]
    decision = coarse_gate(report)
    assert decision["passed"] is False
    assert any("error" in reason for reason in decision["reasons"])


def test_coarse_gate_unresolved_composition_is_fail():
    """没有数值证据（unresolved）不得放行：宁可 blocked 也不猜。"""
    report = _report({"shot_001": None})
    decision = coarse_gate(report)
    assert decision["passed"] is False
