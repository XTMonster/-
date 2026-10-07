# v1.6 规格／契约覆盖审查

日期：2026-10-08。角色：**规格一致性／契约覆盖**（本代理唯一视角）。

审查模型：继承主线当前模型；未调用 DeepSeek、GLM 或其他外部会诊；本记录不是双模型共识。

## 结论

全量读完 `AGENTS.md`（1133 行）、`CONTEXT.md`（71 行）和 v1.6 四份文档（PRD 155 行、技术方案 165 行、TDD 397 行、计划 661 行）。规格共 **37 条 FR／D 需求**（18 条 FR + 19 条 D），计划共 **26 张卡**。**D-03 没有执行卡**；其余需求有名义卡片归属，但数处卡片白名单遗漏实际生产者、调用入口或持久化／导出消费者。不能据此宣布计划已经形成可执行闭环。

审查起点 HEAD：`2a63f95 A4: expose llm.timeout_s in config, panel and driver limits (D-01)`。起点 dirty 是 A5 四个产品文件、`tests/test_needs_review.py` 和 `docs/agents/hooks/model-routing.md`。主线在并行工作，以下产品行号对应本次读取的工作树，不是未来提交不变的行号。

`v1.6/` 和 `docs/v1.6/` 四份同名文件逐对 SHA256 一致。本文引用 `docs/v1.6/` 版本，未改任何规格、产品代码、测试或 AGENTS。

## 1. 全量覆盖矩阵

“有卡”仅表示任务分派存在，**不是实现或验收通过**。括号中的 SC 编号是下文 finding。

| PRD 需求 | PRD 行 | 任务卡／计划行 | 覆盖结果 |
|---|---:|---|---|
| FR-A1 | 79 | C1 363、C2 383 | 有卡；brief → builder、失败 → 计划重问漏线（SC-03） |
| FR-A2 | 80 | E1 470 | 有卡；导出装配者不在白名单（SC-06） |
| FR-A3 | 81 | E2 489 | 有卡；调用入口与开关面板不在白名单（SC-06） |
| FR-A4 | 82 | E1 470 | 有卡；登记表到 prompts 的同源注入待接（SC-06） |
| FR-A5 | 83 | E3 508 | 有卡；生产导出入口不在白名单（SC-06） |
| FR-B1 | 89 | D1 405 | 有卡；brief 通用 serde 可复用，不把它误报为必需新持久化模块 |
| FR-B2 | 90 | D3 448 | 有卡；计数计算时机／参数不足（SC-09） |
| FR-B3 | 91 | D2 426 | 有卡；角色动作曲线消费层漏列，ease 词义冲突（SC-04、SC-10） |
| FR-B4 | 92 | D2 426 | 有卡；运镜归一和调用者丢 curve（SC-04） |
| FR-B5 | 93 | D3 448 | 有卡；逐镜节奏归并规则未钉死（SC-09） |
| FR-C1 | 99 | B2 271、B3 297 | 有卡；FrameSample 信息不足（SC-08） |
| FR-C2 | 100 | B2 271、B4 317 | 有卡；采样量口径、预设所有权需明确（SC-08、SC-10） |
| FR-C3 | 101 | B2 271 | 有卡；持续帧数与稀疏样本数必须分开（SC-08） |
| FR-C4 | 102 | B2 271、B4 317 | 有卡；告警实例到裁决的标识未钉死（SC-05） |
| FR-C5 | 103 | B4 317 | 有卡；accept 只有提示词菜单，没有可执行回复通路（SC-05） |
| FR-C6 | 104 | B5 340、B2 271 | 有卡；jump-cut 几何事件须由 B2/B5 明确承担，不能用 durations 重推（SC-09） |
| D-01 | 110 | A4 160 | 已有提交；配置错误码与 TDD 冲突（SC-10），本审查未替主线复验提交 |
| D-02 | 111 | F1 527 | 有卡；低 effort 配置消费者未分派、自动降级授权需按 PRD 原义记录（SC-10） |
| D-03 | 112 | 仅 G2 验收 636 | **无执行卡**；接口与校验器能力也不匹配（SC-01） |
| D-04 | 113 | B1 251 | 有卡；零 LLM 重放归因工具 |
| D-05 | 114 | F3 568 | 有卡；不改 schema，不改知识门 |
| D-06 | 115 | F3 568 | 有核验卡；不得把已生效字段当新实现 |
| D-07 | 116 | A5 181 | 有卡；当前 dirty 无头漏传且缺登记次数（SC-02） |
| D-08 | 117 | A6 201 | 有卡；reason 三分支；事件“登记”基础设施待明确（SC-11） |
| D-09 | 118 | F2 548 | 有卡；断点／导出／恢复的行为契约需真实杀进程验证，本次不代验 |
| D-10 | 119 | C1 363、C2 383 | 同 FR-A1（SC-03） |
| D-11 | 120 | A2 113 | 已有提交；成员资格口径已明确，本审查未替主线复验提交 |
| D-12 | 121 | B4 317 | 有卡；头部测量通道未闭合（SC-08） |
| D-13 | 122 | B4 317 | 同 FR-C5（SC-05） |
| D-14 | 123 | B5 340 | 同 FR-C6 |
| D-15 | 124 | A3 139 | 已有提交；本审查未替主线复验提交 |
| D-16 | 125 | F4 585 | 有卡；`layer_occupancy(beats)` 缺换算成帧的上下文（SC-09） |
| D-17 | 126 | A3 139 | PRD 拒绝／引导有卡；TDD 额外写的 ambient 编译通道无卡（SC-10） |
| D-18 | 127 | G1 604 | 有卡；side 预设及接触阴影 |
| D-19 | 128 | A7 225 | 有卡；全帧报告 → 交付 README 漏列（SC-07） |
| FR-E1 | 134 | A1 80 | 已有提交；计划局部步骤容差与终验 max_delta=0.0 不一致（SC-12） |
| FR-E2 | 135 | A1 80 | 有全量回归要求；本审查不替测试角色判绿 |

