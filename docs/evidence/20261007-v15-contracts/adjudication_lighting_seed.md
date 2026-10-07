# 裁决项：`光线=` 检索种子没有闭集可依（FR-3 的检索通路）

**性质**：⚖️ **须用户裁决**。执行方**只备料**，不动判据、不动索引、不改 schema。
**触发**：执行文档 v1.5 卡 **P4-T5**（TDD §5.7 / FR-3「灯光语义轨」）在落地时
撞到与卡文不符的现状。按 README 规则 4（"差异属于判据/门槛的一律升级"）停下备料。

---

## 1. 问题

TDD §5.7 要求：

> `add("光线", [plan.environment.light 的 time_of_day/mood 组合取值])`——
> **先核对 `VALUE_DOMAINS["lighting"]` 的闭集**，取值不在闭集内就不写。

**实测**：`VALUE_DOMAINS` 里**根本没有 `lighting` 这个键**。

```
python -c "from block_director.knowledge import hypergraph as h; print('lighting' in h.VALUE_DOMAINS)"
-> False
print(sorted(h.VALUE_DOMAINS))
-> ['applies_to_genre','applies_to_shot_size','avg_shot_len','axis_side','beat_type',
    'carry_shots','composition_rule','example_shot','genre','headroom_policy',
    'intensity','intent','pacing','pair','scene_type','seq_phase','transition']
```

而 `lighting` **是** `NODE_TYPES` 的成员，索引里也有真节点：

```
python -c "from block_director.knowledge import hypergraph as h; print('lighting' in h.NODE_TYPES)"
-> True
# knowledge/hypergraph.nodes.jsonl 里 kind=lighting 的节点数
-> 9
```

⇒ `VALUE_DOMAINS` 不是"所有 kind 的允许取值表"，它只登记**需要闭集的那部分
kind**（qualifier 与少数内容 kind）；`lighting` 的词表只存在于 **索引**里。

## 2. 为什么不能"就地补一个闭集"

1. 往 `VALUE_DOMAINS` 加键，等于改 `schema_fingerprint()` 的输入 ⇒ 改**冻结仪器**
   （`tests/plan_v4_instruments.sha256.json` 的 `block_director/knowledge/hypergraph.py`），
   且门⑨（"取值必须落在覆盖面里"）的**收不收**语义随之变化 ⇒ 属判据面（R-5/R-6）。
2. 计划侧灯光语义（`time_of_day ∈ {day,night,dusk,dawn}`、`mood ∈
   {bright,neutral,gloomy,tense,soft}`）与知识侧的 `lighting` 词表
   （高调／低调／冷光／暖光／正面光／侧光／逆光／顶光／底光）**不是同一套词**，
   "编别名表"= **新判据**，与清单 B4（movement 别名）同一形状。
3. 相关：`LIGHT_PACK` 有 13 个 `forbid` 成员 ⇒ 它也是阶段门 **G4**
   （`forbid_members_seen > 0`）最自然的杠杆；所以这条裁决定 G4 能不能成立。

## 3. 选项与代价

| 选项 | 做法 | 代价 | 不做的后果 |
|---|---|---|---|
| **A（现状，已落地）** | 按 §5.7 原文：**没有闭集就不写** `光线=`。种子永远不发 | 零风险、零判据改动 | FR-3 的**检索通路是死的**（灯光语义只到渲染预设，不进检索）；G4 少一个杠杆 |
| **B** | 在**检索期**加一张 `LIGHT_ALIASES`（计划语义 → 知识词表），只写折得到的值；**不动** `VALUE_DOMAINS`、不动索引 | 需要用户裁定"别名表"这一新判据（B4 同批） | —— |
| **C** | 把 `lighting` 加进 `VALUE_DOMAINS`（索引侧换代 + 冻结仪器重签 + 门⑨重跑） | 最重：索引换代 ⇒ 23 份运行 pin 全失配（须走 A6 登记）；冻结仪器第二十九次重签 | —— |

## 4. 建议（可空）

**建议先 B 后 C**：B 只动检索期、可当场验证"种子真的从 0 变成非 0"，且为 G4
提供 `forbid` 计数；C 应并进下一次语料重建一起做（与 B4 别名表同批），
免得单独换代一次。

## 5. 证据指针

- `block_director/knowledge/hypergraph.py`：`VALUE_DOMAINS`（无 `lighting`）、
  `NODE_TYPES`（有 `lighting`）、`QUERY_KEYS["光线"] == "lighting"`。
- `knowledge/hypergraph.nodes.jsonl`：`kind=lighting` 的 9 个节点。
- `block_director/layer5_orchestrator/scene_contract.py`：P4-T5 的接线（构图已发，
  光线按"不在闭集就不写"保持不发）。
- 同样口径的另一条车道记录：`docs/evidence/20261007-054900-p5t1/zero_member_kinds.md`。
