# 提案：**per-kind 适用域语义表**（v1，**未实施**）

日期 2026-10-06。**这份文件只提出设计，不改任何代码、不改任何判据、不设任何门。**
它回答的是 P14-273 留下的那个问题：要把"注入的硬约束"变成"**可执行的判定**"，
缺的不是一个 `if`，而是**一张表**——**每个 kind 到底算什么**。

起因（全部有入库证据，见 `docs/evidence/20261006-forbid-vs-plan/`）：

| 你实现的"适用域"层数 | 在唯一真跑（long21）上报出的"违规" |
|---|---|
| 0 层（成员交集即违规） | **1** 条 —— **假阳性**（一条挂在 `shot_size=MS` 上的 forbid 撞到 **MCU** 的镜） |
| 1 层（只绑定 `shot_size`/`movement`/`intent`） | **66** 条 —— **全部来自同一条边**，因为 `AXIS_RULE` 的 `axis_side` **绑不上**，被当成无条件 |

⇒ **两个数都不是可信的违规率**，而且差的不是精度、是**语义**。

## 一、现状：索引里实际出现了 **24 个 kind**，但**没有任何地方说它们各自算什么**

从唯一真源 `knowledge/hypergraph.edges.jsonl`（638 条边）统计成员角色：

| kind | allow | forbid | qualifier | 备注 |
|---|---|---|---|---|
| `shot_size` | 239 | 4 | 0 | |
| `camera_angle` | 0 | 0 | **175** | **只当质词** |
| `intensity` | 0 | 0 | **228** | **只当质词** |
| `beat_type` | 0 | 0 | **97** | **只当质词** |
| `action` | 190 | 4 | 0 | |
| `emotion` | 173 | 9 | 0 | |
| `movement` | 62 | 18 | 79 | 两种角色都有 |
| `composition_rule` | 0 | 9 | 68 | |
| `lighting` | 36 | 13 | 0 | |
| `intent` | 63 | 0 | 0 | |
| `lens` | 83 | 0 | 0 | |
| `pacing` | 42 | 4 | 27 | |
| `prop` | 19 | 0 | 0 | |
| `sfx` | 24 | 0 | 0 | |
| `genre` | 20 | 0 | 0 | |
| `vfx` | 17 | 0 | 0 | |
| `delivery` | 19 | 2 | 0 | |
| `music` | 8 | 1 | 0 | |
| `axis_topic` | 0 | **6** | 19 | **只当质词 ＋ 只被禁** |
| `headroom_policy` | 0 | 0 | 83 | 只当质词 |
| `pair` / `axis_side` / `scene_type` / `transition` | 0 | 0 | 19/19/25/25 | 只当质词 |
| `avg_shot_len` / `carry_shots` / `seq_phase` / `applies_to_genre` / `applies_to_shot_size` / `example_shot` | 0 | 0 | 9/…/… | 只当质词 |

**问题一句话**：schema 只说了"**哪些槽位必填**"（`REQUIRED_MEMBERS`/`OPTIONAL_MEMBERS`），
**没有说"这个槽位是不是适用条件、对着成片的哪个字段"**。

## 二、提案：把 kind 分成三类

### ① 可绑定（今天就对得上成片里的字段）——**能立刻做成诊断**

成片侧已记录的字段（`SDLShot`/`SDLCamera` 实测）：`shot_type`、`camera.lens`、
`camera.movement(s)`、`intent`、`actions`、`vfx`、`transition_in/out`、`duration_frames`、
`axis_line`、`characters`、`gaze`、`active_speakers`、`dialogues`、`prompt`。

| kind | 绑定到 | 判据形态 |
|---|---|---|
| `shot_size` | `shot_type` | 相等（经 `VALUE_ALIASES`） |
| `movement` | `camera.movement` / `camera.movements[].kind` | 相等／**属于**（`movements` 是列表） |
| `intent` | `intent` / `intent_type` | 相等（12 值闭集） |
| `lens` | `camera.lens` | 数值相等（`35mm` ↔ `35.0`） |
| `vfx` | `vfx[]` | 属于 |
| `action` | `actions[]` | 属于 |
| `transition` | `transition_in` / `transition_out` | 相等 |
| `pacing` | `duration_frames`（经 fps） | **区间**，不是相等 |
| `composition_rule` | **构图分**（RK-10 的 `composition_score`） | **阈值**，不是相等 |
| `camera_angle` | 由 `camera.position/target` 反推的机位角 | 相等／区间 |
| `prop` / `pair` / `axis_side` | `characters` / `axis_line` **部分**可推 | **待定**（见下） |

### ② 成片里**没有**对应字段（要落地得先加字段——**这是扩范围**）

`emotion`、`intensity`、`beat_type`、`seq_phase`、`genre`、`scene_type`、`delivery`、
`music`、`sfx`、`lighting`、`headroom_policy`、`avg_shot_len`、`carry_shots`。

> 其中 **`lighting` 用户已明说不在本次范围**（"尽可能囊括**除了灯光以外**的其他…元素"）；
> `music`/`sfx`/`delivery` 属于**声音与台词交付**，白模预演本身不产出它们。
> ⇒ 这三类（声音/台词/灯光）的"执行校验"**要么不做，要么只做"计划里有没有声明"**，
> 而不是"成片有没有做到"。

### ③ **不是条件、只是话题/标注**（不该参与判定）

`axis_topic`（话题）、`example_shot`（示例）、`applies_to_genre` / `applies_to_shot_size`（**作用域覆盖**，
应折进条件而不是当条件）、以及**任何"只在质词位出现"的 kind**——它们表达的是"这条边在说什么"，
不是"这一镜必须满足什么"。

## 三、必须由你拍板的三件（这就是为什么它是**提案**而不是补丁）

1. **②那批要不要扩范围？** 要"校验情绪/节奏/桥段类型"，就得先在成片侧**加字段**并让生成器填它
   ——那是**新功能**，不是修洞。若不做，请在提案里明确写"**不校验**"，而不是让它永远是"未定义"。
2. **①里的"区间/阈值"型（`pacing`、`composition_rule`、`camera_angle`）判据怎么定？**
   相等式判定对它们**没有意义**；一旦定阈值，**就是新的判据**——按本仓纪律须你明示批准。
3. **报出来的数拿去干什么？** 先做**诊断**（不设门，只进证据目录）还是直接**设门/R0xx**？
   我建议**先诊断**：把①类里"能对上的"跑出来报数，**不改验收**；看几轮真跑的分布再谈设门。

## 四、若你同意，我建议的**第一步（最小、可回退）**

只做①类、只做**相等式**的那几个（`shot_size` / `movement` / `intent` / `lens` / `vfx` / `action` /
`transition`），产出一份**诊断**：每镜列出"适用边 → 是否被成片违反"，**不设门、不改链的退出码**，
落 `docs/evidence/<run-id>/forbid_vs_plan.json`。②③类**先在报告里显式列为"未纳入"**——
按 §4.1b 的精神，**未纳入要写出来，不能因为没算就当没有**。

## 五、未验证 / 边界（诚实挂）

* 本文的分类是**基于 schema ＋ 索引实测 ＋ 成片字段清单**做的**人工判断**，**没有**经过
  "每条 kind × 每条边"的逐条核对；`pair`/`prop`/`axis_side` 三个我标成"**待定**"就是因为
  它们**看名字像能绑、但没有机械可推的字段**。
* 只统计了**一份索引**（638 条边）与**一份真跑**（long21）。
* 本文**没有**修改任何代码、判据或门限；`git` 里它只是一份 markdown。