NFR 也逐条对过：NFR-1 由全局 R-1/R-2 承接；NFR-2 由配置卡和 gen_specs 承接，但存在错误码冲突；NFR-3 由 B3 的 100 帧 <5 s 承接；NFR-4 的事件契约机制并不存在于现有 `contracts/audit.py`，见 SC-11；NFR-5 由全局 R-6 承接。

## 2. 可执行 findings

### SC-01 / P1 — D-03 没有执行卡；其 oneOf 接口也不是现有校验器支持的子集

证据：

- PRD:112 要求三类 invalid 归零、subject id 归一、`hand_to.toward` 结构目标；TDD:168–172 给出接口，TDD:353/390 列测试与终验。
- 全量卡片标题只有 A1–A7、B1–B5、C1–C2、D1–D3、E1–E3、F1–F4、G1–G2；计划:636 的 D-03 仅是终验项，没有任何执行卡承担。
- `block_director/layer5_orchestrator/tool_schema.py:7–8,40–85` 仅支持 type/required/properties/items 等子集，不处理 `oneOf`。
- `block_director/contracts/tools.py:19–60` 是工具名／工具组真源，不是动作参数 schema 的存放处；TDD:34 直接把 hand_to schema 指向这里，与当前边界不符。
- 轻量实测：把 TDD 的三分支 `oneOf` 填入 `validate_args`，`toward="not_a_target"` 与 `toward={}` 均返回 `[]`，即非法值被认为无问题。

建议：补一张明确的 D-03 卡，仍只覆盖 PRD 原需求。先盘点并列明实际 schema 生产者（`editor.py`／`tool_bindings.py`）、校验器（`tool_schema.py`）、归一函数及动作编译消费者（`motion/model.py`／`cinema/props.py`／相关调用者），再钉住 union 的拒收语义和可执行目标变换。不得仅增加 description 或让测试只看 schema 字面量。

### SC-02 / P1 — A5 当前 dirty 只接了 GUI，原需求的无人值守路径仍丢请求明细与次数

证据：

- 计划:183 明确无人值守产物可见；:193 明确 README 要“镜号 + 登记次数”。
- 真实生产者是 `driver.py:2211–2219`，其中 `review_requests.append` 保存完整条目；`control_tools.py:46–52` 只返回文案。A5 白名单:187–191 却只点 control_tools，不点驱动或无头入口。
- `driver.py:394` 的 snapshot 只输出 `review_requests: len(...)`，不是列表；`headless_runner.py:76–98` 没另加请求明细。
- `tools/run_headless.py:180–206` 和 `tools/run_export.py:138–144` 调用 `export_project` 时都没传 `review_requests`。
- 当前 dirty 的 `manifest.py:57–58` 用 set 把请求折成镜号，丢失同镜重复登记次数；`export_director.py:133–141` 只列唯一镜号和总镜数。
- 相反，当前 dirty 已在 `modal_operator.py:222` 和 `panel_main.py:89` 传了请求列表。因此这不是“还没看到写入逻辑”，是入口之间确实不一致。

