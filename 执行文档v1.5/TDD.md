# TDD —— BlockDirector 执行文档 v1.5 技术设计文档

版本：执行文档 v1.5 草案（2026-10-07；目录 `docs/执行文档v1.5/`）
对应 PRD：同目录 `PRD.md`
阅读约定：本文所有路径相对仓库根 `E:\白模预演codex`；引用的现有文件/字段
均在撰写时核对过（2026-10-07，HEAD `f6530c6`）。

---

## 1. 设计原则（来自两份调研报告，作为本版架构公理）

1. **LLM 只输出"有限词表能表达的决策"**。取值空间能枚举成词表的（景别、运镜、
   动词、情绪、灯光语义）交给 LLM 并用 enum 锁死；连续数值（帧号、坐标、弧度）
   是求解器的输出，不是 LLM 的输出。
2. **解构单位是"镜"，原子粒度是"拍点"**。一镜一份契约，可独立校验、独立重生成；
   镜内 2–5 个拍点，归一化时机 t∈[0,1]，与具体时长换算解耦。
3. **规则按约束性质分流到四条通道**（§5），硬性程度与"违反后的失败成本"挂钩；
   规则的最大价值不在"被遵守"，而在"被引用"。
4. **契约是唯一事实来源**：Blender 场景永远可以从契约重新生成；用户在 Blender
   里的手调要么回写契约、要么明确标记一次性覆写（现有 scene_sync 机制延续）。
5. **判据不动**（红线 R-5）；新机制先诊断、后设门，设门必须经用户裁决。

## 2. 架构总览与新增部件落点

```
剧本 ──► layer1_input（fountain/fdx/shotlist 解析，无 LLM）
        ──► 阶段 S：understand.py → SceneBrief（已有；其 beats 是叙事节拍，
        │                                    与拍点表无关，见 §3.1 消歧）
        ──► 阶段 A：planner.py → emit_plan → Plan（schema 增 environment：
        │            anchors/light，场级声明只生成一次）
        ──► 阶段 B1：editor.py → emit_shot_draft → 逐镜草案（schema 升级）
              ▲                │
              │ 知识注入        ▼
        knowledge/retriever   【新】拍点表 beats[] ──► 【新】beat_compiler
        （三通道 + 规则包渲染    （t/verb/target/pace）      （t→帧，face_to→朝向，
         升级 + forbid 反查）                              target→锚点坐标）
              ▲                │                            │ 编译产出现有 actions[]
              │                ▼                            ▼
        超图 hg/v2      Plan/ShotPlan（契约升级，SDL 1.5）─► layer3_engine 构建
                                                              │
        规则裁判通道：rule_checker（R001–R012/R019）+ compliance.py（R013/R015）
                     + shot_auditor（已有）+ 【新】破例辩护对拍（declared vs detected）
                     + 【P2 可选】VLM 评审外回路
```

**新增文件**（全部为纯 Python、不 import bpy，除非注明）：

| 新文件 | 职责 |
|---|---|
| `block_director/contracts/beats.py` | ShotBeat/LightSpec/CompositionSpec/RuleJustification 数据类 + 校验 |
| `block_director/layer5_orchestrator/beat_compiler.py` | 拍点表 → 现有 actions[] 的确定性编译 |
| `block_director/knowledge/rulepack.py` | 规则包装配：强度渲染、top-k 预算、冲突并陈、自由度声明 |
| `tests/test_beats.py` / `test_beat_compiler.py` / `test_rulepack.py` / `test_sdl_15.py` 等 | 单测 |
| `docs/knowledge/JUDGE_ALIGNMENT_v1.md` | 评委口径对齐方案（FX-7，备料） |
| `docs/knowledge/REGEN_LOG_TEMPLATE.md` | 换代登记模板（A6 机制的动作件） |

