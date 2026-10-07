# PRD —— BlockDirector 执行文档 v1.5 产品需求文档

版本：执行文档 v1.5 草案（2026-10-07；目录 `docs/执行文档v1.5/`）
底座：执行文档 v1.2（权威规格）＋ 改进执行文档 v1.4（P9.4–P16 已落地）＋
超图 hg/v2（节点/边扩类裁决已落地）
输入材料：`docs/research_src/白模预演规则增强研究报告.pdf`、
`docs/research_src/白模预演插件剧本解构粒度设计报告.pdf`、
`docs/knowledge/OPEN_ITEMS_20261007.md`

---

## 1. 产品定位

BlockDirector 是一个 Blender 插件：**导入剧本 → LLM 按语义自动完成白模预演
（blocking 级）→ 导出逐镜参考视频/首帧图/prompts**，供下游 AI 视频生成使用。

预演的价值定位（两份调研报告的共同结论）：**便宜地回答昂贵的问题**——
"这场戏成不成立、该怎么拍"，而不是生产一部规则上无可挑剔的成片。
一切规则体系服务于这个答案的可靠性，不服务于"自动"。

## 2. 用户与核心场景

| 角色 | 场景 | 现状 |
|---|---|---|
| 导演/分镜师 | 导入剧本文本，一键得到整场白模预演 | 已有（阶段 S→A→B1→B2→检查→导出全链） |
| 导演/分镜师 | 对某一镜不满意，改走位/机位后只重建这一镜 | 已有（`regenerate_shot`，13.2 面板） |
| 导演/分镜师 | 理解 AI 为什么这样拍（规则引用、破例理由） | **缺**：无规则引用/破例辩护字段 |
| 导演/分镜师 | 控制 AI 的"守规矩程度"（合规模式 vs 探索模式） | **缺**：规则预算/模式参数不存在 |
| 用户（剧本侧） | 剧本里的对白、走位、道具交互被忠实还原 | 部分：对白已有；**走位语义化、道具交互事件化缺** |
| 用户（画面侧） | 构图、景别、运镜符合电影语言惯例 | 部分：构图评分已有；**LLM 拿不到"怎么用"的构图方法知识** |

## 3. 现状盘点（已实现，不复述细节）

- 四层 LLM 编排：阶段 S（SceneBrief 剧本理解）→ 阶段 A（emit_plan 拍摄清单）
  → 阶段 B1（emit_shot_draft 逐镜结构化草案）→ B2 场景构建 → B5 ReAct 修复环。
- 契约层：`contracts/plan.py`（Plan/ShotPlan）、`contracts/sdl.py`（SDL 1.4）、
  `contracts/brief.py`（SceneBrief）、`contracts/knowledge.py`（HyperEdge/Case DTO）。
- 引擎层：24 种运镜端到端、取景求解器（景别+镜头→距离/机位）、180° 轴线控制
  （R001 v1.9）、构图评分（含遮挡射线检测、构图门 ≥70%）、角色几何冻结 1.70。
- 规则/审计层：R 系列规则检查（R001–R012、R019 在
  `layer3_engine/rule_checker.py`；R013/R015 在
  `layer5_orchestrator/compliance.py`；R014 已按 X6 删除）、逐镜审计、
  修复回路、预算限额。
- 知识层：超图 RAG hg/v2（17 节点类 / 13 边类 / 2353 卡 / 638 边）、
  三通道检索（cards/edges/cases）、L3 案例层 1143 条、逐镜契约串查询
  （`shot_constraint_query`）、三栏注入（硬约束/经验建议/参考案例）。
- 交付层：逐镜 mp4、首帧图、深度序列、全片拼接、shots.json
  （`layer8_delivery/export_director.py`）、prompts.md。

## 4. 问题陈述（本版要解决的）

### P-1 剧本解构粒度偏实现层
LLM 在 `emit_shot_draft` 里直接写**绝对帧号**（`start_frame/end_frame`）与坐标
（`target_position`）。调研结论：连续数值不可枚举、不可语义校验，是幻觉温床；
且单镜失败/修改时的重生成粒度粗。应升级为**拍点表**（归一化时机 t∈[0,1] +
动词枚举 + 目标 + 节奏），帧号由求解器换算。

### P-2 五轨道不齐：解构维度缺层
对照"Staging / Cast Action / Camera / Light / Timing"五轨道：
- Staging：无**场景锚点**（门/桌/窗）与前/中/后景纵深声明，道具摆位靠坐标直写；
  且**场级环境没有契约宿主**（Plan 类目前只有 shots/continuity_notes/
  scene_heading），锚点与灯光语义无处声明；
