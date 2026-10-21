# F13：per-shot 墙钟前瞻均摊（纯函数）。
# 真跑（final8/final9）实测：全局墙钟是唯一时间护栏，单镜 ReAct/修复
# 空转（一次 LLM 调用可达 190s+）可耗尽整场墙钟 -> CANCELLED，后续镜
# 没有生成机会。本测试钉死"按剩余镜数前瞻均摊"的纯函数语义：
# * 剩余镜 > 1 时，公平份额 = 剩余墙钟 / 剩余镜数（不低于地板）；
# * 当前镜已用时间超过份额 -> 触发收尾当前镜（保留 best、渲染、前进）；
# * 剩余 1 镜永不触发（整场墙钟归它）；
# * 墙钟无限（0）永不触发。
# 这是资源公平分配策略，不是放宽 80 分门槛：未过线照样记 failed、
# 按 F12 渲染最佳版本出 mp4。
from __future__ import annotations

import sys

import pytest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer5_orchestrator.wall_share import (  # noqa: E402
    per_shot_wall_share,
)


def test_remaining_shots_one_never_triggers() -> None:
    """最后一镜：整场剩余墙钟都归它，永不因份额收尾。"""
    assert per_shot_wall_share(
        remaining_wall_s=300.0, remaining_shots=1,
        elapsed_in_shot_s=9999.0) is False


def test_unlimited_wall_never_triggers() -> None:
    """墙钟无限（0）：不开启时间预算。"""
    assert per_shot_wall_share(
        remaining_wall_s=0.0, remaining_shots=4,
        elapsed_in_shot_s=9999.0) is False


def test_over_share_triggers() -> None:
    """剩余 240s、剩 4 镜 -> 份额 60s/镜；已用 61s -> 触发。"""
    assert per_shot_wall_share(
        remaining_wall_s=240.0, remaining_shots=4,
        elapsed_in_shot_s=61.0) is True


def test_under_share_no_trigger() -> None:
    """剩余 240s、剩 4 镜 -> 份额 60s/镜；已用 59s -> 不触发。"""
    assert per_shot_wall_share(
        remaining_wall_s=240.0, remaining_shots=4,
        elapsed_in_shot_s=59.0) is False


def test_floor_raises_small_share() -> None:
    """份额低于地板（默认 60s）时按地板算，防过激。"""
    assert per_shot_wall_share(
        remaining_wall_s=120.0, remaining_shots=4,
        elapsed_in_shot_s=75.0, min_share_s=60.0) is True
    assert per_shot_wall_share(
        remaining_wall_s=120.0, remaining_shots=4,
        elapsed_in_shot_s=55.0, min_share_s=60.0) is False


def test_exactly_at_share_boundary_not_trigger() -> None:
    """恰好等于份额：不触发（下一轮迭代再判）。"""
    assert per_shot_wall_share(
        remaining_wall_s=240.0, remaining_shots=4,
        elapsed_in_shot_s=60.0) is False


def test_remaining_shots_zero_is_safe() -> None:
    """防御：剩余镜 0（异常态）不触发。"""
    assert per_shot_wall_share(
        remaining_wall_s=300.0, remaining_shots=0,
        elapsed_in_shot_s=9999.0) is False


def test_negative_elapsed_is_safe() -> None:
    """防御：负耗时（时钟异常）按未超时处理。"""
    assert per_shot_wall_share(
        remaining_wall_s=240.0, remaining_shots=4,
        elapsed_in_shot_s=-5.0) is False


def test_negative_remaining_wall_is_unlimited() -> None:
    """防御：负数剩余墙钟按"墙钟无限"处理。"""
    assert per_shot_wall_share(
        remaining_wall_s=-1.0, remaining_shots=4,
        elapsed_in_shot_s=9999.0) is False
