# 裁决备料 · `axis_side` 两套词表（清单 B2 / FX-5）

**run-id**：20261007-0610-p5t3t4
**卡**：`执行文档v1.5/EXECUTION_PLAN.md` 卡 **P5-T4**（TECH_SOLUTIONS §二 B2）
**性质**：⚖️ **备料件**。只出对照与影响面，**不改代码、不改索引、不改判据**（红线 R-5 / R-8）。

---

## 0. 结论摘要

1. **两套词表确实不相交**（除 `neutral`）：知识侧 `axis_side` 的定义域是
   `("left","right","neutral")`；成片侧 `shots[].axis` 给的是
   `status ∈ {correct, neutral, crossed}` ＋ `side_sign ∈ {+1,-1}` ＋ `pair`。
2. **但 TECH_SOLUTIONS 推荐的"路线 B（检索期映射层）先行"依赖一个前提，而这个前提
   已经被本仓库自己的校准数据推翻**：`left/right → ±1` 的映射**不是确定的**
   （同一次真跑里 `+1` 同时对上"左侧"（5）与"右侧"（1），`-1` 对上"左侧"（2））。
   ⇒ 路线 B 今天**只能绑 `neutral`**（已经绑了），`left/right` 落不了地。
3. **所以真正的待裁点不是"A 还是 B 先行"，而是先定义"知识侧的 `left/right` 到底指谁
   的什么左/什么右"**（说话人的左？观众画面的左？人物朝向的左？）。定义一天不定，
   两条路线都只能停在 `neutral`。
4. **建议**：先做**路线 B 的 `neutral` 那一半**（已落地）+ 把 `left/right` 的
   **定义问题**单独升级给用户；`left/right` 的落地（无论 A 还是 B）等定义到位再排。

---

## 1. 实测证据

### 1.1 知识侧（索引）

```
python -c "..."   # 统计 nodes.jsonl 里 type∈{axis_side,axis_topic} 的取值
```

输出（逐字）：

```
{ "('axis_side', 'left')": 1, "('axis_side', 'neutral')": 1, "('axis_side', 'right')": 1,
  "('axis_topic', '中性机位')": 1, "('axis_topic', '关系轴')": 1, "('axis_topic', '视线轴')": 1,
  "('axis_topic', '越轴')": 1, "('axis_topic', '运动轴')": 1 }
```

闭集：`block_director/knowledge/hypergraph.py:279` `"axis_side": ("left", "right", "neutral")`。
三类各有 **1 个节点**（不是"很多边各带一个"）。

### 1.2 成片侧（真跑产物）

`docs/evidence/20261007-real-axis/execution_closure.json` 的
`observed_field_domain`（逐字）：

```
"axis.status": {"correct": 33, "crossed": 29}
```

产品侧的状态定义在 `block_director/cinema/axis.py:453`：
`correct` / `neutral` / `crossed`，其中 `neutral` = 机位恰好落在轴线上、画面没有左右信息
（`AXIS_NEUTRAL = "neutral"`，`axis.py:23`）。

### 1.3 校准（**决定性的负结果**）

`docs/evidence/20261007-axis-family-ruling/axis_convention_calibration.json`，`n=23`：

```
cross_tab = { "+1 | left": 5, "+1 | mixed": 2, "+1 | other": 8, "+1 | right": 1,
              "-1 | left": 2, "-1 | other": 5 }
```

* `side_sign = +1` 的镜头里，拉片笔记说"在左侧"的 **5** 个、说"在右侧"的 **1** 个；
* `side_sign = -1` 的镜头里，说"在左侧"的 **2** 个；
* ⇒ **符号域与自然语言左右不是一一对应**。文件自己的 `note` 一句原文：
  "校准用，只看**同一镜**上标'有错 → ±1'与'散落在左右/中性'"。

同一目录的裁决包（`领域专家.json` / `实现顾问.json`）给出的处置是
**"弃 `left/right`、索引改用符号域"**——但那是**路线 A**（换代）。

### 1.4 现行判定期只绑 `neutral`

`tools/knowledge/execution_closure_report.py:84`

```python
VALUE_BINDINGS: Dict[str, Dict[str, str]] = {"axis_side": {"neutral": "neutral"}}
```

注释（`:75-79`）写明理由："`left`/`right` **不绑**（校准已证明它们跟 ±1 对不上）……
它们会落进 `premise_value_unbound` 并**逐条列出**，**绝不当成'通过了'**"。

---

## 2. 两条路线对照

### 路线 A —— 索引换代：`axis_side` 弃 `left/right`，改符号域 `+/-`

| 维度 | 内容 |
|---|---|
| 做法 | 改 `hypergraph.VALUE_DOMAINS["axis_side"]` 与索引里那 2 个节点（`left`/`right` → `+`/`-`） |
| 是否换代 | **是**（R-8）：`VALUE_DOMAINS` 是 `schema_fingerprint` 载荷的一部分（`hypergraph.py:72-73`） |
| 连带 | 索引重建 → 23 份运行的 `pins` 全失配 → 最小重跑 Q0–Q4/Q6b/Q7/E1 |
| 前提 | **要先定义 `+`/`-` 是"谁的左"** —— 见 §3；不定义就只是把歧义从中文搬到符号 |
| 收益 | 索引侧与成片侧**同域**，判定无需映射表；62 条 `unmatched` 自然消解 |
| 代价 | 一次索引换代 + 全部读数换代（不可与 G3/G4 同跑，必须隔离单跑） |

