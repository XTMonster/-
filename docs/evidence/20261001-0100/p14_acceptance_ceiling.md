# RK-13 的 Q1/Q2/Q4/Q6b：**上限**低于验收线，先修 oracle／索引，不是先调检索

度量时间：2026-10-01 01:00（Asia/Shanghai）。
被测树：`f57f3df`（`tools/holdout_score.py` 的 Q4 真实口径 + required 边不可解析记账）
+ 当时工作区（`tools/check_holdout.py` 的门⑨/门⑩ 尚未提交，但它不影响本表的上限算术）。
数据：`fixtures/knowledge_holdout.jsonl` **4539 条 / 5043 条 `must`**；
索引 `knowledge/hypergraph.{nodes,edges}.jsonl` = 307 节点 / **387 边**。

## 0. 一句话结论

把排序换成**永远猜对的神谕排序器**，Q1 最高 **0.2653**、Q2 最高 **0.2813**、
Q4/Q6b 最高 **0.2623** —— 四条线（0.70 / 0.90 / 1.0 / 1.0）**全都不可达**。
因此当前的 Q1≈0.14、Q2≈0.22 里，**绝大部分不是检索排序的损失，而是 oracle 与索引
不同构**（§2.3 的 Q6b 前置①把这种情形直接定义为"索引构建失败"）。

## 1. 复现命令

```powershell
python tools/knowledge/holdout_ceiling.py --json docs/evidence/20261001-0100/p14_acceptance_ceiling.json
python tools/holdout_score.py --holdout fixtures/knowledge_holdout.jsonl
python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab fixtures/knowledge_holdout.vocab.json --cards fixtures/knowledge_holdout.cards.json
```

## 2. 上限表（`p14_acceptance_ceiling.json`）

| 指标 | 上限（神谕排序） | 验收线 | 判定 |
|---|---|---|---|
| Q1 top-1 | **0.2653**（1204 / 4539） | ≥ 0.70 | **不可达** |
| Q2 top-3 | **0.2813**（1277 / 4539） | ≥ 0.90 | **不可达** |
| Q4 required 可检索 | **0.2623**（1323 / 5043） | = 1.00 | **不可达** |
| Q6b 注入完整 | **0.2623**（1323 / 5043） | = 1.00 | **不可达** |

`seed_miss_queries = 0`：没有一条查询是"种子一个都命中不了"，所以上限不是被种子面卡住的。

## 3. 上限被谁吃掉：按边类型的 `must` 供需

`p14_acceptance_ceiling.json` 的 `must_per_type`（`demanded` = 标注要求数，
`resolvable` = 索引里真的找得到的那条边，`absent` = 索引里**没有**）：

| 边类型 | 索引边数 | demanded | resolvable | absent |
|---|---|---|---|---|
| ACTION_BEAT | 97 | 308 | 57 | 251 |
| AXIS_RULE | 16 | 263 | 16 | 247 |
| EDIT_RHYTHM | 17 | 316 | 300 | 16 |
| EMOTION_PACK | 41 | 771 | 207 | 564 |
| IMPACT_PACK | 6 | 256 | **0** | 256 |
| INTENT_PACK | 8 | 679 | 33 | 646 |
| LIGHT_PACK | 21 | 364 | 300 | 64 |
| PERFORMANCE_PACK | 97 | 328 | **0** | 328 |
| SHOT_PATTERN | 40 | 569 | 132 | 437 |
| SOUND_PACK | 2 | 240 | **0** | 240 |
| STAGING_PACK | 27 | 493 | 176 | 317 |
| TRANSITION_PACK | 13 | 212 | 66 | 146 |
| TROPE | 2 | 244 | 36 | 208 |

三类边（`IMPACT_PACK` / `PERFORMANCE_PACK` / `SOUND_PACK`）**一条都对不上**：
索引里分别只有 6 / 97 / 2 条边，而标注要求 256 / 328 / 240 条不同的槽位组合。

## 4. 排序侧还剩多少（可改进空间）

