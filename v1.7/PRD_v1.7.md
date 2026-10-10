# BlockDirector v1.7 产品需求文档（PRD）—— 前端界面、像素小助手 与 参考包交付闭环

| 项 | 值 |
|---|---|
| 版本 | v1.7.5（2026-10-10：配套《改进计划》细节完善版——§3.14 SDL 升 **1.7**（1.5/1.6 已被占用，`sdl.py:25` 实读）；执行颗粒度全部落到《改进计划》v1.7.5 的"落地步骤/测试清单/验收命令"三段式。v1.7.4：双执行者改版。v1.7.3 严格自审：A-U1-1 与 gen_specs 矛盾修正、R020 收窄、R021/R023 操作化。v1.7.2：M1–M5 并入、Q8 结案、红线 R-V。v1.7.1：首轮自审 7 项） |
| 日期 | 2026-10-08 |
| 上游文档 | `BlockDirector_执行文档_v1.2.md`、`改进执行文档v1.4.md`、v1.5 落地台账（AGENTS.md「P14 现状」块）、`docs/v1.6/PRD_v1.6.md`（质量主线，并行） |
| 证据基线（代码现状，全部实地读数） | ① UI 层现状：`block_director/layer7_ui/` 共 **1,551 行 / 6 个 bpy 面板**，无任何 Web/聊天界面<br>② 配置真源：`contracts/config.py`（794 行）＋ 插件侧单例 `settings.py`（54 行）<br>③ 密钥纪律：`config.py:74` `api_key` 注释"见 §14.3，**不写入 .blend**"；`GLM_API_KEY` 只从环境变量读<br>④ 进程边界：`tools/sidecar_server.py`（642 行，stdlib-only、loopback、Bearer token），现有端点 `/health`、`/v1/chat`、`/v1/retrieve`、`/v1/embed`(501)、`/v1/cancel`（:452–492）<br>⑤ 状态机：`layer5_orchestrator/states.py:8–24` `DriverState` **14 态**——小助手动画数据源<br>⑥ 上下文治理：`orchestration.context_window_tokens=32000`（config.py:132），裁剪 `context_budget.py::trim_messages`<br>⑦ 知识栈：`rag.top_k=15` / `rule_top_k=8` / `cases_backend` / `cases_top_k=3` / 每镜 50000 / 预取 60000（config.py:97–109）<br>⑧ 规则现状：`layer3_engine/rule_checker.py`（914 行）已实现 R001–R010/R012/R019 等，**无开关机制**；`_error/_warning` 直推调用点 24 处（:596–658）<br>⑨ 轨迹现状：`overlay/geometry.py` 移动路径几何（纯函数有单测）、`operator_path_draw.py` 落 `BD_Path_*`<br>⑩ 兽设参考：`docs/ui-assistant/assets/mikael_reference.jpg`（米迦尔三视图＋色板，2,304×1,728）<br>⑪ 调研报告：R-痛点（`docs/v1.7/调研依据_痛点调研与功能评估.md`）：16 痛点 P1–P16、5 模块 M1–M5、**M1 判 P0**<br>⑫ 导出层现状：`layer8_delivery/`（renderer/concat/depth_pass/export_director）已产 per-shot mp4、首帧图、`shots.json`、`prompts.md`、可选 depth——**M1 是增强不是新建**<br>⑬ 连续性数据源现成：`rule_checker.py:111 _pair_screen_order` 已在算"谁在画面哪侧" |
| 执行者设定 | **Opus 5.5 × DeepSeek v4 Pro 混合执行**（分工表见《改进计划 v1.7》§0.2：Opus 21 卡＝全部前端＋跨层/核心文件/高风险卡；DeepSeek 18 卡＝单文件/接口钉死卡）。两执行者共用同一套注意力纪律 ⇒ PRD 只定"做什么、为什么、验收什么"；接口真源在 TDD；执行颗粒度在《改进计划 v1.7》，**每卡单文件焦点、显式验收命令、禁止跨卡重构** |
| 红线（继承 + 新增） | 继承：不改任何已有判据/门限；`contracts/`、`utils/` 不 import bpy；`.ps1` ASCII-only<br>R-UI-1：API key **永不**写入 .blend、trace、审计日志、git、Web 响应正文（只回掩码）<br>R-UI-2：Web 界面是**附属品**——没有它，`run_headless` 全链路必须逐字节不受影响<br>**R-V（v1.7.2 新增）**：本期所有新检测规则（R020–R025）一律 **warning 级起步**，不进 error、不进任何门；升格需冻结工程实测＋用户裁决 |

