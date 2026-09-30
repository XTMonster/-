# 门⑪（`gate_10_index_resolvable`）未命中的根因分类与规格级裁决请求

日期：2026-10-01 · run-id `20261001-0159`
产出：`holdout_gates.json`（`tools/check_holdout.py --out`）、
`knowledge_quality.json`（`tools/holdout_score.py --json`）。

复现命令（本目录下两份 JSON 就是这两条命令的原样输出）：

```
python tools/check_holdout.py fixtures/knowledge_holdout.jsonl \
  --vocab fixtures/knowledge_holdout.vocab.json \
  --cards fixtures/knowledge_holdout.cards.json \
  --extractor-manifest knowledge/hypergraph.manifest.json \
  --out docs/evidence/20261001-0159/holdout_gates.json --json
python tools/holdout_score.py --json docs/evidence/20261001-0159/knowledge_quality.json
```

## 1. 结论

`gate_10_index_resolvable` **现在红的是 9405/13713 条 spec（68.6%）**，
而且它红的原因**不是**"检索器不行"、也**不是**"标注噪声大"，而是
**规格在两条互相矛盾的要求上把这条门写成了构造上不可达**：

* §2.3 Q6b 前置①（`改进执行文档v1.4.md`）要求
  `norm_key(索引边) == norm_key(标注边)`，而 `norm_key` 的定义里**包含完整成员集**
  （`tools/holdout_score.py::norm_key` → `(type, frozenset((role, kind, node_id)))`）；
* §2.3c 的标注通道第 2 条同时写死"**标注方不可见索引**：只能拿到语料、schema、本协议"。

不看索引就要求逐字命中索引那条边的**完整**成员集，只有"索引每条边都恰好是标注者
会写的那一组"才可能成立。实测吻合 4308/13713 = **31.4%**，且**不是排序问题**：
同一批 query 在候选集内的目标边名次中位数 = 1（见
`docs/evidence/20261001-0057/measurement_integrity.md`）。

## 2. 证据：把"68.6% 未命中"按根因拆开

新增的诊断（`tools/check_holdout.py::_unresolved_cause`）把每条未命中的 spec
归到下面四类之一。**它只加诊断键，不改门⑪的判据**（status 仍是规格字面的
「成员集完全相等」）。

| 根因 | 条数 | 含义 | 能被谁修 |
|---|---:|---|---|
| `value_not_in_index` | **35** | spec 里的 `kind=取值` 在索引节点里不存在 | 标注侧（改提示／重标） |
| `no_edge_of_type` | **0** | 同类边一条都没有 | — |
| `plain_subset_index_has_extra_members` | **534** | 边在，索引那条边**多带了成员** | 规格裁决 |
| `plain_subset_but_forbid_differs` | **685** | 边在，只有 `forbid` 集不同 | 规格裁决 |
| `no_edge_with_those_plain_members` | **8151** | 同类边在，但没有任何一条覆盖全部 `plain` 成员 | 重抽取／补语料（或规格裁决） |

`unresolved_closeness`（未命中 spec 被**最好那条同类边**覆盖了几个 `plain` 成员）：

| 覆盖了 k/n 个 plain 成员 | 条数 |
|---|---:|
| 2 | 5534 |
| 1 | 3053 |
| 3 | 600 |
| 0 | 210 |
| 4 | 8 |

**读法**：最大的一堆是"只差一个成员"（覆盖 2/3 有 4239 条）。
也就是说索引**已经很接近**标注者的期望，差的是"标注者写 `（意图收束 × MCU × crane_down）`
而索引只抽到 `（意图收束 × MCU × 其它运镜）`"这种组合差——这是**组合空间**的必然结果，
不是噪声。

按边类型看未命中：`INTENT_PACK` 1713、`SHOT_PATTERN` 1211、`EMOTION_PACK` 1210、
`STAGING_PACK` 875、`ACTION_BEAT` 853、`PERFORMANCE_PACK` 835、`IMPACT_PACK` 694、
`AXIS_RULE` 574、`TROPE` 425、`SOUND_PACK` 324、`LIGHT_PACK` 320、
`TRANSITION_PACK` 306、`EDIT_RHYTHM` 65。

