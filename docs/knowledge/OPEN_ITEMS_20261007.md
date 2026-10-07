# 未完成项与缺陷总表（BlockDirector / P14，2026-10-07 03:4x 采）

> ## ⚠️ **接管状态（2026-10-07 执行文档 v1.5 落地后加注）——先读这一段再读下表**
>
> 下表是**采集时刻（03:4x）的快照**。执行文档 v1.5 已把其中绝大多数**做掉或备料完毕**；
> **以本块为准**，下表的原文**保留存档**（不删、不改写）。总索引：
> `docs/evidence/20261007-v15-final/README.md`；单树链读数：`docs/evidence/20261007-083902/`。
>
> | 条目 | 现在的状态 | 落点 |
> |---|---|---|
> | **A1** E1/RK-13 | **仍是链上唯一的红**（按设计；判据冻结、已结案） | `RK13_CLOSEOUT.md`；链 `rks.json` `failed_checks=["RK-13"]` |
> | **A2** 复议配方 | **不变**（休眠项，等触发条件） | 同上 §5 |
> | **A3** 两评委差 0.27 | **备料完成**（归属文档＋rubric＋20 条校准流程） | `docs/knowledge/JUDGE_ALIGNMENT_v1.md` |
> | **A4** 深度-12 真判 oracle 未量 | **备料完成**：14,080 个三元组 ≈ 403 h 串行（估算已锚在 192 行/1h50m 上） | `docs/evidence/_v15_stage8/a4_depth12/` |
> | **A5** R1/R5/D10/D11 须用户点头 | **已格式化成裁决包**（问题→选项→影响面→证据→建议） | `docs/evidence/20261007-0610-p5t3t4/adjudication_pack.md` |
> | **A6** 换代登记机制 | **模板落地**（并按此办了第二十八次仪器重签） | `docs/knowledge/REGEN_LOG_TEMPLATE.md`、`tests/plan_v4_instruments.sha256.json` `_reason_28` |
> | **B1** "132 张手写卡不在索引里" | **前提被实测证伪**：抽取器早已纳入；索引引用 **2262/2353**，手写卡 **116/132 已被引用**，零边的只有 **16 张**；`AGENTS.md` 的失实陈述已改正 | `docs/evidence/20261007-v15-closeout/adjudication_p5t2_index_regen.md`、`AGENTS.md` **另**：C1 的三分类结论（后两类 74.4%、四层一致）给"该不该换代"提供了正面证据——语料侧确实需要重抽/重挂。 |
> | **B2** `axis_side` 两套词表不相交 | **备料完成**（并实测“路线 B 的前提被校准数据推翻”，真正的待裁点是**定义 left/right 指谁**） | `docs/evidence/20261007-0610-p5t3t4/adjudication_axis_side_domain.md` |
> | **B3** 33 条"判不了"的边 | **备料完成**：实测 **8 条不同边／32 次出现／13 槽位**；提案覆盖 8/8、**可直接落地 0/8** | `docs/evidence/_v15_stage8/b3_coverage/` |
> | **B4** movement 中英词表没别名 | **备料完成**（对照表＋VALUE_ALIASES 提案＋缓存键纳入方案） | `docs/evidence/20261007-0610-p5t3t4/adjudication_movement_aliases.md` |
> | **B5** 5 个零成员 kind | **诊断完成**：2 个漏抽（`applies_to_genre`/`applies_to_shot_size`）、3 个有意延后 | `docs/evidence/20261007-054900-p5t1/zero_member_kinds.md` |
> | **B6** ②③类未纳入判定 | **映射增量一节已附**在 B5 的诊断报告里（维持"先诊断、不设门"） | 同 B5 |
> | **B7** forbid 守门能力为 0 | **已激活并实测**：同代重放 103 条真实查询 → `forbid_members_seen = 217`，且 top-1 逐条保持 | `docs/evidence/20261007-g4-forbid-guard/` |
> | **B8** 两边词表重叠度 | 随 B2/B4 的对照表收口（`vocabulary_gap` 落在闭环报告里） | 同 B2/B4 |
> | **C1** 90 槽位三分类 | ✅ **已完成（90/90，单一判官 `qwen3.8-max-0902`＋思考拉满）**：`corrupt = 67/90 = 0.7444` → **`corrupt-dominated`** ⇒ 按裁定口径**「暂缓重抽」被证伪、应启动换代**；四个分层一致（0.65–0.80） | `docs/evidence/20261007-grounding-sample90/三分类汇总.json`、`docs/evidence/_v15_stage8/c1_recap/` |
> | **C2** 9 边/15 槽位局部手术 | **备料完成**（换卡 vs 删边两案＋换代影响面＋A6 预填表）；**索引零字节改动** | `docs/evidence/_v15_stage8/c2_edge_surgery/` |
> | **C3** `topic` 字段准确率没核 | **诊断完成**：`topic` 是来源级标签（对卡级零分辨率）；机械预读 88/90 里至少 23 行是"不知道" | `docs/evidence/_v15_stage8/c3_topic/` |
> | **C4** 未佐证槽位双口径 | **口径校验脚本落地**（措辞纪律＋两分母并列＋`not-checkable ≤ 345`） | `tools/knowledge/attestation_ledger.py`、`docs/evidence/_v15_stage8/c4_ledger/` |
> | **C5** 19 份 superseded 是否失据 | **机械解析完成**：22 份 pin / **21 份就是现行代** / 1 份退休(gen0)；语义那一半裁定说"不能定案" | `docs/evidence/_v15_stage8/c5_superseded/` |
> | **C6** 16 条 `amended` 的 fix | **实测是换代**（层为被 pin 的 gate 输入）⇒ 停手备料 | `docs/evidence/_v15_stage8/c6_layer_fix/` |
> | **E1–E5** 文档一致性 | **已修**（抬头／悬空引用／台账注记／AGENTS 读数刷新） | `docs/knowledge/OPEN_PROBLEMS.md`、`AGENTS.md`、`PLAN_HYPERGRAPH_v4_PROGRESS.md` |
> | **F1** C 盘 2.7 GB | **已过期**：实测可用 **≈26.8 GB**（文档已改注） | `docs/evidence/20261007-v15-final/README.md` §6.4 |
> | **F2/F3/F4** 通道现状 | **不变**（Kimi 挂起；GPT-6A 仅显式回退；GLM 抖动）；本机另缺 `GLM_API_KEY` | 同上 §6.2 |
> | **F5** 工作树未提交 | **清单已出**（`P0-T2`）；**提交口径待用户确认**（`P7-T2`） | `docs/evidence/20261007-050254-baseline/worktree_inventory.md`、`20261007-v15-closeout/commit_grouping.md` |
> | **G1–G9** 历史点名待核 | **逐条核查完成**（10 条判词：open 6 / closed 4），**一处代码未改** | `docs/evidence/_v15_stage8/g1_g9_recheck/` |
> | **七/八节** 已结案与"已不存在" | **不变**，仍不许当待办 | 本文件下文原样 |
>
> **仍真正开着的只有三件**：① 用户对 `P5-T2`（要不要为零边卡换代）与 `P7-T2`（提交口径）拍板；
> ② `C1` 余下 10 批（**只差一个 `GLM_API_KEY`**）；③ 各 ⚖️ 备料件所等待的裁决本身。

