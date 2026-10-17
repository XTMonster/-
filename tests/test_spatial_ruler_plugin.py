from block_director.contracts.plan import Plan, ShotPlan, Responsibility
from block_director.layer5_orchestrator.spatial_ruler import audit_and_prepare_plan


class Brief:
    speakers = [{"speaker": "米迦尔", "listener": "伊恩"}]
    gaze = [{"from": "米迦尔", "to": "偷盗者"}]
    space = [{"character": "偷盗者", "relative_to": "伊恩"}]


def test_plugin_spatial_ruler_recovers_cast_and_flags_rhythm():
    plan = Plan(scene_heading="码头")
    plan.shots = [
        ShotPlan("shot_001", "建立", "ELS", 120,
                 responsibility=Responsibility(white_model=["米迦尔", "伊恩"])),
        ShotPlan("shot_002", "推进", "MS", 168,
                 responsibility=Responsibility(white_model=["偷盗者"])),
    ]
    _, findings = audit_and_prepare_plan(
        plan, brief=Brief(), declared_total_seconds=8.0)
    assert plan.shots[0].characters == ["米迦尔", "伊恩"]
    assert plan.shots[1].characters == ["偷盗者"]
    assert any(item.rule == "SR002" and item.severity.value == "error"
               for item in findings)
