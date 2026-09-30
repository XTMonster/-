# 隔壁审查 25 条 —— 逐条裁决（2026-10-01，主 agent）

规则：每条给**判据**（命令/文件:行号/数字）与**处分**（已修 / 该修待做 / 不成立 / 需用户裁决）。
不以"审查方写了什么"为准，一律回当前工作区实测。

## A. 卡住验收的（8 条）

| # | 结论 | 判据与处分 |
|---|---|---|
| 1 | **成立，已修** `91ded6d` | `fixtures/knowledge_holdout.cards.json` 2067 vs 运行时 `CARDS` 2113。新增 `tools/holdout_merge.py --cards-only`，按唯一真源重写 → 2113。复测：池通道门⑥ `missing 317 / ghost 0`；旧 oracle `1380 / 341`（ghost 全在旧 oracle 侧）。 |
| 2 | **成立，已修** | 门③ 三个"零使用取值"＋三个词表外取值，是**旧词表（频次前 12）**的产物。已换成"支撑 ≥3 对"的不动点口径（`tools/knowledge/holdout_vocab.py`，`c2f0b15`）。池通道门③ 现为 **pass**（missing/unknown/thin 全空）。 |
| 3 | **成立，已修** | 门⑨ 2271/4239 不可达的根因是"旧 oracle × 新索引"。池通道 **short_ratio = 0.0**（门⑨ 由构造保证，`24eb572` + 测试 `tests/test_holdout_pool.py::test_every_generated_entry_is_reachable`）。 |
| 4 | **成立，已修** | 门⑩ exact 口径下池通道 `unresolved_ratio = 0.0`（`must` 2220 / `top1` 1457 / `never` 1457 全部解析）。 |
| 5 | **成立，只能人做** | 门⑦ 0/120。双模型复核**不得**冒充人审（协议 §5.5/§5.6 写明）。→ 需用户裁决 #13。 |
| 6 | **成立，是 #5 的后果** | `docs/evidence/20261001-061859/rks.json` RK-13 = measured + false，正是 §4.1b"缺证据不得判通过"的设计。门⑦ 不做完，它就该是 false。**不需要"修"**。 |
| 7 | **部分过期** | 报的 Q1/Q2/Q4/Q6b 是**旧 oracle 文件**上的数。池通道实测 Q1 **0.915**／Q2 **0.978**／Q3 **0.0**／Q6a **1.0**／Q7 **1.0** 全过线；**Q4 0.9377／Q6b 0.9688 仍差**——已定量到两个根因：①目标边与竞争边分差只有 0.002–0.01（部分匹配但更常见的边压过完全匹配的边）；②`render_edges` 的 2000 token 预算丢边。→ 归 retriever 排序工作。 |
| 8 | **成立** | `fixtures/knowledge_holdout.jsonl` 目前仍是**旧自由标注 oracle**；`work/glm_pool/mechanical.jsonl` 是机械通道产物，真正的 GLM 池标注（`work/glm_pool/glm_full.log`）仍在跑。**没有把机械产物提升为正式 oracle**——那要等 #9 的裁决。 |

## B. 只能用户拍板的（5 条）

| # | 结论 | 说明 |
|---|---|---|
| 9 | **成立，需裁决** | 候选池标注收窄了协议 §5.2，并把"抽取召回"移出机器门。裁决与边界清单在 `docs/knowledge/ORACLE_DECISION_v15.md`。**未经追认不提升为正式 oracle。** |
| 10 | **成立，需裁决** | `SEQUENCE_FLOOR` 在 `tools/kb_fetch/build_cases.py` / `tests/test_cases_corpus.py` / `AGENTS.md`。外部语料派生不出 7 条序列类案例 → 三条路（留自撰／记 0 并改自设门／放宽）后两条都是改验收标准。 |
| 11 | **成立，需裁决** | 门⑩ 期望关系（exact/subset/card_edge）与 `forbid` 宿主范围。**注意**：本轮的池通道已在 `exact` 口径下把门⑩ 打到 0 未解析，所以"改口径"这条**不再是把门调绿的必要手段**——它现在只剩"要不要测别的语义"这个问题。 |
| 12 | **成立，需裁决** | `AXIS_RULE` 13 条边 vs oracle 需求。实测它现在**已经过了门④**（≥30 对），所以这条是"要不要为检索质量再加可区分槽位"，不是验收阻塞。 |
| 13 | **成立，需用户或人做** | 人审 ≥120 条 + Q5/Q7/E3 最终裁定。Q5/E1 目前 `not_measured`。 |

## C. 数据与契约（8 条）

