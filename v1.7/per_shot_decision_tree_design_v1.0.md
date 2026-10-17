# 每分镜决策树（per-shot decision tree）设计 v1.0

> v1.0（2026-10-18）：D1 决策树投影已合入主仓库 main（cherry-pick `a32366b`
> ＋ S1/S2/S3 冲突适配，合入 commit 见 `v1.7/PROGRESS.md` 2026-10-18 行），
> 全链证据齐备（main 树 pytest **4400 passed / 2 skipped**、per-shot Blender
> 探针 5/5、gen_specs --check OK、六视角评审六份报告落
> `E:\bd_vlm_v2\work\reviews\`），本文由草案定稿。后续改动按本仓库
> AGENTS.md 纪律另起修订记录。

> 状态：定稿（v1.0，2026-10-18）。
> v0.6（2026-10-12）：D1 代码与纯层/bpy 测试全部落地后的定稿记账——把 v0.5
> 规划中已实现的部分从「计划」改为「落地」记录（阶段 3/4b/5、opt_variables、
> 审计事件、rk9 兼容、resume 方案 B、results 整体替换），并修正 v0.5 中与
> HEAD 不符的两处风险表述（P1-2 已落地：vlm 树已含 `motion/targets.py`；
> 九类新事件已登记）。见文末「修订记录」v0.6 条目。
> v0.5（2026-10-11）：用户裁决 B（深度整合）与 D1（决策树投影）后进入
> 定稿前的自查修订，覆盖 A–X 全部缺口；见文末「v0.5 自查补丁 5」。
> 原则：剧本始终最高优先级；已被裁决的例外显式建模；不改任何判据/阈值；
> 每次投影/拒绝留审计；决策树是**单一真源**，现有 watchdog/repair 都从它导入。

> v0.4（2026-10-11）新增「数值层（连续优化）」：见 §3.5、阶段 5/6、§8.1（复用检查）。
> v0.5（2026-10-11）用户裁决后的定稿修订：§3.6 全链整合（方案 B，用户已选）、
> §3.4 轴真源与 `axis_side` 注入、§4 投影路径映射表、审计事件必有字段、
> §7 裁决状态更新；详见文末「修订记录」。
> v0.3（2026-10-11）修正：见文末「修订记录」。
> v0.2（2026-10-11）：接入点行号已按 vlm 树 HEAD（af448dd）重新核实；
> 测试计划引用 r6 run `12dadce87acc` 的 21 条 invalid 回归夹具
> （`%USERPROFILE%\Documents\BlockDirector Projects\runs\audit_log.jsonl`）。

## 1. 问题与动机（证据）

r6 终态 invalid=21（draft=2 / react=12 / repair=7；llm_error=8×402 配额耗尽，
读数作废作证，证据在 g8 复核树
`E:\bd_g8_rerun\docs\evidence\20261011-v16-g8-r6\`，**vlm 树无此目录**，
引用时以 run_id `12dadce87acc` 与审计日志为准）。其中：

- draft 只有 2 条：结构解析→B1 严格 schema→看门狗这条线已收敛；
- react（12）与 repair（7）是主要失控区间：**执行-反馈循环**里模型以自由文本
  夹带语义、事后校验才打回，修复回路再烧一次调用，且可能换个方式再越界。
- 实证被拒样本：`camera.side='side'`、`'front-right, same 180° side as shot_004'`、
  `'伊恩同侧（延续 shot_008 轴侧，不越轴）'`、`look_at.params.angle_deg`（等价键
  与 target 同框被判域拒绝）。

结论：**被动拒绝（watchdog）→ 主动投影（decision tree）**。树不解析自由文本，
只从剧本声明与已锁定求解器输出推导合法动作空间；agent 在空间内自由表达，
空间外投影到最近合法值（留审计）或显式拒绝。

## 2. 为什么“每分镜一棵树”，而不是一棵全局树

决策空间随**镜的轴关系、镜头类型、机位、角色声明**变化：

```text
shot_004（正面双人，A 在左）:
  camera.side ∈ {neutral}（正面），movement ∈ {static,dolly-in}
  look_at.target ∈ {A, B}（同框主体），禁止 cross-line
shot_008（过肩，A 右 B 左，轴已锁定）:
  camera.side ∈ {over_shoulder}（或按轴侧映射为 front_left/front_right——P1 已如此），
  movement ∈ {static, pan}
  look_at.target ∈ {A, B}，禁止跨到 shot_004 反侧
```

全局树会让“合法空间”对每镜都一样，等于没有投影；每镜树把剧本声明与轴语义
物化成该镜唯一允许的动作集合，draft/react/repair 每一轮**复用同一棵树**，
保证三轮对同一镜的语义一致。

## 3. 架构

```text
                   ┌──────────────────────────────────────────┐
剧本声明(SDL) ────▶│ per_shot_decision_tree.py（纯层，无 bpy）│
求解器输出(轴/机位)▶│  - build_tree(shot, plan, contract)      │
                   │  - project(node, proposal) → (verdict,    │
                   │    projection, reason, audit)             │
                   │  - 决策节点清单（硬规则/软规则/剧本分支）    │
                   └───────────────┬──────────────────────────┘
                                   │
          ┌────────────┬───────────┼───────────────┬──────────┐
          ▼            ▼           ▼               ▼          ▼
   B1 draft       react 工具      repair 工具    shot_schema  看门狗
  (editor)       (driver/react) (driver/repair)  (校验)      (normalize)
```

### 3.1 决策节点类型

1. **剧本硬节点（最高优先级）**：剧本已声明 → 无条件走声明分支；
   与 agent 提议冲突 → 投影/拒绝并记 `E_SCRIPT_xxx`。
2. **规则节点**：R 系列规则（轴 180°、构图门、遮挡语义…）→ 从规则真源导入，
   允许显式例外分支（空镜豁免、双人镜 MCU 组中心锚点、声明遮挡不告警）。
3. **动作空间节点**：该镜合法 action 类型 / 参数域（由运动库 + 镜头类型推导）。
4. **软建议节点**：知识检索/经验建议，只影响评分，不投影硬拒绝。

### 3.2 数据流（每镜每轮）

```text
plan/shot → build_tree() → Tree(shot_id, nodes, legal_space)
  ├─ draft:  proposal → project() → 合法值 | 投影值+审计 | 拒绝+原因
  ├─ react:  工具提议 → project()（同一棵树）
  └─ repair: 修复提议 → project()（同一棵树，引用原 invalid 记录）
```

投影永远留痕：`{original, projected, node, reason, shot_id, stage}`，
写入 `audit_log.jsonl`（新增事件类型按 §3.6.4 T 的九类最小形状，一次提议
多处越界 = 一个事件、`records[]` 多条；登记顺序纪律 `V16_EVENT_FIELDS` →
`openapi.yaml` → 测试），不吞错、不改判据。

### 3.3 代码级结构（新增纯层模块，无 bpy）

**新文件**：`block_director/layer5_orchestrator/decision_tree.py`（纯 Python，
红线：不 import bpy；可以 import `contracts/`、`motion/model.py`、
`cinema/framing.py`、`cinema/axis.py` 的纯函数）。

```
class Verdict(StrEnum):              # 投影结果三态
    ACCEPT    = "accept"             # 提议本来就在合法空间
    PROJECTED = "projected"          # 提议越界，已投影到最近合法值
    REJECTED  = "rejected"           # 提议与剧本硬约束冲突，不投影，退回

@dataclass(frozen=True)
class DecisionNode:
    key: str            # "camera.side" / "camera.lens" / "action.look_at.target" / ...
    kind: str           # script_hard / rule / action_space / soft_advice
    priority: int       # 0=最高（剧本硬节点），越大越软
    allowed: Tuple[str, ...] | None          # 闭集（合法值）
    range: Tuple[float, float] | None        # 数值域（lens / amount / t）
    reason: str         # 人类可读、进审计的原因
    source: str         # 规则/真源出处（例如 "axis_state" / "CAMERA_SIDES"）

    def __post_init__(self) -> None:
        """J：`allowed` 与 `range` 必须**恰有一个**非空（闭集键 / 数值键），
        `build_tree` 对每个节点强制校验；两键同时或同时为空是构建期错误，
        抛 `TreeBuildError`，不静默构造一棵缺判域的树。"""
        if (self.allowed is None) == (self.range is None):
            raise TreeBuildError(
                f"{self.key}: allowed 与 range 必须恰有一个非空"
                f"（allowed={self.allowed!r}, range={self.range!r}）")

@dataclass(frozen=True)
class ProjectionRecord:
    shot_id: str
    stage: str          # draft / react / repair
    node_key: str
    original: Any
    projected: Any
    verdict: Verdict
    reason: str

@dataclass
class ShotDecisionTree:
    shot_id: str
    nodes: Tuple[DecisionNode, ...]
    legal_space: Dict[str, Tuple[Any, ...]]   # 该镜合法动作空间（供提示词渲染）

def build_tree(shot: ShotPlan, plan: Plan | None, *,
               contract=None, axis_side: Optional[int] = None) -> ShotDecisionTree
def project(tree: ShotDecisionTree, proposal: Dict[str, Any],
            *, stage: str) -> Tuple[Dict[str, Any], List[ProjectionRecord]]
