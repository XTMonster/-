# C3：`topic` 字段准确率诊断（P8-T2）——产出与结论

**卡**：`执行文档v1.5/TECH_SOLUTIONS.md` 第三节 **C3**
（"✅ 可执行（诊断）：从 90 槽位样本里抽 `topic` 字段与原卡对拍，出准确率读数；
只诊断，不改生成器"）。
**卡定义**：`执行文档v1.5/dispatch_graph.json` 的 `P8-T2`。
**执行者**：`/root/p8t2_c3`（子 agent，DeepSeek 主线）。**代码改动：零。**
**日期**：2026-10-07。

写集：本目录（`docs/evidence/_v15_stage8/c3_topic/`）。以下 5 个文件由本 agent 产出：
`topic_field_audit.py`、`topic_field_audit.json`、`topic_field_audit.md`、
`topic_field_audit.stdout.txt`、`topic_card_verdicts.json`。
同目录另有**另一套** C3 产物（`diagnose_topic.py`、`README.md`、`topic_accuracy.json`、
`topic_inventory.json`、`diagnose.stdout.txt`，时间戳 07:56:03–07:56:19）**不是本 agent 写的**，
未做任何删改；两套的关系见第 5 节。

---

## 1. 结论（先结论，后证据）

1. **`topic` 是"来源级"标签，不是"这张卡讲了什么"的卡级判断。**
   生产者是 `tools/kb_fetch/import_cards.py:81-83`：
   `theme = 该 chunk 的 theme 或 record.theme`，
   `topic = theme or (domain if domain in TOPIC_QUOTAS else "")`；
   而 `theme` 是**来源**在 `knowledge/sources.yaml` 里的声明（80 行 `theme:`）。
   实测：**576 个 `chunk_id`、以及全部来源 url，各自只出现 1 个 `topic`**
   ⇒ 它对"同一来源内部哪张卡讲什么"**零分辨率**。

2. **机械预读的 `topic_mismatch = 88/90` 不能被读成"97.8% 挂错卡"。**
   `topic` 非空词表只有 10 个取值，与 `hypergraph.ALLOWED_KINDS`（30 个）**只在
   `camera_angle`、`lighting` 两个值上相交** ⇒ 其余 28 个 kind 是"结构性不可能匹配"。
   把 88 拆开：**55 行是"有 topic 但词表不相交"、33 行是"来源卡压根没有 topic"**
   （缺失 ≠ 不等）。样本里唯一有机会匹配的 kind 是 `camera_angle`（23 行），
   也只有 2 行匹配上——而那 2 行恰好是样本里最大的两条多来源边（32 张 / 35 张来源卡）。

3. **`topic` 自身的准确率（82 张人工抽查，proxy）：faithful 54 / partial 7 /
   mislabeled 21**（65.9% / 8.5% / 25.6%）。错标**不是均匀分布**：
   `camera_angle` 5/5 全错标、`editing` 10/12、`color` 4/6 —— 全是"一本泛题材书被归到
   某个主题配额下"的来源；而学科专精的来源（`anime` 11/11、`shot_language` 30/34
   faithful+4 邻接、`storyboard` 8/10）几乎全对。
   例：`gen_cine_0065` 的 `topic=camera_angle`，正文却是"自制毛面胶片的器材应急"；
   `gen_edit_0161` 的 `topic=editing`，正文是"基顿式主角的表演基调"。

4. **对下游的含义**：任何拿 `topic` 当"这张卡的主题"来判断"挂错卡"的判据，
   都会把**来源级标签的错标当成卡级事实**。要让 `topic` 承担卡级判断，
   得改生成器把它落成卡级字段——那是**改生成物/改判据**，按红线 R-5 属**须裁决**。
   本卡只出读数，不动手。

## 2. 证据（命令 + 文件:行号 + 真实输出）

复算命令（仓库根，只读）：

```
python docs/evidence/_v15_stage8/c3_topic/topic_field_audit.py
```

逐字输出留档 `topic_field_audit.stdout.txt`；机器可读读数
`topic_field_audit.json`；人读版 `topic_field_audit.md`；判读数据
`topic_card_verdicts.json`。

| 结论 | 证据 |
|---|---|
| `topic` 的出处 | `tools/kb_fetch/import_cards.py:81-83`；`tools/kb_fetch/common.py:51`（`TOPIC_QUOTAS` 六域）；`knowledge/sources.yaml` 80 行 `theme:` |
| 来源级、零分辨率 | `topic_field_audit.json::resolution`：`chunks=576`、`chunks_with_more_than_one_topic=0`、`sources_with_more_than_one_topic=0` |
| 词表只在 2 个值上相交 | `topic_field_audit.json::topic_vocab_intersect_allowed_kinds = ["camera_angle","lighting"]`；词表 10 值见 `::topic_vocab`；`ALLOWED_KINDS` 30 个来自 `block_director/knowledge/hypergraph.py` |
| 88 的拆解 | `topic_field_audit.json::sample_decomposition`：`matched 2 / mismatch_with_topic 55 / no_topic_at_all 33`；两条 matched 边 `hg:05c36cb730e7`(32 卡) 与 `hg:1953fa522d0c`(35 卡) |
| 卡级对拍（能算的） | `::card_level_agreement`：`topic == domain` 552/1049；`topic ∈ card.tags` 0/1049；`topic` 字面出现在 `card_blob` 1/1049 |
| 82 张抽查 | `topic_field_audit.json::spot_audit`；`covers_exactly_the_with_topic_sample = true`（判读集 == 样本带 topic 卡集合，82 张，非"抽几张就说准确率"） |
| 运行时看不到 `topic` | `block_director/knowledge/generated.py` 的 `CARD_FIELDS` 不含 `topic`（只进审计，不进 `Card`） |