建议：A5 白名单明确扩至请求明细输出、两个无头入口及既有 GUI 导出装配者；保留 snapshot 计数字段的兼容语义，另给运行交付摘要完整明细或按镜计数。测试从控制工具派发到无头摘要再到实际交付装配，重复请求同一镜两次，验证 `needs_review=true` 且 README 该镜计数为 2。GUI 既有提示行为不变。

### SC-03 / P1 — C1/C2 没有 brief.environment 到场景构建和计划重问的消费链

证据：

- 计划:369–373 只让 C1 改 brief/understand/SDL；C2:389–395 只列 scene_executor、事件和测试。
- `shot_builder.py:540,556–565` 从 SceneSpec 和 `plan.environment.anchors/light` 调 `build_environment`；不传 `brief.environment`，失败只 `summary.warnings.extend(...)`。
- `contracts/cast.py:343–355` 只消费 `brief.space` 决定站位；SceneSpec 当前没有新环境元素字段。
- `scene_executor.py:542–548` 当前签名也没有 brief/environment 元素输入；不修改调用者而仅给 executor 加参数，参数将没有生产者。
- `tools/rebuild_project.py:86–88` 只由 SDL 还原 plan/spec 后重建，不把 `sdl.brief` 传给 builder。仅证明 brief 字段 serde 往返，不能证明零 LLM 重建环境一致。
- PRD:79／计划:385 要求解析失败“带回计划重问”，但 C2 白名单没有 driver/planner/repair 的反馈消费者。

建议：在 C1/C2 中明定新环境字段的权威承载和 `brief → plan/spec → builder → executor` 桥接，补 `shot_builder.py` 与所选纯契约／SDL 转换层的白名单，重建通路不得只存不消费；明确哪个有界阶段承接 `E_ENV_001` 并重问。纯映射表应放纯层，不能让 `tests/test_env_anchors.py` 为测试纯函数而导入触发 bpy 的 `layer3_engine` 包。

### SC-04 / P1 — D2 曲线字段在归一和调用边界丢失，角色动作落地层也未列入白名单

证据：

- D2 白名单在计划:432–438；缺 `cinema/camera_motion.py`、`shot_builder.py`、`motion/model.py`、角色 motion_library。
- `cinema/camera_motion.py:277–279` 的 `movement_spec` 重建固定键集合，没有 curve。实测输入 `curve="sharp"` 后输出只有 type/amount/start_frame/end_frame/seed/subject。
- `shot_builder.py:446–449` 调 `apply_camera_movement` 不传 curve；bpy 侧当前签名在 `layer3_engine/cinema_engine/camera_motion.py:42–46`，即使仅给该端增加可选 curve，也一直收到缺省值。
- 角色动作 `beat_compiler.py:20–21` 输出既有 actions 字段；实际位移由 `motion/model.py:590–648` 展开；角色关键帧插值由 `character_system/motion_library.py:156–198` 消费，均不在 D2 白名单。

建议：补齐归一／传递／执行三层，保持 24 种运镜几何求解结果不变，只保留并应用时间曲线元数据。验收矩阵必须量真实关键帧／位移轮廓，而不是断言词表可枚举。角色动作同理：先明确 curve 进入 ActionRequest 还是编译后帧表，再列真实消费者；不能靠“多写 curve 字段”宣称生效。

### SC-05 / P1 — B4 的 accept/guard_verdict 没有协议入口和派发者

证据：

- 计划:330 菜单第四项 `accept（声明刻意）`，:334 要求必记 guard_verdict；PRD:103 要求模型明确接受／拒绝每条告警。
- B4 白名单:323–328 不含工具 schema／注册／driver 派发；只改提示词无法制造一个可调用的动作。
- `repair.py:150–160` 的真实 tool 列表来自 registry；`contracts/tools.py:24–60` 的控制、动作工具都没有 accept。
- TDD:178–179 的 verdict 仅 `shot_id + warning_type`，无法区分同一镜同类但不同主体或不相邻时段的告警，而 GuardWarning:107–115 明确有 subject/frame_range。
- `contracts/audit.py:47–64` 的 AuditResult 当前没有 guard 字段；B4 “这里只消费已登记事件”不足以定义告警 serde 和修复载荷的所有权。

