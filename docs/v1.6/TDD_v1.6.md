# BlockDirector v1.6 技术设计文档（TDD）

| 项 | 值 |
|---|---|
| 版本 | v1.6（草案） |
| 日期 | 2026-10-08 |
| 配套 | `PRD_v1.6.md`（需求/判据）、`技术方案_v1.6.md`（选型理由） |
| 读者 | 执行者（DeepSeek v4.1 flash）与评审者（用户）。**所有接口在此钉死；任务卡只引用本文件编号，不重新发明接口** |
| 修订 | **v1.6.1（2026-10-08 查漏补缺）**：遮罩通道机制修正（逐对象材质槽 + 深度 pass 同引擎，不用 Workbench / `material_override`）；规则表去掉 R020，改为 R001 判定输入改造（编号/级别不动）；`E_CAST_001`/`E_DELIVER_002` 改"角色表成员资格"判定（`char_001` 是合法内部 id）；`scene_built` 增 `reason` 字段（D-08 根因已查明）<br>**v1.6.2（2026-10-08）**：D-19 落点——`label_baking.py` 进模块表；`labels.adaptive_sampling`/`labels.fullframe_verify` 配置段；`label_overlap_report` 事件；`test_label_fullframe.py` 测试<br>**v1.6.3（2026-10-08 二次自审）**：景别区间表拆成头部/全身两种口径并修正语法（原表混用两种量且 MLS 行不是合法 tuple）；`jump_cut_risk` 严重度与 PRD 统一为 warning；§6 配置补齐 `jump_*`/`size_bands` 键（与 §4.1 名单逐键一致）；R001 行补"事件码 `E_AXIS_001` 不变"；§8 测试清单补齐 12 个此前只在任务卡里出现的测试文件 |

---

## 1. 红线（每张任务卡开头都要复述）

1. `block_director/contracts/`、`block_director/utils/`、`block_director/cinema/`、新增的纯层模块**禁止 import bpy**。
2. 一切 bpy 调用过 `utils/threading_guard.py::@main_thread_only`。
3. 改 `contracts/config.py` 后必跑 `python tools/gen_specs.py`，`specs/config.default.yaml` 不许手改。
4. 冻结几何不动：总高 1.70、头球相切（`cinema/anchor.py` 是唯一推导源）。
5. 验收判据数值不动：`PASS_SCORE = 70`、R001–R019 语义、知识层门①–⑩。
6. `.ps1` ASCII-only；`$ErrorActionPreference = 'Continue'` + 显式 `$LASTEXITCODE`。
7. 新事件类型必须登记进 `contracts/audit.py` 的事件契约；新告警/新字段必须有 serde 往返测试。
8. `python -m pytest` 全绿才算完成；headless 测试走 `tools/blender_tests/`。

## 2. 模块清单（新增 ▲ / 修改 ●）

