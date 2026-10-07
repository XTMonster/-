# 执行文档 v1.5 —— **最终证据索引**（P7-T1 交付物）

**run-id**：20261007-v15-final
**权威链读数**：`docs/evidence/20261007-083902/`（`tree.json.stable = True`，单树可引用）
**口径**：判据／阈值／门限**一个字未动**（红线 R-5）；本索引只汇总**实测**读数，
推断一律标注。

---

## 1. 一句话结论

**27 张任务卡已完成 25 张**；另**补齐计划漏掉的 9 张**（阶段 8）**完成 8 张 + 1 张如实记阻塞**。
链上**只剩 `RK-13`（E1 ≥ 0.70）这一条按设计报红、已结案的红线**；
其余每道门都有**单树权威读数**。**未完成的**全部是计划自己标"须用户裁决"的两项
（`P5-T2` 索引换代、`P7-T2` 提交口径）与一项外部阻塞（`C1` 余下 10 批，缺 `GLM_API_KEY`）。

## 2. 阶段门逐门读数（G0–G7）

| 门 | 判据 | 实测 | 证据 | 复算命令 |
|---|---|---|---|---|
| **G0** 基线 | 五组读数落盘 | pytest 2492 passed/1 skipped；C 盘 26.8 GB；golden/specs 绿 | `20261007-050254-baseline/` | `python -m pytest` |
| **G1** 文档一致性 | 全量测试无新增失败 | 无失败（doc-only 改动） | `20261007-050633-g1/`、`AGENTS.md`、`OPEN_PROBLEMS.md` | `python -m pytest` |
| **G2** 契约层 | pytest 绿 ＋ SDL 1.4 兼容 ＋ golden/ specs `--check` | 全绿；1.4 迁移零新增 finding | `20261007-v15-contracts/` | `python -m pytest`；`python tools/gen_golden.py --check`；`python tools/gen_specs.py --check` |
| **G3** 引擎 | 三份冻结工程同代重建，逐镜读数不回退 | `(shot_id,passed,score,errors)` **identical_rows = True**（long9/long11/long12） | `20261007-g3/README.md` | 见该 README 的 worktree 对照命令 |
| **G4** 规则通道 | `forbid_members_seen > 0` ＋ Q1/Q2 同口径不回退 | 重放 **103** 条真实检索查询：`forbid_members_seen = 217`、`top1_preserved = 103/103`、`top1_is_backfilled = 0` | `20261007-g4-forbid-guard/` | `python docs/evidence/20261007-g4-forbid-guard/g4_forbid_guard.py` |
| **G5** 知识库裁决备料 | 备料件齐 ＋ 换代登记合规 | 阶段 8 的 9 张卡：8 完成 1 阻塞；换代登记模板 ＋ 多处裁决包齐 | `_v15_stage8/`、`docs/knowledge/REGEN_LOG_TEMPLATE.md` | `ls docs/evidence/_v15_stage8/*/` |
| **G6** 评审与评估 | 默认关配置下全链路不回归 | `vlm_review.enabled=false` 零行为差（单测）；多样性工具出读数 | `20261007-p6t1-vlm-review/`、`20261007-p6t2-diversity/` | `python -m pytest tests/test_vlm_review.py tests/test_best_of_n.py` |
| **G7** 收尾 | 全绿 ＋ 证据齐 ＋ 文档同步 | 见 §3（`tree.stable=True`） | `20261007-083902/` | `powershell -File tools/run_tests.ps1` |

## 3. G7 权威读数（单树）

```
powershell -File tools/run_tests.ps1        ->  docs/evidence/20261007-083902/
  tree.json       : head f6530c6e44702028c6e42a9e1d11436c0b19d1c2   stable True
  holdout_gates   : overall pass        generation gen2      （门①–⑩ 全 pass）
  holdout_quality : passed true
      Q1 0.9975 (线 0.70) | Q2 1.0 | Q3 0.0 (max 型) | Q4 1.0 | Q6a 1.0 | Q6b 1.0 | Q7 1.0
  rks.json        : 203 checks   failed = ["RK-13"]          （唯一红＝已结案的 E1 红线）
  探针            : 31 支全部 "OK:"，0 支 FAILED
  链内 pytest     : 2781 passed, 1 skipped    且**无 warnings summary**
```

