"""运行设置：把面板上的选择覆盖到配置上（执行文档 v1.2 §13.1）。

纯函数（接收一个映射而不是 ``bpy`` 的 scene），因此可以在 pytest 里直接断言
"面板选什么 → 配置变成什么"。

原则：**面板只覆盖它有控件的那几项**，其余一律沿用配置文件的值；覆盖完再跑
一次 ``config.errors()``，有错就报错而不是带着坏配置开跑（例如 ``export_depth``
配了 workbench）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from ..contracts.config import AppConfig
from ..contracts.enums import AuditLevel, DeliveryPreset, RenderBackend
from ..layer1_input.script_parser import SUFFIX_FORMATS

#: 面板提供选择的取值（顺序即界面顺序）
PROVIDERS = ("openai", "deepseek", "anthropic", "local")
AUDIT_LEVELS = tuple(item.value for item in AuditLevel)
PRESETS = tuple(item.value for item in DeliveryPreset)
APPEARANCES = ("clay", "flat", "color_coded")
BACKENDS = tuple(item.value for item in RenderBackend)


def suffix_help(mapping: Mapping[str, str]) -> str:
    """把 ``SUFFIX_FORMATS`` 渲染成给人看的一句话（v1.4 US-1③）。

    刻意**派生**而不是手写：手写的串一定会漂移（实测 ``panel_main`` 那句就
    漏了 ``.md``/``.text``）。负例见 ``tests/test_run_settings_suffix_formats``。
    """
    suffixes = "、".join(sorted(str(key) for key in mapping))
    return f"支持的剧本格式：{suffixes}（.md/.txt 走纯文本解析，可直接黏贴中文分镜表）"


#: v1.4 US-1③：面板的"剧本格式"说明串必须与 ``script_parser.SUFFIX_FORMATS``
#: **同源**。它落在本模块（**无 bpy**）而不是 ``panel_main.py``——后者的顶层
#: ``import bpy`` 会让纯层单测进不去，同源断言就无从写起。
SUFFIX_HELP = suffix_help(SUFFIX_FORMATS)


def apply_scene_settings(config: AppConfig,
                         settings: Mapping[str, Any]
                         ) -> Tuple[AppConfig, List[str]]:
    """就地覆盖配置，返回 ``(config, problems)``；``problems`` 空表示可用。"""
    problems: List[str] = []

    provider = str(settings.get("provider") or "").strip()
    if provider:
        config.llm.provider = provider
    model = str(settings.get("model") or "").strip()
    if model:
        config.llm.model = model

    level = str(settings.get("audit_level") or "").strip()
    if level:
        if level not in AUDIT_LEVELS:
            problems.append(f"审核级别 {level!r} 不在 {AUDIT_LEVELS} 之内")
        else:
            config.audit.level = AuditLevel(level)

    preset = str(settings.get("preset") or "").strip()
    if preset:
        if preset not in PRESETS:
            problems.append(f"分辨率预设 {preset!r} 不在 {PRESETS} 之内")
        else:
            config.delivery.preset = DeliveryPreset(preset)
    appearance = str(settings.get("appearance") or "").strip()
    if appearance:
        if appearance not in APPEARANCES:
            problems.append(f"外观预设 {appearance!r} 不在 {APPEARANCES} 之内")
        else:
            config.delivery.appearance = appearance
    backend = str(settings.get("render_backend") or "").strip()
    if backend:
        if backend not in BACKENDS:
            problems.append(f"渲染后端 {backend!r} 不在 {BACKENDS} 之内")
        else:
            config.delivery.render_backend = RenderBackend(backend)

    for key in ("max_cost_usd", "max_wall_minutes"):
        value = settings.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            problems.append(f"{key} 必须是数字，实际 {value!r}")
            continue
        if number < 0:
            problems.append(f"{key} 不能为负（{number}）")
            continue
        setattr(config.budget, key, number)

    timeout = settings.get("llm_timeout_s")
    if timeout is not None:
        try:
            number = float(timeout)
        except (TypeError, ValueError):
            problems.append(f"llm_timeout_s 必须是数字，实际 {timeout!r}")
        else:
            if number <= 0:
                problems.append(f"llm_timeout_s 必须为正数（{number}）")
            else:
                config.llm.timeout_s = number

    call_cap = settings.get("max_llm_calls")
    if call_cap is not None:
        try:
            number = int(call_cap)
        except (TypeError, ValueError):
            problems.append(f"max_llm_calls 必须是整数，实际 {call_cap!r}")
        else:
            if number < 0:
                problems.append(f"max_llm_calls 不能为负（{number}）")
            else:
                # 字段语义不变：面板改的是"每场景额度公式"本身
                config.budget.max_llm_calls_per_scene_formula = str(number)

    problems.extend(item.message for item in config.errors())
    return config, problems


def collect_settings(scene) -> Dict[str, Any]:
    """从 scene 上读面板字段（缺字段时给 None，表示"不覆盖"）。"""
    keys = ("bd_provider", "bd_model", "bd_audit_level", "bd_preset",
            "bd_appearance", "bd_render_backend", "bd_max_cost_usd",
            "bd_max_wall_minutes", "bd_max_llm_calls", "bd_llm_timeout_s")
    return {key[3:]: getattr(scene, key, None) for key in keys}