def render_legal_space(tree: ShotDecisionTree) -> str
```

**J（自查补丁 5）**：`DecisionNode.__post_init__` 强制 `allowed`/`range` 恰有
一个非空；`build_tree` 对所有节点统一跑该校验，任意节点两空/两有 → 
`TreeBuildError`，测试断言。

### 3.4 树的构建与投影规则（每镜一棵树）

**build_tree() 的输入**（全部是已锁定/纯计算量）：

- `shot`：该镜的 `ShotPlan`（角色、景别、声明动作、相机声明、拍点、构图、辩护）；
- `plan`：全片计划（用于 `axis_state` 的顺序状态机、环境锚点、连续性）；
- `contract`：`ShotContract`（已有 `constraint_query()` 的每镜契约，软建议注入）；
- 规则真源导入（不抄第二份）：
  - `cinema/framing.py::CAMERA_SIDES` → `camera.side` 的闭集；
  - `contracts/enums.py::MOVEMENT_TYPES` / `MOVEMENT_UNITS`（`cinema/camera_motion.py`）
    → `camera.movements[].type` 的闭集与 `amount` 单位/典型区间；
  - `motion/model.py::ACTION_PARAMS` / `ACTION_PARAM_ALIASES` / `ACTION_TYPES`
    → 动作工具与 `emit_shot_draft.actions[].params` 的键与等价键归一。
    **P1-2 差异必须先行统一**：vlm 树（HEAD `af448dd`）
    `ACTION_PARAMS["look_at"] = ("yaw_deg", "pitch_deg")`——`target` 不在合法键内；
    g8 树为 `("yaw_deg", "pitch_deg", "target")`，互斥判域在
    `motion/model.py:283-284`、`beat_compiler.py:540-541`、`editor.py:210`，
    **该互斥校验当前只存在于 g8 树未提交改动**。vlm 树动作层（`model.py:708-713`）
    只读 `yaw_deg`/`pitch_deg`，工具层（`tool_bindings.py:325-333`）才把
    `target` 折算成角度。树入口必须先统一这个差异，并以测试钉住；
  - `cinema/axis.py::axis_state()` → 逐镜轴侧 `±1`（轴规则的纯函数真源）；
  - `contracts/beats.py::FACE_TO_VALUES / PACE_VALUES / COMPOSITION_RULES /
    SUBJECT_POSITIONS / RULE_ACTIONS` → 拍点/构图/辩护的闭集。

**每镜唯一化**（这是「每分镜一棵树」的实质）：

1. 角色闭集 = `shot.characters` ∪ 剧本声明的锚点/道具（`environment.anchors` 的
   `name`、`props` 名单）；
2. 轴侧闭集 = `axis_state(axis, plan, initial)` 给该镜的 `±1`，再投影到
   `CAMERA_SIDES` 的 9 个 token（正面 `front` 两侧各取一个候选；`over_shoulder`
   是唯一合法 token——**没有 `over_shoulder_A/B` 变体**，过肩方向由轴侧闭集
   映射为 `front_left`/`front_right`；只在 OTS/POV 镜开放；空镜豁免——
   `characters` 为空时不做轴侧闭集）。

   **D（自查补丁 5）：轴侧真源的纯层缺口。** `shot_builder.py::axis_for_shot`
   （`:244`）是 bpy 侧函数（读 `context._axis_sides_used`/`_axis_lines_used`），
   **纯树模块不能 import 它**。因此树的轴侧真源分两段：
   - 无注入时用 `cinema/axis.py::axis_state` 的**纯函数预测**（顺序状态机的
     `±1`），这是测试/离线/无 bpy 环境的真源；
   - 主路径运行时由驱动注入**该镜实际锁定值**：`build_tree(..., axis_side=
     Optional[int])`，取 `context._axis_sides_used[shot_id]`（摆位器已落账，
     `_axis_absent_shots` 记无轴镜）。注入值必须 ∈ {+1,-1,0}（0 = 无轴/空镜
     豁免），否则 `TreeBuildError`；
   - `regenerate_shot` 逐镜重建时同样从 `axis_for_shot(context, shot)` 取侧别
     传给 `place_shot_camera(..., axis=...)`（§3.6.4 第 5 项）——**树与重建
     用同一个运行时真源**，杜绝"树说合法、重建摆到另一侧"。
3. 动作空间闭集 = 该镜已声明动作类型 ∪ 该镜镜头类型允许的运镜；
4. 数值域 = `lens ∈ [8, 300]`、`amount` 按 `MOVEMENT_UNITS` 的单位区间、
   `beats[].t ∈ [0, 1]`、起止帧 ∈ 该镜帧窗；
5. 软建议节点 = `shot_constraint_query()` 的检索结果（只进提示词与评分，
   不投影硬拒绝）。

**project() 的优先级**（与实测 invalid 的分布对应）：

| 优先级 | 节点 | 规则 |
|---|---|---|
| P0 | 剧本硬节点 | 与剧本声明冲突 → `REJECTED` + `E_SCRIPT_xxx`，不投影； |
| P1 | 规则节点 | `camera.side` 不在闭集 → `PROJECTED` 到最近合法 token； |
| P2 | 动作空间节点 | `action_type` 不在闭集 → `PROJECTED`/`REJECTED`（无歧义才投影）； |
| P3 | 等价键归一 | `ACTION_PARAM_ALIASES`（已有单一真源）→ 归一后进 `ACCEPT`； |
| P4 | 软建议 | 只影响评分与提示词，不投影。 |

**I（自查补丁 5）：投影要覆盖嵌套路径。** 提案的合法值不在顶层：r6 的
`emit_shot_draft` 里 `camera.side` / `actions[].type` / `actions[].params` /
`beats[]` / `movements[]` 都是嵌套字段。`project()` 必须按**工具→路径映射表**
（§4）定位节点：`("camera", "side")`、`("actions", "*", "type")`、
`("actions", "*", "params")`（整段进 `ACTION_PARAMS` 判域）、
`("beats", "*")`、`("movements", "*", "type")`；遍历顺序 = 先顶层后嵌套，
每条越界独立成 `ProjectionRecord`，一次提议多处越界 → 多条记录进同一事件
的 `records[]`（见 §9 修正 K）。

投影候选的选取：对枚举闭集用「词形前缀 + 编辑距离」找最近合法值（例：
`side='side'` → `left`/`right`；`side='front-right, same 180° side as shot_004'`
→ 先剥离自由文本，再按轴侧选 `front_left`/`front_right`）；对数值域做 clamp；
对 `look_at` 的 `target` 只接受 `shot.characters ∪ 锚点名`，不接受自由文本坐标
（坐标必须走 `target_position` 数组，且不与 `target` 同框——r6 实证被拒样本）。

### 3.5 数值层（连续优化）——代码级

> 本节是用户 2026-10-11 批注的落地：连续变量（角色行动、构图、视频震动等）
> 的优化作为决策树规划的**数值层**写进同一份文档。与树的分工是——**树管
> 结构/离散，数值层管连续微调，agent 提供初始意图，用户保留画面裁定权**。
> 实现顺序：先树（阶段 0–4），后数值层（阶段 5），最后 r7 真跑（阶段 6）。
> 本节只做规划，未获批准前不实现。

#### 3.5.1 为什么这里不用梯度下降（用户的直觉 vs 目标函数的事实）

用户提出「连续变量可以用梯度下降优化」。方向对了一半，但**对得分函数不可行**，
证据是本仓库评分函数的结构（已逐行核对）：

- `cinema/composition.py` 的 `evaluate_composition`：六个分项满是 `_clamp01`
  与分段线性（`_headroom`/`_lead_room`/`_thirds`/`_balance`/`_framing`）；
  `_occlusion` 是**三档**（全遮挡 0 / 部分 0.3 / 无遮挡 1），且
  `primary.inside_ratio() <= 0.05` 时总分被硬压到 ≤20——处处不可微、有
  阶梯与硬闸；
- 遮挡读数来自 bpy 侧 `scene.ray_cast`，是离散事件（射线是否被挡），
  对机位参数不连续；
- 节奏/时长读数（`asl_s`/`duration_cv`/`monotony`/`jump_cut_risks`）同样是
  分段统计量。

结论：**评分函数不满足梯度存在的条件**，梯度下降在这类目标上会被阶梯平台
与硬闸误导。正确路线是**无导数（黑箱）优化**：Hooke-Jeeves 模式搜索 /
随机重启。但用户的直觉里有一个**正确的内核**——agent 确实应该在优化里
起作用：给**初始点 x0 / 意图 / 步长策略**（哪一维值得动、初始步长多少、
预算多少），并在优化结果回写前做语义复核。优化器负责盒内数值提升，agent
负责意图与验收，各司其职。**原则是通用的**：即使将来某个子目标可微、
改用梯度类方法，学习率（及其等价物）同样由 agent 决定并进审计，优化器
不内置默认值兜底（本设计以 HJ 步长 `step_scale` 承载这一职责）。

**方法选择也归 agent（用户 2026-10-11 批注「梯度下降的使用也是需要 agent
进行规划和使用」）**：

- agent 每轮显式声明方法（`method_choice`，如 `"hooke_jeeves"` /
  `"random_restarts"` / `"auto"` / 将来可微子目标上的 `"gradient"`）与
  理由（`method_reason`），随 `opt_problem` 一起提交；优化器不替 agent
  决定用什么方法；
- 若 agent 选了梯度法，但该目标不可微（评分函数含阶梯/硬闸/离散 ray_cast，
  见上方证据），优化器**不自动降级换方法**，而是返回 `method_inapplicable`
  回执（带 `evidence` 指向哪条规则不可微），由 agent 换方法或调整目标后
  重提——保证「方法选择权在 agent、不静默降级」；
- **可微性由 agent 声明，不靠优化器事后猜（自查补丁 5 / L·M）**：`OptProblem`
  新增 `score_kind`（`"blackbox"` / `"differentiable"`，默认 `"blackbox"`）。
  `_check_method_applicable` 的**第一判据是这份声明**——`method_choice="gradient"`
  打在 `score_kind="blackbox"` 上，构建期即回执 `method_inapplicable`，不进入
  优化循环。**运行期兜底**：即便声明 `"differentiable"`，`_evaluate` 实测遇到
  `-inf`（硬违规）或 NaN 时，仍以 `method_inapplicable` 回执（`evidence` 记录
  触发键与读数），**不自动降级换方法、不静默跳过**。理由：可微性不可能从
  任意黑箱 `Callable` 的签名静态判断，声明 + 运行期证据双段判定才是可审核的。
- `method` 与 `method_choice` 一起进 `opt_result` 审计，评审可追责。

#### 3.5.2 分层与边界

| 层 | 负责 | 不负责 |
|---|---|---|
| 决策树 | 结构/离散闭集（side、action_type、movement.type、look_at.target）＋数值域盒边界（单一真源） | 连续微调 |
| 优化器 | 连续键的盒内微调（lens、机位微调、动作幅度、handheld amount…） | 改离散键、越域、改剧本硬值 |
| agent | 提供 x0/意图/步长（学习率类比）/预算，接收优化结果并做语义复核 | 数值寻优本身 |
| 用户 | 画面效果最终裁定（尤其震动等无客观评分的项） | — |

硬边界（代码强制）：
1. **登记期拒绝**：离散键/剧本硬值**不允许**登记为 `OptVariable`——树的
   `legal_space["opt_variables"]` 只导出连续数值键；谁试图把
   `camera.side`/`action_type`/剧本锁定的 `angle_deg=45` 之类登记成变量，
   在构建期就抛 `OptDomainError`（不是运行时兜底）；
2. **运行期拒绝**：即便 x0 含未登记键或越盒值，`optimize` 也直接拒绝该提议
   并留 `opt_rejected` 审计，绝不静默丢弃或改写；x0 必须是树上登记键的
   子集、值必须在盒内；
3. 剧本**显式声明数值**的键默认不进优化（例：剧本写「转身 45°」，则
   `angle_deg=45` 只投影、不寻优）；只有剧本/用户给出**范围**或值未锁定时
   才开优化；
4. 优化器输出是**建议值**：构图/节奏类由 agent 复核后回写并留审计；
   震动等主观类**只出候选**（同一确定性 seed 渲染 2–3 档），由用户拍板，
   绝不自动写回。

#### 3.5.3 新纯层模块 `block_director/layer5_orchestrator/continuous_optimizer.py`

红线同 `contracts/`：不 import `bpy`、不依赖第三方（见 §3.5.4 复用结论），
>=3.10 标准库即可。

```python
class OptDomainError(ValueError):
    """登记期错误：把离散键/剧本硬值/未登记键登记为 OptVariable，
    或 step_scale 缺键/非正。构建期即抛，不留 `opt_rejected` 审计
    （还没到运行期，没有可拒绝的调用）。调用方负责把该异常记入运行
    日志/失败原因——它是构建期配置错误，不是“提议被拒”事件，避免与
    `opt_rejected` 语义混淆。"""

@dataclass(frozen=True)
class OptVariable:
    key: str                      # "camera.lens" / "camera.movements[0].amount" /
                                  # "actions[0].params.angle_deg" / "beats[0].t"
    low: float
    high: float
    unit: str                     # "米" / "度" / "毫米" / "t" / "倍" ...
    scale: float = 1.0            # 步长建议基准（由 MOVEMENT_UNITS 典型区间导出，
                                  # 只供 agent 显式取用，优化器不自动兜底）
    step: float | None = None     # 有则对候选取整（如 1 度 / 0.01 米）

@dataclass(frozen=True)
class OptProblem:
    variables: Tuple[OptVariable, ...]
    score: Callable[[Dict[str, float]], float]   # 黑箱评分；越高越好；-inf=硬违规
    x0: Dict[str, float]                          # agent 给定的初始意图
    step_scale: Dict[str, float]                  # agent 决定的初始步长（“学习率”
                                                  # 类比）：每键 >0；缺键/非正/含
                                                  # 未登记键 → 登记期 OptDomainError，
                                                  # 不自动推导兜底
    shot_id: str                                  # 审计元数据（opt_candidate/result 必填）
    stage: str                                    # "draft" / "react" / "repair" / "review"
    score_kind: str = "blackbox"                  # agent 声明的目标可微性：
                                                  # "blackbox"（默认，无梯度信息）/
                                                  # "differentiable"（将来可微子目标）；
                                                  # _check_method_applicable 的第一判据
    method_choice: str = "auto"                   # agent 显式声明的方法
                                                  # （"hooke_jeeves"/"random_restarts"/
                                                  #  "auto"/ 将来 "gradient"）
    method_reason: str = ""                       # agent 选该方法的理由，进审计
    max_calls: int = 40
    seed: int | None = None                       # 确定性（随机重启使用）
    tolerance: float = 1e-3

@dataclass(frozen=True)
class OptResult:
    x: Dict[str, float]           # 结果（无提升或失败时 == x0）
    value: float
    x0: Dict[str, float]
    value0: float
    calls: int
    method: str                   # "hooke_jeeves" / "random_restarts" / ...
    improved: bool
    method_inapplicable: str | None = None   # agent 选了不适用于本目标的
                                             # 方法时给出回执（含 evidence），
                                             # 不自动降级换方法
    audit: Tuple[Dict[str, Any], ...]   # 每次候选评测 {x, value, reason}
    warnings: Tuple[str, ...]