**修改文件**：`contracts/plan.py`、`contracts/sdl.py`、`contracts/config.py`、
`layer2_sdl/sdl_migrate.py`、`layer5_orchestrator/editor.py`（schema+合并）、
`layer5_orchestrator/planner.py`（emit_plan schema 增 environment）、
`layer5_orchestrator/scene_contract.py`（检索种子接线，§5.7）、
`layer3_engine/scene_executor.py`（灯光矩阵/道具事件/锚点落位）、
`knowledge/client.py`（三栏渲染接 rulepack）、`knowledge/retriever.py`
（forbid 反查）、`layer8_delivery/export_director.py`（shots.json 新字段）、
`specs/openapi.yaml`（同步）、`fixtures/expected_*.json`（**只经
`tools/gen_golden.py` 重生成**，红线 R-11）、
`specs/config.default.yaml`（由 `tools/gen_specs.py` 生成，**不手改**）。

## 3. 契约设计（核心）

### 3.1 ShotBeat（拍点）——`contracts/beats.py`

> **命名消歧（重要）**：`contracts/brief.py::SceneBrief.beats` 是**叙事节拍**
> （`{id, summary, participants, emotion, function}`，阶段 S 对剧本的理解产物）；
> 本节的 `ShotBeat` 是**执行拍点**（一镜内的动作时刻表）。两者概念不同、
> 生产者不同、消费者不同，**不得互相喂入、不得合并**。类名刻意用
> `ShotBeat` 而不是 `Beat`，防止与 brief.beats 在阅读和维护时混淆。
> ShotPlan 上的字段名仍叫 `beats`（JSON 契约面简洁），但代码注释必须写明
> "这是执行拍点表，不是 SceneBrief.beats"。

```python
@dataclass
class ShotBeat:
    t: float            # 归一化时机，0.0–1.0，镜内单调不减
    subject: str        # character_id；必须在 cast 里
    verb: str           # 枚举，见下
    target: str = ""    # 锚点名（staging anchors）或 character_id；可空
    face_to: str = ""   # character_id / screen_left / screen_right / camera / away；可空
    pace: str = ""      # slow / normal / brisk；可空（缺省 normal）
    react: str = ""     # 情绪反应标签（自由短文本，仅注释用）；可空
```

**verb 词表**（闭集；可执行动词必须落在既有 `motion/model.py::ACTION_TYPES`，
语义动词由编译器映射，词表真源仍在 motion/model.py——本表新增键必须先进
ACTION_TYPES/ACTION_PARAMS，红线 R-7）：

| 类别 | verb | 编译目标 |
|---|---|---|
| 移动 | `walk_to` `run_to`（已有） | 直通 actions |
| 入场/出场 | `enter_from` `exit_frame`（**新增**，语义级） | walk_to，起点/终点在画外锚点 |
| 姿态 | `sit` `stand` `turn_body` `jump`（已有） | 直通 |
| 头部/视线 | `look_at` `turn_head` `nod` `shake_head`（已有） | 直通；`face_to` 折算成 look_at 参数 |
| 上身 | `body_tilt` `fall_down`（已有） | 直通 |
| 道具交互 | `place_prop` `pick_up` `hand_to`（**新增**，语义级） | 道具交互事件（§4.4） |

**不变量**（`validate_beats()`，纯函数）：
- `0.0 ≤ t ≤ 1.0`；同一 subject 的拍点按 t 单调不减；
- `subject` 必须在该镜 characters 内；`target` 非空时必须能在本场锚点表或 cast 解析；
- `face_to`/`pace` 非空时必须在各自闭集内；
- 每镜拍点数 ≤ 8（schema 层 maxItems=8）。

### 3.2 Plan 级环境宿主：anchors 与 light 的生产者

`Plan` 类（`contracts/plan.py:155`）目前只有 `shots/continuity_notes/
scene_heading`——场级环境**没有契约宿主**。本版新增：

```python
@dataclass
class Plan:
    ...  # 既有字段不动
    environment: Dict[str, Any] = field(default_factory=dict)
    # 形状：{"anchors": [SDLAnchor 的 dict 形...], "light": LightSpec 的 dict 形}
```

- **生产者 = 阶段 A 的 emit_plan**：`planner.py`（`:45-72` 的
  emit_plan 参数 schema 定义处）增加 optional `environment` 键。场级信息密度低、
  稳定性高，一次生成全场共用（粒度报告 §4.1"场"层）。
