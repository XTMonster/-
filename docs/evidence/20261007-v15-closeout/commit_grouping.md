# 裁决备料 · P7-T2（文档同步与提交）——**分组清单，未执行任何 git 提交**

**run-id**：20261007-v15-closeout
**HEAD**：`f6530c6e44702028c6e42a9e1d11436c0b19d1c2`（工作树未提交，78 组条目）
**纪律**：卡 P7-T2 写明「提交前向用户展示分组清单，**确认后**执行」；
本文件就是那份清单。**一个 commit 都还没做**。

---

## §1 分组（每组文件**互不重叠**，可直接 `git add` 逐组提交）

> 说明：少数文件同时承载**两张卡**的改动（git 只能把整个文件放进一条 commit），
> 这些文件在表里加了 ⚠️ 并注明第二张卡；提交信息必须两句都写。

### 组① 契约层（v1.5 P2-T1…T5）

```
block_director/contracts/beats.py            (新) ShotBeat/LightSpec/CompositionSpec/RuleJustification + validate_beats
block_director/contracts/plan.py                   ShotPlan.beats/composition/rule_justifications + Plan.environment
block_director/contracts/sdl.py                     SDL 1.5：SDLAnchor + environment.anchors/light + shot 三字段
block_director/layer2_sdl/sdl_builder.py            SDL 1.5 导出
block_director/layer2_sdl/sdl_migrate.py            KNOWN_VERSIONS += "1.5"；1.4→1.5 纯缺省填充
block_director/contracts/config.py                  rag.rule_top_k(5,3–8) + vlm_review{enabled,max_shots}
specs/config.default.yaml                           （由 tools/gen_specs.py 生成，勿手改）
specs/openapi.yaml                                  sidecar DTO 同步
fixtures/expected_sdl_simple.json                   ┐
fixtures/expected_sdl_long.json                     │ R-11：只经 tools/gen_golden.py 重生成
fixtures/expected_shots_long.json                   │ （漂移只有 version 1.4→1.5 与新增可选字段）
fixtures/tool_transcript_simple.jsonl               ┘
tests/test_beats.py                                 (新)
tests/test_plan_v15_fields.py                       (新)
tests/test_sdl_15.py / tests/test_sdl_v15.py        (新)
tests/test_config_vlm_review.py                     (新)
block_director/contracts/vlm_review.py              (新) VLM 评审 DTO（P6-T1 的契约面）
```

建议信息：`feat(v1.5-契约): 拍点/锚点/灯光/构图/破例辩护五类契约 ＋ Plan.environment ＋ SDL 1.5 迁移 ＋ 配置三键`

### 组② 求解器与引擎（v1.5 P3-T1…T4，含 P2-T4 的工具 schema）

```
block_director/layer5_orchestrator/beat_compiler.py (新) 拍点表 → actions 的确定性编译与合并
block_director/layer5_orchestrator/planner.py       ⚠️ 兼 P2-T4：emit_plan 增 optional environment
block_director/layer5_orchestrator/editor.py        ⚠️ 兼 P2-T4/P4-T4/P6-T2：逐镜 schema/提示词/候选骨架
block_director/layer5_orchestrator/driver.py        ⚠️ 兼 P2-T4：草案合并回 ShotPlan
block_director/layer5_orchestrator/headless_runner.py  ⚠️ 兼 P4-T1/T2：三栏渲染接 rulepack
block_director/layer5_orchestrator/modal_operator.py   SDL 1.5 落盘
block_director/cinema/staging.py                    (新) solve_anchor_positions
block_director/cinema/lighting.py                   (新) resolve_lighting_preset 矩阵
block_director/cinema/props.py                      (新) 道具交互动词 → 跟随关键帧
block_director/cinema/station.py                    aim_offset_for_composition（构图声明消费）
block_director/cinema/anchor.py                     派生链（冻结几何 1.70 / ADR-0007 不动）
block_director/layer3_engine/scene_executor.py      ⚠️ 兼 P3-T2/T3：锚点落位 + 灯光矩阵 + 道具事件
block_director/layer3_engine/shot_builder.py        拍点编译接线 + 构图偏置
block_director/layer7_ui/panel_shots.py             镜头面板带新字段
tools/run_headless.py                               导出链路带新字段
tests/test_beat_compiler.py / test_staging_anchors.py / test_lighting_matrix.py
tests/test_prop_interaction.py / test_composition_consumption.py        (新)
tools/blender_tests/test_anchor_staging.py / test_prop_interaction.py / test_phase3_audit.py
```