输入指纹（本次实测 sha256 前若干位 + 字节数，便于复算对拍）：

```
63aee4973f0c26f0… 135427 bytes  docs/evidence/20261007-grounding-sample90/sample90.json
0597326a9d300137… 501338 bytes  knowledge/hypergraph.edges.jsonl
789c0625ad6c6f65…  29053 bytes  knowledge/hypergraph.nodes.jsonl
11fa3f6b7cefdb94…  17515 bytes  tools/kb_fetch/import_cards.py
d55723077daae17a…  17180 bytes  tools/kb_fetch/common.py
98a43bcaace45fe3…  81469 bytes  block_director/knowledge/hypergraph.py
cc82893904fa85da…   3784 bytes  block_director/knowledge/generated.py
dfb42f929cfca2d5… 106589 bytes  knowledge/sources.yaml
```

## 3. 缺口与风险

1. **单通道**：本机 `GLM_API_KEY` 未设置（`os.environ` 里没有）⇒ 第 1 节第 3 条的
   82 张判读是**DeepSeek 主线 agent 的人工判读（proxy-only）**，没有第二通道对拍。
   **不许**用别的通道冒充 GLM 判词。
2. **非随机样本**：90 槽位是"分层取前 N"的确定性样本（`sample_grounding90.py` 的抽样
   规则）⇒ 给的是**分层覆盖读数**，不是置信区间。第 3 条的 82 张是它的子集。
3. **`topic` 只覆盖 47.2% 的生成卡**（1049/2221），132 张手写策展卡**没有**这个字段
   ⇒ "全库 `topic` 准确率"这个分母本身只有一半。
4. **未追根的一条小异常**：`knowledge/sources.yaml` 里 `theme: anime_production /
   character_animation / pipeline` 这 3 个取值（8 个来源）**在卡片上零出现**。
   本 agent 实测那些来源产出的生成卡为 0 张（多为书评/人物访谈类），
   但**没有逐条核**它们是不是被 chunk 阶段丢掉 ⇒ 标"未验证"，不当结论。

## 4. 建议动作（只到"须裁决"为止）

* **不要**用 `topic` 做任何卡级判断（判"挂错卡"要读来源卡正文——判据
  `tools/knowledge/attestation.py` 拼的正是它）。
* 若要让 `topic` 承担卡级语义：需改 `tools/kb_fetch/import_cards.py` 的生成逻辑
  （把 `topic` 落成卡级字段）+ 换代登记（A6 模板）⇒ **须用户裁决**，本卡不动。
* 与 C1（90 槽位三分类）的关系：C1 的三分类才是"挂错卡/取错值/蕴含未写出"的判据；
  本卡的作用是**抽掉 C3 这个已知弱点**——在读到 `topic_mismatch` 时不要把它当
  "97.8% 挂错卡"。

## 5. 与同目录另一套 C3 产物的对账（如实记）

同目录另有一套产物（作者不是本 agent，未删改）。**两套的承重结论同向**
（`topic` 词表与 kind 词表只在 2 个值上相交；88 不能读成"97.8% 挂错卡"；
GLM 未跑；样本非随机）。逐项对拍：

| 量 | 本套 | 另一套 | 差异原因 |
|---|---|---|---|
| 机械预读复算 | `matched 2 / mismatch_with_topic 55 / no_topic_at_all 33` | `topic_ok 2 / topic_mismatch 65 / topic_unknown 23` | **口径差**：一行既有多来源又"部分来源无 topic"时，本套计入 mismatch（至少有一张卡有 topic），另一套计入 unknown。10 行落在这个边界上（55+10=65、23+10=33） |
| 词表交集 | `camera_angle`、`lighting`（2 个） | 同 | 一致 |
| `topic == domain` | 552/1049 = 52.6% | 52.62% | 一致 |
| 样本规模 | 90 行 / 204 张来源卡 | 90 行 / 369 个行×卡关系 / 39 行多来源 | 一致（204 是去重后的卡数） |
| 本 agent **额外**做的 | 82 张**逐卡判词**（faithful/partial/mislabeled）＋ 出处与分辨率的形式证明 | 三种口径的重算 + `domain` 兜底对照 | 互补 |

两套都不构成验收结论；判据/门限一个字未动（R-5）。