## 3. 本轮已经修掉的那 35 条（真实缺陷，不是口径问题）

`tools/kb_fetch/holdout_gen.py` 的 `EDIT_RHYTHM` 模板原来写成

```
avg_shot_len=<<1s|1-3s|3-8s|>8s>
```

外层 `<>` 是"取值表"的记号，而第一个取值**本身就是 `<1s`**，两层叠出 `<<1s`。
标注员逐字照抄，于是 35 条 `must/top1/never` 带着词表里不存在的
`avg_shot_len=<<1s` 落盘。实测 `_node_id_for(graph,'avg_shot_len','<1s')`
返回 `avg_shot_len:<1s`，而 `'<<1s'` 返回空 → 这 35 条从构造上就解析不到索引边。

已修：模板改成把四个取值**逐条列出来**并写明"第一个档位只有一个小于号"。
回归测试：`tests/test_knowledge_holdout.py::test_holdout_prompt_spells_inline_enum_values_verbatim`
（① 模板行里不许出现 `<<`；② `VALUE_DOMAINS` 里内联写死的 9 个枚举，每个取值都得逐字在提示里）。

## 4. 各档口径的可达上限（供裁决，不是提议降线）

同一份 fixture、同一个索引，只换"命中"的定义：

| 口径 | 命中 / 总数 | 比例 |
|---|---:|---:|
| A. 现行（规格字面）：成员集**完全相等** | 4308 / 13713 | **31.4%** |
| B. 标注成员 ⊆ 某条同类索引边，且 `forbid` 集相等 | 4842 / 13713 | **35.3%** |
| C. 同 B，但 `forbid` 集不参与比较 | 5527 / 13713 | **40.3%** |
| D. 只要求"取值都在索引里、且同类边存在"（不做成员集比较） | 13678 / 13713 | **99.7%** |

## 5. 裁决请求（三条路，互斥）

1. **保持 A（现行）** —— 那么 `RK-13` 在可预见的未来不可能通过：这条门要求
   "看不见索引的标注者逐字猜中抽取器的成员集"，而实测上限 31.4%。
   要继续走这条路，唯一的正当动作是**把索引抽成"每张卡恰好一条、且成员集就是
   该卡全部可写成员"的形态**，并把标注提示改成"只准抄这张卡自己那一组"——
   那等于取消标注者与抽取器之间的独立性（§2.3c 第 2 条），需要用户明确许可。
2. **改成 B 或 C** —— 把门⑪ 的判据从"成员集完全相等"改成"标注成员 ⊆ 索引边"。
   它仍然是**可失败**的门（现在就有 8871/13713 条不满足），仍然能抓出
   "索引里没有这条知识"；它只是不再要求"逐字猜中可选成员"。
   改动点：`tools/check_holdout.py::gate_index_resolvable` 与 `tools/holdout_score.py::spec_to_norm_key`。
3. **改成 D，并把"值域合法性"做成独立门** —— 只查"用例里的取值都在冻结词表里、
   同类边存在"。这条最松，但配 `gate_3_seed_coverage`／`gate_4_edge_types`
   仍然不是空转；代价是 Q6b 前置① 原有的"索引构建失败要当场暴露"这一层变弱。

**我不自行选择任何一档**：改门⑪ 的判据就是改验收口径（§4.1b 硬规则②的精神），
必须由用户拍板。在这之前，门⑪ 保持**红**，`RK-13` 保持 **fail**，
`AGENTS.md` 的"P14 未完成"一节保持原样。

## 6. 明确不做

- 不把门⑪ 写成 `not_measured`、不调低任何门限、不删任何断言。
- 不为了变绿去改标注文件里已有的 `must`／`top1`／`never`（那正是"改判据"）。
- 不用"机械补 q"绕过门⑨：`q` 是独立标注者的判断，由脚本改写等于自证
  （§4.1b 硬规则②）。门⑨ 的正解是**用 `holdout/v12` 提示重标**，
  见 `AGENTS.md` 的 P14 待办。
