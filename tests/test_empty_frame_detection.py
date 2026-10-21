"""R2 ticket 08（S4）：空画/空帧检测进交付。

根因：渲染出的帧可能是全黑/全白/空墙（mask 全帧同字节），此前没有像素级
检测就进交付包。这里钉住：纯层判定（无 bpy）识别"全帧同字节"，并以
E_EMPTY_FRAME 预警进 BlockoutReport.findings；空镜豁免语义与既有
E_BLOCKOUT_EMPTY_WALL 一致（不扩大）。
"""

from __future__ import annotations

from block_director.cinema.blockout_report import (
    E_EMPTY_FRAME,
    build_blockout_report,
    empty_frame_finding,
    is_uniform_frame,
)


def test_is_uniform_frame_black():
    assert is_uniform_frame(bytes(8))            # 全 0
    assert is_uniform_frame(b"\xff" * 8)         # 全 255
    assert is_uniform_frame([0, 0, 0, 0])        # 全灰 RGBA 展平


def test_is_uniform_frame_non_uniform_false():
    assert not is_uniform_frame(b"\x00\x00\x01\x00")
    assert not is_uniform_frame([0, 255, 0, 0])


def test_is_uniform_frame_empty_data_is_not_uniform():
    # 缺文件/空数据不误判为空帧（渲染失败与画面内容问题是两件事）。
    assert not is_uniform_frame(b"")
    assert not is_uniform_frame([])


def test_empty_frame_finding_emits_warning():
    finding = empty_frame_finding(
        "shot_001", {"frame": 12, "pixels": b"\x00" * 16})
    assert finding is not None
    assert finding["check_id"] == E_EMPTY_FRAME
    assert finding["severity"] == "warning"
    assert finding["shot_id"] == "shot_001"


def test_empty_frame_finding_none_for_normal_frame():
    assert empty_frame_finding(
        "shot_001", {"frame": 12, "pixels": b"\x00\x00\x01\x02"}) is None


def test_build_report_contains_empty_frame_finding():
    report = build_blockout_report(
        manifest={"cameras": [], "shot_table": []},
        per_shot=[{
            "shot_id": "shot_001",
            "empty": False,
            "frames": [{"frame": 1, "png": "a.png",
                        "pixels": b"\x00" * 16}],
        }],
    )
    ids = [f["check_id"] for f in report["findings"]]
    assert E_EMPTY_FRAME in ids


def test_build_report_empty_shot_waived():
    # 空镜豁免：无被摄主体的镜不适用画面判据，也不报空帧。
    report = build_blockout_report(
        manifest={"cameras": [], "shot_table": []},
        per_shot=[{
            "shot_id": "shot_002",
            "empty": True,
            "frames": [{"frame": 1, "png": "b.png",
                        "pixels": b"\x00" * 16}],
        }],
    )
    assert not [f for f in report["findings"]
                if f["check_id"] == E_EMPTY_FRAME]
