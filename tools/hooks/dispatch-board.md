## 自动派发板（dispatch-board hook）

> 本段由 `dispatch-board.ps1` 每轮自动生成，依据是仓库里的
> `执行文档v1.5/dispatch_graph.json`（机器可读 DAG，与 EXECUTION_PLAN 的
> 附录 A/B 同源）。它只做一件事：**算出"现在能安全并行派发的任务卡"**。
> **并行只有三条硬边界，越界就一定不派**：
> ① 依赖未满足（`depends:`）② 写集与在飞卡相交（`conflict:`）③ 该卡本身
> 不可派发（`mode:serial` 同文件双写 / `mode:user` ⚖️ 须用户点头 / `mode:gate` 阶段门）。

**进度**：done {DONE}/{TOTAL}｜在飞 {INFLIGHT_N}｜并发上限 {MAX}｜**现在可派发 {READY_N}**

### 一、现在立刻派发（并行安全；有多少派多少，直到上限）

{READY}

派发每一张卡时，`spawn_agent` 的消息必须包含：① 卡号与卡文（让它自己读
`执行文档v1.5/EXECUTION_PLAN.md` 的该卡整段）② 当前已完成的卡清单（避免重做）
③ **它的写集白名单**（不许改白名单外的文件）④ 红线 R-1…R-11 ⑤ 不许跑全量 pytest
（并发上限 2）⑥ 不许 git commit ⑦ 完成后跑该卡验收命令并回报。
派发前先 `-Claim`，完成后 `-Mark`。

> **禁止孙子代理**：派发的消息里必须写一句「**不要 spawn 任何子 agent**」。
> 实测教训（2026-10-07）：子 agent 自行派生孙子后会**抢同一批文件**、把状态
> marker 改乱（曾把两张卡标成在飞而实际没人做），并越界去做别的卡。**派发权只
> 在主线**——子 agent 只执行它自己那一张卡。

### 一之二、**派发前分析**（每张卡：目标 × 耦合性）

在决定派谁之前，先把每一张卡摊开看：它的**目标**、写集与其它卡的**重叠数**
（`coupling`）、**依赖深度**（`deps_depth`）、以及它是否**触碰冻结仪器**
（`frozen_instruments`，从 `tests/plan_v4_instruments.sha256.json` **实时**读）。
耦合度越高越不许同时派——同文件双写会丢工作，这正是本项目付过代价的形态。

{ANALYSIS}

### 一之三、**本轮决定**（派几张、为什么不派剩下的）

{BATCH}

> 决策规则（机械、可复核）：**能派**当且仅当 依赖全完成 ∧ 写集与在飞卡及同批卡
> **两两不相交** ∧ `mode=auto` ∧ 未到并发上限；否则**不派**，退回串行。
> 每次分析的机器可读快照落在 `docs/evidence/_v15_dispatch/last_board.json`。

### 二、在飞（不要重复派发；也不要派写集与它们相交的卡）

{INFLIGHT}

### 三、暂不派发（原因码）

{BLOCKED}

原因码：`depends:<ID>` 依赖未完成；`conflict:<ID>` 写集与在飞卡 `<ID>` 相交；
`mode:serial` 同文件双写／语义依赖，必须等前序 `-Mark` 后由主线或单代理串行做；
`mode:user` ⚖️ 须用户裁决，只准备材料；`mode:gate` 阶段门，由主线自己跑验收命令；
`cap` 并发已到上限（先等在飞的收工）。

### 四、状态维护命令（主线执行）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\hooks\dispatch-board.ps1" -Claim P3-T4
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\hooks\dispatch-board.ps1" -Mark  P3-T4
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\hooks\dispatch-board.ps1" -Unclaim P3-T4
```

**质量红线（不许为了并行而破）**：写集相交的卡**永远**不同时派；阶段门必须
在该阶段全部卡 `-Mark` 之后由主线跑；⚖️ 卡不许派实现。并行只用于**文件互斥且
语义独立**的卡——一旦不满足，就退回串行，宁慢不乱。
