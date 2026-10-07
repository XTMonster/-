# 会诊包（实际送进模型的逐字内容）

## system（角色：人工裁决）：本次**没有** system 提示词（`--plain` 机械标注包，问题自带输出契约）

## user（所有角色共用；角色 人工裁决 的包逐字如下）

```text
# 本次要审的问题

# 裁定：v1.5 收尾的**分组提交口径**（P7-T2）

## 背景

BlockDirector 的执行文档 v1.5 已落地并**验证通过**（本工作树：`python -m pytest`
2808 passed / 1 skipped / 0 failed；`run_tests.ps1` 完整跑完 35/35 步，
唯一红是已结案的 RK-13/E1）。卡 P7-T2 写的纪律是：

> 「提交前向用户展示分组清单，**确认后**执行」

用户 2026-10-07 把这条**确认**授权给了你：

> 「老账未动：P7-T2 分组提交口径、210 个零候选槽位（含 axis_side 一族）的删边/裁决。
>   用拍板的问题 2 的那个 qwen3.8max0902 解决，**代替人工裁决**」

也就是说：**你的判词代替用户的"确认"**。判词要能直接执行。

## 现状（客观事实）

* HEAD：`f6530c6`；工作树**未提交**，`git status --porcelain` 有 **166** 条
  （既有 v1.5 各阶段的改动，也有今天这一轮换代的改动）。
* 备料清单：`docs/evidence/20261007-v15-closeout/commit_grouping.md`（**逐字读它**）：
  78 组条目分成若干组，每组文件互不重叠；少数文件同时承载两张卡的改动（清单里标了 ⚠️）。
* 今天新落的、**清单写成之后**才出现的产物（清单里没有它们，需要你决定放哪一组）：
  `tools/kb_fetch/rebind.py`、`tools/kb_fetch/build_hypergraph.py`、
  `knowledge/hypergraph.{edges,manifest}.json`、`knowledge/card_scope.json`、
  `docs/knowledge/REGEN_LOG_20261007_rotation.md`、`docs/evidence/20261007-v15-*/`、
  `docs/evidence/20261007-204326/`、`block_director/motion/model.py`（坐标参数校验）、
  `block_director/layer5_orchestrator/driver.py`（构建失败留 traceback）、
  `tools/sidecar_server.py`、`tools/glm_consult.py`、
  `tests/test_rebind.py`、`tests/test_action_param_values_are_checked.py`、
  `tests/test_sidecar_retrieve.py`、`tests/test_glm_consult.py`、
  `tests/test_budget_gate.py`、`tests/test_extract_run_evidence.py`、
  `tests/test_q5_audit_channel.py`、`tests/test_evidence_digest_is_checkout_independent.py`、
  `tests/test_chain_evidence_is_measured.py`、`tools/run_tests.ps1`、
  `block_director/contracts/config.py`（token 上限两格）＋ `specs/config.default.yaml`、
  `AGENTS.md`、`docs/knowledge/ACCEPTANCE_STATUS.md`、`CONTEXT.md`。

## 请你裁的三件事（给可执行的结论，不要复述背景）

1. **分组口径**：是**照清单执行**（并把它之后新增的产物按主题并进最合适的那一组），
   还是要调整？若调整，请给出**完整**的组表（组号 → 文件 → 提交信息），
   并说明与清单的差异理由。
2. **每组的验证粒度**：每一组 commit 前后要不要跑测试？跑什么？（本仓现状是一整套
   `pytest` 约 3 分钟、完整链约 40 分钟；逐组跑完整链显然不现实——请给一个**你认账**的
   最低口径，并说清"哪一组必须跑什么"。）
3. **换代那一组的地位**：知识索引换代（`rebind/v1 → v2`，索引指纹 `c796a5a8… →
   e5213e1b…`）是**独立一组**、先提交，还是与其它改动合并？理由是什么？
   （注意：索引一换代，22 份已入库运行的 pin 就如实失代，这是**记录在案**的预期行为。）

**只输出一个 JSON 对象**：

```
{"verdict": "采纳|修正后采纳|退回",
 "groups": [{"id": 1, "files": ["..."], "message": "<提交信息>"}, ...],
 "verification": {"per_group": "<每组跑什么>", "full_chain": "<什么时候跑完整链>"},
 "index_regen_group": "<把换代放哪一组、为什么>",
 "why": "<≤200 字>",
 "risks": ["<≤40 字>", ...]}
