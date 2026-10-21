"""缺陷 D / U1（T8）：单镜 fail 后继续，交付层带失败清单仍产出视频。

- 纯层 ``build_failures_payload``：只把 terminal_shots=="failed" 的镜收进
  ``failures[]``（镜号 / 最高分 / 无新高轮数 / 原因），确定性排序；
- ``render_failures_markdown``：README 失败清单段，含镜号与 80 门槛说明；
- 驱动级闭环：回溯 3 轮无新高 -> shot_001 记 failed -> ``snapshot()`` 的
  ``failures`` 载荷带 shot_001（best 62.0）且不含已过镜 shot_002；
- 交付记分：failed 镜照常渲染最佳版本并计入 ``delivered_shots``，但不计入
  ``passed_shots``（出片不等于通过，D3）。
"""

from __future__ import annotations

from block_director.delivery.failures import (
    FAILURES_SCHEMA,
    build_failures_payload,
    render_failures_markdown,
)


def test_failures_payload_keeps_only_failed_shots_deterministically():
    payload = build_failures_payload(
        terminal_shots={"shot_001": "failed", "shot_002": "passed",
                        "shot_003": "failed"},
        best_scores={"shot_001": {"score": 62.0},
                     "shot_003": {"score": 74.5}},
        no_gain={"shot_001": 3, "shot_003": 4})
    assert payload["schema_version"] == FAILURES_SCHEMA
    failures = payload["failures"]
    assert [f["shot_id"] for f in failures] == ["shot_001", "shot_003"]
    first = failures[0]
    assert first["best_score"] == 62.0
    assert first["no_gain_rounds"] == 3
    assert "无新高" in first["reason"] and "80" in first["reason"]
    #: 已过镜绝不进失败清单
    assert not any(f["shot_id"] == "shot_002" for f in failures)


def test_failures_payload_reason_never_contradicts_best_score():
    """best > 80 时文案不许再写"未达到门槛"（final9 shot_002=80.7 实测）。"""
    payload = build_failures_payload(
        terminal_shots={"shot_001": "failed"},
        best_scores={"shot_001": {"score": 80.7}},
        no_gain={"shot_001": 3})
    reason = payload["failures"][0]["reason"]
    assert "无新高" in reason and "80.7" in reason
    assert "未达到 80 分门槛" not in reason
    #: 低于门槛的失败镜保留原文案（门槛说明仍在，测试既有契约）
    low = build_failures_payload(
        terminal_shots={"shot_001": "failed"},
        best_scores={"shot_001": {"score": 62.0}},
        no_gain={"shot_001": 3})["failures"][0]["reason"]
    assert "未达到严格高于 80 分的门槛" in low and "80" in low


def test_failures_payload_empty_when_nothing_failed():
    payload = build_failures_payload(
        terminal_shots={"shot_001": "passed", "shot_002": "passed"},
        best_scores={}, no_gain={})
    assert payload["failures"] == []


def test_finished_shots_are_pending_review_not_silently_passed():
    payload = build_failures_payload(
        terminal_shots={
            "shot_001": "finished",
            "shot_002": "passed",
            "shot_003": "failed",
        },
        best_scores={
            "shot_001": {"score": 55.8},
            "shot_003": {"score": 62.0},
        },
        no_gain={"shot_003": 3},
    )

    assert [item["shot_id"] for item in payload["failures"]] == ["shot_003"]
    pending = payload["pending_review"]
    assert [item["shot_id"] for item in pending] == ["shot_001"]
    assert pending[0]["status"] == "finished"
    assert pending[0]["best_score"] == 55.8
    assert "审核未通过" in pending[0]["reason"]


def test_failures_markdown_lists_shots_and_threshold():
    payload = build_failures_payload(
        terminal_shots={"shot_001": "failed", "shot_002": "passed"},
        best_scores={"shot_001": {"score": 62.0}},
        no_gain={"shot_001": 3})
    text = render_failures_markdown(payload["failures"])
    assert "shot_001" in text
    assert "62.0" in text
    assert "80" in text
    assert "shot_002" not in text


def test_readme_renders_pending_review_as_quality_record(tmp_path):
    from block_director.delivery.readme import render_readme

    manifest = {
        "project": "pending-review",
        "resolution": [1280, 720],
        "fps": 24,
        "total_frames": 48,
        "generated_at": "2026-10-21T00:00:00+08:00",
        "shots": [{
            "shot_id": "shot_005",
            "duration_seconds": 2.0,
            "rhythm": {"tension": 3},
        }],
    }
    text = render_readme(
        manifest,
        out_dir=tmp_path,
        pending_review=[{
            "shot_id": "shot_005",
            "status": "finished",
            "best_score": 55.8,
            "reason": "模型声明完成，但审核未通过",
        }],
    )

    assert "## 待复核镜头（质量未通过）" in text
    assert "| shot_005 | finished | 55.8 |" in text
    assert "模型声明完成，但审核未通过" in text
    assert "不视为已过镜" in text


def test_driver_snapshot_carries_failures_after_fail_continue():
    """驱动级：fail-continue 后 snapshot 带失败清单（best 分 62.0）。"""
    from test_backtrack_no_stop_on_fail import _run_backtrack

    driver, state = _run_backtrack()
    snapshot = driver.snapshot()
    assert snapshot["terminal_shots"]["shot_001"] == "failed"
    payload = snapshot["failures"]
    assert payload["schema_version"] == FAILURES_SCHEMA
    failures = payload["failures"]
    assert [f["shot_id"] for f in failures] == ["shot_001"]
    assert failures[0]["best_score"] == 62.0
    assert "无新高" in failures[0]["reason"]
    assert not any(f["shot_id"] == "shot_002" for f in failures)