- 阶段 B1 不得改写 environment（单镜草案只管单镜）；该纪律写进 editor 提示词。
- 消费者：`build_scene`（锚点摆位 §4.3、灯光矩阵 §4.5）、`shot_constraint_query`
  （§5.7 种子接线）、SDL 导出。

### 3.3 Staging 锚点——`contracts/sdl.py` 扩展

```python
@dataclass
class SDLAnchor:
    name: str                  # "door" / "table" / "window" …，场景内唯一
    depth: str = "mid"         # fg / mid / bg（纵深分层，相对相机视角）
    relation: str = ""         # 自然语言方位："behind 甲" / "between 甲 and 乙"
    position: List[float] = field(default_factory=list)  # 求解器回填；LLM 不写
```

- `SDLEnvironment.anchors: List[SDLAnchor]`，新增可选字段，缺省空表。
- relation 由**摆位求解器**（§4.3）解析为坐标；LLM 只写 relation 与 depth。

### 3.4 灯光语义——`contracts/beats.py::LightSpec`

```python
@dataclass
class LightSpec:
    time_of_day: str = ""   # day / night / dusk / dawn；空 = 不声明
    mood: str = ""          # bright / neutral / gloomy / tense / soft；空 = 不声明
    key_direction: str = "" # front / side / back；可空
```

落点：`Plan.environment.light`（契约面）→ `SDLEnvironment.light`（持久层）。
**语义 → 预设矩阵**（§4.5），绝不向 LLM 开放灯具参数（energy/color/size）。

### 3.5 构图声明——`contracts/beats.py::CompositionSpec`

```python
@dataclass
class CompositionSpec:
    rule: str = ""             # thirds / center / symmetry / diagonal /
                               # frame_within_frame / lead_room；空 = 求解器默认
    subject_position: str = "" # left_third / right_third / center；空 = 默认
```

落点：`ShotPlan.composition`、`SDLShot.composition`。消费方式：取景求解器的
对准点偏移（§4.6）＋ 检索种子（§5.7），**不动冻结几何 1.70 与"头球相切"
（ADR-0007）**。

### 3.6 破例辩护——`contracts/beats.py::RuleJustification`

```python
@dataclass
class RuleJustification:
    rule: str      # 规则/边的标识（edge_id 或规则名）
    action: str    # "follow" / "break"
    reason: str    # 叙事理由（break 时必填）
    precedent: str = ""  # 破例先例（影片/案例 id），break 时建议填
```

落点：`ShotPlan.rule_justifications: List[RuleJustification]`。
审计对拍见 §5.4。

### 3.7 ShotPlan 字段变更清单（`contracts/plan.py`）

新增（全部可选、有缺省，`to_dict/from_dict` 同步）：
`beats: List[Dict]`（ShotBeat 的 dict 形）、`composition: Dict`、
`rule_justifications: List[Dict]`；`Plan` 增 `environment: Dict`（§3.2）。

**不改**：`duration_frames` 唯一时长真源地位；`declared_*` 证据字段语义；
既有任何字段的名字与类型。

### 3.8 emit_plan / emit_shot_draft schema 变更

**emit_plan**（`planner.py` 的 schema 定义处，`:45-72`）：
- 增 optional `environment`：扁平 object，`anchors`（array，maxItems=12，
  item `{name, depth: enum[fg,mid,bg], relation}`）+ `light`（扁平 object，
  三个 enum 字段），`additionalProperties: False`。

**emit_shot_draft**（`editor.py::EMIT_SHOT_DRAFT_PARAMETERS`）properties 增加：
- `beats`：array，maxItems=8，item 扁平 object：`{t:number(0..1), subject:string,
  verb:enum(来自 ACTION_TYPES 渲染), target:string, face_to:enum, pace:enum,
  react:string}`，`additionalProperties: False`；
- `composition`：扁平 object，两个 enum 字段；
- `rule_justifications`：array，maxItems=6，item `{rule, action:enum, reason, precedent}`。

Schema 纪律（粒度报告 §2.2）：**扁平优先、必填优先、枚举优先**——只锁词汇与
语法，绝不锁选择；`actions[]` 保留（兼容与直写通道），beats 与 actions 同镜
并存时编译器负责合并（§4.2 冲突规则）。

