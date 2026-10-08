"""v1.6 E3（FR-A5）：角色定妆卡的**纯层**测试。

``layer8_delivery/reference_cards.py`` 的模块顶层不 import bpy，但它的包
``layer8_delivery/__init__.py`` 会拉进 bpy——与
``tests/test_tool_bindings_env.py`` 同一招：按文件路径直接加载模块源码，
只测纯层部分（机位设计值、画幅几何、文件名清洗与防碰撞）。
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from block_director.contracts.elements import Element

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = (ROOT / "block_director" / "layer8_delivery"
            / "reference_cards.py")
    spec = importlib.util.spec_from_file_location(
        "bd_reference_cards_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ref = _load_module()


def _element(element_id: str, label: str) -> Element:
    return Element(id=element_id, kind="character", label=label,
                   color_hex="#FF6B6B")


# --------------------------------------------------------------------------- #
# 机位设计值：任务卡 E3 钉死的三个数字，一个字不许动。
# --------------------------------------------------------------------------- #
def test_camera_design_values_are_pinned():
    assert ref.CARD_LENS_MM == 50.0
    assert ref.CARD_DISTANCE_M == 3.0
    assert ref.CARD_HEIGHT_M == 1.0


def test_framing_design_values_are_pinned():
    assert ref.CARD_SENSOR_WIDTH_MM == 36.0
    assert ref.CARD_SENSOR_FIT == "HORIZONTAL"
    assert ref.CARD_RESOLUTION == 1024
    assert ref.CARD_AIM_HEIGHT_M == 1.0


# --------------------------------------------------------------------------- #
# 画幅几何：与 FOLLOWUP_FINDINGS 的 square-frame 分支逐数字一致。
# --------------------------------------------------------------------------- #
def test_vertical_fov_matches_followup_findings():
    # 2·atan(36/(2·50)) = 2·atan(0.36)
    assert ref.CARD_VERTICAL_FOV_RAD == pytest.approx(
        2.0 * math.atan(36.0 / 100.0), rel=1e-12)
    assert math.degrees(ref.CARD_VERTICAL_FOV_RAD) == pytest.approx(
        39.598, abs=1e-3)


def test_frame_height_covers_body_plus_label_with_symmetric_margins():
    # 画高 = 2·3·tan(vfov/2) = 6·0.36 = 2.16 m；覆盖 [-0.08, 2.08]。
    assert ref.CARD_FRAME_HEIGHT_M == pytest.approx(2.16, abs=1e-9)
    assert ref.CARD_FRAME_HEIGHT_M > 2.00  # 脚 0 → 标签锚点 2.00 都装得下


def test_ndc_positions_of_feet_head_and_label_anchor():
    feet = ref.card_ndc_y(0.0)
    head = ref.card_ndc_y(1.70)
    label = ref.card_ndc_y(2.00)
    assert feet == pytest.approx(0.037037, abs=1e-6)
    assert head == pytest.approx(0.824074, abs=1e-6)
    assert label == pytest.approx(0.962963, abs=1e-6)
    # 三个点都在画内，且上下各留 ≥3% 画面高的边距。
    assert 0.03 <= feet <= 0.97
    assert 0.03 <= head <= 0.97
    assert 0.03 <= label <= 0.97


def test_ndc_y_scales_with_aim_height():
    # 对准点抬高 0.5 m ⇒ 同一点在画面里低 0.5/2.16。
    shifted = ref.card_ndc_y(1.0, aim_height=1.5)
    assert shifted == pytest.approx(
        (1.0 - (1.5 - 2.16 / 2.0)) / 2.16, abs=1e-9)


# --------------------------------------------------------------------------- #
# 机位数学：正前方 3 m、高 1.0 m、水平对准。
# --------------------------------------------------------------------------- #
def test_camera_pose_places_camera_3m_in_front_at_1m_height():
    location, look_at = ref.card_camera_pose((2.0, 3.0, 0.0), (0.0, 1.0, 0.0))
    assert location == pytest.approx((2.0, 6.0, 1.0))
    assert look_at == pytest.approx((2.0, 3.0, 1.0))


def test_camera_pose_normalises_facing_and_falls_back_on_zero():
    location, _look_at = ref.card_camera_pose((0.0, 0.0, 0.0), (3.0, 4.0, 0.0))
    assert location == pytest.approx((3.0 * 3.0 / 5.0, 3.0 * 4.0 / 5.0, 1.0))
    fallback, _ = ref.card_camera_pose((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    assert fallback == pytest.approx((0.0, 3.0, 1.0))


def test_camera_pose_keeps_distance_at_3m():
    location, look_at = ref.card_camera_pose((1.0, -2.0, 0.0), (-1.0, 2.0, 0.0))
    distance = math.hypot(location[0] - look_at[0],
                          location[1] - look_at[1])
    assert distance == pytest.approx(3.0, abs=1e-9)
    assert location[2] - look_at[2] == pytest.approx(0.0)  # 无俯仰


# --------------------------------------------------------------------------- #
# 文件名清洗：确定性、保留可读字符、中性化不安全名字。
# --------------------------------------------------------------------------- #
def test_sanitise_keeps_cjk_and_alphanumerics():
    assert ref.sanitise_filename("伊恩") == "伊恩"
    assert ref.sanitise_filename("Maya") == "Maya"
    assert ref.sanitise_filename("Agent 07-B") == "Agent_07-B"


def test_sanitise_replaces_unsafe_characters_and_collapses_runs():
    assert ref.sanitise_filename(r'a<b>c:d"e/f\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"
    assert ref.sanitise_filename("a  b  c") == "a_b_c"
    assert ref.sanitise_filename("  _x_  ") == "x"
    assert ref.sanitise_filename("name..") == "name"


def test_sanitise_neutralises_windows_reserved_names():
    assert ref.sanitise_filename("CON") == "_CON"
    assert ref.sanitise_filename("com3") == "_com3"
    assert ref.sanitise_filename("LPT9") == "_LPT9"
    assert ref.sanitise_filename("console") == "console"  # 非精确保留名不动


def test_sanitise_falls_back_deterministically():
    assert ref.sanitise_filename("") == "character"
    assert ref.sanitise_filename("***") == "character"
    assert ref.sanitise_filename("") == ref.sanitise_filename("")


# --------------------------------------------------------------------------- #
# 卡片文件名分配：label 优先、碰撞安全、与输入顺序无关。
# --------------------------------------------------------------------------- #
def test_assign_names_use_registry_labels():
    names = ref.assign_card_names(
        [_element("char_001", "伊恩"), _element("char_002", "Maya")])
    assert names == {"char_001": "伊恩", "char_002": "Maya"}


def test_assign_names_fall_back_to_id_when_label_empty():
    names = ref.assign_card_names(
        [_element("char_001", ""), _element("char_002", "Maya")])
    assert names == {"char_001": "char_001", "char_002": "Maya"}


def test_assign_names_are_collision_safe_and_order_independent():
    first = [_element("char_001", "同名"), _element("char_002", "同名")]
    second = list(reversed(first))
    a = ref.assign_card_names(first)
    b = ref.assign_card_names(second)
    assert a == b
    # id 小的拿基础名，id 大的追加 id 后缀；两种入列顺序结果一致。
    assert set(a.values()) == {"同名", "同名_char_002"}
    assert a["char_001"] == "同名"
    assert a["char_002"] == "同名_char_002"


def test_assign_names_are_collision_safe_case_insensitively():
    names = ref.assign_card_names(
        [_element("char_001", "Maya"), _element("char_002", "maya")])
    assert len(set(name.lower() for name in names.values())) == 2
    assert names["char_001"] == "Maya"
    assert names["char_002"] == "maya_char_002"


def test_assign_names_are_deterministic_across_calls():
    elements = [_element("char_001", "伊恩"), _element("char_002", "伊恩"),
                _element("char_003", "伊恩")]
    assert ref.assign_card_names(elements) == ref.assign_card_names(elements)
    assert len(set(ref.assign_card_names(elements).values())) == 3