- Cast Action：无拍点层（见 P-1）；道具交互未事件化；
- Camera：已有（24 运镜 + 景别枚举）；
- Light：只有环境级 `lighting` 预设字符串，无 time_of_day/mood 语义；
- Timing：已有（duration_frames 唯一真源 + 对白优先）。

### P-3 规则"约束 vs 泛化"失衡
超图 RAG 已实现且三栏注入已通，但：
- 注入**无强度标注**：hard/soft 在边上有（`hardness`），渲染进 prompt 时不区分
  "必须"与"通常"，LLM 无法掌握让步空间；
- **无例外与先例**：破例先例不是一等公民，LLM 破例只能"硬违"；
- **无规则预算**：一次注入多少条不可控，存在规则堆积→指令冲突的风险；
- **冲突不并陈**：两条规则竞争时系统悄悄二选一，不交给 LLM 裁决；
- **无破例辩护通道**：生成契约里没有"我引用了哪条规则/我有意违反哪条及理由"；
- **forbid 零命中**（OPEN_ITEMS B7）：索引里有 21 条带 forbid 成员的边，但真实
  运行里含 forbid 的边一条都没被激活——执行闭环当前**没有守门能力**。

### P-4 知识库自身缺口（OPEN_ITEMS 知识类）
- B1：132 张手写策展卡不在索引里（覆盖 2221/2353）；
- B2：`axis_side` 两套词表不相交（索引 left/right/neutral vs 成片 correct/crossed）；
- B4：movement 中英词表只量了落差、没编别名；
- B5：5 个声明了却零成员的 kind（是有意还是漏抽未逐条核）；
- C1–C6：出处缺口（90 槽位三分类进行中、9 边待局部手术、superseded 失据待核等）。

### P-5 评审与评估单一
- 只有确定性规则裁判（R 系列 + 构图分），无 VLM 外回路（构图/情绪的软质量无把关）；
- 无多样性指标（"不僵硬"不可测）；
- A3：两位评委同批差 0.27（deepseek 0.44–0.46 / glm 0.67–0.7120），口径未对齐，
  且至今没有归属文档。

### P-6 文档一致性缺陷
OPEN_ITEMS E1–E5：OPEN_PROBLEMS 缺"已被接管"抬头、悬空引用、台账过期/撞号、
AGENTS.md 状态块读数过期。会误导下一个执行者（包括执行模型）。

## 5. 需求列表

优先级：P0 = 本版必须；P1 = 本版应做；P2 = 本版可选（机制在、默认关）。

### 功能性需求

| 编号 | 需求 | 优先级 | 来源 |
|---|---|---|---|
| FR-1 | **拍点契约**：ShotPlan/emit_shot_draft 增加 `beats[]`（t∈[0,1]、subject、verb 枚举、target、face_to、pace、react），帧号由编译器换算 | P0 | 粒度报告 §2/§4 |
| FR-2 | **Staging 锚点**：Plan 级 `environment.anchors[]`（name/depth_layer fg/mid/bg/relation），由阶段 A 的 emit_plan 声明，道具/走位引用锚点名而非坐标 | P0 | 粒度报告 §4.2 |
| FR-3 | **灯光语义轨**：场级 `environment.light{time_of_day, mood, key_direction?}` → 预设矩阵映射到 LIGHTING_PRESETS | P1 | 粒度报告 §3/§5.3 |
| FR-4 | **道具交互事件**：place_prop/pick_up/hand_to 作为 beat 动词，生成道具跟随关键帧 | P1 | 粒度报告 §3 修正表 |
| FR-5 | **规则强度渲染**：注入块按 hardness 标注"必须（除非声明破例）/通常"，例外与先例随边渲染 | P0 | 规则报告 §2.2/§4.4 |
| FR-6 | **规则预算**：每镜注入规则条数上限可配（`rag.rule_top_k`，默认 5，区间 3–8），与既有 token 上限同取紧者 | P0 | 规则报告 §3.1 |
| FR-7 | **冲突并陈**：同域冲突规则同时呈现并注明竞争关系，交 LLM 裁决 | P1 | 规则报告 §3.2 |
| FR-8 | **破例辩护字段**：每镜 `rule_justifications[]{rule, action: follow/break, reason, precedent?}`，进 schema、进审计 | P0 | 规则报告 §4.4 |
| FR-9 | **forbid 守门激活**：检索装配时对命中种子反查含 forbid 成员的边并优先注入；trace 记 forbid_members_seen | P0 | OPEN_ITEMS B7 |
| FR-10 | **构图方法声明**：每镜可声明 `composition{rule, subject_position}`（枚举），取景求解器按声明偏置对准点；**声明同时作为 `构图=` 检索种子接入逐镜超图查询**（QUERY_KEYS 已有该键；接线改变查询串形状，测量并入阶段门 G4） | P1 | 用户要求＋规则报告 |
| FR-11 | **VLM 评审外回路**（可选、默认关）：渲染帧+意图→VLM 粗筛评分，仅相对比较不作唯一裁决 | P2 | 规则报告 §4.5/§7.1 |
| FR-12 | **Best-of-N 探索模式**：同镜 N=3~5 候选，规则评分 rerank 不过滤，低分候选保留展示 | P2 | 规则报告 §6 |
| FR-13 | **契约版本管理**：SDL 升 1.5（beats/anchors/light/composition/rule_justifications），1.4 工程无损加载；golden 夹具随版本同步重生成 | P0 | 粒度报告 §6 |

