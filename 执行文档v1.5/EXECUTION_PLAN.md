# EXECUTION_PLAN —— BlockDirector 执行文档 v1.5 执行计划（任务卡）

版本：执行文档 v1.5 草案（2026-10-07；目录 `docs/执行文档v1.5/`）
用法（务必先读同目录 `README.md`）：**一次只执行一张卡**；卡内"必读"按顺序
读完再动手；验收红不带入下一张；标 ⚖️ 的卡只产出材料、停手等用户。
全局红线 R-1…R-11 见 README，逐卡适用。
多执行者/插空场景的并行与串行分析见**附录 B**；单执行者按附录 A 顺序即可。

任务卡编号：P{阶段}-T{序号}。依赖关系用 → 表示。
总览：

| 阶段 | 主题 | 卡数 | 阶段门 |
|---|---|---|---|
| 0 | 基线与环境 | 2 | G0：基线读数落盘 |
| 1 | 文档一致性修复（FX-1） | 3 | G1：全量测试无新增失败 |
| 2 | 契约层升级（FR-1/2/3/8/10/13） | 5 | G2：pytest 全绿 + SDL 1.4 兼容 + golden --check |
| 3 | 求解器/引擎落地（FR-1/2/3/4/10） | 4 | G3：headless 三工程重建对照 |
| 4 | 规则通道（FR-5/6/7/8/9/10 种子） | 5 | G4：forbid_members_seen>0 且质量门不回退 |
| 5 | 知识库修复与裁决备料（FX-2/4/5/6/7/8） | 4 | G5：备料件齐 + 换代登记合规 |
| 6 | 评审与评估（FR-11/12，P2） | 2 | G6：默认关配置下全链路不回归 |
| 7 | 收尾 | 2 | G7：全绿 + 证据齐 + 文档同步 |

---

# 阶段 0｜基线与环境

## 卡 P0-T1｜环境体检与基线读数
- 目标：建立本版开始前的事实基线，后续所有"不回退"对照都以它为准。
- 必读：
  1. `docs/执行文档v1.5/README.md`（纪律与环境约束）
  2. `AGENTS.md` 的 Rules 一节
- 步骤：
  1. `df -h /c` 记录 C 盘余量（清单 F1：约 2.7 GB，低于 2 GB 停手报用户）；
  2. `python -m pytest -q` 全量跑，记录 passed/failed/skipped 数与耗时；
  3. `powershell -File tools/run_tests.ps1` 记录探针通过数（以实测为准）；
  4. `python tools/gen_golden.py --check` 记录 golden 链路状态（此刻应为绿）；
  5. `git log --oneline -1`、`git status --porcelain` 记录 HEAD 与工作树状态。
- 验收：五组读数落进 `docs/evidence/<run-id>-baseline/baseline.md`
  （run-id = 日期时间，如 20261008-103000）。
- 红线：只读不写代码；不提交任何东西。
- 完成定义：□ 基线文件落盘 □ 五组读数齐全 □ 异常项（如有失败）逐条标注"基线即红"

## 卡 P0-T2｜在跑工作树清点（不提交）
- 目标：把 OPEN_ITEMS F5 的未提交改动列成清单，供用户决定提交口径
  （对应 TECH_SOLUTIONS C1 收口第 1 步）。
- 必读：`docs/knowledge/OPEN_ITEMS_20261007.md` §五 F5
- 步骤：
  1. `git status --porcelain` 全量列出；
  2. 逐文件标注归属：`tools/glm_consult.py`+`tests/test_glm_consult.py`
     （--plain 修复，清单§附）、`tools/knowledge/grounding_classify.py`（新增）、
     `docs/evidence/20261007-grounding-*/`（在跑证据）；
  3. 写 `docs/evidence/<run-id>-baseline/worktree_inventory.md`：
     每文件给"改动摘要（git diff --stat）+ 建议提交分组"。
- 验收：清单落盘；**不做任何 git commit**（提交口径须用户确认）。
- 完成定义：□ 清单覆盖 git status 全部条目 □ 每组改动有建议提交信息草稿

---

# 阶段 1｜文档一致性修复（FX-1）

> 对应 TECH_SOLUTIONS §四。纯文档改动，低风险热身；改完跑阶段门 G1。

## 卡 P1-T1｜OPEN_PROBLEMS 抬头 + 悬空引用
- 目标：修 E1/E2。
- 必读：`docs/knowledge/OPEN_PROBLEMS.md`（全文）；
  `docs/knowledge/OPEN_ITEMS_20261007.md` §四 E1/E2
- 步骤：
  1. OPEN_PROBLEMS 顶部加"已被接管"块：P1 已结案（指 RK13_CLOSEOUT）、
     P3 已被真跑推翻、P4 已解、P5 已被吸收——各给一行指针；
  2. `AGENTS.md:58` 的"见 OPEN_PROBLEMS (19)"改为指向
     `docs/knowledge/OPEN_ITEMS_20261007.md` B1；
  3. 台账 `docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md:1325` 的"⑲"同样改指 B1。
- 验收：`grep -n "OPEN_PROBLEMS" AGENTS.md` 无 "(19)"；
  `grep -n "⑲" docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md` 无残留。