def optimize(problem: OptProblem) -> OptResult: ...   # 方法取自 problem.method_choice
def _check_method_applicable(problem) -> Tuple[bool, str]: ...
# 第一判据 = problem.score_kind 声明；运行期遇 -inf/NaN 再由 _evaluate 回执
# method_inapplicable（带 evidence），不自动降级换方法
def _clamp_value(v: OptVariable, x: float) -> float: ...   # 与树 project() 同源
def default_step_scale(variables) -> Dict[str, float]: ...
# 步长建议值（区间典型跨度 / 20 之类）；只供 agent 显式调用后自行决定
def _hooke_jeeves(problem, rng) -> ...: ...                # 无导数主实现
def _random_restarts(problem, rng) -> ...: ...             # 非凸目标的补充起点
def _evaluate(problem, x) -> Tuple[float, Dict[str, Any]]: ...
```

算法要点（全部可写成 ~150 行标准库）：

- **主方法 `hooke_jeeves`**：坐标方向模式搜索。候选生成 = 当前点沿各轴
  ±`step_scale[key]`（**agent 决定**，见下），先探移动再按净增益方向加速
  （模式移动）；步长减半直到低于 `tolerance` 或预算耗尽。对「含少量硬闸的
  连续目标」够用，且完全确定。
- **步长由 agent 决定（用户 2026-10-11 批注的“学习率”类比）**：
  `step_scale` 是 `OptProblem` 必填字段，逐键给初始步长；缺键/非正/含未
  登记键 → 登记期抛 `OptDomainError`，**不自动推导兜底**；`default_step_scale`
  只是给 agent 的建议助手，调用后仍由 agent 决定是否覆写；生效值进
  `opt_result` 审计，评审可查。
- **方法也由 agent 决定**：`method_choice`/`method_reason` 必填（默认为
  `"auto"` 时也要给理由）；`_check_method_applicable` 先按
  `score_kind` 声明判定——`"gradient"` 用在 `score_kind="blackbox"` → 回执
  `method_inapplicable`，不进优化循环、不换方法、不吞错误；声明
  `"differentiable"` 后运行期实测遇 `-inf`/NaN，同样回执并留 `evidence`。
- **`random_restarts`**：非凸目标（构图含阶梯）只靠 HJ 会困在局部；
  `seed` 固定用 `random.Random(seed)` 撒 8–16 个起点，各跑短 HJ，取最优。
  产出完全可复现（与 `camera_motion._noise` 同一确定性纪律）。
- **`auto`**：先跑一次 HJ，若预算剩余 ≥10 次再随机重启补位；`improved`
  为 false 时**结果必须等于 x0**（不许「无提升还改写」）。
- **候选评测 `_evaluate`**：先对全部变量 `_clamp_value`（与树投影同一口径），
  再调 `score`；返回 `-inf` 的一律不选、原因写进审计；每次评测都进
  `OptResult.audit`，不改判据、不静默。

**算法边界细节（自查补强，2026-10-11）**：

- **取整与 clamp 的次序**：带 `step` 的键，候选生成必须是
  `clamp(round_to_step(clamp(x ± δ)))` —— 先 clamp 再取整，取整可能把值
  顶出盒外（例：盒高 48、步长 10、clamp 后 46 → round 到 50 越盒），
  因此取整后必须再 clamp 一次；两段次序写进 `_candidate`，测试钉住。
- **grid 键的终止基准**：带 `step` 的键，步长减半不得低于
  `max(tolerance, step/2)`，否则对取整键做无意义细分、白白烧预算；
  终止条件按“该键是否 grid”分别取。
- **预算计数含初始评测**：`value0` 也消耗 1 次调用；`calls <= max_calls`
  的计数口径包含 x0 一次，测试按此断言。
- **x0 自身硬违规**：若 `score(x0) == -inf`，立即返回 `x == x0`、
  `improved=False`，不再寻优（起始点已违规 → 把问题退回 agent 调整意图，
  不自动找可行点）；审计 reason 记 `hard_violation_at_x0`。
- **随机重启起点在盒内**：对每键按盒均匀采样，先 clamp 再评分；
  起点不需要也别绕过盒边界。

#### 3.5.4 连续键的来源与盒边界（与树共用同一真源）

| 键（示例） | 真源 | 盒边界 | 备注 |
|---|---|---|---|
| `camera.lens` | `cinema/camera_motion.py::MIN_LENS/MAX_LENS`（8–300 mm） | `[8, 300]`，单位 mm | 构图离线优化的主键之一 |
| `camera.movements[i].amount` | `cinema/camera_motion.py::MOVEMENT_UNITS`（:94，每运镜 `(单位, 低, 高)`） | 按运镜取区间 | **单位必须由表给**（v1.5 实测：`dolly_in` 12 米穿过主体）；该表已与 `MOVEMENT_TYPES` 有防漂断言 |
| `actions[k].params.angle_deg` / `lean_deg` 等 | `motion/model.py::ACTION_PARAMS`（:103）；取值域 `action_param_domains` / `action_param_problems` | 由动作类型与剧本声明推出 | `speed` 是**闭集**（`_SPEED_RATE`），不是连续键，不进优化器（见 §3.5.2 硬边界 1） |
| `beats[].t` / 拍点 | `contracts/sdl.py` SDL 时间轴、`cinema/schedule.py` 帧安排 | `[0, 1]`（镜内比例） | 决策树定拍点结构，优化器只微调同层动作的错开量 |
| `animation.walk_speed` 等设置 | `contracts/config.py`（`config.default.yaml` 由它生成） | 配置既有上下限 | 全局设置不逐镜优化，属运行级 |

每镜参与优化的变量清单由树的 `legal_space` **附带导出**：
`legal_space["opt_variables"] = tuple(OptVariable(...))`。树仍在中央：既给
离散闭集，又给连续盒；agent 的 x0 只能在这些登记键里取（提示词渲染同样
来自这里，单一真源）。

#### 3.5.5 在哪些场景启用（不铺开）

与树同一纪律——**只对实测出现问题的维度开优化**，不以“预防性铺开”换取
覆盖：

1. **构图门（judge #3 audit_pass_rate）**：`lens` / 机位微调 的离线优化，
   评分回调注入 `evaluate_composition`（纯层可先跑；bpy 侧 ray_cast 开销大，
   只在真跑验证或离线快照里做）。**口径不漂移**：只说「离线评分」不改变
   判据 #3 的输入——判据 #3 仍读**实际运行时 shot_auditor 采样的
   `audit_pass_rate`**，优化只产出候选建议；一旦候选被 agent/计划采纳，
   判据用真实运行读数复算，不用离线分代替。任何替代口径都是降级，禁止；
2. **运镜强度（handheld 等）**：**无客观评分**，主观视觉效果 → 优化器只
   在同一确定性 seed 下出 2–3 档候选，**候选渲染由用户拍板**（不自动回写）；
3. **节奏/时长（r7 复跑若 R011 重犯）**：`beats[].t` 微调在前
   `layer5_orchestrator/timing_tool.py` 的纯函数评分上做，目标函数可直接算。

不启用：剧本显式声明的数值、离散键、`speed` 闭集、全局设置（§3.5.2）。

#### 3.5.6 审计与回写（登记事件，防回放炸链）

新增审计事件（必须在 `contracts/audit.py::V16_EVENT_FIELDS` 登记后使用，
否则 `missing_event_fields` 返回 `<unregistered>`、回放链抛 `ReplayError`）：

- `opt_candidate`：每次候选评测 `{shot_id, round, stage, x, clamped, value,
  reason}`（`value=-inf` 表示硬违规，reason 记录哪条规则）；
- `opt_result`：每镜每轮优化结果 `{shot_id, round, stage, x0, value0, best_x,
  best_value, step_scale, calls, method_choice, method_reason, method, improved,
  refit_by}`（`method_choice`/`method_reason` 是 agent 在 `OptProblem` 里的
  原始声明，`method` 是优化器实际执行的方法（普通情况与 `method_choice`
  相同；`method_inapplicable` 时不执行、method 为空）；`refit_by` ∈
  `{"agent","user","none"}`——谁复核/拍板，绝不伪称 `human`）；
- `opt_rejected`：优化器试图改离散键/剧本硬值被拒 `{shot_id, key, attempt,
  reason}`。

定稿后同步 `specs/openapi.yaml`（事件字段进 wire 协议）与
 vlm 树审计测试文件（`tests/test_audit_contract.py` / `test_audit_logger.py` /
 `test_vlm_audit_events.py`，P1-3 注明本树无 `test_audit_events.py`）。
所有事件与 tree 的 `draft_projected` /
`react_projected` / `repair_projected` 一起进 `audit_log.jsonl`，回放链可完整
重放。

### 3.6 执行编排：场景/元素就位 → 逐镜剧情预演循环（方案 B：深度整合）

> 用户 2026-10-11 裁决：**直接改现有 `plan_structured` 主路径**，默认所有
> 真跑都走「先准备场景与元素 → 然后逐镜剧情预演，每次一个镜头，并优化 →
> 持续迭代到该镜没有问题，再进入下一镜」。**迭代是逐渐调整，不是重做**：
> 不得为每次迭代推倒整场重建；复用已就位的场景与角色，只增量调整**当前镜**
> 的参数（相机、动作关键帧、连续变量），下一镜开工前本镜必须干净。

#### 3.6.1 为什么 B（深度整合）而不是旁路模式

- 方案 A（`per_shot_previz` 枚举、默认关闭）把新流程做成旁路：两个主路径
  长期共存，判据/审计/交付各自为政，`orchestration.mode` 多一个永远要
  维护的分叉；方案 B 让**每镜一次构建 → 一次预演**成为唯一主路径，所有
  真跑、UI 按钮、headless 批处理默认一致。
- 回归面大是 B 的代价，但仓库既有机制（`_shot_queue` 逐镜审核、`_advance_shot`、
  `regenerate_shot` 单镜增量、`schedule.py` 排片、`note_build` 基线）已经按
  「逐镜」组织：真正缺的是**准备阶段**与**逐镜重建时的轴状态传递**，不是
  一条新的并行管线。B 把这些缺口补在主路径上，`mode` 仍是单值。
- **不重做**的纪律直接钉进循环：`prepare_scene` 只建一次环境/角色/道具/群众；
  每镜预演用 `regenerate_shot`（只删该镜帧窗关键帧、只换该镜相机），绝不
  整场 rebuild；用户已动过的角色（`bd_user_animated`）整段保护，不覆盖。

#### 3.6.2 现状（代码事实，vlm 树 HEAD `af448dd` 核对）

- 现在是一次性单体构建：`driver.py::_step_building`（`:1855`）→
  `builder.build(plan, brief)` → `_after_build_state`（`:1920`）把所有
  `auditor.shot_ids()` 塞进 `_shot_queue` → 逐镜 `_step_checking`
  （`:2127`）→ `_advance_shot`（`:2211`）。审核/修复已逐镜，但**构建是
  一把梭**：`build_scene`（`layer3_engine/shot_builder.py:538`）内部才拆
  两趟（排动作/烘焙 → 摆机位/运镜/标签）。
- `SceneBuilder` 协议（`layer5_orchestrator/builder.py:17`）只有
  `build(plan, brief)` 一个方法；bpy 实现是 `BpySceneBuilder`
  （`shot_builder.py:947`）。
- `shot_regenerator.py::regenerate_shot`（`:62`）已经是正确的逐镜积木：
  `sync_from_blender` 回读用户编辑 → 只删该镜帧窗关键帧（
  `clear_keyframes_in_range`，`:35`）→ 用 `live_subject_entries`（
  `shot_builder.py:273`）当前站位摆 `place_shot_camera`（`:304`）→ 重烘
  该镜动作 → 重烘标签。**逐镜预演就是把它接到 driver 审核循环的
  PREPARE_SCENE/PER_SHOT 阶段（§3.6.3），取代"整场 build → CHECKING"的
  一把梭路径**。
- 轴顺序状态跨镜累积：`_axis_for_placement`（`shot_builder.py:185`）把
  每镜实际侧别写进 `context._axis_sides_used`、摆位线写进
  `_axis_lines_used`；主构建在 `build_scene` 内用局部 `live_side` 接力
  （`:715` 起）。**`regenerate_shot` 目前不读这两张表**——主路径拆成逐镜后，
  重建第 N 镜必须从 `axis_for_shot(context, shot)`（`:244`）取“该镜当时用的
  轴线”，否则增量重建会把机位摆到观众没看见过的一侧（r6 实测同类缺陷：
  修复回路把 `shot_001` 位置 y 从 -4.30 翻成 +4.30、构图 74.6 → 20.0）。

#### 3.6.3 目标状态机与数据流

```text
PLANNING → EDITING（B1 逐镜结构化草案）→ PREPARE_SCENE → PER_SHOT →
  (PER_SHOT 内逐镜循环) → FINISHING
