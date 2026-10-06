# 执行闭环诊断 v2：相等式 kind **3 → 7**、**口径表**、21 次运行全扫

日期 2026-10-07。裁决依据不变（GLM-5.3 F2：**先诊断、不设门**）；这一步做
`docs/knowledge/APPLICABILITY_SEMANTICS_v1.md` 第四节"第一步"点名的那批：
**只做相等式的 kind**，②③ 类**显式列出未纳入**。

> **本目录的 v2 第一版曾被一次独立审查当场驳回，理由全部成立**，本版按它的要求重写：
> ① 聚合数**重算不出来**（"判不了 95／不适用 224"没写口径，且 95+224+1 与 344 差 24 条）；
> ② `movement`（329 个成员）在"能判 3 种／判不了"的二分里**整体缺席**；
> ③ ①/② 分类的括号定义与举例**与注入清单错位**；
> ④ "违规 0"其实出自**仅 1 条生效边、且该边 forbid 成员为 0** —— 是"**无物可违**"，
> 却写得像"查了通过"。**下面逐条改。**

## 一、口径表（每个聚合数都能由原子量唯一重算）

**边口径**（`ledger` 字段，产物里就有）：

```
injected_edges = edge_indecidable + edge_inactive + edge_active
               + injected_edge_missing_from_index
               + edges_in_events_without_a_built_shot
344            = 95 + 224 + 1 + 0 + 24      ← 闭合
```

* `injected_edges` ＝ 所有 `retrieval_call` 事件里 `data.edge_ids` 的条数**求和**（344）；
* `edge_indecidable` ＝ 这条边的成员里**有 kind 不在绑定表** ⇒ 整条判不了（95）；
* `edge_inactive` ＝ 前提（非 `forbid` 成员）**没全中**（224）；
* `edge_active` ＝ 前提全中（1）；
* `edges_in_events_without_a_built_shot` ＝ 那些 `retrieval_call` 的 `shot_id` **没有对应的成片镜头**
  （3 个事件共 24 条边）——第一版把它**静默跳过**，于是三分之和差 24 条。

**成员口径**（`member_kinds_seen` / `covered_kinds` / `not_covered_kinds`）：
这轮被注入的**成员**共 **1,049** 条，按 kind 分成"有绑定／没绑定"两张表（见 §四）。

## 二、绑定表与"这一轮到底注入了什么"

| kind | 成片侧字段 | 归一化 |
|---|---|---|
| `shot_size` | `shot_type` | — |
| `intent` | `intent_type` | — |
| `lens` | `camera.lens` | `35mm` / `35` / `35.0` ⇒ 同一个 |
| `movement` | `movements[].kind` ＋ `declared_camera_move` | — |
| `action` | `action_types[]` | — |
| `transition` | `declared.transition` ＋ `transition_in/out` | — |
| `vfx` | `vfx[].type` | — |

**注入清单**：`20261006-long21` 的 67 条 `retrieval_call` 共注入 **344 条边**，只有 **4 种类型**
（`INTENT_PACK 243`、`AXIS_RULE 66`、`SHOT_PATTERN 22`、`STAGING_PACK 13`）；
成员 kind 只有 10 种。**`action`/`transition`/`vfx` 一次都没被注入** ⇒ 它们是 `no_data`。
（复算：`probe_injected_members.py`。）

## 三、逐 kind 的**成员三分**（`member_outcomes_by_kind`）——这一张才是关键

| kind | `matched` | `unmatched` | `film_side_empty` |
|---|---|---|---|
| `shot_size` | **201** | 68 | 0 |
| `intent` | **105** | 120 | 0 |
| `lens` | **17** | 2 | 0 |
| `movement` | 5 | 1 | **296** |

**怎么读**：`shot_size`/`intent`/`lens` 是**真的在比**（两边都有值）；
而 `movement` 的 **296/302 个成员落进 `film_side_empty`** —— 成片侧那两个字段
（`movements[].kind`、`declared_camera_move`）**几乎是空的**。
⇒ 关于 `movement`，正确的话不是"能判"也不是"判不了"，而是"**没得比**"。