- 红线：最小 diff；AGENTS.md 除这一行外不动（本文件还有 P1-T3/P7-T2 两次
  后续修改，注意别互相覆盖——见附录 B 同文件串行表）。
- 完成定义：□ 抬头块落盘 □ 两处悬空引用改指 □ grep 验收过

## 卡 P1-T2｜台账过期块与编号注记
- 目标：修 E3/E4。
- 必读：`docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md` 第 100–140 行、
  P14-295/P14-307/P14-308 三节、文件末尾 30 行
- 步骤：
  1. `:118` 的"P10 待处置"改为"P10 已裁 D13=A（v4 只作影子，不切换）"＋裁决指针；
  2. P14-295 撞号两节：加编者注"本节与上节同号，保留原样以免断引用"；
  3. P14-308/307 顺序错位：加一行编者注说明锚点插入成因；
  4. 台账尾补一行"P14-319 已落（见 git f6530c6），本台账编号至 P14-318 止"。
- 验收：四处注记落盘；`grep -n "P10 待处置" docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md` 无残留。
- 红线：**不重编号**、不删任何历史段落。
- 完成定义：□ 四处注记 □ grep 验收过

## 卡 P1-T3｜AGENTS.md 状态块读数刷新
- 目标：修 E5。
- 必读：`AGENTS.md` 的 Status 一节；卡 P0-T1 的基线文件
- 步骤：把状态块中的 pytest 读数、探针数、HEAD 更新为 P0-T1 实测值；
  历史读数（2085 passed 等）保留在既往段落叙述里，只改"现行"行。
- 验收：`python -m pytest -q` 再跑一次确认与写入值一致；
  `powershell -File tools/run_tests.ps1` 无新增失败（阶段门 G1）。
- 红线：必须在 P1-T1 之后动 AGENTS.md（同文件串行，附录 B）。
- 完成定义：□ 状态块=实测值 □ G1 过

---

# 阶段 2｜契约层升级

> 必读公共部分：同目录 `TDD.md` §3 全节。本阶段全部纯 Python，不碰 bpy。

## 卡 P2-T1｜contracts/beats.py：拍点与三个规格类
- 目标：落地 TDD §3.1/3.4/3.5/3.6 的 ShotBeat/LightSpec/CompositionSpec/
  RuleJustification 与 `validate_beats()`。
- 必读：TDD §3.1（**含命名消歧块**）/3.4/3.5/3.6；
  `block_director/contracts/plan.py`（风格参照）；
  `block_director/motion/model.py` 的 ACTION_TYPES/ACTION_PARAMS；
  `block_director/contracts/brief.py:96-113`（确认 SceneBrief.beats 是叙事节拍，
  避免混淆）
- 新建：`block_director/contracts/beats.py`、`tests/test_beats.py`
- 步骤：
  1. 四个 dataclass 按 TDD 定义逐字段实现；`to_dict/from_dict` 齐全；
     类名是 **ShotBeat**（不是 Beat），模块 docstring 写明与 SceneBrief.beats
     的区别；
  2. `BEAT_VERBS`：可执行动词从 `motion/model.py::ACTION_TYPES` **导入**；
     语义动词（enter_from/exit_frame/place_prop/pick_up/hand_to）的定义
     先进 `motion/model.py` 的表（补 ACTION_TYPES/ACTION_PARAMS 条目，
     参数键先给最小集），再从那里导入——红线 R-7；
  3. `validate_beats(beats, characters, anchors) -> List[str]` 实现 TDD §3.1
     全部不变量，返回问题清单（不抛异常，与契约层风格一致）；
  4. 单测覆盖：正常表、t 越界、乱序、未知 subject/target、未知 verb、
     face_to/pace 闭集外取值。
- 验收：`python -m pytest tests/test_beats.py -q` 全绿；
  `python -c "import block_director.contracts.beats"` 在**无 bpy** 环境可导入。
- 红线：R-1（不 import bpy）、R-6/R-7（枚举导入不手抄）。
- 完成定义：□ 四类+校验实现 □ 单测全绿 □ 无 bpy 导入断言

## 卡 P2-T2｜ShotPlan 与 Plan 字段扩展
- 目标：TDD §3.2/§3.7。
- 必读：TDD §3.2/§3.7；`block_director/contracts/plan.py` 全文
- 步骤：
  1. ShotPlan 增 `beats`/`composition`/`rule_justifications` 三字段
     （List/Dict 形状，缺省空）；
  2. **Plan 增 `environment: Dict`**（TDD §3.2：anchors+light 的契约宿主）；
  3. `to_dict/from_dict` 同步（from_dict 对缺失键容错）；
  4. 更新 `tests/` 中 plan 相关 fixture（若有断言字段全集的测试）；
  5. `specs/openapi.yaml` 同步（新字段 optional）；
  6. 跑 `python tools/gen_golden.py --check`：若漂移，先 diff 确认**只有新增的
     可选字段**（shots.json 类夹具会多出空键），再跑 `python tools/gen_golden.py`
     重生成，夹具 diff 随本卡同批提交（红线 R-11）。
- 验收：`python -m pytest tests/ -q -k "plan or serde"` 全绿；全量 pytest 无新增失败；
  golden --check 通过（重生成后）。
- 红线：不改既有字段名与类型；duration_frames 唯一真源地位不动；夹具不许手改。
- 完成定义：□ 四字段 □ serde 双向 □ openapi 同步 □ golden 过 □ 全量无新增失败