建议：钉住一个结构化判词入口及其注册／校验／派发／审计全链白名单；采用可区分实例的告警标识或完整匹配键（不必另造新需求）。明确 accept 仅是语义裁决记录，不能静默消掉现有硬 error 或 PASS_SCORE。提供“同镜同类不同主体分别 accept/reject”的反例验证。

### SC-06 / P1 — E1–E3 的新产物没有导出装配者，配置开关也没有面板任务

证据：

- E1 白名单:476–479 只有契约、纯 manifest/prompts；E2:495–498、E3:512–515 只有新 pass 文件、config 和测试。
- 现有真正执行文件创建和 pass 调度的是 `export_director.py:233–265,297–345`；它调用深度、写 shots/prompts/README。该模块不在 E1–E3 任一卡白名单。
- TDD:53 还要求 `run_settings.py + panel_main.py` 暴露 guard 档和 mask/reference 开关；实际 A4:166–171 只负责 timeout，后面没有卡接这些 UI 项。

建议：把 `export_director.py` 和必要的 DeliveryReport 扩展写入 E1–E3，规定先生成同一份 ElementRegistry，再由 prompts、mask、reference 共同消费；调用关闭路径必须不产对应文件且不误记降级。把 TDD 已要求的面板开关显式归卡，不增功能。

### SC-07 / P2 — A7 报告登记与交付汇总之间缺消费者

证据：

- PRD:128 要自检报告进交付包；TDD:336 要交付 README 汇总；G2 计划:644 同样把 README 列为读数位置。
- A7 白名单:231–236 没有 BuildSummary／driver 审计装配／export_director。
- 现有 exporter 的 `_readme` 签名 `export_director.py:97` 仅消费 manifest 和 DeliveryReport；事件流不会自动出现在交付中。

建议：A7 先定义标签全帧报告返回／存储契约，再明确经构建摘要或独立报告文件进入 exporter 的通路，补对应白名单。不要在标签层反向 import orchestrator，也不能只在测试中手工调用 README 假装链路已通。

### SC-08 / P1 — FrameSample 的数据形状不足以承载头部占比、视角和持续帧语义

证据：

- TDD:187 把 FrameSample 钉成 `(frame, subject, SubjectBox, visible_ratio, behind_camera)`。
- 当前 `cinema/composition.py:42–52` 的 SubjectBox 只有矩形、朝向和裁切标志；没有头／身体部位标识、数值深度、镜头 id 或相机视角。
- TDD:203–210 又要求按景别分别量头部和全身；PRD:102／TDD:99 要在证据里输出头部占画高；PRD:104 的跳切判定要真实视角差。
- TDD:219/224 默认每 4 帧采样并加密关键帧，而 :199 的持续阈值单位是 **帧**，不是“12 个样本”。

建议：在 B2 先补完整的采样契约（复用 SubjectBox，但明确 head/body 两种量及其归属，镜头与相机摘要由谁提供）；B3 只产事实，不猜缺失的部位比率。把稀疏样本时间跨度／未采样区间处理钉死，测试同一时间曲线用 step=1 和 step=4+事件帧时不把阈值单位偷换。此处不裁定具体几何算法或修改任何阈值。

### SC-09 / P2 — 两个纯函数缺必要上下文，逐镜 rhythm 合并规则未定义

证据：

- D3 计划:450 要在计划确认后读 jump-cut 计数；:460 却把核心接口固定成 `rhythm_readings(durations)`。时长列表不包含占比或视角，不能算 PRD:104 的几何条件。计划确认时真实相机也尚未构建。
- F4:592 指定 `layer_occupancy(beats)` 输出帧区间；当前 `contracts/beats.py:72–78` 的拍点只有归一化 t/pace，没有 duration_frames、位移距离或已编译动作帧。现有编译器按时长／距离算帧（`beat_compiler.py:7–13`）。
- FR-B5 的每镜 rhythm 在 PRD:93；ShotRhythm 三字段在 TDD:79–89；但一镜有多个拍点和多个 camera movements 时，用哪个 pace/curve 汇总，没有规则。

建议：节奏纯读数保留 durations 输入，jump-cut 只接收 B2/B5 的已测事件计数，明确在终审／交付阶段回填，绝不从时长推几何；占用表优先消费已编译动作帧，或显式接 duration/cast/anchors，并调用同一编译真源；钉住每镜 rhythm 来自哪个明确的声明，而非隐藏“取第一条”策略。

