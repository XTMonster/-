"""落盘那一刻的 SDL 校验**必须带回来**，不能算完就丢。

现场（2026-10-03 的 64 镜真跑）：`project.bdproj` 里带着 26 条 `S6`
（镜头装不下对白），而 `save_run_project` 调了 `validate_sdl(sdl)` 之后
**把返回值丢了**——运行照报 `DONE`、文件照写，直到 `load_project` /
`rebuild_project` / 面板加载时才发现这份工程过不了自己的校验。

本用例钉三件事：
1. 校验**照跑**（不是把校验关掉），错在哪一镜、错在哪条规则都带回来；
2. **落盘前**与**加载后**量的是同一件事（同一个报告形状、同一组规则）；
3. 干净的工程如实报 `ok`，不制造假警报。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer5_orchestrator.headless_runner import (  # noqa: E402
    save_run_project,
)
from block_director.layer9_persistence import (  # noqa: E402
    load_project,
    validation_report,
)


def _summary(*, dialogue_end: int) -> dict:
    """一份最小运行摘要：只有一个 72 帧的镜头。"""
    shot = {
        "shot_id": "shot_001", "order": 1, "intent": "推进",
        "shot_type": "MS", "duration_frames": 72,
        "characters": ["char_001"],
    }
    if dialogue_end:
        shot["dialogues"] = [{
            "character_id": "char_001", "text": "我先上船。",
            "start_frame": 40, "end_frame": dialogue_end,
        }]
    return {"success": True, "built": True,
            "plan": {"scene_heading": "落盘校验用例", "shots": [shot]}}


def test_a_shot_that_cannot_hold_its_dialogue_is_reported_at_save_time(tmp_path):
    saved = save_run_project(_summary(dialogue_end=70), out_dir=tmp_path)

    assert saved.path.exists()
    assert saved.validation["ok"] is False
    assert saved.validation["rules"] == ["S6"]
    first = saved.validation["errors"][0]
    #: 只报"校验不过"是不够的——要说清是哪一镜、错在哪，人才知道怎么修。
    assert first["rule"] == "S6"
    assert first["target"] == "shot_001"
    assert "装不下对白" in first["message"]


def test_the_save_time_report_and_the_load_time_report_agree(tmp_path):
    saved = save_run_project(_summary(dialogue_end=70), out_dir=tmp_path)
    loaded = validation_report(load_project(tmp_path))

    assert loaded["ok"] == saved.validation["ok"] is False
    assert loaded["rules"] == saved.validation["rules"] == ["S6"]
    assert [item["target"] for item in loaded["errors"]] == ["shot_001"]
    #: 两边报的是同一句话——口径漂了就等于"落盘时是一套、加载时是另一套"。
    assert (loaded["errors"][0]["message"]
            == saved.validation["errors"][0]["message"])


def test_a_project_that_fits_reports_ok_and_stays_quiet(tmp_path):
    saved = save_run_project(_summary(dialogue_end=40), out_dir=tmp_path)

    assert saved.validation["ok"] is True
    assert saved.validation["errors"] == []
    assert saved.validation["rules"] == []
    assert validation_report(load_project(tmp_path))["ok"] is True


def test_the_saved_file_is_written_even_when_validation_fails(tmp_path):
    """报告与闸门分开：**带 finding 的工程照样落盘**（§14.2 要能再打开它）。

    这条是负对照——若实现改成"校验不过就不写文件"，重构/交付就对真实运行断了。
    """
    saved = save_run_project(_summary(dialogue_end=70), out_dir=tmp_path)

    assert saved.path.exists()
    assert saved.path.name == "project.bdproj"
    #: 而且**能读回来**，校验结论一致（不是写了个打不开的文件）。
    assert load_project(tmp_path).sdl.shots[0].id == "shot_001"