**离线/回放兼容**：`layer5_orchestrator/offline.py` 与
`tests/test_protocol_end_to_end.py` 的既有夹具不含新字段——新字段全 optional，
离线应答可以不产出；升级后这些测试必须**无新增失败**（P2-T4 验收的一部分）。

### 3.9 SDL 1.5 与迁移（`contracts/sdl.py`、`layer2_sdl/sdl_migrate.py`）

- `SDL_VERSION = "1.5"`；`sdl_migrate.KNOWN_VERSIONS` 现含
  `("1.0","1.1","1.2","1.3","1.4")`，追加 `"1.5"`；
- 迁移 1.4→1.5：纯增字段，迁移 = 缺省填充，**无删除、无改名**；
- 1.4 工程加载：所有新字段缺省 ⇒ 行为与升级前逐字节一致（迁移测试断言）；
- KNOWN_VERSIONS 只增不改；1.2 之前的 roster 修复逻辑不受影响。

**golden 夹具同步（红线 R-11 的首次应用）**：`fixtures/expected_sdl_simple.json`
第 3 行钉着 `"version": "1.4"`，`expected_shots_long.json` 含 shots.json 全字段
——版本号与新键会让 `tools/gen_golden.py --check` 漂移失败。流程：先 diff 确认
变化**只有版本号与新增可选字段** → 跑 `python tools/gen_golden.py` 重生成 →
夹具 diff 与代码改动同批提交。任何超出"纯新增"的漂移都停下来升级给用户。

## 4. 编译与求解层

### 4.1 beat_compiler：t → 帧

`compile_beats(shot: ShotPlan, anchors, cast) -> List[action dict]`，纯函数：

- `start_frame = max(1, round(t * shot.duration_frames))`；`end_frame` 由动词
  时长表给（walk_to 由距离/步速估，look_at 类固定 12 帧，可配置表
  `BEAT_DURATION_TABLE`）；同 subject 串行（沿用 §9.7 同层冲突仲裁）；
- **走位起点接力**（§六十四纪律）：walk_to/run_to 的缺省起点 = 该角色
  **当前位置**（上一拍/上一镜的落点），不是剧本起始站位；
- 与 `dialogue_pins[]` 对齐：对白时段内的拍点不得覆盖说话人嘴部窗口
  （沿用 dialogue_budget 的口径）；
- **用户动画保护**：`bd_user_animated` 标记的角色不生成/不覆盖关键帧
  （与 regenerate_shot 同纪律）；
- 输出形状与现有 `actions[]` **完全一致**——下游 builder/auditor/R003 零改动。

### 4.2 beats 与直写 actions 的合并规则

同镜同时存在时：同 subject 同动词且帧窗重叠 >50% 视为重复，**beats 编译结果
优先**（因为它是语义层）；其余直写 actions 原样保留，合并后过 R003 检查。

### 4.3 锚点摆位求解（relation → 坐标）

`scene_executor.build_environment` 前置一步 `solve_anchors()`：
- `behind X`：X 的背向 2.0 m；`between A and B`：中点；`left_of X 2m` 这类
  带距离的用 X 的局部左向；解析不出 → 记 `unresolved_anchor` 并放场景原点
  附近缺省位，**不猜复杂关系**（沿用 SceneBrief"不猜代词"纪律）；
- 锚点落成 `BD_Anchor_*` empty，进 Guides 集合，`hide_render=True`；
- 锚点必须接入导出审计的 helper 白名单（既有"helper 不得泄漏进参考视频"
  检查），否则导出会被拒。

### 4.4 道具交互事件

`place_prop/pick_up/hand_to` 编译为：道具对象关键帧 + 起止区间内的
Child Of（或纯父子）跟随角色手部代理；未交互的道具**不打关键帧**
（粒度报告 §3 修正表）。Workbench 无 alpha 的既有告警逻辑复用。

### 4.5 灯光语义 → 预设矩阵