## 卡 P2-T3｜SDL 1.5 与迁移器
- 目标：TDD §3.3/§3.9；FR-13。
- 必读：TDD §3.3/§3.9；`block_director/contracts/sdl.py` 全文；
  `block_director/layer2_sdl/sdl_migrate.py` 全文；`tests/` 里 sdl/migrate 相关测试
- 步骤：
  1. sdl.py：`SDL_VERSION` 升 "1.5"；新增 `SDLAnchor`；`SDLEnvironment` 增
     `anchors: List[SDLAnchor]` 与 `light: Dict`；`SDLShot` 增 `beats`/
     `composition`/`rule_justifications`（Dict/List 缺省空）；serde 同步；
  2. sdl_migrate.py：`KNOWN_VERSIONS`（现 `("1.0","1.1","1.2","1.3","1.4")`）
     追加 "1.5"；注册 1.4→1.5 迁移（纯缺省填充，**无删除无改名**）；
  3. 迁移测试：造一份 1.4 工程 dict → migrate → 断言新字段缺省、
     旧字段逐字节不变、校验零新增 finding；
  4. `layer9_persistence/project_io.py` 若校验 SDL_VERSION，确认 1.5 被接受；
  5. **golden 同步**：`fixtures/expected_sdl_simple.json` 第 3 行的
     `"version": "1.4"` 必漂移——diff 确认只有版本号与新增可选字段后，
     `python tools/gen_golden.py` 重生成（若 P2-T2 已重生成过，此处只需
     --check 确认；两卡谁先谁后都行，以最后一次 --check 全绿为准）。
- 验收：`python -m pytest tests/ -q -k "sdl or migrate or project"` 全绿；
  golden --check 通过。
- 红线：KNOWN_VERSIONS 只增不改；1.2 之前的 roster 修复分支不动；R-11。
- 完成定义：□ 1.5 落盘/读回 □ 1.4 兼容测试 □ golden 过 □ 全量无新增失败

## 卡 P2-T4｜emit_plan 与 emit_shot_draft schema 升级
- 目标：TDD §3.8。
- 必读：TDD §3.8；`block_director/layer5_orchestrator/planner.py:45-72`
  （emit_plan 参数 schema 定义处）与提示词模板；
  `block_director/layer5_orchestrator/editor.py` 的 EMIT_SHOT_DRAFT_PARAMETERS
  与合并函数；`block_director/layer5_orchestrator/tool_schema.py` 的 validate_args；
  `block_director/layer5_orchestrator/offline.py`（离线应答）
- 步骤：
  1. **emit_plan**：schema 增 optional `environment`（TDD §3.8 形状：
     anchors maxItems=12 + light 三 enum 字段）；提示词加一句"场级锚点与灯光
     在这里声明一次，全场共用；单镜细节不要写进 environment"；
  2. **emit_shot_draft**：properties 增 `beats`（maxItems=8，verb enum 从
     ACTION_TYPES 渲染）、`composition`（两 enum）、`rule_justifications`
     （maxItems=6，action enum follow/break）——全部扁平、
     additionalProperties: False；提示词加"不许改写 environment（场级归
     阶段 A）"；
  3. 合并函数：新字段合并回 ShotPlan；镜号/顺序/时长仍归计划（既有纪律）；
     beats 与 actions 并存时**都保留**，编译在 P3-T1 做；
  4. 非法草案只标记该镜、不 fail 整轮（既有纪律延续）；
  5. **离线/回放兼容**：offline.py 与 `tests/test_protocol_end_to_end.py`
     的既有夹具不含新字段——新字段全 optional，确认这些测试无新增失败；
  6. 单测：合法 beats 草案合并、越界 t 被 validate_args 拒、未知动词被拒。
- 验收：`python -m pytest tests/ -q -k "editor or draft or tool_schema or planner or protocol or offline"` 全绿。
- 红线：schema 只锁词汇不锁选择；maxItems 上限必加。
- 完成定义：□ 两工具 schema 升级 □ 合并逻辑 □ 离线兼容 □ 单测全绿

## 卡 P2-T5｜配置项与 gen_specs
- 目标：TDD §7（本卡先落地前三个键）。
- 必读：TDD §7；`block_director/contracts/config.py` 的 RagConfig/errors()/
  OrchestrationConfig；`tools/gen_specs.py`
- 步骤：
  1. RagConfig 增 `rule_top_k: int = 5`；errors() 加校验（int 且 3–8，
     报错码沿用 CFG_0xx 序列下一个空号）；新增 `VlmReviewConfig`
     （enabled=false, max_shots=0）并挂进 AppConfig；
     （`orchestration.draft_candidates` 由 P6-T2 落地，本卡不加）
  2. `python tools/gen_specs.py`，确认 `specs/config.default.yaml` 与代码一致
     （git diff 只含新键）；
  3. 配置单测：越界值报错、缺省合法。
- 验收：`python -m pytest tests/ -q -k "config or specs"` 全绿；
  gen_specs 幂等（连跑两次无 diff）。
- **阶段门 G2**：全量 pytest 绿 ＋ SDL 1.4 兼容测试过 ＋
  `python tools/gen_golden.py --check` 过。
