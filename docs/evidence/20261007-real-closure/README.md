# 第二次真跑（两栏都落地之后）：`movement` 真的在比了，生效边 **1 → 30**

日期 2026-10-07 02:35。真模型运行：`run_id 65df857a3bb5`、64 镜、`llm_calls 352`、
`retrieval_call 67`、`motions 118`、`state DONE`；`generation: gen2`。
产物：`audit_log.jsonl`／`llm_trace.jsonl`／`run_manifest.json`＋ 诊断 `execution_closure.json`。

## 一、与上一次真跑的对照（同一把尺子）

| 量 | `20261007-real-axis`（只有 axis 栏） | `20261007-real-closure`（axis ＋ camera_move） |
|---|---|---|
| `movement` 的成员三分 | `film_side_empty 294` ／ matched 5 ／ unmatched 1 | **`film_side_empty 0`** ／ **matched 268** ／ unmatched 33 |
| `edge_field_absent` | 53 | **1**（只剩 `axis_side` 那一条） |
| **`edge_active`（前提全中的边）** | **1** | **30** |
| `edge_indecidable` | 34 | 33 |
| 注入边 / 口径闭合 | 352 ✓ | 344 ✓（`33+256+0+1+30+24`） |

⇒ `declared.camera_move` 那一栏的收益**在正式读数上兑现了**：
成片侧现在有 `declared.camera_move ∈ {static 283, dolly_in 4}`，`movement` 的取值域与知识侧**重叠**
（`dolly_in`＋`static` 都出现过），**268 个成员命中、33 个不命中**，没有一个是"没得比"。

## 二、"0 违规"这一次的限定（比上一轮更紧）

* `edge_active = 30` —— 有 **30 条边的前提真的被满足了**（规则确实适用），
  但**这 30 条边里一条带 `forbid` 成员的都没有** ⇒ `forbid_members_seen = 0`、
  `judgeable_forbid_members = 0` ⇒ 违规 0 **仍然是"无物可违"**。
* 换句话说：这一次的改进是"**池子里终于有能判的边了**"，**不是**"查出/排除了违规"。
  裁定 F4 的设门条件 (a)（可判 forbid 成员 > 0）**仍是 0**。

## 三、顺带修掉**我自己工具里的一个 bug**（而且是"让报告更好看"的那一类）

`analyze()` 的 forbid 判定里，`else` 被我写成了 **`for...else`**——Python 里它属于 `for`，
循环没有 `break` ⇒ **每条生效的边都会**给 `no_match` +1，**哪怕那条边一个 forbid 成员都没有**。
实测后果：本跑一度报 `no_match 30` 而 `forbid_members_seen 0`（自相矛盾），
把"0 违规"读得比实际更干净。

修法：把 `else` 挪回 `if matched(...)` 的分支（现在是"撞不上才 +1"）；
守门 `test_no_match_counts_unmatched_forbids_not_active_edges`：
① 生效但**无 forbid 成员** ⇒ `no_match` 必须是 0；② 有一个撞不上的 forbid ⇒ 恰好 1。
修完本跑 `no_match` **归 0**、与 `forbid_members_seen 0` 一致 ✓。

## 四、全扫更新（23 次运行，含这两次真跑）

| 量 | 值 |
|---|---|
| 分析的运行 | **23**（22 次真的注入了边） |
| 违规 = 0 的运行 | **23 / 23**（按 §二 的限定读） |
| 判不了的边 | 中位数 **35.5**、最大 89 |
| 生效的边 | 中位数 7.5、**最大 30** |
| 设门条件（裁定 F4） | (a) false（可判 forbid 成员 = 0）／(b) false（生效边中位数 7.5 < 10）／(c) false（违规 max 0）⇒ **`conclusion` 仍是"判据集为空 ⇒ 回补判据，不设门"** |

## 五、未验证 / 边界

1. `axis_side` 仍是**值级部分绑定**（只绑 `neutral`），本跑 62 条 `unmatched` 是"前提不成立"
   （成片侧只有 `correct`/`crossed`，没有 `neutral`）——与上一份一致。
2. 剩下的 33 条判不了的边全部来自 `headroom_policy`／`composition_rule`／`camera_angle`
   三个 kind；它们**缺的不是区间**（见 `../20261007-uncovered-kinds-grounding/`）。
3. 两次真跑仍**不能当分布**；本目录**没有**用影子结果，也没有更新 Q5/E2 的读数。