| 模块 | 变化 | 职责 |
|---|---|---|
| `contracts/rhythm.py` | ▲ | 节奏闭集与 DTO：`CURVE_VALUES`、`PACING_PROFILES`、`RhythmArc`、`ShotRhythm` |
| `contracts/guard.py` | ▲ | 视锥告警 DTO：`GuardWarning`、`Severity`、`Confidence`、`GUARD_SCHEMA_VERSION` |
| `contracts/elements.py` | ▲ | 元素登记表 DTO：`ElementRegistry`、`Element` |
| `contracts/beats.py` | ● | `ShotBeat` 增 `curve: str = "smooth"`；增 `ambient` 动词通道（D-17） |
| `contracts/brief.py` | ● | `SceneBrief` 增 `rhythm_arc: List[Dict]`（FR-B1） |
| `contracts/config.py` | ● | 新增 `llm.timeout_s`、`guard.*`、`rhythm.*`、`delivery.mask_pass`、`delivery.reference_cards` 段（§7） |
| `contracts/tools.py` | ● | `hand_to.toward` 改 union schema；工具 description 补坐标系/单位/闭集（D-03） |
| `contracts/audit.py` | ● | 新事件：`guard_warning`、`guard_verdict`、`retry_ladder`、`rhythm_reading` |
| `cinema/frustum_metrics.py` | ▲ | 纯层：2D 包围盒序列 → 六度量 + 曲线事件 + `GuardWarning` 列表 |
| `cinema/framing.py` | ● | CU/ECU 景别改像素可测约束反解（D-12）；求解后回读函数 `readback_shot_size()` |
| `cinema/axis.py` | ● | 轴线判定改银幕左右序状态机输入（D-14/FR-C6） |
| `cinema/lighting.py` | ● | `key_direction` 补 `side` 预设变体；接触阴影设置（D-18） |
| `layer3_engine/frustum_sampler.py` | ▲ | bpy 层：逐帧采样 → 纯层；BVH 可见比例 |
| `layer3_engine/label_baking.py` | ● | 采样步长自适应 + 二维松弛 + 烘焙后全帧自检（D-19） |
| `layer3_engine/character_system/character_factory.py` | ● | `_add_rounded_box_body` → `_add_cylinder_body`（FR-E） |
| `layer3_engine/scene_executor.py` | ● | 环境方位闭集解析 + 最小骨架 + 失败 finding（FR-A1/D-10） |
| `layer3_engine/shot_auditor.py` | ● | 审核携带 `GuardWarning[]`；节奏读数挂载 |
| `layer5_orchestrator/understand.py` | ● | `rhythm_arc` schema + `deterministic_rhythm()` 回退（`E_BRIEF_002`） |
| `layer5_orchestrator/planner.py` | ● | 计划提示注入：节奏档案 + 同层时间轴占用表（D-16） |
| `layer5_orchestrator/editor.py` | ● | B1 schema 增 `curve`；起草提示带占用表 |
| `layer5_orchestrator/beat_compiler.py` | ● | `pace × curve` → 帧长倍率 + 插值模式表（FR-B3） |
| `layer5_orchestrator/repair.py` | ● | 修复提示注入告警证据 + 参数化 reframe 菜单（FR-C5） |
| `layer5_orchestrator/driver.py` | ● | 重试阶梯（D-02）；`llm_timeout_s` 从配置读（D-01）；撞线保留产物（D-09） |
| `layer5_orchestrator/retry_ladder.py` | ▲ | 纯层：阶梯状态机（超时 → 瘦身重试 → 降级） |
| `layer3_engine/cinema_engine/camera_motion.py` | ● | 写关键帧时按 `curve` 设插值（FR-B4） |
| `layer7_ui/run_settings.py` + `panel_main.py` | ● | 超时、guard 阈值档、遮罩/定妆卡开关（D-01） |
| `layer8_delivery/mask_pass.py` | ▲ | 逐元素遮罩渲染（FR-A3） |
| `layer8_delivery/reference_cards.py` | ▲ | 角色定妆卡渲染（FR-A5） |
| `delivery/manifest.py` | ● | 导出 `elements.json`；`shots.json` 增 `needs_review`、`rhythm`、`elements_in_frame` |
| `delivery/prompts.py` | ● | 元素表头 + 表外名字对拍校验（FR-A4） |
| `layer3_engine/checkpoint_manager.py` | ● | 覆盖 B1/审核阶段 + `--resume`（D-09） |
| `tools/diagnose_composition.py` | ▲ | 零 LLM 构图归因（D-04） |

## 3. 契约设计

### 3.1 `contracts/rhythm.py`（纯）

