"""v1.7 卡 I3（TDD §12.x，R-痛点 M2）：白模参考包（reference_pack）装配测试。

纯 pytest，不 import bpy。契约真源 = ``v1.7/spec_I3_reference_pack_exec_v2.md``
与 ``.scratch/I3_dispatch_A_pure.md``。本文件只测纯层
（``block_director/layer8_delivery/package.py`` + 三份模板）；bpy 侧接线
（``rule_checker.continuity_snapshot``、``export_director`` 三处接线、
Blender 探针断言）由 ``tools/blender_tests/test_phase6_delivery.py`` 覆盖。

为什么这些断言：I3 的交付物是"给目标视频模型的白模参考包"，五件套的文件名、
表头、逐字句子都必须可对拍——AI 生成的视频以它为参考，任何错位都会直接
落进成片。所有"逐字"断言都抄自 SPEC v2 §3.2/§3.4/§3.6。
"""

from __future__ import annotations

import json
import os
import re
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from block_director.contracts.plan import Plan, Responsibility
from block_director.contracts.target_models import load_table
from block_director.contracts.config import DeliveryConfig

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "specs" / "prompt_templates"
TEMPLATE_KEYS = ("seedance_2.5", "kling", "hailuo_h3")


def _load_package():
    """Load the pure package module without importing layer8_delivery.__init__ (bpy)."""
    package_name = "block_director.layer8_delivery"
    package = types.ModuleType(package_name)
    package.__path__ = [str(ROOT / "block_director" / "layer8_delivery")]
    sys.modules[package_name] = package
    name = f"{package_name}.package"
    path = ROOT / "block_director" / "layer8_delivery" / "package.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


_package = _load_package()
_render_template = _package._render_template
_slice_sentence = _package._slice_sentence
_target_key = _package._target_key
_authority_sentence = _package._authority_sentence
build_reference_pack = _package.build_reference_pack

#: SPEC v2 §3.6 模板逐字（三份必须字节相同）。
EXPECTED_TEMPLATE = """# $target_label 白模参考包 · 共 $shot_count 镜 / $rendered_count 段白模视频
参考视频里只取四样：运镜的起点方位、运动路径与终点方位，镜头切换点，节奏与时长，人物与道具的摆放位置。
画面中的几何体全部是占位符；占位符颜色仅用于区分角色身份（同色即同人），不代表最终外观、材质与色调。
$authority_sentence
$slice_sentence
"""

#: SPEC v2 §3.6 三 authority 变体逐字。
AUTHORITY_CARD_AND_STYLE = (
    "角色外观、表情与动作细节，以随包角色定妆卡与逐镜镜头卡"
    "（shot_cards.md）为准；场景风格与色调以风格参考图为准。")
AUTHORITY_CARD_NO_STYLE = (
    "角色外观、表情与动作细节，以随包角色定妆卡与逐镜镜头卡"
    "（shot_cards.md）为准；场景风格与色调以镜头卡文字描述为准。")
AUTHORITY_NO_CARD = (
    "角色外观、表情、动作细节与场景风格，一律以逐镜镜头卡"
    "（shot_cards.md）的文字描述为准。")

#: 模板静态句② 与 M2 中性句逐字。
STATIC_COLOUR_SENTENCE = (
    "画面中的几何体全部是占位符；占位符颜色仅用于区分角色身份"
    "（同色即同人），不代表最终外观、材质与色调。")
NEUTRAL_COLOUR_SENTENCE = (
    "画面中的几何体全部是占位符；占位符颜色不代表任何含义，"
    "不代表最终外观、材质与色调。")

#: M2 warning 逐字。
M2_WARNING = (
    "reference_pack: 检测到同色角色（同色即同人）声明不成立，"
    "模板已改中性句（见 README 角色名册）。")

#: slice 句三模型逐字（count 由 suggest_slices + 1 算出）。
SLICE_SENTENCES = {
    "seedance_2.5": (
        "时间线超出单段上限，已建议切为 {count} 段（切点全在镜头切换处，"
        "见 README）；逐段喂入并保持段序。"),
    "kling": (
        "时间线超出单段上限，已建议按 5/10 秒档位组织为 {count} 段"
        "（切点全在镜头切换处，见 README）；逐段喂入并保持段序。"),
    "hailuo_h3": (
        "时间线超出单段上限，已建议按 4–15 秒段组织为 {count} 段，"
        "注意参考文件预算（图 9 / 视频 3 / 音频 3）（切点全在镜头切换处，"
        "见 README）；逐段喂入并保持段序。"),
}