def test_delivery_render_includes_failed_best_effort():
    """U6/U1：fail 镜**照常渲染**最佳版本（白模预演视频一定要生成）；
    已交付镜排除，出片≠通过。"""
    from block_director.delivery.failures import (
        renderable_shot_ids,
    )

    all_ids = ["shot_001", "shot_002", "shot_003"]
    delivered = {"shot_002"}
    failed_ids = {"shot_003"}
    render = renderable_shot_ids(all_ids, delivered=delivered,
                                 failed_ids=failed_ids)
    assert render == ["shot_001", "shot_003"]


def test_delivered_shot_ids_include_every_rendered_mp4():
    """R2-D2：``delivered`` 只回答“盘上有没有片”，不冒充“是否通过”。

    failed 镜也照常产出最佳版本 mp4；若把它排除，断点就会与磁盘账实不符。
    "是否通过"由 ``passed_shot_ids`` 另行派生。
    """
    from block_director.delivery.failures import delivered_shot_ids

    report_shots = [
        {"shot_id": "shot_001", "video": "blockout_shot_001.mp4"},
        {"shot_id": "shot_002", "video": "blockout_shot_002.mp4",
         "failed": True},
        {"shot_id": "shot_003", "video": None, "failed": True},
        {"shot_id": "shot_004"},
    ]
    assert delivered_shot_ids(report_shots) == ["shot_001", "shot_002"]


def test_passed_shot_ids_exclude_failed_best_effort_mp4():
    """``passed`` 是 ``delivered`` 的子集：failed 有片但不算通过。"""
    from block_director.delivery.failures import passed_shot_ids

    report_shots = [
        {"shot_id": "shot_001", "video": "blockout_shot_001.mp4"},
        {"shot_id": "shot_002", "video": "blockout_shot_002.mp4",
         "failed": True},
        {"shot_id": "shot_003", "video": None},
    ]
    assert passed_shot_ids(report_shots) == ["shot_001"]


def test_passed_shot_ids_exclude_finished_best_effort_mp4():
    from block_director.delivery.failures import passed_shot_ids

    report_shots = [
        {"shot_id": "shot_001", "video": "blockout_shot_001.mp4"},
        {"shot_id": "shot_002", "video": "blockout_shot_002.mp4",
         "pending_review": True},
    ]
    assert passed_shot_ids(report_shots) == ["shot_001"]


def test_pending_review_shot_ids_are_reported_from_delivery_shots():
    from block_director.delivery.failures import pending_review_shot_ids

    report_shots = [
        {"shot_id": "shot_001", "video": "blockout_shot_001.mp4"},
        {"shot_id": "shot_002", "video": None, "pending_review": True},
        {"shot_id": "shot_003", "video": "blockout_shot_003.mp4",
         "pending_review": True},
    ]
    assert pending_review_shot_ids(report_shots) == ["shot_002", "shot_003"]


def test_manifest_marks_failed_and_pending_review_shots():
    """shots.json 必须逐镜携带真实审核身份，不能只把问题藏在旁路文件。"""
    from block_director.contracts.plan import Plan, ShotPlan
    from block_director.delivery.manifest import build_manifest

    plan = Plan(shots=[
        ShotPlan(shot_id="shot_001", intent="失败镜", shot_type="MS",
                 duration_frames=24),
        ShotPlan(shot_id="shot_002", intent="待复核镜", shot_type="MCU",
                 duration_frames=24),
        ShotPlan(shot_id="shot_003", intent="通过镜", shot_type="CU",
                 duration_frames=24),
    ])
    failures = build_failures_payload(
        terminal_shots={
            "shot_001": "failed",
            "shot_002": "finished",
            "shot_003": "passed",
        },
        best_scores={
            "shot_001": {"score": 62.0},
            "shot_002": {"score": 55.8},
        },
        no_gain={"shot_001": 3},
    )

    shots = build_manifest(plan, failures=failures)["shots"]

    assert shots[0]["failed"] is True
    assert "pending_review" not in shots[0]
    assert shots[1]["pending_review"] is True
    assert "failed" not in shots[1]
    assert "failed" not in shots[2] and "pending_review" not in shots[2]


def test_prompt_sheet_marks_failed_best_effort_and_pending_review():
    """Prompt 表必须把尽力版本与待复核镜标清，不能诱导下游当成已过镜。"""
    from block_director.contracts.plan import Plan, ShotPlan
    from block_director.delivery.prompts import render_prompt_sheet

    plan = Plan(shots=[
        ShotPlan(shot_id="shot_001", intent="失败镜", shot_type="MS",
                 duration_frames=24),
        ShotPlan(shot_id="shot_002", intent="待复核镜", shot_type="MCU",
                 duration_frames=24),
    ])
    failures = build_failures_payload(
        terminal_shots={"shot_001": "failed", "shot_002": "finished"},
        best_scores={
            "shot_001": {"score": 62.0},
            "shot_002": {"score": 55.8},
        },
        no_gain={"shot_001": 3},
    )

    sheet = render_prompt_sheet(
        plan,
        failures=failures["failures"],
        pending_review=failures["pending_review"],
    )

    assert "**审核状态**：未通过（尽力版本）" in sheet
    assert "**审核状态**：待复核（finished）" in sheet
    assert "## 待复核镜头（质量未通过）" in sheet
    assert "shot_002 | finished | 55.8" in sheet
    assert "无参考视频" not in sheet