另有独立跑的 `python -m pytest`（同树）：**2781 passed / 1 skipped**；
`hooks/selftest.ps1` **133/0**；`hooks/dispatch-board.selftest.ps1` **25/0**。

## 4. 差异对照（v1.5 开始前 → 现在）

| 量 | 开始前 | 现在 | 判读 |
|---|---|---|---|
| pytest | 2492 passed / 1 skipped | **2781 passed / 1 skipped** | +289 条（新契约/引擎/规则/评审用例） |
| 探针链 | 28 支（32 步） | **31 支（35 步）** | 新增 anchor-staging／prop-interaction／vlm-review |
| SDL | 1.4 | **1.5**（1.4 无损加载） | 迁移 = 纯缺省填充 |
| Q1 | 0.9975 | **0.9975** | **一度掉到 0.1208，已定位并修复**（见 §5） |
| `forbid_members_seen` | 无此读数 | **217**（103 条真实查询重放） | FR-9/B7 守门能力：从"没有读数"到"实测 >0" |
| 构图门/R 系列（三工程） | 基线 | **逐镜四元组 identical** | 零回退 |

## 5. 本版独立查出并修掉的**真回归**（最重要的一条）

首轮链报 `Q1 fail 0.1208`（基线 **0.9975**）。根因：P4-T3 的 forbid 补挂第一版把补挂边
**插到检索列表最前**，40 条抽样里 **30 条**的 top-1 被顶掉。
TDD §5.6 的原话是"**渲染**排最前"（注入文本顺序），不是改写检索名次。
修法：`retrieve()` 只**追加**补挂边（名次不动、读数照旧），"排最前"交给
`rulepack.render_rule_pack(exempt_edge_ids=…)`。修后 Q1 回到 **0.9975**（见 §3）。
守门：`tests/test_forbid_guard_backfill.py` 7 条（含"不得顶掉检索名次""必须排在注入文本最前"）。

## 6. 遗留问题清单（全部如实挂出，不含推断）

### 6.1 等用户裁决（计划自己标的 ⚖️）

| 项 | 状态 | 材料 |
|---|---|---|
| **P5-T2** 132 张手写卡入索引（换代） | 前提**已被证伪**（抽取器早已纳入；索引引用 2262/2353；真缺口是 **16 张手写卡零边**） | `20261007-v15-closeout/adjudication_p5t2_index_regen.md` |
| **P7-T2** 分组提交 | 分组清单已备好，**一个 commit 都没做** | `20261007-v15-closeout/commit_grouping.md` |
| **C2** 9 边/15 槽位"换卡 vs 删边" | 备料齐（含 A6 预填登记表）；删边＝换代 | `_v15_stage8/c2_edge_surgery/` |
| **C6** 16 条 `amended` 的 `fix` | 实测**是换代**（层为被 pin 的 gate 输入）；备料齐 | `_v15_stage8/c6_layer_fix/` |
| **C5** 19 份 superseded | 机械解析：**22 份 pin / 21 现行 / 1 退休(gen0)**；语义那一半裁定说"不能定案" | `_v15_stage8/c5_superseded/` |
| **A4** 深度-12 真判 | 成本已锚：**14,080 三元组 ≈ 403 h 串行**；建议先跑 20 条试点 | `_v15_stage8/a4_depth12/` |
| **B3** 33 条"判不了" | 实测 **8 条不同边 / 32 次出现 / 13 槽位**；提案覆盖 8/8、可直接落地 0/8 | `_v15_stage8/b3_coverage/` |
| **灯光种子闭集** | `VALUE_DOMAINS` 无 `lighting` 键 ⇒ `光线=` 发不出种子（编别名表＝新判据） | `20261007-v15-contracts/adjudication_lighting_seed.md` |

### 6.2 外部阻塞

| 项 | 阻塞 | 一旦解除怎么做 |
|---|---|---|
| **C1** 90 槽位三分类 | 12 批只跑完 2 批（10/90 槽位）；**`GLM_API_KEY` 缺失** | 按 `_v15_stage8/c1_recap/README.md` §4 逐批跑，再按分水岭汇总 |

### 6.3 两处口径更正（以实测为准）

1. **"23 份运行 pin" 实测是 22**（`_v15_stage8/c5_superseded/superseded_audit.json`）；
2. **C6 的"19 份 superseded"是上一版处置方案的口径**——裁定采用增量层机制后，
   夹具维度上不存在这一档（`_v15_stage8/README.md` §5）。