**这份表的性质**：只列**当前**还开着的未完成项与缺陷，每条给"证据 / 判据"。
已结案、已裁决、以及**我实测后确认已经不存在**的历史条目，单独放在末尾——
不许把它们当待办，也不许反过来把待办写成已完成。

**采集方式**（全量，不是按需挑）：`docs/knowledge/ACCEPTANCE_STATUS.md`（6322 行，
逐节扫 `还没做/未做/待办/未验证/仍未/待裁`）＋ `PLAN_HYPERGRAPH_v4_PROGRESS.md`（2511 行，
后 1200 行逐行扫）＋ `RK13_CLOSEOUT.md`（全文）＋ `ADJUDICATIONS_v4.md`（全文筛 `须用户点头`）
＋ `OPEN_PROBLEMS.md` ＋ 现行工作树与运行中进程 ＋ 索引产物实测。
**凡我没有实测支撑的，一律标"待核"并给出行号**，不写成结论。

---

## 一、判据 / 验收类

| # | 项 | 状态 | 证据 |
|---|---|---|---|
| A1 | **E1 / RK-13 是链上唯一的红**（判据 `E1 ≥ 0.70`，等价 ≥135/192；现行 0.1771=34/192） | **已结案，不是待办**：GLM-5.3 两轮裁定"现行判据下不可达"（门要求可用上界约 **1.61 倍**，缺口 **51 行**），按 (a) 结案；链上**照旧报红并 `exit 1`** | `RK13_CLOSEOUT.md` 全文；`docs/evidence/20261006-e1-gate-glm/` |
| A2 | **复议配方（休眠项）**：原样重判 20 个三元组各两次且**逐分一致** ＋ 试跑 50 个三元组计时落进数小时量级。两项都过才重新考虑 (B) | **未做（预注册，等触发）** | `RK13_CLOSEOUT.md` §5 |
| A3 | **两位评委同批差 0.27**（deepseek 0.44–0.46 ／ glm 0.67–0.7120）⇒ "过没过线取决于用哪把尺"；判据冻结 ⇒ 只能"对齐判据"不能改阈值 | **未做，且至今没有归属文档**（是整份清单里唯一没有承接的技术问题） | `OPEN_PROBLEMS.md` P2；`docs/evidence/20261006-rerank-shapes/README.md` |
| A4 | **深度-12 的真判 oracle 从未量过** | **未做**——结案文书里唯一没有真判支撑的承重墙，已逐字标 proxy-only ＋ 推断 | `RK13_CLOSEOUT.md` §3／§7 |
| A5 | 仍标 **`须用户点头`** 的四条：**R1**（噪声带 R 是否升为验收门限）、**R5**（`Case` 新增可选字段进 `schema_fingerprint` 纳管范围）、**D10**（某臂召回为空时 E1 分母怎么算）、**D11**（"看得见的降级"是否升格成"该臂无效"的机器门） | **未重新路由**：按 2026-10-06 改判，决定应走 **GLM-5.3**，而这四条还挂在旧表上 | `ADJUDICATIONS_v4.md:20`／`:24`／`:26`／`:51` |
| A6 | **索引/夹具换代会让已入库运行失配**：23 次运行把索引指纹与 oracle 整文件 sha 钉进 `run_manifest.json.pins`；`repin()` **拒绝**把"换代"洗成"没换行" | **未做（机制已在，动作未做）**——任何删边/改夹具都要显式登记换代 ＋ 最小重跑 | 台账 P14-318；`RK13_CLOSEOUT.md`；门⑦ 先例 |

