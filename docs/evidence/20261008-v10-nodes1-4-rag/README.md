# `20261008-v10-nodes1-4-rag` — 超图 RAG 在真实一跑里**到底输出了什么**

用户 2026-10-08 中途问："超图建模 rag 输出了什么，有没有达预期效果"。
这一份是**同一跑**（剧本 = 用户真实分镜表 `shotlist_market_v10_nodes1_4`，
13 镜，`qwen3.8-max-0902@百炼`，思考档 max）的现场读数，**没有重跑检索、没有改判据**。

## 1. 检索层：真的走了超图，且三通道都有货

`runs/audit_log.jsonl` 的 14 条 `retrieval_call`（**1 条 plan ＋ 13 条 shot，逐镜一条**）：

| 项 | 读数 |
|---|---|
| backend | `hypergraph`（14/14），无 `degraded` |
| 索引指纹 | `e5213e1b64781c24103eecae15a4921b5766f75c4709672fa48997de692cdf89` |
| cards / edges | 计划 8/8；逐镜 5–8 / 5–8 |
| L3 案例 | **每镜 3 条**（`case_*`，见 `retrieval_call.data.case_ids`） |
| `forbid` 成员 | 每镜 1–3 条（`forbid_members_seen == forbid_members`，没有回填） |
| 查询串 | 由 `scene_contract.shot_constraint_query()` 生产：`景别=CU；意图=铺垫；运镜=dolly_in；对白=dialogue` |

⇒ **检索与注入这一层达预期**：这是 v1.4 之前"超图那一栏在真实运行里从来没被注入过"
的反面——现在真注入、带 forbid、trace 可对拍。

## 2. 注入层：三栏**只上得去一栏**（实测数字）

提示里的知识块（`work/_rag_lanes.txt`，由 `runs/llm_trace.jsonl` 逐字统计）：

| 阶段 | 【硬约束（禁/许）】 | 【经验建议（软）】 | 【参考案例（仅参考）】 |
|---|---|---|---|
| 计划（`purpose=plan`，1 次） | **19 行 / 2627 字符** | **缺席** | **缺席** |
| 逐镜草稿（`purpose=editor`，13 次） | 6–12 行 | **只有 4/13 出现**（1–4 行） | 10–12 行（每次都到） |

根因在 `block_director/knowledge/retriever.py:856-877`：三栏**共用同一次调用、同一个
token 上限**（计划侧 `rag.plan_prefetch_tokens=2000`、逐镜 `rag.max_tokens_per_call=800`），
装配是**先到先得**（硬 → 软 → 案例 → 卡片），装不下就整条丢。硬约束栏一满，
后面的栏就没了——这不是 bug，是既有口径的**可预测后果**，但它意味着
"三栏注入"在真实数据上**退化成 1–2 栏**。

## 3. 效果层：**"禁项"与"剧本声明"打架**（这一条最要紧）

把每镜**注入过的禁项**与该镜**最终选择的机位**求交集（`work/_rag_adoption.txt`，
两侧都取自同一条 trace）：

```
13 镜全部带禁项：未违反 9　违反 4（shot_002 / 004 / 005 / 007）
```

看那 4 条"违反"是什么：

| 镜 | 剧本声明 | 注入的硬约束 | 模型选的 |
|---|---|---|---|
| 镜2 | CU ＋ dolly_in | `禁={movement:dolly_in, shot_size:CU}` | CU ＋ dolly_in（＝照剧本） |
| 镜4 | CU | `禁={shot_size:CU}` | CU（＝照剧本） |
| 镜5 | CU ＋ dolly_in | `禁={movement:dolly_in, shot_size:CU}` | CU ＋ dolly_in（＝照剧本） |
| 镜7 | CU ＋ dolly_in | `禁={movement:dolly_in, shot_size:CU}` | CU（＝照剧本） |

来源边是**条件性**的 `SHOT_PATTERN`，例：
`[SHOT_PATTERN] shot_size=MS lens=lens:50mm movement=movement:zoom_in headroom_policy=cinematic 禁={shot_size:CU}`
——它的意思是"**当 MS＋50mm＋变焦推近时**，不要用 CU"，是**条件模式的取反**。
但检索按 `景别=` 那一格命中它，渲染层又把每条边一律写成「**[必须（除非声明破例）]**」，
于是它变成了一条**无条件**禁令，正好禁掉了剧本写死的景别。模型这一轮**跟了剧本**
（R015 会因此判红的是"不照剧本办"，所以它做对了），代价是**白烧 token 与注意力**。

⇒ 这一条不达预期：**方向没错（硬约束栏确实该带 forbid），粒度错了**
（条件边被当成无条件边；被禁的那一格又恰好是检索用的那一格）。

## 4. 与 RAG 无关、但拖慢这跑的两件事（一并记）

* `draft_invalid` **4 条**：`hand_to.toward` 被模型写成 `'木围栏'` / `'camera'` /
  数组，schema 只收数字 ⇒ 重问。这是"LLM 合约"问题，不是检索问题。
* `llm_error` 1 条 ＋ `repair_failed` 1 条（shot_002 第 2 次修复），单次调用超时
  900 s 下的长尾。

## 5. 我只报读数，不提判据

判据 / 门限 / 阈值一个字节没动。可执行的下一步（**待用户拍板**）：

1. **渲染层区分**"无条件禁令"与"条件模式的取反"——后者不该写成 `[必须]`，
   而应写成 `[若 MS+lens50+zoom_in 则 禁 CU]` 或只进【经验建议（软）】栏；
2. **三栏改为按栏配额**（硬:软:案例），而不是先到先得——否则计划阶段永远只剩硬栏；
3. 把"禁项 × 最终选择"的交集做成**离线判据**（区分"剧本声明的合法破例"与"真违反"），
   替代"再跑一次模型"当证据。

**证据文件**：`work/_rag_lanes.txt`（三栏逐次统计）、`work/_rag_adoption.txt`（禁项 vs 选择）、
量具 `work/_rag_audit.py` / `work/_rag_adoption.py`（都只读产物，不调模型）。
联合会诊（两栏）另见 `docs/evidence/20261008-v10-nodes1-4-rag/panel/`（未完成时如实留 `failed`）。