```


## 源码：docs/evidence/20261007-v15-closeout/commit_grouping.md（第 1–181 行，逐字，带行号）

```
    1| # 裁决备料 · P7-T2（文档同步与提交）——**分组清单，未执行任何 git 提交**
    2| 
    3| **run-id**：20261007-v15-closeout
    4| **HEAD**：`f6530c6e44702028c6e42a9e1d11436c0b19d1c2`（工作树未提交，78 组条目）
    5| **纪律**：卡 P7-T2 写明「提交前向用户展示分组清单，**确认后**执行」；
    6| 本文件就是那份清单。**一个 commit 都还没做**。
    7| 
    8| ---
    9| 
   10| ## §1 分组（每组文件**互不重叠**，可直接 `git add` 逐组提交）
   11| 
   12| > 说明：少数文件同时承载**两张卡**的改动（git 只能把整个文件放进一条 commit），
   13| > 这些文件在表里加了 ⚠️ 并注明第二张卡；提交信息必须两句都写。
   14| 
   15| ### 组① 契约层（v1.5 P2-T1…T5）
   16| 
   17| ```
   18| block_director/contracts/beats.py            (新) ShotBeat/LightSpec/CompositionSpec/RuleJustification + validate_beats
   19| block_director/contracts/plan.py                   ShotPlan.beats/composition/rule_justifications + Plan.environment
   20| block_director/contracts/sdl.py                     SDL 1.5：SDLAnchor + environment.anchors/light + shot 三字段
   21| block_director/layer2_sdl/sdl_builder.py            SDL 1.5 导出
   22| block_director/layer2_sdl/sdl_migrate.py            KNOWN_VERSIONS += "1.5"；1.4→1.5 纯缺省填充
   23| block_director/contracts/config.py                  rag.rule_top_k(5,3–8) + vlm_review{enabled,max_shots}
   24| specs/config.default.yaml                           （由 tools/gen_specs.py 生成，勿手改）
   25| specs/openapi.yaml                                  sidecar DTO 同步
   26| fixtures/expected_sdl_simple.json                   ┐
   27| fixtures/expected_sdl_long.json                     │ R-11：只经 tools/gen_golden.py 重生成
   28| fixtures/expected_shots_long.json                   │ （漂移只有 version 1.4→1.5 与新增可选字段）
   29| fixtures/tool_transcript_simple.jsonl               ┘
   30| tests/test_beats.py                                 (新)
   31| tests/test_plan_v15_fields.py                       (新)
   32| tests/test_sdl_15.py / tests/test_sdl_v15.py        (新)
   33| tests/test_config_vlm_review.py                     (新)
   34| block_director/contracts/vlm_review.py              (新) VLM 评审 DTO（P6-T1 的契约面）
   35| ```
   36| 
   37| 建议信息：`feat(v1.5-契约): 拍点/锚点/灯光/构图/破例辩护五类契约 ＋ Plan.environment ＋ SDL 1.5 迁移 ＋ 配置三键`
   38| 
   39| ### 组② 求解器与引擎（v1.5 P3-T1…T4，含 P2-T4 的工具 schema）
   40| 
   41| ```
   42| block_director/layer5_orchestrator/beat_compiler.py (新) 拍点表 → actions 的确定性编译与合并
   43| block_director/layer5_orchestrator/planner.py       ⚠️ 兼 P2-T4：emit_plan 增 optional environment
   44| block_director/layer5_orchestrator/editor.py        ⚠️ 兼 P2-T4/P4-T4/P6-T2：逐镜 schema/提示词/候选骨架
   45| block_director/layer5_orchestrator/driver.py        ⚠️ 兼 P2-T4：草案合并回 ShotPlan
   46| block_director/layer5_orchestrator/headless_runner.py  ⚠️ 兼 P4-T1/T2：三栏渲染接 rulepack
   47| block_director/layer5_orchestrator/modal_operator.py   SDL 1.5 落盘
   48| block_director/cinema/staging.py                    (新) solve_anchor_positions
   49| block_director/cinema/lighting.py                   (新) resolve_lighting_preset 矩阵
   50| block_director/cinema/props.py                      (新) 道具交互动词 → 跟随关键帧
   51| block_director/cinema/station.py                    aim_offset_for_composition（构图声明消费）
   52| block_director/cinema/anchor.py                     派生链（冻结几何 1.70 / ADR-0007 不动）
   53| block_director/layer3_engine/scene_executor.py      ⚠️ 兼 P3-T2/T3：锚点落位 + 灯光矩阵 + 道具事件
   54| block_director/layer3_engine/shot_builder.py        拍点编译接线 + 构图偏置
   55| block_director/layer7_ui/panel_shots.py             镜头面板带新字段
   56| tools/run_headless.py                               导出链路带新字段
   57| tests/test_beat_compiler.py / test_staging_anchors.py / test_lighting_matrix.py
   58| tests/test_prop_interaction.py / test_composition_consumption.py        (新)
   59| tools/blender_tests/test_anchor_staging.py / test_prop_interaction.py / test_phase3_audit.py
   60| ```
   61| 
   62| 建议信息：`feat(v1.5-引擎): 拍点编译接线 ＋ 锚点摆位 ＋ 灯光矩阵 ＋ 道具交互 ＋ 构图声明消费（空声明零行为差）`
   63| 
   64| ### 组③ 规则通道与裁判（v1.5 P4-T1…T5 + P6-T1）
   65| 
   66| ```
   67| block_director/knowledge/rulepack.py                (新) 强度渲染/预算/冲突并陈/自由度声明
   68| block_director/knowledge/hypergraph.py              forbid 反查补挂 + trace 两键（第二十八次仪器显式重签）
   69| block_director/knowledge/retriever.py               三栏装配接 rulepack
   70| block_director/knowledge/client.py                  检索期审计
   71| block_director/layer5_orchestrator/scene_contract.py 构图/光线检索种子接线（P4-T5）
   72| block_director/layer3_engine/shot_auditor.py        ⚠️ 兼 P4-T4/P6-T1：破例辩护对拍 ＋ VLM 外回路（默认关）
   73| block_director/delivery/manifest.py                 shots.json 新字段（P4-T4/P15）
   74| block_director/contracts/audit.py                   shot_audit 字段
   75| block_director/contracts/messages.py                消息面同步
   76| block_director/motion/model.py                      ACTION_TYPES/ACTION_PARAMS 补语义动词（R-7 真源）
   77| tests/test_rulepack.py / test_forbid_guard_backfill.py / test_retrieval_seed_wiring.py
   78| tests/test_justification_audit.py                                              (新)
   79| tests/plan_v4_instruments.sha256.json               仪器重签留痕（第二十八次）
   80| ```
   81| 
   82| 建议信息：`feat(v1.5-规则): 规则包强度与预算 ＋ forbid 反查守门 ＋ 种子接线 ＋ 破例辩护对拍 ＋ VLM 外回路（默认关）`
   83| 
   84| ### 组④ 评估骨架（v1.5 P6-T2）
   85| 
   86| ```
   87| tools/diversity_score.py                            (新) 景别编辑距离 / 运镜卡方 / 机位符号翻转率
   88| tests/test_best_of_n.py                             (新)
   89| tests/test_vlm_review.py                            (新)
   90| tools/blender_tests/test_vlm_review.py              (新)
   91| ```
   92| 
   93| 建议信息：`feat(v1.5-评估): 多样性度量（纯函数）＋ Best-of-N 骨架（默认 1 = 现状，零行为差）`
   94| 
   95| ### 组⑤ 知识备料与文档一致性修复（v1.5 P1-T1…T3 + P5-T1/T3/T4）
   96| 
   97| ```
   98| AGENTS.md                                            状态块读数刷新（P1-T3；第三次改，见附录 B 串行表）
   99| docs/knowledge/OPEN_PROBLEMS.md                      "已被接管"抬头（P1-T1/E1）
  100| docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md        四处编者注（P1-T2/E3/E4）
  101| docs/knowledge/REGEN_LOG_TEMPLATE.md          (新)   换代登记模板（P5-T1/A6）
  102| docs/knowledge/JUDGE_ALIGNMENT_v1.md          (新)   评委口径对齐方案（P5-T4/A3）
  103| docs/knowledge/OPEN_ITEMS_20261007.md         (新)   本版输入材料：未完成项总表
  104| docs/evidence/20261007-054900-p5t1/           (新)   B5 零成员 kind 诊断
  105| docs/evidence/20261007-0610-p5t3t4/           (新)   P5-T3/T4 三份备料
  106| docs/evidence/20261007-v15-closeout/          (新)   本轮收尾 ＋ 两份裁决包
  107| ```
  108| 
  109| 建议信息：`docs(v1.5): 文档一致性修复（E1–E5）＋ 换代登记模板 ＋ 评委口径 ＋ 裁决备料`
  110| 
  111| ### 组⑥ 派发 hook 与工具修复（用户 2026-10-07 要求 ＋ C1 收口）
  112| 
  113| ```
  114| tools/hooks/                                        (新) 自动派发 hook（.ps1/.md/.json/selftest）
  115| tests/test_dispatch_graph.py                        (新) DAG 结构守卫
  116| tools/glm_consult.py                                 `--plain` 机械标注包（输出契约互斥）＋ bundle_manifest 位置参数修复
  117| tests/test_glm_consult.py                            同上，+80 行取证
  118| tools/knowledge/grounding_classify.py       (新)    90 槽位三分类驱动（C1）
  119| docs/evidence/20261007-grounding-probe/     (新)    `--plain` 对照实测
  120| docs/evidence/20261007-grounding-sample90/  (新+M)  90 槽位分层抽检产物（含 `_superseded/` 失败重跑）
  121| docs/evidence/20261007-wrong-card-correction/ (新)  错卡判据勘误
  122| tools/knowledge/quality.py                          K1 读法相关（如决定修，见组⑤ 的 B1 差异）
  123| tools/holdout_expect_movements.py                   标注工具同步
  124| tests/test_q5_plan_shaped_entries.py                构图种子进查询后的 join 口径
  125| tools/run_tests.ps1                                 探针清单 31 支（链规模 35/35 对拍）
  126| ```
  127| 
  128| 建议信息：`feat(tools): 自动派发 hook ＋ glm_consult --plain 修复 ＋ 出处缺口三分类在跑产物`
  129| 
  130| ### 组⑦ 输入材料（**用户放置，非本轮产物**）
  131| 
  132| ```
  133| 执行文档v1.5/          本执行包（PRD/TDD/TECH_SOLUTIONS/EXECUTION_PLAN/README/dispatch_graph）
  134| docs/research_src/     两份调研报告（v1.5 的输入）
  135| ```
  136| 
  137| 建议：单列一条 `docs(v1.5): 执行包与调研输入入库`，或**保持未跟踪**（由用户决定）。
  138| 
  139| ## §2 未跟踪的 `docs/evidence/` 目录（本轮各阶段门与在跑产物）
  140| 
  141| ```
  142| docs/evidence/.last_run_id / .last_p1t3_run     运行游标
  143| docs/evidence/_v15_dispatch/                    派发板状态（done/inflight marker）
  144| docs/evidence/20261007-045808-baseline/         已中断的并行车道半成品（**不是本版基线**）
  145| docs/evidence/20261007-050254-baseline/         P0-T1/P0-T2 基线
  146| docs/evidence/20261007-050633-g1/               G1
  147| docs/evidence/20261007-0510-baseline/           已中断（ABORTED.md）
  148| docs/evidence/20261007-051832-p1t3/             已中断（ABORTED.md）
  149| docs/evidence/20261007-054322-v15-lane/         车道记录（P1-T3/P2-T1/P3-T1/P4-T1…T3）
  150| docs/evidence/20261007-060813-v15-mainline/     契约层/规则层落地主记录
  151| docs/evidence/20261007-v15-contracts/           契约层与规则层落地证据（含 G2 读数）
  152| docs/evidence/20261007-g3/                      G3
  153| docs/evidence/20261007-p2t5-config/             P2-T5
  154| docs/evidence/20261007-p6t1-vlm-review/         P6-T1
  155| docs/evidence/20261007-p6t2-diversity/          P6-T2
  156| docs/evidence/20261007-g7-final/                P7-T1（全量链）——**本目录在收尾时仍在写入**
  157| docs/evidence/20261007-p7t1-final/              P7-T1（pytest 读数）
  158| ```
  159| 
  160| 建议：单独一条 `docs(evidence): v1.5 各阶段门与在跑产物入库`。
  161| 
  162| ## §3 需要用户先裁定的三件事（否则提交口径不闭合）
  163| 
  164| 1. **`执行文档v1.5/` 与 `docs/research_src/` 是否入库**（§1 组⑦）——
  165|    它们是你放置的**输入材料**，不是本轮产物。
  166| 2. **P5-T2 的前提差异怎么处置**（见同目录
  167|    `adjudication_p5t2_index_regen.md` §5 的选项 A/B/C）——
  168|    选 B 的话，提交里应含一条更正 `AGENTS.md:58` 与 B1 的**最小 diff**。
  169| 3. **C 流的 90 槽位三分类是否收口**——`docs/evidence/20261007-grounding-sample90/`
  170|    的 12 批作业若已跑完，结论要如实写；**未跑完就不要提交成"已完成"**。
  171| 
  172| ## §4 提交前检查（用户点头后执行）
  173| 
  174| ```
  175| python tools/gen_specs.py --check     # 组① 落盘后必须仍绿
  176| python tools/gen_golden.py --check    # 组① 落盘后必须仍绿
  177| python -m pytest -q                   # 全量
  178| powershell -File tools/run_tests.ps1  # 链（RK-13 按设计报红并 exit 1，见收尾 README）
  179| git log --oneline -8                  # 分组是否清晰
  180| git status --porcelain                # 工作树是否干净
  181| ```
