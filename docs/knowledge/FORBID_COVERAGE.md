# 禁忌（forbid）召回率实测与提案（2026-10-01）

## 一、问题

规范 §2.3 的边表里，**只有 `EMOTION_PACK` 允许带 `forbid` 成员**
（`(forbid, movement|shot_size|vfx)*`），其余 12 类边一个禁忌槽位都没有。
实现忠实照做：`hypergraph.OPTIONAL_MEMBERS` 里也只有 `EMOTION_PACK` 有 `forbid` 项。

后果是**语料里绝大部分禁令进不了索引**。实测（复现：`work/_diag_forbid_recall.py`）：

```
卡片总数                              1601
正文里出现"忌/不要/避免/禁用/别用/不拍/宁/绝不/不能"的卡   278
其中真的产出了 forbid 成员的                              16   = 5.8%
上述 278 张里同时提到情绪词的                              29
全库带 forbid 成员的边                                  54 / 683
```

也就是说：**278 条明确的"不要这样拍"里，只有 16 条进了索引**；剩下 262 条的
禁令在检索期不存在，超图**无从否决**。而禁忌恰恰是这套 RAG 最有价值的一层
——规范自己也写着"禁忌是你最有价值的产出"（抽取提示第 4/10 条）。

## 二、根因不是模型不听话

抽取提示已经在反复要求写 forbid（第 4、4b、10 条），但模型面临的是一道
**结构题**：一张写着"台词段落里不要让说话者与听话者同时动作"的卡，
它表达的是**构图/调度**上的禁令，而 schema 只允许把禁令挂在情绪包上。
硬要写，就得凭空造一个情绪（`emotion=?`）——那是**编造成员**，
比不写更糟。所以模型选择了不写。

## 三、提案（规格级，实现不得自选）

把 `forbid` 从"情绪包专属"放宽为 **"该边本来就有这个槽位，就可以禁止它"**：

| 边类型 | 建议允许的 forbid | 依据（该 kind 已是它的槽位） |
|---|---|---|
| `EMOTION_PACK` | movement / shot_size / vfx（**现有**） | 现状 |
| `SHOT_PATTERN` | movement | 选填 `(allow, movement)*` |
| `STAGING_PACK` | camera_angle / shot_size | 必填/选填里都有 |
| `PERFORMANCE_PACK` | camera_angle | 必填 `(qualifier, camera_angle)` |
| `IMPACT_PACK` | movement | 必填 `(qualifier, movement)` |
| `SOUND_PACK` | sfx | 必填 `(allow, sfx)` |
| `LIGHT_PACK` | camera_angle | 选填 `(allow, camera_angle)*` |
| `TRANSITION_PACK` | transition | 必填 `(qualifier, transition)` |

配套（照旧不得放宽的地方）：

* **经验层仍然不得单独产生 forbid**（`to_edge` 里已有 `experience_cannot_forbid`），
  放宽 schema 不动这一条；
* `allow` 与 `forbid` 不得出现同一个 `node_id`（已有校验门照旧）；
* **扩充后必须同步**：门⑤/⑤b（每个 `forbid` 成员要有 ≥1 条冲突用例）、
  oracle 的 `forbid_*` 写法、`render_edge_block` 的注入文本。

## 四、预期效果与代价

* 预期：带 `forbid` 的边从 **54** 条提升到与 278 张禁令卡同量级；
  Q7（禁忌拦截率）与 Q3（负样本误命中）第一次有足够的分母。
* 代价：门⑤b 的覆盖要求随之变宽（每个 `(type, kind)` 的 forbid 都要有冲突用例），
  oracle 需要补一轮；`SCORE_WEIGHTS.forbid_hit` 的加成对象变多，需要重标定。

**结论：这是一条能显著提升安全层质量、但会改变 schema 与验收面口径的改动，
属规格裁决。实现侧把实测摆在这里，不擅自改。**

## 五、新证据（2026-10-01 语料换代之后）：标注员**一直在**写这些禁令

oracle 精准剔除那 300 条"断言了不可能存在的边"的条目时，罪名分布把上一节的
推论坐实了——**它们几乎全是 `EMOTION_PACK` 上写了 schema 不允许的 `forbid_*`**：

| 被拒的禁令 | 条数 |
|---|---|
| `forbid_pacing` | 30 |
| `forbid_lighting` | 27 |
| `forbid_camera_angle` | 21 |
| `forbid_sfx` | 18 |
| `forbid_lens` | 17 |
| `forbid_intent` / `forbid_action` / `forbid_composition_rule` | 各 12 |
| 其余（`forbid_*` 与少量普通槽位） | 合计约 100 |

也就是说：**不是模型不肯写禁忌，而是它想写的那些禁令没有合法的宿主边**——
标注员判断"这条知识是关于节奏/光线/机位/音效的禁令"，而 schema 只允许把
`forbid` 挂在情绪包上，于是要么写错（被门拒收，本次 300 条），要么干脆不写
（第一节的 5.8% 召回）。两条证据指向同一个裁决点。

代价这次是**可数的**：这 300 条被剔除后，Q7 的冲突查询从 502 掉到 **272**
（仍 ≥60，pass），也就是说**安全层最值钱的那部分覆盖掉了将近一半**。
