# 裁决包 · A5 四条"须用户点头"（R1 / R5 / D10 / D11）

**run-id**：20261007-0610-p5t3t4
**卡**：`执行文档v1.5/EXECUTION_PLAN.md` 卡 **P5-T4**（TECH_SOLUTIONS §一 A5）
**性质**：⚖️ **备料件**。按 2026-10-06 的改判，这四条应走 **GLM-5.3** 裁决通道；
本文只做**路由与格式化**，**不替用户/GLM 拍板**（R-5）。
结构固定：**问题 → 选项 → 影响面 → 证据指针 → 建议**。

> 这四条在旧表（`docs/knowledge/ADJUDICATIONS_v4.md`）上的位置：
> R1 `:20`、R5 `:24`、D10 `:26`、D11 `:51`。

---

## 1. R1 —— 噪声带 R 的数值与**验收地位**

**问题**：`C6` 的对齐配方里，"噪声带 R 由同臂离散推出"这条**配方**已采纳；
但 R 本身是否**升格为验收门限**（即：`ΔE1 < R` 时判"不显著"并阻止结论），
还是只作为**读数提示**（照出差值，由人看），至今没有归属。

**选项**

| 选项 | 内容 | 代价 |
|---|---|---|
| **A** 只作读数 | 报告里给 R 与 `ΔE1`，不设门 | 差值小但仍被当成"提升"引用 |
| **B** 升为门限 | `ΔE1 < R` ⇒ 该对比不出结论（标 `not_significant`） | 会改"哪些对比算数" ⇒ 判据级；需说清历史读数追溯口径 |

**影响面**：`D8`（默认路由）直接消费"`ΔE1(lightrag − hybrid) ≥ 噪声带 R`"这一条；
若 R 升为门限，`D8` 的触发次数与默认路由**都会变**。历史批次（三臂对照、
`20261006-e1-*` 系列）全部需要按新口径重述或显式标"旧口径"。

**证据指针**

* 配方来源：`docs/knowledge/PLAN_V4_LOOP2_DISPOSITION.md` B.1（N=8、成对、降级计数=0）；
* 旧表条目：`docs/knowledge/ADJUDICATIONS_v4.md:20`；
* 清单条目：`docs/knowledge/OPEN_ITEMS_20261007.md` §一 A5。

**建议**：**空**（判据级问题；主线不建议，交 GLM-5.3 裁决）。

---

## 2. R5 —— `Case` 新增可选字段是否纳入 `schema_fingerprint`

**问题**：`Case` 新增可选字段（`score` / `chunk_ids` / `entity_hits`）已经落地；
争议只在**一支**：把这些字段**纳入 `schema_fingerprint` 的纳管范围**之后，
"改既有字段语义"要不要也算判据改动（须用户点头）。

**选项**

| 选项 | 内容 | 代价 |
|---|---|---|
| **A** 只纳管"新增" | 新字段进指纹；改既有语义照旧自由 | 既有语义被改时无闸门（与 S0/S1a 同形状的洞） |
| **B** 两者都纳管 | 新增与"改既有语义"都进指纹（改则换代） | 更严；每次调语义都是一次换代 |

**影响面**：`block_director/knowledge/hypergraph.py::schema_fingerprint()` 的载荷；
`tools/kb_fetch/build_hypergraph.py` 的 `CACHE_KEY_FIELDS` 第 6 格（`schema_version`）；
`tests/plan_v4_instruments.sha256.json` 的守门（本版已经历第 28/29 次重新冻结）。

**证据指针**

* 旧表条目：`docs/knowledge/ADJUDICATIONS_v4.md:24`；
* 指纹载荷：`block_director/knowledge/hypergraph.py:35-80`；
* 冻结守门：`tests/test_plan_v4_instruments_frozen.py`。

**建议**：**空**。

---

## 3. D10 —— 某臂"召回为空"时 E1 的分母怎么算

**问题**：E1 的分母是"面板条目数"。某臂对某查询**一条都没召回**时，那一行
**整行消失**（不是记 0），于是召回差的臂分母更小、每行更值钱 —— 跨臂不是同一把尺。

**实测（A/B 第一轮，2026-10-05）**

| 臂 | 行数 | 有行的查询数 | 平均行/查询 |
|---|---|---|---|
| hybrid | 192 | 64/64 | 3.0 |
| lexical | 192 | 64/64 | 3.0 |
| lightrag | **142** | **59/64** | 2.4 |

**选项**

| 选项 | 内容 | 代价 |
|---|---|---|
| **A** 维持现状 | 分母 = 实际打出来的行数 | 跨臂不对等（本题小 26%） |
| **B** 固定分母 | 分母 = 查询数 × top-k，空召回记 0 | 语义更对，但**改变历史读数含义**（台账里 0.1823 / 0.2135 都是按 A 算的）⇒ 等于动判据 |
| **C** 两者并报 | 面板同给 A 与 B 两个值；`D8` 的路由判定读 **B**，历史对照仍用 **A** | 多一份计算与记录；不改变任何既有读数 |