## 二、知识栈 L1/L2（超图索引）

| # | 项 | 状态 | 证据 |
|---|---|---|---|
| B1 | **132 张手写策展卡不在索引里**（索引覆盖 2221/2353） | **未做** | `ACCEPTANCE_STATUS.md` 顶部读数板 K1；`AGENTS.md:58` |
| B2 | **`axis_side` 值级绑定未做**：字段已落进 `shots.json`，但索引侧仍是 `left/right/neutral`；成片侧只有 `correct`/`crossed` ⇒ **两套词表不相交**，62 条 `unmatched`（＝前提不成立） | **未做**；裁定要求"弃 `left/right`、索引改用符号域"＝**知识侧换代** | 台账 P14-313／P14-315／P14-317 的"未验证/边界"：`PLAN_HYPERGRAPH_v4_PROGRESS.md:2347`／`:2376`／`:2471` |
| B3 | **剩余 33 条"判不了"的边**（全在 `headroom_policy`／`composition_rule`／`camera_angle`）：它们缺的不是区间，而是**适用域语义** | **未做**——`APPLICABILITY_SEMANTICS_v1.md` 是**提案，未实施**（不改判据、不设门） | `APPLICABILITY_SEMANTICS_v1.md`；台账 `:2508` |
| B4 | **`movement` 的中英词表只量了落差、没编别名**（知识侧有 `固定` 这类中文取值，成片侧是 `dolly_in` 这类英文枚举） | **未做**；**编别名＝新判据，须裁定** | 台账 P14-309 |
| B5 | **声明了但索引里零成员的 kind（5 个）**：`applies_to_genre`、`applies_to_shot_size`、`carry_shots`、`example_shot`、`seq_phase` | **待核**：是有意不用（如 `example_shot` 被门显式排除）还是漏抽——**未逐条核** | 实测 `knowledge/hypergraph.edges.jsonl`（schema 声明 30 kind，实际用到 25） |
| B6 | **执行闭环的 ②类（成片无字段）与③类（话题/标注）仍未纳入判定**；映射表只有 7 个 kind | **未做**（按裁定"先诊断、不设门"） | 台账 `:2268`、`:2411` |
| B7 | **"违规 0"至今仍是"无物可违"**：第二次真跑 `edge_active = 30`，但**这 30 条一条 `forbid` 成员都没有** ⇒ `forbid_members_seen = 0` ⇒ 裁定 F4 的设门条件 (a) 仍为 **0** | **设计状态**（意味着"执行闭环"目前**没有守门能力**） | 台账 P14-317；`docs/evidence/20261007-execution-closure-v2/` |
| B8 | **两边词表不是同一种话**：`shot_size`/`intent`/`lens` 完全重叠，`movement` 只部分重叠，`axis_side` 完全不相交 | **部分未做**（movement 已从"没得比"变成"能比"，值域重叠） | 台账 P14-309／P14-316；`20261007-uncovered-kinds-grounding` |

