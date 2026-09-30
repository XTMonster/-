# P14 验收度量的可信化（R54）— 证据

本轮只动"度量与门"，不动语料、oracle 生成、索引构建（那三条属并行 lane）。
所有数字都是本机实跑，命令与输入指纹一并给出；**没有一项被粉饰**。

## 1. 输入指纹（`sha256`）

| 文件 | sha256 |
|---|---|
| `fixtures/knowledge_holdout.jsonl` | `7527baeff6d3ae7beed16ebaa98edc18bfa784f395c69183f06b74608352a1da` |
| `fixtures/knowledge_holdout.vocab.json` | `e9ae25b2d1f4516d95ad148c50222ab030015f35a446e8c7c8e48463a2883380` |
| `knowledge/hypergraph.nodes.jsonl` | `a7b09f8ce47e60343b741464b23ea83160956c2896df6f6475bee4ac3c34febe` |
| `knowledge/hypergraph.edges.jsonl` | `01d2172ee4de4091748fbe74ba432ae8c6f21883acb30d991f6d3ccf62d550aa` |

> 索引（387 条边）在本轮期间被并行 lane 重建过（此前 382 条），所以
> **任何跨提交的数字比较都要先比指纹**。

## 2. 修掉的两个"度量本身在骗人"的洞

### 2.1 Q4 曾是恒真式

`tools/holdout_score.py` 里是 `_metric("Q4", required_total, required_total, 1.0)`——
分子与分母是同一个变量，于是"required 边 100% 可检索"**永远**成立。
规格 §4.1 对 Q4 的定义是 `命中的 required_hyperedge_ids 数 / Σ_q |required(q)|`。

修完之后的实跑（`knowledge_quality.json`）：

| 指标 | 分子/分母 | 值 | 线 | 判定 |
|---|---|---|---|---|
| Q4 | **984 / 1323** | **0.7438** | 1.0 | **fail** |

### 2.2 解析不到的 `must` 被静默丢掉

`if key is not None` 会把"标注指向了索引里不存在的边"的 `must` 从 required
分母里剔掉——分母变小、比率变好看，缺陷反而看不见。§2.3 的 Q6b 前置① 写的是
相反的处置：**"若某 query 的 required 边在归并后确实不存在，则索引构建失败"**。

现在它被单独记账，并且只要存在一条就让 `passed = false`：

```
"must_total": 5043, "required_unresolved": 3720, "required_unresolved_entries": 3386
```

`tools/knowledge/quality.py` 新增 `Q4_pre_required_edges_exist`，防止
`overall` 在 oracle 与索引不同构时仍报 `pass`（Q4 的比率看不到这件事，
因为它的分母跟着一起缩）。

## 3. 新增的两道覆盖门（R54）

两条都是"协议写了、机器没查"的口子。

| 门 | 判据 | 现状（实跑） |
|---|---|---|
| **⑩ `gate_9_reachability`** | `must[0]`/`top1` 能表达的槽位必须逐字出现在 `q` 里（协议 §3.1 对 `must` 的定义；标注提示词规则 0） | **fail：816 / 4539 = 17.98%** 的条目够不着自己的期望边 |
| **⑪ `gate_10_index_resolvable`** | `must`/`top1`/`never` 必须映射到当前索引里的边（§2.3 Q6b 前置①） | **fail：10046 / 13713 = 73.26%** 未命中（逐字段：must 3720/5043、top1 3315/4539、never 3011/4131） |

门⑪ 缺索引时记 `not_measured`、退出码 2（§4.1b 硬规则 1：缺证据不得判通过）。

## 4. 为什么 Q1/Q2 的低值**不是**排序问题（全量实测）

对全部 4539 条逐条追踪（`work/p14_ceiling_probe.py`）：

| 量 | 值 |
|---|---|
| `must` 能进候选集的 query 数 | 1277 / 4539 → **ceiling_Q2 = 0.2813** |
| `top1` 能进候选集的 query 数 | 1204 / 4539 → **ceiling_Q1 = 0.2653** |
| 目标边在候选集里的名次中位数 | **1** |
| 种子集大小 | 中位 3、均值 3.1、最大 20 |