### SC-10 / P2 — 几处契约冲突会迫使执行者即席决策

1. **错误码撞号**：TDD:322 指定 CFG_021 preset／CFG_022 timeout／CFG_023 interval；当前 `config.py:450` 已把 021 用于 vlm_review.max_shots，:458 的 022 用于 draft_candidates，A4 实际在 :399 用 023 表示 timeout。建议保持已发货代码含义，修订文档并为新增项分配未用编号，不重写旧错误语义。
2. **ease 词义相反**：PRD:91 写“ease_out 起步 / ease_in 落地”；TDD:246–247 定义 ease_in=slow_start、ease_out=slow_end；D2:440 又要求 ease_out 末段慢。建议文档统一词义并保持双方都写明的可测“首末慢／sharp 前15%完成85%”目标，不以删断言解冲突。
3. **ambient 是 TDD 额外接口，但没有执行卡**：TDD:31／技术方案:142 要给 ShotBeat 增 ambient 动词并进入 vfx/ambience；A3:145–154 只允许拒绝错误角色并禁止改 create_vfx 参数。PRD D-17 本身只要求拒绝／引导。建议明确 ambient 是既有需求的何种落实，若保留就分派编译／schema卡，若非本版则修正文档，不让执行者自行扩功能。
4. **低 effort 显式开关没人建**：TDD:294／F1:540 引用 `llm.low_effort_on_timeout`，F1 白名单:533–538 没有 config／面板／传输。需要明确显式开关路径；自动阶梯不得偷偷降低 reasoning_effort。
5. **guard 档位权威不一致**：技术方案:110 说由计划在剧本级选；TDD:297 是 config.preset；TDD:53 又要求面板。需要先定声明、计划、配置、面板的优先级，不能让 loose 无意覆盖冻结的既有硬门。strict/loose 的实际表值尚未给出，不在本审查里自行填数。

### SC-11 / P2 — “在既有 audit.py 登记事件”指向了不存在的机制

证据：

- TDD:21／计划:37 要新事件先登记；A6:209、B2:279 等逐卡引用此机制。
- 全读 `contracts/audit.py` 的 114 行，只定义 AuditError 和 AuditResult，没有事件类型表／事件字段 schema。
- 实际 `layer6_audit/audit_logger.py:75–81` 用任意 `kind: str` 和 `data: Dict`；`:125` 的 log 收事件字符串，当前没有契约登记校验。
- B3:307 要求先登记 E_GUARD_001，但 B3:303–305 白名单甚至没有 audit.py。

建议：在最早涉及事件的 A6 中显式定义最小新事件契约表和往返／生产者对拍策略，并允许必要消费者；后续按该既定机制登记。不得仅在 docstring 列事件名就宣称满足 NFR-4，也不需要未经需求要求把所有历史事件改成拒收模式。

### SC-12 / P2 — 终验条数和圆柱误差口径存在文本自冲突

证据：

- A1 计划:98 的局部测试写 `max_delta ≤1e-6`；PRD:134 和 G2:641 的合同写 `max_delta=0.0`。不能以较松的局部断言替代终验。
- A1:86–89 列三文件（含探针登记），:109 却说“只有上述两个文件”。
- G2 表:629–644 已有 16 条，:650 的完成定义仍写“15 条全过”。

建议：修文档计数并把 A1 原始 AABB 逐位等同性终验保留；不删除测试、不放松精度。若实际浮点路径需要另定度量方法，应说明原始量测与差值生成方式，不能自行把0改成容差。

## 3. 修订方案与自我审核

建议修订顺序与原阶段顺序一致：

1. 先收口 A5 的真实无人值守数据链与次数，再明确 A6 的事件契约基础，给 A7 补报告交付通路。
2. 在开始 B 阶段前补 D-03 执行卡；在 B2 冻结 FrameSample 和告警实例标识，在 B4 补结构化判词入口及派发链。
3. C 阶段明确环境字段桥接／重问／重建三个方向；D 阶段补 curve 两层消费与节奏所有权；E 阶段补 export_project 装配及同源登记表。
4. 最后以 G2 全部 **16** 条终验和既有全量测试为准。本审查不给未实施卡判绿。

本方案已自查：

