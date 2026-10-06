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