---

## 1. 背景

BlockDirector 到 v1.5 为止是一条"命令行 → 白模成片"的自动化链路。交互面只有 6 个 Blender N 面板（证据①），设置靠手改 YAML；而 R-痛点调研（证据⑪）指出：**这条管线的故障点正从"生成质量"向"交接质量"迁移**——白模视频没有"身份声明"会被下游模型当成外观来源（P1）、相机方向只存在于画面里会被镜像解读（P3）、规格不匹配要烧一次生成积分才暴露（P7/P13）。

**v1.7 因此是双主线**（2026-10-08 用户裁决合并）：

- **交互线**：统一设置（key/思考强度/上下文/知识库/规则）、聊天、剧本优化、轨迹可视化、Q 版像素小助手（米迦尔）；
- **交付线**（R-痛点 M1–M5）：导出包生成器、导出沙箱、目标模型适配器、校验层扩展、剧本层分工声明。

### 1.1 为什么是"Web 前端 ＋ Blender 内轻量精灵"的混合形态（论证在《技术方案》§2）

- bpy 面板体系做不出富聊天/设置 UI（证据①：1,551 行才撑起 6 个列表型面板）；
- 但 sidecar 已经是**现成的进程边界与 HTTP 服务**（证据④），且它"own the provider specifics"——Web 前端挂在他上面零新进程；
- 小助手在 Blender 视口里只需要"存在感"（GPU 贴图精灵），重交互全在 Web 端；
- R-UI-2 保证：Web 端挂了/没开，命令行链路零影响。

### 1.2 交付线与现有架构的关系（不多建新架构）

R-痛点 §6 的结论原文：新增模块"大部分是**已有校验层架构的自然延伸**"。落位如下：

| 报告模块 | 落到本仓哪里 | 关键证据 |
|---|---|---|
| M1 导出包生成器 | 增强 `layer8_delivery/`（`prompts.md`/`shots.json` 已有 P15 基础）＋ 新增 `reference_pack/` | 证据⑫；运镜文字化复用 `cinema/camera_motion.py` 采样；continuity 表复用 `_pair_screen_order`（证据⑬） |
| M2 目标模型适配器 | `specs/target_models.yaml`（**数据文件**，报告原文要求）＋ `delivery.target_model` ＋ 切片建议 | R-痛点 P7/P13 |
| M3 导出沙箱 | `layer8_delivery/export_sandbox.py` 包裹现有导出 | R-痛点 P11（9 项设置＋alpha/色深静默丢失） |
| M4 校验扩展 | `rule_checker.py` 新增 R020–R025（**warning 级**，红线 R-V） | R-痛点 P4/P5/P10/P14 |
| M5 分工声明 | plan schema `shot.responsibility`＋SDL 1.5＋R024 声明比对 | R-痛点 P6/P16/§5 |

**反向边界**（报告 §5 三条"不要硬解"，本期遵守）：不增强白模动画细节能力、不管成片端残余不一致、不把白模流程强加给该跳过的镜头。

## 2. 角色与使用场景

| 角色 | 场景 |
|---|---|
| 导演（唯一用户） | S1 配置：首次使用，打开设置页填 key、选模型、调思考强度与上下文、**选目标模型** |
| | S2 编剧：把草稿剧本贴进"剧本优化"，看建议（**含分工建议**）、采纳改写稿，确认后进分镜 |
| | S3 监控：跑长片时切到聊天页问"跑到哪了"，小助手在 Web 页和 Blender 视口里同步显示状态 |
| | S4 调镜：在轨迹视图看走位路径与机位弧线（**附运镜文字**），不满意回 Blender 用路径工具改 |
| | S5 调参：知识库页试检索；规则页关掉某条误报规则 |
| | **S6 交付（新）**：导出后拿 `reference_pack/` 直接喂 Seedance/Hailuo——分工提示词＋运镜文字＋continuity 表都在包里；时间线超目标模型上限时**导出前**就看到切片建议 |

## 3. 功能需求

> 编号：FR-U＝界面功能，FR-A＝小助手，FR-E＝导出层，FR-V＝校验扩展，FR-S＝剧本层分工。每条挂证据；验收判据用可执行语句写。

### 3.1 FR-U1 统一设置中心（P0）

