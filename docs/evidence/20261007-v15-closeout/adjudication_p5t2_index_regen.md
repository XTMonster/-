# 裁决备料 · P5-T2（B1：手写策展卡入索引）——**卡与代码现状不符，停手等用户**

**run-id**：20261007-v15-closeout
**HEAD**：`f6530c6e44702028c6e42a9e1d11436c0b19d1c2`
**纪律**：判据／阈值／门限一个字未动（红线 R-5）；索引一个字节未动（红线 R-8）；
**未执行任何换代动作**。本文件是 P5-T2「⚖️ 前置确认」要的那份材料，
外加一条**必须由用户裁定的差异**。

---

## §1 卡原文要求（`执行文档v1.5/EXECUTION_PLAN.md`，卡 P5-T2）

> 目标：FX-2。**动手前先向用户确认换代窗口**。
> 步骤：① 填换代登记表（前指纹）；② 扩展输入源纳入策展卡 → 重建索引 →
> 记录后指纹；③ 最小重跑：Q0–Q4/Q6b/Q7/E1 同口径；④ ACCEPTANCE_STATUS 读数板
> K1 更新为 **2353/2353**（实测后填）。
> 前提（卡文与 `AGENTS.md:58`、`OPEN_ITEMS_20261007.md` B1 同源）：
> **「132 张手写策展卡不在索引里（索引覆盖 2221/2353）」**。

## §2 实测：**这个前提在当前工作树里不成立**

### 2.1 输入侧——手写卡**早就在抽取器的输入里**

`tools/kb_fetch/build_hypergraph.py::load_cards()`（`:2001` 起）已含一段标注为
**"v1.5 修正"** 的代码：除 `knowledge/cards_generated/*.jsonl` 外，**再把
`block_director/knowledge/corpus.HANDWRITTEN_CARDS`（132 张）逐张并入**，
并为它们**合成如实的出处**（`chunk_id = curated/<id>`、span 取整段正文、
provenance 记 `权威文档`）。该代码在 **HEAD 上已提交**（`git status` 未列
`tools/kb_fetch/build_hypergraph.py` 为改动）。

⇒ 抽取器看到的卡片全集＝ `2221 生成卡 ＋ 132 手写卡 = 2353`。

### 2.2 产物侧——索引**已经在引用手写卡**

对已发货的 638 条边逐条取 `sources[]` 求并集：

| 量 | 实测 |
|---|---|
| 语料卡片全集 | **2353**（手写 132 ＋ 生成 2221） |
| **被 ≥1 条边引用的卡** | **2262** |
| **一条边都没有的卡** | **91**（其中手写 **16**、生成 **75**） |
| 引用了但不在语料里的 id（幻影） | **0** |

手写卡的旗舰硬规则（`axis_180`／`axis_cross`／`axis_30_degree_practice`／
`comp_*` 等）**都在被引用的那 116 张里**——正是卡文说"永远召不回"的那几张。

⇒ **「132 张手写策展卡不在索引里」与产物不符**：真实缺口是 **16 张手写卡
零边**，不是 132 张。

### 2.3 `2221` 这个数字是怎么被读错的（根因）

`2221` 出自 `K1_source_ref_complete`，其原文是
`tools/knowledge/quality.py` 输出的一行：

```
[pass] K1_source_ref_complete: 2221 张生成卡的 source_ref 六字段全部非空
```

它量的是 **生成卡的出处完整性**（分母 ＝ 生成卡张数 2221），**不是**
"索引覆盖了多少卡"。`AGENTS.md:58` 把它写成
"The hypergraph index covers **2,221** of those cards" ⇒ **把出处完整性
误读成索引覆盖率**。这是文档漂移，不是索引缺陷。

## §3 证据（命令 ＋ 真实输出）

```
python -c "from block_director.knowledge import corpus as c; print(len(c.HANDWRITTEN_CARDS), len(c.GENERATED_CARDS), len(c.CARDS), len(c.CARD_ID_COLLISIONS))"
132 2221 2353 0

python -c "
import json,pathlib
from block_director.knowledge import corpus
all_ids={c.id for c in corpus.CARDS}; hw={c.id for c in corpus.HANDWRITTEN_CARDS}; gen={c.id for c in corpus.GENERATED_CARDS}
src=set()
for line in pathlib.Path('knowledge/hypergraph.edges.jsonl').read_text(encoding='utf-8').splitlines():
    if line.strip(): src.update(json.loads(line).get('sources') or [])
print('corpus', len(all_ids), 'cited', len(all_ids & src), 'uncited', len(all_ids - src),
      'hw_uncited', len(hw - src), 'gen_uncited', len(gen - src), 'phantom', len(src - all_ids))"
corpus 2353 cited 2262 uncited 91 hw_uncited 16 gen_uncited 75 phantom 0

python -c "import pathlib,json;d=json.loads(pathlib.Path('knowledge/hypergraph.manifest.json').read_text(encoding='utf-8'));print(d['cards'], d['valid_unique'], d['rejects'])"
2353 638 0

grep -n "K1_source_ref_complete" docs/knowledge/ACCEPTANCE_STATUS.md
3062:[pass] K1_source_ref_complete: 2221 张生成卡的 source_ref 六字段全部非空
```

## §4 换代登记（**计划值**，按 `REGEN_LOG_TEMPLATE.md` 预填；**未执行**）

| 字段 | 值 |
|---|---|
| 触发卡 / 裁决 | 卡 P5-T2（原判据）——**前提已被 §2 证伪，是否仍做须用户裁定** |
| 换代类型 | 索引重建（若做）／**本次未做** |
| 是否需要用户点头 | **是** |

### §4.1 前指纹（2026-10-07 实测，工作树未动）