`scene_executor.LIGHTING_PRESETS` 新增矩阵键（既有 clay_studio/indoor_soft/
outdoor_sun/night/studio3p 五键不动）：

| time_of_day \ mood | bright | neutral | gloomy/tense | soft |
|---|---|---|---|---|
| day | outdoor_sun | clay_studio | indoor_soft | indoor_soft |
| night | studio3p | night | night | night |
| dusk/dawn | outdoor_sun | indoor_soft | indoor_soft | indoor_soft |

映射函数 `resolve_lighting_preset(LightSpec) -> str` 纯函数；`key_direction`
仅在有对应预设变体时生效，否则忽略并记 trace。未知组合回退 `clay_studio`。
矩阵内容是**设计表**，后续调表不动代码结构。

### 4.6 构图声明消费

`cinema/framing.py` 求解后、写机位前：
- `subject_position=left_third/right_third` → 对准点沿画面横向偏移 1/6 幅宽
  （沿用 §六十八已验证的"横移六分之一幅宽"机制）；
- `rule=lead_room` → 朝角色面朝方向偏；`center/symmetry` → 居中（显式覆盖
  thirds 默认）；`diagonal/frame_within_frame` 本版只记录、进 prompt 知识，
  不改几何（求解器不支持时**降级为记录**，不硬解）；
- 一切偏移走 `cinema/anchor.py` 的派生链，冻结几何 1.70 与头球相切不动；
- **空声明 = 现状逐字节一致**（单测断言）。

## 5. 规则四通道架构（"约束不损泛化"的落地）

| 通道 | 内容 | 现状 | 本版动作 |
|---|---|---|---|
| 1 硬约束 | 越轴/遮挡/穿模/时长/几何 | R001–R012/R019（`layer3_engine/rule_checker.py`）＋ R013/R015（`layer5_orchestrator/compliance.py`）＋ shot_auditor ＋ 构图门（R014 已按 X6 删除） | **不动**；继续不进 prompt |
| 2 半硬 | 词汇与语法 | 严格 tool schema（已有） | beats/composition/justifications/environment 进 schema（§3.8） |
| 3 软引导 | 原则/例外/强度/先例 | 三栏注入已有，渲染无强度 | **rulepack.py 升级渲染与装配**（§5.1–5.3）＋种子接线（§5.7） |
| 4 裁判 | 生成后把关 | R 系列 + 构图分（已有） | 破例辩护对拍（§5.4）；VLM 外回路（P2，§5.5） |

### 5.1 规则包渲染（`knowledge/rulepack.py::render_rule_pack`）

对每条注入的超边渲染一行：
`[必须] 轴线：对话双方机位待在轴线同侧（先例：常规正反打）｜例外：需表现关系破裂时可越轴（先例：《闪灵》）`
- hardness=hard → `[必须（除非声明破例）]`；soft → `[通常]`；
- 边的例外/先例成员存在即渲染，不存在不编；
- **原子注入**纪律不变：整条边装不下就整条不注入并记 dropped，
  绝不截断（`client.py::render_edge_block` 既有契约）。

### 5.2 规则预算与冲突并陈

- 配置 `rag.rule_top_k`（int，默认 5，合法区间 3–8；`config.py` 校验 +
  `tools/gen_specs.py` 同步）；整场预取沿用 `plan_prefetch_tokens` 不动；
- **与 token 上限的关系**：三栏共享的 800/2000 token 上限照旧生效，
  规则包在该上限内装配；条数预算与 token 上限**取紧者**；
- 装配时按 (类型, 主键值) 分桶，同桶超过预算 → 按 confidence×occurrences 截断；
- **冲突检测**：同桶内结论互斥（同 kind 不同值，或一条命中 allow 一条命中
  其 forbid）→ 两条都保留并在文本里并陈：`[冲突] A … ｜ B …（更具体者优先，
  由你裁决）`；冲突对不受预算截断（宁可超一条，不藏冲突）；
- forbid 补挂的边同样不受预算截断（§5.6）。

### 5.3 自由度声明

规则包末尾固定一段：本场戏**已有强惯例的维度**（被 hard 边覆盖的 kind）与
**刻意留白的维度**（未命中的 kind）各列一行。给 LLM 明确的创作空间边界，
对应规则报告 §3.2 的"部分约束"。

