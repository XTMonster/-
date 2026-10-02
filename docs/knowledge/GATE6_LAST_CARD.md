# 门⑥ 的最后一张卡：`gen_cine_0247`（2026-10-02）

## 现状（一条命令可复现）

```
python tools/check_holdout.py fixtures/knowledge_holdout.jsonl \
    --vocab fixtures/knowledge_holdout.vocab.json \
    --cards fixtures/knowledge_holdout.cards.json \
    --assertable fixtures/knowledge_holdout.assertable.json \
    --reviewer-classes human,llm-panel \
    --exclude-cards knowledge/card_scope.json
→ gate_6_sources fail, cards 2113, cards_expected 2084, missing_count 1
```

其余 10 道门全绿。唯一缺的那张卡是 `gen_cine_0247`：

> **持续流动的摄影机**：摄影机始终处于某种运动中——位移、摇移或改变焦距，
> 避免长时间静止固定，以保持画面的流动感。
> （MIT OCW 21L.011 *The Film Experience* 2006 讲义，CC-BY-NC-SA）

## 为什么补不上：它的索引边是**抽错的**

这张卡在索引里只有一条边：

```
hg:7840fbdf6555  EMOTION_PACK  sources=[gen_cine_0247]
   allow     emotion   emotion:平静
   qualifier intensity intensity:low
   forbid    movement  movement:固定
```

卡里**没有**"平静"或"强度低"这两个意思——它讲的是运镜。抽取器把一堂课里的**上下文**
当成了这张卡的内容。两条独立证据：

1. **逐字对比**：卡片的正文与 `quote` 只有那句运镜话（「The camera is always moving
   in some way…」），"平静／low"在卡里不出现。
2. **双模型复核**（`tools/holdout_review_llm.py`，DeepSeek ＋ GLM，跨族、
   `temperature=0`、提示指纹 `52c09bf2…`）：给这张卡写出来的唯一一条期望
   `情绪=平静；强度=low；禁运镜=固定` 被**两个模型同时判 rejected**：

   ```
   a(deepseek-chat): 卡只讲运镜持续运动，未支持情绪=平静或强度=low的耦合
   b(glm-4.7):       卡未提及情绪平静或强度低，不支持该 EMOTION_PACK 耦合
   ```

   原始记录：`docs/knowledge/GATE6_LAST_CARD.panel.json`
   （`selected: 1, accepted: 0, dropped: 1`；缺口轮的产出见同目录的 `.gap.json`）。

门⑩ 要求 `must` 必须解析到索引里的边，所以**任何**覆盖这张卡的条目都只能引用上面那条
边——也就只能断言"这张卡支持平静／低强度"。复核说它不支持，于是这张卡在当前索引上
**写不出合规的期望**。

## 为什么不是"再改一次分母"就完事

§4.1b 的分母口径是「每张**入库卡**至少派生 1 条」。入库＝可断言。这张卡的**知识确实
在镜头层**（"别老定着不动"是运镜取舍），但它落不进任何一类边的**必填槽位**：

| 可能的宿主 | 必填槽位 | 这张卡能给的值 |
|---|---|---|
| `SHOT_PATTERN` | `shot_size` ＋ `lens` ＋ `headroom_policy` | 一个都没有（卡没说景别/焦距/留白） |
| `EMOTION_PACK` | `emotion` ＋ `intensity` | 一个都没有（卡不谈情绪/强度） |

也就是说：**它是一张"可断言"的卡，但当前 schema 没有一个能诚实承载它的边型**——
这正是 `card_scope_audit.py` 里 `not_expressible` 那一类（"确属影视制作，但词表没有
槽位放它"）。它之所以没被算进 `excluded`（29 张），只是因为抽取器**替它编**了一条
能过门的边。

把这一段写清楚，是为了不让"门⑥ 缺 1 张"被读成"标注员偷懒"。**它不是标注缺口，
是抽取精确度缺陷 ＋ schema 覆盖缺口。**

## 建议的处置（按优先级）

1. **抽取侧加一条成员落地判据**（真正的修法）：`allow` 取值的取值或别名必须出现在
   该边的来源卡正文里——`forbid` 半边已经有这套判据（`holdout_pool.grounded_conflict_pairs`），
   `allow` 没有。加了它，这条边在抽取期就会被拒，`gen_cine_0247` 变成"零条边"，
   与另外 29 张卡同路径进 `excluded`，门⑥ 自然转绿，而且**下一次重抽不会复发**。
   （本轮没做：它需要一次全量重抽才能验证，而重抽产物与当前入库索引不是同一份——
   `work/hypergraph.atoms.jsonl` 是工作区文件，不在版本库里。改判据却无法用同一批
   数据回放，等于把索引换成另一份，风险大于收益。）
2. **给"整场持续运动"补一类宿主**：例如让 `SHOT_PATTERN` 的 `movement` 成为必填之外
   的可选槽位并允许"任意非固定"的表达。这是 schema 变更，牵动词表不动点与 oracle，
   属独立工作项。
3. **手工删掉这条边**（`knowledge/hypergraph.edges.jsonl` 删 1 行 ＋ 改 manifest 计数）
   ——**不建议**：它让索引与"从语料可重算"这个性质脱钩，下一次重抽会把这条边带回来，
   门⑥ 重新变红，而且没有留下任何阻止它复发的规则。

## 顺带记下的两个数（这一轮实测）