- 没有把 `brief.to_dict()` 已经能携带新字典字段的通路误报为必需重造持久化层；SC-03 指的是**重建消费**，不是“不能保存”。
- 没有要求改 24 种几何运镜求解器；SC-04 只要求保存／传递时间曲线，并量真实输出。
- 没有把用户当前“只用当前模型”的执行通道改判写成 DeepSeek/GLM 共识；G2 文本中的旧 DeepSeek 通道要求应由主线按最新用户指令处理，不在本审查中发任何外部模型请求。
- 没有把 PRD 已明确规定的 D-02 两次超时降级、FR-B1 确定性回退扩展到其他失败类型；也没有凭审查自行采用任何新降级策略。
- 以上缺口都是落实既有 PRD 的生产／消费路径或内部矛盾，不是添加新产品需求。

## 4. 取证命令与真实输出摘要

```text
git status --short
 M block_director/delivery/manifest.py
 M block_director/layer5_orchestrator/modal_operator.py
 M block_director/layer7_ui/panel_main.py
 M block_director/layer8_delivery/export_director.py
 M docs/agents/hooks/model-routing.md
?? tests/test_needs_review.py

git log -1 --oneline
2a63f95 A4: expose llm.timeout_s in config, panel and driver limits (D-01)

Get-FileHash -Path v1.6/*.md,docs/v1.6/*.md -Algorithm SHA256
PRD:     8B6829130CE3709E0323EEACF5AA2128CE1D95CD09353DF8875809AD5B2771E3
TECH:    78C5689C6263C559B7057DB889E4DDDD80D928F66D958444977A5611B1749C0C
TDD:     B90D00FFCFFDB905F7D636578C06753579E6ECE5BC7B6E80217458CD76358B68
PLAN:    CFA20BFBA2389AE44FACF39AC484D3C59F948F70726997F75F91CED64B756D9C
Each pair is equal.

python -c "from block_director.cinema.camera_motion import movement_spec; print(movement_spec({'type':'dolly_in','amount':1.0,'curve':'sharp'},shot_start=1,shot_end=48))"
{'type': 'dolly_in', 'amount': 1.0, 'start_frame': 1, 'end_frame': 48, 'seed': 0, 'subject': ''}

validate_args(TDD oneOf schema, {"toward": "not_a_target"})
[]
validate_args(TDD oneOf schema, {"toward": {}})
[]
```

其他取证：逐段 `Get-Content` 完整读取规格；`rg --files` 先盘点相关目录，再对所有卡和实际消费链定位；`git diff` 核对 A5 当前工作树。未执行全量 pytest 或 Blender（主线正在跑）；未运行真实模型样片；未验证视觉验收、人审元素识别、性能5秒门、全帧标签和恢复杀进程行为。上述都必须由后续相应执行卡提供真实证据。

## 5. 追加审查：默认值来源与 A2 可信角色表

主线追加任务后继续同一唯一角色、同一当前模型。追加起点 HEAD 为 `f95cd2d`（只追加了会话模型路由修订），A5 仍为 dirty；未改 v1.6 需求、测试、产品源码，未运行 pytest／Blender。

### SC-13 — 两条默认 5 断言属于未随新契约更新的历史测试，不应让生产默认退回 5

结论：**现行精确默认是 8，旧配置缺该键也应回落 8；显式写入 5 仍须原样接受。合法区间仍为整数 3–8，CFG_020 的拒收集合一项不能删。** 按这三条更新已过期默认值断言，是同步已经明确发布的契约，不是降低验收；不得把精确等于 8 改成“在范围内即可”或与被测实现动态自对拍。

来源逐项对清：

| 来源 | 可验证内容 |
|---|---|
| `git blame -L 34,55 -- tests/test_config_vlm_review.py` | `test_rule_top_k_default_is_five_and_legal` 与 :38 的 `==5` 来自 `a346948d`，提交日期 2026-10-07 21:04:03 +0800 |
| `git blame -L 101,110 -- tests/test_config_vlm_review.py` | 缺键兼容测试 :108 的 `==5` 同样来自 `a346948d` |
| `git log --follow --oneline -- tests/test_config_vlm_review.py` | 只出现 `a346948`，之后默认变更没有同步此文件 |
| `git show 04426d9 -- block_director/contracts/config.py specs/config.default.yaml` | 2026-10-08 01:09:38 只改注入 token 上限为 50000/60000，`rule_top_k` 仍为 5 |
| `git show 133f4b8 -- block_director/contracts/config.py specs/config.default.yaml` | 2026-10-08 01:22:42 明确将 `top_k:5→15`、`rule_top_k:5→8` 同批写进代码和生成规格 |
| `docs/evidence/20261008-v10-nodes1-4-run/README.md:165,180,187–193` | 标明定值依据为用户“你帮我决定合理的数值”、合法区间内扫参；确定 15/8；cases_top_k 保持 3 |
| `docs/v1.6/PRD_v1.6.md:115`、计划:570 | v1.6 D-06/F3 要求核验现值 15/8，明确不是重调宽度 |