```python
CURVE_VALUES: tuple = ("linear", "smooth", "ease_in", "ease_out", "sharp")
PACING_PROFILES: Dict[str, Dict[str, Any]] = {
    "contemplative": {"asl_band_s": (8.0, 12.0)},
    "standard":      {"asl_band_s": (4.0, 8.0)},
    "urgent":        {"asl_band_s": (2.0, 4.0)},
}
CURVE_TO_INTERPOLATION: Dict[str, str] = {   # bpy 枚举名，纯层只存字符串
    "linear": "LINEAR", "smooth": "BEZIER", "ease_in": "BEZIER",
    "ease_out": "BEZIER", "sharp": "LINEAR",
}
#: ease_in/ease_out 与 smooth 的区别在"帧长倍率 + 手柄倾向"，由编译层实现；
#: sharp = 前 15% 帧完成 85% 位移（蓄-发-收的"发"），编译层折帧实现，不靠 fcurve 手柄。

@dataclass
class ShotRhythm:
    tension: int = 3            # 1–5
    pace: str = "normal"        # 沿用 PACE_VALUES
    curve: str = "smooth"       # CURVE_VALUES

@dataclass
class RhythmArc:
    shot_id: str
    tension: int
    note: str = ""
```

不变量：`curve_problems(curve)` 校验函数复刻 `action_param_problems` 的写法；非法值列问题、不猜。

### 3.2 `contracts/guard.py`（纯）

```python
GUARD_SCHEMA_VERSION = "guard/v1"

class Severity(str, Enum):    # error 必须处理 / warning 由 LLM 裁决 / info 默认不打扰
    ERROR = "error"; WARNING = "warning"; INFO = "info"

class Confidence(str, Enum):
    HIGH = "high"; LOW = "low"

@dataclass
class GuardWarning:
    shot_id: str
    frame_range: Tuple[int, int]
    type: str                 # 闭集见下
    subject: str              # 角色/元素 id；"scene" 表示镜头级
    evidence: Dict[str, Any]  # {实测值, 阈值/区间, ...} 数值必须可 JSON
    severity: Severity
    confidence: Confidence
    declared_intent: str = ""
    suggestion_hint: str = ""

WARNING_TYPES: tuple = (
    "subject_out_of_frame",   # 完全出画（非剧本设计）→ error, high
    "subject_behind_camera",  # z<0 → error, high
    "subject_not_visible",    # 包围盒在画内但可见比例 0 → error, high
    "edge_clip",              # 裁切率超阈 → warning（包围盒虚胖 ⇒ low）
    "occlusion",              # 主体可见比例 <0.8 且未声明前景遮挡 → warning
    "framing_too_tight",      # 头部/主体占比高于景别区间 → warning, high
    "framing_too_loose",      # 低于区间 → warning, high
    "headroom_off",           # 留白出区间 → warning
    "lead_room_short",        # 朝向侧留白 <0.05 → warning
    "thirds_deviation",       # → info
    "size_drift",             # 镜内景别漂移 >±15% → warning
    "sudden_jump",            # 两帧占比跳变超阈 → warning, high
    "unplanned_exit",         # 出画事件与声明时间 diff 超阈 → warning
    "jump_cut_risk",          # 相邻镜占比差<10% 且视角差<30° → warning（PRD FR-C6；由 LLM 裁决）
    "axis_screen_order",      # 银幕左右序翻转（无中性镜桥接）→ error
    "pace_monotony",          # 全片镜长相同 → info
)
```

### 3.3 `contracts/elements.py`（纯）

```python
@dataclass
class Element:
    id: str              # 稳定 id：角色=角色表名；道具=prop_id；环境件=env_<方位>_<序号>
    kind: str            # "character" | "prop" | "environment"
    label: str           # 显示名（进 prompts.md 与遮罩色表）
    color_hex: str       # 角色=cast 色；环境=灰阶；遮罩纯色同源
    shape: str = ""      # prop 的形状闭集；character 固定 "capsule_q"（圆柱身+头球）
    first_shot: str = ""

@dataclass
class ElementRegistry:
    elements: List[Element]
    def by_id(self) -> Dict[str, Element]: ...
    def to_dict(self) / from_dict(cls, data)   # serde 往返；排序按 id，保证确定性
```

### 3.4 环境方位闭集（`contracts/brief.py` 扩展）

