# v1.5 逐卡测试核对（"这些子 agent 的任务到底测过没有"）

**run-id**：20261007-v15-card-tests
**触发**：用户问「这些子 agent 的任务有做过测试了么？」——回答必须**以当前工作树的实测读数为证**，
不能拿子 agent 的自述当验收。
**纪律**：只跑测试、只记录；不改判据（R-5）。

---

## 1. 逐卡专项测试（本机实测，一条一条跑出来的）

```
python -m pytest <file>            # pytest 9.1.1：-q 不打印汇总行，故用默认 verbosity
```

| 卡 | 测试文件 | 实测 |
|---|---|---|
| P2-T1 拍点契约 | `tests/test_beats.py` | **17 passed** |
| P2-T2 Plan 字段 | `tests/test_plan_v15_fields.py` | **5 passed** |
| P2-T3 SDL 1.5 | `tests/test_sdl_15.py` | **6 passed** |
| P2-T3 SDL 1.5（另一车道同名文件） | `tests/test_sdl_v15.py` | **14 passed** |
| P2-T4 emit schema＋合并 | `tests/test_draft_v15_schema.py` | **6 passed** |
| P2-T5 配置三键 | `tests/test_config_vlm_review.py` | **29 passed** |
| P3-T1 拍点→actions | `tests/test_beat_compiler.py` | **20 passed** |
| P3-T2 锚点摆位 | `tests/test_staging_anchors.py` | **16 passed** |
| P3-T3 灯光矩阵 | `tests/test_lighting_matrix.py` | **11 passed** |
| P3-T3 道具交互 | `tests/test_prop_interaction.py` | **13 passed** |
| P3-T4 构图声明消费 | `tests/test_composition_consumption.py` | **33 passed** |
| P4-T1/T2 规则包 | `tests/test_rulepack.py` | **14 passed** |
| P4-T3 forbid 补挂 | `tests/test_forbid_guard_backfill.py` | **7 passed** |
| P4-T4 破例辩护对拍 | `tests/test_justification_audit.py` | **10 passed** |
| P4-T5 检索种子接线 | `tests/test_retrieval_seed_wiring.py` | **6 passed** |
| P6-T1 VLM 评审回路 | `tests/test_vlm_review.py` | **34 passed** |
| P6-T2 多样性 / Best-of-N | `tests/test_best_of_n.py` | **31 passed** |
| P1-T3 状态块读数 | `tests/test_agents_status_is_current.py` | **3 passed** |
| 派发图结构守卫 | `tests/test_dispatch_graph.py` | **4 passed** |

**合计 19 组 / 279 条，全绿**（命令可逐条复现）。

## 2. Blender 侧（真实 bpy 环境，链内探针）

`tools/run_tests.ps1` 的探针清单里，v1.5 新增三支并已登记（链规模对拍由
`tests/test_agents_status_is_current.py` 钉住）：

```
tools/blender_tests/test_anchor_staging.py     -> label=anchor-staging
tools/blender_tests/test_prop_interaction.py   -> label=prop-interaction
tools/blender_tests/test_vlm_review.py         -> label=vlm-review
```

另 P3-T4 在 `tools/blender_tests/test_phase3_audit.py` 里加了一条
`declared_composition_overrides_the_default_aim`。

最近一次完整链（`docs/evidence/20261007-071404/`）**探针全过**；
因本轮又修了 Q1 回归（见 §4），已按纪律**重跑**一次链，读数见随后的
`docs/evidence/<新 run-id>/`。

## 3. 只出文档的卡（**按设计没有单测**，如实记）

| 卡 | 交付物 | 怎么验 |
|---|---|---|
| P1-T1／P1-T2 | 文档抬头／编者注 | `grep` 验收（`OPEN_PROBLEMS (19)`/`⑲` 无残留）+ 状态块用例 |
| P5-T1 | 换代登记模板 ＋ 零成员 kind 诊断 | 自带脚本 `python docs/evidence/20261007-054900-p5t1/zero_member_kinds.py --check` → `[OK]`（exit 0） |
| P5-T3／P5-T4 | ⚖️ 备料件（别名表／axis_side 双路线／评委口径／A5 裁决包） | **无单测**（它们不改代码），按卡的交付物清单逐份存在性核对 |

## 4. 顺带查出的**真回归**（已修，且是本轮最重要的发现）

首轮完整链报 `Q1 fail 0.1208`（**基线是 0.9975**）。定位：

