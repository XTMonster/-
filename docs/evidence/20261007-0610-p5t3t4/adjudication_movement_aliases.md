# 裁决备料 · 运镜别名表（清单 B4 ＋ G9）

**run-id**：20261007-0610-p5t3t4
**卡**：`执行文档v1.5/EXECUTION_PLAN.md` 卡 **P5-T3**（TECH_SOLUTIONS §二 B4 / §六 G9）
**性质**：⚖️ **备料件**。本文件**不改一行代码、不改一条判据、不动一次索引**（红线 R-5 / R-8）。
凡标「实测」的都有命令与输出；推断一律写「推断」，没有证据的写「未验证」。

---

## 0. 结论摘要（先给结论，证据在后）

1. **B4 的词表落差只剩一个值**：三份词表（知识索引 / 引擎 24 运镜枚举 / held-out 查询词表）
   的并集是 **25 个值**，其中 **24 个逐字等价**，唯一对不上的是中文的 **`固定`**
   （引擎侧没有 `固定`/`static` 这个枚举——"不动"在引擎里表达为 `movements` 数组里没有条目）。
2. **G9 的前提（"别名表仍不在缓存键里"）已被现行代码推翻**：缓存键第 8 个分量
   `vocabulary_fingerprint` 由 `tools/kb_fetch/vocabulary.py::lexicon_fingerprint()` 现算，
   其载荷**显式包含 `hg.VALUE_ALIASES`**（实测 20 条）。所以"改别名表 ⇒ 索引换代"这条
   在当前 HEAD 上**已经成立**。真正**没被**纳管的，是两张**消费侧**表（检索期/判定期），
   它们不进索引构建的缓存键——这不是缺陷，但必须**具名 + 版本化**（见 §4）。
3. **顺带实测到一个真实缺陷**：`hypergraph.VALUE_ALIASES` 里 `甩镜`/`甩镜头`/`whip_pan`
   三个键折向 `whip_pan`，而**索引里没有任何一个节点叫 `whip_pan`**（索引只有
   `whip_pan_left` / `whip_pan_right`）。⇒ `运镜=甩镜` 这类查询折成了一个**死值**，
   命不中任何种子，还会把 `seed_miss` 伪装成"知识库里没有"（与 P4-T5 给 `构图` 加防呆
   是同一种病）。**修它要动 `VALUE_ALIASES` ⇒ 索引换代**，所以只列清单，等用户点头。
4. **提案**（§5，只写不改）：两步——① 修 `VALUE_ALIASES` 的 1 个死值 + 补 `固定` 一族；
   ② 把三张消费侧表**指明真源 + 版本号**，并把 `VALUE_ALIASES_VERSION` 写进
   `knowledge_trace.json`。**两步都动判据输入，必须用户先裁。**

---

## 1. 实测 A：三方词表对拍（全量，不是抽样）

复算命令（只读，零网络）：

```
python docs/evidence/20261007-0610-p5t3t4/probe_movement_alias_table.py \
    --out docs/evidence/20261007-0610-p5t3t4/movement_alias_table.json
```

输出（逐字）：

```
sizes: {'knowledge_index': 25, 'engine_enum': 24, 'heldout_vocab': 25, 'union': 25}
counts_by_class: {'已等价': 24, '无对应': 1}
engine_not_in_heldout: []
heldout_not_in_engine: ['固定']
knowledge_not_in_engine: ['固定']
```

| 词表 | 来源（`文件:行`） | 取值数 | 内容 |
|---|---|---|---|
| 知识索引 | `knowledge/hypergraph.nodes.jsonl`（`type=movement`） | **25** | 24 个英文枚举 ＋ `固定` |
| 引擎枚举 | `block_director/contracts/enums.py:154-181` `Movement` | **24** | `dolly_in` … `lead_subject` |
| held-out 查询词表 | `fixtures/knowledge_holdout.vocab.json` `kinds.movement` | **25** | 24 个英文枚举 ＋ `固定` |

**唯一落差**（机器判定，分类判据写在探针文件里）：