只看**能解析上**的 1323 条 required 边（`tools/holdout_score.py` 的同一套解析）：

| 去向 | 条数 |
|---|---|
| 进了 top-3 | 984 |
| 进了候选集但被挤出 top-3 | **313** |
| 两跳扩展都没进候选集 | 26 |

对这 313 条逐条比对"胜者"和"标注边"**各自覆盖了查询里多少个 kind**：

| 情形 | 条数 |
|---|---|
| 胜者覆盖**更多**查询 kind（排序没错） | 18 |
| 胜者覆盖**一样多**（查询本身分不出胜负） | **290** |
| 胜者覆盖更少（真正的排序缺陷） | 5 |

也就是说 **308 / 313 = 98.4%** 的"掉出 top-3"是**查询本身无法分辨**的平局：
标注者的 `top1` 来自它的**来源卡**，而不是从 `q` 推出来的。例：

```
hq_0007  q = "轴线=运动轴；光线=逆光"
         top1 = LIGHT_PACK:lighting=逆光,intensity=high
         rank1 = AXIS_RULE(pair=any_two,axis_side=neutral,axis_topic=…运动轴…)
```

两条边都只覆盖查询里的 1 个 kind，`TYPE_PRIORITY` 把 `AXIS_RULE`(1.0) 排在
`LIGHT_PACK`(0.8) 前面 —— **任何只看 `q` 的排序器都无法知道标注者想要哪一条**。

同样地，984 条进了 top-3 的 required 边里有 **322 条不是第 1 名**（`rank_of_must`
中位数 = 1 掩盖了这个长尾），Q1 因此再丢一截。

把同一判据推广到**全体** 1204 条"top-1 边能进候选集"的 query：其中 **1201 条**
（`top1_ambiguous`）的期望边在候选集里**存在另一条 `q` 覆盖数不更少的边**——
也就是说 `q` 单独无法把期望边挑出来。只用这一条信号排序得到的是
`qonly_ranking_floor_Q1 = 0.0007`（**下限**，因为 `occurrences`／`authority` 这类与
查询无关的量实际会"碰对"一部分：实测 Q1 = 0.1417 > 0.0007）。
`ceiling(Q1) = 0.2653` 仍是**上界**——进不了候选集的边永远排不到第一。
两个数都要连着看：上界说"排序最好也就到 0.27"，下限说"只靠 `q` 认边几乎无从下手"。

## 5. 一条结构性冲突：`AXIS_RULE` 的 `norm_key` 恒不相等

`AXIS_RULE` 的必填槽位只有 `pair` + `axis_side`（`hypergraph.REQUIRED_MEMBERS`），
而 v1.5 为了让这类边能被查询锚住，给它加了**可选** `axis_topic`
（`hypergraph.OPTIONAL_MEMBERS[AXIS_RULE]`）。
冻结的标注提示又明确要求"`pair` 与 `axis_side` 都写在 `must` 里，`q` 里只写
`轴线=<取值>`"（`tools/kb_fetch/holdout_gen.py` 的 SYSTEM_PROMPT 规则 10）。
于是标注侧写出的成员集**永远**比索引边少一个 `axis_topic`：

| `AXIS_RULE` | demanded | norm_key 精确相等 | 仅要求"标注 ⊆ 索引" |
|---|---|---|---|
| 条数 | 263 | **16** | 200 |

这不是数据噪声，是**协议与 schema 的结构性冲突**；§2.3 前置①按字面实现时，
这一整类边都不可能过门。

## 5b. 更根本的一层：门① 的判据与"标注方不可见"互斥

规格 §2.3 的 Q6b 前置①（`改进执行文档v1.4.md:849-854`）要求
`∀q, ∀required: ∃ 抽出的边 满足 norm_key(该边) == norm_key(标注边)`，
而 `norm_key = (type, frozenset((role, kind, node_id)))` **含完整成员集**；
`fixtures/knowledge_holdout.protocol.md:148` 同时写死**标注方不可见**——
"标注方只能拿到语料、schema、本协议；不得拿 index、`knowledge_trace.json`、
检索器、抽取 prompt"。