## 四、"没纳入"逐条写出来（提案 §4 的要求）

| | kind 与条数 |
|---|---|
| **已纳入**（有绑定） | `movement 302`、`shot_size 269`、`intent 225`、`lens 19` |
| **未纳入**（显式列出） | `pair 63`、`axis_side 63`、`axis_topic 63`、`headroom_policy 19`、`composition_rule 13`、`camera_angle 13` |

**分类按"本轮事实"重划**（第一版把两套分类混着用，被审查当场抓住）：

| 类别 | 定义（本轮口径） | 本轮实例 |
|---|---|---|
| **A：已注入＋成片有字段** | 能进入逐条比对 | `shot_size`／`intent`／`lens`／`movement`（后者 296 条**没得比**） |
| **B：已注入＋成片无字段** | **构造上判不了** | `pair`／`axis_side`／`axis_topic`／`headroom_policy`／`composition_rule`／`camera_angle` |
| **C：本轮未注入** | **无数据**（`no_data`） | `action`／`transition`／`vfx`／`emotion`／`intensity`／`beat_type`／`lighting`／`music`／`sfx`／`delivery`… |

（提案 ① 类里把 `composition_rule`／`camera_angle` 当"区间/阈值型"——那是
**能不能定判据**的分类；本表是**本轮能不能算**的分类。两者不是一张表，第一版混着写是错的。）

## 五、"违规 0"的**限定写法**

**不是**"查了 344 条边、0 条违规"。准确说法是：

> 344 条注入边里，**能判的只有 1 条**（前提全中），而**这条边没有任何 `forbid` 成员**
> ⇒ 被检查的 `forbid` 成员 **0** 个 ⇒ 违规 **0** 是"**无物可违**"，不是"查了通过"。
> 其余 343 条：95 条**判不了**（B 类）、224 条**不适用**（前提不中）、24 条**镜头没建成**。

这条限定必须跟数字一起出现——否则它就是本仓最忌的那种"**把没有证据读成证据**"。

## 六、21 次真实运行的全扫（把"只有 1 次"补掉）

`docs/evidence/` 下有审计日志 ＋ `shots.json` 的运行共 **21 次**，逐次跑诊断并压成
`sweep.all_runs.json`：

| 量 | 结果 |
|---|---|
| 分析的运行 | **21**（**20** 次真的注入了边；`20261004_chunked_long14` 的 shots 与检索事件对不上，如实记） |
| **违规 = 0 的运行** | **21 / 21**（**注意**：按 §五 的限定读——多数是"无物可违"） |
| 判不了的边（每次） | 中位数 **98.5**、最大 **107**（旧世代 6 镜的几次是 4～12） |
| 生效的边（每次） | 中位数 **7.5**、最大 **20**（`20261006-long21` 只有 1） |
| 已纳入／未纳入的成员数 | 逐次 790～910 ／ 103～257 |

⇒ "违规 0"**不是某一次的偶然**；而**每次都有约 90～107 条边在构造上判不了**。
**这套执行闭环目前量到的主要不是"是否被违反"，而是"有多少东西根本比不了"。**

## 七、顺手抓出并修掉**我自己工具里的三个 bug**（都写成守门）

1. **只归一了一边**：`lens:35mm` 撞不上 `35.0` ⇒ **真违规被记成 `no_match`**（漏判比假阳性更隐蔽）；
2. **词表统计写在判定的 `continue` 之后** ⇒ 只有"生效"的边被统计，`action`/`transition`/`vfx`
   一起变成空集合、**看着像没问题**；
3. **没有建成镜头的那些边被静默跳过** ⇒ 三分之和与分母差 24 条（见 §一的口径表）。

三条的错误方向都是"**让报告更干净**"，所以必须由守门钉住。

## 八、这是诊断，不是门

没有 pass line、**没有接进** `run_tests.ps1` 的通过与否；判据/阈值/分母一个字没动；
**没有**因为这次读数改任何产品代码。守门 11 条（`tests/test_execution_closure_report.py`）。

## 九、未验证 / 边界（如实挂）