### 路线 B —— 检索期映射层（不换代）

| 维度 | 内容 |
|---|---|
| 做法 | 在 `shot_constraint_query` / `seeds_for` 侧加确定性映射（知识侧左右 → 符号） |
| 是否换代 | 否（索引不动） |
| 前提 | **同样要先定义"知识侧 left/right 是什么"**——否则映射函数写不出来 |
| 今天能做的一半 | **`neutral` 已绑**（§1.4），这一半**已经在跑** |
| 做不了的一半 | `left/right ↔ ±1` 已被 §1.3 的校准**证伪**（不是"没量"，是量了、不一致） |
| 风险 | 强行编一张表 = **新判据**（TECH_SOLUTIONS 自己也这么定性），且会把 62 条 `unmatched` 从"看得见"洗成"匹配上了"——**这是把噪声藏进通过里**，与本仓库"缺证据不得当成通过"的纪律相反 |

---

## 3. 关键反证（本备料与 TECH_SOLUTIONS 原文的分歧，必须点明）

TECH_SOLUTIONS §二 B2 写："**路线 B（不换代，推荐先行）**：检索期映射层——在
`shot_constraint_query`/`seeds_for` 侧加确定性映射（左/右 → 符号），索引不动，
62 条 unmatched 先变成'可匹配'"。

**这段与库内证据冲突**：`axis_convention_calibration.json` 量出来的正是"左/右 → 符号"
这件事，而结论是**不一致**（`+1` 同时配左侧与右侧）。因此：

* 若按 B2 原文执行，**要么**编出一张与校准矛盾的映射（自证、且把不一致藏起来），
  **要么**在实现时发现写不出来而停手；
* 仓库里已有的、由**会诊判词**支撑的处置是**弃 `left/right`**（路线 A 的形状），
  而不是补映射（路线 B 的形状）。

**遵照"缺证据不得当成通过"与"分歧必须点明"的纪律，本备料不按 B2 原文的推荐先行路线 B，
而是把分歧如实列出，交用户裁。**

---

## 4. 待裁点（唯一需要用户回答的问题）

> **知识侧的 `axis_side = left` / `right` 指的是哪一种左/右？**

| 选项 | 含义 | 可否与 `side_sign` 建立确定性映射 |
|---|---|---|
| **A** 说话人的左/右（角色本体的左） | 与镜头无关，能由角色朝向算出 | **可**（但要先确定 `side_sign` 的定义侧） |
| **B** 观众/画面的左/右 | 与机位有关，随镜头翻转 | 需要一条"翻转规则"（R001 已经在算，但那是成片侧的） |
| **C** 机位相对连线的左/右（＝ `side_sign` 的定义侧） | 与成片侧同域 | **可**，且与路线 A 的符号域天然一致 |
| **D** 不确定/维持现状 | 保留 62 条 `unmatched` 并逐条列出 | 不可（继续"判不了"） |

**建议（备料件不拍板，只给建议）**：选 **C** —— 它与成片侧的 §6.2/`axis.py` 口径同域，
落地就是路线 A 的形状（一次换代、一次读数换代），且不需要额外发明映射。
选 A/B 则会多出一层"从角色/画面左右折算到机位左右"的映射，而那一层的正确性
目前**没有任何证据**（未验证）。

---

## 5. 证据指针

| 内容 | 位置 |
|---|---|
| 校准原始数据 | `docs/evidence/20261007-axis-family-ruling/axis_convention_calibration.json` |
| 会诊判词（弃 left/right） | `docs/evidence/20261007-axis-family-ruling/{领域专家,实现顾问}.json` |
| 成片侧字段域 | `docs/evidence/20261007-real-axis/execution_closure.json` |
| 现行绑定（只绑 neutral） | `tools/knowledge/execution_closure_report.py:75-84` |
| 知识侧闭集 | `block_director/knowledge/hypergraph.py:279` |
| 产品侧状态定义 | `block_director/cinema/axis.py:23`、`:453-460` |
| B2 原文 | `docs/knowledge/OPEN_ITEMS_20261007.md` §二 B2；`执行文档v1.5/TECH_SOLUTIONS.md` §二 B2 |

## 6. 未验证 / 边界

* **未做**：任何 `VALUE_DOMAINS` / 节点 / 映射表的改动；任何索引重建。
* **未量**：路线 A 换代后 Q1/Q2/Q5/E1 的**净影响**（要重建才量得到）——所以路线 A
  "62 条 unmatched 消解"是**结构性推断**，不是实测读数。
* **未裁**：`left/right` 的定义（§4）；这是本卡唯一真正阻塞项。