- 红线：R-4。
- 完成定义：□ 三键落地 □ 校验 □ specs 同步 □ G2 三项全过

---

# 阶段 3｜求解器/引擎落地

## 卡 P3-T1｜beat_compiler：拍点→actions
- 目标：TDD §4.1/4.2；FR-1 的求解侧。
- 必读：TDD §4.1/4.2；`block_director/contracts/beats.py`（P2-T1 产物）；
  `block_director/motion/model.py`；`block_director/cinema/schedule.py`（帧排程参照）；
  `block_director/layer5_orchestrator/dialogue_budget.py`（对白窗口口径）
- 新建：`block_director/layer5_orchestrator/beat_compiler.py`、
  `tests/test_beat_compiler.py`
- 步骤：
  1. `BEAT_DURATION_TABLE`（动词→缺省帧长）设计表，顶部注释"调表不动结构"；
  2. `compile_beats(shot, anchors, cast) -> (actions, problems)`：t→帧换算、
     face_to→look_at 参数折算、enter_from/exit_frame→画外锚点 walk_to、
     同 subject 串行避让、对白窗口避让；
  3. **走位起点接力**（TDD §4.1，§六十四纪律）：walk_to/run_to 缺省起点 =
     角色当前位置，**不是**剧本起始站位；
  4. **用户动画保护**：`bd_user_animated` 标记的角色不生成/不覆盖关键帧；
  5. `merge_with_actions(compiled, written)`：TDD §4.2 重复判定与优先规则；
  6. 单测：换算正确性、合并去重、对白避让、起点接力、锚点缺失时 problems
     非空且不猜。
- 验收：`python -m pytest tests/test_beat_compiler.py -q` 全绿；输出形状与
  现有 actions[] 一致（用一份既有 fixture 断言键集相等）。
- 红线：纯函数、零 bpy；锚点解析不出就记 problem，**不猜坐标**。
- 完成定义：□ 编译器 □ 合并器 □ 单测全绿

## 卡 P3-T2｜锚点摆位求解
- 目标：TDD §3.3/§4.3；FR-2。
- 必读：TDD §4.3；`block_director/layer3_engine/scene_executor.py` 的
  build_environment；`block_director/utils/threading_guard.py`
- 步骤：
  1. 纯函数 `solve_anchor_positions(anchors, cast_positions) -> (positions, unresolved)`
     放**不 import bpy** 的模块；支持 behind/between/left_of/right_of＋
     可缺省距离 2.0 m；
  2. bpy 侧（@main_thread_only）：锚点落 `BD_Anchor_*` empty 进 Guides，
     `hide_render=True`；unresolved 锚点放缺省位并记 `unresolved_anchor` 审计；
  3. **把 BD_Anchor_ 前缀接进导出审计的 helper 白名单**（否则"helper 泄漏进
     参考视频"检查会拒导出）；
  4. 单测只测纯函数部分；headless 冒烟测 empty 创建与 hide_render。
- 验收：纯函数单测全绿；headless 冒烟（tools/blender_tests 风格）通过。
- 红线：R-2；本卡与 P3-T3 同改 scene_executor.py——串行或同一执行者
  （附录 B）。
- 完成定义：□ 求解器 □ bpy 落位 □ 白名单接入 □ 测试过

## 卡 P3-T3｜灯光矩阵与道具交互事件
- 目标：TDD §4.4/4.5；FR-3/FR-4。
- 必读：TDD §4.4/4.5；`block_director/layer3_engine/scene_executor.py` 的
  LIGHTING_PRESETS（:47-66）/create_lights/create_prop
- 步骤：
  1. LIGHTING_PRESETS 按 TDD §4.5 矩阵补新预设（既有 5 键不动）；
     `resolve_lighting_preset(LightSpec) -> str` 纯函数 + 单测（未知组合回退
     clay_studio 并记 trace）；
  2. create_lights 接环境 light 字段（缺省=现有 lighting 字符串，行为不变）；
  3. 道具交互：place_prop/pick_up/hand_to 的跟随关键帧（Child Of 或纯父子，
     起止区间键 visibility/transform）；未交互道具不打关键帧；
  4. headless 冒烟：三动词各一镜，断言道具帧数>0、静态道具帧数=0。
- 验收：单测 + headless 冒烟全绿。
- 红线：R-2；不向 LLM 暴露灯具参数；Workbench 限制告警复用；
  与 P3-T2 同文件串行。
- 完成定义：□ 矩阵 □ 道具事件 □ 测试过

## 卡 P3-T4｜构图声明消费
- 目标：TDD §4.6；FR-10 的求解侧（检索侧在 P4-T5）。
- 必读：TDD §4.6；`block_director/cinema/framing.py`（求解器出口）；
  `block_director/cinema/anchor.py`（派生链）
- 步骤：
  1. 求解后按 composition.subject_position 偏置对准点（左/右 1/6 幅宽，
     复用 §六十八横移机制）；lead_room 朝面朝方向偏；center/symmetry 居中；
     diagonal/frame_within_frame 只记录不改几何；
  2. 全部偏移走 anchor.py 派生链；冻结几何 1.70/头球相切（ADR-0007）不动；
  3. 单测：各 rule 的偏移方向与幅度；**空声明=现状逐字节一致**；
  4. 阶段门 G3：headless 重建三份冻结工程（long9/long11/long12），
     构图门通过率/逐镜通过/R 系列读数与 P0-T1 基线对照落
     `docs/evidence/<run-id>-g3/`。