建议信息：`feat(v1.5-引擎): 拍点编译接线 ＋ 锚点摆位 ＋ 灯光矩阵 ＋ 道具交互 ＋ 构图声明消费（空声明零行为差）`

### 组③ 规则通道与裁判（v1.5 P4-T1…T5 + P6-T1）

```
block_director/knowledge/rulepack.py                (新) 强度渲染/预算/冲突并陈/自由度声明
block_director/knowledge/hypergraph.py              forbid 反查补挂 + trace 两键（第二十八次仪器显式重签）
block_director/knowledge/retriever.py               三栏装配接 rulepack
block_director/knowledge/client.py                  检索期审计
block_director/layer5_orchestrator/scene_contract.py 构图/光线检索种子接线（P4-T5）
block_director/layer3_engine/shot_auditor.py        ⚠️ 兼 P4-T4/P6-T1：破例辩护对拍 ＋ VLM 外回路（默认关）
block_director/delivery/manifest.py                 shots.json 新字段（P4-T4/P15）
block_director/contracts/audit.py                   shot_audit 字段
block_director/contracts/messages.py                消息面同步
block_director/motion/model.py                      ACTION_TYPES/ACTION_PARAMS 补语义动词（R-7 真源）
tests/test_rulepack.py / test_forbid_guard_backfill.py / test_retrieval_seed_wiring.py
tests/test_justification_audit.py                                              (新)
tests/plan_v4_instruments.sha256.json               仪器重签留痕（第二十八次）
```

建议信息：`feat(v1.5-规则): 规则包强度与预算 ＋ forbid 反查守门 ＋ 种子接线 ＋ 破例辩护对拍 ＋ VLM 外回路（默认关）`

### 组④ 评估骨架（v1.5 P6-T2）

```
tools/diversity_score.py                            (新) 景别编辑距离 / 运镜卡方 / 机位符号翻转率
tests/test_best_of_n.py                             (新)
tests/test_vlm_review.py                            (新)
tools/blender_tests/test_vlm_review.py              (新)
```

建议信息：`feat(v1.5-评估): 多样性度量（纯函数）＋ Best-of-N 骨架（默认 1 = 现状，零行为差）`

### 组⑤ 知识备料与文档一致性修复（v1.5 P1-T1…T3 + P5-T1/T3/T4）

```
AGENTS.md                                            状态块读数刷新（P1-T3；第三次改，见附录 B 串行表）
docs/knowledge/OPEN_PROBLEMS.md                      "已被接管"抬头（P1-T1/E1）
docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md        四处编者注（P1-T2/E3/E4）
docs/knowledge/REGEN_LOG_TEMPLATE.md          (新)   换代登记模板（P5-T1/A6）
docs/knowledge/JUDGE_ALIGNMENT_v1.md          (新)   评委口径对齐方案（P5-T4/A3）
docs/knowledge/OPEN_ITEMS_20261007.md         (新)   本版输入材料：未完成项总表
docs/evidence/20261007-054900-p5t1/           (新)   B5 零成员 kind 诊断
docs/evidence/20261007-0610-p5t3t4/           (新)   P5-T3/T4 三份备料
docs/evidence/20261007-v15-closeout/          (新)   本轮收尾 ＋ 两份裁决包
```

建议信息：`docs(v1.5): 文档一致性修复（E1–E5）＋ 换代登记模板 ＋ 评委口径 ＋ 裁决备料`

### 组⑥ 派发 hook 与工具修复（用户 2026-10-07 要求 ＋ C1 收口）