因此 F3 计划:577 写的 `git show 04426d9` 是**提交定位错误**：核验 token 上限看它，核验宽度必须看 `133f4b8`。这不授权修改 cases_top_k、E1 证书语境或任何知识门。

建议主线对 `tests/test_config_vlm_review.py` 的严格处置：

1. 文件说明、测试名及两处默认期望精确同步到 **8**，注释挂 `133f4b8` 和 v1.6 D-06 来源；不是根据“实现现在返回什么”临时改期望。
2. 保留 :42 的全部六个合法值 `[3,4,5,6,7,8]` 和 :49 的全部非法／错型值 `[2,9,0,-1,3.5,5.0,"5",True,None]`；错误码和字段名断言不变。
3. 增明确的兼容反例：旧配置**显式**指定 `rule_top_k=5`，serde／加载后仍为 5，不擅自升级；与“缺键使用新默认 8”分开。
4. 生成规格同步、serde、VLM 开关／上限测试均保留；不得改成 `assert expected == AppConfig().rag.rule_top_k` 这种丢失独立默认值 oracle 的写法。
5. 同卡运行完整相关测试并在最终执行全量；本审查没有替主线把失败标为通过。

本次只读诊断命令和实值：

```text
python -c "from block_director.contracts.config import AppConfig; cfg=AppConfig(); data=cfg.to_dict(); data['rag'].pop('rule_top_k'); restored=AppConfig.from_dict(data); explicit=AppConfig.from_dict({'rag':{'rule_top_k':5}}); print({'current_default':cfg.rag.rule_top_k,'missing_key_default':restored.rag.rule_top_k,'explicit_legacy_five':explicit.rag.rule_top_k,'validation_codes':[x.code for x in cfg.errors()]})"
{'current_default': 8, 'missing_key_default': 8, 'explicit_legacy_five': 5, 'validation_codes': []}
```

### SC-14 / P1 — A2 把候选里的数字形 ID 加入白名单，违反“已分配成员资格”口径

结论：**`char_001` 的形状只说明命名格式，不证明它已分配；合法性只能由本次运行独立于候选的角色登记表证明。** 不允许由候选计划自身、由它构出的 SceneSpec 或候选-derived 场景反向补 roster。`char_a` 也不应仅因字符串形状被特殊处置：若真的在受信登记表中就按成员资格处理；表外任意字符串都应拒收。

当前漏洞的可执行证据：

- `driver.py:548–567` 的 `_cast_roster(include_from=...)` 扫描 `self.plan` 和当前候选；只要 `cid.startswith("char_") and cid[5:].isdigit()` 就把该 cid 放进 allowed。
- `driver.py:2051–2053` 恰好在校验前传入 `chunk_plan`；没有 roster 时还由 `if roster` 整段跳过。
- `_character_names()` 在 `driver.py:541–545` 没有解析名时回读已收计划；它适合旧提示侧便捷逻辑，**不适合作为独立验收白名单的权威来源**。
- `contracts/plan.py:38–51` 的纯 `unknown_cast_ids` 本身会按集合拒收，问题在上游传给它的集合被候选污染；现有 `tests/test_cast_hard_check.py:35–38` 手工给合法 roster 只证明纯函数，不覆盖生产者。

轻量只读复现（不构建场景、不调 LLM）：

```text
python -c "from types import SimpleNamespace; from block_director.layer5_orchestrator.driver import PrevisDriver; from block_director.contracts.plan import Plan, ShotPlan, unknown_cast_ids; from block_director.contracts.enums import ShotType; driver=object.__new__(PrevisDriver); driver.parsed_script=SimpleNamespace(character_names=['Alice']); driver.plan=None; candidate=Plan(shots=[ShotPlan(shot_id='shot_001',intent='test',shot_type=ShotType.MS,duration_frames=48,characters=['Alice','char_999'])]); roster=driver._cast_roster(include_from=candidate); print({'candidate_characters':candidate.shots[0].characters,'derived_roster':roster,'unknown':unknown_cast_ids(candidate,roster)})"
{'candidate_characters': ['Alice', 'char_999'], 'derived_roster': ['Alice', 'char_999'], 'unknown': []}
```

