"""§15.6 深度序列交付约定的纯计算测试。"""

from __future__ import annotations

from block_director.delivery import (
    DEPTH_FRAME_PREFIX,
    DEPTH_RANGE,
    depth_dir_name,
    depth_manifest_entry,
    depth_range_note,
)


def test_normalisation_range_is_fixed_and_documented():
    assert DEPTH_RANGE == (0.1, 50.0)
    note = depth_range_note()
    assert "0.1" in note and "50" in note and "归一化" in note


def test_directory_and_pattern_match_the_spec():
    assert depth_dir_name("shot_001") == "depth_shot_shot_001"
    assert DEPTH_FRAME_PREFIX == "frame_"
    entry = depth_manifest_entry("shot_001", 96)
    assert entry["pattern"] == "frame_%04d.png"
    assert entry["bit_depth"] == 16 and entry["channels"] == "BW"
    assert entry["range_m"] == [0.1, 50.0]


def test_manifest_entry_records_the_frame_count():
    assert depth_manifest_entry("shot_002", 0)["frames"] == 0
    assert depth_manifest_entry("shot_002", 120)["frames"] == 120
