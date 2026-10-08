"""配置契约（执行文档 v1.2 §21.5）。

本模块是配置的**单一真源**：``specs/config.default.yaml`` 由 :func:`dump_default_yaml`
生成并与之保持一致。同时把文档中的设计决策编码成可执行校验（:func:`AppConfig.validate`），
例如"向量检索必须走 sidecar""depth 导出必须用 EEVEE"。
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .enums import (
    Appearance,
    AuditLevel,
    CROWD_MODES,
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

CONFIG_VERSION = "1.3.0"
CONFIG_ENV_VAR = "BLOCKDIRECTOR_CONFIG"

#: ``#RRGGBB`` / ``#RGB``（契约层不 import utils，保持依赖单向）
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _is_hex_color(value: object) -> bool:
    return bool(_HEX_COLOR_RE.match(str(value or "")))


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
    #: v1.6 A4：LLM 单次调用墙钟超时（秒）。慢思考通道建议 ≥600。
    timeout_s: float = 300.0
    max_tokens: int = 0               # 0 = 不发送；思维模型需放大（实测 qwen3 需 8k+）
    temperature_plan: float = 0.7
    temperature_repair: float = 0.2
    trace_prompts: bool = True        # §11.3：trace 记录完整 prompt/response
    trace_max_chars: int = 8000       # 单条记录的字段上限（§14.1 的"可配置上限"）


@dataclass
class RagConfig:
    enabled: bool = True
    #: v1.4 §2.3：默认后端 = **超图 RAG**（跑在 sidecar 上）。
    #: sidecar 不可用时降级为内置 BM25，并在 `knowledge_trace.json` 里
    #: 标 `degraded: true` —— 降级可以，静默不行。
    backend: RagBackend = RagBackend.HYPERGRAPH
    embedder: str = "bge-small-zh-v1.5"
    #: 2026-10-08：用户要求"注入更多知识"之后，由主线**按实测**定的值（12→15 的取舍见
    #: `docs/evidence/20261008-v10-nodes1-4-run/README.md` §8）：15 是**最小**能让
    #: **计划阶段三栏到齐**（硬/软/案例）的宽度；再往上（20/30/50）只有弱命中——
    #: "命中≥2 个查询槽位"的边**恒为 5 条**，20 以上七成以上是擦边。
    top_k: int = 15
    #: v1.5 §7（P2-T5）：规则包（P4-T1 ``rulepack``）每镜注入的规则条数上限。
    #: 校验 3–8——太少约束不足，太多会把候选挤掉。消费者在 P4-T1 落地。
    #: 规则包渲染条数上限（合法区间 **3–8**，`CFG_020`）；取合法上限。
    rule_top_k: int = 8
    #: 2026-10-08 用户裁决："把这个调高到五六万这样子"——三栏注入的**每镜**上限。
    #: 改的是**预算**（上限），不是判据；实际注入多少仍由检索宽度决定
    #: （`top_k` / `rule_top_k` / `cases_top_k`），**上限抬了不等于注入变多**。
    max_tokens_per_call: int = 50000
    #: v1.4 §2.3：整场预取（``block_for_plan``）的 token 上限。此前是
    #: ``knowledge/retriever.py`` 里的硬编码常量，现在有真正的消费者。
    #: 同上：整场预取（`block_for_plan`）的 token 上限，2026-10-08 抬到 60000。
    plan_prefetch_tokens: int = 60000
    #: v1.4 §2.3b：L3 案例层的载体。``lightrag``（默认）／``hybrid``（仅
    #: LightRAG 不可用时降级，须记 ``cases_degraded``）／``off``（显式关闭）。
    cases_backend: str = "lightrag"
    #: L3 返回的参考案例条数（注入到"仅参考"栏）
    cases_top_k: int = 3
    #: v1.4 §2.3 / §3.2（R51）：超图抽取**第 1 段**（逐 chunk 抽原子边）的并发上限。
    #: 第 2 段（跨卡归并）**强制串行**，不受该键影响——否则同一批数据两次运行
    #: 会得到不同的边，六元指纹缓存与"重放一致"直接失效。
    extract_concurrency: int = 16


@dataclass
class OrchestrationConfig:
    mode: OrchestrationMode = OrchestrationMode.PLAN_STRUCTURED
    max_repair_attempts: int = 2
    react_max_steps: int = 6
    #: 一次**定向修复**里允许几轮 LLM（v1.4 §7.1 B4）。``1`` = 老行为：
    #: 模型回一次就收尾。默认 3 的理由是实测出来的——2026-10-04 的 64 镜真跑
    #: (`long17`) 里 104 个修复回合有 **72 个**恰好是 `search_knowledge` ＋
    #: `get_scene_state` 两次**只读**调用："查资料 + 看场景"把唯一一轮用光了，
    #: 模型连动手的机会都没有（工具观测此前也没有回灌，见 `driver._continue_repair`）。
    repair_max_turns: int = 3
    context_window_tokens: int = 32000
    #: v1.4 §2.4：单次运行的镜数上限。``0`` = 不限（**省略 ``maxItems`` 键**，
    #: 不是写 0——``tool_schema.py`` 会真的执行 ``maxItems``）。
    max_shots: int = 0
    #: Level 2 自我审核（§11.1）：每镜通过规则校验后再让模型反思一次。
    #: 它每镜多一次 LLM 调用，长片请按预算（§12.6）自行取舍。
    self_review: bool = True
    #: v1.5 §7（P6-T2）：同一镜生成几个候选草案（Best-of-N 探索模式）。
    #: ``1`` = 现状（每镜一次调用、零行为差）；``2–5`` 时同镜多要 N 个候选，
    #: 规则评分只做 **rerank 不作过滤**——低分候选进 ``shots.json`` 的
    #: ``alternates[]``，不丢。默认关。
    draft_candidates: int = 1


@dataclass
class AuditConfig:
    level: AuditLevel = AuditLevel.STANDARD
    human_gate_on_plan: bool = True
    human_gate_on_axis_violation: bool = True


@dataclass
class VlmReviewConfig:
    """v1.5 §5.5（P6-T1）：可选的 VLM 评审**外回路**。

    评审结果只写进 ``shots.json`` 与面板展示，**不参与任何门**（红线：评委
    不作唯一裁决）。默认关——``enabled=False`` 时全链路零行为差。
    ``max_shots=0`` 表示不限制被评审的镜数。
    """

    enabled: bool = False
    max_shots: int = 0


@dataclass
class BudgetConfig:
    #: 每个镜头允许多少次 LLM 调用。v1.3 多了阶段 S 与运镜/知识检索，
    #: 额度从 v1.2 的 ``shots * 6`` 提到 ``shots * 8 + 40``（§6.1 / v1.4 §2.4）。
    max_llm_calls_per_scene_formula: str = "shots * 8 + 40"
    #: v1.4 §2.4：单场静态额度**下限保障**（不是上限）。真正的硬顶只由
    #: CLI ``--max-llm-calls`` 提供（``0`` = 不限）。
    max_llm_calls_ceiling: int = 200
    max_cost_usd: float = 5.0
    max_wall_minutes: float = 120.0
    #: **每次调用允许多少 token**（2026-10-07 用户"你看着来"授权后加）：账本的
    #: token 上限＝``本场调用额度 × 这一格``，再与 ``max_tokens_ceiling``、以及
    #: ``BudgetLimits.max_tokens`` 的静态下限取**大**。
    #:
    #: 为什么必须让它随场景走（实测）：`BudgetLimits.max_tokens` 是**写死的 2 M**，
    #: 而调用额度是"shots * 8 + 40"——两个上限互相矛盾：v15 管线下 64 镜真跑两次
    #: 都**在只用了 59% 调用额度时**就吃满 2 M（`prompt 1,886,634 + completion 118,326`，
    #: 见 `docs/evidence/20261007-v15-long/` 与 `…-long-topped-out/`），
    #: 于是"没用完的调用额度"结构上不可达，长剧本验收恒红。
    #: 7,000 来自实测：那两次真跑 **6,150 / 6,311 token/调用**，向上取整到千。
    #: 这一格只影响**资源上限**，不改任何判据/门限。
    tokens_per_call_allowance: int = 7000
    #: token 上限的**静态帽**（0 = 不设帽）：再长的戏也不让它无限增长。
    #: 60 镜（520 次调用 × 7,000 = 3.64 M）不触帽；100 镜以上按 4 M 封顶。
    max_tokens_ceiling: int = 4_000_000


@dataclass
class BriefConfig:
    """阶段 S（剧本理解，§3.2）。"""

    #: 是否先做一次结构化理解。关掉就退回 v1.2 的"直接规划"路径。
    enabled: bool = True
    #: SceneBrief 注入规划提示的 token 上限。没有上限的超长理解会把整次
    #: 调用顶出模型上下文窗口（system 永远不进 trim 的裁剪范围）。
    max_tokens: int = 1200


@dataclass
class SceneConfig:
    """场景空间：模型能看到的**可用范围**（v1.6，2026-10-04）。

    为什么需要它（真跑实测）：`walk_to` 的 `target_position` 是**绝对**位置，
    而计划提示里从来没有"这场戏有多大"这件事 ⇒ 模型把目的地写到 8–9.5 m，
    再经一串接力把角色带到 25 m 之外（`docs/evidence/20261004-walk-handover/`）。
    这个值有两个消费者：

    * 计划提示里的一条**硬约束**（走位目的地必须落在范围内）；
    * 构建期对越界走位的**告警**（`shot_builder.action_requests`）。

    它**不**夹取机位——`SceneSpec.room` 仍然只在场景显式给出房间时才生效
    （把默认范围当房间用会让所有远机位被悄悄夹回来）。
    """

    #: 场地半径（米）：可用范围 = X ∈ [−extent, +extent]、Y ∈ [−extent, +extent]。
    extent_m: float = 12.0


@dataclass
class CrowdConfig:
    """群众代理（v1.3 §3.6）。

    v1.4 X17：``enabled`` 是**三态**——``None``（默认）＝按剧本声明，
    ``True`` ＝强制开启，``False`` ＝显式关闭（优先级最高）。
    优先级：**显式 false > 剧本声明 > 默认关**。
    """

    enabled: Optional[bool] = None
    max_instances: int = 40
    seed: int = 0
    #: ``static`` 或 ``walk``（walk 是"漂移 + 微起伏"的近似，不是骨骼走姿）
    mode: str = "walk"
    height: float = 1.65
    spacing: float = 1.6


@dataclass
class VfxConfig:
    """特效代理（v1.3 §3.6）。Workbench 下没有半透明，代理是不透明实色。"""

    enabled: bool = True


@dataclass
class CharacterConfig:
    #: v1.4 §2.1 冻结几何（纯比例，由 ``cinema/anchor.py`` 推导绝对高度）。
    #: 旧的 ``head_radius``/``body_radius``/``body_height``/``leg_height``/
    #: ``eye_radius`` 五个字段全仓零消费者，已删除；``CFG_301`` 防止复活。
    total_height: float = 1.70
    head_ratio: float = 0.37
    torso_ratio: float = 0.44
    leg_ratio: float = 0.19
    eye_r: float = 0.035
    eye_dx: float = 0.11
    #: 眼球相对头球的突出量（米）：``d = head_r - eye_r + eye_protrusion``
    eye_protrusion: float = 0.015
    #: 头球与躯干顶的间隙（0 ＝ 相切，容差 ±0.005）
    neck_gap: float = 0.0
    #: 眼睛单独用一份深色材质。v1.2 给眼睛挂的是**与身体同一个材质**，
    #: 于是眼睛和身体同色、看上去像没有五官。
    eye_color: str = "#101010"
    label_size: float = 0.15
    label_font_path: str = ""      # 留空则自动探测 CJK 字体（§9.4）
    #: v1.3 诉求 4：标签进参考视频（首帧 PNG 与 depth 序列仍然不带）。
    label_render: bool = True
    #: 屏幕恒定字号：720p 下的目标像素高度与可读下限
    label_pixels: float = 30.0
    label_min_pixels: float = 24.0
    #: 上限：不超过画面高度的这个比例（避免大远景里标签大得离谱）
    label_max_ratio: float = 0.06
    label_color: str = "#FFFFFF"          # 白字
    label_stroke_color: str = "#000000"   # 黑描边
    #: v1.6 A7（D-19）：步长自适应。标签间相对屏幕速度超阈或插值期检出重叠时，
    #: 该区段加密直至每帧；关闭则恢复固定步长行为。
    label_adaptive_sampling: bool = True
    #: v1.6 A7（D-19）：烘焙后全帧自检，重叠帧写 label_overlap_report 事件。
    label_fullframe_verify: bool = True


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
    #: v1.3：剧本声明优先。剧本写明了时长就用它，只有没声明才回退到语速估算。
    #: 取值 ``script_first`` / ``engine``。
    timing_source: str = "script_first"
    #: 声明值与引擎下限之间的容差（秒）：用于 R015 的"声明自洽"判定。
    declared_tolerance_s: float = 0.2
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
    #: v1.6 E3（FR-A5）：每角色一张固定机位定妆卡（可选，默认开）。
    reference_cards: bool = True
    #: v1.6 E2（FR-A3）：逐元素遮罩（可选，默认开；需 eevee）。
    mask_pass: bool = True
    per_shot_clips: bool = True
    #: v1.4 §2.4 D4：连续成片**默认产出**并保留分段（原默认 false）。
    full_concat: bool = True
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
class FramingConfig:
    """构图/取景策略（v1.4 §2.2）。"""

    #: ``board``（默认，头顶不切、上边距 ≥ 画面高 8%）／``cinematic``
    headroom_policy: str = "board"


@dataclass
class GuardConfig:
    """视锥构图校验阈值（v1.6 B2，FR-C）。与 ``cinema/frustum_metrics.GuardConfig`` 逐键同名。"""

    #: 总开关；关掉时采样器与告警都不跑（不是降级，是用户选择）
    enabled: bool = True
    #: 风格档：strict / standard / loose（GUARD_PRESETS）；下面的数值 = standard
    preset: str = "standard"
    #: 边缘裁切率超过此值告警（包围盒虚胖时标 confidence=low）
    edge_clip_max: float = 0.10
    #: 朝向侧留白低于此值告警
    lead_room_min: float = 0.05
    #: 持续违规至少多少帧才触发告警（瞬时越界容忍）
    sustain_frames: int = 12
    #: 镜内景别漂移上限（占比变化 > 此值告警）
    size_drift: float = 0.15
    #: 两帧内占比跳变上限
    jump_ratio: float = 0.25
    #: 跳切风险：视角差低于此值（度）时检查景别差
    jump_cut_angle_deg: float = 30.0
    #: 跳切风险：景别占比差低于此值时告警
    jump_cut_size_diff: float = 0.10
    #: 主体被遮挡超过此值且未声明前景遮挡 → warning
    occlusion_warn: float = 0.20
    #: bpy 采样步长（帧数）
    sample_step: int = 4
    #: 景别区间表（TDD §4.1）：head＝头部占画高（近景系），body＝全身占画高（中远景系）
    size_bands: Dict[str, Dict[str, List[float]]] = field(
        default_factory=lambda: {
            "head": {"MCU": [0.45, 0.60], "CU": [0.55, 0.75],
                     "ECU": [0.75, 1.0]},
            "body": {"MS": [0.55, 0.70], "MLS": [0.70, 0.88],
                     "LS": [0.35, 0.60], "ELS": [0.15, 0.35]},
        })


#: 三档阈值组（TDD §6）：standard = GuardConfig 默认值；strict 收紧、loose 放宽。
#: 只覆盖"比率/帧数"类阈值，景别区间表三档共用。
GUARD_PRESETS: Dict[str, Dict[str, float]] = {
    "strict": {"edge_clip_max": 0.05, "lead_room_min": 0.08,
               "sustain_frames": 6, "size_drift": 0.10, "jump_ratio": 0.15,
               "occlusion_warn": 0.10},
    "standard": {},
    "loose": {"edge_clip_max": 0.20, "lead_room_min": 0.03,
              "sustain_frames": 24, "size_drift": 0.25, "jump_ratio": 0.35,
              "occlusion_warn": 0.35},
}


def resolve_guard_thresholds(guard: "GuardConfig") -> Dict[str, Any]:
    """按 ``preset`` 把档位表叠到显式阈值上（standard ＝ 原样）。"""
    values = {key: getattr(guard, key) for key in (
        "edge_clip_max", "lead_room_min", "sustain_frames", "size_drift",
        "jump_ratio", "jump_cut_angle_deg", "jump_cut_size_diff",
        "occlusion_warn", "sample_step")}
    values.update(GUARD_PRESETS.get(str(guard.preset), {}))
    values["size_bands"] = {kind: {name: (float(b[0]), float(b[1]))
                                   for name, b in bands.items()}
                            for kind, bands in guard.size_bands.items()}
    return values


@dataclass
class RhythmConfig:
    """节奏编译（v1.6 D2，FR-B3；TDD §6 的 ``rhythm:`` 段）。"""

    #: 总开关。关掉 = 回到 v1.5 的节奏路径（用户选择，不是静默降级）。
    enabled: bool = True
    #: 镜长档案名（闭集 = ``contracts/rhythm.py::PACING_PROFILES``）。
    pacing_profile: str = "standard"
    #: ``pace`` → 帧长倍率表（与 ``beat_compiler.PACE_FRAME_MULTIPLIER`` 同值，
    #: ``tests/test_config_v16.py`` 逐键对拍防漂移）。
    pace_frame_multiplier: Dict[str, float] = field(default_factory=lambda: {
        "slow": 1.35, "normal": 1.0, "brisk": 0.7,
    })


@dataclass
class LabelsConfig:
    """角色标签全帧防互挡（v1.6 A7，D-19）。"""

    #: 是否开启自适应采样加密（插值帧检出重叠时局部加密到每帧）
    adaptive_sampling: bool = True
    #: 是否在烘焙后做全帧自检并写 label_overlap_report 事件
    fullframe_verify: bool = True


@dataclass
class AppConfig:
    config_version: str = CONFIG_VERSION
    llm: LLMConfig = field(default_factory=LLMConfig)
    rag: RagConfig = field(default_factory=RagConfig)
    orchestration: OrchestrationConfig = field(default_factory=OrchestrationConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    brief: BriefConfig = field(default_factory=BriefConfig)
    scene: SceneConfig = field(default_factory=SceneConfig)
    crowd: CrowdConfig = field(default_factory=CrowdConfig)
    vfx: VfxConfig = field(default_factory=VfxConfig)
    character: CharacterConfig = field(default_factory=CharacterConfig)
    animation: AnimationConfig = field(default_factory=AnimationConfig)
    dialogue: DialogueConfig = field(default_factory=DialogueConfig)
    delivery: DeliveryConfig = field(default_factory=DeliveryConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    framing: FramingConfig = field(default_factory=FramingConfig)
    vlm_review: VlmReviewConfig = field(default_factory=VlmReviewConfig)
    guard: GuardConfig = field(default_factory=GuardConfig)
    rhythm: RhythmConfig = field(default_factory=RhythmConfig)
    labels: LabelsConfig = field(default_factory=LabelsConfig)

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
        #: v1.6：场景可用范围。0 或负数等于"哪儿都不能站"，必须当场拦下。
        if float(self.scene.extent_m) <= 0.0:
            err("CFG_214", "scene.extent_m",
                f"场景范围半径必须为正数（当前 {self.scene.extent_m}）")
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
            err("CFG_012", "llm.trace_max_chars",
                f"trace 字段上限不能为负（当前 {self.llm.trace_max_chars}）；"
                f"0 表示不截断")
        if self.llm.max_tokens < 0:
            err("CFG_014", "llm.max_tokens",
                f"max_tokens 不能为负（当前 {self.llm.max_tokens}）；0 表示不限制")
        if self.llm.timeout_s <= 0:
            err("CFG_023", "llm.timeout_s",
                f"LLM 超时时间必须为正数（当前 {self.llm.timeout_s}）")
        #: v1.6 B2：视锥构图校验段。TDD 草拟的 CFG_021–023 已被占用，顺延到 215–217。
        if self.guard.preset not in GUARD_PRESETS:
            err("CFG_215", "guard.preset",
                f"未知档位 {self.guard.preset!r}；合法值 {sorted(GUARD_PRESETS)}")
        for name in ("edge_clip_max", "lead_room_min", "size_drift",
                     "jump_ratio", "jump_cut_size_diff", "occlusion_warn"):
            value = float(getattr(self.guard, name))
            if not 0.0 < value < 1.0:
                err("CFG_216", f"guard.{name}",
                    f"比率阈值必须在 (0, 1) 内（当前 {value}）")
        if not 0.0 < float(self.guard.jump_cut_angle_deg) < 180.0:
            err("CFG_216", "guard.jump_cut_angle_deg",
                f"角度阈值必须在 (0, 180) 内（当前 {self.guard.jump_cut_angle_deg}）")
        for name in ("sustain_frames", "sample_step"):
            if int(getattr(self.guard, name)) < 1:
                err("CFG_216", f"guard.{name}",
                    f"帧数阈值必须 ≥1（当前 {getattr(self.guard, name)}）")
        for kind, bands in (self.guard.size_bands or {}).items():
            for shot_type, band in (bands or {}).items():
                ok = (isinstance(band, (list, tuple)) and len(band) == 2
                      and 0.0 <= float(band[0]) < float(band[1]) <= 1.0)
                if not ok:
                    err("CFG_217", f"guard.size_bands.{kind}.{shot_type}",
                        f"景别区间必须是 [lo, hi] 且 0≤lo<hi≤1（当前 {band}）")
        # --- v1.6 D2（FR-B3）：节奏编译段。CFG_020–023 与 210–217 已被占用，
        # 顺延到 218 / 219。---
        #: 延迟导入：beats → motion.model → cinema → contracts.enums 这条链会与
        #: ``contracts/__init__ → config`` 成环（模块顶层 import 会当场炸），
        #: 校验只发生在运行期，函数体内导入即可。
        from .beats import PACE_VALUES
        from .rhythm import PACING_PROFILES
        if str(self.rhythm.pacing_profile) not in PACING_PROFILES:
            err("CFG_218", "rhythm.pacing_profile",
                f"未知节奏档案 {self.rhythm.pacing_profile!r}；"
                f"合法值 {sorted(PACING_PROFILES)}")
        multipliers = self.rhythm.pace_frame_multiplier
        if not isinstance(multipliers, dict) or set(multipliers) != set(PACE_VALUES):
            err("CFG_219", "rhythm.pace_frame_multiplier",
                f"节奏帧长倍率表必须恰好包含 {'/'.join(PACE_VALUES)} 三档"
                f"（当前 {multipliers!r}）")
        else:
            for pace, value in multipliers.items():
                if (isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or float(value) <= 0.0):
                    err("CFG_219", f"rhythm.pace_frame_multiplier.{pace}",
                        f"帧长倍率必须为正数（当前 {value!r}）")
        if self.rag.top_k <= 0:
            err("CFG_007", "rag.top_k", "检索条数必须为正整数")
        if self.orchestration.max_repair_attempts < 0:
            err("CFG_008", "orchestration.max_repair_attempts", "修复次数不能为负")
        if self.orchestration.react_max_steps < 0:
            err("CFG_009", "orchestration.react_max_steps", "ReAct 步数不能为负")
        # --- 决策 3（§7.1）：v1.2 的编排范式是四段式；react_only 是 v1.0 的
        # 旧范式，驱动器并未实现它。与其静默忽略这个配置项，不如明确报错。
        if self.orchestration.mode is OrchestrationMode.REACT_ONLY:
            err("CFG_013", "orchestration.mode",
                "v1.2 使用四段式编排（plan_structured）；react_only 是 v1.0 的"
                "旧范式，本版本未实现，请改为 plan_structured")
        if self.budget.max_cost_usd <= 0:
            err("CFG_010", "budget.max_cost_usd", "费用上限必须为正数")
        if self.budget.max_wall_minutes <= 0:
            err("CFG_011", "budget.max_wall_minutes", "时间上限必须为正数")
        if int(self.budget.max_llm_calls_ceiling) < 8:
            err("CFG_015", "budget.max_llm_calls_ceiling",
                f"单场静态额度下限不得小于 8（当前 "
                f"{self.budget.max_llm_calls_ceiling}）；0 = 不限的语义由 "
                f"CLI --max-llm-calls 表达，不要在这里写 0")
        if int(self.orchestration.max_shots) < 0:
            err("CFG_016", "orchestration.max_shots",
                f"镜数上限不能为负（当前 {self.orchestration.max_shots}）；"
                f"0 表示不限")
        if int(self.rag.plan_prefetch_tokens) <= 0:
            err("CFG_017", "rag.plan_prefetch_tokens",
                f"整场预取预算必须为正数（当前 "
                f"{self.rag.plan_prefetch_tokens}）")
        if str(self.rag.cases_backend) not in ("lightrag", "hybrid", "off"):
            err("CFG_018", "rag.cases_backend",
                f"只能是 lightrag / hybrid / off（当前 "
                f"{self.rag.cases_backend!r}）")
        if int(self.rag.extract_concurrency) < 1:
            err("CFG_019", "rag.extract_concurrency",
                f"抽取并发必须 ≥ 1（当前 {self.rag.extract_concurrency}）；"
                f"1 = 完全串行")

        # --- v1.5 §7（P2-T5）：规则包条数上限与可选 VLM 评审外回路 ---
        rule_top_k = self.rag.rule_top_k
        if (isinstance(rule_top_k, bool)
                or not isinstance(rule_top_k, int)
                or not (3 <= rule_top_k <= 8)):
            err("CFG_020", "rag.rule_top_k",
                f"规则包条数上限必须是 3–8 的整数（当前 {rule_top_k!r}）")
        vlm_max_shots = self.vlm_review.max_shots
        if (isinstance(vlm_max_shots, bool)
                or not isinstance(vlm_max_shots, int)
                or vlm_max_shots < 0):
            err("CFG_021", "vlm_review.max_shots",
                f"VLM 评审镜数上限必须是 ≥ 0 的整数"
                f"（当前 {vlm_max_shots!r}）；0 表示不限")
        # --- v1.5 §7（P6-T2）：Best-of-N 的候选数 ---
        draft_candidates = self.orchestration.draft_candidates
        if (isinstance(draft_candidates, bool)
                or not isinstance(draft_candidates, int)
                or not (1 <= draft_candidates <= 5)):
            err("CFG_022", "orchestration.draft_candidates",
                f"每镜候选数必须是 1–5 的整数（当前 {draft_candidates!r}）；"
                f"1 = 现状（每镜一次调用）")

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
        if not _is_hex_color(self.character.eye_color):
            # 非法颜色会被 hex_to_rgb 静默回退成白色——"黑色的眼睛"变成白色，
            # 用户却看不到任何提示。宁可启动前就报错。
            err("CFG_204", "character.eye_color",
                f"眼睛颜色必须是 #RRGGBB（当前 {self.character.eye_color!r}）")
        if str(self.dialogue.timing_source) not in ("script_first", "engine"):
            err("CFG_205", "dialogue.timing_source",
                f"只能是 script_first 或 engine"
                f"（当前 {self.dialogue.timing_source!r}）")
        if self.dialogue.declared_tolerance_s < 0:
            err("CFG_206", "dialogue.declared_tolerance_s",
                "容差不能为负（单位：秒）")
        for field_name, value in (("label_color", self.character.label_color),
                                  ("label_stroke_color",
                                   self.character.label_stroke_color)):
            if not _is_hex_color(value):
                err("CFG_207", f"character.{field_name}",
                    f"必须是 #RRGGBB（当前 {value!r}）")
        if self.character.label_min_pixels <= 0:
            err("CFG_208", "character.label_min_pixels", "可读下限必须为正数")
        if self.character.label_pixels < self.character.label_min_pixels:
            err("CFG_209", "character.label_pixels",
                "目标字号不得小于可读下限")
        if self.brief.max_tokens <= 0:
            err("CFG_210", "brief.max_tokens",
                f"SceneBrief 的注入上限必须为正数"
                f"（当前 {self.brief.max_tokens}）")
        if int(self.crowd.max_instances) < 0:
            err("CFG_211", "crowd.max_instances",
                f"群众实例上限不能为负（当前 {self.crowd.max_instances}）")
        if self.crowd.height <= 0:
            err("CFG_212", "crowd.height",
                f"群众身高必须为正数（当前 {self.crowd.height}）")
        if str(self.crowd.mode) not in CROWD_MODES:
            err("CFG_213", "crowd.mode",
                f"只能是 {'/'.join(CROWD_MODES)}（当前 {self.crowd.mode!r}）")
        # --- v1.4 §2.1/§2.2：角色比例与头顶留白策略 ---
        ratio_sum = (float(self.character.head_ratio)
                     + float(self.character.torso_ratio)
                     + float(self.character.leg_ratio))
        if abs(ratio_sum - 1.0) > 1e-6:
            err("CFG_303", "character.head_ratio",
                f"头/躯干/腿三段比例之和必须为 1.0（当前 {ratio_sum:.6f}）")
        for name, value in (("head_ratio", self.character.head_ratio),
                            ("torso_ratio", self.character.torso_ratio),
                            ("leg_ratio", self.character.leg_ratio)):
            if float(value) <= 0:
                err("CFG_304", f"character.{name}",
                    f"比例必须为正数（当前 {value}）")
        if float(self.character.total_height) <= 0:
            err("CFG_305", "character.total_height",
                f"总身高必须为正数（当前 {self.character.total_height}）")
        if float(self.character.eye_dx) <= 0:
            err("CFG_306", "character.eye_dx",
                f"眼睛水平偏移必须为正数（当前 {self.character.eye_dx}）")
        if str(self.framing.headroom_policy) not in ("board", "cinematic"):
            err("CFG_302", "framing.headroom_policy",
                f"只能是 board / cinematic（当前 "
                f"{self.framing.headroom_policy!r}）")
        # --- v1.4 §2.1 CFG_301：profile 推导值必须与引擎里的硬编码一致 ---
        from ..cinema.anchor import CharacterProfile, NECK_GAP_TOLERANCE

        profile = CharacterProfile(
            total_height=float(self.character.total_height),
            head_ratio=float(self.character.head_ratio),
            torso_ratio=float(self.character.torso_ratio),
            leg_ratio=float(self.character.leg_ratio),
            eye_r=float(self.character.eye_r),
            eye_dx=float(self.character.eye_dx),
            eye_protrusion=float(self.character.eye_protrusion),
            neck_gap=float(self.character.neck_gap),
        )
        if abs(profile.neck_gap_error()) > NECK_GAP_TOLERANCE:
            err("CFG_301", "character.neck_gap",
                f"头球中心与躯干顶的间隙偏离相切 "
                f"{profile.neck_gap_error():+.6f}（容差 "
                f"±{NECK_GAP_TOLERANCE}）")
        try:
            profile.eye_offset()
        except ValueError as exc:
            err("CFG_301", "character.eye_protrusion", str(exc))
        # 引擎里的取景常量必须等于 profile 的推导值——否则"配置改了、相机
        # 还在按旧身高取景"，而且**不会有任何测试变红**。
        try:
            from ..cinema import framing as framing_module

            if abs(float(framing_module.SUBJECT_HEIGHT)
                   - profile.total_height) > 1e-6:
                err("CFG_301", "character.total_height",
                    f"cinema/framing.py 的身高常量 "
                    f"{framing_module.SUBJECT_HEIGHT:.4f} 与 profile "
                    f"{profile.total_height:.4f} 不一致")
            if abs(float(framing_module.EYE_Z) - profile.eye_z) > 1e-6:
                err("CFG_301", "character.head_ratio",
                    f"cinema/framing.py 的眼睛高度 "
                    f"{framing_module.EYE_Z:.4f} 与 profile "
                    f"{profile.eye_z:.4f} 不一致")
        except Exception:  # noqa: BLE001 - 取景模块不可用时不该让配置报错
            pass
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