#: SPEC v2 §3.2 README 名册表头逐字。
README_HEADER = "| 角色名 | 占位色 | 身高 | 定妆卡文件 | 出场镜号 |"
#: SPEC v2 §3.3 shot_cards 表头逐字。
SHOT_CARDS_HEADER = "| 镜号 | 景别 | 时长s | 运镜文字 | 出场角色 | 台词数 | 连续性指针 |"


def _elements_payload() -> dict:
    """两角色 + 一环境件（元素登记表按 id 排序）。"""
    return {
        "elements": [
            {"id": "char_001", "kind": "character", "label": "米迦尔",
             "color_hex": "#FF0000"},
            {"id": "char_002", "kind": "character", "label": "以赛亚",
             "color_hex": "#00FF00"},
            {"id": "env_001", "kind": "environment", "label": "码头",
             "color_hex": ""},
        ]
    }


def _plan(*, short: bool = True, skip: bool = True) -> Plan:
    """两镜计划：shot_001 无分工声明；shot_002 可选 skip_white_model=True。

    short=True 时长 3s/1.5s（不触发切片）；short=False 每镜 20s（40s 总长，
    三模型段上限全超，slice 句非空）。
    """
    d1 = 72 if short else 480
    d2 = 36 if short else 480
    payload = {
        "scene_heading": "INT. 码头 - 日",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "建立",
             "shot_type": "MCU", "duration_frames": d1,
             "characters": ["char_001"],
             "dialogue_ids": ["d1", "d2"]},
            {"shot_id": "shot_002", "order": 2, "intent": "反应",
             "shot_type": "LS", "duration_frames": d2,
             "characters": ["char_001", "char_002"]},
        ],
    }
    plan = Plan.from_dict(payload)
    if skip:
        plan.shots[1].responsibility = Responsibility(
            white_model=["位置"], prompt=["动作"], ref_image=["外观"],
            skip_white_model=True)
    return plan


def _manifest(*, with_narration: bool = True) -> dict:
    """手工最小 manifest（字段名按 SPEC v2 §3.3/§10）。"""
    shots = [
        {"shot_id": "shot_001", "order": 1, "intent": "建立",
         "shot_type": "MCU", "declared": {"shot_type": "MCU"},
         "start_frame": 1, "end_frame": 72, "duration_frames": 72,
         "duration_seconds": 3.0, "characters": ["char_001"],
         "dialogue_ids": ["d1", "d2"], "continuity_in": "S01",
         "camera": {"name": "cam_001", "position": [0.0, 0.0, 0.0],
                    "lens": 50.0}, "axis": {}, "paths": {},
         "elements_in_frame": ["char_001", "env_001"]},
        {"shot_id": "shot_002", "order": 2, "intent": "反应",
         "shot_type": "LS", "declared": {"shot_type": ""},
         "start_frame": 73, "end_frame": 108, "duration_frames": 36,
         "duration_seconds": 1.5, "characters": ["char_001", "char_002"],
         "dialogue_ids": [], "continuity_in": "",
         "camera": {"name": "cam_002", "position": [0.0, 0.0, 0.0],
                    "lens": 35.0}, "axis": {}, "paths": {},
         "elements_in_frame": ["char_001", "char_002"]},
    ]
    if with_narration:
        shots[0]["camera_narration"] = "固定机位"
    return {"shots": shots}


def _config(target: str = "seedance_2.5", *, reference_cards: bool = True
            ) -> DeliveryConfig:
    return DeliveryConfig(target_model=target,
                          reference_cards=reference_cards)


