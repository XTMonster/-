# "知识 → 成片"的执行闭环：**没有任何东西在管**——但**naive 的补法当场就假阳性**

日期 2026-10-06 20:3x。起因是 GPT-6A 的 `c_arch` 答案第 3 条（它的原话）：

> 最疑似遗漏：**知识到 Blender 的执行闭环**。硬规则须有**适用域、对象／时间绑定和可执行判定**，
> 生成后校验，失败修复或拒绝；……**检索相关不等于镜头可用**。

这是**意见**。本目录把它变成**证据**——而且结论比"有个洞"更具体：
**照直觉补的那一刀，在第一份真实数据上立刻出错。**

## 一、结构侧：确实没人管（读码，两处）

* `block_director/layer3_engine/rule_checker.py` 里对 `knowledge` **只有一行**引用
  （`getattr(self.knowledge, "last_edges_query", "")`，是**记账**，不是判定）；
  R001–R019 全是**几何/连续性**规则，没有一条由超边的 `forbid` 驱动。
* 注入那一路（`knowledge/retriever.py`）只负责"把边渲染进 prompt"，**不产出任何断言**。

⇒ **注入 ≠ 执行**：`forbid` 成员被写进了提示词，**没有任何东西检查成片是否违反它**。

## 二、数据侧：naive 的检查**当场假阳性**（这是本目录最有价值的一条）

我写了个最直觉的检查（`probe_forbid_enforcement.py`）：

> 逐镜取**实际发出的 prompt**（§4.1b 硬规则 2 允许的通道）→ 抽出 `禁={...}` 成员；
> 再取该镜计划里的运镜 → **有交集就算违规**。

跑在**唯一一份真实长跑**（`docs/evidence/20261006-long21/`，64 镜）上，原始产物
`naive_check.json` 给出 **`shots_compared: 72`、`violations: 1`**——**一枪命中**：

```
shot: shot_005 | purpose: editor
  plan movements : [['movement', 'dolly_in']]
  injected forbid: [['movement', 'dolly_in']]
  clash          : [['movement', 'dolly_in']]
```

**但把它读仔细就不成立了。** 那一镜的完整注入块（逐字见 `shot005_block_lines.txt`）是：

```
[INTENT_PACK] intent=intent:…  shot_size=shot_size:MCU movement=dolly_in      ← 三条：MCU × dolly_in 是**被允许**的
[SHOT_PATTERN] shot_size=shot_size:MS lens=lens:35mm movement=movement:… headroom_policy=cinematic
              禁={movement:dolly_in}                                        ← 这条的**适用域是 MS**
```

而 `shots.json` 里 `shot_005` 的 **`shot_type` 是 `MCU`**。⇒ 那条 `forbid` **根本不适用于这一镜**；
我的"1 条违规"是**忽略了边的适用域**造出来的**假阳性**。

## 三、还有一条更硬的：这一跑的运镜**不是知识层决定的**

同一镜的计划是 `movements: [{'kind': 'dolly_in', 'start_frame': 1, 'end_frame': 96,
'source': 'declared'}]`——`source` 是 **`declared`**，也就是**剧本自己声明的**，
不是知识层挑的。而全片 64 镜里**只有 1 镜有运镜**（其余都是 `static`）。

⇒ 在**现有证据**上，"计划违反注入约束"这件事**连一次真冲突都还没发生过**：
样本是 1 镜，而且那一镜的运镜来自剧本声明。

## 四、结论（三句，都能对上证据）

1. **闭环确实缺**：`forbid` 只被注入、不被校验（结构侧两处引用可查）。
2. **但不能照直觉补**：任何"成员交集即违规"的检查，**必须先把边的适用域绑上**
   （上例的 `forbid` 是 **MS** 的、镜是 **MCU**）——否则**第一份真实数据就假阳性**。
   这正是 GPT-6A 原话里的"**适用域／对象-时间绑定**"，本目录用实测给了它一个具体形状。
3. **现有证据量不出风险大小**：唯一真跑 64 镜里只有 1 镜有运镜、且是剧本声明的 ⇒
   要量化"违规率"，**靠现有跑不行**，得先有**真会动镜头**的跑，或者一条**合成夹具**
   （注入一条明确适用本镜的 `forbid`，再看有没有东西拦住）。

## 五、未验证 / 边界

* **只查了 `movement` / `shot_size` 两类成员**（这是注入块里实际出现的两类）；
  `vfx` 等其它 kind 的 forbid 未涉及。