## 三、出处缺口（**进行中**，当前主线正在推的一件事）

| # | 项 | 状态 | 证据 |
|---|---|---|---|
| C1 | **90 槽位分层三分类**（裁定给的"修数据 vs 接受下界"分水岭）：≥33% 后两类 ⇒ 暂缓重抽被证伪；≤10% ⇒ 修数据被证伪 | **进行中／部分完成**：`batch1`、`batch12` 有产物；`_superseded/` 是那批失败重跑；新增 `tools/knowledge/grounding_classify.py` 与 `glm_consult --plain` 修复**尚未提交** | `docs/evidence/20261007-grounding-sample90/`；工作树 `M tools/glm_consult.py` |
| C2 | **9 条边 / 15 个槽位待"局部手术"**（换卡或删边）；机械判定 `topic_mismatch 14` | **未做**——因为**删边＝改 `hypergraph.edges.jsonl` ⇒ 索引指纹换 ⇒ 23 份运行 pin 全失配** ⇒ 要按门⑦ 的规矩显式登记＋最小重跑 | 台账 P14-318；`work/_probe_wrong_card.py` |
| C3 | **`topic` 字段本身也是生成物，其准确率没核**（机械预读 88/90 全靠它） | **未做** | `docs/evidence/20261007-grounding-sample90/README.md` §四 |
| C4 | **未佐证槽位两个口径都要报**：`attested 331 / unattested 1262 / not-checkable 345`，`share 0.2078`（分母＝可检 1593），按全 1938 算是 **0.1708** | **记账纪律**：措辞一律"未被来源佐证"≠"编造"；成功线必须同判据同分母并钉住 `not-checkable ≤ 345` | 台账 P14-318 |
| C5 | **19 份 `superseded` 是否让 Q1/Q2/Q4/Q6b 失据** | **未定案**（裁定明说不能定案） | 台账 `:2159` |
| C6 | **层里 16 条 `amended` 的 `fix` 文本仍未生效**（本轮的层是**输入工件**） | **未做** | 台账 `:2192` |

## 四、文档一致性缺陷（本轮实测发现，**与代码无关但会误导下一个人**）