- 验收：单测全绿；G3 对照无回退（空声明路径）。
- 红线：不动冻结几何；空声明必须零行为差。
- 完成定义：□ 偏置实现 □ 单测 □ G3 对照落盘

---

# 阶段 4｜规则通道（约束不损泛化）

## 卡 P4-T1｜rulepack：强度渲染与规则预算
- 目标：TDD §5.1/5.2 前半；FR-5/FR-6。
- 必读：TDD §5.1/5.2；`block_director/knowledge/client.py` 的 render_edge_block；
  `block_director/knowledge/hypergraph.py` 的 render_edges/HyperEdge.hardness
- 新建：`block_director/knowledge/rulepack.py`、`tests/test_rulepack.py`
- 步骤：
  1. `render_rule_pack(edges, nodes, budget, token_limit) -> (text, dropped, stats)`：
     每边一行带 `[必须（除非声明破例）]`/`[通常]` 强度标；例外/先例成员存在即渲染；
  2. 预算：按（类型，主键值）分桶，超 budget（=config.rag.rule_top_k）按
     confidence×occurrences 截断；条数预算与 token 上限**取紧者**；
     **原子注入**纪律（整条装不下记 dropped）；
  3. 接线：client.py 三栏渲染改调 rulepack（签名兼容，旧测试要么过要么按
     新输出更新——更新必须在卡内留 diff 说明）；`knowledge_trace.json`
     每次运行必写的纪律不受影响；
  4. 单测：强度标注、预算截断、原子注入、空边集。
- 验收：`python -m pytest tests/test_rulepack.py -q` 全绿；
  全量 pytest 无新增失败。
- 红线：R-6；不截断 forbid 成员所在的边。本卡与 P4-T2 同文件（rulepack.py）
  串行。
- 完成定义：□ 渲染器 □ 预算 □ 接线 □ 全量绿

## 卡 P4-T2｜冲突并陈与自由度声明
- 目标：TDD §5.2 后半/§5.3；FR-7。
- 必读：TDD §5.2/5.3；P4-T1 产物
- 步骤：
  1. 冲突检测：同桶内同 kind 不同值 / allow-forbid 对 → 并陈文本
     `[冲突] A｜B（更具体者优先，由你裁决）`；冲突对不受预算截断；
  2. 自由度声明：包末输出"已约束维度/留白维度"两行（按命中 kind 集合算）；
  3. 单测：冲突对保留且并陈、无冲突时无标注、自由度声明与命中集一致。
- 验收：`python -m pytest tests/test_rulepack.py -q` 全绿。
- 红线：宁可超预算一条，不藏冲突；P4-T1 之后（同文件）。
- 完成定义：□ 并陈 □ 自由度声明 □ 单测

## 卡 P4-T3｜forbid 反查补挂（守门激活）
- 目标：TDD §5.6；FR-9/FX-3/OPEN_ITEMS B7。
- 必读：TDD §5.6；`block_director/knowledge/retriever.py` 的 hypergraph_edges
  与装配段；`block_director/knowledge/hypergraph.py` 的 NodeIndex/seeds_for
- 步骤：
  1. 实现 forbid_backfill（TDD §5.6 伪代码）；补挂边渲染排最前、不受预算截断；
  2. trace 增 `forbid_backfilled`/`forbid_members_seen` 两键
     （`retrieval_call` 审计事件同步；新增键是 optional，旧 trace 读取方不受影响）；
  3. 单测：命中种子能反查出 forbid 边、无 forbid 时行为与现状一致。
- 验收：单测全绿。
- 红线：不动索引、不动判据；补挂纯检索期。
- 完成定义：□ 反查 □ trace 两键 □ 单测

## 卡 P4-T5｜检索种子接线（构图/光线入契约串）
- 目标：TDD §5.7；FR-10 的检索侧。
- 必读：TDD §5.7；`block_director/layer5_orchestrator/scene_contract.py` 的
  shot_constraint_query（:85 起）；`block_director/knowledge/hypergraph.py` 的
  QUERY_KEYS（:410 起）与 VALUE_DOMAINS
- 步骤：
  1. `add("构图", [shot.composition.get("rule")])`——空值不写（既有纪律）；
  2. 光线种子：**先核对 `VALUE_DOMAINS["lighting"]` 闭集**，只在取值落在闭集内
     时写入；不在就不写（死值污染查询）；
  3. 单测：含/不含新字段的契约串形状；死值不落串；
  4. **测量纪律**：查询串形状变化 ⇒ Q5 等口径的前后对照必须同代——
     本卡的测量并入 G4，不与接线前的读数混代比较。
- 验收：单测全绿；全量 pytest 无新增失败。
- 红线：QUERY_KEYS 不新增键（两个键已存在）；本卡只动生产侧。
- 完成定义：□ 两类种子接线 □ 闭集核对 □ 单测

## 卡 P4-T4｜破例辩护字段与审计对拍
- 目标：TDD §3.6/§5.4；FR-8。
- 必读：TDD §5.4 与 §6 第 8 步（shots.json/prompts.md 纪律）；
  `block_director/layer5_orchestrator/editor.py` 的提示词段；
  `block_director/layer3_engine/shot_auditor.py`；
  `block_director/layer8_delivery/export_director.py`（shots.json，:276 附近）
