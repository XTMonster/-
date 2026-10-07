# 阶段 8 的**并行实况与独立核验**（非本卡作者视角）

**run-id**：`_v15_stage8/verify_closeout`
**作者**：一条被并行派发的执行线程（它先落了 P8-T1/T2/T4 的产物，随后发现
同一条流水线上还有兄弟 agent 在写同一批目录，于是**停手**并改做核验）。
**性质**：**核验记录**，不是新卡。不含判据改动、不含裁决。
**时间**：2026-10-07 07:53–08:10（本地时间）

---

## 0. 为什么这份文件存在（必须先读）

本次并行派发出现了**写集相交**（这正是派发板文档里点名禁止的形态），
实证如下：

| 现象 | 实测证据 |
|---|---|
| `docs/evidence/_v15_dispatch/inflight/` 在 07:52 已有 `P8-T1/T2/T4/T5/T6/T7.claim`（不是本线程写的） | 文件时间戳 |
| 本线程 07:53 又 `-Unclaim`＋`-Claim` 了同样 6 张 ⇒ **可能踩掉兄弟在飞标记** | 本线程命令记录 |
| `docs/evidence/_v15_stage8/c3_topic/` 里**同时存在两套** C3 产物（本线程的 `diagnose_topic.py`＋`README.md`＋`topic_*.json`，与 `p8t2_c3` 的 `topic_field_audit.*`＋`README_topic_field_audit.md`） | 两套文件都在，谁也没删谁 |
| `done/P8-T3.done`（07:56:32）、`P8-T9.done`（07:56:32）、`P8-T8.done`（07:56:52）**不是本线程写的** | 本线程只写了 `P8-T1`(07:55:23)、`P8-T2`(07:56:2x)、`P8-T4`(07:58:03) |
| `c2_edge_surgery/edges.json` 在 07:59:22 被**重新生成**（本线程 07:57:29 生成过） | mtime；内容确定性相同 |

> **给主线的建议**：`c3_topic/` 的两套产物**择一交付**；否则同一份证据会被数两遍。
> `tools/test` 与索引**未被任何一方改动**（见 §3）。

## 1. 逐卡核验表（08:10 时点）

| 卡 | 出处 | 产物 | 本线程独立复算 | 结论 |
|---|---|---|---|---|
| **P8-T1**（C4 记账口径） | `TECH_SOLUTIONS` §三 C4 | `tools/knowledge/attestation_ledger.py`、`tests/test_attestation_ledger.py`、`_v15_stage8/c4_ledger/**` | `python -m pytest tests/test_attestation_ledger.py -q` → **12 passed**；`python tools/knowledge/attestation_ledger.py --report …` → **exit 0**，两分母 0.2078/0.1708 | **核验通过** |
| **P8-T2**（C3 `topic` 诊断） | §三 C3 | 两套（见 §0） | 独立复算：`topic` 词表 10 值 ∩ `ALLOWED_KINDS` 30 值 = **{camera_angle, lighting}**；576 个 chunk 中**0 个**有 >1 个 `topic` | **核验通过**（两套承重结论同向） |
| **P8-T3**（C6 amended fix） | §三 C6 | `_v15_stage8/c6_layer_fix/**` | 读文件：卡文要求"改层"，实测层是**被 pin 的 gate 输入**、`fix` 是散文且数条要改 oracle 夹具 ⇒ 停手备料 | **备料成立**（属 ⚖️，见 `adjudication_c6_layer_fix.md`） |
| **P8-T4**（C2 9 边备料） | §三 C2 | `_v15_stage8/c2_edge_surgery/**` | `python …/edge_surgery.py` → 旧尺子 `mismatch 14/matches 1`、新尺子 `mismatch 6/matches 2/unknown 6/in_card_text 1`，与入库 `work/_wrong_card_full.json` **逐条一致**；`runs_pinning_index = 22` | **核验通过** |
| **P8-T5**（C5 superseded） | §三 C5 | **08:10 时点无任何产物** | —— | **未交付**（兄弟 `p8t5_c5` running） |
| **P8-T6**（A4 深度-12） | §一 A4 | **08:10 时点无任何产物** | —— | **未交付**（兄弟 `p8t6_a4` running） |
| **P8-T7**（B3 覆盖矩阵） | §二 B3 | **08:10 时点无任何产物** | —— | **未交付**（兄弟 `p8t7_b3` running） |
| **P8-T8**（G1–G9 只核不改） | §六 | `_v15_stage8/g1_g9_recheck/**`（10 条判词：open 6 / closed 4） | 抽查两条：**E2 closed 成立**（`rg -n "OPEN_PROBLEMS" AGENTS.md` **无输出**；台账里 `rg -n "⑲"` **无输出**）；**G9 closed 与代码一致**（`schema_fingerprint()` 载荷确实不含别名表，但第八格 `vocabulary_fingerprint` 由 `tools/kb_fetch/vocabulary.py::lexicon_fingerprint()` **从代码现算**，别名变更会使索引换代） | **抽查通过**（其余 8 条未逐条复算） |
| **P8-T9**（C1 三分类收口） | §三 C1 | `_v15_stage8/c1_recap/README.md` | 读文件：12 批只完成 2 批（10/90 槽位），**根因是 `GLM_API_KEY` 缺失** | **如实记"未完成"**（⚖️/阻塞） |

