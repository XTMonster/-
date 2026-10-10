"""卡 A1：小助手状态映射契约（v1.7 TDD §3）。"""

from __future__ import annotations

import re

from block_director.contracts.assistant import CLIP_BY_STATE, clip_for_state
from block_director.layer5_orchestrator.states import DriverState


def test_keys_match_driver_states():
    assert set(CLIP_BY_STATE) == {state.value for state in DriverState}


def test_clip_names_are_legal():
    assert all(re.fullmatch(r"[a-z_]+", clip) for clip in CLIP_BY_STATE.values())


def test_unknown_state_falls_back():
    assert clip_for_state("NO_SUCH") == "sit"


def test_empty_and_none_fall_back():
    assert clip_for_state("") == "sit"
    assert clip_for_state(None) == "sit"