```

新状态两个，仅主路径使用（`plan_structured` 默认即走，不新增 mode）：

- `PREPARE_SCENE`：调用新增 `builder.prepare_scene(plan, brief, spec)`，
  只建**场景与元素**（清对象/集合 → 环境/锚点/灯光 → 角色/标签 → 道具 →
  群众 → `SceneContext` + `set_context` → `note_build()` 记基线）。**不摆
  相机、不烘焙动作、不建镜头标记**。`scene_prepared` 审计事件一次。
- `PER_SHOT`：从 `_shot_queue` 取当前镜，逐镜执行：

```text
for shot_id in shot_queue:            # 顺序推进，不改计划顺序
    repeat:
        1. project(tree[shot_id], proposal)     # 决策树投影（阶段 0–4 接入）
        2. regenerate_shot(shot_id)             # 增量重建：只动这一镜
        3. _audit_shot(shot_id)                 # 规则/构图/穿模审核
        4. if passed / finished: break
        5. else: REPAIRING/ReAct → 回到 1（同一棵树，同一镜；
           REPAIRING/ReAct/REVIEWING 完成后统一经
           `_resume_per_shot_or_checking()` 回到 PER_SHOT 继续审当前镜）
    _advance_shot()                             # 移入下一镜，树缓存失效
```

- 每镜**构建一次、预演一次、审核一次**；不干净就**在该镜内**迭代（修复/
  ReAct/连续优化），通过了才 `_advance_shot`。`_advance_shot` 里同时
  `_decision_trees.pop(shot_id)`（与 `_repair_baseline.pop` 同一时机，
  `driver.py:2211`）。
- 迭代是**增量**的：第 2 步只清 `[start, end]` 帧窗内关键帧、只换该镜相机
  与标记；环境、角色网格、其他镜的相机/动画一概不动。`regenerate_shot`
  返回的 `warnings/protected` 直接进 `shot_iteration` 审计。

#### 3.6.4 代码级改动清单（方案 B）

1. **`contracts/enums.py`**：`OrchestrationMode` 不加新值（B 不新增旁路）。
2. **`states.py`**：`DriverState` 加 `PREPARE_SCENE = "PREPARE_SCENE"`、
   `PER_SHOT = "PER_SHOT"`（`TERMINAL_STATES` 不变）。
3. **`builder.py`**：`SceneBuilder` 协议加可选方法
   `prepare_scene(plan, brief=None, spec=None) -> Dict`（**C：可选方法，
   用 `hasattr(builder, "prepare_scene")` 探测**——协议不强制假 builder
   实现，既有注入假 builder 的测试不受破坏）；`BpySceneBuilder`
   实现为 `build_scene` 头部解耦（`clear_blockdirector_objects` →
   `ensure_collections` → `purge_orphan_data` → `build_environment` →
   `create_character`/标签 → `SceneContext` + `set_context` →
   `note_build()`），**不含** `motion_requests` 烘焙、机位、运镜、标签烘焙。
   返回 `{"characters": n, "cameras": 0, ...}` 摘要。不提供实现时
   `hasattr(builder, "prepare_scene")` 为 False → 退回旧 `build` 整场路径
   （这是**兼容回退，不是降级**：无 bpy 测试注入假 builder 时可走旧路径；
   真跑主路径一定用 prepare→逐镜）。
4. **`driver.py`**：
   - `__init__` 加 `self._decision_trees: Dict[str, ShotDecisionTree] = {}`、
     `self._per_shot_iterations: Dict[str, int] = {}`；
   - `_step_editing` 完成 B1 后：`target = PREPARE_SCENE`（builder 有
     `prepare_scene` 时），否则旧 `BUILDING`；
   - 新增 `_step_prepare_scene`：调 `builder.prepare_scene`，落
     `scene_prepared` 审计，**初始化 `build_summary["results"]` 空表**（见
     F/G/U/V/W），塞 `_shot_queue`（保持现有 `_after_build_state` 顺序），
     转 `PER_SHOT`；
   - 新增 `_step_per_shot`：`_audit_shot` → passed/`_pending_finish` 走
     `_mark_terminal` + `_advance_shot`；失败走 `REPAIRING`（现有
     `_step_checking` 的同一批分支复用；见 B/E/H 的出口统一 helper）；
   - **B/E/H（自查补丁 5）——逐镜模式转移统一**：`_advance_shot` 转
     `PER_SHOT`（非 `CHECKING`），REPAIRING/ReAct/REVIEWING 完成后的
     **同一镜恢复出口**统一走 helper `_resume_per_shot_or_checking()`：
     builder 有 `prepare_scene` 时回 `PER_SHOT`（继续审当前镜），否则回
     `CHECKING`（旧路径）；`_step_repairing` 无 `_pending_audit` 的出口
     （`:2428`）同样走该 helper；
   - **B（自查补丁 5）——逐镜回滚**：`_rollback_repair_if_worse` 在
     prepare 路径下**不再整场 rebuild**：恢复 `_repair_baseline[shot_id]`
     的计划快照 → `self.plan`/`context.plan` 更新 → `regenerate_shot`
     重做当前镜（增量，不推倒环境/角色/其他镜）→ 转 `PER_SHOT`；旧
     BUILDING 整场重建分支只留给假 builder（无 `prepare_scene`）兼容回退；
   - `_dispatch_tool_calls` 前插决策树投影（阶段 2 落点）；
   - `_advance_shot`：pop 后 `self._decision_trees.pop(str(done), None)`。
5. **`shot_regenerator.py`**：`regenerate_shot` 加
   `axis=axis_for_shot(context, shot)` 传给 `place_shot_camera`（与主构建
   同源；`_axis_absent_shots` 已由 `_axis_for_placement` 记录）；返回
   `axis_side`/`axis_line` 供审计。**这是 B 的必改项**，不加则逐镜重建越轴。
6. **审计事件**：新事件 `scene_prepared`、`shot_iteration`（每镜每轮
   `{shot_id, round, action: build|audit|repair|opt, result}`）、
   `shot_advanced`（移入下一镜）——**先登记 `contracts/audit.py::V16_EVENT_FIELDS`
   再用**，并同步 `specs/openapi.yaml`（同 §3.5.6 纪律）。

   **T（自查补丁 5）：事件必有字段逐一定义，不能只有一句话。** 阶段 2/3/4/5
   新增的九类事件全部写死最小形状（进 `V16_EVENT_FIELDS`，测试与
   `openapi.yaml` 对拍）：

   - `draft_projected`：`(shot_id, stage, records)`——`records[]` 是
     `ProjectionRecord` 全量（一次草案多处越界 = 多条，不再是"每镜每轮最多
     一条"，K 修正）；
   - `react_projected`：`(shot_id, stage, tool, records)`；
   - `repair_projected`：`(shot_id, stage, tool, records, repair_invalid)`——
     `repair_invalid` 是原 invalid 记录引用（同一镜同一轮可复现）；
   - `scene_prepared`：`(characters, cameras, props, crowd, prepared_at)`；
   - `shot_iteration`：`(shot_id, round, action, result, warnings, protected)`；
   - `shot_advanced`：`(shot_id, next_shot_id, decision_trees_evicted)`；
   - `opt_candidate`：`(shot_id, round, stage, x, clamped, value, reason)`；
   - `opt_result`：`(shot_id, round, stage, x0, value0, best_x, best_value,
     step_scale, calls, method_choice, method_reason, method, improved, refit_by)`；
   - `opt_rejected`：`(shot_id, key, attempt, reason)`。

   登记顺序纪律：**先 `V16_EVENT_FIELDS` → 再 `specs/openapi.yaml` → 再
   vlm 树的审计测试文件（`tests/test_audit_contract.py` /
   `test_audit_logger.py` / `test_vlm_audit_events.py`；P1-3 注明本树无
   `tests/test_audit_events.py`）**，任一事件未登记前不得被生产者写
   （`missing_event_fields` 对未登记事件返回 `["<unregistered>"]`，回放链抛
   `ReplayError`）。

#### 3.6.5 不变量（逐镜预演）

- 复用 `schedule.py::shot_ranges/travelled_positions`：帧窗与“这一镜开始时
  人在哪”不因拆分而变；
- `bd_user_animated` 角色整段保护（`regenerate_shot` 现有 `guarded` 逻辑）；
- 只清该镜 `[start, end]` 关键帧；其他镜相机/标记/关键帧不动；
- 每次迭代都审计（`shot_iteration` 事件），**不静默**；`_pending_finish`/
  `abort` 语义不变；
- 逐镜回滚（`_rollback_repair_if_worse` 的 prepare 路径分支）：恢复
  `_repair_baseline[shot_id]` 计划快照 → `self.plan`/`context.plan` 更新 →
  `regenerate_shot` 重做当前镜（增量）→ 转 `PER_SHOT`；环境/角色/其他镜
  不动，`bd_user_animated` 保护不因回滚失效；
- 轴状态 `_axis_sides_used`/`_axis_lines_used` 跨镜累积，逐镜重建从
  `axis_for_shot` 读，不重新猜；
- 交付与回放链完整：`shots.json`/`prompts.md`/`camera_traj.json` 与
  `audit_log.jsonl` 均按逐镜结果落盘；`replay.py` 可重放
  `scene_prepared`/`shot_iteration`/`opt_*` 事件（全部登记后）。

#### 3.6.6 与决策树/数值层的衔接

- **每镜一棵树**：`build_tree(shot, plan, contract)` 在 `PREPARE_SCENE` 后、
  第一轮 PER_SHOT 前构建并缓存 `_decision_trees[shot_id]`；draft/react/
  repair/优化四类提议都从同一棵投影（§3.2/§4 不变式）；
- **数值层 per-shot**：`opt_problem` 只作用于当前镜（`OptVariable` 键来自
  该镜 `legal_space`），`step_scale`/`method_choice` 由 agent 每轮显式声明
  （§3.5）；优化结果由 agent 复核回写（`refit_by`），震动类只出候选交用户；
- **迭代收敛定义**：`_audit_shot.passed`（规则/构图/穿模全绿）或
  `_pending_finish` 声明完成——与现有 CHECKING 同一验收，不改判据。

**S（自查补丁 5）：树的失效条件（缓存重建时机）**。`_decision_trees[shot_id]`
在以下任一情况必须**重建**，旧树继续投影就是拿过期语义换新镜：

1. **计划合并**：`emit_shot_draft` 的修正值被采纳并 `merge_draft` 进 `plan`；
2. **镜头切换**：`_advance_shot` pop 该镜时 evict（`driver.py:2211` 同时机，
   `_repair_baseline.pop` 一起）；`_current_shot_id` 变化 = 旧树失效；
3. **`update_plan` / `regenerate_shot` 路径**：任何把 `self.plan` 或
   `context.plan` 换成新对象的入口（repair 重提草案、回滚快照恢复），
   当前镜的树在下一轮 PER_SHOT 前重建；
4. **轴状态变化**：`_axis_sides_used[shot_id]` 被 `_axis_for_placement`
   改写（换位/越轴修复后），树按新 `axis_side` 重建。

阶段 2 测试覆盖：同镜 repair 重提草案后，`_decision_trees[shot_id]` 的
`legal_space` 与重建前不同；不同镜之间缓存不串。

## 4. 接入点（已核实行号）

> 行号按 vlm 树 HEAD `af448dd`（2026-10-11 核对）；g8/main 树因各自改动
> 行号会漂，接入时以函数名 + 行为锚点为准，不用写死行号。

| 阶段 | 接入点（vlm 树，函数锚点） | 现状 |
|---|---|---|
| B1 draft | `editor.py::extract_draft`（`:518`）：`ShotDraft.from_dict`（`:545`）之后、`roster` 检查与 `raise ValueError` 之前 | 已有 schema 校验＋逐动作参数核；**投影插在 `normalize_action_params` 归一之后**（`:566`），与它共用"逐动作"循环，不新增一遍遍历 |
| react | `driver.py::_dispatch_tool_calls`（`:2952`）：`parsed_arguments()`（`:2963`）成功之后、`registry.execute`（`:2967`）之前 | 工具调用后校验（`validate_args`），无事前投影；投影在这里插入，执行前就把闭集外值投影掉 |
| repair | 同 `_dispatch_tool_calls`（repair 与 react 共用同一分发器） | 同上；修复提议与 react 提议走**同一棵树**，`stage` 区分（`repair`/`react`），引用原 invalid 记录 |
| 校验/真源 | `tool_registry.py::execute`（`:107`）→ `tool_schema.py::validate_args`（`:88`）；`editor.py:117` `side` enum 真源 = `framing.py::CAMERA_SIDES`（`:342`） | 校验保留不删：决策树投影是**事前**减错，`validate_args` 仍是**事后**兜底（防投影漏网） |
| 动作参数真源 | `motion/model.py::ACTION_PARAMS`（`:103`）/`ACTION_PARAM_ALIASES`（`:139`）/`ALL_ACTION_PARAM_KEYS`（`:129`）/`normalize_action_params`（`:146`）/`action_param_problems`（`:201`） | 树从这里导入等价键单一真源，不抄第二份 |
| 运镜真源 | `contracts/enums.py::MOVEMENT_TYPES`（`:181`，来自 `Movement` 枚举）；`cinema/camera_motion.py::MOVEMENT_UNITS`（`:94`，每运镜 `(单位, 下限, 上限)`） | 树据此建 `camera.movements[].type` 闭集与 `amount` 数值域；`MOVEMENT_UNITS` 与 `MOVEMENT_TYPES` 已有防漂断言（`:111`） |
| 轴真源 | `cinema/axis.py::axis_state`（`:285`，纯函数，输出每镜 `±1`）；`SIDE_POSITIVE/NEGATIVE`（`:18-19`） | 树据此算该镜轴侧闭集；R001 判据仍在 `rule_checker.py::check_shot`（`:607` 起）——树**只导入轴侧结果**，不重写判据 |
| 拍点/构图/辩护闭集 | `contracts/beats.py::FACE_TO_VALUES`（`:37`）/`PACE_VALUES`（`:40`）/`COMPOSITION_RULES`（`:49`）/`SUBJECT_POSITIONS`（`:51`）/`RULE_ACTIONS`（`:54`） | 树建拍点/构图/辩护节点；`validate_beats` 在 `editor.py:569-572` 已在解析期核，树不替代它 |
| 知识注入 | `scene_contract.py::shot_constraint_query`（`:135`） | 每镜知识检索 = 软建议节点输入；`rag.cases_backend='off'` 时恒空，不向 sidecar 索要、不算降级 |
| 工具 schema | `tool_bindings.py`：`setup_camera(side)`（`:423`，`side` enum 在 `:711` 附近 schema）；`reframe`（`:603`，只收 `shot_type/lens`）；`look_at`（`:735`）/`face_character`（`:750`）的 `target`+`target_position` 二选一 | 树的 `look_at.target` 只接受 `shot.characters ∪ 锚点名`；坐标走 `target_position` 且不与 `target` 同框（r6 实证被拒样本） |

**接入点事实核查（P1-1/P1-3）**：
- **测试文件名漂移（P1-3）**：`tests/test_react_finish_required.py` 与
  `tests/test_draft_watchdog.py` **在 vlm 树不存在**，只在 g8 树。vlm 树对应
  文件是 `test_driver.py`、`test_driver_react.py`、`test_editor.py`、
  `test_action_params_are_constrained.py`、`test_action_param_values_are_checked.py`、
  `test_draft_v15_schema.py`。阶段 2/3 的“回归原样过”应落在 vlm 树实际文件名上。
- **新增审计事件必须先登记（P1-4）**：`contracts/audit.py::V16_EVENT_FIELDS`
  （`:58`）是事件字段登记表；`missing_event_fields(kind, data)` 对未登记事件
  返回 `["<unregistered>"]`，`layer9_persistence/replay.py:207` 据此抛
  `ReplayError`。规划新增的 `draft_projected` / `react_projected` /
  `repair_projected` **必须先在 `V16_EVENT_FIELDS` 登记**（含各自必有字段），
  文档未提——实现时漏登记，回放链会当场炸（实测
  `missing_event_fields('draft_projected', None) == ['<unregistered>']`）。
- **回归测试名以 vlm 树为准（P1-3 复核）**：`test_react_finish_required.py` /
  `test_draft_watchdog.py` 不在 vlm 树；阶段 2 回归写
  `test_driver_react.py`、阶段 3 回归写 `test_editor.py`，各自原样过。

**投影插入点细节（两处，不是三处）**：

1. **B1 draft**：`extract_draft` 内、`normalize_action_params` 归一循环之后——
   `project(tree, draft.to_dict(), stage="draft")`，把返回的修正值写回 draft；
   投影记录并入该镜审计（`draft_projected` 事件）。`ShotDraft.from_dict` 的
   schema 校验仍在它前面（投影只改取值，不改形状；形状错误照旧 `draft_invalid`）。
2. **react/repair**：`_dispatch_tool_calls` 内、`registry.execute` 之前——
   按 `call.function.name` 查表得到该工具的参数节点，`project(tree, args, stage)`
   后把修正值写回 `call.function` 的解析参数，再执行。`validate_args` 保留为
   兜底；`self_review` 的 JSON 解析错误（r6 那 1 条）不属于决策树（不是语义越界，
   是语法损坏），不进树。

**I（自查补丁 5）：工具 → 投影路径映射表**（`project()` 的遍历蓝本，嵌套
路径先顶层后嵌套；`*` = 数组元素逐个投影）：

| 工具 / 入口 | 投影路径 | 节点真源 |
|---|---|---|
| `emit_shot_draft`（B1 draft） | `camera.side` | `CAMERA_SIDES` + 轴侧闭集 |
| `emit_shot_draft` | `camera.lens` | `MIN_LENS/MAX_LENS`（数值域） |
| `emit_shot_draft` | `actions[*].type` | `ACTION_TYPES` |
| `emit_shot_draft` | `actions[*].params` | `ACTION_PARAMS`/`ACTION_PARAM_ALIASES`/`action_param_problems` |
| `emit_shot_draft` | `beats[*]` | `FACE_TO_VALUES`/`PACE_VALUES`/`COMPOSITION_RULES`/`SUBJECT_POSITIONS`/`RULE_ACTIONS` |
| `emit_shot_draft` | `movements[*].type` / `.amount` | `MOVEMENT_TYPES`/`MOVEMENT_UNITS` |
| `setup_camera`（react） | `side` | `CAMERA_SIDES` + 轴侧闭集 |
| `look_at` / `face_character` | `target`、`target_position` | 角色闭集 ∪ 锚点名；坐标与 target 互斥（G8-C） |
| `move_character` / `enter_from` 等 | `target_position` / 键集过滤 | `ACTION_PARAMS`（`_COORDINATE_KEYS`） |
| `move_camera` / `reframe` | `lens`、数值键 | 数值域（盒内 clamp） |
| `request_self_review` / `finish_shot` / `abort` | —— | 控制工具不进树（非语义越界） |

**数据流不变式**：同一镜的 draft/react/repair 三轮都从**同一棵** `ShotDecisionTree`
投影；树只算一次（每镜构建一次，缓存在 driver 的 `_decision_trees[shot_id]`，
由计划合并/镜头切换失效）。

## 5. 优先级（由实测 invalid 驱动）

优先级依据 r6 终态（run `12dadce87acc`，证据全路径
`E:\bd_g8_rerun\docs\evidence\20261011-v16-g8-r6/`——**vlm 树无此目录**，
引用以 run_id 与审计日志为准）：

1. **react 线（12 条）**：工具提议投影，优先做 `camera.side` / `look_at.target` /
   `movement` 闭集。12 条的构成：`回复中没有工具调用` 7 条（**不属于投影**——
  是模型没调工具，属 prompt/工具集收窄问题，树不越权）；`look_at` 双写 target
   与角度 2 条；`enter_from` 混入 `target_position` 1 条；`camera.side` 自由文本
   2 条（`'front-right, same 180° side as shot_004'`、`'伊恩同侧（延续 shot_008
   轴侧，不越轴）'`——P1 先剥离自由文本、按轴侧投影到 `front_left`/`front_right`）。
