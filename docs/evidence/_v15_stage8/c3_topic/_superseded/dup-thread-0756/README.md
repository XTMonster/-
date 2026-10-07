# C3：`topic` 字段准确率诊断（**只诊断**，P8-T2）

**run-id**：`_v15_stage8/c3_topic`
**卡**：`执行文档v1.5/TECH_SOLUTIONS.md` §三 **C3**（✅ 本版直接做：只诊断、不改生成器）
**卡定义**：`执行文档v1.5/dispatch_graph.json` 的 `P8-T2`
**日期**：2026-10-07｜**代码改动：零**（本目录只有产物与复算脚本）

---

## 1. 结论（先结论，后证据）

1. **`topic` 本身是一枚质量很差的标签**：2221 张生成卡里 **1172 张（52.77%）的
   `topic` 是空的**；132 张手写卡**根本没有 `topic` 字段**（`Card` 的字段表见
   `block_director/contracts/knowledge.py`）。非空时它也只和 `domain` **52.62%** 一致。
2. **更要紧的是：这个比较根本没有量纲**。卡级「主题」的取值是
   `storyboard / shot_language / editing / anime / lighting / color / camera_angle /
   performance / character_design / technique`（10 个），而边级槽位名是
   **25 个 `kind`**（`shot_size / intensity / action / …`）。两套词表**只在 2 个值上偶然重合**
   （`camera_angle`、`lighting` 既是 topic 值又是 kind 名）——这就是旧探针偶尔判出
   "主题相符"的唯一来源，**不是"卡挂对了"的证据**。
3. 换成**全库都有的 `domain`**（9 个值：`cinematography / blocking / composition /
   performance / storyboard / editing / production / axis_theory / anime`）后，
   与 25 个 kind 的**交集是 0**：`domain` 是比 kind **更粗的另一个维度**。
4. ⇒ **`topic` 的"准确率"这个问题本身要降级**：不管 `topic` 准不准，
   「`topic` ≠ 成员 kind 就当挂错卡」这条机械判据**都不成立**（与
   `../20261007-wrong-card-correction/README.md` 的勘误同向，本卡给它补上了全库口径的读数）。
   要判"挂错卡"必须**读来源卡正文**（判据 `tools/knowledge/attestation.py` 拼的正是它）。

## 2. 90 槽位样本在三种口径下的重算（实测）

样本：`../20261007-grounding-sample90/sample90.json`（90 行、369 个"行×来源卡"关系、
**39 行是多来源**）。三种口径**只差一件事**：卡级主题取哪个字段。

| 口径 | 卡级主题怎么取 | `topic_ok` | `topic_mismatch` | `topic_unknown` |
|---|---|---|---|---|
| `topic_naive`（**仓库里那份机械预读**） | 只读 `topic`；空串也进集合 | 2 | **88** | —（没有这一桶） |
| `topic_corrected` | 手写卡用 `domain` 顶替；空 `topic` 单列 | 2 | **65** | **23** |
| `domain_only` | 一律用 `domain`（2353 张卡都有） | 0 | **90** | —（不可能空） |

**旧口径的 88 里，有 23 行其实是"不知道"**——空串进集合后 `['']` 是**真值**，
`kind not in ['']` 恒真，于是"来源卡没有这个字段"被记成了"主题不符"。

按层（`topic_corrected`）：

| stratum | ok | mismatch | unknown |
|---|---|---|---|
| `closed_loop_kind` | 2 | 22 | 6 |
| `pack:PERFORMANCE_PACK` | 0 | 14 | 6 |
| `pack:SHOT_PATTERN` | 0 | 17 | 3 |
| `pack:STAGING_PACK` | 0 | 12 | 8 |

## 3. 全库 `topic` 质量读数（实测）

| 量 | 值 |
|---|---|
| 卡片总数 | 2353（生成 2221 ＋ 手写 132） |
| 生成卡 `topic` 为空 | **1172（52.77%）** |
| 手写卡带 `topic` 的 | **0**（字段不存在） |
| `topic` 取值数（非空） | 10 |
| `domain` 取值数 | 9（全库 2353 张**每张都有**） |
| 非空 `topic` 与 `domain` 一致的比例 | **0.5262** |
| 空 `topic` 按 `domain` 的分布 | blocking 294／performance 276／axis_theory 184／composition 175／production 145／cinematography 98 |

