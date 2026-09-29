# P14 收尾方案（全量审查后重写：只列**实测为缺**的项）

基线：`8cebecd`，工作区干净（仅 `.scratch/`、`docs/evidence/<run-id>/`、`fixtures/knowledge_holdout.*`
未跟踪）。`python -m pytest` 全绿（`pyproject.toml:addopts="-q"` 叠 `-q` 会吞掉汇总行，
不是失败）。`tools/run_tests.ps1` 的 `$checks` 27 项与 `tools/blender_tests/test_*.py` 27 个**双向一致**，
`$total = 31`。

## 0. 全量审查结论（逐项实测，非印象）

已完成且**有生产者**的：`contracts/knowledge.py`（`HyperEdge`/`Case` DTO）、
`contracts/operations.py`（`RetrieveResponse.edges/cases`）、`specs/openapi.yaml`（枚举含 `hypergraph`）、
`block_director/knowledge/hypergraph.py`（9 门/去重/原子注入）、`knowledge/hypergraph.*`（295 节点/143 有效边）、
`block_director/knowledge/client.py`（`KnowledgeClient`＋`retrieval_call` 事件）、
`tools/sidecar_server.py`（`/v1/retrieve` 三通道＋`/health` 能力位由**加载结果**决定）、
`tools/knowledge/{quality,sample_edges}.py`、`tools/ab_triple_baseline.py`、
`layer5_orchestrator/headless_runner.py::_write_knowledge_trace`。

实测**仍缺**（本轮要做的全部）：

| # | 缺什么 | 证据 |
|---|---|---|
| 1 | `block_director/knowledge/cases.py` 不存在 | `Test-Path` → False；§3.1 明列为 P14 新增落点 |
| 2 | `knowledge/cases.jsonl` / `cases.manifest.json` 不存在 | 同上；L3 ≥300 篇无数据源 |
| 3 | `tools/kb_fetch/build_cases.py` 不存在 | `tools/kb_fetch/` 13 个文件里没有它 |
| 4 | 插件侧**从不注入参考案例栏** | `retriever.py` 只有 `edge_block`＋`【卡片正文补充】`；没有 `render_cases` 消费点 |
| 5 | `knowledge_trace.json` 的 `cases_backend`/`cases_degraded`/`lanes`/`lightrag_index_fingerprint` 在**无 sidecar** 的插件运行里恒缺 | `retriever.trace_payload()` 只在 `_edges_from_client` 拿到时才 merge；无 client 时是死字段 |
| 6 | `fixtures/knowledge_holdout.jsonl` = 0 字节 | `Get-Item` → 0；`knowledge_quality.json` 里 Q1–Q7 全 `not_measured` |
| 7 | 人审 ≥120 条（协议门⑦） | agent 不可代替，只能 `not_measured` |

`knowledge/hypergraph.manifest.json` 的 `rejects` 账目**已收口**（`rejects=0` 且
`hypergraph.rejects.jsonl` 0 行，Q0 实测 `pass`），AGENTS.md 里那条旧账作废。

## 1. 修改方案（按依赖顺序）

### A. `block_director/knowledge/cases.py`（新增，无 bpy）

API（**由集成方写死，所有消费点只认这套**）：

```python
CASE_TYPES = ("narrative", "sequence_pattern", "lesson")
CASE_BACKENDS = ("lightrag", "hybrid", "off")

@dataclass
class CaseIndex:
    cases: list[Case]
    requested: str = "lightrag"
    effective: str = "hybrid"
    degraded: bool = False
    reason: str = ""
    fingerprint: str = ""
    @property enabled -> bool
    def retrieve(self, query, top_k=3) -> list[Case]

def load_case_index(path: Path, backend: str = "lightrag",
                    manifest: Path | None = None) -> CaseIndex
def render_cases(cases, *, limit: int) -> str      # "【参考案例（仅参考）】…"
def case_fingerprint(cases) -> str
```

纪律：`lightrag` 适配器**只在 `lightrag` 包可导入时**才真走；否则降级 `hybrid` 并记
`cases_degraded=true`/`lightrag_adapter_unavailable`（§2.3b 的规范路径，不是自创降级）。
`off` 恒空且**不算降级**。渲染栏**永不产出约束**（`Case` DTO 结构上无 `forbid`）。

### B. `tools/kb_fetch/build_cases.py`（新增）→ `knowledge/cases.*`

