# 换代登记模板（REGEN LOG TEMPLATE）

**谁用**：任何一次**触发换代**的动作——改 `knowledge/hypergraph.edges.jsonl`
（删边/加边/重建）、改 held-out 夹具、改 `knowledge/cases.*`、改冻结仪器。
**对应**：清单 A6（`docs/knowledge/OPEN_ITEMS_20261007.md` §一）＋ 执行文档 v1.5
卡 P5-T1（`执行文档v1.5/EXECUTION_PLAN.md` 阶段 5）＋ 红线 **R-8**。

**为什么必须有它**（2026-10-07 实测的连带后果）：**删一条边就等于换代**——
`knowledge/hypergraph.manifest.json` 的 `fingerprint` 变 ⇒ 已入库运行的
`run_manifest.json.pins.index.fingerprint` **全部失配**（`tools/extract_run_evidence.py --check`
会判「这份运行不是这一代索引跑的」）。这个仓库**不许把换代洗成「没换行」**：
`repin()` 只对「旧 pin 恰好等于该文件现在的裸字节哈希」这一种情形重签
（那是 CRLF/LF 口径差），内容真变了就 `skipped` 并让 `--check` 如实报 STALE。

**怎么用**：

1. 动手**之前**先把 §1–§4 填到「计划值」，把「影响面」和「最小重跑集」钉死；
2. 动手**之后**回填 §3 的「后指纹」与 §4 的实测读数，**不达预期就如实记负结果**；
3. 每次换代在 `docs/knowledge/REGEN_LOG.md` 追加一节（本文件只是**骨架**；
   该账本目前**还不存在**——第一次真换代时由执行者创建，编号从 `REGEN-0001` 起）；
4. 判据/阈值/门限**一个字不许动**（R-5）；本模板只登记事实，不裁决。

> 现成的先例：门⑦ `gen1 → gen2`（`fixtures/knowledge_holdout.generations.json`
> 的 `generations[2]`）。见本文 **附录 A**——那是「输入集合变了就是换代、
> 但夹具字节未动」的标准形状。

---

## REGEN-____ ｜ <一句话标题>

| 字段 | 值 |
|---|---|
| 日期 | YYYY-MM-DD |
| 执行者 | （主线 / 子 agent 名） |
| 触发卡 / 裁决 | 例：卡 P5-T2｜`docs/knowledge/ADJUDICATIONS_v4.md:NN` |
| 换代类型 | 索引重建 / 删边 / 加边 / 夹具改写 / 案例层重建 / 仪器重签 |
| 是否需要用户点头 | 是 / 否（涉及判据或"须用户点头"条目时为**是**） |

### §1 换代原因（必填）

* **要解决什么**：（一句话；引用清单条目或裁决原文）
* **为什么必须换代**：（不换代行不行——写清"不换代的代价"）
* **为什么是现在**：（与 G3/G4 测量快照的隔离关系；见附录 B 的隔离条）

### §2 影响面

* **会变的产物**：`knowledge/hypergraph.edges.jsonl` / `knowledge/hypergraph.nodes.jsonl`
  / `knowledge/hypergraph.manifest.json` / `knowledge/hypergraph.vocab.json` /
  `knowledge/cases.*` / `fixtures/knowledge_holdout*` / `tests/plan_v4_instruments.sha256.json`
  —— 逐项打勾，没变的写"未变"。
* **会失配的消费者**：已入库运行的 `pins.index.fingerprint` /
  `pins.cases.fingerprint` / `pins.holdout.sha256` / `pins.third_party`。
  实测份数：`__` 份（命令见 §5）。
* **哪些读数作废**：逐条列（例：与语料相关的 Q1/Q2/Q4/Q6b 必须重新判；
  `docs/evidence/` 里引用旧代索引的结论**保留但标"异代"**，**不删**）。

### §3 前后指纹

| 产物 | 前 | 后 | 命令 |
|---|---|---|---|
| 索引 `manifest.fingerprint` | `____` | `____` | `python -c "import pathlib;from block_director.knowledge.hypergraph import manifest_fingerprint as f;print(f(pathlib.Path('knowledge')))"` |
| `schema_fingerprint()` | `____` | `____` | `python -c "from block_director.knowledge import hypergraph as h;print(h.schema_fingerprint())"` |
| 词表 `vocabulary_fingerprint` | `____` | `____` | `knowledge/hypergraph.manifest.json` 的 `cache_key` |
| 案例层 | `____` | `____` | `python -c "from block_director.knowledge.cases import manifest_fingerprint as f;print(f(__import__('pathlib').Path('knowledge')))"` |
| held-out `holdout.sha256` | `____` | `____` | `python tools/extract_run_evidence.py --help` 里的摘要口径 |
| 第三方代 `third_party` | `____` | `____` | `fixtures/knowledge_holdout.generations.json` |
| 冻结仪器（如需重签） | 第 `__` 次 | 第 `__` 次 | `tests/plan_v4_instruments.sha256.json` 的 `_reason_NN` |

**换代判据**：`schema_fingerprint()` / 索引 `fingerprint` / 案例层指纹 / 夹具 sha 里
**任何一项**变了 ⇒ 就是换代，必须登记。只做 CRLF→LF 的口径重签**不算**换代
（那正是 `repin()` 的适用域）。

### §4 最小重跑集（**不许扩大、也不许缩小**）