| # | 结论 | 判据与处分 |
|---|---|---|
| 14 | **部分成立，**不是缺陷** | "词表比 schema 窄"里，`axis_side`／`avg_shot_len`／`headroom_policy`／`pair`／`applies_to_*` 这几类**没有查询键**，按设计就不能进 `q` —— 它们缺席是**正确**的。真正窄的是 `transition=whip`、`scene_type=dialogue/reaction`、`genre=documentary`、`intent` 7 个值，它们被"支撑 ≥3 对"的规则挡住，**这是刻意的**（凑不出 3 对就无法满足门③）。→ 不改口径；把这条判据写进 `ORACLE_DECISION_v15.md` §八。 |
| 15 | **不成立（举例全部证伪）** | 实测：`固定` 只有一个节点 `movement:固定`（name `固定机位`），没有 `static` 孪生；`手持` → 单个 `movement:handheld`；`低机位` → 单个 `camera_angle:低机位`；`过肩` 的确有两个节点，但那是 `applies_to_shot_size:OTS`（节点类型）与 `camera_angle:过肩`，**不同 kind 不算别名分裂**。→ 需要一份可复现的具体清单才动手。 |
| 16 | **成立，该修** | `action` 的 35 个取值里约 16 个不是动作：`人物弧光`／`人物塑造`／`分工`／`制作流程`／`分镜写法`／`动线`／`化妆`／`协作`／`反派表演`／`在场处理`／`叙事`／`台词`… 这是抽取器把概念塞进最近的必填槽位造成的**标签空间污染**，会同时稀释 `ACTION_BEAT` 与 `PERFORMANCE_PACK` 的召回。→ 归 index/语料 lane，方案见下。 |
| 17 | **成立** | 实测 915 条边里带 `forbid` 的 **81 条全部是 `EMOTION_PACK`**，其余 12 类为 0 —— 跨类负向知识（"这个动作不该配这个运镜"）**结构上表达不了**。→ 与 #11 的 `forbid` 宿主范围是同一件事，需用户裁决后改 schema。 |
| 18 | **成立，一半是内容缺口** | `character`／`object` 两个节点类：**0 个节点、0 次使用**（实测）。缺的三类边（对白交付/配乐/道具×环境）是**语料缺口**而不是 schema 缺陷——13 类边里没有对应类型。→ 与 #14/#17 一起作为"下一次扩 schema"的输入。 |
| 19 | **不成立** | 审查说"132 张手写策展卡不入索引（无 source_span）"。实测 `HANDWRITTEN_CARDS` 132 张**全部**出现在 `knowledge/hypergraph.edges.jsonl` 的 `sources` 里（生成卡 1981 张里 1948 张也在）。→ 不修。 |
| 20 | **成立，需等 #10** | `knowledge/cases.jsonl` 733 篇里 53 篇 `source_ref.url` 是 `repo://`（自撰），manifest 指纹绑旧语料。重生成**必须先拍板 #10**（自撰拉片笔记留不留），否则要么白干要么把自撰洗成外部。 |
| 21 | **成立，但优先级低** | E2 要 `shots.json` 的 `movements[].source ∈ {experience, lesson, case}`，而 `delivery/manifest.py` 记录的是 `declared` 等值 → 分子恒 0。**但 E2 在 `tools/knowledge/quality.py:133` 明确是 `diagnostic: True`、不设门**，不影响验收。→ 低优先，可在下一轮把边来源写进 manifest。 |

## D. 环境与工程（4 条）

| # | 结论 | 判据与处分 |
|---|---|---|
| 22 | **成立，已修** `91ded6d` | 4 处引用已停用的 `qwen3-vl:30b`。`probe_local_model.py` 的 `--model` 改必填；两个 `fixtures/local_*.config.yaml` 加"已停用/历史"抬头并把 model 换成当前可跑的 `glm-4.7-flash`；sidecar 示例命令换成云端上游。 |
| 23 | **成立，未修** | LightRAG 真实索引缺失，走 `cases_degraded=true` 降级。这是允许的路径，但"要不要建真索引"是 #20/#10 的下游。 |
| 24 | **不成立（已过期）** | `depth`／`full_concat` **已实现**：`block_director/layer8_delivery/depth_pass.py`、`concat.py`、`export_director.py`，并有 `tools/blender_tests/test_delivery_extras.py`。config 里的告警是**前置条件检查**（如 depth 要 EEVEE，`config.py:365` CFG_102），不是"声明了没做"。→ 不修。 |
| 25 | **部分成立，需授权** | `.scratch/` 实测 **105** 个文件（不是 41）。ollama blob 实测 **32.83 GB**（18.25 GB 完整重复副本 + 14.58 GB 中断分片），不是 18.49 GB。删除是破坏性操作，**等用户一句话**。 |

## E. 流程与协作（2 条）

| # | 结论 | 处分 |
|---|---|---|
| 26 | **成立，已修** `91ded6d` | 两条标注 lane 同时在跑，v14 分片半成品有被误并的风险。已停 shard4、把 7 个分片移进 `work/glm_v14/QUARANTINE/` 并写 README（含"不得用于门①–⑩"的说明）。 |
| 27 | **成立，是协作事实** | 热文件在同一时段被多路改写（`hypergraph.py`、`vocab.json`、`tools/holdout_*`、`knowledge/hypergraph.*`）。本轮已把"谁能改哪个文件"写进各 lane 的任务书；主 agent 提交前按文件挑。 |

## 汇总

* **已修**：#1 #2 #3 #4 #22 #26（提交 `c2f0b15`／`24eb572`／`e34f45b`／`91ded6d`）。
* **该修、未修**：#16（action 标签污染，方案见下）／#7 的 Q4+Q6b（retriever 排序）／#21（E2 记账，低优先）。
* **不成立**：#15 #19 #24（举例/事实与当前工作区不符）。
* **需用户裁决**：#9 #10 #11 #12 #13 #25。

### #16 的修复方案（待 index lane 执行，不动验收线）
`action` 是 `ACTION_BEAT`／`PERFORMANCE_PACK` 的**必填**槽位，抽取器碰到"人物弧光"这类概念时无处可放就塞进去。
三条候选，按代价排序：
1. **收紧取值词表**：把非动作取值从 `hg.VALUE_DOMAINS["action"]` 移出，抽取时按"必填槽位填不满 → 该边整条丢弃"处理（与 §2.3 的 K4 口径一致）；代价是 `ACTION_BEAT` 边数会掉，需要补语料。
2. **加一个 `concept` kind** 并允许它作为选填成员挂在最近的边上：保留信息、不再污染 `action`；代价是 schema 变更 + 金标准重建。
3. **只做诊断**：把 16 个非动作取值列进 `docs/knowledge/`，不改 schema——最省，但不解决召回稀释。
建议先做 **3 → 1**（先用诊断把清单钉死，再收紧词表并补语料），把 2 留给"下一次扩 schema"（与 #17/#18 一起做）。