### 修复性需求（OPEN_ITEMS 承接）

| 编号 | 需求 | 优先级 | 对应条目 |
|---|---|---|---|
| FX-1 | 文档一致性修复（抬头/悬空引用/过期块/读数刷新） | P0 | E1–E5 |
| FX-2 | 132 张手写策展卡入索引（换代登记 + 最小重跑） | P1 | B1 + A6 |
| FX-3 | forbid 守门激活（同 FR-9） | P0 | B7 |
| FX-4 | movement 中英别名表提案（含缓存键纳入别名表） | P1（须裁决） | B4 + G9 |
| FX-5 | axis_side 值级绑定方案（先检索期映射，换代留裁决） | P1（须裁决） | B2 |
| FX-6 | 零成员 kind 逐条核查报告（只诊断不改判据） | P1 | B5 |
| FX-7 | 评委口径对齐方案与归属文档（只备料不判分） | P1（须裁决） | A3 |
| FX-8 | 出处缺口收尾：提交在跑改动、9 边局部手术备料 | P1 | C1/C2/F5 |

### 非功能性需求

| 编号 | 需求 |
|---|---|
| NFR-1 | 契约/工具层纯 Python 零 bpy 依赖（红线 R-1/R-2） |
| NFR-2 | 一切枚举有单一真源（hypergraph.py / motion/model.py），禁止抄写漂移（R-6/R-7） |
| NFR-3 | 所有变更可回放：工程可重建、审计 JSONL 可 replay；golden 夹具只经 gen_golden 重生成（R-11） |
| NFR-4 | 新字段全部可选、有缺省：旧工程/旧日志/旧 offline 夹具行为不变（向后兼容） |
| NFR-5 | 成本可控：条件修正（违规才重生成）、规则预算封顶；全流程 token ≤ 单次的 3 倍 |

## 6. 验收指标（Definition of Done）

| 层 | 指标 | 目标 | 口径 |
|---|---|---|---|
| 合规 | emit_shot_draft schema 解析失败率 | ≈0（与语义错误分开统计） | 真实运行审计 |
| 合规 | R 系列（R001–R013/R015/R019）违规率 | 不高于本版开始前基线 | 三份冻结工程（long9/long11/long12 同代重建） |
| 合规 | forbid_members_seen | 真实运行 >0（守门能力从 0 到 1） | retrieval_call trace |
| 质量 | 构图门通过率（≥70% 分） | 不降低 | 同上三份冻结工程 |
| 泛化 | 同一剧本 3 次生成的分镜差异度 | 可测量且 >0（不许退化成查表） | 新增多样性度量脚本 |
| 工程 | `python -m pytest` | 全绿（基线见阶段 0 实测记录） | 阶段门 |
| 工程 | `tools/run_tests.ps1` | 探针全过（基线以阶段 0 实测为准，加探针则同步改对拍） | 阶段门 |
| 工程 | golden 链路 | `python tools/gen_golden.py --check` 通过（夹具随 SDL 1.5 重生成后） | 阶段门 G2 |
| 兼容 | SDL 1.4 工程 | 无损加载、校验零新增 finding | 迁移测试 |

## 7. Non-goals（本版明确不做）

- 不做精细灯光/材质/表情/手指/次级运动——白模 blocking 层为止；
- 不引入 PSL 散文分镜中间层（现有 JSON 契约链已承担中间层职责，见 TDD §5.8）；
- 不重建相机 rig（Track-To target 机制已存在且经 24 运镜验证，见 TDD §5.8）；
- 不训练/微调专用 VLM 评审模型（ShotVL 路线仅记录为后续选项）；
- 不把规则全量灌 prompt（本版的核心反目标）；
- 不替用户拍板任何标"须裁决"的项（A2/A4/A5、B2 换代、B3、B4、C2/C5、G6 等）；
- 不改 E1/RK-13 判据（已结案，链上照旧报红）；
- 不做 MCP 外部架构改造（契约层架构无关，保持传统 addon 封闭 UX）。