Web 设置页分组暴露下列配置，保存即写盘（YAML），插件下次运行前重读：

| 分组 | 键 | 现状证据 |
|---|---|---|
| 模型 | `llm.provider` / `llm.model` / `llm.base_url` / `llm.api_key` / `llm.timeout_s` / `llm.max_tokens` | config.py:67–82 全部已存在 |
| 思考强度 | **新增** `llm.thinking_level`（`off`/`low`/`medium`/`high`，默认 `off`） | 现无此键；映射见 TDD §4.2 |
| 上下文 | `orchestration.context_window_tokens`（滑块 8k–128k）＋只读说明"超出即裁剪，保 system＋最新轮" | config.py:132、context_budget.py |
| 知识库 | `rag.enabled` / `backend` / `top_k` / `rule_top_k` / `cases_backend` / `cases_top_k` / `max_tokens_per_call` / `plan_prefetch_tokens` | config.py:86–118 全部已存在 |
| 规则 | **新增** `audit.rules_disabled`（字符串列表，默认空＝全开） | rule_checker.py 无开关机制（证据⑧） |
| 预算 | `budget.max_cost_usd` / `max_wall_minutes` / `max_llm_calls_ceiling` | config.py:167–190 |
| **目标模型（新）** | **新增** `delivery.target_model`（下拉，规格摘要只读展示） | R-痛点 M2/P13；现无此键，消费者 FR-E3 |

验收：
- A-U1-1 保存后 `python tools/gen_specs.py --check` 通过（默认值真源不漂移）；用户配置写盘后 `AppConfig.load()` 无 error 级 Issue（注意：新增键本身会使 `config.default.yaml` 经 gen_specs 重新生成，这是设计内行为，"不漂移"指与 config.py 逐字节一致）；
- A-U1-2 key 保存后：配置文件 key 字段恒 `""`、secrets.json 0600 落盘；trace/审计/HTTP 响应全文 grep 不出明文 key；
- A-U1-3 `python tools/gen_specs.py --check` 通过。

### 3.2 FR-U2 聊天助手（P0）

Web 聊天页：左侧对话流，右侧当前运行状态卡（状态机状态、当前镜号、LLM 调用数、token 消耗——数据源同 panel_debug，证据①/⑤）。

- 后端复用 sidecar `/v1/chat` 上游通道（证据④），会话持久化 `runs/<run-id>/chat.jsonl`；
- v1.7 范围：**只读问答＋状态查询**（"现在哪个镜头""上一条告警是什么"由后端从审计日志取数回答，不经过模型）；
- **命令执行不在 v1.7**（列入移交事项，须带确认门）——`regenerate_shot()` 有 `bd_user_animated` 保护语义（AGENTS.md），聊天直接改场景必须先过规格裁决。

验收：
- A-U2-1 无运行时聊天可用（插件用法、知识库问答）；
- A-U2-2 运行中状态卡每 2 s 刷新且与 `audit_log.jsonl` 最新事件一致；
- A-U2-3 sidecar 不可达时聊天页显示离线横幅，不白屏。

### 3.3 FR-U3 剧本优化（P0）

新阶段 **Stage P（polish）**，位于 UNDERSTANDING 之后、PLANNING 之前，**默认关闭**（`script_polish.enabled=false` 时零行为差）：