## 2. 本线程独立发现的**读数/口径问题**（都在本文件里给复算命令）

1. **`sample90` 的机械预读把"没有字段"读成了"不符"**：
   `docs/evidence/20261007-grounding-sample90/sample90.json` 的
   `mechanical_pre_read.topic_mismatch = 88`（分母 90）。它的判定是
   `not topic_ok and card_topics and kind not in card_topics`——而 `card_topics`
   对"来源卡没有 `topic`"记的是 **`['']`（真值）** ⇒ `kind not in ['']` 恒真。
   本线程重算（`…/c3_topic/diagnose_topic.py`）：**修正后 mismatch 65 / unknown 23 / ok 2**。
   ⇒ 那个 88 里**至少 23 行是"不知道"**，不是"主题不符"。
2. **"23 份运行 pin" 实测是 22 份**：`run_manifest.json` 全仓 **22** 份，
   每份都 `pins.index`，指纹全等于 `c796a5a8…`（`…/c2_edge_surgery/edge_surgery.py`）。
   `OPEN_ITEMS_20261007.md` 与台账里的 **23** 与实测差 1 —— **以 22 为准**，不"凑数"。
3. **C2 里 3 个槽位是"值域问题"，不是"挂错卡"**：
   `headroom_policy: cinematic`（边 `hg:3f26bdf8d230`／`hg:6d201c4c47a3`／`hg:e2ea1c270f9b`）
   的取值 `cinematic` 在**全库 2353 张卡的正文里一个字都没出现** ⇒ 按构造永远不可能被
   "正文回查"判成有依据（与 `not-checkable` 同类）。**换卡救不了，删边也不证明什么。**
4. **C3 有两套并存产物**（见 §0）：承重结论同向，唯一差别是**10 行**在
   `mismatch` 与 `unknown` 之间搬家（65/23 ↔ 55/33）。**须择一**。

## 3. 红线现场（本线程的写入面）

```
git status --porcelain -- knowledge fixtures docs/evidence/_v15_stage8
-> knowledge/ 与 fixtures 的改动**均不是本线程产生**；
   本线程只新增：docs/evidence/_v15_stage8/{c4_ledger,c3_topic,c2_edge_surgery}/**、
                 tools/knowledge/attestation_ledger.py、tests/test_attestation_ledger.py
```

* 索引 `knowledge/hypergraph.edges.jsonl` / `.nodes.jsonl` / `.manifest.json`
  **一个字节未动**（`git status` 里 `knowledge/` 无改动）。
* 未 `git add`／未 `git commit`；未跑全量 pytest（并发上限 2）；
  未 spawn 任何子 agent（PreToolUse guard 明文拒绝，本线程未绕过）。
* 静态纪律自检：`python tools/check_assertions.py` → `[OK] 扫描 306 个文件，未发现空断言`；
  `python -m pytest tests/ -q --collect-only` → 无收集错误。

## 4. 未完成 / 未核验（如实记，不许当已通过）

1. **P8-T5 / P8-T6 / P8-T7 在 08:10 时点没有任何产物** ⇒ 阶段 8 **未收口**。
2. **P8-T8 的 G1/G2/G3/G4/G6/G8 六条 open 判词**、以及 G5/G7 两条 closed 判词，
   本文件**只抽查了 E2 与 G9**，其余**未独立复算**。
3. **三张 ⚖️/用户卡全部悬空**：`P5-T2`（B1 换代窗口）、`P7-T2`（文档同步与提交）、
   `P8-T9`（C1 三分类，被 `GLM_API_KEY` 缺失阻塞）。
4. **阶段门未跑**：本版没有为阶段 8 定义 `G8` 门；若按目录纪律收口，
   应由主线在 9 张卡全 `-Mark` 后跑**全量 `python -m pytest` ＋ `tools/run_tests.ps1`
   ＋ `python tools/gen_golden.py --check`**。**本文件不是那一步的替代。**
5. `GLM_API_KEY` 在本机未设置 ⇒ 一切"GLM 交叉对拍/人工裁决"类动作**都没跑**，
   任何声称跑过的都要单独要 usage 证据。