```python
SPACE_DIRECTIONS: tuple = ("front", "back", "left", "right", "above", "ground")
SPACE_DISTANCES: tuple = ("near", "mid", "far")   # near≤4m / mid≤10m / far>10m（相对场景中心）
# SceneBrief.environment[]（新增，与 space[] 并列）：
#   {label, direction: SPACE_DIRECTIONS, distance: SPACE_DISTANCES, size: ("s","m","l"), mood: str}
# space[] 保持原义（角色间关系）；环境件一律走 environment[]。
```

场景构建器映射表（`scene_executor.py` 内）：`(direction, distance) → 坐标偏移` 一张确定性表；`size` → 尺寸档表。解析不出 ⇒ finding + 带回计划重问（不再静默跳过）。

### 3.5 工具 schema 修订（D-03）

* `hand_to.toward`：`oneOf[ number, {"character": str}, {"point": [float,float,float]} ]`；编译层归一到数字/锚点。
* 所有动作工具的 `description` 由 `tool_schema.py` 自动生成，模板：「坐标系：世界系，米，Z 向上。`speed` 闭集：walk/run。允许键表：…。正例：…。反例：…」。闭集内容**导入** `motion/model.py::action_param_domains()`，不手抄。
* 修复接口 id 归一：`normalize_subject_id(raw, shot_characters, scene_ids)`：精确命中角色表名 → 原名；`char_0N` 形 → 按 SceneContext 映射到本镜角色；都不中 → 错误信息回显合法值列表。

### 3.6 审计事件（`contracts/audit.py`）

| 事件 | 字段 | 触发 |
|---|---|---|
| `guard_warning` | shot_id, warnings[]（DTO 全量）, frames_sampled | 审核/终审采样后 |
| `guard_verdict` | shot_id, warning_type, accepted: bool, reason, fix_action | LLM 裁决后 |
| `retry_ladder` | stage（"slim_retry"/"degrade"）, shot_id, elapsed_s | 重试阶梯每步 |
| `rhythm_reading` | asl_s, duration_cv, monotony: bool, jump_cut_risks: int | 计划确认后一次 |

## 4. 引擎设计要点

### 4.1 `cinema/frustum_metrics.py`（纯层，核心）

输入：`List[FrameSample]`，`FrameSample = (frame, subject, SubjectBox, visible_ratio, behind_camera)`（`SubjectBox` 复用 `cinema/composition.py` 现有 dataclass，不新造）。
输出：`List[GuardWarning]`。
函数：

```python
def frame_metrics(box: SubjectBox, visible: float, declared: DeclaredShot) -> Dict[str, float]
def detect_events(samples: List[FrameSample], cfg: GuardConfig) -> List[GuardWarning]
def compare_with_intent(samples, declared: DeclaredShot, cfg) -> List[GuardWarning]
def cut_level_checks(shots: List[ShotSummary], cfg) -> List[GuardWarning]   # 轴线序/跳切/景别序列
def aggregate(warnings: List[GuardWarning]) -> List[GuardWarning]           # 同镜同类时间聚合
```

阈值全在 `GuardConfig`（config.guard 段的运行时形）：`edge_clip_max=0.10`、`lead_room_min=0.05`、`sustain_frames=12`、`size_drift=0.15`、`jump_ratio=0.25`、`jump_cut_angle_deg=30.0`、`jump_cut_size_diff=0.10`、`occlusion_warn=0.20`（**§6 的 yaml 必须与这份名单逐键一致**）。

**景别区间表**（D-12 的"同一把尺"）。先钉死度量口径，再给表——这张表测的是两个不同的量，混在一列就会自相矛盾：

* 近景系列（MCU/CU/ECU）：量 **头部占画高比**（头顶到下颌的屏幕高度 ÷ 画面高度）；
* 中远景系列（MS/MLS/LS/ELS）：量 **全身占画高比**（脚底到头顶的屏幕高度 ÷ 画面高度）。