- 输入：原始剧本＋SceneBrief；输出：① 逐条建议清单（结构/对白节奏/可拍性/**分工建议维度**——哪些镜该跳过白模，衔接 FR-S1），② 一份完整改写稿；
- **人工确认门**：改写稿必须经用户点"采纳"才替换进 PLANNING 的输入——复用 `audit.human_gate_on_plan` 的既有门语义（config.py:149），不新建门的种类；
- 双向留痕：建议与改写稿写进审计日志与 `project.bdproj`。

验收：
- A-U3-1 `enabled=false` 时与 HEAD 的 plan 逐字节一致（golden 回归）；
- A-U3-2 未点采纳时 PLANNING 输入恒为原剧本；
- A-U3-3 改写稿与建议可在 Web 页 diff 查看（原稿左、改稿右）。

### 3.4 FR-U4 运动轨迹可视化（P1）

- **U4a 视口内增强（P1）**：移动路径按角色着色（取角色 `color` 字段）、路径叠关键帧刻度（每 12 帧一格）、当前帧高亮；全部走 `overlay/geometry.py` 纯几何层新增函数，GPU 绘制仍只在 `draw_overlay.py`（证据⑨）；
- **U4b Web 轨迹页（P2，可裁剪）**：从 `shots.json` 读每镜路径数据，渲染 2D 俯视图（房间矩形＋角色路径折线＋相机弧线）；镜头列表含**"运镜文字"列**（数据源 FR-E1 的 `camera_narration`，未落地时显"-"）。

验收：
- A-U4-1 `--background` 下新几何函数单测通过（继承"测几何不测像素"纪律）；
- A-U4-2 俯视图坐标与 `shots.json` 数值一致（±0.01 m）。

### 3.5 FR-U5 知识库管理与试检索（P1）

- 知识页：语料统计（卡/边/案例数，**实读** `knowledge/*.jsonl` 行数）、按域浏览、全文搜卡；
- 试检索盒：调 `/v1/retrieve`（证据④三通道已就绪）→ 三栏展示＋trace，**与注入提示词同一端点**——"看到的就是模型吃到的"；
- 不做：在线编辑语料/重建索引（门①–⑩链路不许被 UI 绕过）。

验收：
- A-U5-1 试检索 trace 与插件侧 `knowledge_trace.json` 同构（契约测试）；
- A-U5-2 统计数字与磁盘实读一致。

### 3.6 FR-U6 规则开关（P1）

- 规则页列出全部规则（编号/名称/严重级/简介，**数据源 `contracts/rule_catalog.py`**，前端不存第二份）＋每条一个开关；
- 关闭进 `audit.rules_disabled`；`rule_checker._finding` 入口哨兵短路（TDD §4.4），被跳规则在 `shot_audit` 留 `skipped` 痕——静默跳过不允许（对齐 config.py:89–90"可以降级，静默不行"）；
- 红线：只能关、不能改阈值数值。

验收：
- A-U6-1 关闭 R009 后重跑冻结工程，R009 全部 `skipped:true` 且其余规则读数逐字节不变；
- A-U6-2 空列表时与 HEAD 零行为差。

### 3.7 FR-A 像素小助手（P0，本版灵魂）

形象：**米迦尔 Q 版像素化**（证据⑩）。色板取自设定图：

| 用途 | 色 | 取值（设定图取样，±8 色差容忍） |
|---|---|---|
| 主毛色·青 | cyan | `#2EC4E6` |
| 角/耳尖/尾纹·紫 | purple | `#3B1D5A` |
| 星纹/闪电纹·黄 | yellow | `#F6C90E` |
| 底毛·白 | white | `#F2F2F0` |
| 瞳·橙 | orange | `#E8791A` |

规格：基分辨率 **48×48 px**，×4 最近邻放大；逐帧精灵表＋CSS `steps()`（Web）/ GPU 贴图帧切换（Blender 视口）。状态映射**单一真源 `contracts/assistant.py`**（TDD §3）：

| DriverState | clip | 语义 |
|---|---|---|
| IDLE / 无任务 | `sleep` | 趴下＋Zzz |
| UNDERSTANDING | `read` | 读剧本 |
| PLANNING / EDITING | `think` | 托腮思考泡 |
| CALLING_LLM | `think_wait` | 等模型 |
| EXECUTING_TOOL / BUILDING | `build` | 搬方块 |
| CHECKING / REVIEWING | `inspect` | 放大镜校验 |
| REPAIRING | `fix` | 扳手修理 |
| AWAIT_HUMAN | `ask` | 举手问号 |
| FINISHING | `pack` | 打包 |
| DONE | `celebrate` | 跳＋星星 |
| ERROR | `dizzy` | 摔倒蚊香眼 |
| CANCELLED | `sit` | 坐下抱尾 |
| POLISHING（新增态） | `read` | 优化剧本中 |

- 每 clip 4–8 帧 12 fps；初版占位像素稿（程序生成），**管线先行、正式美术后补**（TDD §6 帧表 JSON）；
- 位置：Web 右下角常驻（可拖拽）＋ Blender 视口右上角（可关，`ui.viewport_sprite`）；
- 彩蛋（P2，可裁）：5 min 无交互打哈欠；导出成功 `celebrate` 后追加 `pride`。

验收：
- A-A-1 映射表与 `DriverState` 一一对应（契约测试遍历枚举对拍）；
- A-A-2 状态切换后 Web 端 ≤2 s 换 clip；
- A-A-3 全部 clip 帧表校验通过（帧数/尺寸/调色板合法）。

### 3.8 FR-E1 导出包生成器（P0，R-痛点 M1）

证据：P1（白模被当外观来源——"白模＋分工提示词"才是完整交付物；正向短指令优于禁止清单，GPTunneL 实证）、P3（相机反向为最高频失败，对策=运镜文字化）、P8（continuity 表）、P14（职责分离骨架）；本仓 `prompts.md`/`shots.json` 已有基础（证据⑫）。

需求：导出目录新增 `reference_pack/`：
1. **分工提示词**：按目标模型切换模板（模板是 `specs/prompt_templates/*.txt` **数据文件**，stdlib `string.Template` 渲染；核心句照 P1 转述：只取运镜/切换/节奏/摆放，几何体是占位符、颜色不代表色调）；
2. **逐镜运镜文字**：`cinema/camera_narration.py` 纯函数从相机采样算"起点方位→运动→终点方位"，写入镜头卡片与 `shots.json.camera_narration`；
3. **continuity 表**（`continuity.json`）：逐镜"谁在画面哪侧/朝向/相对位置"，复用 `_pair_screen_order`（证据⑬）；
4. **职责分离提示词骨架**：白模管什么/参考图管什么/文字管什么分区（P14）。

验收：
- A-E1-1 golden 工程导出后 `reference_pack/` 文件清单与关键字段对拍通过；
- A-E1-2 运镜文字与相机数据方位一致（手算夹具 ±1 方位）；
- A-E1-3 模板不含禁止清单长文（≤5 句正向指令）。

### 3.9 FR-E2 导出沙箱（P0，R-痛点 M3）

证据：P11（视口导出 9 项设置＋切视频格式**静默丢弃** alpha/16 位色深——对自动管线是确定性陷阱）。

需求：`layer8_delivery/export_sandbox.py` context manager 包裹导出全程：备份/还原输出路径、格式、容器、编码、质量、分辨率比例、帧率、色深、alpha 模式（≥9 项），**异常也还原**（try/finally）；锁相机视角与帧率；LLM 侧代码永不直接写 `scene.render.*`（静态检查守门）。

验收：
- A-E2-1 headless 测试：沙箱内故意改设置＋抛异常，退出后 9 项逐一还原；
- A-E2-2 既有导出 golden 对拍零漂移。

### 3.10 FR-E3 目标模型适配器（P1，R-痛点 M2）

证据：P7（Seedance 2.5 单段≤30 s/参考总≤30 s、Kling 5/10 s 档、Hailuo H3 4–15 s/12 文件）、P13（规格应建场时初始化而非导出时发现）、报告 §4"规格表=可更新数据文件"。

需求：
- `specs/target_models.yaml` 三模型规格（数字**照抄 R-痛点 §2 P7 并注来源行**）；loader 非法即报结构化 error；
- `delivery.target_model`（默认 `seedance_2.5`，未知值 CFG_172 warning 回落）；
- **超限切片建议**：时间线超目标单段上限 → warning＋建议切点（优先镜头切换处，其次运镜静止段）；**只建议不执行**；
- 建场规格（帧率/宽高比）与目标不一致 → warning，**不偷偷改设置**。

验收：
- A-E3-1 45 s 单镜对 seedance_2.5 → 恰好 1 条超限 warning＋切点落在镜界；
- A-E3-2 规格表三模型字段完整、区间合法；
- A-E3-3 设置页目标模型分组下拉可切换并落盘。

### 3.11 FR-V1 比例一致性校验 R020（P1，R-痛点 M4-a）

证据：P5（比例漂移忠实传导到成片，**必须在白模侧修**，提示词修不回来）；几何 1.70 已冻结（ADR-0007），跨镜一致性的基准存在。

需求：R020（**warning 级**，红线 R-V）：同一角色 id 跨镜包围盒世界高度两两差 > `guard.scale_drift`（默认 0.05，待实测校准）告警。**收窄说明**：调研报告写的"角色 vs 门/桌参照物比例"分支**不做**——仓内无标定尺寸真源（门/桌无标准尺寸库），缺真源的阈值就是拍脑袋；该分支列入移交事项，有真源后再立项。

验收：
- A-V1-1 冻结工程注入已知比例错误 → 恰好 1 条 R020；无错误工程 → 零误报；
- A-V1-2 阈值键进 config＋gen_specs 同步。

### 3.12 FR-V2 运动复杂度/翻转/速度检测 R021–R023（P2，R-痛点 M4-b）

证据：P4（一镜两运动必丢其一，对策=拆镜头）、P10（路径跟随翻转失控，LLM"看不见"翻转结果）。

需求（全部 warning 级，操作化定义见 TDD §13.3）：
- R021 单镜复合运动：相机相邻采样段**航向角差 > 30°** 记 1 次方向突变，突变数＋该镜主体运动条目数 ≥ `guard.compound_motion_max`（默认 2）→ "建议拆镜头"；
- R022 相机 up 向量逐帧符号突变 → 翻转告警；
- R023 相机加速度（采样二阶差分 × fps²，**单位 m/s²**）> `guard.cam_accel_max`（默认 8.0）→ 告警；
- 阈值进 guard 节（CFG_174/175），**无实测依据的默认取保守宽值并注"待校准"**。

验收：
- A-V2-1 三个构造夹具各命中一次；
- A-V2-2 三份冻结工程误报计数写进证据目录（只记录，不判红）。

### 3.13 FR-V3 提示词-白模矛盾检测 R025（P3，R-痛点 M4-c，默认关）

证据：P14（文字与白模各说各话→模型摇摆）；报告 §4 原文"唯一涉及语义判断的项，校验层只提供实测方位数据，可交给 LLM 裁决层"。

需求：校验层产实测方位数据（从/到方向，复用 FR-E1 的运镜文字化结果）；LLM 裁决层比对提示词文本，矛盾 → warning。**默认关**（`guard.prompt_conflict_check=false`）。

验收：
- A-V3-1 构造"文字从左到右/实测从右到左"样本 → 恰好 1 条 R025；
- A-V3-2 `enabled=false` 全链零行为差。

### 3.14 FR-S1 剧本层分工声明（P2，R-痛点 M5）

证据：P6（白模粒度悖论——太细有害，动作细节应交 Prompt/参考图）、P16（固定口播/纯光影镜头用白模是负优化）、报告 §5 三条"不要硬解"。

需求：
- plan schema 加**可选** `shot.responsibility`：`{white_model[], prompt[], ref_image[], skip_white_model: bool}`；缺省 null＝未声明；SDL 升 **1.7**（v1.7.5 修正：`contracts/sdl.py:25` 实测当前 `SDL_VERSION="1.6"`，1.5 已占用；旧文件迁移补 null，零 error）；
- `skip_white_model=true` 的镜：不建白模主体、`shots.json` 标记、导出包给"直出提示词＋参考图"指引；
- R024（warning）：声明 vs 实测矛盾（声明 skip 却建了主体；声明移交 prompt 的细节却 K 了细粒度关键帧）；
- Stage P 建议清单含分工维度（衔接 §3.3）；声明进 `reference_pack/`。

验收：
- A-S1-1 v1.4 SDL 文件加载零 error 且字段为 null；
- A-S1-2 声明 skip 的镜场景中无白模主体对象；未声明镜的默认路径零行为差；
- A-S1-3 声明与实测矛盾 → 恰好 1 条 R024。

## 4. 非功能需求

| 项 | 要求 |
|---|---|
| NFR-1 安全 | sidecar 维持 loopback-only；`/v1/ui/*` 全鉴权（Bearer）、静态资源免鉴权但禁载敏感数据（TDD §7 分层）；key 明文不出进程边界（R-UI-1） |
| NFR-2 零依赖 | sidecar stdlib-only；Web 前端零构建；模板引擎用 `string.Template`（不引 jinja）；PNG 校验不引 PIL |
| NFR-3 性能 | Web 轮询 ≥1.5 s；视口精灵 draw 回调 <1 ms（贴图预载，回调内不读盘不解码） |
| NFR-4 可测 | 状态映射/帧表/配置序列化/端点契约/新规则全部纯 Python 可测；headless 断言规矩不变（不测像素） |
| NFR-5 兼容 | 新配置键全带默认值；SDL 1.5 迁移路径补齐；旧配置/旧工程加载零 error；未声明分工的剧本全链零行为差 |
| NFR-6 数据文件化 | 目标模型规格表、提示词模板均为文本数据文件进仓（模型迭代极快，R-痛点 §4 原文要求） |

## 5. 界面设计（线框）

### 5.1 Web 主界面（四页签＋常驻小助手）

```
┌──────────────────────────────────────────────────────────────┐
│ BlockDirector        [聊天] [轨迹] [知识库·规则] [设置]        │
├──────────────────────────────────────────────────────────────┤
│ 聊天页：                         │ 状态卡（运行中才出现）：     │
│  ┌───────────────────────────┐  │  状态: REPAIRING            │
│  │ 对话流（我/助手气泡）       │  │  镜头: shot_023/064         │
│  └───────────────────────────┘  │  LLM: 87 次 · 512k tok      │
│  [输入框............] [发送]     │  费用: $0.83 / $5.00        │
│   剧本优化入口（顶部横幅）         │  [查看审计] [取消运行]       │
│                                  │  目标模型: seedance_2.5      │
│                                  │       ┌─────┐               │
│                                  │       │ 🦊  │ ← 小助手常驻  │
│                                  │       └─────┘               │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 设置页（六分组手风琴；**规则开关在「知识库·规则」页签**，见 §5.3）

```
设置
├─ 模型        [provider▾] [model____] [base_url____] [key: ••••••] [测试连接]
├─ 思考强度    (●)关闭 ( )低 ( )中 ( )高   ※高=慢思考，超时建议≥600s
├─ 上下文      [────●──────] 32000 tok   超出即裁剪：保 system＋最新轮
├─ 知识库      [启用☑] top_k[15] 规则包[8] 案例[3] 每镜上限[50000]
├─ 目标模型    [seedance_2.5 ▾]  单段≤30s · 宽高比[0.4,2.5] · 视频参考≤10段/总≤30s
└─ 预算        费用上限[5.0]$  墙钟[120]min  调用硬顶[200]
```

### 5.3 其余页面

- 剧本优化：左右 diff 双栏＋建议清单（**含分工建议**）＋[采纳改写稿]（二次确认）；
- 轨迹：左镜头列表（**运镜文字列**）＋右 2D 俯视画布；
- 知识库：统计条＋域筛＋试检索三栏；规则页同页签下半区。

高保真示意：`docs/v1.7/mockup/index.html`（静态线框，浏览器直接打开）。

## 6. 里程碑与裁剪线（顺序 = R-痛点优先级矩阵）

| 里程碑 | 内容 | 裁剪线 |
|---|---|---|
| M1 契约底座 | 阶段 A（含规格表、分工声明契约） | 不可裁 |
| **M2 交付线 P0** | **FR-E1 导出包、FR-E2 导出沙箱**（报告判 P0："不做则管线空转"） | 不可裁 |
| M3 设置页＋小助手 Web | FR-U1（含目标模型分组）、FR-A（Web 侧） | 视口精灵可裁到 M5 |
| M4 聊天＋剧本优化＋适配器 | FR-U2、FR-U3、FR-E3 | 聊天命令执行本就不在范围 |
| M5 轨迹＋知识库＋规则＋校验扩展 | FR-U4/U5/U6、FR-V1/V2、FR-S1 | U4b、彩蛋、FR-V3 可裁 |

## 7. 风险与开放问题

| # | 风险/问题 | 应对 |
|---|---|---|
| Q1 | 精灵美术资产谁产出 | 管线先行，占位帧跑通全部验收；正式资产单独排期 |
| Q2 | Web 前端是否需要登录 | 不需要——loopback＋Bearer token；token 面板可复制 |
| Q3 | 聊天命令执行边界 | v1.7 只读；写操作进移交事项（确认门） |
| Q4 | 思考强度映射漂移 | 集中在 sidecar 一处（TDD §4.2）；百炼降级留痕 |
| Q5 | 规则开关被用来"消红" | 文案明示＋`skipped:true` 留痕＋阈值不可改 |
| Q6 | 打包分发后 `web/` 资产安放 | `BD_ASSISTANT_ASSETS` 覆盖口；移交事项 |
| Q7 | token 进浏览器历史 | sessionStorage 转存＋`history.replaceState` 抹 query |
| ~~Q8~~ | ~~M1–M5 与 v1.7 先后~~ | **已裁决（2026-10-08）：并入本版**，阶段 I/J 承接 |
| Q9 | 新规则阈值无实测依据 | 一律 warning 级＋保守宽值＋注释"待实测校准"（红线 R-V）；真跑后回填 |
| Q10 | Kling/Hailuo 规格数字只有文档来源 | 数据文件注明来源条目；首次真跑后校准（移交事项） |
| Q11 | 分工声明被模型乱填（skip 滥用） | R024 声明 vs 实测比对＋Stage P 建议只是建议，采纳权在人（§3.3 门） |