def _write_elements(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "elements.json"
    path.write_text(json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _build(tmp_path: Path, *, short: bool = True, skip: bool = True,
           config: DeliveryConfig | None = None,
           manifest: dict | None = None,
           continuity: dict | None = None,
           elements: dict | list | None = "auto",
           slice_sentence: str | None = None):
    """测试便捷入口：写 elements.json（默认）并调用公开 API。"""
    if elements == "auto":
        _write_elements(tmp_path, _elements_payload())
    passed_elements = None if elements == "auto" else elements
    return build_reference_pack(
        tmp_path,
        _plan(short=short, skip=skip),
        config or _config(),
        manifest if manifest is not None else _manifest(),
        continuity=continuity,
        elements=passed_elements,
        slice_sentence=slice_sentence,
    )


def _readme(pack) -> str:
    """README 内容读盘取得（SPEC §3.1 的 ReferencePack 无 readme 字段）。"""
    return (pack.out_dir / "README.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. 模板文件
# --------------------------------------------------------------------------- #

def test_templates_exist_share_five_placeholders_and_are_byte_identical():
    texts = {}
    for key in TEMPLATE_KEYS:
        path = TEMPLATES / f"{key}.txt"
        assert path.is_file(), f"模板缺失：{path}"
        texts[key] = path.read_text(encoding="utf-8")
    assert len({text for text in texts.values()}) == 1, "三份模板必须逐字相同"
    placeholders = re.findall(r"\$[A-Za-z_]+", texts["seedance_2.5"])
    assert set(placeholders) == {
        "$target_label", "$shot_count", "$rendered_count",
        "$authority_sentence", "$slice_sentence"}
    assert texts["seedance_2.5"] == EXPECTED_TEMPLATE


# --------------------------------------------------------------------------- #
# 2. 渲染 helper（严格替换 / 空槽删行 / 连续空行压一行）
# --------------------------------------------------------------------------- #

def test_render_template_substitute_is_strict():
    with pytest.raises(KeyError):
        _render_template("A $missing B", {"other": "x"})


def test_render_template_drops_empty_slots_and_collapses_blank_lines():
    out = _render_template("A\n\n\n$slot\nB", {"slot": ""})
    assert out == "A\nB\n"
    assert "\n\n" not in out


# --------------------------------------------------------------------------- #
# 3. authority 三变体
# --------------------------------------------------------------------------- #

def test_authority_card_and_style_when_cards_and_style_image(tmp_path: Path):
    #: 导出链路现无风格图资产（has_style_image 恒 False），变体 1 只在 helper
    #: 层可及——直接对 helper 断言（SPEC v2 §3.6 逐字）；build 路径恒走变体 2。
    assert _authority_sentence(True, True) == AUTHORITY_CARD_AND_STYLE
    pack = _build(tmp_path, config=_config(reference_cards=True),
                  slice_sentence="")
    assert AUTHORITY_CARD_NO_STYLE in pack.prompt


def test_authority_card_no_style_image_when_no_style_asset(tmp_path):
    #: 当前导出无风格图资产：has_style_image 恒 False → 变体 2。
    pack = _build(tmp_path, config=_config(reference_cards=True),
                  slice_sentence="")
    assert AUTHORITY_CARD_NO_STYLE in pack.prompt


def test_authority_no_card_when_reference_cards_disabled(tmp_path):
    pack = _build(tmp_path, config=_config(reference_cards=False),
                  slice_sentence="")
    assert AUTHORITY_NO_CARD in pack.prompt
    assert "以随包角色定妆卡" not in pack.prompt


# --------------------------------------------------------------------------- #
# 4. 未知 target 回落 seedance_2.5
# --------------------------------------------------------------------------- #

def test_unknown_target_falls_back_to_seedance(tmp_path):
    pack = _build(tmp_path, config=_config("unknown_model"),
                  slice_sentence="")
    assert (pack.out_dir / "prompt_unknown_model.txt").exists() is False
    assert (pack.out_dir / "prompt_seedance_2.5.txt").exists() is True
    assert "Seedance 2.5" in pack.prompt


def test_target_key_falls_back_without_issue():
    assert _target_key(_config("not_a_model")) == "seedance_2.5"
    assert _target_key(_config("kling")) == "kling"


# --------------------------------------------------------------------------- #
# 5. M2 同色 → 中性句 + warning
# --------------------------------------------------------------------------- #

def test_m2_same_colour_swaps_to_neutral_sentence_and_warns(tmp_path):
    payload = dict(_elements_payload())
    payload["elements"][1]["color_hex"] = "#FF0000"  # char_002 与 char_001 同色
    _write_elements(tmp_path, payload)
    pack = build_reference_pack(
        tmp_path, _plan(), _config(),
        _manifest(), slice_sentence="")
    assert NEUTRAL_COLOUR_SENTENCE in pack.prompt
    assert STATIC_COLOUR_SENTENCE not in pack.prompt
    assert M2_WARNING in pack.warnings


def test_m2_no_warning_when_colours_distinct(tmp_path):
    pack = _build(tmp_path, slice_sentence="")
    assert STATIC_COLOUR_SENTENCE in pack.prompt
    assert not [w for w in pack.warnings if w.startswith("reference_pack")]


# --------------------------------------------------------------------------- #
# 6. slice 句三模型逐字（count 正确）
# --------------------------------------------------------------------------- #

def test_slice_sentences_are_verbatim_for_all_three_models():
    long_plan = _plan(short=False, skip=True)   # 40s 总长，三模型段上限全超
    table = load_table()
    expected_counts = {"seedance_2.5": 2, "kling": 3, "hailuo_h3": 3}
    for key in TEMPLATE_KEYS:
        sentence = _slice_sentence(key, long_plan, table[key])
        count = expected_counts[key]
        assert sentence == SLICE_SENTENCES[key].format(count=count)


def test_slice_sentence_empty_when_within_cap():
    table = load_table()
    assert _slice_sentence("seedance_2.5", _plan(short=True),
                           table["seedance_2.5"]) == ""


def test_custom_slice_sentence_passes_through(tmp_path):
    pack = _build(tmp_path, slice_sentence="自定义切片句。")
    assert "自定义切片句。" in pack.prompt


# --------------------------------------------------------------------------- #
# 7. 句数 ≤ 5（去掉 # 头行与含括号行后按 。 计数）
# --------------------------------------------------------------------------- #

def test_prompt_sentence_count_is_within_five(tmp_path):
    pack = _build(tmp_path, slice_sentence="")
    kept = [line for line in pack.prompt.splitlines()
            if line.strip() and not line.strip().startswith("#")
            and "（" not in line and "）" not in line]
    count = sum(line.count("。") for line in kept)
    assert count <= 5, f"句数 {count} 超限：\n{pack.prompt}"


def test_no_residual_placeholder_in_rendered_prompt(tmp_path):
    pack = _build(tmp_path, slice_sentence="")
    assert "$" not in pack.prompt


# --------------------------------------------------------------------------- #
# 8. rendered_count 公式
# --------------------------------------------------------------------------- #

def test_rendered_count_counts_only_declared_skip(tmp_path):
    pack = _build(tmp_path)
    assert pack.shot_count == 2
    assert pack.rendered_count == 1


def test_rendered_count_all_rendered_when_no_skip_declared(tmp_path):
    pack = _build(tmp_path, skip=False)
    assert pack.rendered_count == 2


def test_rendered_count_none_responsibility_is_not_a_skip(tmp_path):
    #: SPEC 公式逐字是 ``sum(s.responsibility and ...)``——None 会 TypeError；
    #: 派单钉死必须用显式 None 判断。这里同时覆盖 None 与 skip 混合。
    pack = _build(tmp_path)
    assert pack.rendered_count == 1


# --------------------------------------------------------------------------- #
# 9. responsibility 行逐字
# --------------------------------------------------------------------------- #

def test_responsibility_lines_are_verbatim(tmp_path):
    pack = _build(tmp_path)
    assert "- shot_001: 未声明" in pack.responsibility
    assert ("- shot_002: white_model=位置; prompt=动作; ref_image=外观; "
            "skip_white_model=true") in pack.responsibility
    assert ("（其中 1 镜声明直出提示词＋参考图，无白模视频，"
            "见 responsibility.md）") in pack.responsibility


def test_responsibility_no_skip_line_when_all_rendered(tmp_path):
    pack = _build(tmp_path, skip=False)
    assert "其中" not in pack.responsibility


# --------------------------------------------------------------------------- #
# 10. README 名册
# --------------------------------------------------------------------------- #

def test_readme_roster_header_height_card_path_and_shots(tmp_path):
    pack = _build(tmp_path)
    readme = _readme(pack)
    assert README_HEADER in readme
    assert ("| 米迦尔 | #FF0000 | 1.70 | reference/characters/米迦尔.png | "
            "shot_001、shot_002 |") in readme
    assert ("| 以赛亚 | #00FF00 | 1.70 | reference/characters/以赛亚.png | "
            "shot_002 |") in readme


def test_readme_card_path_written_unavailable_when_cards_disabled(tmp_path):
    pack = _build(tmp_path, config=_config(reference_cards=False))
    readme = _readme(pack)
    assert "（未生成）" in readme
    assert "reference/characters/米迦尔.png" not in readme


# --------------------------------------------------------------------------- #
# 11. shot_cards 表头与字段对应
# --------------------------------------------------------------------------- #

def test_shot_cards_header_and_row_fields(tmp_path):
    pack = _build(tmp_path)
    assert SHOT_CARDS_HEADER in pack.shot_cards
    assert "| shot_001 | MCU | 3.0 | 固定机位 | char_001 | 2 | S01 |" \
        in pack.shot_cards
    assert "| shot_002 | LS | 1.5 | - | char_001、char_002 | 0 | - |" \
        in pack.shot_cards


# --------------------------------------------------------------------------- #
# 12. continuity.json 写盘格式
# --------------------------------------------------------------------------- #

def test_continuity_json_format_and_key_order(tmp_path):
    continuity = {"shot_001": {"left": ["char_001"], "right": [],
                                "facing": {}, "note": ""},
                  "shot_002": {"left": [], "right": ["char_002"],
                               "facing": {}, "note": ""}}
    pack = _build(tmp_path, continuity=continuity)
    path = pack.out_dir / "continuity.json"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert '"shot_001"' in text and '"shot_002"' in text
    assert text.index('"shot_001"') < text.index('"shot_002"')
    data = json.loads(text)
    assert data["shot_001"]["left"] == ["char_001"]
    assert data["shot_002"]["right"] == ["char_002"]


def test_continuity_json_written_even_when_empty(tmp_path):
    pack = _build(tmp_path, continuity={})
    data = json.loads((pack.out_dir / "continuity.json").read_text(
        encoding="utf-8"))
    assert data == {}


# --------------------------------------------------------------------------- #
# 13. files = 5 个绝对路径
# --------------------------------------------------------------------------- #

def test_files_are_five_absolute_existing_paths(tmp_path):
    pack = _build(tmp_path)
    assert len(pack.files) == 5
    assert len(set(pack.files)) == 5
    for path in pack.files:
        assert os.path.isabs(path), path
        assert Path(path).is_file(), f"文件不存在：{path}"
    assert str(pack.out_dir / "README.md") in pack.files
    assert str(pack.out_dir / "prompt_seedance_2.5.txt") in pack.files
    assert str(pack.out_dir / "shot_cards.md") in pack.files
    assert str(pack.out_dir / "continuity.json") in pack.files
    assert str(pack.out_dir / "responsibility.md") in pack.files


def test_files_use_target_specific_prompt_name(tmp_path):
    pack = _build(tmp_path, config=_config("kling"))
    assert str(pack.out_dir / "prompt_kling.txt") in pack.files


# --------------------------------------------------------------------------- #
# 14. elements.json 缺失 → ValueError 逐字
# --------------------------------------------------------------------------- #

def test_missing_elements_json_raises_verbatim_valueerror(tmp_path):
    with pytest.raises(ValueError,
                       match="reference_pack: 缺少元素登记表（elements.json），"
                             "拒绝猜测"):
        build_reference_pack(tmp_path, _plan(), _config(), _manifest(),
                             slice_sentence="")


def test_elements_parameter_accepts_registry_payload_and_list(tmp_path):
    payload = _elements_payload()
    pack = build_reference_pack(
        tmp_path, _plan(), _config(), _manifest(),
        elements=payload, slice_sentence="")
    assert "米迦尔" in _readme(pack)
    pack2 = build_reference_pack(
        tmp_path, _plan(), _config(), _manifest(),
        elements=payload["elements"], slice_sentence="")
    assert "以赛亚" in _readme(pack2)
