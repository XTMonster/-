# P14 度量闭环：合并期强制 + 门⑪ 根因分类 + `<<1s` 提示缺陷

日期：2026-10-01 · run-id `20261001-0207`

本目录下两份 JSON 就是下面两条命令的**原样输出**：

```
python tools/check_holdout.py fixtures/knowledge_holdout.jsonl \
  --vocab fixtures/knowledge_holdout.vocab.json \
  --cards fixtures/knowledge_holdout.cards.json \
  --extractor-manifest knowledge/hypergraph.manifest.json \
  --out docs/evidence/20261001-0207/holdout_gates.json --json
python tools/knowledge/quality.py --run-id 20261001-0207 \
  --out docs/evidence/20261001-0207/knowledge_quality.json
```

`docs/evidence/adhoc/knowledge_quality.json` 同时用
`python tools/knowledge/quality.py --run-id adhoc` 重算过（它此前停在
`index_edges=556`，而当前索引是 579 条边，属于陈旧快照）。

## 1. 本轮修掉的三件事（都有测试兜底）

| # | 缺陷 | 落点 | 回归测试 |
|---|---|---|---|
| 1 | **合并是 oracle 的唯一入口，却只判格式**：格式对、但语义不可达（`q` 够不着自己的 `must` 边）或用了词表外取值的分片会被写进库，到收尾才由门③/门⑨ 整份判红，那时已分不清是哪一批产出的 | `tools/holdout_merge.py::merge()`（import `check_holdout.validate_entry` / `check_holdout.query_shortfall` / `holdout_fill.unknown_values_in`，**不另写第二份判据**；三类拒收**分开记账**并进报告，不静默丢弃） | `tests/test_holdout_merge.py` 新增 4 例 |
| 2 | **门⑪ 只报"未命中 68.6%"，说不出根因**，于是"标注写错取值"和"索引里根本没这条知识"混成一堆，无法处分 | `tools/check_holdout.py::_unresolved_cause()` —— **只加诊断键**（`unresolved_by_cause` / `unresolved_by_edge_type` / `unresolved_closeness`），门⑪ 的 status 判据**一处未动**，仍是规格字面的"成员集完全相等" | `tests/test_check_holdout.py` 新增 1 例 + 既有用例补断言 |
| 3 | **提示把 `<<1s` 写成了两层尖括号**（`avg_shot_len=<<1s\|1-3s\|3-8s\|>8s>`，外层是"取值表"记号，第一个取值本身就是 `<1s`），标注员逐字照抄 → 35 条 `must` 带词表外取值落盘、**从构造上**解析不到索引边 | `tools/kb_fetch/holdout_gen.py::SYSTEM_PROMPT` 改成把四个取值逐条列出并写明"第一个档位只有一个小于号" | `tests/test_knowledge_holdout.py::test_holdout_prompt_spells_inline_enum_values_verbatim`（① 模板行不许出现 `<<`；② `VALUE_DOMAINS` 里 9 个内联枚举的每个取值都要逐字出现在提示里） |

## 2. 本轮**实测**的验收状态（全部为红项，不粉饰）

门（`holdout_gates.json`）：

| 门 | status | 关键数字 |
|---|---|---|
| ① 规模 | pass | 4539 条（下界 1200） |
| ② 格式 | pass | 4539/4539 |
| ③ 词表双向覆盖 | **fail** | `missing_values`：`movement=["固定"]`、`lens=["10mm","135mm"]`；`unknown_values`：`sfx=["心跳","金属撞击"]`、`movement=["pan_right"]` |
| ④ 边类覆盖 | pass | — |
| ⑤ / ⑤b forbid | pass | 429 冲突 / 64 成员 |
| ⑥ 来源覆盖 | **fail** | 1733 张卡里 **687 张没有条目**；**29 条条目引用了已不存在的卡 id** |
| ⑦ 人审 | **fail** | **0/120**（agent 不可替代） |
| ⑧ 抽取/标注独立性 | pass | deepseek / zhipu |
| ⑨ 可达性 | **fail** | **970/4539 = 21.4%** |
| ⑩ 索引可解析 | **fail** | **9405/13713 = 68.6%** 未命中 |

门⑩ 的根因分布（`_unresolved_cause`，**诊断量，不改判据**）：