```
tools/hooks/                                        (新) 自动派发 hook（.ps1/.md/.json/selftest）
tests/test_dispatch_graph.py                        (新) DAG 结构守卫
tools/glm_consult.py                                 `--plain` 机械标注包（输出契约互斥）＋ bundle_manifest 位置参数修复
tests/test_glm_consult.py                            同上，+80 行取证
tools/knowledge/grounding_classify.py       (新)    90 槽位三分类驱动（C1）
docs/evidence/20261007-grounding-probe/     (新)    `--plain` 对照实测
docs/evidence/20261007-grounding-sample90/  (新+M)  90 槽位分层抽检产物（含 `_superseded/` 失败重跑）
docs/evidence/20261007-wrong-card-correction/ (新)  错卡判据勘误
tools/knowledge/quality.py                          K1 读法相关（如决定修，见组⑤ 的 B1 差异）
tools/holdout_expect_movements.py                   标注工具同步
tests/test_q5_plan_shaped_entries.py                构图种子进查询后的 join 口径
tools/run_tests.ps1                                 探针清单 31 支（链规模 35/35 对拍）
```

建议信息：`feat(tools): 自动派发 hook ＋ glm_consult --plain 修复 ＋ 出处缺口三分类在跑产物`

### 组⑦ 输入材料（**用户放置，非本轮产物**）

```
执行文档v1.5/          本执行包（PRD/TDD/TECH_SOLUTIONS/EXECUTION_PLAN/README/dispatch_graph）
docs/research_src/     两份调研报告（v1.5 的输入）
```

建议：单列一条 `docs(v1.5): 执行包与调研输入入库`，或**保持未跟踪**（由用户决定）。

## §2 未跟踪的 `docs/evidence/` 目录（本轮各阶段门与在跑产物）

```
docs/evidence/.last_run_id / .last_p1t3_run     运行游标
docs/evidence/_v15_dispatch/                    派发板状态（done/inflight marker）
docs/evidence/20261007-045808-baseline/         已中断的并行车道半成品（**不是本版基线**）
docs/evidence/20261007-050254-baseline/         P0-T1/P0-T2 基线
docs/evidence/20261007-050633-g1/               G1
docs/evidence/20261007-0510-baseline/           已中断（ABORTED.md）
docs/evidence/20261007-051832-p1t3/             已中断（ABORTED.md）
docs/evidence/20261007-054322-v15-lane/         车道记录（P1-T3/P2-T1/P3-T1/P4-T1…T3）
docs/evidence/20261007-060813-v15-mainline/     契约层/规则层落地主记录
docs/evidence/20261007-v15-contracts/           契约层与规则层落地证据（含 G2 读数）
docs/evidence/20261007-g3/                      G3
docs/evidence/20261007-p2t5-config/             P2-T5
docs/evidence/20261007-p6t1-vlm-review/         P6-T1
docs/evidence/20261007-p6t2-diversity/          P6-T2
docs/evidence/20261007-g7-final/                P7-T1（全量链）——**本目录在收尾时仍在写入**
docs/evidence/20261007-p7t1-final/              P7-T1（pytest 读数）
```

建议：单独一条 `docs(evidence): v1.5 各阶段门与在跑产物入库`。

## §3 需要用户先裁定的三件事（否则提交口径不闭合）

1. **`执行文档v1.5/` 与 `docs/research_src/` 是否入库**（§1 组⑦）——
   它们是你放置的**输入材料**，不是本轮产物。
2. **P5-T2 的前提差异怎么处置**（见同目录
   `adjudication_p5t2_index_regen.md` §5 的选项 A/B/C）——
   选 B 的话，提交里应含一条更正 `AGENTS.md:58` 与 B1 的**最小 diff**。
3. **C 流的 90 槽位三分类是否收口**——`docs/evidence/20261007-grounding-sample90/`
   的 12 批作业若已跑完，结论要如实写；**未跑完就不要提交成"已完成"**。

## §4 提交前检查（用户点头后执行）

```
python tools/gen_specs.py --check     # 组① 落盘后必须仍绿
python tools/gen_golden.py --check    # 组① 落盘后必须仍绿
python -m pytest -q                   # 全量
powershell -File tools/run_tests.ps1  # 链（RK-13 按设计报红并 exit 1，见收尾 README）
git log --oneline -8                  # 分组是否清晰
git status --porcelain                # 工作树是否干净
```