```python
# 近景系列：头部占画高比
HEAD_HEIGHT_BANDS = {"MCU": (0.45, 0.60), "CU": (0.55, 0.75), "ECU": (0.75, 1.0)}
# 中远景系列：全身占画高比
BODY_HEIGHT_BANDS = {"MS": (0.55, 0.70), "MLS": (0.70, 0.88), "LS": (0.35, 0.60), "ELS": (0.15, 0.35)}
```

CU 的 55–75%（头部口径）即 PRD D-12 的判据来源；MLS 上限 0.88 由冻结几何反解（头顶留白 ≥8% + 脚下余量 6% ⇒ 全身最高占 0.86，取 0.88 为设计上限）。**以上数值都是初稿**：卡 B4 落地时以合成场景的实测标定为准并回填本表；表进 config（`guard.size_bands`），不进代码常量。

### 4.2 `layer3_engine/frustum_sampler.py`（bpy）

```python
@main_thread_only
def sample_shot(shot_id, step: int = 4, extra_frames: Iterable[int] = ()) -> List[FrameSample]
```

* `scene.frame_set(f)` → `evaluated_depsgraph_get()` → 每主体 `evaluated_get(dg).matrix_world` → 八角点 `world_to_camera_view` → z<0 归 `behind_camera`。
* 可见比例：包围盒表面采样 N=9 点，`scene.ray_cast(dg, cam_pos, dir)` 命中距离 vs 目标距离，容差 0.05 m。
* `extra_frames` = 相机/主体关键帧 ± 1。性能预算：100 帧 < 5 s（进 headless 测试断言）。

### 4.3 轴线状态机（`cinema/axis.py` 改造）

```python
@dataclass
class ScreenOrderState:
    left_to_right: Tuple[str, ...]     # 当前画面左→右的角色序
    facing_sign: Dict[str, int]        # -1/0/+1
def update_order(state, samples) -> ScreenOrderState
def axis_violation(prev: ScreenOrderState, cur: ScreenOrderState, bridge_ok: bool) -> Optional[GuardWarning]
```

`bridge_ok`：中间隔了中性镜（双方 facing_sign≈0）或骑轴镜 ⇒ 合法换侧。R001 规则改为消费此判定；`axis_note` 仅展示。

### 4.4 节奏编译（`beat_compiler.py` 扩展）

```python
PACE_FRAME_MULTIPLIER = {"slow": 1.35, "normal": 1.0, "brisk": 0.7}   # 作用于 BEAT_DURATION_TABLE 与走位估帧
CURVE_PROFILE = {  # 编译层把"曲线词"落实为 (插值模式, 位移时间轮廓)
    "linear":   ("LINEAR", None),
    "smooth":   ("BEZIER",  None),
    "ease_in":  ("BEZIER",  "slow_start"),   # 前 20% 帧位移 ≤10%
    "ease_out": ("BEZIER",  "slow_end"),     # 末 20% 帧位移 ≤10%
    "sharp":    ("LINEAR",  "burst"),        # 前 15% 帧完成 85%
}
```

走位类：`walk_to/run_to` 的根位移关键帧按轮廓插中间帧（确定性：同一输入同一帧表）。运镜类：`camera.movements[].curve` 原样传到 `cinema_engine/camera_motion.py`，写关键帧时查 `CURVE_TO_INTERPOLATION`。

### 4.5 重试阶梯（`layer5_orchestrator/retry_ladder.py`，纯状态机）

```python
@dataclass
class RetryPolicy:
    max_attempts: int = 2          # 同一提示最多 2 次
    slim_on_timeout: bool = True   # 第 2 次用瘦身包（去 RAG 三栏，留该镜声明+审计发现）
    degrade_after: bool = True     # 仍失败 → shot_degraded，不再第 3 次
def next_step(history: List[CallOutcome], policy: RetryPolicy) -> str   # "retry_same" | "retry_slim" | "degrade"
```

驱动在 repair/react/plan 三处统一调用；每步记 `retry_ladder` 事件。降 `reasoning_effort` 不在自动阶梯里（用户显式开关 `llm.low_effort_on_timeout`，默认 false）。

### 4.6 断点续跑（D-09）