* `excluded_with_entries = ["gen_axis_0095", "gen_axis_0196"]`：被剔的 29 张里有 2 张
  **已经有条目**。这不是损失（覆盖多出来的部分照旧算），但它说明"被剔"不等于"这张卡
  在语料里没用过"——剔的只是**门⑥ 的分母**。
* `edge_backed_without_entry_count = 1`：门⑥ 真正在测的那个数（可断言卡里还缺条目的）
  从 21 降到 1，且这 1 张的成因已定位到具体的边与具体的复核记录。

---

## 已解决（2026-10-02，同日落地）

上面那份"建议的处置"里，**第 1 条的方向是对的，但它写的那条判据不能照字面实现**——
这一节记录最后怎么做的，以及为什么不是照抄。

### 1. 建议里的"`allow` 必须在卡里落地"**不能全局施加**（实测）

原文写的是：*"`allow` 取值的取值或别名必须出现在该边的来源卡正文里——`forbid` 半边已经
有这套判据（`grounded_conflict_pairs`），`allow` 没有。"* 照这条去做，540 条边里会判掉
**538 条**（`allow` 596 个、`qualifier` 701 个成员在卡里找不到字面）。原因不是语料脏，
而是**抽取器本来就在做抽象**：`beat_type=coverage`、`intensity=mid`、`action=上下场`
这类推断在卡里永远没有字面。全局落地判据会把索引清空。

复现：`work/zz_rule_probe.py`（判据的爆炸半径逐档实测：6 / 2 / 6 / 2 / 2 / 2 条）。

### 2. 真正的判据：**禁令必须有宿主**

只在这条边**是某条禁令的宿主**时才施加落地要求。四条同时成立才拒收：

1. 卡里真有否定表述（与门⑤ 共用 `block_director.knowledge.grounding.NEGATION_CUES`）；
2. 至少一条 `forbid` 成员的取值/名字/别名**在卡里落地**；
3. 这条边的**必填 `allow` 主体**一个都不落地；
4. 出处都是**已知的卡**。

落在 `tools/kb_fetch/build_hypergraph.py::unsupported_prohibition_hosts`，由 `run()` 与
`rematch()` **共用**（第 2 段是纯函数，`--rematch` 就能离线重放，**不调模型**）。
`VALIDATION_RULES_VERSION = "gate/v1"` 进六元指纹成为第七个分量——这正是 §2.3 表格里
"六元指纹 **＋ 校验门代码版本**"那句的后半句，也是 §6「重抽取成本」点名建议的那一条。

### 3. 顺手抓到的一个真缺陷：`emotion:平静` 的别名表少了 `安静`

第一次跑出来的账是**删 2 条**，其中第二条是 `cine_move_handheld`：

```
卡：手持 … 因此纪实、混乱、紧张都用它。禁忌：**安静的**对话用手持，会让观众误以为有危险。
边：EMOTION_PACK:allow_emotion=平静, intensity=low, forbid_movement=handheld   ← 意思完全对得上
```

它被拒收**只是因为** `emotion:平静` 的别名表里没有"安静"（表里已有 `安宁`／`留白`）。
也就是说：**落地判据的输入是别名表**，别名表漏一个同义词，一条正确的禁令就会被判成
"主体是编的"。补上 `安静`（`tools/kb_fetch/vocabulary.py::EMOTIONS`）之后重跑：
**删 1 条**（只剩下面那条编出来的）、`forbid` 成员 8 → **7**。
实测两档都留在用例里：`tests/test_hypergraph_precision.py` 的
`test_the_handheld_prohibition_is_kept_because_the_synonym_is_in_the_vocabulary` 与
`test_the_same_prohibition_is_dropped_when_the_synonym_is_missing`。

### 4. 结果（一条命令可复现）

```
python tools/kb_fetch/build_hypergraph.py --rematch        # 540 → 539 条边，账在 manifest.merge
python tools/kb_fetch/card_scope_audit.py                  # 重新生成 knowledge/card_scope.json
python tools/check_holdout.py … --exclude-cards knowledge/card_scope.json
→ 十一门全 pass（含 gate_6_sources）；overall: pass
```

被拒的那条边**没有任何 oracle 条目引用**（实测：`fixtures/knowledge_holdout.jsonl` 里
指向它那套成员集的条目 **0 条**，门⑨/⑩ 因此一动不动）。`gen_cine_0247` 变成零条边，
与另外 29 张卡同路径离开门⑥ 的分母；`edge_backed_without_entry_count` 由 **1 → 0**。
这条边**没有**从 `work/hypergraph.atoms.jsonl` 里删掉——归并期每次都重跑这条判据，
所以"从语料可重算"这个性质没有被破坏。

### 5. 还没做的那半（写清楚，别当成已完成）

**提示本身没改。** `SYSTEM_PROMPT` 的规则 4b 仍然写着"把那个取值挂到 `EMOTION_PACK` 上"，
规则 6b 的"逐类自问"清单仍然只列 **13** 类（`extract/v8` 把 schema 扩到 16 类后漏了 `DIALOGUE_PACK`／
`MUSIC_PACK`／`PROP_PACK`），规则 1／1b 也还写着"13 类"。这三处要改就得换
`PROMPT_VERSION`（`extract/v13`）并**整库重抽＋重标 oracle**，属独立工作项；
本轮的精确度门是它的**离线兜底**（见 `docs/knowledge/ACCEPTANCE_STATUS.md` §二十）。