| # | 缺陷 | 证据 |
|---|---|---|
| E1 | **`OPEN_PROBLEMS.md` 没有"已被接管"抬头**：P1 已结案、P3 已被真跑推翻、P4 已解、P5 已被吸收，但文件里仍按"未解问题"呈现 | `docs/knowledge/OPEN_PROBLEMS.md`（最后提交 `0b08733`，10-06 09:42） |
| E2 | **悬空引用**：`AGENTS.md:58` 与台账 `:1325` 都写"见 `OPEN_PROBLEMS` (19) / ⑲"，而该文件只有 **P1–P6**，没有第 19 条 | `AGENTS.md:58`；`PLAN_HYPERGRAPH_v4_PROGRESS.md:1325` |
| E3 | **台账的 `## 当前阻塞与下一步`（第 118 行）已过期**：仍写"P10 待处置"，而 P10 早已裁 **D13 = A** | `PLAN_HYPERGRAPH_v4_PROGRESS.md:118` |
| E4 | **台账编号错位与落后**：`P14-308` 排在 `P14-307` 之前（作者自陈是锚点插入造成）；`P14-295` 有两节撞号；台账尾停在 **P14-318** 而 HEAD 已是 **P14-319** | 台账 §P14-309 的"编号说明"；`git log` |
| E5 | **`AGENTS.md` 状态块与现行读数不一致**（仍写着 2085 passed 之类历史数；现行是 2470 passed / 1 skipped @ `bd74e4a`） | `AGENTS.md` vs `ACCEPTANCE_STATUS.md` 顶部读数板 |

## 五、环境与通道

| # | 项 | 证据 |
|---|---|---|
| F1 | **C 盘只剩约 2.7 GB**（pytest 的 tmp 在 `%TEMP%`；`~/.cache/huggingface` 19.2 GB 因 HF 只有镜像可达而**故意不删**） | 台账 P14-220 |
| F2 | **Kimi 余额挂起**（429 `exceeded_current_quota_error`）⇒ 回退通道不可用；发货代那条 **85% 降级**的重排读数**已作废** | `docs/evidence/20261006-kimi-quota/` |
| F3 | **GPT-6A 已降为显式回退**（非默认）：已知包线＝Cloudflare 524（~100 s 边缘超时）、74,565 字符大包 50 分钟零输出、一次裁定 2900 s 且正文截断 467 字符 | 台账 P14-289／P14-290 |
| F4 | **GLM-5.3 自身抖动**：同一份包一次 **900.1 s 超时** vs 一次 **275.6 s 成功**（n=1 vs n=1，**根因未查**） | 台账 `:1705`、`:1926` |
| F5 | **工作树当前未提交**（2026-10-07 03:4x）：`M tools/glm_consult.py`、`M tests/test_glm_consult.py`、`M docs/evidence/20261007-grounding-sample90/*`、`?? tools/knowledge/grounding_classify.py`、`?? docs/evidence/20261007-grounding-probe/`、`?? docs/evidence/20261007-wrong-card-correction/`、`?? .../_superseded/` | `git status --porcelain` |

## 六、历史记录点名、但**现行台账未见收口记录**——需逐条核对（不当结论用）

> 这几条来自早期审计章节（10-01～10-03）。它们**可能已经做过**，也可能没有；
> 我没有在现行台账里找到对应的收口记录，所以标"待核"并给行号，**不写成缺陷**。

| # | 项 | 出处 |
|---|---|---|
| G1 | 抽取提示里的历史措辞（"13 类"、规则 4b 的"挂到 `EMOTION_PACK`"）是否随 `extract/v18` 收口 | `ACCEPTANCE_STATUS.md:1248`（§20.8） |
| G2 | `schema` 仍没有"运镜政策"的宿主（`gen_cine_0247` 那条知识的禁半没进索引） | `ACCEPTANCE_STATUS.md:1248`（§20.8 第 2 条） |
| G3 | 用户手工项的 **ollama 残片** | `ACCEPTANCE_STATUS.md:1260` |
| G4 | **抽取提示漂移**（§22.2，被记成"覆盖率交换"，需与整库重抽＋重标同批处理） | `ACCEPTANCE_STATUS.md:1416`、`:1543`、`:1850` |
| G5 | **按 chunk 的原子边缓存**（cache_key ＋ 语料 sha 命中就不重抽） | `ACCEPTANCE_STATUS.md:1940` |
| G6 | `rule_of_thirds` / `lead_room` 的口径裁决；"求解器遵守 §10.4 vs 评分模型接受居中主体"仍两条未裁 | `ACCEPTANCE_STATUS.md:3965`、`:4001` |
| G7 | `drift_is_bridged` 的**参照系**（"自上次已交代状态以来"）未换——它是另一个状态机 | `ACCEPTANCE_STATUS.md:4773` |
| G8 | Q5 的**基准串口径**（计划期 `retrieval_call.query` 与 `ShotContract` 分母不一致） | `ACCEPTANCE_STATUS.md:1129`（§19.5 第 1 条） |
| G9 | **词表（别名表）仍不在缓存键里** ⇒ "同一指纹 ⇒ 同一索引"在别名表维度上不成立 | `ACCEPTANCE_STATUS.md:1260` 之后（§20.8 第 4 条） |