| 根因 | 条数 |
|---|---:|
| `no_edge_with_those_plain_members`（同类边在，但没有一条覆盖全部 plain 成员） | 8151 |
| `plain_subset_but_forbid_differs`（边在，只差 `forbid` 集） | 685 |
| `plain_subset_index_has_extra_members`（边在，索引那条多带了成员） | 534 |
| `value_not_in_index`（取值不在索引节点里 —— 本轮已把提示侧的成因修掉） | 35 |
| `no_edge_of_type` | 0 |

指标（`knowledge_quality.json`）：`overall=fail`

| 指标 | 值 | 线 | 判 |
|---|---|---|---|
| Q0 构建门 | rejects 0 / processed 184 = total 184 | — | pass |
| Q1 | 765/4539 = **0.169** | 0.70 | fail |
| Q2 | 1153/4539 = **0.254** | 0.90 | fail |
| Q3 | 23/1291 = 0.018 | 0.10 | pass |
| Q4 | 1154/1563 = **0.738** | 1.00 | fail |
| Q6a | 13536/13536 = 1.0 | 1.00 | pass |
| Q6b | 1232/1563 = **0.788** | 1.00 | fail |
| Q7 | 249/249 = 1.0 | — | pass |
| **Q4 前置①** | **3480/5043 条 `must` 在索引里找不到对应边** | 0 | fail（§2.3 "索引构建失败"） |
| E1 / E2 | — | — | not_measured（需人工打分 / 需真实运行的 `shots.json`） |
| E3 / E3_cases | 0 | 0 | pass |

## 3. 门③/⑥ 为什么现在红（与门⑩ 是**两件事**）

门③ 与门⑥ 在 `docs/evidence/20261001-011631/` 还是绿的，在
`20261001-013501/` 之后转红 —— 分界点是**语料从 1075 张长到 1733 张**：

- 门⑥：`fixtures/knowledge_holdout.cards.json` 已经是 1733 张的当前快照
  （与 `block_director.knowledge.corpus.CARDS` 逐条一致），而 oracle 仍只覆盖
  旧的 1075 张 → 687 张新卡零条目、29 条条目引用已被改名/删除的旧 id。
- 门③：`fixtures/knowledge_holdout.vocab.json` 与 oracle 都是旧世代快照，
  索引长出新取值（`sfx=心跳` 等）后双向覆盖就对不上了。

**结论**：这两道门不需要改判据，需要的是**用当前语料重标一次 oracle**
（`holdout/v12` 提示 + 重建词表快照），这正是并行 lane 正在做的事。

## 4. 仍然需要用户裁决的一项（本 lane 不自行选择）

门⑩ 的判据来自 §2.3 Q6b 前置①（`norm_key(索引边) == norm_key(标注边)`，
`norm_key` **含完整成员集**），而 §2.3c 同时写死"标注方不可见索引"。
实测各档口径的可达上限（同一 fixture、同一索引，只换"命中"的定义）：

| 口径 | 命中/总数 | 比例 |
|---|---:|---:|
| A 现行（成员集完全相等） | 4308/13713 | 31.4% |
| B 标注成员 ⊆ 某条同类索引边且 `forbid` 相等 | 4842/13713 | 35.3% |
| C 同 B，`forbid` 不参与比较 | 5527/13713 | 40.3% |
| D 只要求"取值都在索引里且同类边存在" | 13678/13713 | 99.7% |

三档的取舍、以及"保持 A 就意味着 RK-13 在可预见未来不可能通过"的论证见
`docs/evidence/20261001-0159/gate10_rootcause.md` §5。**在用户拍板前，门⑩ 保持红、
RK-13 保持 fail、本 lane 不调 `SCORE_WEIGHTS`、不动门限。**

## 5. 明确不做

- 不为了变绿改 `must`/`top1`/`never`，不用脚本机械补 `q`（§4.1b 硬规则②）。
- 不删测试、不跳过测试、不改断言、不 `try/except` 吞错。
- 不把门⑦ 写成通过（人审 agent 不可替代），一律 `fail` 并单独报告。
- 不降 Q1/Q2/Q4/Q6b/Q7 的任何线，不动 §4.1b 的分母下界。
