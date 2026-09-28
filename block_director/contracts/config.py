"""配置契约（执行文档 v1.2 §21.5）。

本模块是配置的**单一真源**：``specs/config.default.yaml`` 由 :func:`dump_default_yaml`
生成并与之保持一致。同时把文档中的设计决策编码成可执行校验（:func:`AppConfig.validate`），
例如"向量检索必须走 sidecar""depth 导出必须用 EEVEE"。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .enums import (
    Appearance,
    AuditLevel,
    DeliveryPreset,
    ErrorCode,
    OrchestrationMode,
    RagBackend,
    RenderBackend,
    Severity,
    TransportMode,
    VideoCodec,
    CRF,
    resolution_for,
)
from .serde import from_plain as _from_plain
from .serde import to_plain as _to_plain

CONFIG_VERSION = "1.2.0"
CONFIG_ENV_VAR = "BLOCKDIRECTOR_CONFIG"


# --------------------------------------------------------------------------- #
# 校验结果
# --------------------------------------------------------------------------- #
@dataclass
class Issue:
    """一条配置问题。``severity == error`` 时不得启动运行。"""

    code: str
    field: str
    severity: Severity
    message: str

    def __str__(self) -> str:  # pragma: no cover - 便利方法
        return f"[{self.severity}] {self.field}: {self.message} ({self.code})"


# --------------------------------------------------------------------------- #
# 分节配置
# --------------------------------------------------------------------------- #
@dataclass
class LLMConfig:
    transport: TransportMode = TransportMode.AUTO
    sidecar_url: str = "http://127.0.0.1:8765"
    sidecar_token: str = ""
    sidecar_timeout_s: float = 120.0
    provider: str = "openai"          # openai / deepseek / anthropic / local
    model: str = "gpt-4o"
    api_key: str = ""                 # 见 §14.3，不写入 .blend
    base_url: str = ""
    temperature_plan: float = 0.7
    temperature_repair: float = 0.2
    trace_prompts: bool = True        # §11.3：trace 记录完整 prompt/response
    trace_max_chars: int = 8000       # 单条记录的字段上限（§14.1 的"可配置上限"）


@dataclass
class RagConfig:
    enabled: bool = True
    backend: RagBackend = RagBackend.BM25     # 默认；§6.1
    embedder: str = "bge-small-zh-v1.5"
    top_k: int = 5
    max_tokens_per_call: int = 800


@dataclass
class OrchestrationConfig:
    mode: OrchestrationMode = OrchestrationMode.PLAN_STRUCTURED
    max_repair_attempts: int = 2
    react_max_steps: int = 6
    context_window_tokens: int = 32000
    #: Level 2 自我审核（§11.1）：每镜通过规则校验后再让模型反思一次。
    #: 它每镜多一次 LLM 调用，长片请按预算（§12.6）自行取舍。
    self_review: bool = True


@dataclass
class AuditConfig:
    level: AuditLevel = AuditLevel.STANDARD
    human_gate_on_plan: bool = True
    human_gate_on_axis_violation: bool = True


@dataclass
class BudgetConfig:
    max_llm_calls_per_scene_formula: str = "shots * 6"
    max_cost_usd: float = 5.0
    max_wall_minutes: float = 30.0


@dataclass
class CharacterConfig:
    head_radius: float = 0.35
    body_radius: float = 0.25
    body_height: float = 0.7
    leg_height: float = 0.4
    eye_radius: float = 0.06
    label_size: float = 0.15
    label_font_path: str = ""      # 留空则自动探测 CJK 字体（§9.4）


@dataclass
class AnimationConfig:
    fps: int = 24
    walk_speed: float = 0.05
    run_speed: float = 0.1
    blend_frames: int = 6


@dataclass
class DialogueConfig:
    """语速基准（§4.4）。``speech_rate`` 是**语速**倍率：>1 更快、耗时更短。"""

    chinese_cps: float = 3.0
    english_wps: float = 2.5
    speech_rate: Dict[str, float] = field(default_factory=lambda: {
        "normal": 1.00, "angry": 1.15, "excited": 1.15,
        "urgent": 1.20, "sad": 0.80, "thinking": 0.85, "whisper": 0.90,
    })


@dataclass
class DeliveryConfig:
    preset: DeliveryPreset = DeliveryPreset.HD16X9
    appearance: Appearance = Appearance.CLAY
    render_backend: RenderBackend = RenderBackend.WORKBENCH   # §15.3 定稿
    video_codec: VideoCodec = VideoCodec.H264                 # Blender 内置 FFmpeg
    crf: CRF = CRF.MEDIUM
    export_depth: bool = False                                # 需 eevee
    export_camera_traj: bool = False
    per_shot_clips: bool = True
    full_concat: bool = False
    external_ffmpeg_path: str = ""       # 可选；仅拼接/转码

    @property
    def resolution(self) -> Tuple[int, int]:
        return resolution_for(self.preset)


@dataclass
class UIConfig:
    show_axis: bool = True
    show_composition: bool = True
    show_safe_area: bool = True
    show_labels: bool = True


@dataclass
class AppConfig:
    config_version: str = CONFIG_VERSION
    llm: LLMConfig = field(default_factory=LLMConfig)
    rag: RagConfig = field(default_factory=RagConfig)
    orchestration: OrchestrationConfig = field(default_factory=OrchestrationConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    character: CharacterConfig = field(default_factory=CharacterConfig)
    animation: AnimationConfig = field(default_factory=AnimationConfig)
    dialogue: DialogueConfig = field(default_factory=DialogueConfig)
    delivery: DeliveryConfig = field(default_factory=DeliveryConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    # ----------------------------------------------------------------- 校验
    def validate(self) -> List[Issue]:
        """返回全部配置问题；空列表表示可安全启动（§21.5 + 文档决策）。"""
        issues: List[Issue] = []

        def err(code: str, field_name: str, message: str,
                severity: Severity = Severity.ERROR) -> None:
            issues.append(Issue(code, field_name, severity, message))

        # --- 通用取值域 ---
        if self.animation.fps <= 0:
            err("CFG_001", "animation.fps", "帧率必须为正整数")
        if self.animation.blend_frames < 0 or self.animation.blend_frames >= self.animation.fps:
            err("CFG_002", "animation.blend_frames",
                f"过渡帧数必须在 [0, fps) 内（当前 {self.animation.blend_frames}）")
        if self.dialogue.chinese_cps <= 0:
            err("CFG_003", "dialogue.chinese_cps", "中文字/秒必须为正数")
        if self.dialogue.english_wps <= 0:
            err("CFG_004", "dialogue.english_wps", "英文词/秒必须为正数")
        for emotion, rate in self.dialogue.speech_rate.items():
            if rate <= 0:
                err("CFG_005", f"dialogue.speech_rate.{emotion}",
                    "语速倍率必须为正数（>1 表示更快、耗时更短）")
        for name, value in (("temperature_plan", self.llm.temperature_plan),
                            ("temperature_repair", self.llm.temperature_repair)):
            if not 0.0 <= value <= 2.0:
                err("CFG_006", f"llm.{name}", f"温度必须在 [0, 2] 内（当前 {value}）")
        if self.llm.trace_max_chars < 0:
            err("CFG_008", "llm.trace_max_chars",
                f"trace 字段上限不能为负（当前 {self.llm.trace_max_chars}）；"
                f"0 表示不截断")
        if self.rag.top_k <= 0:
            err("CFG_007", "rag.top_k", "检索条数必须为正整数")
        if self.orchestration.max_repair_attempts < 0:
            err("CFG_008", "orchestration.max_repair_attempts", "修复次数不能为负")
        if self.orchestration.react_max_steps < 0:
            err("CFG_009", "orchestration.react_max_steps", "ReAct 步数不能为负")
        if self.budget.max_cost_usd <= 0:
            err("CFG_010", "budget.max_cost_usd", "费用上限必须为正数")
        if self.budget.max_wall_minutes <= 0:
            err("CFG_011", "budget.max_wall_minutes", "时间上限必须为正数")

        # --- 决策 1（§6.1）：向量检索只能由 sidecar 提供 ---
        if self.rag.enabled and self.rag.backend is RagBackend.VECTOR \
                and self.llm.transport is TransportMode.DIRECT:
            err("CFG_101", "rag.backend",
                "向量检索需要 sidecar（进程内模式禁止安装 torch/faiss）；"
                "请改为 bm25，或将 llm.transport 设为 auto/sidecar")

        # --- 决策 2（§15.3）：depth 导出需要 Z Pass，只有 EEVEE 提供 ---
        if self.delivery.export_depth and self.delivery.render_backend is not RenderBackend.EEVEE:
            err("CFG_102", "delivery.export_depth",
                f"depth 导出需要 Z Pass，必须使用 eevee（当前 {self.delivery.render_backend}）")

        # --- 决策 3（§15.3 实测）：OpenGL 视口渲染仅限 GUI ---
        if self.delivery.render_backend is RenderBackend.VIEWPORT:
            err("CFG_103", "delivery.render_backend",
                "viewport(OpenGL) 仅能在 GUI 下工作；批处理会被自动改派为 workbench",
                Severity.WARNING)

        # --- 提示类 ---
        if not self.character.label_font_path:
            err("CFG_201", "character.label_font_path",
                "未指定中文字体，将自动探测系统 CJK 字体（§9.4）",
                Severity.WARNING)
        if self.llm.transport is TransportMode.DIRECT and not self.llm.api_key \
                and not self.llm.base_url:
            err("CFG_202", "llm.api_key",
                "进程内模式未配置 API Key 或本地端点，LLM 调用将失败",
                Severity.WARNING)
        if not self.rag.enabled:
            err("CFG_203", "rag.enabled",
                "RAG 已关闭，将使用 digest 兜底知识注入",
                Severity.WARNING)
        return issues

    def errors(self) -> List[Issue]:
        return [i for i in self.validate() if i.severity is Severity.ERROR]

    def require_valid(self) -> None:
        """存在 ERROR 级问题时抛 ValueError（启动前调用）。"""
        problems = self.errors()
        if problems:
            raise ValueError("配置校验失败:\n" + "\n".join(str(p) for p in problems))

    # ------------------------------------------------------------- 序列化
    def to_dict(self) -> Dict[str, Any]:
        return _to_plain(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        return _from_plain(cls, data)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        """从 YAML/JSON 载入；文件不存在时返回默认配置。"""
        target = Path(path) if path is not None else default_config_path()
        if not target.exists():
            return cls()
        raw = target.read_text(encoding="utf-8")
        data = _parse_text(raw, target.suffix.lower())
        return cls.from_dict(data)

    def save(self, path: Optional[Path] = None) -> Path:
        """写回配置；沿用后缀决定格式（默认 YAML，其次 JSON）。"""
        target = Path(path) if path is not None else default_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        suffix = target.suffix.lower()
        if suffix in (".yaml", ".yml"):
            text = dump_yaml(self.to_dict())
        else:
            text = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        target.write_text(text, encoding="utf-8")
        return target


# 序列化工具（to_plain / from_plain）已抽到 contracts/serde.py，供 SDL 等复用。
# --------------------------------------------------------------------------- #
# 路径与文本解析（§1.4 / §14.3 跨平台）
# --------------------------------------------------------------------------- #
def default_config_dir() -> Path:
    """按平台返回配置目录。Windows 用 %APPDATA%\\BlockDirector\\，其余用 XDG。"""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "BlockDirector"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "BlockDirector"


def default_config_path() -> Path:
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override)
    return default_config_dir() / "config.yaml"


def _parse_text(text: str, suffix: str) -> Dict[str, Any]:
    if suffix in (".yaml", ".yml"):
        return parse_yaml(text)
    return json.loads(text)


def parse_yaml(text: str) -> Dict[str, Any]:
    """解析 YAML；缺少 PyYAML 时给出明确指引而不是 ImportError。"""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - 仅缺依赖时触发
        raise RuntimeError(
            "读取 YAML 需要 PyYAML；请改用 .json 配置，或安装："
            "<blender>/<ver>/python/bin/python.exe -m pip install pyyaml"
        ) from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("配置文件根节点必须是映射（mapping）")
    return data


def dump_yaml(data: Dict[str, Any]) -> str:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("写出 YAML 需要 PyYAML；请改用 .json 后缀") from exc
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def dump_default_yaml() -> str:
    """生成 specs/config.default.yaml 的内容（供测试与文档同步）。"""
    header = (
        "# BlockDirector 默认配置（执行文档 v1.2 §21.5）\n"
        "# 本文件由 block_director.contracts.config.dump_default_yaml() 生成，请勿手工漂移；\n"
        "# 修改默认值请改 block_director/contracts/config.py 后重新生成。\n\n"
    )
    return header + dump_yaml(AppConfig().to_dict())