| 门 / 读数 | 必须重跑？ | 理由 | 实测结果 |
|---|---|---|---|
| 门①–⑩（`python tools/check_holdout.py --generations fixtures/knowledge_holdout.generations.json`） | 是/否 | | |
| Q0 结构门（`tools/knowledge/quality.py`） | 是/否 | | |
| Q1/Q2/Q4/Q6b（`tools/holdout_score.py`） | 是/否 | | |
| Q5（人裁决项） | 是/否 | | |
| Q7 / E1 / E2 / E3 | 是/否 | | |
| 构图门 / R 系列 / headless 三工程重建 | 是/否 | | |
| 全量 `python -m pytest` | **永远是** | 换代必须过全量 | |

**最小**的定义：只重跑**输入被这一代替换掉**的那些读数；能证明"与该输入无关"的
读数**不要**重跑——多跑会把测量噪声当成换代信号。

### §5 pin 处置（**不许洗白**）

```powershell
# 1) 谁失配了（只读；exit 1 且逐个点名 STALE 是预期行为）
python tools/extract_run_evidence.py --check --out-dir docs/evidence/<run-id>

# 2) 口径重签（只对 CRLF/LF 这一种情形生效；内容真变了会进 skipped）
python tools/extract_run_evidence.py --repin --out-dir <同一目录>
```

* 失配的旧运行：**原样保留**，在 `generations.json` 或本表里标成 **"异代"**；
  **不**改它们的 pin 去"凑"新指纹（那是洗白，`repin()` 也会拒）。
* 需要作为**新代**读数引用的运行：按 `fixtures/knowledge_holdout.generations.json`
  追加一代（见 §6），并在 `pins.generation` 写清是哪一代。

### §6 换代注册（`fixtures/knowledge_holdout.generations.json`）

```jsonc
{
  "id": "gen<下一个编号>",
  "inputs": { "holdout": "<sha256>", "third_party": "<sha256…若适用>" },
  "transition": {
    "from": "gen<上一个>",
    "reason": "<一句话>",
    "counts": { "selected": 0, "keep": 0, "drop": 0, "flag": 0, "retry": 0 },
    "diff_note": "<夹具/索引字节到底动没动，逐字说清>",
    "pending": []
  },
  "runs": []
}
```

改完把顶层 `current` 提升到新代；`runs[]` 里登记本次在新代上跑过的运行目录名。
守门：`tests/test_gate7_generation.py`、`tests/test_run_generation_registry.py`
（"只在已记录的口径下转绿"）。

### §7 落盘与提交

* 证据目录：`docs/evidence/<run-id>-regen/`（`README.md` ＋ 本表填好的副本 ＋
  前后指纹的原始输出）。
* 报告命名沿用清单 §七 的闸门约定：涉及裁决的另写 `adjudication_<主题>.md`。
* 提交**分组**：索引/夹具产物一批、账本与证据一批、代码接线（若有）一批；
  `git status` 里不该出现"半份换代"（索引换了、账本没换）。

### §8 完成定义（勾完才算换代结束）

* [ ] §1–§4 的**计划值**在动手前写死
* [ ] §3 的前后指纹**实测**填全，且与换代判据一致
* [ ] §4 的最小重跑集**跑完**，回退/负结果**如实记录**
* [ ] §5 的失配运行**逐份**标了"异代"，**没有一份**被 repin 洗白
* [ ] §6 的注册条目已追加、`current` 已提升
* [ ] 全量 `python -m pytest` 绿；`tools/gen_golden.py --check`、
      `tools/gen_specs.py --check` 绿（若夹具动了）
* [ ] `docs/knowledge/ACCEPTANCE_STATUS.md` 的读数板（如 K1）同步
* [ ] 本表在 `docs/knowledge/REGEN_LOG.md` 里有一节

---

## 附录 A：已填样例（门⑦ `gen1 → gen2`，2026-10-07）

摘自 `fixtures/knowledge_holdout.generations.json` 的 `generations[2]`：

| 字段 | 值 |
|---|---|
| 换代类型 | 夹具**输入集合**变化（第三方代裁并入 gate 的输入） |
| 前后指纹 | `holdout` **逐位相同**（`e3e6bac2…`）；**新增** `third_party=eda380e4…` |
| 换代原因 | 合并件已过门①–⑩ 却计账 `third-party 0` ⇒ 口径不闭合 |
| counts | `selected 212 / keep 194 / drop 2 / flag 16 / retry 0` |
| pin 处置 | 链上口径由 `llm-panel 210` 变 `third-party 212`；**夹具字节未动** |
| 为什么这算换代 | 裁决原文：「输入集合变了就是换代」——**不是**因为字节变了 |

**这条样例的教学点**：换代判据是**输入集合 / 指纹**，不是"文件字节有没有动"。
反过来，只动换行口径的 `repin()` **不是**换代。

## 附录 B：两条硬边界

1. **索引换代必须与 G3/G4 测量快照隔离单跑**（`EXECUTION_PLAN.md` 附录 B 第 19 条）：
   索引重建改变检索行为与指纹；与构图门/闭环对照同跑，before/after 的分母会被换掉，
   **那次测量作废**。
2. **仪器重签要单独留痕**：`tests/plan_v4_instruments.sha256.json` 是冻结清单，
   有意改动要走"显式重新冻结 ＋ 写明理由"（该文件里已有 `_reason_1…_reason_28`
   的先例）；**判据本身**在任何情况下都不许动。
