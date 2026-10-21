"""Driver spatial snapshots must use the same cast headings as the scene."""

from __future__ import annotations

from block_director.contracts.cast import SceneSpec
from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer6_audit.audit_logger import AuditLogger


def test_driver_spatial_design_uses_scene_spec_cast_facings():
    plan = Plan(
        scene_heading="market",
        shots=[
            ShotPlan(
                shot_id="shot_001",
                intent="两人对峙",
                shot_type="MS",
                duration_frames=48,
                order=1,
                characters=["米迦尔", "偷盗者"],
                camera={"side": "front", "lens": 35},
            )
        ],
    )
    driver = PrevisDriver(transport=None, audit=AuditLogger())
    driver.plan = plan

    driver._build_spatial_design()
    design = driver.snapshot()["spatial_design"]

    assert design is not None
    snapshot_facings = {
        str(character["name"]): list(character["facing"])
        for character in design["characters"]
    }
    scene_facings = {
        str(member.name): list(member.initial_facing)
        for member in SceneSpec.from_plan(plan).cast
    }
    assert snapshot_facings == scene_facings