**影响面**：`tools/knowledge/e1_panel.py::summarise` 的 `len(rows)`；`D8` 路由判定；
全部历史 E1 读数（`docs/evidence/20261006-e1-*`）。

**证据指针**：旧表 `docs/knowledge/ADJUDICATIONS_v4.md:26-49`；
面板实现 `tools/knowledge/e1_panel.py`（`summarise`）。

**建议**：**C**（原表的主线建议，理由逐字："既不让历史数字失真，又让 D8 建立在
'召回为空算失手'这件语义正确的事上"）。**但这是判据级问题，只作建议。**

---

## 4. D11 —— "看得见的降级"是否升格成"该臂无效"的机器门

**问题**：2026-10-05 的 P9 对齐跑产出了一份**格式完整**的三臂读数，而其中：
hybrid/lexical 是在**没有中文线索层**的案例集上量的（BM25 对中文查询近 0 命中）；
lightrag 是在**每请求崩一次事件循环**的服务上量的
（`work/_sidecar4.err` 里 5771 行 `bound to a different event loop`）。
产物如实记了 `queries_with_no_rows: 6`、每行 `zh: ""`，`CaseIndex` 也早有
`cases_clue_state`/`cases_clues` —— **但没有任何门消费它们**，于是 lightrag 臂照常
给出对照值，混进"三臂比较"。

**选项**

| 选项 | 内容 | 代价 |
|---|---|---|
| **A** 维持现状 | 照出读数，靠人看 `clue_state` / `queries_with_no_rows` | 弱臂数字继续以合法形态进入对外结论（最怕的静默） |
| **B** 加仪器门 | 任一臂满足 `clue_state != ""` **或** `queries_with_no_rows > 0` ⇒ 该臂标 `invalid_arm`、**不出对照值**，批终态记 `invalid` | 改"哪些读数算数" ⇒ 判据级；历史追溯口径要一并说清 |
| **C** 两者并报 | 照出对照值，同时在报告头部打 `instrument_warning` + 具名原因 | 不改"哪些读数算数"；**不阻止**弱臂数字被误引 |

**影响面**：`tools/knowledge/e1_panel.py` / `e1_baseline_summary.py` 的汇总层；
`tools/run_tests.ps1` 的证据钩子（RK-13 归属）。

**证据指针**

* 旧表条目：`docs/knowledge/ADJUDICATIONS_v4.md:51-76`；
* 会诊来源：`docs/evidence/20261005-p9-consult/`；
* 服务侧日志：`work/_sidecar4.err`（5771 行事件循环报错）。

**建议**：**B**（原表主线建议），**并附一条不阻塞的独立项**：会诊的另一条
"服务侧对'同一类不可自愈错误'加熔断"是**工程护栏**、不属判据，
可在用户点头前按普通缺陷单独立项。

**与 v1.5 的关系（本版新信息）**：卡 P4-T4 刚落地的
**破例辩护对拍**（`shots[].justification_audit`：`declared_breaks` /
`detected_violations` / `undeclared_violations` / `declared_but_clean`）
是 D11 同一形状的诊断前置 —— 它**只记录、不设门**，
正好是"要不要设门"这个问题的现场数据来源。两条线索**互相引用、互不阻塞**。

---

## 5. 路由建议（本备料件唯一的动作项）

| 项 | 建议路由 | 现状 |
|---|---|---|
| R1 | GLM-5.3 裁决 | 未路由（旧表挂在"主线建议"上） |
| R5 | GLM-5.3 裁决 | 未路由 |
| D10 | GLM-5.3 裁决 | 未路由（主线建议 C） |
| D11 | GLM-5.3 裁决 | 未路由（主线建议 B） |

按 2026-10-06 改判（本仓库 `AGENTS.md` 模型分工契约 §1b），**人工裁决走 GLM-5.3**，
Kimi 降为回退、GPT-6A 仅显式回退。
**本批未发起 GLM 调用**（本会话进程内 `GLM_API_KEY` 未继承；且裁决本身属用户动作）。

## 6. 证据指针汇总

| 内容 | 位置 |
|---|---|
| 旧表（四条原文与代价表） | `docs/knowledge/ADJUDICATIONS_v4.md:20` / `:24` / `:26` / `:51` |
| 清单条目 | `docs/knowledge/OPEN_ITEMS_20261007.md` §一 A5 |
| 技术方案原文 | `执行文档v1.5/TECH_SOLUTIONS.md` §一 A5 |
| 模型分工契约（谁裁） | `AGENTS.md` §「模型分工契约」1b |
| 破例辩护对拍（D11 的前置） | `block_director/contracts/beats.py::reconcile_justifications`、`block_director/layer3_engine/shot_auditor.py:47` |