`checkpoint_manager` 现有能力核对后扩展到：B1 每镜起草成功、每镜审核/修复终态（通过/降级）都落 checkpoint；墙钟撞线 → 驱动收尾时导出**已完成镜**的交付物 + `resume_state.json`；`--resume` 读 checkpoint 跳过终态镜（零 LLM 调用）。合成测试：跑到 shot_003 杀进程，`--resume` 后 `llm_request` 计数只对 shot_004+ 增长。

## 5. 交付包新结构（layer8_delivery / delivery）

```
export/<run>/
  blockout_full.mp4 / shots/shot_00X.mp4        # 现状
  first_frames/                                 # 现状
  depth/shot_00X/                               # 现状
  masks/shot_00X/                               # FR-A3（可选，默认开）
  reference/characters/<name>.png               # FR-A5（可选，默认开）
  elements.json                                 # FR-A2
  shots.json        # +needs_review / +rhythm / +elements_in_frame
  prompts.md        # 头部"元素表" + 稳定 token 引用
  camera_traj.json  # 现状
  README.md         # +节奏段 +needs_review 汇总段 +mask/深度归一化说明
```

遮罩渲染参数（**v1.6.1 修正：不是 Workbench，也不是 `view_layer.material_override`**——override 整场景只有一份材质，做不了逐对象分色）：与深度 pass **同引擎**（`depth_pass.py` 用的 EEVEE 系材质节点路线）、`film_transparent=False`、标签与辅助件 `hide_render=True`、**逐对象材质槽**挂纯色自发光材质（每元素一份 `BD_Mask_<element_id>`，色表 = `elements.json`）、环境件统一 `#808080`、世界覆盖纯黑。渲染前快照材质槽与世界、渲染后恢复（快照/恢复纪律照抄 `depth_pass.py:109/137` 的写法）。帧范围与该镜 mp4 完全一致（复用 `cinema/schedule.py` 的帧表，不另算）。

## 6. 面板与配置（`contracts/config.py` 新增）

```yaml
llm:
  timeout_s: 300            # 面板可设；慢通道建议 ≥600（文案提示）
  low_effort_on_timeout: false
guard:
  enabled: true
  preset: "standard"        # strict / standard / loose 三档阈值组；下面列的数值 = standard 档，另两档在其上收紧/放宽，档位表同样进 config
  sample_step: 4
  sustain_frames: 12
  edge_clip_max: 0.10
  lead_room_min: 0.05
  size_drift: 0.15
  jump_ratio: 0.25
  jump_cut_angle_deg: 30.0
  jump_cut_size_diff: 0.10
  occlusion_warn: 0.20
  size_bands:               # §4.1 景别区间表（初稿值以卡 B4 实测标定为准）
    head: {MCU: [0.45, 0.60], CU: [0.55, 0.75], ECU: [0.75, 1.0]}
    body: {MS: [0.55, 0.70], MLS: [0.70, 0.88], LS: [0.35, 0.60], ELS: [0.15, 0.35]}
rhythm:
  enabled: true
  pacing_profile: "standard"
  pace_frame_multiplier: {slow: 1.35, normal: 1.0, brisk: 0.7}
delivery:
  mask_pass: true
  reference_cards: true
labels:
  adaptive_sampling: true     # D-19：标签相对屏幕速度大或插值期检出重叠时局部加密，直至每帧
  fullframe_verify: true      # 烘焙后全帧自检，重叠帧写 label_overlap_report 事件
```

每加一个键：先过 `AppConfig.validate()` 的既有模式（CFG_0xx 新错误码：CFG_021 非法 preset、CFG_022 非法 timeout、CFG_023 非法阈值区间），再跑 `tools/gen_specs.py`。

## 7. 错误码与规则

