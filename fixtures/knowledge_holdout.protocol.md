# held-out 标注协议（冻结版 v1 · R50/R49）

> **本文件在标注开始前冻结，标注期间不得修改**（执行文档 §2.3c 的标注通道约束第 3 条）。
> 词表取值一节标记为 **待语料冻结**：它依赖 P14-1 采集进来的卡片，其余各节现在即为终稿。
> 校验器：`python tools/check_holdout.py fixtures/knowledge_holdout.jsonl`（八道覆盖门，见 §4.1b）。

## 1. 产物

`fixtures/knowledge_holdout.jsonl`：**JSONL，一行一条**，UTF-8，LF 换行。**≥ 1200 条**。

## 2. 一条记录的形状

```json
{"id": "hq_0001",
 "from_card": "cine_shot_size",
 "q": "情绪=气急败坏；动作=跺脚；景别=中景",
 "must": ["EMOTION_PACK:emotion=气急败坏,intensity=high,movement=跺脚,forbid_shot_size=特写"],
 "top1": ["EMOTION_PACK:emotion=气急败坏,intensity=high,movement=跺脚,forbid_shot_size=特写"],
 "never": ["LIGHT_PACK:lighting=逆光"],
 "expect_movements": ["固定"],
 "annotator": {"model_id": "deepseek-chat", "family": "deepseek", "model_version": "v3",
               "prompt_sha256": "…"},
 "independence": "strong",
 "pilot": false,
 "review": {"reviewed_by": "human", "verdict": "accepted"}}
```

| 字段 | 必填 | 含义 |
|---|---|---|
| `id` | ✓ | `hq_0001` 起顺延，**全局唯一** |
| `from_card` | ✓ | 这条查询由哪张卡派生（来源覆盖门用） |
| `q` | ✓ | 查询契约串，`键=值` 用 `；` 分隔，**至少 1 对** |
| `must` | ✓ | 必须能检出的边，**1–3 条**；每条写成 `TYPE:槽位=取值,…` |
| `top1` | ✓ | 期望排第一的那条，**必须 ⊆ `must`** |
| `never` | ✓ | 不该被召回的边，**与 `must` 不相交**；可为 `[]` |
| `expect_movements` | 选填 | 该查询下**作者**期望的运镜（只服务 Q5）；可缺省 |
| `annotator` | ✓ | `{model_id, family, model_version, prompt_sha256}`，手标写 `human` |
| `independence` | ✓ | `strong`（不同厂商族）／`weak`（同厂不同型号） |
| `pilot` | 选填 | `true` 表示试点条目，**不进正式集** |
| `review` | 选填 | 人裁决记录 `{reviewed_by, verdict}` |

### 2.1 `q` 的键集（冻结）

| 中文键（写进 `q`） | 对应 kind | 备注 |
|---|---|---|
| 情绪 | `emotion` | |
| 动作 | `action` | **角色动作** |
| 运镜 | `movement` | **镜头运动**，与"动作"不是一回事 |
| 景别 | `shot_size` | `ECU/CU/MCU/MS/MLS/LS/ELS` 或中文 |
| 镜头 | `lens` | 焦段，如 `85mm` |
| 节奏 | `pacing` | 如"短镜硬切""长镜留白" |
| 特效 | `vfx` | |
| 音效 | `sfx` | |
| 机位 | `camera_angle` | 平视／低机位／高机位／荷兰角 |
| 光线 | `lighting` | 光位／对比／色温 |
| 构图 | `composition_rule` | 必须引用 `cinema/composition.py` 的规则名 |
| 轴线 | `axis_topic` | |
| 题材 | `genre` | |
| 桥段 | `beat_type` | |
| 对白 | `scene_type` | 布尔型查询项（如"对白=有"）按 §2.3 折进 qualifier，**不新造节点类型** |
| 意图 | `intent` | v1.5 新增：**角色/导演想干什么**（铺垫/推进/揭示/转折/停顿/压迫/释放/回望/收束/煽动/留白/对抗），中文闭集 |

布尔型查询项（如"对白=有"）**统一映射到 `pacing`／`scene_type` 的取值**，不新造节点类型（§2.3）。
**词表覆盖门只要求 15 个节点 kind 齐全**（v1.5 起含 `intent`）；`scene_type` 是 qualifier，
词表里有就一并检查、没有不阻塞。

### 2.2 `must`／`never` 的写法