可信内部 ID 的实际生产链与当前映射边界：

| 路径 | 真实生产者／承载者 | 可作为独立来源的条件 |
|---|---|---|
| 用户添加角色 | `panel_cast.py:97–105` → `cast_editor.add_cast_member:98–118`：调用 `next_character_id`，创建对象，再登记 `context.characters[id]` 和 `context.spec.cast += CastMember(id,name,...)` | 登记完成且属于当前运行／工程；不是扫描本次模型候选新建的对象 |
| 纯 ID 分配 | `contracts/cast.py:269–283` 确定性分配最低空缺 `char_NNN` | **单独调用函数不是登记证明**；必须伴随权威 CastMember 登记 |
| 已保存工程 | `project_io.py:122–139` 的 load_project 读文件、迁移、反序列化、校验；`sdl_builder.py:207–215` 从 `SDLProject.characters` 建 spec.cast | 当前明确加载的工程角色清单；不能取某待验证候选刚派生的 SDL |
| 新剧本角色名 | `layer1_input/model.py:179–185` 的 `ParsedScript.character_names`，以及声明侧 aliases:163–165 | 输入解析后的固定角色名；没有已登记 ID 映射时，不能凭 `char_N` 序号猜人物 |
| 离线分镜声明 | `offline.py:77–83` 按**输入声明**首次出现顺序建立 `name→char_NNN`；:98 用它产出镜头引用 | 这是已存在的真实确定性生产者，但 mapping 当前是局部变量，应抽成同源纯函数／事先登记数据注入 roster，而非从返回候选重推 |
| 无声明的默认两镜 | `offline.py:33–64` 明确使用 `char_001/char_002`，不是用户姓名映射 | 使用事先定义的固定演示 cast，与候选输出分离；不能将“offline”当任意候选 ID 的免检通行证 |

重要：**SceneContext 当前并没有自动 name↔id 映射**。

- `scene_context.py:20` 注释明确 `characters` 为 `id → Character`；`:34–35` 仅 `self.characters.get(character_id)`。
- `shot_builder.py:578–603` 从 spec.cast 创建对象，并只按 `member.id` 写 cast_map／characters；显示名只用于 create_character 和标签。
- `cinema/subjects.py:37–38` 同样只按对象 `id` 查被摄主体。
- 所以把 name 和 id 都放进“可接受字符串集合”还不等于工具与场景能一致消费。若允许 name/已登记id 两种入口，需根据**显式 CastMember(id,name)** 在边界统一成既有 canonical id，并保留显示名；不能让同一个人以 name 和 id 两次构建。

建议主线的修复边界：

1. 将可信 roster／id-name 映射在运行装配时注入纯驱动；GUI 读取本次明确选定的 spec.cast，headless／重建读取输入解析或所加载工程。纯 driver 不 import bpy，不从不相关的全局旧场景自动扩张。
2. 保留“没有输入角色表”与“角色表明确为空”的区别。空表不得关闭校验；确实缺少权威输入时如实诊断，不从候选填表。
3. 离线声明使用现有确定性映射的同一生产者，固定演示 cast 另行显式登记。注入的是独立登记数据，不是调用 transport 得到的候选 characters。
4. 在计划分块接收、B1 草案合并、repair/react 的 `emit_shot_draft` 和导出闸处都消费同一权威集合；若新增合法角色，只能经已有用户角色管理动作更新权威集合，不能因模型声称而扩大。
5. 对合法 `CastMember(id="char_001", name="周野")`，同时验证成员放行、显示名正确、实体只一份、下游按 canonical id 找得到；非法 `char_999` 即使数字格式正确也拒收并触发原有重问机制。导出 `roster=None` 当前在 `export_director.py:152–153` 直接返回无错误，该入口漏接必须一并覆盖，不能以缺参表示“免验”。

以上是从 A2“成员资格而非正则”的原需求推导出的信任边界，不新增角色类别，不修改既有规则门限。原始场景视觉、用户添加实际 Blender 对象、无头恢复和所有测试是否通过仍留给主线真实验证；本追加只给静态证据与两个纯只读诊断。