- 步骤：
  1. editor 单镜提示词加"规则引用与破例辩护"要求（引用已注入的规则 id；
     break 必填 reason；给出先例槽位写法）；
  2. shot_auditor 增 declared_breaks/detected_violations 对拍，输出
     undeclared_violations/declared_but_clean，写 shot_audit 一行；
  3. shots.json 导出补 `beats`/`composition`/`rule_justifications` 与对拍结果
     （P15 全字段纪律）；**prompts.md 不含这些引擎内部键**（P15 纪律）；
  4. 单测：对拍集合运算；导出含新字段、prompts.md 不含内部键。
- 验收：单测全绿。
- **阶段门 G4**（在 P4-T1/T2/T3/T5 与本卡全部完成后）：三份冻结工程同代重建，
  before/after 对跑——forbid_members_seen>0；Q1/Q2/Q5/E1 同口径读数对照落
  `docs/evidence/<run-id>-g4/`（任何回退如实记录，**不许调判据**）。
- 红线：**对拍只记录不设门**（设门=OPEN_ITEMS D11 议题，须裁决）；
  editor.py 在 P2-T4 之后改（同文件串行，附录 B）。
- 完成定义：□ 提示词 □ 对拍 □ 导出 □ 单测 □ G4 对照

---

# 阶段 5｜知识库修复与裁决备料

## 卡 P5-T1｜换代登记模板 + B5 零成员 kind 诊断
- 目标：FX-6 + A6 模板；两个都是只诊断/只写模板。
- 必读：`docs/执行文档v1.5/TECH_SOLUTIONS.md` A6/B5；
  `block_director/knowledge/hypergraph.py` 的 QUALIFIER_KINDS；
  `knowledge/hypergraph.edges.jsonl`（抽样）
- 步骤：
  1. 写 `docs/knowledge/REGEN_LOG_TEMPLATE.md`（换代原因/前后指纹/影响面/
     最小重跑集/pin 处置）；
  2. 脚本核查 5 个零成员 kind（applies_to_genre/applies_to_shot_size/
     carry_shots/example_shot/seq_phase）：逐条判"有意不用（证据）/漏抽
     （修复点）"，出 `docs/evidence/<run-id>/zero_member_kinds.md`；
     附 B6 需要的"若纳入判定所需映射增量"一节。
- 验收：两份文档落盘；不改任何代码与判据。
- 完成定义：□ 模板 □ 诊断报告

## 卡 P5-T2｜B1：132 张手写策展卡入索引（换代）⚖️ 前置确认
- 目标：FX-2。**动手前先向用户确认换代窗口**（本版唯一动索引的卡；
  且必须与 G3/G4 测量隔开，见附录 B 隔离条）。
- 必读：TECH_SOLUTIONS B1；`tools/kb_fetch/build_hypergraph.py` 输入段；
  `block_director/knowledge/corpus.py` 与 `cards_*.py`（132 张出处）；
  P5-T1 的 REGEN_LOG_TEMPLATE
- 步骤：
  1. 填换代登记表（前指纹）；
  2. 扩展输入源纳入策展卡 → 重建索引 → 记录后指纹；
  3. 最小重跑：Q0–Q4/Q6b/Q7/E1 同口径；23 份运行 pin 标"异代"，不 repin；
  4. ACCEPTANCE_STATUS 读数板 K1 更新为 2353/2353（实测后填）。
- 验收：覆盖 2353/2353；质量门同口径读数前后对照落
  `docs/evidence/<run-id>-b1/`；回退如实记录。
- 红线：R-8；策展卡内容一个字不改。
- 完成定义：□ 登记表 □ 重建 □ 重跑对照 □ 读数板更新

## 卡 P5-T3｜B4+G9 别名备料（不动手）⚖️
- 目标：FX-4 备料件。
- 必读：TECH_SOLUTIONS B4；`block_director/knowledge/hypergraph.py` 的
  VALUE_ALIASES；`block_director/contracts/enums.py` 的 MOVEMENT_TYPES
- 步骤：
  1. 三方对照表：知识中文取值 × 引擎 24 运镜英文枚举 × held-out 查询词表，
     标 已等价/近似/无对应；
  2. 起草"若落地"的两步 diff 描述（VALUE_ALIASES 增补清单 + 缓存键纳入别名表
     的具体键位），只写提案不改代码；
  3. 出 `docs/evidence/<run-id>/adjudication_movement_aliases.md`。
- 验收：备料件落盘；代码零改动。
- 完成定义：□ 对照表 □ 提案

## 卡 P5-T4｜B2 双路线 + A3 评委口径 + A5 裁决包（备料合集）⚖️
- 目标：FX-5/FX-7 + A5 路由，三件备料。
- 必读：TECH_SOLUTIONS B2/A3/A5；`block_director/cinema/axis.py`（符号域）；
  `block_director/layer5_orchestrator/scene_contract.py` 的 _MOVEMENT_ALIASES 段
