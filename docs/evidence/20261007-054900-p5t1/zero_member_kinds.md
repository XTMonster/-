# 5 个零成员 kind 的诊断（执行文档 v1.5 / P5-T1 / FX-6 / 清单 B5）

**run-id**：20261007-054900-p5t1　**生成者**：`zero_member_kinds.py`（本文档由它逐字节生成）
**schema**：`hg/v2`　指纹 `1a90c089bb8f4f7f`　判定仪器：`gate/v2` / `extract/v18` / `corpus 8b308f0b`

**性质**：诊断。**不改任何代码与判据**（红线 R-5）；不给「该不该删」的结论，
只回答卡 P5-T1 问的那件事——这五个 kind 是**有意不用**还是**漏抽**。

## 1. 三层证据（机械，逐字节可复算）

| kind | schema 声明 | `VALUE_DOMAINS` | 词表节点 | 提示点名行 | 索引成员 | 原子边 | 原子拒收 | 判定 |
|---|---|---|---|---|---|---|---|---|
| `applies_to_genre` | qualifier ✓ | 枚举 film/anime/documentary | 3 | :445、:519 | 0 | 0 | 0 | **漏抽** |
| `applies_to_shot_size` | qualifier ✓ | 枚举 ECU/CU/MCU/MS/MLS/LS/ELS/OTS/POV | 9 | :445、:520 | 0 | 0 | 0 | **漏抽** |
| `carry_shots` | qualifier ✓ | `None`（显式不设枚举） | 0 | **未点名** | 0 | 0 | 0 | **有意延后** |
| `example_shot` | qualifier ✓ | `None`（显式不设枚举） | 0 | **未点名** | 0 | 0 | 0 | **有意不用** |
| `seq_phase` | qualifier ✓ | `None`（显式不设枚举） | 0 | **未点名** | 0 | 0 | 0 | **有意延后** |

列义：**schema 声明**＝在 `QUALIFIER_KINDS` 里；**词表节点**＝抽取器拿到的
冻结词表（`knowledge/hypergraph.vocab.json`）里 `kind:取值` 节点的条数；
**提示点名行**＝`tools/kb_fetch/build_hypergraph.py` 的 **`SYSTEM_PROMPT` 主体**
（`:374` 起的三引号块）里出现该串的行号——**源码注释里的出现不算**；
**索引成员**＝已发货的 638 条边里该 kind 的成员数；**原子边/原子拒收**＝上一段
抽取的两个中间产物（`work/hypergraph.atoms.jsonl` /
`work/hypergraph.atom_rejects.jsonl`）。

索引级佐证（`knowledge/hypergraph.manifest.json`）：`cards 2353`、`valid_unique 638`、**`rejects 0`**、`atom_rejects 464`、`merge_rejects 0`、`dangling_members_dropped 0`。
⇒ 归并期**没有**任何一条边因挂了这五个 kind 被拒（`rejects 0`、`dangling 0`）；夹在中间的 464 条原子拒收里也**一条都没有**它们（见上表最后两列）。

## 2. 逐条判定与出处

### `applies_to_genre` —— **漏抽**

* **schema**：qualifier 闭集成员；必填于 （无），选填于 ['ACTION_BEAT', 'EMOTION_PACK']；`VALUE_DOMAINS` = film、anime、documentary。
* **词表**：`kind:取值` 节点 **3** 个　⇒ 模型**有值可填**。
* **提示**：点名于 `:445`、`:519`。
* **实测产量**：索引成员 **0**、原子边 **0**、原子拒收 **0**。
* **修复点（只提案，本卡不做）**：`tools/kb_fetch/build_hypergraph.py` 的 `SYSTEM_PROMPT` 规则 1c（`:445`）只把它列进「额外成员清单」，**没有进 6b 的逐类自问表**（那张表才是决定模型「每张卡必须逐条问一遍」的那张）。候选修复＝把「这张卡的结论只在某题材成立吗？」加进 6b，并在规则 7 的闭集行（`:519`）再点名一次。**这属于改抽取提示 ⇒ 触发索引换代**，须先按 A6 登记（模板见 `docs/knowledge/REGEN_LOG_TEMPLATE.md`），本卡不执行。

### `applies_to_shot_size` —— **漏抽**

* **schema**：qualifier 闭集成员；必填于 （无），选填于 ['EMOTION_PACK', 'STAGING_PACK']；`VALUE_DOMAINS` = ECU、CU、MCU、MS、MLS、LS、ELS、OTS、POV。
* **词表**：`kind:取值` 节点 **9** 个　⇒ 模型**有值可填**。
* **提示**：点名于 `:445`、`:520`。
* **实测产量**：索引成员 **0**、原子边 **0**、原子拒收 **0**。
* **修复点（只提案，本卡不做）**：同 `applies_to_genre`：`SYSTEM_PROMPT` 规则 1c（`:445`）＋规则 7（`:520`）有它，6b 的逐类自问表没有。候选修复同上一格，**同批换代**。

### `carry_shots` —— **有意延后**