`TYPE:槽位=取值,槽位=取值`，其中

- `TYPE` 只能是 **13 类**之一：`EMOTION_PACK` / `SHOT_PATTERN` / `AXIS_RULE` / `TROPE` /
  `EDIT_RHYTHM` / `LIGHT_PACK` / `ACTION_BEAT` / `PERFORMANCE_PACK` / `INTENT_PACK` /
  `IMPACT_PACK` / `STAGING_PACK` / `SOUND_PACK` / `TRANSITION_PACK`
  （v1.5 用户裁决：把"角色行为/动作/情绪/意图/镜头语言/震动与打击感/构图"这些**强耦合**
  建成独立边类型；真源是 `block_director/knowledge/hypergraph.py`）；
- 槽位名 = **kind**（17 类节点）或 **qualifier**（`pair/axis_side/intensity/applies_to_genre/applies_to_shot_size/headroom_policy/avg_shot_len/transition/scene_type/example_shot`）；
- **禁忌槽位**写成 `forbid_<kind>=取值`——它同时是 Q7 的判定依据（见 3.3）；
- **标注者不写 `norm_key`、不写 `edge_id`、不抄成员清单**：runner 按冻结 schema 展开。

**每类边的必填槽位**（缺即该条不合格，与执行文档的校验门④一致）：

| 边类型 | 必填槽位 |
|---|---|
| `EMOTION_PACK` | `emotion` ＋ `intensity` |
| `SHOT_PATTERN` | `shot_size` ＋ `lens` ＋ `headroom_policy` |
| `AXIS_RULE` | `pair` ＋ `axis_side` |
| `TROPE` | `genre` ＋ `emotion` |
| `EDIT_RHYTHM` | `pacing` ＋ `avg_shot_len` |
| `LIGHT_PACK` | `lighting` ＋ `intensity` |
| `ACTION_BEAT` | `action` ＋ `beat_type` ＋ `intensity` |
| `PERFORMANCE_PACK` | `emotion` ＋ `action` ＋ `camera_angle` |
| `INTENT_PACK` | `intent` ＋ `shot_size` ＋ `movement` |
| `IMPACT_PACK` | `vfx` ＋ `sfx` ＋ `movement` |
| `STAGING_PACK` | `composition_rule` ＋ `shot_size` ＋ `camera_angle` |
| `SOUND_PACK` | `sfx` ＋ `pacing` ＋ `intensity` |
| `TRANSITION_PACK` | `transition` ＋ `pacing` ＋ `scene_type` |

## 3. 判定规则（冻结）

### 3.1 `must`

先问："**这一镜如果抽不到这条边，我会认为检索失败了**吗？" 会 → 进 `must`。
**最多 3 条**——上限是硬的，因为 Q4 要求在 top-3 内 100% 可检出，`|must| > 3` 时 100% 数学上不可达。

### 3.2 `never`

**负样本 = `applies_to_*` 与查询不匹配，或 `allow` 集与查询完全不相交的边。**

反例（必须记住）：查询 `情绪=荒诞；运镜=固定` 时，`EMOTION_PACK(荒诞, forbid=固定机位)` **是必须被召回的**，
不能写进 `never`——模型要靠它放弃固定机位。这正是 Q7 要守的东西。

### 3.3 Q7 冲突条目

一条记录算作"Q7 冲突条目"，当且仅当：
**`q` 里的某个 `(kind, 取值)` 与同一条记录某条 `must` 的 `forbid_<kind>=取值` 相同**。

例：`q` 含 `景别=特写`，`must` 含 `forbid_shot_size=特写` → 该条计入 Q7。
这类条目 **≥ 60 条**（覆盖门⑤）。**由 `tools/check_holdout.py` 机械统计**，不靠人报。

## 4. 八道覆盖门（与 §4.1b 一致；不过门则 RK-13 的一切指标无效）