- 步骤：
  1. B2：路线 A（索引换代改符号域）vs 路线 B（检索期映射层）影响面对照，
     推荐 B 先行；
  2. A3：按 TECH_SOLUTIONS 写 `docs/knowledge/JUDGE_ALIGNMENT_v1.md`
     （rubric 锚点、术语表、20 条校准流程）；GLM-5.3 不可用时只出文档不跑校准
     （GLM 调用串行不并发，README 环境约束）；
  3. A5：R1/R5/D10/D11 四条格式化成裁决包
     `docs/evidence/<run-id>/adjudication_pack.md`。
- 验收：三份备料落盘；不改代码/判据/索引。
- 完成定义：□ B2 对照 □ JUDGE_ALIGNMENT_v1 □ A5 裁决包

---

# 阶段 6｜评审与评估（P2，默认关）

## 卡 P6-T1｜VLM 评审外回路（可选）
- 目标：TDD §5.5；FR-11。
- 必读：TDD §5.5；`block_director/layer3_engine/shot_auditor.py`；
  `block_director/contracts/transport.py`（传输抽象）
- 步骤：
  1. `vlm_review.enabled=false` 时零行为差（单测断言）；
  2. 开启时：每镜首/中/末帧 + intent + composition 声明 → VLM 1–5 分+一句理由，
     结果只进 shots.json 与面板展示，**不参与任何门**；
  3. 评委不可用（超时/429/524）→ 跳过该镜并记录，重试一次后放弃；
  4. 单测用 mock transport。
- 验收：单测全绿；默认关配置下全量 pytest 与 G3 对照无回退。
- 红线：VLM 不作唯一裁决；不接进任何既有门；shot_auditor.py 在 P4-T4
  之后改（同文件串行）。
- 完成定义：□ 回路 □ 默认关零差异 □ 单测

## 卡 P6-T2｜多样性度量与 Best-of-N 骨架
- 目标：PRD 泛化指标 + FR-12。
- 必读：`docs/执行文档v1.5/PRD.md` §6；`block_director/layer5_orchestrator/editor.py`；
  `block_director/contracts/config.py`（P2-T5 产物）
- 步骤：
  1. `tools/diversity_score.py`：同一剧本 N 次生成的 ShotPlan 序列差异度
     （景别序列编辑距离 + 运镜分布卡方 + 机位侧向符号翻转率），纯函数+单测；
  2. Best-of-N 骨架：config 增 `orchestration.draft_candidates`（int，默认 1=现状，
     1–5；**改完必跑 `python tools/gen_specs.py`**，红线 R-4）；editor 支持同镜
     N 候选，规则评分 rerank **不过滤**，低分候选进 shots.json 的 alternates[]；
  3. 默认 1 时零行为差（单测断言）。
- 验收：单测全绿；gen_specs 幂等无 diff；默认配置零差异；差异度脚本对三份
  冻结工程出读数落证据。
- 红线：rerank 不是过滤；默认关；editor.py/config.py 的前序串行见附录 B。
- 完成定义：□ 度量脚本 □ 候选骨架 □ specs 同步 □ 默认零差异

---

# 阶段 7｜收尾

## 卡 P7-T1｜全量回归与证据收口
- 目标：G7 总门。
- 步骤：
  1. `python -m pytest -q` 全量；`powershell -File tools/run_tests.ps1`；
     `python tools/gen_golden.py --check`；
  2. 若新增探针：同步更新 `tests/test_agents_status_is_current.py` 的对拍数
     （链规模对拍是既有纪律）；
  3. 汇总证据索引 `docs/evidence/<run-id>-final/README.md`：
     每阶段门读数 + 差异对照 + 遗留问题清单。
- 验收：全绿；证据索引完整。
- 完成定义：□ 全量绿 □ 探针对拍同步 □ 证据索引

## 卡 P7-T2｜文档同步与提交
- 目标：AGENTS.md/CONTEXT.md/ACCEPTANCE_STATUS/openapi.yaml 与代码一致；
  按用户确认的口径提交（含 P0-T2 的在跑改动分组）。
- 步骤：
  1. AGENTS.md 状态块写入最终实测读数（同 P1-T3 纪律）；
  2. `CONTEXT.md` 若涉及本次模块清单变化，同步小节；
  3. ACCEPTANCE_STATUS.md 增本版章节：做了什么、没做什么、哪些裁决还挂着；
  4. 确认 specs/openapi.yaml 与 contracts 同步（diff 只含新 optional 字段）；
  5. `git add` 分组提交：契约层/求解器/规则通道/知识备料/文档，每组一条
     commit，信息格式沿用仓库惯例（如 `feat(P14-32x): …`）；
  6. 提交前向用户展示分组清单，确认后执行。
- 验收：`git log --oneline -8` 分组清晰；工作树干净。
- 红线：提交口径必须用户确认过；AGENTS.md 是第三次改（附录 B 同文件串行表）。
- 完成定义：□ 四处文档同步 □ 分组提交 □ 工作树干净

---

# 附录 A：执行顺序速查（单执行者）

P0-T1 → P0-T2 → P1-T1 → P1-T2 → P1-T3（G1）→ P2-T1 → P2-T2 → P2-T3 →
P2-T4 → P2-T5（G2）→ P3-T1 → P3-T2 → P3-T3 → P3-T4（G3）→ P4-T1 → P4-T2 →
P4-T3 → P4-T5 → P4-T4（G4）→ P5-T1 →（用户确认换代窗口）P5-T2 → P5-T3 →
P5-T4（G5）→ P6-T1 → P6-T2（G6）→ P7-T1 → P7-T2（G7）

