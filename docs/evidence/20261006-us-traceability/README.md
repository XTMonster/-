# v1.4 §A.3 的 **17 条用户故事**：逐条追溯审计（哪些真的被量到了）

日期 2026-10-06 20:2x。目的：§A.3 的抬头写着"每条 AC 都必须能用 §4 的 oracle 或命令客观判定"，
但**没有人把 17 条逐条对过账**。本目录补这一次，并明确写出**我读了什么、依赖了什么**。

## 一、权威读数（同一次冻结树全链，`docs/evidence/20261006-195300/`）

* `rks.json`：**19 条 RK 全部 `measured`**，其中 **18 条 pass、唯一 fail 是 `RK-13`**；185 条 check。
* `holdout_gates.json`：**门①–⑩ 全部到位且 pass**。
* `knowledge_quality.json`：`Q0 pass / K1 1.0 / Q1–Q7 pass / E3 0 / **E1 fail 0.1771** / E2 not_measured`。
* `tree.json.stable = true`（数字可归因到一棵树）。

## 二、逐条对账

| US | 它点名的 oracle／产物 | 存在？ | **量到了吗（证据）** | 判定 |
|---|---|---|---|---|
| US-1 | RK-9 ＋ `tests/test_run_settings_suffix_formats.py`（契约） | ✅ | RK-9 `pass`；单测 **4 条**，其中含**负例**（"把说明串改回旧的手写句必须断言失败"）——**断言逐条读过** | **满足** |
| US-2 | RK-11 | ✅ | RK-11 `pass` | 满足 |
| US-3 | RK-3 ＋ RK-19 ＋ F2 契约用例 | ✅ | 两条 RK `pass`；`speaker_status`（AC③"不得伪造 character_id"）在 `tests/test_scene_contract.py` 等被断言 | 满足 |
| US-4 | RK-7 | ✅ | RK-7 `pass` | 满足 |
| US-5 | RK-8 | ✅ | RK-8 `pass` | 满足 |
| US-6 | RK-6 | ✅ | RK-6 `pass` | 满足 |
| US-7 | RK-14 ＋ RK-15 | ✅ | 两条 `pass` | 满足 |
| US-8 | RK-4 | ✅ | RK-4 `pass` | 满足 |
| US-9 | RK-1 / RK-2 / RK-5 | ✅ | 三条 `pass` | 满足 |
| US-10 | RK-16 | ✅ | RK-16 `pass` | 满足 |
| **US-11** | **RK-13**（K1–K4 ＋ Q0–Q7 ＋ E1–E3） | ✅ | ①②③④⑤⑦ **pass**（Q1–Q7、E3、门①–⑩）；**⑥ `E1` = `fail`，0.1771 < 0.70** | **不满足（只差 ⑥）** |
| US-12 | RK-10 ＋ `repair_applied` 计数 ＋ 反向突变 | ✅ | RK-10 `pass`；`tests/test_driver_guards.py:277 test_repair_applied_count_matches_failed_shots` 与 `:298 …_not_written_when_nothing_failed`（**正反两条**） | 满足 |
| US-13 | RK-12 ＋ `brief_received` ＋ checkpoint 回归 | ✅ | RK-12 `pass`；`brief_received` 在 `tools/blender_tests/test_replay.py`；checkpoint 在 `tools/blender_tests/test_phase5_checkpoint.py`（两者都在链的 32 步清单里） | 满足 |
| US-14 | RK-18 | ✅ | RK-18 `pass`；`tests/test_budget_gate.py` 含 `test_zero_never_enters_the_min`（AC③ `0 = 不限`） | 满足 |
| US-15 | `tests/test_prompts_fields.py`（契约） | ✅ | 5 条；AC② 的"与同一映射函数相等"（`SHOT_TYPE_LABELS`）与 AC③ 的**内部键全集**（`ENGINE_KEYS`，比文档要求的四条**更宽**）都被断言——**读过** | 满足 |
| US-16 | §4.4 步骤 0 负例 | ✅ | `tools/run_tests.ps1:185-199`：对**非空但不存在**的 `BLENDER_EXE` 也走"找不到"分支并打印 `INCOMPLETE`（AC③ 的原话要求）——**读了代码路径** | 满足（见下"未验证"） |
| US-17 | `tests/test_action_conflicts.py`（契约）＋负例 | ✅ | 6 条；AC① 用**独立重算**的 `_overlap_frames(adjusted) == 0`、AC② 事件数 `== 1`，且含"语义禁忌不许被错开"的负例——**读过** | 满足 |

另外，§5 的 **R43 贯穿规则**（新增探针必须登记进链）：`test_operator_end_to_end.py`、
`test_scene_contract.py`、`test_label_layout.py`、`test_label_toggles.py`、`test_knowledge_holdout.py`、
`test_knowledge_trace.py` **全部存在**，且前四个已作为 `operator-e2e` / `scene-contract` /
`label-layout` / `label-toggles` **登记在链的 32 步清单里**（`run_tests.ps1:138-143`）。