## 七、已结案 / 已裁决——**明确不计入未完成**

* **E1 / RK-13**：结案 (a)，判据一字未动，红如实记（见 A1）。
* **门⑦ 人审那一格**：gen2 落地，链上口径 `third-party 212`，**夹具字节未动**。
* **§7 唯一待拍项 D1b 躯干形状**：裁 ②圆角方体，已落地（P14-302）。
* **P10 / D13**：裁 **A 不切换**（v4 只作影子）。
* **D12**：裁 **C**（双口径显式）。
* **R3**（红线不可达的处置）：已被 RK-13 结案吸收。
* **云端嵌入放交付位**：真跑 **0.1667／0.1146 ≤ 现役 0.1771** ⇒ 已经勘误，是**负结果**不是待办。
* **v1.4 的 9 个阶段（P9.4→P16）**：逐条落地（落点抽查：`contracts/plan.py:70/91`、
  `config.py:141`、`delivery/manifest.py:24-25/28-29`、`driver.py:1307`、
  `modal_operator.py:98`、`cinema/anchor.py`、`tools/check_assertions.py`、`CONTEXT.md`、`docs/adr/` 9 份）。

## 八、我实测后确认**已经不存在**的历史条目（防止下游误列）

| 历史条目 | 实测 |
|---|---|
| "`SHOT_PATTERN.movement` schema 里有、索引里一条都没有"（§19.5 第 2 条） | **不成立**：`SHOT_PATTERN` 83 条边里有 **59 条带 `movement` 成员** |
| 门⑥ 的孤儿卡 `gen_cine_0247` | 已归零（`edge_backed_without_entry_count` 1 → 0，P14-217） |
| "莫名其妙的批量红"（pytest） | 具名根因＝**C 盘写满**（`Errno 28`）；清 pip 缓存 2.6 GB 后同一套代码 **2347 passed / 1 skipped** |
| "去标签池首跑 1,280 行全 None" | 具名根因＝子进程缺 `GLM_API_KEY`；已加 `e1_panel.preflight` 握手 |
| "第三轮判词把 0.375 当终值、按 1.87 倍/63 行读" | 复议后应读 **约 1.61 倍 / 缺口 51 行**（135 对 84），8 条试点 0.375 保留为历史读数 |

---

## 附：当前正在跑 / 刚停的东西（2026-10-07 03:4x）

* **90 槽位三分类**：`docs/evidence/20261007-grounding-sample90/` 下已有 `batch1`、`batch12`、
  `questions/`、`_superseded/`；驱动脚本 `work/_run_grounding_batches.py`（PID 50620 已于 03:3x 退出）。
* **失败的那一版已具名**：`batch1/测试与验收.failed.json` —— `--level high` 与 `low` 两次
  都把 8192 completion 全烧在 reasoning（8169／8178）、`finish_reason=length`、正文空。
* **根因已定位并写好补丁（未提交）**：`glm_consult` 的**角色 system 模板**与问题的输出契约
  互斥（system 要 JSON 对象、问题要 JSON 数组）⇒ 模型把预算花在调和上。
  修法＝**标注类任务走 `--plain`**（无 system），实测同一份 2 条分类问题：带角色
  170.4 s 回错形状，去掉 system **32.9 s 回正确数组**。
* 顺带第三次记下：**中文角色名不能走 PowerShell 5.1 命令行**（ANSI/GBK 解码 ⇒ "未知角色"），
  必须 Python 进程内传参。