| 编号 | 语义 | 级别 |
|---|---|---|
| `E_BRIEF_002` | rhythm_arc 两次理解失败，回退确定性推导 | 事件 |
| `E_GUARD_001` | 采样失败（depsgraph/投影异常） | 事件 |
| `E_ENV_001` | 环境锚点闭集解析失败（finding，带回计划） | finding |
| `E_CAST_001` | 计划 characters 含表外 id（占位 id；成员资格判定，非正则——`char_001` 形是 `cast.py::next_character_id` 分配的合法内部 id） | **error，重问该镜** |
| `E_DELIVER_002` | 交付自检发现**角色表外** id / prompts 表外名 | **拒绝导出** |
| R015 | 无 `declared_breaks` 的声明景别改写 | warning → **error** |
| R001（改造，**不新增规则编号**） | 判定输入从"两人连线 + axis_note 文字"换成银幕左右序状态机（§4.3）；越轴仍是 error，级别与编号不变，**事件码 `E_AXIS_001` 不变**（G2 的验收读数才可对比）；`axis_note` 降级为展示文本 | error（不变） |
| `scene_built`（字段扩展） | 增 `reason: initial / repair_rebuild / rollback_rebuild`（D-08：第二条是修复回路就地重建，设计内行为，补可观测性） | 事件字段 |
| `label_overlap_report` | 标签烘焙后全帧自检：每帧最大两两交叠率 + 重叠帧清单（D-19） | 事件（交付 README 汇总） |

## 8. 测试计划（新增测试文件清单）

| 文件 | 关键断言 |
|---|---|
| `tests/test_rhythm_contracts.py` | 闭集校验、非法值列问题、serde 往返 |
| `tests/test_guard_contracts.py` | DTO serde、WARNING_TYPES 闭集与 Severity 映射合法 |
| `tests/test_frustum_metrics.py` | 六度量公式（合成 SubjectBox）、四类事件检测、聚合合并、瞬时越界不告警 |
| `tests/test_axis_screen_order.py` | 状态机更新、越轴判定、中性镜桥接 |
| `tests/test_beat_compiler_curve.py` | pace×curve → 帧长倍率与插值表；ease_out 末 20% 帧位移 ≤10%；sharp 前 15% ≥85% |
| `tests/test_retry_ladder.py` | 状态机路径：retry_same → retry_slim → degrade；不重试到死 |
| `tests/test_elements_registry.py` | 确定性（两跑逐字节相同）、by_id、serde |
| `tests/test_prompts_elements.py` | 表外名字判 error |
| `tests/test_env_anchors.py` | 方位闭集映射表确定性；非法值 finding；最小骨架三件套存在性（纯层部分） |
| `tests/test_cast_hard_check.py` | 表外 id error + 重问；合法 `char_001` 形已分配 id 放行（防误杀）；交付自检按成员资格拒绝导出 |
| `tests/test_framing_readback.py` | CU 占比落 55–75% + 头顶留白 3–10%；回读不一致自动调距离档 |
| `tests/test_tool_schema_examples.py` | description 含坐标系/闭集/正反例；hand_to union schema 三种合法形 |
| `tests/test_config_v16.py` | 新配置段校验、CFG_021–023、gen_specs 同步 |
| `tests/test_rule_levels.py`（卡 A3） | R015 无破例 ⇒ error、有 `declared_breaks` ⇒ 原级别 |
| `tests/test_tool_bindings_env.py`（卡 A3） | 非在场主体的 `character_action` 被拒，错误文案列出在场角色并指引 vfx 字段 |
| `tests/test_needs_review.py`（卡 A5） | `request_self_review` 登记 ⇒ `shots.json` 该镜 `needs_review: true` + README 汇总段 |
| `tests/test_scene_built_reason.py`（卡 A6） | 初始构建 `reason=="initial"`；修复重建/回滚重建各归各档 |
| `tests/test_repair_prompt.py`（卡 B4） | 修复提示含告警实测数值与动作菜单四项；`accept` 必记 `guard_verdict` |
| `tests/test_brief_environment.py`（卡 C1） | `environment[]` 闭集校验、非法值列问题、serde 往返 |
| `tests/test_sdl_v16.py`（卡 C1） | `environment[]`/`rhythm_arc` 落盘/读回/迁移；旧 bdproj 迁移无损 |
| `tests/test_understand_rhythm.py`（卡 D1） | 两次失败回退 `deterministic_rhythm` 并记 `E_BRIEF_002`；回退只用台词密度+走位距离 |
| `tests/test_rhythm_reading.py`（卡 D3） | ASL/方差/单调性读数正确；info 级不触发 repair；跳切风险只计数（告警归 FR-C6） |
| `tests/test_layer_occupancy.py`（卡 F4） | 占用表纯函数：同层重叠区间正确列出；提示注入含帧区间 |
| `tests/test_lighting_presets.py`（卡 G1） | `key_direction` 三合法值各有预设命中；`side` 变体在 `LIGHT_DIRECTION_VARIANTS` 登记 |
| `tests/test_checkpoint_resume.py`（卡 F2，纯层侧） | checkpoint 覆盖 B1/审核终态；撞线保留已完成镜交付物与 `resume_state.json` |
| `tools/blender_tests/test_frustum_sampler.py` | headless：采样帧数、投影值容差、可见比例、5 s 预算 |
| `tools/blender_tests/test_cylinder_body.py` | headless：圆柱世界 AABB vs 旧圆角方体 max_delta=0.0；锚点读数不变 |
| `tools/blender_tests/test_mask_pass.py` | headless：遮罩帧数与 mp4 一致、颜色与 elements.json 一致、标签不可见 |
| `tools/blender_tests/test_checkpoint_resume.py` | 杀进程 → resume → LLM 调用计数只对未完成镜增长 |
| `tools/blender_tests/test_label_fullframe.py` | headless：全帧标签两两交叠 ≤5%（RK-2 阈值从采样帧扩到全帧）；自适应加密后重叠帧归零；`label_overlap_report` 事件写出 |
| `tools/blender_tests/test_env_skeleton.py`（卡 C2） | headless：环境骨架三件套存在、在正确 collection、`hide_render=False`；方位映射落位正确 |
| `tools/blender_tests/test_reference_cards.py`（卡 E3） | headless：每角色一张定妆卡、固定机位参数、文件命名与 `elements.json` 键一致 |

