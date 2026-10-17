"""v1.7 卡 D3：视口精灵的纯函数（路径解析 / 帧表容错 / 帧数读取）。

Blender 对象与 draw 回调不在此测（--background 下不触发，只测注册表——
见 ``tools/blender_tests/test_assistant_sprite.py``）。本文件只测
``assistant_sprite`` 头部不 import bpy 的纯函数。
"""

from __future__ import annotations

from pathlib import Path

from block_director.layer7_ui.assistant_sprite import (
    clip_frames,
    load_frames_table,
    resolve_assets_dir,
)


def test_resolve_assets_override_wins(tmp_path):
    assert resolve_assets_dir(env=str(tmp_path)) == tmp_path.resolve()


def test_resolve_assets_derives_from_package():
    #: 缺省：从模块文件向上两级到包根，再拼 web/assets/assistant。
    module = Path(__file__).resolve()
    pkg_file = module.parents[1] / "block_director" / "layer7_ui" / "assistant_sprite.py"
    assert resolve_assets_dir(env=None, pkg_file=str(pkg_file)) == (
        module.parents[1] / "web" / "assets" / "assistant"
    ).resolve()


def test_load_frames_table_missing_returns_empty(tmp_path):
    assert load_frames_table(tmp_path) == {}


def test_load_frames_table_bad_json_returns_empty(tmp_path):
    (tmp_path / "frames.json").write_text("{not json", encoding="utf-8")
    assert load_frames_table(tmp_path) == {}


def test_load_frames_table_valid(tmp_path):
    (tmp_path / "frames.json").write_text(
        '{"base_size": 48, "clips": {"think": {"frames": 8, "loop": true}}}',
        encoding="utf-8")
    table = load_frames_table(tmp_path)
    assert table["clips"]["think"]["frames"] == 8


def test_clip_frames_returns_default_on_missing():
    assert clip_frames({}, "nope") == 1
    assert clip_frames({"clips": {"a": {"frames": "bad"}}}, "a") == 1


def test_clip_frames_reads_count():
    table = {"clips": {"a": {"frames": 6}}}
    assert clip_frames(table, "a") == 6