2. **repair 线（7 条）**：修复提议复用同一棵树，避免换姿势再越界。7 条构成：
   `回复中没有工具调用` 2 条（同上不进树）；`camera.side='side'` 1 条（P1 投影到
   最近合法 token）；`look_at` 双写 4 条（P3/互斥字段归一）；
   **无 JSON 语法错**——r6 账上唯一一条 JSON 语法错在 `self_review_invalid`。
3. **draft 线（2 条）不动**：`finger_snap` 不在动作闭集 1 条（P2 投影/拒绝——
   树按镜头类型推导合法动作空间后，可投影到近邻或拒绝；不降低 schema 判据）；
   `look_at` 双写 1 条（P3 归一到 `target_position` 或 `yaw_deg/pitch_deg` 二选一）。
   已收敛，避免回归。
4. **self_review（1 条）**：参数不是合法 JSON——语法损坏，不进树；保持
   `self_review_invalid`，由提示词与逃逸通道处理。

**r6 21 条 invalid 对树的覆盖账**（测试矩阵的蓝本）：

| invalid 类别 | 数量 | 进树? | 树节点/策略 |
|---|---|---|---|
| `draft_invalid`：动作类型不在闭集 | 1 | ✅ | P2 `ACTION_TYPES` 闭集投影/拒绝 |
| `draft_invalid`：`look_at` 双写 target 与角度 | 1 | ✅ | P3 等价键/互斥字段归一 |
| `react_invalid`/`repair_invalid`：`look_at` 双写 | 6 | ✅ | 同上 |
| `react_invalid`/`repair_invalid`：`camera.side='side'` | 1 | ✅ | P1 `CAMERA_SIDES` 词形前缀+编辑距离投影 |
| `react_invalid`：`enter_from` 混入 `target_position` | 1 | ✅ | P2/P3 `ACTION_PARAMS` 键集过滤 |
| `react_invalid`/`repair_invalid`：回复中没有工具调用 | 9 | ❌（非语义越界） | prompt 收窄工具集＋react 步数守卫，已有（react 7 + repair 2） |
| `react_invalid`：`camera.side` 自由文本 | 2 | ✅ | P1 `CAMERA_SIDES` 先剥离自由文本、按轴侧投影 |
| `self_review_invalid`：参数 JSON 语法错 | 1 | ❌（语法损坏） | 保持原样 |

结论：**21 条里 12 条是树的直接猎物**（draft 2 + react 5 + repair 5），
其余 9 条 no_tool 不属语义投影，树不越权（另有 1 条 self_review JSON 语法错，
单列账，不进树）；测试矩阵按此逐条断言，不允许用投影
"让 invalid 数字变 0"来当验收——那会掩盖模型没调工具的真问题。

## 6. 测试计划（每阶段有效测试，不改判据）

TDD，按阶段推进，每阶段新增测试并跑绿后再进入下一阶段：

**阶段 0 — 纯层骨架（新文件 `block_director/layer5_orchestrator/decision_tree.py`，
无 bpy；红线同 `contracts/`）**

- `tests/test_decision_tree.py`：
  - `build_tree(shot, plan)` 对 13 镜样例 `fixtures/shotlist_market_v10_nodes1_4.txt`
    每镜返回一棵树，`nodes` 非空、`legal_space` 覆盖 `camera.side`/`movement`/
    `action_type`/`look_at.target`；
  - 正面镜 `camera.side ∈ {front}`（或两侧候选），OTS 镜开放
    `over_shoulder`（方向走 `front_left`/`front_right` 映射——P1 已如此，
    树不自创 `over_shoulder_A/B` token），空镜（`characters=[]`）不做轴侧闭集；
  - `project()` 对合法提议返回 `ACCEPT` 且 `projected == original`、无审计；
  - 拒绝必带原因与 `source`；投影必带 `original`/`projected`/`reason`。

**阶段 1 — r6 21 条 invalid 回归夹具**

- `tests/fixtures/decision_tree/r6_invalids.json`：从
  `%USERPROFILE%\Documents\BlockDirector Projects\runs\audit_log.jsonl`
  （run `12dadce87acc`，**只导出进树的 12 条**——draft 2 + react 5 +
  repair 5；另有 `self_review_invalid` 1 条单列）导出**逐条**的
  `{kind, shot_id, message, tool_name?, args?}`；夹具只留可复现的语义字段，
  不留对话原文（LLM trace 不入夹具，token 不膨胀）；
- 逐条断言：进树的 12 条投影后 `verdict != "accept"` 且有对应节点/策略；
  9 条 no_tool 不进的，断言树不吞（保持原 invalid 路径）；