| 值 | 索引里有节点 | 引擎枚举里有 | 查询词表里有 | `hypergraph.VALUE_ALIASES` | 判定 |
|---|---|---|---|---|---|
| `固定` | ✅（`movement:固定`，`name=固定机位`，`aliases=[固定机位, static, 静止机位]`） | ❌ | ✅ | `固定→固定`、`固定机位→固定`、`static→固定` | **无对应**（引擎侧没有这个枚举位） |
| 其余 24 个 | ✅ | ✅ | ✅ | —— | **已等价** |

> 说明："`固定` 无对应"**不是缺陷**——引擎把"不动"表达为 `movements` 数组为空。
> 真正要裁的是**成片侧**用什么写出来（见 §2）：`INSTRUCTION_TO_MOVE` 写的是英文 `static`，
> 而 `static` **不是** 24 个枚举之一。

---

## 2. 实测 B：运镜词表在库里**一共住在 7 个地方**（这才是 B4 的实质）

`rg -n "MOVEMENT_ZH|_MOVEMENT_ALIASES|VALUE_ALIASES|INSTRUCTION_TO_MOVE|MOVEMENT_TYPES"`
逐个核实后的清单：

| # | 位置 | 方向 | 取值 | 进了索引缓存键吗 |
|---|---|---|---|---|
| 1 | `contracts/enums.py::Movement`（24 个） | 引擎闭集（真源） | 英文 | 不适用（它是**目标域**） |
| 2 | `tools/kb_fetch/vocabulary.py::MOVEMENT_ZH` | 抽取期：英文枚举 → 中文同义词（25 键，含 `固定`） | 英文键 / 中文值 | ✅ **进了**（`lexicon_tables()` 机械发现全大写常量） |
| 3 | `block_director/knowledge/hypergraph.py::VALUE_ALIASES` | 查询期：任意写法 → **索引节点值** | 20 条 | ✅ **进了**（`tables["hg_value_aliases"]`，`vocabulary.py:400`） |
| 4 | `layer5_orchestrator/scene_contract.py::_MOVEMENT_ALIASES` | 计划期：计划值 → **查询词表**写法 | 5 条（`static/fixed/静止机位/固定机位/locked/locked_off → 固定`） | ❌ **没进**（消费侧） |
| 5 | `layer1_input/shotlist.py::INSTRUCTION_TO_MOVE` | 剧本"拍摄手法" → **成片侧**取值 | 10 条（`固定 → static`） | ❌ 没进 |
| 6 | `tools/knowledge/execution_closure_report.py::VALUE_ALIASES` | 判定期：知识侧 → **成片侧** | 2 条（`固定/固定机位 → static`），`VALUE_ALIASES_VERSION = 1` | ❌ 没进（判定侧，自带版本号） |
| 7 | `fixtures/knowledge_holdout.vocab.json` `kinds.movement` | held-out 查询词表（带 `_fingerprint`） | 25 个 | ❌（夹具，另有指纹） |

**三个方向同时存在**（同一份"运镜词表"，三种规范侧）：

* 索引侧规范值 = **中文 `固定`**（表 3）；
* 查询侧规范值 = **中文 `固定`**（表 4）；
* 成片侧规范值 = **英文 `static`**（表 5、表 6）。

这不是"缺别名表"，而是**别名表有好几张、各朝自己那边折**。风险形状与 `hypergraph.py`
开头记的两个前例（S0 的 qualifier 洞、S1a 的 sidecar 手抄字面量）**完全一样**：
改一张、忘另一张，而一切照绿。

---

## 3. 实测 C：G9（"别名表不在缓存键里"）**已被现行代码推翻**

```
python -c "from tools.kb_fetch import vocabulary as V; \
           t=V.lexicon_tables(); print(sorted(t)); print(V.lexicon_fingerprint())"
```

输出（逐字）：