### 5.4 破例辩护对拍（裁判通道）

`shot_auditor` 增加对照（**只记录、不设门**）：
- `declared_breaks` = rule_justifications 里 action=break 的规则集；
- `detected_violations` = R 系列实际报出的违规；
- 输出 `undeclared_violations = detected − declared` 与 `declared_but_clean`。
该对照写进 shot_audit 一行与 shots.json；**是否设门须用户裁决**（对齐
OPEN_ITEMS D11 的"看得见的降级"议题，先诊断）。

### 5.5 VLM 评审外回路（P2，默认关）

配置 `vlm_review.enabled=false`。开启时：每镜首帧/中帧/末帧 + intent +
composition 声明 → VLM 打 1–5 分＋一句理由，仅用于候选排序与人审参考，
**不作唯一裁决**（ShotBench：最强通用 VLM 摄影维度准确率仅约 59%）。
评委不可用时跳过并记录（README 环境约束）；GLM 类调用串行不并发。

### 5.6 forbid 反查补挂（守门激活，FX-3/FR-9）

在 `knowledge/retriever.py` 装配阶段（不改索引、不改判据）：

```
seeds = 本轮命中的 (kind, value)
for edge in NodeIndex 中满足：
    edge 有 role=forbid 的成员 m_f，且
    edge 的某个 allow 成员 (kind,value) ∈ seeds：
        把 edge 以"禁忌补挂"名义加入候选，渲染排最前
trace 记录：forbid_backfilled=<条数>、forbid_members_seen=<成员数>
```

验收：三份冻结工程同代重建，`forbid_members_seen > 0`，且
Q1/Q2/Q5/E1 同口径读数不回退（前后对跑留证据，并入阶段门 G4）。

### 5.7 新字段的检索种子接线（构图/光线）

`hypergraph.py::QUERY_KEYS` 已有 `构图→composition_rule` 与 `光线→lighting`
两个键，但生产侧 `scene_contract.shot_constraint_query` 从不产出它们——
新增字段不接进去，FR-10 的"构图知识进 prompt"就没有数据通路。

接线（`layer5_orchestrator/scene_contract.py`）：
- `add("构图", [shot.composition.get("rule")])`（空值不写，沿用"只写有值的键"纪律）；
- `add("光线", [plan.environment.light 的 time_of_day/mood 组合取值])`——
  **先核对 `VALUE_DOMAINS["lighting"]` 的闭集**，取值不在闭集内就不写
  （死值会污染查询，§2.3b 的教训）；
- 逐镜查询在 editor.py 每镜发起，接线后同一份工程的查询串形状变化 ⇒
  **Q5 的对拍口径随之变化**，前后对照必须同代测量（并入 G4，不许混代比）。

### 5.8 明确不做的两件事（反范围蔓延）

两份报告的字面建议里，有两条在本项目**已有等价物**，照字面施工等于返工：

1. **不引入 PSL 散文分镜中间层**。报告 1 的"散文分镜 + 约束解码"解决的是
   "自由文本 → 可执行"的无结构问题；本项目的 JSON 契约链
   （emit_plan → emit_shot_draft → ShotPlan/SDL）已经是可解析、可约束解码、
   人可读的中间层，且比散文更严。再插一层 PSL 只会多一次有损翻译。
2. **不重建相机 rig**。报告 2 的"empty rig + Track-To"建议，本项目已实现
   （`move_camera` 移动 Track-To target 沿弧运动、无欧拉翻转，24 运镜全部
   经声明式消费落地）。保持现状。

## 6. 端到端数据流（变更后）

1. layer1 解析剧本（无 LLM）→ 场标/动作行/对白/分镜表声明；
2. 阶段 S：SceneBrief（speakers/gaze/**叙事节拍**/space/arc/props）；失败两连退
   deterministic_brief（已有）；
3. 阶段 A：emit_plan（拍摄清单 + intent_type 闭集 + **environment 场级声明**）；
4. 阶段 B1：逐镜 emit_shot_draft——schema 现含 beats/composition/
   rule_justifications；prompt 里的知识块由 rulepack 渲染（§5.1–5.3），
   查询串含新种子（§5.7）；