### 6.4 环境约束（README 的环境段落已过期，以实测为准）

C 盘可用实测 **≈26.8 GB**（README 写 2.7 GB）；`GLM_API_KEY` 未设置；
G4 的测量用**同代重放**替代真跑（已在 `20261007-g4-forbid-guard/README.md` §4 写明边界）。

## 7. 交付物地图

| 层 | 主要落点 |
|---|---|
| 契约 | `contracts/beats.py`、`plan.py`、`sdl.py`(1.5)、`config.py`、`layer2_sdl/sdl_migrate.py` |
| 求解/引擎 | `layer5_orchestrator/beat_compiler.py`、`planner.py`、`editor.py`、`driver.py`、`cinema/{staging,lighting,props,station}.py`、`layer3_engine/{scene_executor,shot_builder,shot_auditor}.py` |
| 规则通道 | `knowledge/rulepack.py`、`hypergraph.py`(补挂)、`retriever.py`、`client.py` |
| 交付/证据 | `delivery/manifest.py`、`layer8_delivery/*`、`docs/evidence/**` |
| 派发工具 | `tools/hooks/*`（派发板 ＋ 禁孙子守卫 ＋ 自检）、`执行文档v1.5/dispatch_graph.json` |

## 8. PRD §6 验收指标（DoD）逐行核对

| 层 | 指标 | 目标 | 实测 | 证据 / 复算 |
|---|---|---|---|---|
| 合规 | `emit_shot_draft` schema 解析失败率 | ≈0 | **最近 3 次真实运行：219 草案 / 1 无效 = 0.45%**（`long21` 1/74；`real-axis` 0/71；`real-closure` 0/75）。早期运行高到 96%（`20261003_chunked_long` 62/64），说明这条是靠 schema 修复一路压下来的 | `python -c "…统计各 run 的 draft_received / draft_invalid…"`（逐 run 表见下） |
| 合规 | R 系列违规率 | 不高于基线 | **逐镜四元组 identical**（三份冻结工程） | `20261007-g3/README.md` |
| 合规 | `forbid_members_seen` | 真实运行 > 0 | **217**（103 条真实查询同代重放） | `20261007-g4-forbid-guard/` |
| 质量 | 构图门通过率（≥70%） | 不降低 | **identical**（long9 39/79.6、long11 24/64.3、long12 34/72.4 前后一致） | `20261007-g3/README.md` |
| 泛化 | 同剧本 3 次生成差异度 | 可测量且 > 0 | 工具 ＋ 三份冻结工程读数落盘 | `20261007-p6t2-diversity/` |
| 工程 | `python -m pytest` | 全绿 | **2781 passed / 1 skipped** | `20261007-083902/` ＋ 独立跑 |
| 工程 | `tools/run_tests.ps1` | 探针全过 | **31/31**（链 203 项 RK 里仅 `RK-13` 红，属已结案） | `20261007-083902/rks.json` |
| 工程 | golden 链路 | `--check` 通过 | 绿（夹具随 SDL 1.5 重生成，漂移只有版本号＋新增可选字段） | `python tools/gen_golden.py --check` |
| 兼容 | SDL 1.4 工程 | 无损加载、零新增 finding | 绿 | `tests/test_sdl_15.py` |

**逐 run 的解析失败率（实测，用于上面第一行）**：

```
20261002_real        246/250  ok   0.016      20261004_chunked_long1{1,2,4,5,6,7}  0/0  invalid
20261003_chunked_long  2/ 64  ok   0.969      20261004_chunked_long18..20           0 invalid
20261003_intent        0/  6  ok   1.000      20261006-long21                     1/ 74
20261003_real          2/  6  ok   0.667      20261007-real-axis                  0/ 71
20261003_real_long     3/ 64  ok   0.953      20261007-real-closure               0/ 75
20261003_chunked_long9 66/ 66 ok   0.000      （最近 3 次合计：219 ok / 1 invalid = 0.45%）
```

> **未验证（如实）**：v1.5 升级了 `emit_shot_draft` 的 schema（新增 `beats`/`composition`/
> `rule_justifications`），**升级后还没有新的 LLM 真跑**，所以"新 schema 的解析失败率"
> 仍是**空白**；上表是**改动前**的真实运行读数。要闭合这一格，需要一次真实模型运行。