```

## 源码：docs/knowledge/REGEN_LOG_20261007_rotation.md（第 1–182 行，逐字，带行号）

```
    1| # 换代登记 · 2026-10-07：卡↔槽位绑定清洗（用户裁决「换吧」）
    2| 
    3| **性质**：**已获用户明示批准的换代**（R-8 要求的显式登记）。
    4| **触发**：用户 2026-10-07 对两个 ⚖️ 项同时答复「**换吧**」：
    5| ① `P5-T2`（要不要换代）② `C2`（9 条边选「**换卡**」而不是删边）。
    6| **方法**：沿用 `build_hypergraph.py --replace-cards`（工具自带、且其 docstring 里
    7| 就有同形先例：v6 把概念名词写进动作槽位、横跨 329 张卡，用的就是这条清洗路径）。
    8| 
    9| ---
   10| 
   11| ## §1 换代原因（实测证据，不是拍脑袋）
   12| 
   13| 1. **C1 三分类（90 槽位分层样本，已完成）**：
   14|    `corrupt = 67/90 = 0.7444` → `corrupt-dominated`；四个分层**一致**（0.65–0.80）
   15|    ⇒ 按裁定口径（≥33% 且模式一致）「**暂缓重抽**」被证伪。
   16|    证据：`docs/evidence/20261007-grounding-sample90/三分类汇总.json`
   17| 2. **C2 机械判据（9 边 / 15 槽位）**：旧尺子 `topic_mismatch 14 / matches 1`，
   18|    新尺子 `topic_mismatch 6 / topic 或域与 kind 相符 2 / topic 未知 6 / 正文里真的有 1`。
   19|    每条都带 `candidate_cards`（正文里真的写了该取值的**候选卡**）。
   20|    证据：`docs/evidence/_v15_stage8/c2_edge_surgery/edges.json`
   21| 3. **C3**：`topic` 是**来源级**标签、对卡级判定零分辨率 ⇒ 判「挂错卡」必须回到**卡正文**
   22|    （机械预读的 88/90 不能当判决）。
   23| 
   24| ## §2 影响面（要动什么、不动什么）
   25| 
   26| | 项 | 内容 |
   27| |---|---|
   28| | **动** | `knowledge/hypergraph.{nodes,edges}.jsonl`（重建）、`hypergraph.manifest.json`、`work/hypergraph.atoms.jsonl`（原子边） |
   29| | **不动** | **判据／阈值／门限**（R-5）；**held-out 夹具**与第三方层（门⑦ 的输入，字节不动）；`hypergraph.py` 的槽位闭集 |
   30| | **目标卡集** | **277 张**（`work/_rotation_replace_cards.txt`）：C2 的 65 张错卡 ＋ 21 张候选卡 ∪ C1 的 194 张来源卡 |
   31| | **重抽量** | 覆盖 **180 / 708 chunk**（25%）——其余 528 chunk 走**原子边缓存**，逐字节不变 |
   32| | **抽取模型** | **`qwen3.8-max-0902`**（用户 2026-10-07 指示"派发给 qwen3.8max0902，让他完成所有任务"）；`reasoning_effort = max`（用户："新模型思考强度拉到最大"） |
   33| 
   34| ## §3 前后指纹（**前指纹＝实测**，后指纹待重建后填）
   35| 
   36| ```
   37| schema_fingerprint            1a90c089bb8f4f7fbd61a145a2088d6c2628ecbbd4dba47f63396fbf34fadaf3
   38| manifest_fingerprint(前)      c796a5a87018631db54da88406a4bd352741ed346fa1e9b06293c85ef46fed67
   39| hypergraph.nodes.jsonl   sha 789c0625ad6c6f65…    hypergraph.edges.jsonl  sha 0597326a9d300137…
   40| hypergraph.manifest.json sha d0613eb498f91371…    work/hypergraph.atoms.jsonl sha 5cd8cf67680a3ff9…
   41| corpus(fetched.jsonl)    sha 46401b5627df74e9…    vocab.json sha a295f3ef5a1e24a7…
   42| ```
   43| 
   44| **前指纹的完整备份**：`work/_pre_rotation_20261007-154410/`（6 份产物，可回滚/对拍）。
   45| > `work/` 是 `.gitignore` 掉的草稿区 ⇒ 备份**不进库**；索引本体在 `knowledge/`（进库）。
   46| 
   47| ## §4 最小重跑集（换代后必须重跑的）
   48| 
   49| | # | 门／读数 | 命令 |
   50| |---|---|---|
   51| | 1 | 门①–⑩（含门⑦ 两代口径） | `python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab fixtures/knowledge_holdout.vocab.json --cards fixtures/knowledge_holdout.cards.json …` |
   52| | 2 | Q1–Q7（held-out） | `python tools/holdout_score.py --holdout fixtures/knowledge_holdout.jsonl --json <out>` |
   53| | 3 | Q0 / E1–E3 | `python tools/knowledge/quality.py …` ＋ `python tools/knowledge/hard_gates.py …` |
   54| | 4 | 全链 | `powershell -File tools/run_tests.ps1`（含 pytest ＋ 31 支探针） |
   55| | 5 | **C1 复测（同口径）** | 重跑 90 槽位三分类，看 `corrupt_share` 是否下降（**判据不变**） |
   56| 
   57| ## §5 pin 处置（**不许 repin 洗白**）
   58| 
   59| * 已入库运行把 `pins.index`（索引指纹）钉进 `run_manifest.json`；
   60| * 换代后这些 pin **会失配** ⇒ 一律**如实标「异代」**，**不** `repin()`（它会拒）；
   61| * 实测：带 `holdout` pin 的运行 **22 份**（`docs/evidence/_v15_stage8/c5_superseded/superseded_audit.json`），
   62|   其中 21 份的**夹具** pin 仍是现行代字节（夹具未动），**只有索引那一格换代**；
   63| * 需要哪一份运行继续被引用，就**重跑那一份**（成本＝一次真实运行）。
   64| 
   65| ## §6 完成定义
   66| 
   67| □ 前指纹＋备份 □ 重抽（277 卡 / 180 chunk，qwen3.8-max-0902＋effort=max）
   68| □ 后指纹 □ 最小重跑集逐项落证 □ pin 标异代（不 repin）
   69| □ C1 同口径复测 □ 如实报告（**含任何回退**）
   70| 
   71| ---
   72| 
   73| ## §7 第二轮（`rebind/v2`）：把门⑥ 的 11 张孤儿卡修掉，顺手修掉一处"库里的索引不是构建器产物"
   74| 
   75| **触发**：`rebind/v1` 落地后门⑥ 判红——`edge_backed_without_entry = 11`
   76| （`rebind/v1` 把 11 张**本来零边**的卡追加进了 `sources[]`，它们于是成了"可断言卡"，
   77| 而 held-out 里没有它们的条目）。qwen3.8-max-0902 两角色会诊（`work/_qwen_orphan_fix/`）
   78| 一致裁定：根因是"重绑扩大了可断言面"，正解是**收窄候选池**（不改判据、不动冻结夹具）。
   79| 
   80| ### §7.1 改了什么（只有一处规则 ＋ 一处接线 ＋ 一处记账）
   81| 
   82| | 文件 | 改动 |
   83| |---|---|
   84| | `tools/kb_fetch/rebind.py` | `REBIND_VERSION = "rebind/v2"`；新增 `edge_backed_cards()`；`candidate_cards(..., pool=)` / `rebind_edges(..., candidate_pool=)`——候选只从"重绑输入边里已经出现过的卡"里取 |
   85| | `tools/kb_fetch/build_hypergraph.py` | `_apply_rebind()` 先算池再接线，并对拍**保范围不变量**（重绑后 `edge_backed` 只许多出来零张，否则当场 `AssertionError`）；`merge.rebind` 进 manifest（真源在 manifest 里，能审） |
   86| | `tests/test_rebind.py` | 新增 4 条：池的边界（池外一字不许进／空池 ≠ 不设限）、`edge_backed_cards()`、`v1` 对照（不设池必须复现旧行为）、池内照旧重绑 |
   87| | `tests/test_sidecar_retrieve.py` | sidecar 新增 opt-in `--reasoning-effort`（用户"思考强度拉到最大"）：不发时请求体一个字节不变，`openai` 才透传、`ollama` 不透传 |
   88| 
   89| **顺手修掉的既存缺陷（`v1` 的可推导性问题）**：`v1` 落库的那份索引是从**影子脚本**
   90| （`work/_shadow_rebuild.py`，候选次序＝`attestation.load_cards()` 的字典序）promote 回来的，
   91| 而构建器的 `_apply_rebind` 用的是 `build_hypergraph.load_cards()` 的次序——两处次序在个别边上
   92| 给出**不同的候选**（实测 `hg:1bb82beaeb5d` 等：影子挑 `axis_cross_cost`，构建器挑 `cine_establishing`）。
   93| 也就是说 `work/_verify_rebind_reproduces.py` 那句"能逐字节复现"只证明了**影子那一侧**自洽，
   94| 并没有证明"库里的索引 == 构建器产物"。`rebind/v2` 起索引一律**由构建器路径重建**
   95| （`python tools/kb_fetch/build_hypergraph.py --rematch`，不调模型），所以这条等式是**构造性**的。
   96| 
   97| ### §7.2 后指纹（v2）与实测账
   98| 
   99| ```
  100| manifest_fingerprint(v2)      e5213e1b64781c24103eecae15a4921b5766f75c4709672fa48997de692cdf89
  101| cache_key.rebind_version      rebind/v2
  102| hypergraph.edges.jsonl   sha ad88f44e478b4f2c…（551,641 B）   （v1 是 58a4e8b2…／553,672 B）
  103| manifest.merge.rebind         {"edges_touched": 560, "sources_added": 2867, "members_without_candidate": 210,
  104|                               "candidate_pool": 2262, "edge_backed_before": 2262, "edge_backed_after": 2262}
  105| ```
  106| 
  107| * **保范围**：`edge_backed` 2262 → 2262（`v1` 是 2262 → 2273）；
  108|   `v2` 与 HEAD 的"有边卡"集合**逐张相同**（新增 0、丢失 0）。
  109| * **门⑥** 回到 `edge_backed 2262 / excluded 91 / edge_backed_without_entry 0`；
  110|   `python tools/kb_fetch/card_scope_audit.py` 重新落 `knowledge/card_scope.json`。
  111| * **代价（如实记）**：1,063 个可重绑槽位里 **11 个**掉回"零候选"（全是
  112|   `composition_rule:lead_room`，唯一候选只有手写卡 `comp_lead_room`），
  113|   零候选总数 199 → **210**。90 条 C1 样本**一条都不在其中**（`work/_measure_restricted_rebind.py`）。
  114| * **可推导性**：`--rematch` 连跑两次 → `hypergraph.edges.jsonl` 逐字节相同。
  115| 
  116| ### §7.3 最小重跑集（第二轮）
  117| 
  118| | # | 读数 | 结果 |
  119| |---|---|---|
  120| | 1 | 门①–⑩ | **全 pass**（`overall: pass`，generation gen2） |
  121| | 2 | Q1–Q7 | Q1 **0.9975**、Q2 1.0、Q3 0.0、Q4 1.0、Q6a/Q6b/Q7 1.0 —— 与换代前同值 |
  122| | 3 | C1 同口径复测 | 90 槽位三分类（判官 `qwen3.8-max-0902`，`reasoning_effort=max`）见 §7.4 |
  123| | 4 | 全链 | 见 §7.5 |
  124| 
  125| ### §7.4 C1 同口径复测（`rebind/v2` 落库那一份）
  126| 
  127| 判官、模板、90 条样本、批大小全部与真实那一次逐字相同，只有来源卡换成**现行 v2 索引**
  128| 的 `sources`（90 条里有 **20 条**的来源卡与影子版不同）。产物：
  129| `docs/evidence/_v15_stage8/c1_recap/v2_judge/`，组题脚本 `work/_v2_rejudge_prep.py`。
  130| 
  131| （读数见该目录的 `三分类汇总.json` 与 `../shadow_comparison.md` 的对照栏。）
  132| 
  133| ### §7.5 pin 处置（第二轮，**仍不 repin**）
  134| 
  135| `v1` 让 22 份已入库运行的索引 pin 失配；`v2` 再换一次（`00ea933e…` → `e5213e1b…`）。
  136| 按 §5 的纪律：**一律如实标异代**，需要继续被引用的运行**重跑**。第二轮跑出来的新证据：
  137| 
  138| | 目录 | 用途 |
  139| |---|---|
  140| | `docs/evidence/20261007-v15-6shot-ds/` | 6 镜真实运行（sidecar→DeepSeek），同代、零原因零警告 |
  141| | `docs/evidence/20261007-v15-long/` | 61+ 镜长剧本真实运行（同上游），链上 Q5/E2 与长路径证据 |
  142| | `docs/evidence/20261007-v15-6shot-bailian/` | 6 镜真实运行（sidecar→**阿里云百炼** `qwen3.8-max-0902`），同代、零原因零警告 |
  143| 
  144| ---
  145| 
  146| ## §8 第三轮：零候选槽位的**裁决**（qwen3.8-max-0902 代替人工）＋ 一次**没有落地**的剪枝
  147| 
  148| **触发**：用户 2026-10-07 "用拍板的问题 2 的那个 qwen3.8max0902 解决，**代替人工裁决**"
  149| ——即把"老账"里那 199 个零候选槽位（含 `axis_side` 一族）的"删边/裁决"交给判官。
  150| 
  151| ### §8.1 裁决（已出，`reviewed_by: "third-party"`）
  152| 
  153| * 判官：`qwen3.8-max-0902`（**阿里云百炼**，DashScope OpenAI 兼容口），`reasoning_effort=max`，
  154|   **流式**；18 批、每批 ≤12 条，逐条判完 **199/199**（不是抽样）。
  155| * 判词：`keep` **177** / `wrong_card` **20** / `wrong_value` **2**；逐条理由在 `rows[].why`。
  156| * 记录：`docs/evidence/20261007-v15-zerocand-verdict/verdict.json`（＋每批 `裁决.json`
  157|   与 `.usage.json`）；组题/汇总脚本在 `work/_zerocand_*.py`。
  158| 
  159| ### §8.2 规则写好了，但**没有打开**：冻结的 oracle 挡着
  160| 
  161| `tools/kb_fetch/rebind.py` 新增 `PRUNE_VERSION = "prune/v1"` ＋ `prune_members()`
  162| （判成 `wrong_card`/`wrong_value` 的成员从它所属的边上摘掉；边被摘空就整条删），
  163| 并接进构建器——但记录里 **`apply: false`**（缺省也是 false），所以索引**没有动**。
  164| 
  165| 理由（逐条实测，`work/_prune_greedy.py`）：
  166| 
  167| ```
  168| 22 条判决**每一条**单独执行 ⇒ 门⑩ 判红（unresolved 2–67 条 spec）
  169| 基线（一条都不摘）        ⇒ 门⑩ pass
  170| ```
  171| 
  172| 根因：门⑩ 的 spec 是按**边的成员形状**匹配的，而每个成员都是某条 spec 期望的形状的一部分
  173| ——所以"摘掉一个无卡佐证的成员"就等于**改掉 oracle 断言**。要执行必须换 **oracle 一代**
  174| （夹具 sha256 进所有运行的 pin ⇒ 那些运行会一起失代，整条链与真跑都要重来）。
  175| 这是**换代决策**，按 R-8 要用户明示；记录里 `apply_blocked_by` 写清了这条。
  176| 
  177| ### §8.3 顺带落地的两件事
  178| 
  179| | 事项 | 内容 |
  180| |---|---|
  181| | **长剧本 token 上限** | 用户"你看着来"⇒ `budget.tokens_per_call_allowance=7000` ＋ `max_tokens_ceiling=4000000`：账本上限＝`max(静态下限, min(静态帽, 本场调用额度 × 每次调用额度))`。小场景仍是 2 M（一个字节不变），64 镜 2 M → **3.864 M**（实测两次真跑 6,150 / 6,311 token/调用） |
  182| | **百炼通道** | 见 `docs/evidence/20261007-v15-bailian/`：根因是**思考模式拒收 `tool_choice=required`**（`InternalError.Algo.InvalidParameter`），sidecar 把非 2xx 一律翻 502 ⇒ 0.7 s 失败；修法是 sidecar 新增 `--tool-choice-mode`（默认 `passthrough`）。另实测：百炼上**非流式大包会挂住**（26 分钟不返回）、**流式 1 s 回首 chunk**，所以 `glm_consult` 加了 `GLM_STREAM=1` 的 opt-in 流式通道 |
