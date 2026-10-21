"""R2 ticket 08：mask 全帧同字节进入交付自检。"""
from pathlib import Path

from block_director.cinema.blockout_report import E_EMPTY_FRAME
from block_director.delivery.mask_check import empty_mask_warning


def _write_frames(root: Path, payloads):
    paths = []
    for index, payload in enumerate(payloads, 1):
        path = root / f"frame_{index:04d}.png"
        path.write_bytes(payload)
        paths.append(path)
    return paths


def test_identical_mask_frames_emit_empty_frame_warning(tmp_path):
    files = _write_frames(tmp_path, [b"png-bytes"] * 3)
    warning = empty_mask_warning("shot_001", files)
    assert warning is not None
    assert warning.startswith(E_EMPTY_FRAME)
    assert "shot_001" in warning


def test_changing_mask_frames_do_not_emit_warning(tmp_path):
    files = _write_frames(tmp_path, [b"a", b"b", b"a"])
    assert empty_mask_warning("shot_001", files) is None


def test_empty_or_single_frame_is_not_sequence_warning(tmp_path):
    assert empty_mask_warning("shot_001", []) is None
    files = _write_frames(tmp_path, [b"same"])
    assert empty_mask_warning("shot_001", files) is None
