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

---

## 六、追加：**§A.4 成功指标表**（"全部可度量"的那张表）

| 维度 | 线 | 当前读数（`20261006-195300`，冻结树） | 判定 |
|---|---|---|---|
| 出片 | 1 条命令／两入口一致 | 链 `[4/32]` headless `state=DONE`（64 镜／4584 帧）＋ 导出标记；**RK-9 `pass`** | 满足 |
| 规模 | 声明 N 镜 → N 镜 | **RK-11 `pass`** | 满足 |
| 几何 | 头球 ≥99%／每采样帧不越界／左右各 ≥1 簇 | **RK-14 / RK-6 / RK-4 全 `pass`** | 满足 |
| 标签 | 交叠 0 对越界 | **RK-2 `pass`** | 满足 |
| 构图 | 构图门 ≥70% | **RK-10 `pass`** | 满足 |
| **知识** | K1–K4 ＋ Q0–Q7 ＋ E1 ≥70% ＋ E3 = 0 | **K1 `1.0`／K2 `1.0`／K3 每域最小 154 张、占比 0.0654／K4 `1.0`／Q1 `0.9975`／Q2 `1.0`／Q3 `0.0`／Q4 `1.0`／**Q6b `1.0`**／**Q7 `1.0`**／**E3 `0`** 全 pass；**`E1 = fail 0.1771`** | **不满足（只差 E1）** |
| 预算 | `llm_calls ≤ ceiling_effective` 且 `retrieval_calls ≤ (2+N)×lanes` | **RK-18 `pass`** | 满足 |
| 回归 | §1.6 的 34 条不得被弱化或跳过 | 断言随 `pytest`（2376 passed）与 32 步链执行；`tools/check_assertions.py` 扫空断言 **[OK] 272 文件**；`#34`（生产常量）由 **RK-14/RK-15 输入侧**量住且两者 `pass` | 满足（见下） |

⇒ **§A.4 八行里七行满足；唯一不满足的仍是"知识"那一行的 `E1`**——与 §A.3 的结论**互相同证**：
**整份 v1.4 的验收面就是一格**。

### 未验证（§A.4 这一轮的边界，如实挂）

* "**33 条断言不得被弱化**"这一格，我核的是"它们在 `pytest`／链里被执行"＋"没有空断言"，
  **没有**做"逐条拿 §1.6 的落点去比对今天的断言是否仍等强"——那是一次**独立的逐条审计**
  （§1.6 有 34 行、每行带 `文件:行号`），**本轮没做**。
  所以这一格我说的是"**在执行、没被跳过**"，不是"**等强**"。
* §A.4 只到"指标有读数"；指标本身的**噪声带**这一类问题（如 P14-263 量到的 E1 上界 ±0.04）
  **不在本表的范围内**。

---

## 七、追加：**§1.6 的 34 条**——⚠"会量错"那一类逐条查完，抓到**一条真的没闭合**

§1.6 把最危险的一类单独标了 ⚠：**"不会红、只会继续量旧几何"**。这一类可以直接用
grep 查（旧数字 1.45 / 1.10 / 0.95 / 1.60 还在不在），所以先查它。

### 1. ⚠ 类（几何"量错"）：**已全部收敛到 profile**

§3.1 点名的"**十个硬编码位置 ＋ 三个必改消费者**"逐个查：

| 位置 | 现在是什么 |
|---|---|
| `cinema/framing.py:24-31`（`SUBJECT_HEIGHT/EYE_Z/CHEST_Z`，**#1/#34**） | `_PROFILE.total_height` / `_PROFILE.eye_z` / `_PROFILE.chest_z`（注释明写"1.45/1.10/0.95 是旧几何"） |
| `cinema/composition.py:31` | `SUBJECT_HEIGHT_FOR_HEADROOM = _PROFILE.total_height` |
| `layer2_sdl/sdl_validator.py:17` | 注释明写"v1.3 写死的 1.45 会让穿模判定整条偏移（§1.6 量错项）" |
| `cinema_engine/composition_guide.py:213/216`（**#18**） | 改为 `from ...cinema.framing import SUBJECT_HEIGHT`（不再是自己的常量） |
| `knowledge/corpus.py:43-45 / :90-91`（digest 与卡正文） | 改为 `EYE_Z`/`CHEST_Z` **插值进正文**（`from ..cinema.framing import CHEST_Z, EYE_Z, SHOT_FRAME`）——文档点名"**必须新增对拍断言**"的那两处，现在实现层面已无法漂 |
| `motion/model.py:306`（`EYE_Z_DEFAULT`，**#17**） | `_PROFILE.eye_z`（注释明写"旧值 1.10 是 v1.3 的几何"） |
| `knowledge/cards_cinematography.py:368`（`cine_eye_level`，**文档说它"没有任何测试对拍、最隐蔽"**） | `parameters={"eye_z": EYE_Z}`——**也改成派生了** |
| `character_factory.py:29-36/44-51`（**#22/#23** 的 `PIVOT_Z`/`EXPECTED_TOTAL_HEIGHT`） | `EXPECTED_TOTAL_HEIGHT = _PROFILE.head_top_z`；`PIVOT_Z` 由 profile 派生（注释明写旧表让头球埋进躯干） |