* **schema**：qualifier 闭集成员；必填于 （无），选填于 （无）；`VALUE_DOMAINS` = `None`（显式不设枚举）。
* **词表**：`kind:取值` 节点 **0** 个　⇒ 模型**无从可填**（规则 2：`node_id` 必须取自词表）。
* **提示**：**未点名**（提示词从不要求模型产出它）。
* **实测产量**：索引成员 **0**、原子边 **0**、原子拒收 **0**。
* **有意不用/延后的落地证据**：同 `seq_phase`（`hypergraph.py:139`／`:292`／`:300`，`tests/test_qualifier_lazy_keys.py:28`）。⇒ 零成员是**设计状态**。

### `example_shot` —— **有意不用**

* **schema**：qualifier 闭集成员；必填于 （无），选填于 ['TRANSITION_PACK', 'TROPE']；`VALUE_DOMAINS` = `None`（显式不设枚举）。
* **词表**：`kind:取值` 节点 **0** 个　⇒ 模型**无从可填**（规则 2：`node_id` 必须取自词表）。
* **提示**：**未点名**（提示词从不要求模型产出它）。
* **实测产量**：索引成员 **0**、原子边 **0**、原子拒收 **0**。
* **有意不用/延后的落地证据**：`改进执行文档v1.4.md:1127`：`example_shot` = 自由文本（**唯一不设枚举**的 qualifier：它是**参考资料引用**，**不参与判定**；仍必须带 `source_ref`）。⇒ 它天生不是「条件」，进不了执行闭环；且提示词从不要求它（见本报告 §2）。

### `seq_phase` —— **有意延后**

* **schema**：qualifier 闭集成员；必填于 （无），选填于 （无）；`VALUE_DOMAINS` = `None`（显式不设枚举）。
* **词表**：`kind:取值` 节点 **0** 个　⇒ 模型**无从可填**（规则 2：`node_id` 必须取自词表）。
* **提示**：**未点名**（提示词从不要求模型产出它）。
* **实测产量**：索引成员 **0**、原子边 **0**、原子拒收 **0**。
* **有意不用/延后的落地证据**：`block_director/knowledge/hypergraph.py:139` ＋ `:292`：v3/S1a 的**惰性加键**——键先进闭集（让 schema 指纹换代、让 trace 看得见），**取值域留给 S2**；`tests/test_qualifier_lazy_keys.py:28` 把「显式延后」钉住（S2 落地时那条会红，逼着人把词表写进来）。⇒ 零成员是**设计状态**。

## 3. 结论

* **漏抽（2 个）**：`applies_to_genre`、`applies_to_shot_size`。提示点名了、词表给了值、校验门也放行，但**原子层就是 0**——抽取器从未产出。修复点在抽取
  提示（把它们从「额外成员清单」提到 6b 的逐类自问表），**属改提示 ⇒ 索引换代**，
  须按 A6 登记；本卡不改。
* **有意不用（1 个）**：`example_shot`。自由文本的**参考资料引用**，天生不是条件；
  且词表里 0 个节点 ⇒ 结构性不可产。
* **有意延后（2 个）**：`seq_phase`、`carry_shots`。v3/S1a 的惰性键：键先进闭集、
  取值域留给 S2；`tests/test_qualifier_lazy_keys.py` 把「延后」钉住。

## 4. 若纳入执行闭环判定所需的**映射增量**（清单 B6 备料，只列不设门）

现行闭环诊断的映射表（**导入自** `tools/knowledge/execution_closure_report.py`，
不抄第二份）只收能**精确判等**的 kind：

```
action -> ('action_types[]',)
axis_side -> ('axis.status',)
intent -> ('intent_type',)
lens -> ('camera.lens',)
movement -> ('movements[].kind', 'declared.camera_move')
shot_size -> ('shot_type',)
transition -> ('declared.transition', 'transition_in', 'transition_out')
vfx -> ('vfx[].type',)
```

这五个 kind **一个都不在**映射表里 ⇒ 它们现在全部落进 `not_covered_kinds`
（「判不了」），**不当违规报**。若要把它们纳入判定，各自需要的增量是：

| kind | 成片侧有没有对应字段 | 需要的增量 | 性质 |
|---|---|---|---|
| `applies_to_shot_size` | 有（`shots[].shot_type`，已被 `shot_size` 用着） | 加一条绑定即可（与 `shot_size` 同字段） | ① 类，**可实现** |
| `applies_to_genre` | 无（成片侧没有题材字段） | 生成器先产 `shots[].declared.genre` | ② 类，**要新字段** |
| `example_shot` | 无 | 它是自由文本引用、**不参与判定** | ③ 类，**不该纳入** |
| `seq_phase` | 无 | 先有 S2 产取值、再谈成片侧字段 | ② 类，**依赖 S2** |
| `carry_shots` | 无 | 同 `seq_phase` | ② 类，**依赖 S2** |

**口径纪律**：本表只是「若要判、缺什么」的清单，**不是**设门提案——设门＝新判据，须用户裁决（清单 D11）。

## 5. 复算

```
python docs/evidence/20261007-054900-p5t1/zero_member_kinds.py          # 重新生成本文档
python docs/evidence/20261007-054900-p5t1/zero_member_kinds.py --check  # 与本文档对拍
```