```
lexicon_tables keys: ['ACTIONS', 'AXIS_TOPICS', 'CAMERA_ANGLES', 'COMPOSITION_RULES_ZH',
 'DELIVERIES', 'EMOTIONS', 'EXTRA_VFX', 'GENRE_ZH', 'HOLDOUT_CAP', 'HOLDOUT_KINDS',
 'LIGHTING', 'MOVEMENT_ZH', 'MUSIC_STRATEGIES', 'PACING_ZH', 'PROPS', 'SFX',
 'SHOT_SIZE_NAMES', 'UNQUERYABLE_KINDS', 'VFX_TYPES', 'VFX_ZH',
 'grounding_negation_cues', 'hg_value_aliases']
fingerprint: f72697eceed9e8d14dd886a85a3fe6c7e7aa2479f9c1de25dbe22d7e84b1fb0f
hg.VALUE_ALIASES in tables: True
n aliases covered: 20
```

生产者：`tools/kb_fetch/vocabulary.py:400`（`tables["hg_value_aliases"] = dict(hg.VALUE_ALIASES)`），
消费点：`tools/kb_fetch/build_hypergraph.py` 的 `CACHE_KEY_FIELDS` 第 8 个分量
（`vocabulary_fingerprint`），另有守门 `tests/test_lexicon_inputs.py:91`
（"改否定词表 ⇒ 指纹必动"）。

**所以 G9 的结论要改写成**：索引构建的缓存键**已经**覆盖 `hg.VALUE_ALIASES`；
没被覆盖的是**消费侧两张表**（表 4 / 表 6）。它们不影响"索引怎么建"，所以**不该**塞进
索引缓存键（塞了会让每次改词表都白重建一次索引）；正确做法是**给它们一个显式版本号并写进
运行痕迹**，让"这一轮用的是哪版别名表"可查——见 §5 第 2 步。

---

## 4. 实测 D：一个真实死值（**建议随 B4 一起修**）

```
python -c "..."   # 复算：把 VALUE_ALIASES 的每个 target 拿去 nodes 全表里找
alias targets with NO node of any type: ['whip_pan']
```

* `hypergraph.VALUE_ALIASES` 有 3 个键折向 `whip_pan`：`甩镜`、`甩镜头`、`whip_pan`；
* 索引里**没有任何节点**的 `value` 是 `whip_pan`（只有 `whip_pan_left` / `whip_pan_right`）；
* 后果：`运镜=甩镜` 折成一个不存在节点 ⇒ 0 种子 ⇒ 该查询的 `seed_miss` 无法与
  "知识库里真没有"区分（§2.3b 的教训、`tests/test_scene_contract_query_vocab.py` 的整份成因）。

> 分类：**这是缺陷，不是判据问题**。但修它要改 `VALUE_ALIASES` ⇒ 改它会让第 8 个缓存分量变
> ⇒ **索引换代**（R-8）。所以按纪律：**只列清单，不落地**。

---

## 5. 提案（只写不改；落地前必须用户点头）

### 第 1 步：修 `hypergraph.VALUE_ALIASES`（**换代**动作）

建议 diff（`block_director/knowledge/hypergraph.py:470-478`）：

```
 # 现状（缺陷：折向不存在的节点）
-    "甩镜": "whip_pan", "甩镜头": "whip_pan", "whip_pan": "whip_pan",
 # 建议：折向右摇（`甩镜` 的常见用法）——**或**两条都留、由用户裁方向
+    "甩镜": "whip_pan_right", "甩镜头": "whip_pan_right",
+    "甩镜左": "whip_pan_left", "甩镜右": "whip_pan_right",
 # `固定` 一族（表 2 的中文同义词，查询里会出现）
+    "静止机位": "固定",
```

**待裁点**：`甩镜` 折左还是折右？影库里 `甩镜` 没有方向信息，而索引侧是**有方向的**
（left/right）。三条选项：(a) 折右（多数人的默认手向）；(b) 两条都发（一个查询值 → 两个
种子）；(c) 保持不折并显式记 `vocab_miss`。**这是判据级选择，不由执行侧拍板。**

**影响面**（换代的代价，按 A6 模板预填）：

