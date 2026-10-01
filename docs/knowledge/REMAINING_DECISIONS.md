# 剩余红门的决议清单（2026-10-01，主 agent）

四道红门各自的**当前数字、根因、可选项、我的建议与代价**。本文只汇总，逐项证据在
`ACCEPTANCE_STATUS.md` §九与 `ORACLE_DECISION_v15.md`。

## ① 门④ 边类覆盖：3 类短线，**供给天花板**

```
short_pairs: IMPACT_PACK 22 / SOUND_PACK 21 / MUSIC_PACK 14   （线是 30）
```

根因已查到底（§9.12）：这三类的**原子边数 ≈ 覆盖卡片数 ≈ 22**，且 required 签名
大多各不相同 —— 跨卡归并**没有可并的东西**，所以"对数 ≈ 原子数"，够不到 30。

* **选项 A（推荐先试）**：换来源族。判据是"许可白名单 ＋ robots 门 ＋ 真的讲剪辑/声音实务"。
  已知两次 Gutenberg 定向检索都空手（20 本里 4 本有技术内容，其中 3 本本来就在语料里）；
  下一步要试的是**CC 授权的高校影视制作课程讲义/开放教材**这类别的来源族。
* **选项 B（若 A 失败则必须裁决）**：`--min-per-type 30` 是 schema 只有 6 类时的常数。
  16 类摊同一份许可语料后，这三类**在构造上够不到**。要不要按"每类 ≥10 张卡 ＋
  该类的全部可断言对"重定这条门，是**规格裁决**。
* **代价**：A 需要新的抓取/清洗轮（数小时，且不保证找得到）；B 改的是验收标准本身。

## ② 门⑥ 来源覆盖：缺 393/2113，**三类成因已定量**

```
no_edge_at_all              184   ← 索引里没有任何边引用这张卡（供给）
in_oversized_group          177   ← 该卡的边落在 >3 的 (类型,查询) 组里，整组被跳过
edge_has_out_of_vocab_value  32   ← 边里有词表外取值，整条被跳过
```

`in_oversized_group` 里 **150 张是 `STAGING_PACK`**，而它的成因与 `EDIT_RHYTHM`
**不是同一种**（那一种是"缺查询键"，已修）：

```
group size 4 | type STAGING_PACK | q = 景别=MS；机位=平视；构图=occlusion
  [构图=occlusion, 景别=MS, 机位=平视, forbid_composition_rule=balance]        cards 1
  [构图=occlusion, 景别=MS, 机位=平视, forbid_composition_rule=rule_of_thirds] cards 1
  ...
```

四条边的**必填成员完全相同**，区别只在"**禁止哪个构图规则**"。而 `q` 里同一个键
只有一个值 —— `构图` 已经被必填值 `occlusion` 占用，**被禁止的那个取值写不进去**。
`query_of()` 因此只能跳过 forbid 侧，四条边拿到同一个 q、不可区分，整组被跳过。

* **选项 A（推荐）**：给 `forbid` 值一套**独立查询键**（例：`禁构图` → `forbid_composition_rule`）。
  这样 q 可以同时说"构图=occlusion（要）"与"禁构图=balance（不要）"，四条边立刻可分，
  实测**直接回收 150 张卡**。代价：协议 §2.1 的键集要扩（与 v1.5 加 `强度`、
  v1.6 加 `镜长`/`语气`/`配乐`/`道具` 同类），要同步提示、词表、oracle。
* **选项 B**：不动。那 150 张卡在门⑥ 里就一直是红的 —— 但**这是诚实的**：
  当前查询语言确实表达不出这些边之间的差别。

## ③ 门⑦ 人审：**通路已打通，等你 74 个勾**

`tools/knowledge/human_review_sheet.py` 生成的表里正好 **74 节**（= 门⑦ 会数到的条数），
门⑦ 判据是 `reviewed >= min(needs, 120)` → **勾完即过**。三步命令在
`docs/knowledge/HUMAN_REVIEW_SHEET.md` 表头。**这一步 agent 不能代替**（协议 §5.5/§5.6：
双模型复核只能写 `llm-panel`，写 `human` 就是伪造证据）。

## ④ 门⑧ 换族：GLM 在跑

`glm_v6`（`glm-4.7-flash`，family zhipu，与抽取器 deepseek 异族）。跑完 → 提升 →
门⑧ 有望转绿。当前 oracle 是**机械通道**的临时件，隔壁新增的检查正确地拒绝了它
（`non_model_families: ["rule"]`）—— 这条红是**对的**。

## ⑤ 质量指标 Q4 / Q6b：0.972 / 0.9865（合同线 1.0）

已定量（§9.8）：`occurrences` 让"部分匹配但更常见"的边以 0.002–0.01 的分差把
"逐字全中"的边挤出 top-3；Q6b 另有一部分是 `render_edges` 的 2000 token 预算丢边。
权重已做过一次 12 点网格扫参（四项同时变好）。**剩下的缺口需要"锚点"层面的改动**：
`Q4` 要求每条 required 都进 top-3，而当同一个查询下"完全对齐"的边多于 3 条时，
它在数学上不可能 —— 选项 A 的**forbid 键**同样会缓解这一类（它让更多边变得可分）。

## 汇总建议（按性价比排序）

1. **门⑦ 74 个勾**（你，30 分钟）——唯一"做完就绿"的一条。
2. **门⑧**：等 GLM v6（在跑）。
3. **门⑥ 的 forbid 键**（我，协议级扩展）——实测直接回收 150 张卡，且与 Q4 的机制同源。
4. **门④/⑥ 的来源族**（我，需要新抓取族；不保证成功）。
5. **门④ 的门限重定**（你，规格裁决；我不会单方面动）。

## 附：三次定向来源检索的原始结果（避免重复同样的关键词）

每次都走管线自己的 `find_sources.py`（候选逐本过真实 fetch＋extract 门）：

| # | terms | 命中/可抓 | 有技术内容的 |
|---|---|---|---|
| 1 | `photoplay scenario continuity "screen writing" "picture music"` | 8 / 8 | **3**（Writing the Photoplay、How to write photoplays、The Photoplay: A Psychological Study）——**且这 3 本本来就在语料里** |
| 2 | `"motion pictures" cinematography sound technique editing` | 12 / 12 | **1**（Moral Deliberations in Modern Cinema） |
| 3 | `"incidental music" "moving picture music" "trick photography" stunt "mechanical effect"` | 9 / 9 | **2 待评估**（Magic, Stage Illusions and Scientific Diversions；Photographic Amusements）——其余是芬兰语小说／stunt 短篇／"Picture stuff" |

三次共 29 本，只有 4 本与前 3 类短线相关，其中 3 本**已在语料里**。
即：**Project Gutenberg 的关键词检索基本只返回小说**，用它补 `IMPACT_PACK`／
`SOUND_PACK`／`MUSIC_PACK` 是低效路径。下一步要换**馆藏**（CC 授权的高校影视制作
课程讲义/开放教材），而不是继续换关键词。

顺带修掉一个真缺陷（提交见下）：`find_sources.py` 在中文 Windows（控制台 GBK）上
碰到书名里的 `ä` 会抛 `UnicodeEncodeError` **把整轮验证打断**，已经抓完的书一起丢。
现在 stdout/stderr 一律 reconfigure 成 UTF-8 + replace：编码问题最多显示成 `?`，
不会作废一次几十分钟的抓取。
