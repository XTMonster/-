# 阶段门 **G4**：forbid 守门（FR-9 / B7）同代实测 ＋ 排名未动

**run-id**：20261007-g4-forbid-guard
**卡**：`执行文档v1.5/EXECUTION_PLAN.md` 卡 P4-T4 的**阶段门 G4**
（"三份冻结工程同代重建，before/after 对跑——`forbid_members_seen>0`；
Q1/Q2/Q5/E1 同口径读数对照"）
**性质**：**只读测量**。不改判据、不改索引、不改任何已入库运行。

---

## 1. 方法：为什么**不用**新开一次 LLM 真跑也能做同代测量

* 那些冻结的运行把**真实的逐镜检索查询**记进了 `audit_log.jsonl` 的
  `retrieval_call` 事件（`data.query` ＋ `data.edge_ids`）；
* 它们 pin 的索引代与**当前工作树发出的索引**是**同一代**
  （`c796a5a87018631d…`，22 份运行逐份一致）；
* 检索是**确定性纯函数**：同一代索引 ＋ 同一条查询 ⇒ 同一次选边。

⇒ **重放那些真实查询 = 同代测量**，而且**零 LLM 成本**。

```powershell
python docs/evidence/20261007-g4-forbid-guard/g4_forbid_guard.py
```

## 2. 实测（三份冻结工程 ＋ long21）

```
totals = { queries: 103, with_backfill: 66, forbid_members_seen: 217,
           backfilled_edges: 91, top1_preserved: 103, top1_is_backfilled: 0 }
gate_g4 = { forbid_members_seen_gt_0: true, ranking_preserved: true }

  long9     queries=25 with_backfill=17 forbid_members_seen=53 top1_preserved=25 top1_is_backfilled=0
  long11    queries=23 with_backfill=14 forbid_members_seen=49 top1_preserved=23 top1_is_backfilled=0
  long12    queries=28 with_backfill=18 forbid_members_seen=58 top1_preserved=28 top1_is_backfilled=0
  long21    queries=27 with_backfill=17 forbid_members_seen=57 top1_preserved=27 top1_is_backfilled=0
```

**判读**：

1. **`forbid_members_seen = 217 > 0`** ⇒ B7 的"守门能力从 0 到 1"**达成**：
   真实查询里，含禁忌的边**真的被注入**了（66/103 条查询至少补挂一条）；
2. **`top1_preserved = 103/103`，且 `top1_is_backfilled = 0`** ⇒ **排名没有被动过**：
   逐条与当年真实运行记下的 `edge_ids[0]` **完全一致**（这正是 `Q1` 的合同）；
3. 逐镜四元组层面的不回退由 **G3** 独立给出
   （`docs/evidence/20261007-g3/README.md`：long9/long11/long12 的
   `(shot_id, passed, score, errors)` 序列 **identical_rows = True**）；
   Q1/Q2/Q4/Q6a/Q6b/Q7 由**完整链**给出（`docs/evidence/20261007-074427/`：
   **Q1 0.9975 pass**、其余全 pass、`holdout_gates.overall = pass`）。

## 3. **口径澄清**（重要：B7 的"0"与我这里的"3"不是同一个量）

本仓在"forbid 到底有没有生效"这件事上有**三个不同的量**，历史上被混用过：

| 量 | 定义 | 实测 |
|---|---|---|
| **(a) 注入过的边里带 forbid 成员的** | 那几次运行**真的选出来**的边中，含 ≥1 个 `forbid` 成员的**不同边数** | 39 条注入边里 **3 条**（per-run：long9 3 / long11 2 / long12 3 / long21 1；kind 全是 `movement`/`shot_size`） |
| **(b) `judgeable_forbid_members`** | 闭环诊断里**"前提成立、可判"**的边所带的 forbid 成员（不可判的边在 `continue` 前不计） | long21 = **0** |
| **(c) `forbid_members_seen`**（v1.5 新增） | 本次**注入集合**（含补挂）里的 `forbid` 成员总数 | 重放 103 条真实查询 = **217** |

⇒ **不能说成"以前完全是 0"**：当年也注入过带禁忌的边（(a)=3）；
B7 记的"0"指的是 **(b)**（可判的那批）。
本版把它变成 **(c)** 这个**明确、可复算**的读数，并证明它 **> 0**——
这就是 FR-9/FX-3 想要的那件事，**不必也不该**用"以前是 0"来叙事。

## 4. 本门**没有**覆盖的东西（如实写）

1. **没有新开一次 LLM 真跑**：本门重放的是**已记录的真实查询**，
   所以它证明的是"**同一批真实查询下守门生效**"，不是"下一次真跑的模型行为"；
2. **E1 仍红**：E1 属已结案的红线（A1），本门**不碰**它的判据；
3. 本门是**同代对照**：若将来换索引代，"当年记下的 `edge_ids[0]`"就不再可比，
   必须按 A6 重新登记后重测。

## 5. 证据指针

- 本目录 `g4_forbid_guard.py`（测量脚本，只读）／`g4_forbid_guard.json`（逐条明细：103 行）
- `docs/evidence/20261007-g3/README.md`（逐镜四元组 `identical_rows=True`）
- `docs/evidence/20261007-074427/`（完整链：探针 31/31、Q1 0.9975、门①–⑩ pass）
- `work/_g4_before_reading.py`（§3 那张表的 (a) 行：当年注入边的 forbid 计数）