1. `action`/`transition`/`vfx` 在这 21 次里**零注入**——它们到底能不能判，**至今没有数据**。
2. §四 的 **B 类**（`pair`/`axis_side`/…）**怎么绑**没有答案；**C 类**要不要给成片加字段
   ——那两件都已提交裁定（`docs/evidence/20261007-closure-next-ruling/`）。
3. `movement` 的中英词表**只量了落差、没编别名**（编了就是新判据）。
4. `composition_rule`/`pacing`/`camera_angle` 的"区间/阈值"判据**没做**（要动先得裁定）。
5. 21 次里有 1 次（`20261004_chunked_long14`）**shots 与检索事件对不上**——原因**没查**。

## 十、轴族（判不了的最大一块）追到底：**不是"没实现"，是"没落字段"**

### 10.1 ③ 类落地之后，读数动了多少（2026-10-07 补）

裁定确认 `pair`（唯一取值 `pair:any_two` ⇒ **恒真前提**）与 `axis_topic`（**话题**）**不是条件** ⇒
本工具新增 `NOT_A_CONDITION` 把它们**忽略**（既不进"判不了"，也不参与前提匹配），
并把三种"判不了"**拆成三个桶**：`edge_indecidable`（kind 没绑定）、`edge_unbound`（**取值**没绑定）、
`edge_field_absent`（**成片侧整个字段缺席**，例如老产物没有 `axis` 那一栏）。

| 量（`20261006-long21`） | ③ 类之前 | ③ 类之后 |
|---|---|---|
| `edge_indecidable` | 95 | **32** |
| `edge_inactive` | 224 | 175 |
| `edge_field_absent` | — | **112**（`axis_side 63` ＋ `movement 49`） |
| `edge_unbound` | — | 0（本轮注入的 `axis_side` **全是 `neutral`**，而 `neutral` 是绑定的） |
| 21 次全扫的 `edge_indecidable` 中位数／最大 | 98.5 / 107 | **36.0 / 89** |

**`not_covered_kinds` 从 6 个 kind 缩到 3 个**：`headroom_policy 19`、`composition_rule 13`、
`camera_angle 13` ——正好都是裁定说"**要先有规则原文的区间**"的那一类。

`pair`/`axis_side`/`axis_topic` 各 63 个成员、对应 `AXIS_RULE` **66 条边**——是"判不了"里最大的一块。
逐条查完（`work/_peek_axis_fields.py`）：

1. **`pair` 只有一个取值 `pair:any_two`**（＝"任意两人"）——它是**作用域**，不是条件；
   **`axis_topic` 是话题**（视线轴／越轴／中性机位／关系轴／运动轴）。
   ⇒ 这两者按提案 **③ 类**处理：**不该参与判定**（第一版把它们的 `class` 写成 `B`（成片缺字段）是错的，
   已改成 `C-topic`；守门 `test_topics_are_not_counted_as_missing_film_fields`）。
2. **`axis_side` 才是真的缺字段，而"实现"早就在库里**：
   `block_director/cinema/axis.py::camera_side_of`（`:136`，叉积 Z 符号 → `±1/0`）与
   `axis_status`（`:452`，→ `correct`/`neutral`/`crossed`）**就是 R001 在用的那套**；
   `20261006-long21` 的审计日志里有 **120 条 R001 判词带逐镜数字**
   （"…该待在第 **-1** 侧、实际在第 **+1** 侧"）。
   缺的只有两件：① `shots.json` 里**没有机器可读字段**（只有散文 `axis_note`，64 镜全非空）；
   ② 索引的 `left`/`right`/`neutral` 与产品的 `±1/0` 之间**命名约定未定**。
   ⇒ 这两件都属"要不要动"（加字段＝新功能；定约定＝新判据），**已提交裁定**
   （`docs/evidence/20261007-axis-family-ruling/`）。

**现在这一版清单里的口径**（`fixtures/closure_uncovered_kinds.json`）：
`B` ＝ 已注入＋成片无字段（要判就得先加字段）；`C-topic` ＝ 已注入但**它不是条件**。
