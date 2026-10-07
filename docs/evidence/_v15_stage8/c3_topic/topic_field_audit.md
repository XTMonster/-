# C3：`topic` 字段的准确率诊断（只诊断，不改生成器）

生成器：`topic_field_audit.py`（只读）。判据同款加载器：`tools.knowledge.attestation.load_cards`。

## 一、`topic` 是什么（出处）

- 生产者：`tools/kb_fetch/import_cards.py:81-83` —— `theme = 该 chunk 的 theme 或 record.theme`，`topic = theme or (domain if domain in TOPIC_QUOTAS else "")`。
- `theme` 是**来源级**声明：`knowledge/sources.yaml` 有 80 行 `theme:`，取值 ['anime', 'anime_production', 'camera_angle', 'character_animation', 'character_design', 'color', 'editing', 'lighting', 'performance', 'pipeline', 'shot_language', 'storyboard', 'technique']。
- `TOPIC_QUOTAS`（`tools/kb_fetch/common.py:51`）＝ lighting/color/camera_angle/editing/anime/storyboard，是 domain 兜底的那一支。

⇒ `topic` 不是「这张卡讲了什么」的**卡级判断**，而是「这张卡来自哪个主题来源」的**来源级标签**，被复制到该来源产出的每一张卡上。

## 二、分辨率：来源级，不是卡级

| 量 | 值 |
|---|---|
| 卡总数 / 生成 / 手写策展 | 2353 / 2221 / 132 |
| 生成卡带非空 `topic` | 1049（47.2%） |
| 手写策展卡带非空 `topic` | 0 |
| 词表（非空取值） | anime, camera_angle, character_design, color, editing, lighting, performance, shot_language, storyboard, technique |
| `chunk_id` 里出现 >1 个 topic 的 | 0 / 576 |
| 同一来源 url 出现 >1 个 topic 的 | 0 |

⇒ 同一个 chunk 的卡片 topic **恒相同**，因此 `topic` 对「同 chunk 内部哪张卡讲什么」**零分辨率**。

## 三、词表覆盖面：机械 `topic_mismatch` 只可能在这几个 kind 上不落空

- `topic` 词表 ∩ `hypergraph.ALLOWED_KINDS`（共 30 个）＝ **['camera_angle', 'lighting']**。
- 也就是说，`kind not in card_topics` 这条机械判据**只有在成员 kind 恰好是 ['camera_angle', 'lighting'] 时才有机会判成「匹配」**；其余 28 个 kind 是「结构性不可能匹配」，与卡片挂得对不对无关。

## 四、把 88/90 拆开（这才是机械预读真正说的东西）

| 分类 | 行数 | 含义 |
|---|---|---|
| `matched`（有来源卡 topic 等于成员 kind） | 2 | 词表巧合 |
| `mismatch_with_topic`（有 topic，但无一等于 kind） | 55 | 词表不相交 |
| `no_topic_at_all`（全部来源卡 topic 为空串） | 33 | **缺失**，不是「不等」 |

两条 `matched` 行：

- `hg:05c36cb730e7` ｜ kind=camera_angle ｜ 来源卡 32 张
- `hg:1953fa522d0c` ｜ kind=camera_angle ｜ 来源卡 35 张

逐 kind 明细：

| kind | 行数 | kind 在 topic 词表里 | 有 topic 的行 | 判成匹配 |
|---|---|---|---|---|
| action | 7 | False | 3 | 0 |
| camera_angle | 23 | True | 14 | 2 |
| composition_rule | 11 | False | 7 | 0 |
| emotion | 10 | False | 5 | 0 |
| headroom_policy | 13 | False | 10 | 0 |
| movement | 9 | False | 6 | 0 |
| shot_size | 17 | False | 12 | 0 |

`no_topic_at_all` 的 kind 分布：[('camera_angle', 9), ('emotion', 5), ('shot_size', 5), ('composition_rule', 4), ('action', 4), ('headroom_policy', 3), ('movement', 3)]。

## 五、`topic` 与卡级标签的对拍（能算的那部分）

| 对拍 | 命中 | 分母 |
|---|---|---|
| `topic == card.domain` | 552 | 1049 张带 topic 的生成卡 |
| `topic` 落在 `card.tags` 里 | 0 | 1049 |
| `topic` 字面出现在卡的 `card_blob` 里 | 1 | 1049 |

（`card_blob` 与判据同源；`tags` 是卡自己的中文标签。）

## 六、样本来源卡（204 张，供人工/独立通道抽查）