- 生成夹具的脚本 `tools/gen_decision_tree_fixtures.py`（读 audit_log、按
  run_id 过滤、落夹具），再 `--check` 防漂移（沿用 golden 的同一套纪律）。

**阶段 2 — react/repair 投影接入**

- `tests/test_react_decision_tree.py`：`_dispatch_tool_calls` 前投影
  `camera.side='side'` → 执行的是合法值且审计多一条 `react_projected`；
  `look_at` 双写 → 按互斥字段归一后执行；
- 回归：`tests/test_driver_react.py`、`tests/test_driver.py` 原样过
  （vlm 树实际文件名，见 P1-3）；
- 修复路径复用同一棵树：同一非法提议在 `stage="repair"` 下投影结果与 react 一致。

**阶段 3 — B1 draft 投影接入**

- `tests/test_editor.py` 新增：draft 里 `camera.side='side'`、`finger_snap`、
  `look_at` 双写 → `extract_draft` 返回投影后的合法 draft，且
  `draft_projected` 审计在；
- 回归：`tests/test_editor.py`、`tests/test_draft_v15_schema.py` 原样过
  （vlm 树实际文件名，见 P1-3；watchdog 判据一字不动）。

**阶段 4 — 全链与探针**

- `python -m pytest`（全量）＋ `run_tests.ps1` 44/44；若新增探针，
  `tests/test_agents_status_is_current.py` 同步更新（状态行 N/N 一致）；
- 真跑 r7（当前会话模型，EEVEE，13 镜）复证判据 #3/#4 与 invalid 构成；
  预期不是 "invalid=0"——是 "语义越界 invalid 归零、no_tool 类由 prompt
  收窄/步数守卫兜底"。

**验收红线**：不得用投影绕过任何现有判据；`validate_args`/`action_param_problems`/
`validate_beats` 全部保留；投影只发生在它们之前，且每一条都留审计。

**阶段 4b — 逐镜预演编排（§3.6，方案 B：深度整合）**

- `tests/test_driver_per_shot.py`（纯层，注入假 builder/auditor）：
  - `plan_structured` 默认路径：`EDITING → PREPARE_SCENE → PER_SHOT →
    FINISHING`，`PREPARE_SCENE` 只调一次 `prepare_scene`，`_shot_queue`
    顺序与 `plan.shots` 一致；
  - 每镜 `PER_SHOT` 内：先 `project` → `regenerate_shot` → `_audit_shot`；
    passed → `shot_advanced` → 下一镜；失败 → REPAIRING/ReAct 回 PER_SHOT
    同一镜（`_current_shot_id` 不变、`_per_shot_iterations[shot_id]` 递增）；
  - **迭代不重做**：两轮之间断言 `prepare_scene` 调用数 == 1、`build` 调用数
    == 0（只走增量 `regenerate_shot`），第 2 轮 `regenerate_shot` 收到的
    参数是“同一镜的修订”，不是全量计划重建；
  - 下一镜不受污染：修 shot_004 后 shot_005 的相机/关键帧对象名与基线
    不变（`note_build` 之后 `dirty_ids()` 为空）。
- `tools/blender_tests/test_per_shot_previz.py`（bpy 探针）：
  - 两次迭代逐字节/仅 delta 变化：只清该镜 `[start, end]` 关键帧，
    其他镜关键帧计数不变；`bd_user_animated` 角色保留；
  - 轴传递：修 shot_N 后 `axis_for_shot(context, shot_N)` 返回的
    `established_side` 与主构建 `_axis_sides_used[shot_N]` 一致（新增
    回归夹具：同一工程整场构建 vs prepare+逐镜，逐镜机位 `matrix_world`
    与整场构建差异 < 1e-4——这是“逐镜不越轴”的硬断言）。
- 回归：`tests/test_driver.py`、`tests/test_scene_sync.py` 原样过；
  若协议加 `prepare_scene` 为可选方法，既有假 builder 测试不受破坏
  （`hasattr` 探测，不强制实现）。

**阶段 5 — 数值层（新增 `continuous_optimizer.py`，无 bpy，无第三方依赖）**

- `tests/test_continuous_optimizer.py`（纯层）：
  - **盒内收敛**：目标函数 = 带已知最优的凹/近似凹测试函数，`optimize` 结果
    在盒内、`value >= value0`、`calls <= max_calls`；
  - **硬违规拒绝**：目标函数在盒内某区域返回 `-inf`，断言优化器不选该候选、
    audit 里有对应 reason、结果仍合法；
  - **确定性**：同一 `seed` 两次 `optimize` 得到逐字节相同结果（含 audit）；
  - **零提升保底**：`improved=False` 时 `x == x0`（不许无提升改写）；
  - **越域拒绝（双段）**：把离散键/剧本硬值登记为 `OptVariable` →
    `OptDomainError`（登记期，不留审计）；x0 含未登记键或越盒值 →
    `optimize` 拒绝并留 `opt_rejected` 审计（与阶段 2/3 的树投影同源）；
  - **步长 agent 决定**：`step_scale` 缺键/非正/含未登记键 →
    `OptDomainError`；同一 x0 不同 `step_scale` 收敛轨迹不同；
    `opt_result` 审计记录生效步长，无自动推导兜底；**方法也由 agent
    决定**：`method_choice="gradient"` 打在不可微目标上（阶梯评分 /
    硬闸 `-inf` / 离散取值）→ 断言返回 `method_inapplicable` 回执（带
    evidence、不进入优化循环、不自动换方法），审计里
    `method_choice`/`method_reason` 原样可查；同一 x0 不同
    `method_choice`/`step_scale` 收敛轨迹不同；
  - **取整/clamp 次序**：带 `step` 的键，候选生成只认
    `clamp(round_to_step(clamp(x ± δ)))`（后 clamp 防取整顶出盒），
    越盒 rounding 实测反例写进测试；grid 键步长减半下限
    `max(tolerance, step/2)`，不烧预算；
  - **预算口径**：`calls <= max_calls` 含 x0 初始评测一次；
  - **x0 硬违规**：`score(x0) == -inf` → 立即返回 `x == x0`、
    `improved=False`、reason=`hard_violation_at_x0`，不自动找可行点；
  - **重启起点**：只从盒内均匀采样，必先 clamp 再评分；
  - **单位/盒来自真源**：对 `MOVEMENT_UNITS` 每一条运镜断言
    `OptVariable.unit/low/high` 与表一致；`lens ∈ [8, 300]`；
  - **与树接口**：`legal_space["opt_variables"]` 只含登记键，agent x0 只允许
    这些键。
- 回归：`tests/test_decision_tree.py` 原样过；审计事件断言落在 vlm 树实际
  文件（`tests/test_audit_contract.py` / `test_audit_logger.py` /
  `test_vlm_audit_events.py`，P1-3 已注明 vlm 树无 `test_audit_events.py`）。

**阶段 6 — 真跑 r7（当前会话模型，EEVEE，13 镜）**

- 复证判据 #3/#4 与 invalid 构成；数值层只对实测的构图门 / 运镜强度 /
  节奏维度启用，不在 r7 全量铺开；
- 数值层产出带审计（`opt_candidate`/`opt_result`/`opt_rejected`），
  结果由 agent 复核并标注 `refit_by`；震动类只出候选，交用户本人裁定；
- 回放链必须能完整重放数值层事件（`replay.py` 不炸）；
- `python -m pytest` 全量 ＋ `run_tests.ps1` 全链；状态行 N/N 与
  `tests/test_agents_status_is_current.py` 对拍。

**验收红线（数值层）**：自研实现 ≠ 降级——先按 §8.1 复用结论逐条排除可
引入库（含许可证门），再在纯层以标准库实现；不得因「scipy 装不上」就放
宽精度或跳过校验；画面效果（尤其震动）由用户本人裁定，不自动写回。

## 7. 待裁决 / 风险

**已裁决（2026-10-11，用户逐条拍板）**

- **D1 决策树投影（O）**：用户已批准——看门狗"只做无歧义归一"扩展为
  "每分镜一棵决策树、主动投影"，draft/react/repair 三轮共用同一棵树；
- **方案 B 深度整合（B）**：用户已选 B——直接改 `plan_structured` 主路径，
  默认所有真跑走 `PLANNING → EDITING → PREPARE_SCENE → PER_SHOT → FINISHING`，
  不新增旁路 mode；
- **数值层排期（O）**：用户已批准「树先、数值层后、r7 真跑验证」；
  连续优化作为决策树规划的数值层并入本文档；
- **学习率/步长与优化方法由 agent 决定（O）**：`step_scale` 逐键必填、
  `method_choice`/`method_reason` 必填；不得自动降级、不得替 agent 改方法；
- **连续优化 ≠ 梯度下降（O）**：评分函数不可微（§3.5.1 代码证据），
  用无导数算法（Hooke-Jeeves + 确定性随机重启），不按梯度下降实现；
- **画面裁定权（O）**：震动等无客观评分的项目，优化器只出候选、由用户
  本人拍板；agent 复核只标记 `refit_by`，绝不伪称 `human`；
- **r7 真跑模型（O）**：按用户裁决走**当前会话模型**（不再是 DeepSeek
  官方通道；r6 被 8×402 配额截断是旧通道的证据，不影响新路由）。

**仍待用户（仅剩真正未裁决项）**

- **r7 真跑额度**：当前会话模型通道的额度/预算尚未实测（r6 的 402 是旧
  通道读数）；阶段 0–3/5 的纯层与回归测试不依赖额度，可先做，r7 真跑
  待额度可用后执行并如实报告；
- **震动类画面效果**：优化器只出候选（确定性 seed 渲染 2–3 档），由用户
  本人裁定选档后才回写，绝不自动写回；
- **提交/合并顺序**：vlm 树 7 提交＋未提交改动、g8 树未提交、main 树未
  提交，三树有同名共享文件被各自改过；需要用户定合并顺序（禁 reset/
  checkout），本规划不越权提交。

**风险（已纳入设计，不再等待拍板）**

- 投影可能掩盖 agent 真实意图 → 审计字段必须完整，评审/人工可查
  （§3.6.4 T 的 `records[]` 全量投影记录）；
- 决策表与现有 watchdog/repair 重复 → 树作为单一真源，其余从它导入，
  `validate_args`/`validate_beats` 原样保留为事后兜底（§4 接入点表）；
- 组合爆炸 → 只对实测出问题的节点建树，不为所有字段建（§9）；
- 画面效果判定仍只由用户本人做；树不碰画面像素；
- **数值层不抢画面裁定权**：震动等无客观评分的项目，优化器只出候选、
  由用户本人拍板；agent 复核只标记 `refit_by`，绝不伪称 `human`；
- **数值层不得撞零依赖红线**：Blender 内置 Python 无 scipy（`pyproject.toml`
  无 `dependencies`），侧车/独立进程虽有 scipy 1.15.3，但优化器必须纯标准库
  实现；若未来要引入库，先按 §8.1 复用检查逐条过许可证门（GPL 禁入）；
- **两树判域差异（P1-2）**：`look_at` 互斥校验只在 g8 树未提交改动，
  vlm 树 `ACTION_PARAMS` 不含 `target`；接入前必须先统一（移植 g8 树的
  `motion/targets.py` 与 `_look_at_target_problems` 到 vlm 树）并以测试钉住，
  否则树在 vlm 树建不起来、或投影语义与 g8 判域不一致；
- **新增审计事件登记（P1-4/T）**：九类新事件（`draft_projected`/
  `react_projected`/`repair_projected`/`scene_prepared`/`shot_iteration`/
  `shot_advanced`/`opt_candidate`/`opt_result`/`opt_rejected`）必须登记进
  `contracts/audit.py::V16_EVENT_FIELDS`，否则 `missing_event_fields` 返回
  `<unregistered>` 且回放链抛 `ReplayError`；登记后同步
  `specs/openapi.yaml` 与测试。

## 8. 附录：r6 21 条 invalid 原始分组（2026-10-11 从审计日志读取）

> 证据位置更正：r6 证据目录在 **g8 复核树**
> `E:\bd_g8_rerun\docs\evidence\20261011-v16-g8-r6\`；vlm 工作树
> `E:\bd_vlm_v2` 下**没有**该目录。引用一律以 run_id `12dadce87acc` 与审计日志
> 为准（`%USERPROFILE%\Documents\BlockDirector Projects\runs\audit_log.jsonl`）。

```text
[draft_invalid] count=2
  shot_005: action_type='finger_snap' 不在动作类型闭集内（合法取值：walk_to、run_to、…）
  shot_012: look_at 不能同时写 target 与 yaw_deg/pitch_deg（无隐式优先级）
