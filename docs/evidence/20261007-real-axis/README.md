# **落地后的第一次真跑**：轴字段生效了，轴族从"判不了"变成"能判、而且判出了结论"

日期 2026-10-07 02:1x。这一份是 **真模型运行**（不是离线、不是单测）：
`run_id c0b5300954dd`、64 镜、`llm_calls 294`、`retrieval_call 68`、`state DONE`。
逐字产物：`audit_log.jsonl`／`llm_trace.jsonl`／`run_manifest.json`（`generation: gen2`）；
诊断读数 `execution_closure.json`。（`shots.json` 按本仓惯例不进证据目录、由清单按 sha 钉住：
`work\_real_axis\export\shots.json`，`d4f08027…`。）

## 一、为什么必须**真跑**：离线通路**根本不检索**

我本想用离线跑验，结果实测：离线一次跑（64 镜）的 `audit_log` 里
**`retrieval_call` = 0 条**、`edge_ids` 一次都没出现 ⇒ **离线通路不做知识检索**。
所以"注入 → 成片"这一类读数**只能在真跑上量**。（这条本身也是个该记住的事实：
链上那份 `injection_audit.json` 读的一直是**真跑** long21，不是链里那次离线。）

## 二、字段生效的证据（对 41 分钟前刚落的 `axis` 字段）

| 量 | 落字段之前的真跑（`long21`） | 落字段之后的真跑（`20261007-real-axis`） |
|---|---|---|
| `axis_side` 在 `covered_kinds` | 不在（判不了） | **在（63 个成员）** |
| `axis_side` 的 `field_absent` | **63** | **1** |
| `axis_side` 的成员三分 | （整条边判不了） | **unmatched 62 ／ film_side_empty 1** |
| 全部 `edge_field_absent` | **112** | **53**（只剩 `movement 52` ＋ `axis_side 1`） |

⇒ **`docs/evidence/20261007-axis-field-landing/` 那个字段真的把轴族解锁了**。

## 三、解锁之后**立刻判出了一个清楚的结论**：两套词表**不相交**

```
axis_side: knowledge_values = ["neutral"]     film_values = ["correct", "crossed"]
           overlap = []   state = disjoint
```

* 本跑注入的 **63 条 `axis_side` 全是 `neutral`**；而成片侧 64 镜里
  `axis.status` 只有 **`correct` 33 ＋ `crossed` 29**（`observed_field_domain`）——
  **一次 `neutral` 都没有**（没有哪台机位正好落在轴线上）。
* ⇒ 62 条前提**不成立**（"当机位中性时…"这条规则在这部片子里**根本没被触发**），
  1 条是那镜没有 `axis` 字段。**这不是缺陷，是"规则不适用"**——但它**必须**被记成
  `unmatched`（而不是像以前那样整条边判不了），否则读者分不清"不适用"和"不知道"。
* `axis_side` 的**值级绑定**（`neutral ↔ neutral`）在本跑里**没有被行使**（0 次机会），
  所以它仍然只是一个**待验证的绑定**，不是已验证的。

## 四、这次真跑的整体读数（与本仓其它运行同口径）

| 量 | 值 |
|---|---|
| 注入边 | **352**（`edge_indecidable 34` ／ `edge_inactive 232` ／ `edge_unbound 0` ／ `edge_field_absent 53` ／ `edge_active 1` ／ 镜头没建成 32 ⇒ **口径闭合**） |
| ③ 类（故意忽略） | `pair 63`、`axis_topic 63` |
| 未纳入 | `headroom_policy 19`、`composition_rule 15`、`camera_angle 15` |
| 违规 | **0**（照 §五 的限定读：生效边 1 条、其上 `forbid` 成员 0 ⇒ **无物可违**） |
| `movement` | 仍然 **294/300 `film_side_empty`**（成片侧那两个字段基本是空的） |

## 五、未验证 / 边界

1. **两次真跑不能当"分布"**：这一份只说明"字段生效了、词表不相交"，**不**说明轴族整体的可判定性。
2. `axis_side` 的值级绑定只在**中性机位**上成立；本跑 0 次中性 ⇒ **没被行使**。
3. 这一份是**新的一代产物**（`generation: gen2`、索引指纹当前）——它可以当 Q5／E2 的新载体，
   但**本轮没有**去更新那两个指标的读数（要按代走）。