- 带非空 `topic` 的 82 张；空 `topic` 的 122 张。
- 逐张摊平见 `topic_field_audit.json` 的 `sample_source_cards`。

## 七、独立抽查：`topic` 描述得了这张卡吗（82 张，人工判读）

判读数据：`topic_card_verdicts.json`。判读者：本文件是 **DeepSeek 主线 agent 的人工判读**（proxy-only），不是裁定通道判词；GLM 交叉对拍因本机 `GLM_API_KEY` 缺失**未跑**，如实标注。
抽样规则（确定可复现）：90 槽位样本里出现的 204 张来源卡，取其中 `topic` 非空的**全部** 82 张，按 `card_id` 升序。
覆盖校验：判读集与样本带 topic 卡的集合**完全相等 = True**（82 张）。

| 判词 | 张数 | 占比 |
|---|---|---|
| `faithful`（topic 就是这张卡的主题） | 54 | 65.9% |
| `partial`（topic 是上位/邻接学科） | 7 | 8.5% |
| `mislabeled`（该卡属于别的 topic 桶） | 21 | 25.6% |

按 topic 拆（错标集中在哪几个来源主题）：

| topic | 抽查张数 | faithful | partial | mislabeled | 全库该 topic 卡数 |
|---|---|---|---|---|---|
| anime | 11 | 11 | 0 | 0 | 141 |
| camera_angle | 5 | 0 | 0 | 5 | 59 |
| character_design | 1 | 1 | 0 | 0 | 5 |
| color | 6 | 1 | 1 | 4 | 99 |
| editing | 12 | 1 | 1 | 10 | 182 |
| lighting | 2 | 1 | 1 | 0 | 104 |
| performance | 1 | 1 | 0 | 0 | 6 |
| shot_language | 34 | 30 | 3 | 1 | 222 |
| storyboard | 10 | 8 | 1 | 1 | 229 |

## 八、诊断结论

1. **`topic` 是来源级标签，不是卡级判断**——同一 `chunk_id` 与同一来源 url 内 topic 恒相同（576 个 chunk、108 个 url，出现 >1 个 topic 的**各为 0**），所以它对「同一来源内部哪张卡讲什么」零分辨率。
2. **机械预读那个 `topic_mismatch = 88/90` 不能读成「97.8% 挂错卡」**：`topic` 词表（10 个非空取值）与 `ALLOWED_KINDS`（30 个）只在 ['camera_angle', 'lighting'] 上相交，因此任何成员 kind 不落在这 2 个值上的行都是「结构性不可能匹配」。88 条里 55 条是「有 topic 但词表不相交」、33 条是「来源卡压根没 topic」（缺失 ≠ 不等）。
3. **`topic` 自身的准确率**（82 张人工抽查，proxy）：faithful 54 / partial 7 / mislabeled 21。错标不是均匀的，而是集中在「把一本泛题材书归到某个主题配额下」的那几个来源主题（camera_angle / color / editing）；学科专精的来源（anime / shot_language / storyboard）几乎全 faithful。
4. **对下游的含义**：任何拿 `topic` 当「这张卡的主题」来判「挂错卡」的判据，都会把来源级标签的错标**当成卡级事实**。要它承担卡级判断，得先改生成器把 `topic` 落成卡级字段——那是**改判据/改生成物**，按红线 R-5 属于**须裁决**，本卡只出读数、不动手。

## 九、未做 / 未验证（如实记）

- **GLM 交叉对拍未跑**：本机 `GLM_API_KEY` 缺失，而 GLM 类调用按 README 环境约束必须串行且带「不可用即跳过」退路 ⇒ 第七节的判读只有**单通道（DeepSeek 主线 agent）**，不是双通道对拍。
- 抽查是**确定性取全部**（82/82），不是随机抽样 ⇒ 给的是**分层覆盖**，不是置信区间。
- `topic` 的消费者（已枚举，全部只读）：`tools/kb_fetch/import_cards.py:236`（写进 jsonl）与 `:289`（import 报告统计）；`docs/evidence/20261007-grounding-sample90/sample_grounding90.py:41,78,120-125`（机械预读 `mechanical_pre_read`）；`docs/evidence/20261007-wrong-card-correction/probe_wrong_card_full.py:109`（P14-318 探针，读作 `topic_or_domain`）。**运行时检索侧看不到它**：`block_director/knowledge/generated.py` 的 `CARD_FIELDS` 不含 `topic`（只进审计，不进 `Card`）。