* **只跑了一份真跑**（long21）。它是当前唯一带 prompt 的真实长跑。
* 我**没有**去实现那条闭环（**这是超出 v1.4 的范围的**：文档的规则集是 R001–R019，
  没有一条说"要校验超边约束的执行"）。要不要把它做成 **诊断**（不设门）还是 **新规则 R0xx**（设门），
  是**新的选择题**——按本仓纪律应当先单列待裁，不在本轮擅自加。

---

## 六、追加：把适用域**绑上一半**之后——违规数从 **1** 跳到 **66**，而且**全来自同一条边**

第三节的假阳性说明"不绑适用域不行"。那就**绑一半试试**：`probe_forbid_apply.py`
——把**能对上的那些 kind**（`shot_size` / `movement` / `intent` ↔ 镜的 `shot_type` /
运镜 / `intent_type`）当作适用条件，并且**两边都过 `hypergraph.VALUE_ALIASES` 折到同一个规范写法**
（索引自己的别名表：`static → 固定`），然后只比对**适用**的边。原始产物 `domain_bound_check.json`：

```
{"edges_applying": 135, "violations": 66, "unbound_members": 0}
violating edge shapes: {('AXIS_RULE', ()): 66}      ← 全部是 AXIS_RULE，且 plain 成员**空**
distinct shots flagged: 63
```

**66 条**看起来像个大发现，但形状一眼就露馅：**全是 `AXIS_RULE`、而且它们的 `plain` 是空的**——
也就是说我的绑定器**没读到它们的适用条件**，于是把它们当成"无条件适用"。
原因在**渲染形式**上：`AXIS_RULE` 的成员是**质词风格**的，不是 `kind:value` 风格：

```
[SHOT_PATTERN] shot_size=shot_size:MS lens=lens:35mm movement=movement:… 禁={movement:dolly_in}
[AXIS_RULE]    pair=any_two axis_side=neutral axis_topic=…              禁={movement:…}
               └────────── 质词：我的解析器读不出"这是不是适用条件" ──────────┘
```

回到**结构化索引**（唯一真源 `knowledge/hypergraph.edges.jsonl`，638 条边）数了一下，
`AXIS_RULE` 里 forbid 在 `movement` 上的**只有 3 条**，其中真正在响的是这一条：

| edge_id | hardness / source | 成员 |
|---|---|---|
| `hg:6982a3446c7f` | **hard / theory** | `pair=any_two`、`axis_side=neutral`、`axis_topic=越轴` → **`forbid movement:固定`** |
| `hg:5f1cb7bb402c` | hard / lesson | `axis_side=right` → `forbid movement:track_left` |
| `hg:6ec001aacfd2` | hard / lesson | `axis_side=left` → `forbid movement:whip_pan_left` |

而**全片 63/64 镜都是 `static`（＝规范写法的 `固定`）** ⇒ 那条规则一旦被当成"无条件"，就会在**几乎每一镜**上响
——这正是那 66 条（跨 63 个镜）的来源。

### 这一节真正的结论（比前两节更硬）

1. **违规数完全取决于你实现了多少"适用域"**：0 层 → **1** 条（假阳性）；1 层 → **66** 条
   （仍全部来自一条**绑不上**的边）。两个数**都不是可信的违规率**。
2. 缺的不是一个 `if`，而是**一套 per-kind 的适用域语义表**：**哪些 kind 是适用条件、各自映射到成片的哪个属性**
   （`axis_side` 绑到什么？`pair=any_two` 算什么？`axis_topic` 是话题还是条件？）。
   **本仓现在没有这张表**——`REQUIRED_MEMBERS`/`OPTIONAL_MEMBERS` 只说"哪些槽位必填"，
   不说"这个槽位是不是适用条件、对着场景的哪个字段"。这就是 GPT-6A 说的"**适用域／对象-时间绑定**"
   在代码里的确切形态。
3. 另外那两条（`axis_side=right → 禁 track_left`、`axis_side=left → 禁 whip_pan_left`）**语义上完全合理**，
   只是**同样无法评估**——因为 `axis_side` 的绑定也不存在。

### 仍未验证

* 这一节只覆盖 `movement` / `shot_size` / `intent` 三类可绑定的 kind；`axis_side` 等质词的绑定**没做**，
  所以**"66 条里有几条是真违规"我答不出**——按上面第 2 条，**在语义表落地之前，这个数不可答**。
* 仍然只跑了一份真跑（long21）。