* 缓存键第 8 分量会变 ⇒ 索引指纹变 ⇒ `knowledge/hypergraph.manifest.json` 换代；
* 已入库的 **23 份运行**的 `run_manifest.json.pins` 会失配，须标"异代"，**不许 repin 洗白**；
* 最小重跑：Q0–Q4 / Q6b / Q7 / E1（同口径）；
* 边本身**逐字节不变**（别名表只在检索期折名，不改抽取），所以"边数不变"是可预期的。

### 第 2 步：消费侧两张表**具名 + 版本化**（不换代）

* 表 6 已有 `VALUE_ALIASES_VERSION = 1`（`tools/knowledge/execution_closure_report.py:96`），
  已满足"具名、版本化、可复核"；
* 表 4（`scene_contract._MOVEMENT_ALIASES`）**没有版本号**。建议把它的版本号与
  `execution_closure_report.VALUE_ALIASES_VERSION` **放同一个常量**（或让前者 import 后者
  的方向表），并把该版本号写进每轮的 `knowledge_trace.json`；
* 只加自述字段，**不参与任何计算**（与 `_reason_19`/`_reason_13` 那批"只写不算"字段同一纪律）。

**为什么这条不换代**：它改的是"运行痕迹里多一行版本号"，不改任何取值、不改任何判据。

---

## 6. 影响面与工作量对照

| 动作 | 是否换代 | 改动面 | 需要重跑 | 风险 |
|---|---|---|---|---|
| 第 1 步（修 `VALUE_ALIASES`） | **是** | 1 个文件 4 行 | Q0–Q4/Q6b/Q7/E1 同口径 | 23 份 pin 失配；边不变但检索结果会变 |
| 第 2 步（消费侧版本化） | 否 | 2 个文件（1 常量 + 1 自述字段） | 不需要 | 几乎为零 |
| 不动作（维持现状） | —— | —— | —— | `甩镜` 查询继续恒为空；三张表继续可能各改各的 |

**建议顺序**：先做第 2 步（零风险、立刻让"这轮用的是哪版别名表"可查），
第 1 步等用户裁 `甩镜` 方向后再与下一次语料重建**同批**执行（避免为 4 行单独换一次代）。

---

## 7. 证据指针与复算命令

| 内容 | 位置 |
|---|---|
| 三方对拍表（机器可读） | `docs/evidence/20261007-0610-p5t3t4/movement_alias_table.json` |
| 对拍探针（只读） | `docs/evidence/20261007-0610-p5t3t4/probe_movement_alias_table.py` |
| 缓存键第 8 分量生产者 | `tools/kb_fetch/vocabulary.py:400`、`:406-434` |
| 缓存键契约（八格） | `tools/kb_fetch/build_hypergraph.py:244-252`、`:275-299` |
| 词表入指纹的守门 | `tests/test_lexicon_inputs.py:91` |
| 判定侧别名表（带版本） | `tools/knowledge/execution_closure_report.py:93-96` |
| 计划侧别名表（无版本） | `block_director/layer5_orchestrator/scene_contract.py:60-63` |
| 成片侧取值来源 | `block_director/layer1_input/shotlist.py:95-100` |
| B4 原始条目 | `docs/knowledge/OPEN_ITEMS_20261007.md` §二 B4、§六 G9 |

复算：

```
python docs/evidence/20261007-0610-p5t3t4/probe_movement_alias_table.py
python -c "from tools.kb_fetch import vocabulary as V; print(sorted(V.lexicon_tables()))"
```

## 8. 未验证 / 边界

* **未做**：任何索引重建、任何 `VALUE_ALIASES` 修改、任何 pin 变更（本卡是备料）。
* **未量**：`甩镜` 查询在真实运行里出现几次（要跑真跑才有分母）——所以第 1 步的
  收益目前只有"死值被修掉"这一条**定性**结论，**定量收益未验证**。
* **未裁**：`固定` 在成片侧到底该不该有一个枚举位（现状是 `static` 只存在于
  `INSTRUCTION_TO_MOVE` 与判定侧别名表，不在 `MOVEMENT_TYPES`）。如果用户希望
  "不动"成为一等公民，那是**引擎闭集扩位**（另一次换代），不在本备料的范围里。