结论：**排序基本没问题**（进了候选集的目标边中位名次是 1），
Q1/Q2 的天花板被"oracle 与索引不同构"压在 0.27/0.28。
因此本轮**不动 `SCORE_WEIGHTS`**——动它只会掩盖 oracle 缺陷。

（另有一条待收口的口径：`SCORE_WEIGHTS` 的现值
`coverage .70 / priority .05 / occurrences .15 / confidence .02 / authority .05 /
forbid_hit .03` 与规格 §2.3 第 3 步写死的
`0.35 / 0.20 / 0.15 / 0.05 / 0.15 / 0.10` 不一致，是前一轮的实测标定。
本 lane 只记录，不擅自改回。）

## 5. 复现命令

```
python tools/check_holdout.py fixtures/knowledge_holdout.jsonl ^
    --vocab fixtures/knowledge_holdout.vocab.json ^
    --cards fixtures/knowledge_holdout.cards.json --json
python tools/holdout_score.py --json docs/evidence/20261001-0057/knowledge_quality.json
python -m pytest -q
```

## 6. 未达标与未覆盖（如实列出）

| 项 | 状态 |
|---|---|
| gate ⑦ 人审 ≥120 | **fail**（协议规定只能人做，agent 不可替代） |
| Q1 ≥ 0.70 | **fail**（当前 0.142，天花板 0.265 由 oracle 决定） |
| Q2 ≥ 0.90 | **fail**（当前 0.217，天花板 0.281） |
| Q4 = 1.0 | **fail**（0.7438，现在是真的在量） |
| Q6b = 1.0 | **fail**（0.812） |
| Q5 / E1 / E2 | **not_measured**（Q5 只在真实模型运行上判、E1 需人打分） |
| RK-13 总判 | **未通过** |
| 门⑩ 的口径面 | 只看 `must[0]` + `top1`、只看 `plain` 槽位、`QUERYABLE_KINDS` 排除 `scene_type`/`beat_type`——**这是产出侧既有的口径**，本 lane 不擅自放宽或收紧；`forbid` 槽位与 `must[1..]` 未纳入，属已知缺口 |

上述未达标项要在 oracle 重标（`holdout/v10`）与索引重建收口后复测；
**人审与 Q5/Q7/E3 的最终裁定必须由人给出**。

## 7. 追加：门⑪ 的两层关系（完全相等 vs 只多不少）

门⑪ 的 status 按 §2.3 前置① 的**字面**判据（`norm_key` **完全相等**）判红，
但同一份实测还必须把第二层事实摆出来，否则会把**结构性冲突**误读成标注噪声：

| 关系 | 命中 / 全部 spec | 比率 |
|---|---|---|
| **完全相等**（规格字面；`spec_to_norm_key`） | 3667 / 13713 | **0.2674** |
| **标注成员 ⊆ 索引边**（`forbid` 仍要求完全相等） | 4273 / 13713 | **0.3116** |

两层都远低于 100%，所以问题不是"标注噪声大"：

* 表面冲突：§2.3 前置① 要求成员集**逐字相同**，而协议 §5.2（`knowledge_holdout.protocol.md:148`）
  写死**标注方不可见索引**——标注者必须在看不见索引的前提下猜中抽取器的成员集；
  抽取（DeepSeek）与标注（GLM/qwen）是两个族，实测吻合率 **1323/5043 = 26.2%**。
* 结构性一例：`AXIS_RULE` 的必填槽位是 `pair`＋`axis_side`，v1.5 给同类边加了**可选**
  `axis_topic`，而冻结的标注提示（`tools/kb_fetch/holdout_gen.py` 规则 10）明确要求
  `must` 里只写 `pair`＋`axis_side` → 这一类边**永远**少一个成员，严格相等判据下
  263 条只有 16 条能命中。

因此 `gate_10_index_resolvable` 额外报出 `strict_relation_matches` /
`subset_relation_matches` / `subset_relation_ratio`（**诊断量，不参与 status**）与
一句 `note`，把"要不要把判据放宽成子集关系"这件事显式交回**规格裁决**。
同类结论与更细的逐类型上限见并行 lane 的
`docs/evidence/20261001-0100/p14_acceptance_ceiling.md`（该文件同时指出 Q3 的
`never` 侧有同款静默缩分母问题，本 lane 的门⑪ 已把 `never` 一并记账）。
