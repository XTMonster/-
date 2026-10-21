"""缺陷 E（T2）：相机引用按镜头稳定解析（纯层，禁止 import bpy）。

单镜重建会删旧相机建新相机（对象身份变化但镜头键稳定），模型手里上一轮的
``camera_id`` 可能是对象名、镜头键或 ``BD_Cam_<shot>`` 字面量；解析必须
优先对象名、再回查镜头键，重建后旧 ID 不再产生 domain_error。
"""

from __future__ import annotations

import pytest

from block_director.contracts.camera_ref import resolve_camera_ref


class FakeCamera:
    def __init__(self, name: str):
        self.name = name


def test_object_name_resolves_and_returns_shot_key():
    cameras = {"shot_001": FakeCamera("BD_Cam_shot_001"),
               "shot_002": FakeCamera("BD_Cam_shot_002")}
    camera, shot_id, problem = resolve_camera_ref(cameras, "BD_Cam_shot_002")
    assert camera is cameras["shot_002"]
    assert shot_id == "shot_002"
    assert problem == ""


def test_shot_key_direct_resolve():
    cameras = {"shot_001": FakeCamera("BD_Cam_shot_001")}
    camera, shot_id, problem = resolve_camera_ref(cameras, "shot_001")
    assert camera is cameras["shot_001"]
    assert shot_id == "shot_001"
    assert problem == ""


def test_after_rebuild_old_id_resolves_to_new_object():
    #: 重建后旧对象被删，新对象同名（对象身份不同），镜头键指向新对象。
    old = FakeCamera("BD_Cam_shot_001")
    new = FakeCamera("BD_Cam_shot_001")
    cameras = {"shot_001": new}
    camera, shot_id, problem = resolve_camera_ref(cameras, "BD_Cam_shot_001")
    assert camera is new
    assert camera is not old
    assert shot_id == "shot_001"
    assert problem == ""


def test_missing_camera_returns_error_with_roster():
    cameras = {"shot_001": FakeCamera("BD_Cam_shot_001")}
    camera, _shot_id, problem = resolve_camera_ref(cameras, "BD_Cam_shot_999")
    assert camera is None
    assert problem != ""
    assert "BD_Cam_shot_999" in problem
    assert "shot_001" in problem


def test_empty_id_is_no_resolution():
    cameras = {"shot_001": FakeCamera("BD_Cam_shot_001")}
    camera, shot_id, problem = resolve_camera_ref(cameras, "")
    assert camera is None
    assert shot_id == ""
    assert problem == ""