[react_invalid] count=12
  回复中没有工具调用 ×7
  emit_shot_draft: args.actions[0]（action_type=enter_from）不允许出现字段 target_position
  camera.side 自由文本 ×2（'front-right, same 180° side as shot_004'；
  '伊恩同侧（延续 shot_008 轴侧，不越轴）'）
  look_at 不能同时写 target 与 yaw_deg/pitch_deg ×2
[repair_invalid] count=7
  回复中没有工具调用 ×2
  emit_shot_draft: args.camera.side 取值必须 ∈ CAMERA_SIDES，实际 'side'
  look_at 不能同时写 target 与 yaw_deg/pitch_deg ×4
[self_review_invalid] count=1
  submit_review 参数不是合法 JSON: Expecting ',' delimiter: line 1 column 236
```

合计 21＋1（self_review 不计入交接的 21 项，单独列账）。

## 8.1 附录：数值层复用检查（GitHub，2026-10-11）

> hook 硬性要求：设计/规划类动笔前做复用检查，候选 ≥3，逐条填
> 「能否直接用/魔改点/撞哪条约束/结论/证据」，许可证门（MIT/Apache/BSD/ISC/
> MPL-2.0 可引入；GPL/AGPL 禁入）。

| 候选 | 许可证 | 能否直接用 | 魔改点 | 撞哪条约束 | 结论 |
|---|---|---|---|---|---|
| `scipy.optimize`（minimize / differential_evolution） | BSD-3 | 独立 Python 可用（本机 1.15.3 实测 import 通过） | 无 | **Blender 内置 Python 无 scipy**（`pyproject.toml` 无 dependencies；侧车才可依赖） | 引用其算法思路：Nelder-Mead / Powell / 边界处理；**不作为在 Blender 进程内的运行依赖** |
| `fchollet/nelder-mead` | **GPL-2.0** | 否 | — | 许可证门（GPL 禁入） | **禁入**；只能参考公开算法文本 |
| `owruby/nelder_mead` | MIT | 间接 | 需补盒约束与确定性种子 | 零依赖红线可破（MIT 可引入），但引入第三方与“纯标准库自研”冲突 | 参考实现结构；否则不引入，自研等价逻辑 |
| `CMA-ES/pycma` | NOASSERTION（含 GPL 组件） | 否 | — | 许可证门（断言不明，禁入） | **禁入** |
| `CyberAgentAILab/cmaes` | MIT | 间接 | 转译/裁剪为纯层标准库 | 引入第三方与零依赖冲突 | 参考 CMA-ES 思想；本项目目标多为低维盒约束，**不需要 CMA-ES 的协方差开销**，方案用 Hooke-Jeeves + 随机重启 |

**结论**：可引入候选无一能在不撞红线的前提下直接落地（scipy 只活在有依赖的
独立进程；GPL/不明许可证禁入；MIT 候选要么转译要么不引）。因此 v0.4 的
实现路径是——**引用公开算法思想，纯标准库自研 Hooke-Jeeves + 确定性随机
重启，~150 行**。这不是降级：无导数算法对该类不可微目标本来就更合适，
且实现后以测试（盒内收敛/硬违规拒绝/确定性/零提升保底）钉住，证据见阶段 5。

## 9. 审查视角覆盖（性能 / 鲁棒 / 安全）

**性能**
- 每镜只 `build_tree` 一次，缓存在 `driver._decision_trees[shot_id]`；
  draft/react/repair 三轮复用，不重复构建；计划合并/镜头切换时失效。
- `project()` 只对**实测出问题**的节点建树（`camera.side` / `look_at.target` /
  `movement` / `action_type` / `enter_from` 键集），不为全部字段建——组合爆炸
  控制在测试矩阵（21 条 invalid）覆盖的节点上；新增节点以新 invalid 实测触发，
  不以"预防性铺开"换取覆盖。
- 词形前缀 + 编辑距离投影只对**短字符串**（side token、角色 id）计算，
  不把整段自由文本当编辑距离对象；`side='front-right, same 180° side as shot_004'`
  先剥离自由文本再投影，避免 O(n²) 拖慢 react 热路径。
- 投影记录按 `{shot_id, stage, node_key, original, projected, verdict, reason}`
  单条写审计；**K（自查补丁 5）**：一次提议多处越界 → 每处一条记录、多条
  记录合进**同一个** `*_projected` 事件体的 `records[]`（一次提议 = 一个事件，
  不是 N 个事件；审计字段 §3.6.4 已定义）。**每镜每轮最多一条**与「每条留
  审计」不再矛盾：事件一条、记录 N 条。
- **数值层**：候选评测预算硬上限 `max_calls`（默认 40），超预算即停；
  `random_restarts` 的起点数随预算缩放（8–16），不随维度指数膨胀；
  盒边界与 `MOVEMENT_UNITS` 同源，优化器不做自己的第二份区间。

**鲁棒**
- `build_tree(shot, plan, contract)` 必须对 **缺失/空输入** 安全：
  `shot.characters` 空（空镜豁免）、`plan` 为 `None`、`contract` 为 `None`、
  `axis_state` 对无轴镜返回空、`shot_constraint_query` 检索失败返回空——
  全部有显式 fallback，且与现有 `deterministic_brief()` 同级（**不算降级**，
  是既有契约定义的合法分支）。
- `project()` 对**无法归一的提议**（编辑距离无近邻、数值域外无 clamp 语义）
  必须显式 `REJECTED` 并留 `reason`，**不得静默吞掉**；`validate_args` /
  `action_param_problems` / `validate_beats` 原样保留为兜底。
- 缓存失效条件要**可测试**：计划合并、镜头切换、`regenerate_shot` 后
  `_decision_trees[shot_id]` 必须重建，否则旧树投影新镜语义（阶段 2 测试覆盖）。
- 非法提议投影后的值**不得再触发二次越界**：投影结果必须再过一次
  `validate_args`（兜底），若仍越界则 `REJECTED`，不无限循环。
- **数值层**：`optimize` 对 `score` 抛异常不得静默吞掉——异常传播到调用方
  并记入审计；`-inf` 候选直接进入拒绝记录，不参与 argmax；
  `improved=False` 时结果恒等于 x0（零提升不改写）。
- **数值层**：确定性种子——同一 seed 两次 optimize 逐字节一致（含 audit），
  与 `camera_motion._noise` 同一纪律；随机重启只依赖 `random.Random(seed)`，
  不触全局 `random`。

**安全**
- 夹具 `tests/fixtures/decision_tree/r6_invalids.json` **只含可复现语义字段**
  （`kind/shot_id/message/tool_name?/args?`），**不含 LLM trace / 对话原文**；
  token 不膨胀、不泄剧本原文敏感片段。生成脚本 `--check` 防漂移，
  沿用 golden 同一套纪律。
- 新增审计事件 `draft_projected` / `react_projected` / `repair_projected`
  必须**先登记** `contracts/audit.py::V16_EVENT_FIELDS` 再使用
  （P1-4；未登记 `missing_event_fields` 返回 `<unregistered>`，回放链抛
  `ReplayError`）——这同时是**回放完整性红线**，不是性能优化。
- 树模块红线同 `contracts/`：**不 import `bpy`**；只调纯函数
  （`motion/model.py` / `cinema/framing.py` / `cinema/axis.py` / `contracts/`），
  由 `tests/test_decision_tree.py` 静态断言 + 全量 `pytest` 守。
- 投影不改判据/阈值/断言；验收是"语义越界 invalid 归零"，不是"invalid 变 0"；
  no_tool 类 9 条由 prompt 收窄 + 步数守卫兜底，树不越权。
- **数值层**：优化器不改判据/阈值/断言，也不碰画面判定权——震动等主观项
  只出候选（确定性 seed 渲染 2–3 档），由用户本人拍板；`refit_by` 如实标记
  复核方，绝不伪称 `human`。
- **数值层**：`opt_candidate`/`opt_result`/`opt_rejected` 必须先登记
  `V16_EVENT_FIELDS` 再使用（与 tree 投影事件同一红线），否则回放链抛
  `ReplayError`；登记后同步 `specs/openapi.yaml` 与测试。

## 10. 修订记录

- **v0.7（2026-10-12）**：逐镜版本历史接线落地（本会话收尾；全量 pytest
  **3678 passed / 2 skipped**，基线 3673 + 新增 5；最新全链证据
  `docs/evidence/20261012-220336/`，holdout_gates overall="pass"）：
  - **纯层**：`layer5_orchestrator/shot_versioning.py` 新增
    `ShotVersion`/`ShotVersionHistory`（append-only，version 从 0 连续、
    shot_id 一致、reason ∈ {initial, repair, react, rollback,
    manual_restore}，不可变 dataclass + 深拷贝 to_dict）。
  - **driver 接线**：`driver.py` 在 `_record_adversarial_review` 之后调用
    `_record_shot_version`（reason = rollback/repair/initial，用函数开头
    捕获的局部 `restored` 区分回滚）；公开只读接口
    `restore_shot_version(shot_id, version)`（缺失抛 KeyError）；历史随
    `ResumeState.version_histories` 落盘/恢复（`_checkpoint_resume` /
    `_apply_resume_state`，解析失败包 `ResumeStateError`）；`_advance_shot`
    不 pop 历史（跨镜保留，已加注释）。
  - **对抗审查**：`adversarial_review.py::review_shot` 确定性、可序列化，
    产出 `ReviewIssue`（severity 含 soft；安全区/九宫格为参考软尺，
    只记录不改 pass/score，硬判据仍为权威）。
  - **测试**：`tests/test_driver_shot_versioning.py` 5 用例（留痕/只读回溯、
    rollback 标记、resume 往返、跨镜保留、缺失镜抛 KeyError）；
    SPEC 组合回归 7 文件 51 条通过；`test_openapi_matches_contracts.py`、
        `test_agents_status_is_current.py` 通过。
- **v1.0（2026-10-18）**：D1 合入主仓库后的定稿记录——用户裁决 3「D1 合入
  main」执行完毕（集成分支 `codex/d1-merge` 三提交融合空间尺转正第一批
  `9f59ffa`/第二批 `cdae1a4`，ff 合入 main HEAD `72edc90`，台账 commit
  `aa7c142`）；合入后全量验证：main 树 pytest **4400 passed / 2 skipped /
  0 failed**（4402 tests，2026-10-18 实读，`-o addopts=""`）、per-shot Blender
  探针 5/5（含双人 MCU 组中心锚点判据）、gen_specs --check OK、六视角评审
  六份报告全通过（`E:\bd_vlm_v2\work\reviews\`）；设计文档随 D1 收尾归档主
  仓库 `v1.7/每分镜决策树设计_v1.0.md`。
- **v0.6（2026-10-12）**：D1 全部落地与 rk9 收尾后的定稿记账（全量 pytest
  **3650 passed / 2 skipped** 实测；per-shot 探针 3/3、operator-e2e 4/4、
  scene_sync 8/8；headless 全链 `built: true / DONE / 64 镜 / 139 LLM 调用 /
  每镜相机齐全`）：
  - **阶段 3（draft 投影）**：`editor.py::extract_draft` 增加可选 `tree` 参数
    （`:524`）；`ShotDraft.projection_records`（`:369-371`）不进 `to_dict`；
    REJECTED 合入 ValueError——`finger_snap` 保持 `draft_invalid`（不改判据、
    不降级）；`driver._finish_editor_turn`（`:1825`）传树、写 `draft_projected`
    事件（`:1863-1871`）、merge 后 evict 树。测试 `tests/test_editor.py` +3；
  - **阶段 4b 纯层**：`states.py` 加 `PREPARE_SCENE`/`PER_SHOT`；`builder.py`
    拆 `PreparableSceneBuilder`（可选方法 + isinstance 兼容，
    `prepare_scene`/`rebuild_shot` 见 `:46/:51`）；`driver.py` 的
    `_step_prepare_scene`（`:1989`）/`_step_per_shot`（`:2048`）/
    `_audit_and_route`/`_tree_for_shot`/`_advance_shot`（`:2453`，写
    `shot_advanced` 于 `:2475-2478`）/`_rollback_repair_if_worse` 增量分支。
    测试 `tests/test_driver_per_shot.py` 6 用例；
  - **阶段 4b bpy**：`shot_builder.py` 抽 `_prepare_static_scene` +
    `prepare_scene` 入口 + `BpySceneBuilder.prepare_scene/rebuild_shot`（rebuild
    带 get_synchronizer 回读）；`shot_regenerator.py` 轴状态推进
    （`context.axis_live_side`/`axis_spans`/`axis_advanced_shots`，`:172-223`）
    + `context.schedule[shot_id]` 写入（`:95-99`，修 E_GUARD_001「场景里没有
    镜头帧区间」）。探针 `tools/blender_tests/test_per_shot_previz.py` 3/3；
  - **opt_variables**：`decision_tree.build_tree` 的 `legal_space["opt_variables"]`
    （camera.lens + 各 MOVEMENT_UNITS.amount；scale 建议基准、step 按单位）；
  - **审计事件**：`contracts/audit.py::V16_EVENT_FIELDS` 九类已登记（`:58-109`，
    含 `draft_projected`/`react_projected`/`repair_projected`/`scene_prepared`/
    `shot_iteration`/`shot_advanced`/`opt_candidate`/`opt_result`/`opt_rejected`）；
    `specs/openapi.yaml` 已加 `V16EventRecord` schema（kind 枚举 22 项）+
    `tests/test_openapi_matches_contracts.py` 对拍；`tests/test_vlm_audit_events.py`；
  - **rk9 兼容与收尾修正**：`_step_prepare_scene` 补发 `scene_built`（driver.py
    `:2020-2032`，reason=`scene_built_reason(False, False)`，与交付链兼容）；
    `prepared_at` 用 `datetime.now(timezone.utc)`（`:2010`）修 1970 年；
    `_step_per_shot` 汇总计数（cameras/motions/keyframes 逐镜累计，headless
    实测 `cameras: 67/motions: 5/keyframes: 576`）；resume 方案 B
    （`_apply_resume_state` `:2944`：无待起草镜时 target 转
    `PREPARE_SCENE if _supports_prepare_scene() else BUILDING`）；results
    整体替换（同镜 rebuild 后整条替换、保留非 rebuild 键，新增
    `test_rebuild_result_replaces_shot_entry_and_preserves_audit_keys`）；
  - **§7 状态更新**：r7 真跑额度已由用户授权（2026-10-12「真跑采用当前会话
    模型」）；P1-2「两树判域差异」已落地（vlm 树已含 `motion/targets.py`）；
    剩余待用户项 = 震动类画面选档、三树合并顺序、主仓库 evidence 入库裁决。
  - **离线传输 REACT 分支（D1 回归收口）**：`offline.py` 在 `Purpose.EDITOR`
    分支后、兜底 `emit_plan` 前补 `Purpose.REACT` 分支，返回确定性
    `finish_shot`（带 `summary`），离线替身不再回兜底计划——此前 ReAct 请求
    落到 `emit_plan`，驱动记非法后重入，61 镜基线实测 0 交付、LLM 调用撞
    552 上限、CANCELLED；修复后同一基线 64 镜、138 次调用、6 镜完成、
    `react_rounds=1`。这是契约层（`contracts/tools.py::FINISH_SHOT`）对离线
    传输的修正，非行为变更文档；配套回归 3 条
    （`tests/test_offline_transport.py`）。判据与阈值一字未动。
- **v0.5（2026-10-11）**：用户裁决 B（深度整合）与 D1（决策树投影）后的
  定稿自查补丁 5，覆盖 A–X 全部缺口：
  - **A**：`DecisionNode.__post_init__` 强制 `allowed`/`range` 恰有一个非空，
    否则抛 `TreeBuildError`（§3.3）；
  - **B/E/H**：§3.6.4 逐镜模式转移统一——`_advance_shot` 转 `PER_SHOT`、
    REPAIRING/ReAct/REVIEWING 恢复出口统一走 `_resume_per_shot_or_checking()`，
    `_step_repairing` 无 `_pending_audit` 出口（`:2428`）同样走该 helper；
  - **B（回滚）**：`_rollback_repair_if_worse` 在 prepare 路径下不再整场
    rebuild——恢复 `_repair_baseline[shot_id]` 计划快照 → 更新
    `self.plan`/`context.plan` → `regenerate_shot` 重做当前镜（增量）→
    转 `PER_SHOT`；旧 BUILDING 整场重建只留给无 `prepare_scene` 的假 builder
    兼容回退（§3.6.4 第 4 项、§3.6.5）；
  - **C**：`SceneBuilder` 协议加可选方法 `prepare_scene`，用 `hasattr`
    探测；无实现时退回旧 `build` 整场路径（兼容回退，不算降级；真跑主路径
    一定用 prepare→逐镜）（§3.6.4 第 3 项）；
  - **D**：`build_tree(shot, plan, contract, axis_side=None)` 增加轴侧注入；
    轴侧真源两条定义——纯层用 `axis.py::axis_state` 预测，驱动注入
    `_axis_sides_used` 实际值；`regenerate_shot` 必须接
    `axis_for_shot(context, shot)` 传给 `place_shot_camera`（§3.4、§3.6.4
    第 5 项）；
  - **F/G/U/V/W**：交付 `build_summary["results"]` 表在 `PREPARE_SCENE` 就
    初始化，`_record_vlm_review`/`_record_justification_audit` 不再因缺表
    静默跳过（§3.6.4 第 4 项、§7）；
  - **I**：投影覆盖嵌套路径——`camera.side`/`actions[*].params`/`beats[*]`/
    `movements[*]`，一次提议多处越界 = 多条 `ProjectionRecord` 合进一个
    事件的 `records[]`；§4 增加工具 → 投影路径映射表；
  - **J**：见 A（同一条 `__post_init__` 强约束）；
  - **K**：性能条目修正——每镜每轮最多一个 `*_projected` 事件、事件内
    `records[]` 可含 N 条记录，「每镜每轮最多一条」与「每条留审计」不再
    矛盾（§9）；
  - **L/M**：`OptProblem.score_kind` 由 agent 声明；`_check_method_applicable`
    第一判据 = 声明；运行期遇 `-inf`/NaN 回执 `method_inapplicable`；
    `OptProblem` 语法修正（`shot_id`/`stage` 移到带默认值字段前）（§3.5.1）；
  - **O**：§7 重写——D1、B、数值层排期、agent 决定步长/方法、连续优化≠
    梯度下降、画面裁定权、r7 当前会话模型全部标为**已裁决**，仅保留真正
    剩余裁决（r7 真跑额度、震动类画面选档、三树合并顺序）；
  - **S**：§3.6.6 树失效/缓存重建四条件（计划合并、镜头切换、`update_plan`/
    `regenerate_shot` 路径、轴状态变化）；
  - **T**：§3.6.4 九类新事件的最小形状逐一定义，登记顺序纪律
    （`V16_EVENT_FIELDS` → `openapi.yaml` → 测试）。
- **v0.4（2026-10-11）**：新增「数值层（连续优化）」（§3.5）——明确评分
  函数不可微（`cinema/composition.py` 逐行证据），因此用无导数优化
  （Hooke-Jeeves + 确定性随机重启）而非梯度下降；新增
  `continuous_optimizer.py` 数据结构与算法（OptVariable/OptProblem/OptResult/
  optimize/_clamp_value/_hooke_jeeves/_random_restarts/_evaluate）；树与优化器
  分工与硬边界（优化器只动 `legal_space` 登记键、剧本硬值不寻优、震动类只出
  候选交用户裁定）；连续键真源表（lens/MOVEMENT_UNITS/ACTION_PARAMS 数值键/
  beats[].t）；新增审计事件 `opt_candidate`/`opt_result`/`opt_rejected` 及
  登记红线；阶段 5 纯层测试（盒内收敛/硬违规拒绝/确定性/零提升保底/越域
  拒绝/真源对拍）与阶段 6 r7 真跑；§8.1 GitHub 复用检查（scipy 仅独立进程
  可用、GPL 禁入、MIT 候选不引入自研等价逻辑）；§7 风险补充数值层三条；
  §9 补数值层性能/鲁棒/安全条目；并修正 r6 证据目录位置（在 g8 复核树
  `E:\bd_g8_rerun\`，vlm 树无此目录）。
- **v0.4 自查补丁（2026-10-11）**：按用户批注把「学习率等价参数」落成
  `OptProblem.step_scale`（必填、逐键 >0、agent 决定，缺键/非正/含未登记键
  登记期抛 `OptDomainError`，无自动推导兜底，`default_step_scale` 只作建议；
  生效值进 `opt_result` 审计）；补 `OptDomainError` 定义并明确「登记期抛
  错不留审计 / 运行期 x0 越域留 `opt_rejected`」双段拒绝；§5 证据路径改完整
  全路径；§3.5.5 强调构图离线优化不改变判据 #3 口径（仍读运行时
  `audit_pass_rate`，离线分不替代）；§3.5.1 显式声明「学习率类参数由 agent
  决定」是通用原则（将来即便子目标可微、改用梯度类方法也一样）；补算法
  边界细节（取整/clamp 次序、grid 键终止下限、预算含 x0、x0 硬违规直接
  返回、重启起点盒内采样）并同步进阶段 5 测试计划。
- **v0.4 自查补丁 2（2026-10-11）**：按用户批注「梯度下降的使用也是需要
  agent 进行规划和使用」把**方法选择本身**落成 agent 决策：
  `OptProblem.method_choice`/`method_reason` 必填、`optimize(problem)` 不再
  接受 method 参数、`_check_method_applicable` 判定（agent 选 `"gradient"`
  但目标不可微 → 返回 `method_inapplicable`，不自动降级、不换方法、不吞
  错误）；`opt_result` 审计增加 `method_choice`/`method_reason` 字段；
  阶段 5 测试计划增加「方法不可微」与「同一 x0 不同方法轨迹不同」两条断言。
- **v0.4 自查补丁 3（2026-10-11）**：修正两处与代码真源不符的表述——
  `over_shoulder_A/B` 在 `framing.py::CAMERA_SIDES`（`:342`）并不存在，
  只有 `over_shoulder` 一个 token，OTS/POV 的过肩方向由轴侧闭集映射为
  `front_left`/`front_right`（§2 示例、§3.4 唯一化、阶段 0 测试计划同步
  修正）；阶段 1 夹具描述从「21 条全导出」改为「只导出进树的 12 条」
  （draft 2 + react 5 + repair 5；9 条 no_tool 与 1 条 self_review JSON
  语法错不进夹具，§5 表格原本就是 12 条口径，§6 与它对齐）。
- **v0.4 自查补丁 4（2026-10-11）**：按用户裁决「方案 B：深度整合——
  直接改现有 plan_structured 主路径，默认所有真跑走准备→逐镜」新增
  §3.6「执行编排：场景/元素就位 → 逐镜剧情预演循环」——默认主路径
  `PLANNING → EDITING → PREPARE_SCENE → PER_SHOT → FINISHING`（不新增
  mode）；新状态 `PREPARE_SCENE`/`PER_SHOT`；`prepare_scene` 只建场景与
  元素、不摆相机/不烘焙动作；逐镜循环 = 决策树投影 → `regenerate_shot`
  增量重建（只清该镜帧窗、只换该镜相机）→ 审核 → 不干净在本镜内迭代 →
  通过才 `_advance_shot`；「迭代是逐渐调整，不是重做」钉成硬纪律；
  关键缺口标注：`regenerate_shot` 必须接 `axis_for_shot`（`_axis_sides_used`/
  `_axis_lines_used`），否则逐镜重建越轴；新增审计事件
  `scene_prepared`/`shot_iteration`/`shot_advanced`（先登记
  `V16_EVENT_FIELDS` 再用）；阶段 4b 纯层 + bpy 探针测试计划（逐镜与
  整场构建机位一致 <1e-4、迭代不重做、下一镜不污染）。
- **v0.3（2026-10-11）**：修正 r6 分组账目（P1-1，react 12 = 7 no_tool + 1
  enter_from + 2 look_at 双写 + **2 camera.side 自由文本**；repair 7 = 2 no_tool +
  1 side + **4 look_at 双写、无 JSON**；进树 **12** 条 = draft 2 + react 5 +
  repair 5，no_tool 9 条不进树）；标注 `look_at` 互斥判域只在 g8 树未提交
  （P1-2）；修正回归测试文件名以 vlm 树为准（P1-3，`test_react_finish_required.py`
  与 `test_draft_watchdog.py` 不在 vlm 树）；补新增审计事件登记要求（P1-4，
  `V16_EVENT_FIELDS` + 回放链 `ReplayError`）。