## 4. 词表量纲（本卡的承重墙）

| 词表 | 值数 | 与 kind 的交集 |
|---|---|---|
| 成员 `kind`（`knowledge/hypergraph.edges.jsonl` 实测） | **25** | —— |
| `topic`（非空） | 10 | `camera_angle`、`lighting`（**2**） |
| `domain` | 9 | **0** |

## 5. 复算（逐字可跑）

```
python docs/evidence/_v15_stage8/c3_topic/diagnose_topic.py
-> 打印全量 JSON；同时写 topic_inventory.json / topic_accuracy.json
```

留档：`diagnose.stdout.txt`（本次运行的逐字输出）、`diagnose_topic.py`（只读脚本）、
`topic_inventory.json`、`topic_accuracy.json`。

## 6. 未验证 / 边界（如实记）

1. **GLM 交叉对拍未跑**：本机 `GLM_API_KEY` 未设置
   （`python -c "import os;print(bool(os.environ.get('GLM_API_KEY')))"` → `False`）⇒
   本卡的"准确率"是**机械读数**，没有模型/人工判词。**不许**用别的通道冒充 GLM 判词。
2. **本卡没有、也不该**改生成器（`tools/kb_fetch/**`、`knowledge/cards_generated/**` 未动）——
   改 `topic` 的抽取是**换数据**，须按裁定与 A6 流程走。
3. `topic_corrected` 里"手写卡用 `domain` 顶替"是**我们的口径选择**（与勘误文档同口径），
   不是原始数据的字段——原数据里手写卡就该记"没有 `topic`"。
4. 样本是**确定性取前 N**（见 `sample90` 的抽样规则），不是随机抽样 ⇒ 这些是**分层覆盖读数**，
   不是置信区间。

## 7. 同目录的**第二套产物**与逐项对账（2026-10-07，必须读）

本目录里**同时存在两套 C3 产物**：本文件所描述的一套（`diagnose_topic.py` /
`README.md` / `topic_inventory.json` / `topic_accuracy.json`），以及并行 agent
`p8t2_c3` 产出的另一套（`topic_field_audit.py` / `README_topic_field_audit.md` /
`topic_field_audit.{json,md,stdout.txt}` / `topic_card_verdicts.json`）。
**两套都不是对方删改的**；这是并行派发时"写集相交"造成的重复，不是数据事故。

**承重结论同向**（两套独立得出同一件事）：`topic` 不能承担卡级判断。

| 口径 | 本套 | `p8t2_c3` 那套 |
|---|---|---|
| 90 行里判"不符"（mismatch） | **65** | **55** |
| 90 行里判"不知道"（unknown） | **23** | **33** |
| 判"相符"（ok） | 2 | 2 |
| 合计 | 90 | 90 |

**差异的成因（唯一的一处）**：一行**既多来源、又只有部分来源的 `topic` 非空**时，
两套把它记进不同桶——本套判 `unknown` 的条件是"**所有**来源卡都给不出主题"，
所以这种行落进 `mismatch`；另一套按"**有一张来源卡主题为空**"就降级成 `unknown`。
**正好 10 行**在 `mismatch` 与 `unknown` 之间搬家（65 − 10 = 55、23 + 10 = 33）。
两者都对"`topic` 不可用作卡级判据"这一结论**无影响**；请用户/主线**择一作为交付件**，
不要两套并列当两个独立结论引用（那会把同一份证据数两遍）。

`p8t2_c3` 那套另外给了两样本套没做的读数（**值得保留**）：

- `topic` 是**来源级**标签而非卡级：`tools/kb_fetch/import_cards.py:81-83` 取来源的
  `theme`（`knowledge/sources.yaml`）/域兜底 ⇒ 实测 576 个 `chunk_id` / 108 个 url
  **各自只有一个 `topic`**，对"同来源内部哪张卡讲什么"**零分辨率**；
- `topic` 词表与 `hypergraph.ALLOWED_KINDS`（30）**只在 `camera_angle`、`lighting` 相交**；
- 82 张逐卡判读：faithful 54 / partial 7 / mislabeled 21（**单通道**，DeepSeek 侧，非 GLM 对拍）。
