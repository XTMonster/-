"""F13：per-shot 墙钟前瞻均摊（纯层，无 bpy，无 IO）。

真跑（final8/final9，2026-10-20）实测：全局墙钟（``--wall``/``max_wall_minutes``）
是唯一时间护栏；单镜 ReAct/修复空转（一次 LLM 调用可达 190s+）可直接耗尽
整场墙钟，``_wrap_up_wall_clock`` 把整场打成 CANCELLED，后续镜没有生成
机会——7 镜完整剧本下风险翻倍。本模块把全局墙钟按"剩余镜数"前瞻均摊：
单镜超过自己的公平份额时，driver 收尾该镜（保留 best、渲染最佳版本、
如实记 failed）并推进下一镜，等价于 F11 ``react_round_exhausted`` 的
**时间维度**版（F13：拦截错误后回溯而不是停止生成，视频一定要出）。

语义红线：这里**不修改任何分数门槛/判据**——未过 80 分照样记 failed、
按 F12 渲染最佳版本出 mp4；它只是资源公平分配，不是降级。
"""

from __future__ import annotations


def per_shot_wall_share(
    remaining_wall_s: float,
    remaining_shots: int,
    elapsed_in_shot_s: float,
    min_share_s: float = 60.0,
) -> bool:
    """当前镜是否已超过其公平墙钟份额（触发逐镜收尾前进）。

    参数：
        remaining_wall_s -- 整场剩余墙钟（0/负数 = 无限/不启用）。
        remaining_shots -- 剩余镜数（含当前镜；<=1 时整场墙钟归当前镜）。
        elapsed_in_shot_s -- 当前镜自上次迭代已持续的时间。
        min_share_s -- 单镜时间地板（防过激；默认 60s）。

    返回：
        True = 当前镜已超份额，driver 应保留 best、收尾并推进下一镜；
        False = 继续当前镜的迭代。
    """
    if remaining_wall_s <= 0:
        return False
    if remaining_shots <= 1:
        return False
    if elapsed_in_shot_s < 0:
        return False
    share = max(remaining_wall_s / remaining_shots, min_share_s)
    return elapsed_in_shot_s > share