```

## 源码：block_director/contracts/config.py（第 155–190 行，逐字，带行号）

```
  155| @dataclass
  156| class BudgetConfig:
  157|     #: 每个镜头允许多少次 LLM 调用。v1.3 多了阶段 S 与运镜/知识检索，
  158|     #: 额度从 v1.2 的 ``shots * 6`` 提到 ``shots * 8 + 40``（§6.1 / v1.4 §2.4）。
  159|     max_llm_calls_per_scene_formula: str = "shots * 8 + 40"
  160|     #: v1.4 §2.4：单场静态额度**下限保障**（不是上限）。真正的硬顶只由
  161|     #: CLI ``--max-llm-calls`` 提供（``0`` = 不限）。
  162|     max_llm_calls_ceiling: int = 200
  163|     max_cost_usd: float = 5.0
  164|     max_wall_minutes: float = 120.0
  165|     #: **每次调用允许多少 token**（2026-10-07 用户"你看着来"授权后加）：账本的
  166|     #: token 上限＝``本场调用额度 × 这一格``，再与 ``max_tokens_ceiling``、以及
  167|     #: ``BudgetLimits.max_tokens`` 的静态下限取**大**。
  168|     #:
  169|     #: 为什么必须让它随场景走（实测）：`BudgetLimits.max_tokens` 是**写死的 2 M**，
  170|     #: 而调用额度是"shots * 8 + 40"——两个上限互相矛盾：v15 管线下 64 镜真跑两次
  171|     #: 都**在只用了 59% 调用额度时**就吃满 2 M（`prompt 1,886,634 + completion 118,326`，
  172|     #: 见 `docs/evidence/20261007-v15-long/` 与 `…-long-topped-out/`），
  173|     #: 于是"没用完的调用额度"结构上不可达，长剧本验收恒红。
  174|     #: 7,000 来自实测：那两次真跑 **6,150 / 6,311 token/调用**，向上取整到千。
  175|     #: 这一格只影响**资源上限**，不改任何判据/门限。
  176|     tokens_per_call_allowance: int = 7000
  177|     #: token 上限的**静态帽**（0 = 不设帽）：再长的戏也不让它无限增长。
  178|     #: 60 镜（520 次调用 × 7,000 = 3.64 M）不触帽；100 镜以上按 4 M 封顶。
  179|     max_tokens_ceiling: int = 4_000_000
  180| 
  181| 
  182| @dataclass
  183| class BriefConfig:
  184|     """阶段 S（剧本理解，§3.2）。"""
  185| 
  186|     #: 是否先做一次结构化理解。关掉就退回 v1.2 的"直接规划"路径。
  187|     enabled: bool = True
  188|     #: SceneBrief 注入规划提示的 token 上限。没有上限的超长理解会把整次
  189|     #: 调用顶出模型上下文窗口（system 永远不进 trim 的裁剪范围）。
  190|     max_tokens: int = 1200
```
```
