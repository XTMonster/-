# 裁决备料 · B3：`APPLICABILITY_SEMANTICS_v1` 提案 ×「判不了」的边（覆盖矩阵）

**run-id**：_v15_stage8/b3_coverage
**卡**：`执行文档v1.5/TECH_SOLUTIONS.md` §二 **B3**（⚖️ 须裁决，本版只备料）
**性质**：**只出对照**。不改判据、不设门、**一个字都不改** `APPLICABILITY_SEMANTICS_v1.md`
与索引（红线 R-5/R-8）。

---

## 1. 先把"判不了"的边复现出来（可复算）

```powershell
python docs/evidence/_v15_stage8/b3_coverage/undecidable_edges.py `
  --run docs/evidence/20261006-long21 `
  --out docs/evidence/_v15_stage8/b3_coverage/undecidable_edges.json
```

脚本**导入** `tools/knowledge/execution_closure_report.py` 的 `MAPPING` /
`NOT_A_CONDITION`（**单一真源，不抄第二份**），按同一规则走该次运行的 `audit_log.jsonl`。

**实测（long21 这一跑）**：

```
distinct undecidable edges = 8
injection occurrences      = 32        （与工具 counts.edge_indecidable 一致）
unmapped member slots      = 13
unmapped kinds             = {headroom_policy, composition_rule, camera_angle}
mapped kinds（今天能判的）  = action, axis_side, intent, lens, movement, shot_size, transition, vfx
not-a-condition（不该判的）= axis_topic, pair
```

> **口径注**：卡文写"剩余 **33** 条判不了的边"，本次实测是 **32 次注入出现 / 8 条不同的边**。
> 差 1 的来源是**运行口径**（33 出自另一次全扫/另一跑），**以本次实测为准**并如实记差；
> 更关键的是"**条**"这个词在这里有两种量纲：**出现次数**（32）与**不同边**（8）——
> 讨论"要不要改索引"时必须用**不同边**（8），讨论"真实运行里判不了多少次"时才用出现次数。

## 2. 逐边覆盖矩阵（8 行）

| # | edge_id | 类型 | 不可用 kind | 提案归类 | 提案**覆盖？** | 落地前置（须用户拍板） |
|---|---|---|---|---|---|---|
| 1 | `hg:3f26bdf8d230` | `SHOT_PATTERN` | `headroom_policy` | §二 **②**（成片无对应字段） | ✅ 覆盖（归②） | ②类要么"**扩范围**"（先加字段并让生成器填）、要么**显式写"不校验"** |
| 2 | `hg:6d201c4c47a3` | `SHOT_PATTERN` | `headroom_policy` | §二 **②** | ✅ 覆盖（归②） | 同上 |
| 3 | `hg:e2ea1c270f9b` | `SHOT_PATTERN` | `headroom_policy` | §二 **②** | ✅ 覆盖（归②） | 同上 |
| 4 | `hg:400a2bfcda8e` | `STAGING_PACK` | `camera_angle`, `composition_rule` | §二 **①**（阈值/区间型） | ✅ 覆盖（归①） | `composition_rule`→构图分需**阈值**、`camera_angle`→由机位反推需定**相等还是区间**；**定阈值＝新判据** |
| 5 | `hg:5b8b86de2d87` | `STAGING_PACK` | `camera_angle`, `composition_rule` | §二 **①** | ✅ 覆盖（归①） | 同上 |
| 6 | `hg:d090d7ce0096` | `STAGING_PACK` | `camera_angle`, `composition_rule` | §二 **①** | ✅ 覆盖（归①） | 同上 |
| 7 | `hg:d28d18bfdde4` | `STAGING_PACK` | `camera_angle`, `composition_rule` | §二 **①** | ✅ 覆盖（归①） | 同上 |
| 8 | `hg:e3ee2d0b5f4c` | `STAGING_PACK` | `camera_angle`, `composition_rule` | §二 **①** | ✅ 覆盖（归①） | 同上 |

**统计**：提案**覆盖 8/8**（分类层面）；**可直接落地 0/8**（每一行都卡在"须用户拍板"的那一步）。

## 3. 按 kind 汇总（3 行）

| kind | 提案归类 | 提案要求你决定什么 | 本次实测出现次数 |
|---|---|---|---|
| `headroom_policy` | ② 成片无对应字段 | 扩范围（加字段）还是**显式"不校验"** | 22 |
| `composition_rule` | ① 阈值型（构图分） | **阈值定多少**（定阈值＝新判据） | 13 |
| `camera_angle` | ① 由 `camera.position/target` 反推 | 用**相等**还是**区间**，区间边界是什么 | 13 |

## 4. 提案自己列的三件必拍板项（原文 §三，逐字）

1. **②那批要不要扩范围？** 要校验情绪/节奏/桥段类型，就得先在成片侧**加字段**并让生成器填它
   ——那是**新功能**，不是修洞。若不打算做，请在提案里明确写"**不校验**"，
   而不是让它永远是"未定义"。
2. **①里的"区间/阈值"型（`pacing`/`composition_rule`/`camera_angle`）判据怎么定？**
   相等式判定对它们没有意义；**一旦定阈值，就是新的判据**——按本仓纪律须你明示批准。
3. **报出来的数拿去干什么？** 先做**诊断**（不设门、只进证据目录）还是直接**设门/R0xx**？
   提案建议先诊断。

## 5. 本卡没有做的事（如实记）

* **没有实施提案**（`APPLICABILITY_SEMANTICS_v1.md` 仍是"提案，未实施"，字节未动）；
* **没有设门、没有改判据、没有改索引**；
* **没有替用户选**（§三的三件全部列成待裁决项）。

## 6. 与 C2 的关系（两张卡的分工）

`C2` 管的是"**槽位挂错卡**"（换卡 vs 删边 ⇒ 索引换代）；
`B3` 管的是"**这些边为什么判不了**"（缺适用域语义 ⇒ 加语义表）。
同一批边在两张卡里是**两种不同的问题**，**不要合并结论**：
换卡救不了"语义没定义"，加语义表也不修"挂错卡"。

## 7. 证据指针

- `docs/evidence/_v15_stage8/b3_coverage/undecidable_edges.json`（逐边清单，机器可读）
- `docs/evidence/_v15_stage8/b3_coverage/undecidable_edges.py`（复算脚本，**导入**工具的映射表）
- `docs/knowledge/APPLICABILITY_SEMANTICS_v1.md`（提案全文 §二/§三/§五）
- `tools/knowledge/execution_closure_report.py`（`MAPPING`/`NOT_A_CONDITION` 的单一真源）