```
Q1 = 每个 held-out 查询的 top-1 是否就是期望边（下限 0.70）
```

而 P4-T3 的 forbid 补挂第一版把补挂边**插到检索列表最前**，
抽样 40 条里有 **30 条**的 top-1 被顶掉 —— 正是 `0.9975 -> 0.1208` 的来源。
TDD §5.6 的原话是"**渲染**排最前"（注入文本的顺序），**不是**改写检索名次。

**修法**：`Hypergraph.retrieve` 只把补挂边**追加**进注入集合（名次不动、
`forbid_members_seen` 照旧统计）；"排最前"改由渲染层
`rulepack.render_rule_pack(exempt_edge_ids=…)` 负责。

**修后实测**：

```
python tools/holdout_score.py --holdout fixtures/knowledge_holdout.jsonl --json ...
-> Q1 pass 0.9975 | Q2 pass 1.0 | Q3 pass 0.0 | Q4 pass 1.0
   Q6a pass 1.0 | Q6b pass 1.0 | Q7 pass 1.0 | passed: true   (exit 0)
```

守门：`tests/test_forbid_guard_backfill.py` 现在 7 条，含
「补挂**不得顶掉检索名次**」「补挂行**必须排在注入文本最前**」
「没有禁忌边时行为逐字不变」三条 —— 断言是**改到正确的层**并加严，不是放宽
（旧的"检索列表第一条必须是补挂边"断言本身编码了那个错误行为）。
冻结仪器按规矩同步到第二十八次（`_reason_28` 记明这次同批修正）。

另修一处会导致**偶发红**的测试卫生问题：`tests/test_best_of_n.py` 的
`subprocess.run(..., text=True)` 没有指定编码，子进程的 UTF-8 输出在本机被按
cp936 解码，`_readerthread` 抛 `UnicodeDecodeError`（pytest 报
`PytestUnhandledThreadExceptionWarning`）。已加 `encoding="utf-8", errors="replace"`。

**同一隐患共 4 处**（用户追问"修了么"时补查出第 2 处）：

| 文件:行 | 子进程 | 原样 | 处置 |
|---|---|---|---|
| `tests/test_best_of_n.py:69` | `tools/gen_specs.py --check` | **真隐患**（子进程写 UTF-8，父进程按 gbk 解码 → `UnicodeDecodeError: 'gbk' codec can't decode byte 0xb4`） | 加 `encoding="utf-8", errors="replace"` |
| `tests/test_config_vlm_review.py:128` | 同上 | **真隐患**（同一处 warning 的第二条，首次漏修） | 同上 |
| `tests/test_hypergraph_determinism.py:238` | `-c print(fingerprint)` | 输出是 ASCII（且已设 `PYTHONIOENCODING=utf-8`），非隐患 | 一并按同一卫生标准加固 |
| `tools/probe_blender.py:286` | `pip --version` | 输出 ASCII，非隐患 | 同上 |

**修后证据**：仓库级扫描 `subprocess.(run|Popen|check_output|check_call)(...)` 里
`text=True` 而无 `encoding=` 的调用 → **NONE**；把该 warning 当错误跑
`python -m pytest tests/test_hypergraph_determinism.py tests/test_best_of_n.py
tests/test_config_vlm_review.py -W error::pytest.PytestUnhandledThreadExceptionWarning`
→ **85 passed**；链内 pytest 的 `warnings summary` 段落**消失**（原来是 2 warnings）。

## 5. 最终验收链（冻结单树，权威读数）

```
powershell -File tools/run_tests.ps1
-> docs/evidence/20261007-074427/
   tree.json     : head f6530c6…  stable True        # 单树，读数可引用
   holdout_gates : overall pass                      # 门①–⑩ 全 pass
   holdout_quality: passed true
       Q1 pass 0.9975 (线 0.70)  Q2 pass 1.0   Q3 pass 0.0
       Q4 pass 1.0   Q6a pass 1.0  Q6b pass 1.0  Q7 pass 1.0
   rks.json      : 203 checks, failed = ["RK-13"]
   链日志        : 31 支 Blender 探针全部 "OK:"，0 支 FAILED
   pytest(链内)  : 2769 passed, 1 skipped —— 且**无 warnings summary**
```

**结论**：v1.5 落地后，链上**只剩 RK-13（E1 ≥ 0.70）这一条已知的、已结案的红**
（A1：判据冻结、按 (a) 结案）。Q1 回归已修，其余门的读数与本版开始前的基线一致。