## 三、结论

**17 条里 16 条的全部 AC 都有"已登记且量到"的 oracle／契约用例；唯一不满足的是 `US-11`，
而且只差第 ⑥ 项（E1 ≥ 70%）**——就是 RK-13，现在是一个**量到的 fail（0.1771）**，
不再是"量不到"。它的另外六项（Q1–Q7、E3、门①–⑩）全 pass。

⇒ **整份 v1.4 的验收面现在是"一格红"**：`US-11⑥ = RK-13 = E1`。这一格要不要动、怎么动，
是用户对 A／C 的裁决（GPT-6A 的 `a_metric` 与 `full_head` 都指出：**动它必须用户明示批准**）。

## 四、未验证 / 我依赖了什么（如实挂）

* **逐条读过断言的只有 5 处**：US-1③、US-13、US-14、US-15、US-17 的文件我读了；
  **其余各条我依赖的是"链上该 RK 已 `measured` 且 `pass`"**（那是本仓的权威读数），
  **不是**逐个 AC 去核对每条断言的措辞。⇒ 本表证明的是"**每格都有已登记的测量**"，
  不等于"我逐字核过每一条 AC"。
* **US-16 的负例没有被链每次执行**：`INCOMPLETE` 那条分支我**读了代码**，但
  "清空变量 ＋ 两个候选路径都不存在"这个**负例跑**是 §4.4 的手工步骤，链里不跑。
* 本审计只覆盖 **§A.3 的 17 条**；§A.4 的成功指标表与 §6 的风险取证表**未在本轮逐条对账**。

---

## 五、追加：**§6 的"取证落点表"逐条对账**（R39 收口的那张表）

§6 自己写着："每条风险的'取证'必须是**具名产物/测试/阶段**，不得写'报告/CI'这类不存在的东西"。
所以这张表**可以被机械核对**——本轮逐条查了：

| 风险 | 它点名要有的东西 | 存在？ | 当前读数 |
|---|---|---|---|
| 抽取噪声 | `tools/knowledge/sample_edges.py` → `docs/evidence/<run-id>/edge_spotcheck.jsonl`；＋`rejects ≤ 5%` | ✅ ✅ | 脚本在；`20261006-195300/edge_spotcheck.jsonl` 28,759 B；**`rejects = 0`** |
| 超边重复与爆炸 | `knowledge/hypergraph.manifest.json` 的 `raw_edges / valid_unique / duplicates / rejects` | ✅ | **638 / 638 / 0 / 0** |
| 检索"半条边" | Q6b = 100%（读**实际 prompt**）＋ Q7 = 100% | ✅ | Q6b `pass`（plan 778/2000、shot 788/800，required 半边 **pass**）；Q7 `pass` |
| 评测无公开基准 | `fixtures/knowledge_holdout.jsonl`（≥1200 条）＋ `tools/check_holdout.py` | ✅ | 门①–⑩ 全 pass（queries 2847） |
| 重抽取成本／通用·确定性 | `tests/test_hypergraph_determinism.py`（新） | ✅ | **文件在**（本轮只核存在，**未读它的断言**） |
| 通用·预算 | `shots.json.llm_calls/retrieval_calls` 与 `audit_log.jsonl` **独立对拍** | ✅ | **RK-18 `pass`** |
| 通用·依赖 | `tests/test_knowledge_trace.py` 断言 `degraded/cases_degraded` 与 `lanes` | ✅ | 文件在；`20261006-long21/knowledge_trace.json` 的键含 `lanes`／`cases_backend`／`cases_degraded`／`lightrag_index_fingerprint`／`degraded` |
| 混合架构（两套索引／路由／小语料） | trace 里的 `lanes` 与两路计数、`cases_degraded` | ✅ | 同上（六个键全在） |

⇒ **§6 的取证落点表逐条都有实物**，没有"写了却没做"的格子。

### 一条如实记的观察（**未定性为缺陷**）

链上那次 **离线** headless 跑，`knowledge_trace.json` 写在**临时目录**
（链的输出里逐字是 `"knowledge_trace": "C:\\Users\\…\\Temp\\bd_run_194204\\knowledge_trace.json"`），
**没有进 `docs/evidence/<run-id>/`**；所以那次运行的证据目录里**没有 trace**，
能引用的 trace 是**真实模型跑 `20261006-long21/`** 那一份。

* **产品行为是合格的**（trace 确实被写了，内容也齐）；
* 但按本仓自己那句"**一个能悄悄消失的具名产物，和一道能悄悄消失的门是同一个洞**"，
  **链的证据目录里少这一件**值得记一笔。
* **没有定性为缺陷**：§6 的表要求的是"`knowledge_trace.json` 必写"，**没有**要求它必须落在证据目录；
  要不要收紧这条口径是**新的选择题**，不在本轮擅自改动。
