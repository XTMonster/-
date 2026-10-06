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