5. 合并回 ShotPlan（镜号/顺序/时长仍归计划所有）→ beat_compiler 编译出
   actions → SceneContract 校验（角色/锚点引用、说话人状态）；
6. B2 构建：solve_anchors → 环境（含灯光矩阵）→ 角色 → 道具事件 →
   相机（24 运镜，构图声明偏置）→ 排片（schedule.py）；
7. 检查：R 系列 + 构图门 + 破例辩护对拍；B5 ReAct 条件修复（违规才修）；
8. 交付：逐镜 mp4/首帧/深度/全片拼接/**shots.json（含新字段，见下）**/prompts.md。
   - shots.json：收 `beats`/`composition`/`rule_justifications`/破例对拍结果
     （P15"逐字段可对拍"纪律的延伸）；
   - prompts.md：**不含**上述引擎内部键（P15"不含引擎内部键"纪律）——
     拍点信息只通过既有的 `prompt` 画面描述字段间接体现。

## 7. 配置新增（`contracts/config.py`）

| 键 | 缺省 | 校验 |
|---|---|---|
| `rag.rule_top_k` | 5 | int，3–8，越界 CFG_0xx 报错（用该序列下一个空号） |
| `vlm_review.enabled` | false | bool |
| `vlm_review.max_shots` | 0（不限） | int ≥0 |
| `orchestration.draft_candidates` | 1（=现状） | int，1–5（P6-T2 落地） |

改完必跑 `python tools/gen_specs.py`（红线 R-4）。

## 8. 兼容与迁移

- SDL 1.4 工程：迁移 = 缺省填充，加载后行为与升级前一致（单测断言零新增 finding）；
- golden 夹具：SDL 版本号与新键属预期漂移，走 R-11 流程重生成（§3.9）；
- 旧 audit_log 重放：replay 只按记录的工具调用重放，新字段缺省 ⇒ 不受影响；
- emit_plan/emit_shot_draft 旧响应（无新字段）：合并逻辑对新字段缺省容错，
  行为不变；offline 夹具与 `test_protocol_end_to_end.py` 无新增失败；
- `specs/openapi.yaml` 与 contracts 同步更新（DTO 新增字段为 optional）。

## 9. 测试策略

- 一切新纯函数先单测：beats 校验、编译器（t→帧、合并、对白避让、起点接力）、
  锚点求解、灯光矩阵、rulepack（预算/冲突/forbid 反查/自由度声明）、
  SDL 1.5 迁移；
- golden 链路：`gen_golden.py --check` 进 G2 阶段门；重生成只走 R-11 流程；
- headless 冒烟：三份冻结工程（long9/long11/long12）同代重建，
  构图门/逐镜通过/R 系列读数前后对照落证据；
- 阶段门：`python -m pytest` 全绿 + `tools/run_tests.ps1` 全过。

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| ShotBeat 与 SceneBrief.beats 概念混淆 | 类名分离 + §3.1 消歧块 + 注释纪律；schema 面两者不同框 |
| beats 与 actions 双通道语义漂移 | 编译器是唯一生产者；合并规则 §4.2；同镜重复检测 |
| schema 变复杂 → 遵循率降 | 扁平/枚举/必填优先；maxItems 上限；解析失败与语义失败分开统计 |
| 规则预算截掉关键禁忌 | forbid 补挂不受预算截断；冲突对不受截断 |
| 破例辩护被当套话 | break 必须给 reason；审计对拍把"无先例破例"单独列出供人审 |
| 灯光矩阵诱导精细灯光诉求 | 只暴露语义三字段；矩阵是设计表，调表不动结构 |
| 索引/夹具换代失配 | 本版**不改索引**（B1/B2 换代单列、须裁决）；forbid 反查纯检索期 |
| 新种子改变查询串 → 测量口径漂移 | 同代测量纪律（§5.7），并入 G4；不许混代比 |
| C 盘空间 | 不装新包；并发 pytest ≤ 2；大批量跑测试前查余量 |