从 `knowledge/sources.yaml` 的 26 个来源（22 个 PD Gutenberg ＋ 4 个 OwnWork 笔记）派生 **≥300** 篇：

- `sequence_pattern`：来自 `knowledge/source_notes/*.md` 里显式的节拍套路（带 `beat_sequence`）；
- `lesson`：来自笔记里的"禁忌/教训"条目；
- `narrative`：来自 `work/chunks.jsonl` 的许可通过语料，按"含镜头/调度的具体做法"确定性筛段，
  标题取段落首句、`excerpt` 取 ≤600 字摘要式摘录。

必须过的门（全部**不降线**）：`source_ref` 六字段 100% 非空；许可白名单 100%；
`case_type ∈ CASE_TYPES`；`case_id` 唯一；归一化 `excerpt` sha256 去重后仍 ≥300；
单文件 ≤512 KB、总 ≤20 MB；`sequence_pattern` 必须带非空 `beat_sequence`。
产出 `knowledge/cases.jsonl` ＋ `knowledge/cases.manifest.json`（来源逐条计数、门、指纹）。

### C. sidecar 复用 `cases.py`（单一真源）

`tools/sidecar_server.py` 的 `CaseLane` 改为 `from block_director.knowledge.cases import load_case_index`
的薄封装，去掉重复实现；trace 增 `lightrag_index_fingerprint`（来自 `cases.manifest.json`）。
既有 `tests/test_sidecar_retrieve.py` 的六条断言**必须原样通过**。

### D. 插件侧三栏注入

`retriever.py`：新增 `cases_block(query, *, top_k, token_limit)` → 「参考案例（仅参考）」；
`block_for_shot` / `block_for_plan` 在超图分支里按 硬约束 → 卡片正文 → 参考案例 三栏拼接；
`trace_payload()` **无条件**写 `cases_backend` / `cases_degraded` / `lanes` /
`lightrag_index_fingerprint` / `provenance`（无 sidecar 时 backend=`off`、lanes=1）。
`headless_runner.py`：把 `rag.cases_backend` / `rag.cases_top_k` 传到检索器。
`export_director.py` 已在收尾写 `knowledge_trace.json`（复核即可）。

### E. held-out（长跑，独立于 A–D）

`work/holdout.partial.jsonl` 里**已有 276 条真实 `qwen3-vl:30b` 标注**（`annotator.family=qwen`,
`independence=strong`，非试点）。缺 ~924 条。先测单批墙钟，再决定是否继续；
**未跑满就如实记 `not_measured`**，绝不把部分集当 oracle。

## 2. 测试（每阶段新增，只加不减）

| 阶段 | 新测试 |
|---|---|
| A | `tests/test_cases.py`（三态、渲染栏、beat_sequence、E3 机制、缺索引降级留痕、`render_cases` 不含约束词） |
| B | `tests/test_cases_corpus.py`（≥300、六字段 100%、许可门、去重幂等、case_type 分布、体积门） |
| C | `tests/test_sidecar_retrieve.py` 原样通过＋新增 `lightrag_index_fingerprint` 断言 |
| D | `tests/test_knowledge_trace.py` 追加：三栏、`cases_backend`/`lanes` 无条件存在、E3 |

## 3. 自我审核（查漏）

| 风险 | 处置 |
|---|---|
| A/B 并行改同一文件 | 文件集合互斥：A 只碰 `block_director/knowledge/cases.py`＋`tests/test_cases.py`；B 只碰 `tools/kb_fetch/build_cases.py`＋`knowledge/cases.*`＋`tests/test_cases_corpus.py` |
| 机械派生＝凑数 | 门②要求 excerpt 必须命中"镜头/调度/剪辑"词表且长度 ∈ [120, 600]；否则进 rejects 并在 manifest 记账 |
| sidecar 重构打红既有 6 条断言 | 先把 `load_case_index` 的行为对齐现状（`cases_index_missing`/`cases_index_unreadable:*`/`cases_index_empty`、`lightrag_adapter_unavailable`），再换实现 |
| 长跑污染 `fixtures/` | 只写 `work/holdout.partial.jsonl`；**门全过**才 promote 到 `fixtures/` |
| 新增字段让 trace 变成"自证" | trace 只做回归留痕，判据仍只读 held-out（§4.1b 硬规则 2） |

## 4. 不做的事

不降任何门限；不删/跳过/弱化既有测试；不把 `not_measured` 写成通过；
不为通过测试把 `cases.jsonl` 手改成少于 300 条或去掉 `source_ref`。
