"""卡 A3：UIEvent DTO（v1.7 TDD §2.1）。"""

from __future__ import annotations

from block_director.contracts.ui_events import UIEvent


def test_roundtrip():
    event = UIEvent(seq=3, ts=12.5, kind="shot_progress", state="BUILDING",
                    shot_id="shot_001",
                    payload={"done": 2, "total": 13})
    assert UIEvent.from_dict(event.to_dict()) == event


def test_payload_defaults_empty():
    first = UIEvent(seq=1, ts=0.0, kind="chat")
    second = UIEvent(seq=2, ts=0.0, kind="chat")
    assert first.payload == {}
    assert second.payload == {}
    first.payload["k"] = "v"
    assert second.payload == {}


def test_from_dict_tolerates_missing():
    event = UIEvent.from_dict({"seq": 1, "ts": 0.0, "kind": "chat"})
    assert event.state == ""
    assert event.shot_id == ""
    assert event.payload == {}
