# 证据索引 · P5-T3 / P5-T4（裁决备料合集）

**run-id**：20261007-0610-p5t3t4
**HEAD**：`f6530c6`（＋本版未提交改动）
**执行者**：子 agent `docs_prep_p5t3_p5t4`
**纪律**：红线 R-5（判据/阈值/门限一个字没动）、R-8（不动索引、不 reseed pin）、
R-9（证据落盘，区分"实测/推断/未验证"）。**本卡是 ⚖️ 备料：零代码改动、零索引改动。**

## 1. 交付物

| 卡 | 交付物 | 位置 |
|---|---|---|
| **P5-T3**（B4 + G9） | 运镜别名表三方对照 + 缓存键纳管核查 + 提案 | `docs/evidence/20261007-0610-p5t3t4/adjudication_movement_aliases.md` |
| ↳ | 只读对拍探针 | `docs/evidence/20261007-0610-p5t3t4/probe_movement_alias_table.py` |
| ↳ | 机器可读对拍结果 | `docs/evidence/20261007-0610-p5t3t4/movement_alias_table.json` |
| **P5-T4**（B2） | `axis_side` 双路线影响面对照 | `docs/evidence/20261007-0610-p5t3t4/adjudication_axis_side_domain.md` |
| **P5-T4**（A3） | 评委口径对齐方案 v1（rubric 锚点/术语表/20 条校准流程） | `docs/knowledge/JUDGE_ALIGNMENT_v1.md` |
| **P5-T4**（A5） | R1/R5/D10/D11 四条裁决包 | `docs/evidence/20261007-0610-p5t3t4/adjudication_pack.md` |

## 2. 实测读数（命令 + 输出）

```
python docs/evidence/20261007-0610-p5t3t4/probe_movement_alias_table.py \
    --out docs/evidence/20261007-0610-p5t3t4/movement_alias_table.json
-> sizes: {'knowledge_index': 25, 'engine_enum': 24, 'heldout_vocab': 25, 'union': 25}
-> counts_by_class: {'已等价': 24, '无对应': 1}
-> heldout_not_in_engine: ['固定']   knowledge_not_in_engine: ['固定']

python -c "from tools.kb_fetch import vocabulary as V; print(sorted(V.lexicon_tables()))"
-> [... 'MOVEMENT_ZH', ... 'grounding_negation_cues', 'hg_value_aliases']    # 别名表已进缓存键
-> V.lexicon_fingerprint() = f72697eceed9e8d14dd886a85a3fe6c7e7aa2479f9c1de25dbe22d7e84b1fb0f
-> n aliases covered: 20

# VALUE_ALIASES 的目标值里，索引（nodes.jsonl，180 个节点）里没有的只有一个：
-> alias targets with NO node of any type: ['whip_pan']
```

## 3. 两条**与来源文档不一致**的发现（如实记录，未自行改设计）

1. **G9 的前提被推翻**：清单/技术方案写"词表（别名表）仍不在缓存键里"，
   实测 `tools/kb_fetch/vocabulary.py:400` 已把 `hg.VALUE_ALIASES` 机械收进第 8 个
   缓存分量。⇒ 该条**已不成立**；剩下的是两张**消费侧**表没有版本号（建议具名+版本化）。
2. **B2 的推荐前提被推翻**：`TECH_SOLUTIONS.md` 推荐"路线 B（检索期映射层）先行"，
   而 `docs/evidence/20261007-axis-family-ruling/axis_convention_calibration.json`
   量出的正是"左/右 → 符号"这件事，结论是**不一致**。⇒ 路线 B 今天只能绑 `neutral`；
   `left/right` 的落地要先回答"知识侧 left/right 指谁的左"。

## 4. 顺带实测到的真实缺陷（已在备料里列清单，未动手）

`hypergraph.VALUE_ALIASES` 的 `甩镜` / `甩镜头` / `whip_pan` 三个键折向 `whip_pan`，
而索引里没有 `whip_pan` 这个节点（只有 `whip_pan_left` / `whip_pan_right`）
⇒ `运镜=甩镜` 是**死值**。修它要动 `VALUE_ALIASES` ⇒ **换代**，故只列清单待裁。

## 5. 未做（明确边界）

* 未改任何代码、未改任何判据/阈值/门限、未重建索引、未动任何 `pins`；
* **未跑** A3 的 20 条评委校准（本会话进程内 `GLM_API_KEY` 未继承；
  卡文规定 GLM 不可用即"只出文档不跑校准"）；
* **未发起** GLM-5.3 裁决调用（A5 的四条属用户/GLM 裁决，执行侧只做路由与格式化）。

## 6. 未验证 / 剩余风险

* `甩镜` 查询在真实运行里出现的频次**未量**（要真跑才有分母）⇒ 修死值的收益只有定性结论；
* 路线 A 换代后 Q1/Q2/Q5/E1 的**净影响未量**（要重建索引才量得到）；
* A3 的"0.27 来自提示词缺锚点"是**推断**，校准本身就是为了验证它，**尚未验证**。
