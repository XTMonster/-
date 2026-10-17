from block_director.layer5_orchestrator.shot_versioning import ShotVersion, ShotVersionHistory


def _v(n=0, reason="initial", plan=None):
    return ShotVersion("shot_001", n, plan or {"lens": 35}, {"camera": 1},
                       {"passed": True}, {"disposition": "pass"},
                       "2026-10-12T00:00:00Z", reason)


def test_append_get_latest_restore_and_immutable_snapshot():
    h = ShotVersionHistory("shot_001")
    h.append(_v())
    source = {"lens": 50}
    h.append(_v(1, "repair", source))
    source["lens"] = 99
    assert h.latest().version == 1
    assert h.restore(1) == {"lens": 50}
    assert h.get(0).plan == {"lens": 35}


def test_round_trip_and_reason_validation():
    h = ShotVersionHistory("shot_001")
    h.append(_v())
    restored = ShotVersionHistory.from_dict(h.to_dict())
    assert restored.to_dict() == h.to_dict()
    try:
        _v(reason="unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown reason must fail")


def test_versions_are_contiguous_and_shot_scoped():
    h = ShotVersionHistory("shot_001")
    try:
        h.append(_v(1))
    except ValueError:
        pass
    else:
        raise AssertionError("non-contiguous version must fail")
    try:
        h.append(ShotVersion("shot_002", 0, {}, {}, {}, {}, "", "initial"))
    except ValueError:
        pass
    else:
        raise AssertionError("cross-shot version must fail")