两条放在一起：标注者必须在**看不见索引**的前提下，把成员集**猜到与抽取器逐字相同**。
抽取由 DeepSeek（`knowledge/hypergraph.manifest.json` 的 `extractor.family = deepseek`）、
标注由 GLM/qwen（`annotator.family = zhipu`/`qwen`）独立完成，实测吻合率 **1323/5043 = 26.2%**。
也就是说门① 按字面**在构造上不可能通过**，除非：

* 判据改成"**标注 ⊆ 索引**"（对 `allow`/`qualifier` 成员），而 `forbid` 成员仍要求**完全相等**
  （Q6b/Q7 要按标注的 forbid 逐条对拍注入文本，这里不能松）；或
* 两侧都只允许写该边类型的**必填槽位**（但那会把 `forbid` 一起砍掉，
  Q6b/Q7 的存在意义随之消失）。

这是**规格级决定**，不是实现可以自行选择的：改判据属于改验收口径，
保留判据则只能靠不断重建索引去逼近一个概率上够不到的目标。

### 为什么索引这一侧很难追上

* 抽取的每卡上限 `MAX_EDGES_PER_CARD = 4`（`tools/kb_fetch/build_hypergraph.py:58`）
  本身不是瓶颈：943 张卡只产出 **799 条原子边**（≈0.85 条/卡），远未触顶；
* 归并把 677 组压成 **387 条唯一边**（manifest 的 `merge.merged_edges`）；
* 标注侧被覆盖门③/④推着**必须**轮换取值、凑够每类 ≥30 条 `must` 对，
  于是给出的槽位组合本来就有相当一部分不是卡片里逐字写着的。

结论：要么索引侧把产出密度提到标注要求的量级（约 5 条/卡，且成员集要能对上），
要么 oracle 侧约束到"语料真能支撑"的组合。**调 `SCORE_WEIGHTS` 两者都不是。**

## 6. 结论与建议（**不动任何验收线**）

1. **Q1/Q2/Q4/Q6b 现在"不可达"**，因此 RK-13 的正确状态是
   `not_measured` / fail —— 不能报 pass，也不能靠调 `SCORE_WEIGHTS` 去够线。
2. 让门①（§2.3 前置①，"required 边必须在索引里存在"）真的过，只有两条路：
   * **索引侧**：让抽取覆盖标注要求的槽位组合（尤其 `IMPACT_PACK` /
     `PERFORMANCE_PACK` / `SOUND_PACK` / `INTENT_PACK`，以及所有带可选成员的边）；
   * **oracle 侧**：把 `must` 约束到**语料真能支撑**的槽位组合（标注方看不到索引，
     所以这需要改标注协议/提示，属规格级决定）。
3. Q1 的 `top1` 还需要一条**可判定性**要求：期望排第一的那条边必须能被它自己的 `q`
   认出来（即 `q` 命名的 kind 集合与 `top1` 边的 kind 集合一致），否则 Q1 是
   "猜标注者的来源卡"，任何排序器都只有约一半机会。
4. 与 Q1/Q2 无关、但同批发现：`SCORE_WEIGHTS`（`hypergraph.py`）与 §2.3 line 772
   写死的默认公式（`0.35 / 0.20 / 0.15 / 0.05 / 0.15 / 0.10`）不一致，
   现状是 `f92d2b2` 的调参值 —— 属"实现偏离规格"，应么按规格回写、要么把规格改准。

## 7. 未验证 / 未覆盖

* 门⑦（人审 ≥120）**仍然 fail**：只能人做，agent 不替代（协议 §5.5）。
* 本节所有上限都是**在现有 387 条边、`hg/v2` schema 下**量的；索引一旦重建，
  必须重跑 `tools/knowledge/holdout_ceiling.py` 再看线。
* `never`（负样本）侧的"存在性"未进上限表：Q3 的分母同样是"能解析上的负样本对"，
  同样的静默缩分母问题在 Q3 上存在（本表只列了 Q1/Q2/Q4/Q6b 四条线）。