## 9. 验收矩阵（PRD 判据 → 测试/证据）

| PRD | 验收载体 |
|---|---|
| FR-A1 / D-10 | `test_env_anchors.py` + 样片重跑 `unresolved_anchor==0` + shot_001 首帧人审 |
| FR-A2 | `test_elements_registry.py` |
| FR-A3 | `test_mask_pass.py` |
| FR-A4 | `test_prompts_elements.py` |
| FR-B1 | `understand` 回退测试 + bdproj 往返 |
| FR-B2/B5 | `rhythm_reading` 事件 + README 对拍 |
| FR-B3/B4 | `test_beat_compiler_curve.py` + 运镜矩阵测试 |
| FR-C1–C4 | `test_frustum_metrics.py` + `test_frustum_sampler.py` + `guard_warning` 事件 |
| FR-C5 / D-13 | 样片重跑：audit_pass_rate ≥10/12、degraded ≤1（证据目录） |
| FR-C6 / D-14 | `test_axis_screen_order.py` + 样片重跑 E_AXIS_001 ≤2 |
| D-01/02/09 | `test_retry_ladder.py` + `test_checkpoint_resume.py` + 面板测试 |
| D-03 | `test_tool_schema_examples.py` + 样片重跑 invalid=0 |
| D-04 | `docs/evidence/<run-id>/composition_diagnosis.md` |
| D-05 | 注入审计测试（条件边不进硬栏） |
| D-11 | `test_cast_hard_check.py` |
| D-12 | `test_framing_readback.py` |
| D-15–D-18 | 规则级别测试 + 样片重跑计数 |
| D-19 | `test_label_fullframe.py` + 样片重跑全帧交叠 ≤5% + 交付包自检报告 |
| FR-E | `test_cylinder_body.py` + 全量 pytest |
