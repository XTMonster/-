# 裁决备料 · C5：「19 份 superseded 是否让 Q1/Q2/Q4/Q6b 失据」

**run-id**：_v15_stage8/c5_superseded
**卡**：`执行文档v1.5/TECH_SOLUTIONS.md` §三 **C5**（⚖️ 本版备料；裁定已说"不能定案"）
**性质**：**机械解析 ＋ 如实记账**。不改判据、不改索引、不动任何 `run_manifest.json`。

---

## 1. 先把"superseded"变成可查的量

```powershell
python docs/evidence/_v15_stage8/c5_superseded/superseded_audit.py
```

脚本**只读**：把仓库里每份 `docs/evidence/*/run_manifest.json` 的
`pins.holdout.sha256` 拿去和**代登记表**（`fixtures/knowledge_holdout.generations.json`）
对照，解析它属于哪一代。判词由登记表推出，**不靠散文**。

**实测**：

```
current_generation = gen2
runs_with_holdout_pin = 22
by_verdict = {"不失据（pin == 现行代）": 21, "待定（异代）": 1}
```

* **21 份**运行的 `holdout` pin 全是 `e3e6bac24d9efcfe…`，在登记表里同时属于
  **gen1 与 gen2**——因为门⑦ 那次换代的机制就是"**旧夹具字节不动**、只多一个
  `inputs.third_party`"。⇒ 这 21 份的**夹具 pin 逐位命中现行代**，**不失据**。
* **1 份**：`20261003_real`，pin 的是 `78708edfc03f5510…` = **`gen0-20261003`（retired）**。
  它已经被显式登记为退休代（不是被混进 gen1）——那份运行的读数**异代**，要用就得重跑。

## 2. 与"19 份"这个数字的关系（口径，如实记）

台账 `:2079` 写的是"其余 **19 份**标 `superseded`"——那是**当年那条路线（规格一致性侧）的处置方案**：
最新一份链运行重立 pin、其余标 superseded。**裁定最终裁的是"B 的原则、A 的机制"**，
也就是**用增量层**：旧夹具字节不动 ⇒ **不需要**把那 19 份标 superseded。

⇒ 今天按登记表机械解析，得到的是 **22 份 pin / 21 份现行 / 1 份退休（gen0）**。
"19"与"22"的差不是矛盾，而是**换了机制之后的口径变化**：
现行机制下"superseded"这一档在**夹具维度上不存在**（字节没动），
只剩"**那一代的 gate 输入里有没有第三方层**"这一个真正的代差。

## 3. 逐份清单（22 行）

完整机器可读清单：本目录 `superseded_audit.json`（含每份的 `holdout_sha256_16` /
`resolved_generations` / `verdict`）。摘要：

| 判定 | 份数 | 运行 |
|---|---|---|
| **不失据**（pin == 现行代，`e3e6bac2…`） | 21 | `20261003_chunked_long{,3,6,9,10}`、`20261003_intent`、`20261003_real_{ds,glm,long}`、`20261004_chunked_long{11,12,14..20}`、`20261006-long21`、`20261007-real-{axis,closure}` |
| **待定（异代）** | 1 | `20261003_real`（pin `78708edf…` = `gen0-20261003`，**已显式登记为 retired**） |

## 4. 裁定留下的那个"不能定案"仍然挂着（不许自己定）

P14-304 逐字：**"19 份 `superseded` 是否让 Q1/Q2/Q4/Q6b 失据——裁定说 bundle 里没有判据原文、
不能定案，按份计数时标 `generation: 1`"**。

本文件**只**给出**机械可判的那一半**（pin 是否命中现行代）；
**语义那一半**（"某份运行的读数还算不算证据"）仍然**待用户裁决**——
因为判据原文不在包里，谁替它下结论都是编。

## 5. 建议（可空）

1. `20261003_real`（gen0）若要继续引用，**重跑一份**即可对齐现行代（成本 ≈ 一次链的真实运行）；
2. 其余 21 份**不必动**：它们 pin 的就是当前的夹具字节；
3. 若用户要"按份计数"的正式口径，把上面的 `generation` 字段写进 `run_manifest.json`
   的**只读报告**（不改 pin、不改夹具）——那是一次纯记账动作，可单列一卡。

## 6. 证据指针

- `docs/evidence/_v15_stage8/c5_superseded/superseded_audit.json`（22 行机器可读）
- `fixtures/knowledge_holdout.generations.json`（`current: gen2`；gen0 标 `retired`）
- `docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md:2079`（"19 份 superseded"的出处）
- 同文件 `:2104-2108`（裁定的原文：**裁 B 的原则、用 A 的机制**；19 份不得定案）
