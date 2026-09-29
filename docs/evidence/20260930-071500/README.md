# P14 收尾证据（run-id `20260930-071500`）

这一份记录 **P14-3（L3 案例层）** 与 **P14-5（质量闭环）** 在本次运行里的实际产物。
判据与门限取自 `改进执行文档v1.4.md` 的 §2.3b / §2.3c / §4.1（RK-13）/ §4.1b，
**没有放宽任何一条**。

## 1. 产物

| 文件 | 生产者 | 说明 |
|---|---|---|
| `knowledge_cases.json` | 本项目（`knowledge/cases.manifest.json` 的摘要） | 726 篇、逐类/逐域计数、去重与配额计数、体积门 |
| `edge_spotcheck.jsonl` | `python tools/knowledge/sample_edges.py --n 30` | 30 条超边的人工抽查样本（`verdict` 留空——**等人判**） |
| `knowledge_quality.json` | `python tools/knowledge/quality.py --run-id 20260930-071500` | Q0–Q7 ／ E1–E3 的当前判定（含 `not_measured`） |

## 2. 本次实测结论（先结论后证据）

**L3 案例层已落地（P14-3 完成）**：

* `knowledge/cases.jsonl` = **726 篇**（门限 ≥300），
  `narrative=653 / lesson=71 / sequence_pattern=2`；
* 逐篇 `source_ref` 六字段全非空、许可全在白名单内（K1/K2 = 100%）；
* `excerpt` 逐条过"改写而非转载"门（≤2 句、≤120 字）；
* 单文件 439 556 B（门限 512 KB），重复构建**逐字节相同**（`build_cases.py --check`）。

**质量门现状**（`knowledge_quality.json`）：

| 指标 | 判定 | 依据 |
|---|---|---|
| Q0 构建门 | **pass** | `rejects/raw ≤ 5%` 且 `processed == total`，且 manifest 的 `rejects` 与 `rejects.jsonl` 行数对得上 |
| Q1–Q7 | `not_measured` | `fixtures/knowledge_holdout.jsonl` 仍在生成长跑中（见第 3 节） |
| E3 经验越权率（索引侧） | **pass** | `source_kind=experience` 的边带 `forbid` 的条数 = 0 |
| E3 经验越权率（L3 侧） | **pass** | 案例行里没有 `forbid`/`forbids`/`constraint` 任何一个键 |
| E1 经验引用相关性 | `not_measured` | **必须人工打分**（≥4/5），agent 不能代替 |
| E2 经验采纳率 | `not_measured` | 需要一次真实运行的 `shots.json`（诊断量，不设门） |

`python tools/knowledge/quality.py` 的退出码是 **2**——按 §4.1b 硬规则 1，
"有证据缺失"**不是通过**。

## 3. 仍未完成（如实记录，不当作通过）

1. **held-out ≥1200 条**（RK-13 的前置）：`fixtures/knowledge_holdout.jsonl`
   仍在本地标注器的长跑中（`tools/holdout_fill.py`，逐批落盘 + 指纹续跑）。
   跑完之前，Q1–Q7 与 `tools/ab_triple_baseline.py` 都只能是 `INCOMPLETE`。
2. **人审 ≥120 条**（§2.3c 标注通道第 4 条 / 门⑦）：**必须由人做**；
   `tools/check_holdout.py` 的门⑦ 会拒绝 agent 自评。
3. **Q5 / Q7 / E3 的最终裁定**（§2.3c 第 5 条）：这三条衡量的是**作者意图**，
   同样只能由人做。
4. **LightRAG 真实索引**：本仓库既没有 `lightrag` 依赖、也没有它建的索引，
   因此 `rag.cases_backend=lightrag` 走的是 §2.3b **写明允许**的降级路径
   （`cases_degraded=true` ＋ `lightrag_adapter_unavailable`），
   `lightrag_index_fingerprint` 如实为空串。这是规范内的路径，不是"实现了 LightRAG"。
5. **`sequence_pattern` 只有 2 条**：判据是"同段内命中 ≥2 个节拍词且出现顺序词"，
   在"以参考书摘为主的语料"上本就稀疏。类型、词表与渲染都已接通（第三栏会印
   `序列：a→b`），但**数量偏薄**，属已知薄弱处。