| # | 门 | 要求 |
|---|---|---|
| ① | 总量 | `len(entries) ≥ 1200` |
| ② | 逐条格式 | 见 §2 的必填与 2.2 的必填槽位；`1 ≤ len(must) ≤ 3`；`top1 ⊆ must`；`must ∩ never = ∅` |
| ③ | 种子覆盖 | **词表里每个取值至少出现在 1 条 `q` 里** |
| ④ | 边类覆盖 | **13 类边（`hypergraph.EDGE_TYPES`）每类至少被 30 条 `q` 的 `must` 要求**（v1.5 D6 把边类从 6 扩到 13，旧值 6 作废） |
| ⑤ | 禁忌覆盖 | **Q7 冲突条目 ≥ 60** |
| ⑥ | 来源覆盖 | **每张入库卡至少派生 1 条**（`from_card` 去重后 ⊇ 卡片集合） |
| ⑦ | 可达性（R54 新增；报告键 `gate_9_reachability`） | **`must[0]`/`top1` 里每个"有查询键"的 `plain` 槽位，必须在 `q` 里逐字出现**——这是 §3.1 对 `must` 的定义（"抽不到它就算检索失败"）的机器实现 |
| ⑧ | 可解析（R54 新增；报告键 `gate_10_index_resolvable`） | **每条 `must`/`top1`/`never` 必须映射到当前索引里的边**（§2.3 Q6b 前置① 的 `norm_key` 口径）；缺索引时记 `not_measured` |

> 门③与门⑥需要外部输入（词表、卡片清单），门⑧需要索引（`--nodes/--edges`，默认读仓库里的
> `knowledge/hypergraph.{nodes,edges}.jsonl`）；缺输入时校验器报 `not_measured`，
> **按 §4.1b 硬规则 1，`not_measured` 不得当作通过**（退出码 2）。

> **R54 的性质说明（与"协议先冻结"不冲突）**：门⑦/门⑧**不是新规则**，是把本协议
> §3.1（`must` 的定义）与执行文档 §2.3 的 Q6b 前置①（required 边必须存在）
> **已有**的条文变成机器检查——此前只有产出侧 `tools/holdout_fill.py` 在拦，
> 校验器不拦。判据口径（只看 `must[0]`+`top1`、只看 `plain` 槽位、
> `QUERYABLE_KINDS` 排除 `scene_type`/`beat_type`）与产出侧**同一份**，
> 未放宽也未收紧。

## 5. 标注通道（R49）

1. **换族**：标注 `family` 必须 ≠ 抽取 `family`。不同厂商族 = `independence: strong`（人审 10–15%）；
   同厂不同型号 = `weak`（**人审 ≥30%**，且该集合在 RK-13 上**降级为辅助证据**，不得单独支撑 Q1/Q2 的 70%/90% 线）。
2. **不可见**：标注方只能拿到语料、schema、本协议；不得拿 index、`knowledge_trace.json`、检索器、抽取 prompt。
3. **协议先冻结**：即本文件。
4. **人抽查校准**：人复核 **10–15%（≥120 条；`weak` 时 ≥360 条）**并报告一致率；**< 90% 整批退回重标**。
5. **分指标归属**：`Q0–Q4`、`Q6a` 可交独立标注 agent；**`Q5`／`Q7`／`E3` 的最终裁定必须由人做**。

**双族分歧驱动裁决（推荐流程）**：两个不同族的模型各标一遍 →
**一致的部分直接入库**，**分歧的部分（通常 15–30%）只把人推到选择题界面**。
分歧率本身就是质检信号：一致率 >95% 说明协议太松（都在说套话），<60% 说明协议有歧义。

### 5.6 双模型复核通道（v1.5 用户裁决）

用户明确指示：**Q5／Q7／E3 这一层交给 DeepSeek 与 GLM 两个模型判**（"我没有经验"）。
落地方式与边界（`tools/holdout_review_llm.py`）：

* 复核记录写 `reviewed_by: "llm-panel"`，**绝不写 `"human"`**；门⑦ 只认 `human`，
  因此它**照旧不通过**——这是"多一份辅助证据"，不是"降低验收标准"；
* 两模型**一致 accepted** → 记为 `accepted`；一致 `rejected` → 该条**从 held-out 剔除**；
  分歧 → 保留并打 `panel_disagreement: true`，同时写进 `--sheet` 的分歧清单（只有几十条），
  人可以只看那份清单来满足门⑦ 的 ≥120 条；
* 工具的入口在 `tools/holdout_review_llm.py`，报告落 `work/holdout_panel.json`。

## 6. 待语料冻结的部分（P14-1 内补齐）

- **取值词表**：每个 kind 下允许的 `取值` 规范名（从采集到的卡片里取），以及每个取值的中文别名。
  **词表未冻结前不得开始正式标注**——否则 `norm_key` 对不上，Q4 会整体为 0 且看起来像"检索不行"。
- 卡片清单（门⑥的输入）。