**唯一剩下的字面数字**是 `cinema/framing.py:88-96` 的 `_FRAME_HEIGHT_RATIO`
（`"CU": 0.90 / 1.45` 这类）——**它不是漏网的硬编码**：注释写明那是
"v1.3 那张表按 1.45 归一后的**比例**"，随 profile 身高缩放（`:116`），
并对含头部景别加下限 `_MIN_HEAD_FRAME`（`:99`）保证 §2.2 的"头顶不切"。
⇒ 与 RK-7（头球可见 ≥99%）`pass` 一致。**这一格是设计选择，不是缺陷。**

### 2. "会变红"类抽样复核（不逐条，见下方的边界）

| # | 它要求改成 | 现在 |
|---|---|---|
| 6 | `full_concat` 默认 | `specs/config.default.yaml:106 full_concat: true` ✅ |
| 15 / 25 | 新公式 ＋ `max_wall_minutes` 120 | `tests/test_run_settings.py:71-72`：`max_wall_minutes == 120.0`、`formula == "shots * 8 + 40"` ✅（**改期望值，不是删断言**）；`contracts/config.py:143 = 120.0` ✅ |
| 21 | `AGENTS.md` 的 37 卡 / `shots * 6` / Phase 5 | `AGENTS.md:132` 已写 `"shots * 8 + 40"`；`:215` 已写 "Phase 5 is done" ✅ |
| 26 | `rag.backend` 默认 | `tests/test_config.py:34`：`is RagBackend.HYPERGRAPH` ✅ |
| 27–33 | SDL 版本串组（7 处） | 六处改为 `== SDL_VERSION`（`test_sdl.py:231/242`、`test_project_io.py:38/65`、`test_layer2_project.py:138`、`test_ui_panels.py:176`），golden 快照 `expected_sdl_simple.json:3 = "1.4"` ✅ |

### 3. **抓到的那一条：§1.6 #20 真的没闭合**（本提交修掉）

§3.1 的模块表里明写："`budget_formula.py` | 改 | …；**注释里的 `"shots * 6"` 同步改（§1.6 #20）**"。
实测两条都还在：

* `block_director/layer5_orchestrator/budget_formula.py:4` 的 docstring 举例仍是 ``"shots * 6"``；
* `tests/test_budget_formula.py::test_documented_default_formula` —— **名字说"文档里的默认公式"，
  断言的却是 `evaluate("shots * 6", …)`**，也就是 **v1.3 的旧默认**。这是 F7"同源文档漂移"里
  最难发现的一种：**测试是绿的**，名字还在替一个已经不存在的默认值作证。
  （这正是 §1.6 把这一类单列的原因。）

**修法（加强，不是替换）**：docstring 改成真默认；那格测试**从配置读真源**
（`AppConfig().budget.max_llm_calls_per_scene_formula`）再算，**同时保留** `shots * N` 形状的覆盖。
守门：全量 `pytest` **2376 passed / 1 skipped**；`tools/check_assertions.py` **[OK] 272 文件**。

### 4. 未验证 / 观察（如实挂）

* **我只逐条查了 ⚠ 类 ＋ 抽样 6 条"会变红"类，不是全部 34 条**。剩下的（如 #2/#3/#5/#7/#9/#11/#12/#19/#24/#35）
  **没有**逐条比对今天的断言是否仍**等强**——那需要按 §1.6 的 `文件:行号` 逐行走一遍，本轮没做。
* 两处**未定性**的观察：`fixtures/local_model.config.yaml:39` 仍写 `"shots * 6"`、
  `fixtures/local_sidecar.config.yaml:47` 仍写 `"shots * 8"`（§3.2 记作"原值"）。
  它们是**探针用的显式配置**、不是默认值，**看不出是否故意**；§1.6 也没列它们。
  **本轮不改**，只记下来备查。