⚖️ 卡（P5-T2 的换代动作、P5-T3、P5-T4）在对应用户确认前只做到"备料完成"。

# 附录 B：并行与串行分析（多执行者/插空时用）

## B.1 并行轨道图

```
轨道0 基线   P0-T1 ║ P0-T2                      （只读+写 evidence，互不撞）
轨道A 文档   P1-T1 ║ P1-T2 ║ P5-T1 ║ P5-T3 ║ P5-T4 （纯文档/备料，全程可插空）
轨道B 契约   P2-T1 → P2-T4 ──────────→ P4-T4 ──→ P6-T2   （editor.py 链，串行）
             P2-T2 ║ P2-T3 ║ P2-T5            （文件互不相交，并行）
轨道C 引擎   P3-T1 ║ P3-T4 ║ (P3-T2 → P3-T3)  （scene_executor.py 同文件串行）
轨道D 知识   (P4-T1 → P4-T2) ║ P4-T3 ║ P4-T5  （rulepack.py 同文件串行）
轨道E 可选   P6-T1（在 P4-T4 后）              （shot_auditor.py 撞车）
隔离点       P5-T2 索引换代——必须在 G3+G4 测量快照**之后**单跑
汇流点       G1…G7 阶段门 = join；P7-T1 → P7-T2 全局收尾
```

## B.2 逐条结论的解释（为什么可以并行 / 为什么必须串行）

**可以并行（文件集不相交 + 语义不依赖）：**

1. **P0-T1 ║ P0-T2**：都是只读仓库 + 各写各的 evidence 文件，无共享输出。
2. **P1-T1 ║ P1-T2 ║ P5-T1 ║ P5-T3 ║ P5-T4**：分别改 OPEN_PROBLEMS/台账、
   新建 REGEN 模板与诊断、新建备料文档——互不相同的文件，且都是文档，
   不影响代码与测试。
3. **P2-T2 ║ P2-T3 ║ P2-T5**：plan.py / sdl.py+sdl_migrate.py / config.py 三个
   文件集不相交；TDD §3 已把字段形状冻结，三方照 schema 施工即可，不需要
   等彼此的实现。golden 重生成以最后完成者的一次 --check 为准。
4. **P3-T1 ║ P3-T4 ║ (P3-T2→P3-T3)**：beat_compiler.py（新建）/
   framing.py（构图）/scene_executor.py（锚点+灯光道具）互不相交。
5. **(P4-T1→P4-T2) ║ P4-T3 ║ P4-T5**：rulepack.py（新建）/ retriever.py /
   scene_contract.py 三个文件集不相交。
6. **轨道 A 全程 ║ 轨道 B/C/D**：文档卡与代码卡零文件交集。

**必须串行（同文件或语义依赖）：**

7. **P2-T1 → P2-T4**：emit_shot_draft 的 verb enum 从 P2-T1 落的
   ACTION_TYPES 渲染，且合并函数依赖 beats 校验形状——没契约就没 schema。
8. **P2-T2 → P2-T4**：合并函数要写进 ShotPlan 新字段，字段不存在就没法合并。
9. **P2-T3 → P3-T2**：锚点求解消费 SDLAnchor 类型。
10. **P3-T2 → P3-T3**：同改 `scene_executor.py`（同文件双写会互相覆盖）。
11. **P4-T1 → P4-T2**：同改新建 `rulepack.py`。
12. **P2-T4 → P4-T4 → P6-T2**：同改 `editor.py`（schema → 提示词 → 候选骨架）。
13. **P4-T4 → P6-T1**：同改 `shot_auditor.py`。
14. **P2-T5 → P6-T2**：同改 `config.py`（且都要跑 gen_specs，必须看到彼此的
    终态再生成）。
15. **P1-T1 → P1-T3 → P7-T2**：同改 `AGENTS.md` 的三处不同区域——同文件
    串行，防互相覆盖。

**语义依赖（文件不撞也得等）：**

16. **P0-T1 先于一切**：后续所有"不回退"对照都以基线读数为分母。
17. **G2/G3/G4 是 join 点**：门内对照要求该阶段所有卡完成，缺一镜读数就
    没有可比性。
18. **P4-T5 的测量并入 G4**：种子接线改变查询串形状，Q5 口径必须同代比
    （TDD §5.7），不许拿接线前读数当分母。
19. **P5-T2 隔离单跑**：索引重建改变检索行为与指纹；若与 G3/G4 同跑，
    before/after 对照的分母被换掉，测量作废（R-8 换代纪律）。且 ⚖️ 需用户
    确认窗口。

**资源约束（并行的硬上限）：**

20. **并发 pytest ≤ 2**：C 盘仅剩约 2.7 GB，pytest tmp 在 %TEMP%（README
    环境约束）；headless Blender 冒烟不同时跑两个实例。
21. **GLM 类调用串行**：GLM-5.3 抖动未查明（F4）且 Kimi 回退挂起（F2）——
    P5-T4 等涉及外部评委的动作串行、带"不可用即跳过并记录"退路。

**单执行者提示**：并行结论用于多执行者分工或"等评测时在旁边做文档卡"；
单执行者严格按附录 A 顺序最稳。