| 产物 | 值 | 命令 |
|---|---|---|
| 索引 `manifest.fingerprint` | `c796a5a87018631db54da88406a4bd352741ed346fa1e9b06293c85ef46fed67` | `python -c "import pathlib;from block_director.knowledge.hypergraph import manifest_fingerprint as f;print(f(pathlib.Path('knowledge')))"` |
| `schema_fingerprint()` | `1a90c089bb8f4f7fbd61a145a2088d6c2628ecbbd4dba47f63396fbf34fadaf3` | `python -c "from block_director.knowledge import hypergraph as h;print(h.schema_fingerprint())"` |
| 词表 `vocabulary_fingerprint` | `f72697eceed9e8d14dd886a85a3fe6c7e7aa2479f9c1de25dbe22d7e84b1fb0f` | `knowledge/hypergraph.manifest.json` 的 `cache_key` |
| 语料 `corpus_sha256` | `8b308f0bf16cba3c07a7e026724f72ede70f9716d0d5bbf3a91eb57d8a35976a` | 同上 |
| 案例层指纹 | `48df4a53c2c95637dd4150499320b1a87fab201645ec4bacec605eb3a8f44a86` | `python -c "from block_director.knowledge.cases import manifest_fingerprint as f; import pathlib; print(f(pathlib.Path('knowledge')))"` |
| held-out `holdout.sha256` | `e3e6bac24d9efcfea8c5f1b5f1f7fd65a8c9869551df52ef0fe327cb74ef8571` | `python -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('fixtures/knowledge_holdout.jsonl').read_bytes()).hexdigest())"` |
| 索引规模 | `cards 2353` / `valid_unique 638` / `rejects 0` | `knowledge/hypergraph.manifest.json` |

### §4.2 影响面（**若**用户裁定做）

* 会变：`knowledge/hypergraph.edges.jsonl` / `.nodes.jsonl` / `.manifest.json` /
  `.vocab.json`（其余"未变"须回填）。
* 会失配的消费者：本次实测 `docs/evidence/*/run_manifest.json` 共 **22 份**
  （台账口径写 23，**差 1 份，未核，不许当结论**）；若属换代，
  这 22–23 份的 `pins.index.fingerprint` 全部失配，**按模板只标"异代"、不 repin**。
* 作废读数：与语料相关的 Q1/Q2/Q4/Q6b、E1 必须同口径重跑；
  引用旧代索引的历史结论**保留但标"异代"**，**不删**。

### §4.3 最小重跑集（**若**用户裁定做）

| 门 / 读数 | 必须重跑？ | 理由 |
|---|---|---|
| 门①–⑩（`python tools/check_holdout.py --generations fixtures/knowledge_holdout.generations.json`） | 是 | 输入集合动了 |
| Q0 结构门（`tools/knowledge/quality.py`） | 是 | 结构随边集变 |
| Q1/Q2/Q4/Q6b（`tools/holdout_score.py`） | 是 | 查询面变 |
| Q5 | 是（但属人裁决项） | 同上 |
| Q7/E1/E2/E3 | 是 | 同上 |
| 构图门 / R 系列 / headless 三工程重建 | 否 | 与索引无关（**必须与 G3/G4 快照隔离单跑**） |
| 全量 `python -m pytest` | **永远是** | 换代纪律 |

### §4.4 动手时机（隔离条）

按 `EXECUTION_PLAN.md` 附录 B 第 19 条：**索引换代必须与 G3/G4 测量快照隔离
单跑**——与构图门/闭环对照同跑会把 before/after 的分母换掉，那次测量作废。
另：本版**唯一**动索引的卡就是 P5-T2。

## §5 选项（**交用户裁定；执行侧不拍板**）

* **选项 A — 按更正后的口径做**：把这些发现写回 `AGENTS.md:58` 与
  `OPEN_ITEMS_20261007.md` B1（"132 张不在索引" → "16 张零边"），
  并把 P5-T2 的目标从"覆盖 2353/2353"改成"**让那 16 张零边的手写卡拿到边
  （或如实记为不产边）**"，再决定要不要真的重建索引。
  代价：一次真换代（22–23 份 pin 失配 ＋ 最小重跑集）。
* **选项 B — 不做换代**：只修文档（AGENTS.md:58 / B1 / K1 的读法），
  把 P5-T2 记为"**前提已由产物证伪，无待办**"；省下一次换代与全部重跑。
* **选项 C — 只修那 16 张卡**：先逐张查"为什么零边"（是真没知识、
  还是抽取器漏抽），再决定；**这仍要判据/换代的裁量**，同上。

**执行侧的建议（可空，不具约束力）**：先做**选项 B 的文档修正**（零风险、
零换代），把"16 张零边手写卡"作为**新的、更小的**议题单列；索引换代是否值得
为它付 22–23 份 pin 失配的代价，请用户裁。

**注意**：P5-T2 卡文写的验收线 `2353/2353` **本身也不可达**——卡片的边是
抽取产物，一张卡完全可能**合法地**一条边都不产（生成本来就有 75 张零边）。
把"卡片被 ≥1 条边引用"设成覆盖门**属于新判据**（红线 R-5），须用户裁决，
执行侧**不许**自行设线。

## §6 完成定义对照（卡 P5-T2）

| 卡文完成定义 | 状态 |
|---|---|
| □ 登记表 | **计划值已填**（§4），动作未做 |
| □ 重建 | **未做**（⚖️ 前置未确认 ＋ 前提已证伪） |
| □ 重跑对照 | **未做** |
| □ 读数板更新 | **未做**（K1 的读法本身需更正，见 §2.3） |

**结论**：P5-T2 **停在动手之前**，符合卡文的「⚖️ 前置确认」纪律；
新增一条用户裁定项——**卡文前提与产物不符**。
