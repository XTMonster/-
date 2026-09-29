# P14 收尾执行方案（P14-3 / P14-4 / P14-5 ＋ P14-1 的 held-out）

依据：`改进执行文档v1.4.md` §2.3 / §2.3b / §2.3c / §2.3d、§3.1–§3.3、§4.1（RK-13）、
§4.1b、§4.2、§4.4、§4.5、§5 的 P14 行、§B.2、§B.3、§6 与 `.scratch/v1.4/p14_plan.md`。
基线：`17cb959`，`python -m pytest` 全绿（1070 项），`tools/run_tests.ps1` 31 项全绿。

## 0. 现状（全量审查后的准确清单）

已完成（有代码 ＋ 有测试）：

| 项 | 证据 |
|---|---|
| L1/L2 语料 ≥900 卡、九域每域 ≥60 且 ≥5% | `knowledge/cards_generated/*.jsonl` = 943 生成 ＋ 132 手写 = 1075 |
| 超图 schema / 9 条校验门 / 去重计权 / 四步检索 / 原子注入渲染 | `block_director/knowledge/hypergraph.py` |
| 超图索引落盘 | `knowledge/hypergraph.{nodes,edges}.jsonl`（295 节点 / 168 边）、`hypergraph.manifest.json`（rejects 2.6% ≤ 5%，processed == total == 250） |
| 词表冻结 | `knowledge/hypergraph.vocab.json`、`fixtures/knowledge_holdout.vocab.json`（86 取值 / 14 kind） |
| 标注协议冻结 | `fixtures/knowledge_holdout.protocol.md` |
| 六道覆盖门校验器 | `tools/check_holdout.py`（退出码 0/1/2） |
| 两族候选 ＋ 分歧裁决 | `tools/holdout_candidates.py`、`tools/holdout_review.py` |
| `RagBackend.HYPERGRAPH`、`Capability.HYPERGRAPH`、`rag.cases_backend`、`rag.plan_prefetch_tokens`、`framing.headroom_policy` | `contracts/enums.py`、`contracts/config.py`、`specs/config.default.yaml` |
| 检索器侧的降级留痕与（本地）超图分支 | `block_director/knowledge/retriever.py`（`degraded/degraded_reason/edge_block`） |

未完成：

1. **P14-1 的 held-out**：`fixtures/knowledge_holdout.jsonl` 仍是**空文件**（0 字节），
   六道门里只有 ①②④⑤ 可判定过；③⑥ 与 ⑦（人审）**未判定**。`knowledge_holdout.cards.json`
   只有 1 个 id（调试残留）。
2. **P14-3**：`block_director/knowledge/cases.py` 不存在；`knowledge/cases.*` 不存在；
   案例层 ≥300 篇的语料与索引都没有。
3. **P14-4**：`RetrieveResponse` 只有 `cards[]`（`contracts/operations.py:56-64`）；
   `specs/openapi.yaml` 的 `capabilities.items.enum` 缺 `hypergraph`、`RetrieveResponse`
   缺 `edges[]/cases[]`；sidecar 的 `/v1/retrieve` 只回 `cards`，`/health` 不宣告 hypergraph；
   插件侧**没有** sidecar 知识客户端，`knowledge_trace.json` **从不落盘**；
   `retrieval_call` 事件**零生产者**；`--seed` / `--temperature 0` 未加。
4. **P14-5**：Q0–Q7 ＋ E1–E3 的质量闭环、`tools/ab_triple_baseline.py`、
   `tools/knowledge/sample_edges.py`、`docs/evidence/<run-id>/ab_triple.json` 全都没有。

## 1. 关键实测（本轮新增，非假设）

| 事实 | 命令 | 结果 |
|---|---|---|
| 本地 `qwen3-vl:30b` 在 `/api/chat` ＋ `think:false` 下 **content 恒空** | `python work/probe_annotate_speed.py` | `content_len=0, thinking_len=860, done_reason=length`；`think_off=true/false` 都一样 |
| 同一个模型走 `/v1/chat/completions` **有 content** | `python work/probe_annotate_openai.py` | 21–34 s / 次，`finish_reason=stop`，`completion_tokens≈1000–1600`（思考税） |
| `tools/kb_fetch/llm.py::OllamaClient` 走的正是坏端点 | `tools/kb_fetch/llm.py:130` | `f"{OLLAMA_BASE}/api/chat"` → 标注/抽取拿到空 content → `json.loads("")` 必炸 |
| Blender / DeepSeek / Ollama 三个前置都在位 | `Test-Path`、`/api/tags`、`DEEPSEEK_API_KEY` | 均在位 |

**结论**：§6 的"端点陷阱"在 `tools/kb_fetch/llm.py` 里**真实存在**，且正是 P14-1 的
held-out 跑不出来的直接原因。必须先修它，否则任何长跑都是空转。

## 2. 阶段计划（严格按序，每阶段先红后绿）

### R1 契约（P14-4 的一半，`contracts/` ＋ `specs/openapi.yaml`）

| 落点 | 动作 |
|---|---|
| `block_director/contracts/knowledge.py` | 新增 `HyperEdge` DTO（`edge_id/type/members/forbid/weight/source_span/source_kind/hardness/occurrences/confidence`）与 `Case` DTO（`case_id/case_type/title/excerpt/beat_sequence/source_ref/score`）。**`Card` 不动**（既有 `cards[]` 消费方要向后兼容） |
| `block_director/contracts/operations.py` | `RetrieveResponse` 增 `edges: List[HyperEdge] = field(default_factory=list)`、`cases: List[Case] = field(default_factory=list)`（**必须带默认值**：`tests/test_openapi_matches_contracts.py:128` 只用关键字 `cards=` 构造） |
| `specs/openapi.yaml` | `capabilities.items.enum` ＋ `hypergraph`；新增 `HyperEdge`/`Case` schema；`RetrieveResponse.properties` 增 `edges`/`cases`（`required` **不变**，向后兼容） |

先红测试：`tests/test_openapi_matches_contracts.py`（#35 的字段对拍 ＋ 样例 payload）、
`tests/test_knowledge_contracts.py`（新：往返、默认值、`members` 三元组形状）。

### R2 案例层（P14-3，`knowledge/cases.*` ＋ `knowledge/cases.py`）

| 落点 | 动作 |
|---|---|
| `block_director/knowledge/cases.py` | **新增（无 bpy）**：`CaseIndex.load()` 读 `knowledge/cases.jsonl`；三态 `lightrag`（可选适配器：`lightrag` 包可导入才用）／`hybrid`（BM25 ＋ 标签过滤，**降级路径**）／`off`；`retrieve(query, top_k)`；`render_cases(cases)` 渲染成「参考案例（仅参考）」栏；**永不产出 `forbid`**（E3 的机制侧保证） |
| `tools/kb_fetch/build_cases.py` | **新增**：从 `knowledge/sources.yaml` 的 PD 语料与 `knowledge/source_notes/*.md` 派生 **≥300** 篇案例（`case_type ∈ {narrative, sequence_pattern, lesson}`，逐篇 `source_ref`，`sequence_pattern` 带 `beat_sequence`），过许可门与去重门后落 `knowledge/cases.jsonl` ＋ `knowledge/cases.manifest.json` |
| `tools/sidecar_server.py` | 装配 `CaseIndex`，`/v1/retrieve` 回 `cases[]`；`rag.cases_backend=off` → `cases[]` 恒空且**不报错**；不可用 → `cases_degraded: true` ＋ 原因 |

先红测试：`tests/test_cases.py`（三态、渲染栏位、`beat_sequence`、E3 机制、缺索引时的降级留痕）、
`tests/test_cases_corpus.py`（≥300、逐篇 source_ref、六字段全非空、去重幂等）。

### R3 sidecar 检索面（P14-4 的另一半，落点 `tools/sidecar_server.py`）

- 启动时按 `--knowledge-dir`（默认仓库 `knowledge/`）加载超图索引与案例索引；
  索引缺失 → 能力位**不**宣告 `hypergraph`（插件据此降级并留痕）。
- `/health`：`capabilities` 含 `Capability.HYPERGRAPH`（索引可用时）。
- `/v1/retrieve`：回 `{cards[], edges[], cases[], trace{}}`；`edges[]` 是**整条**超边
  （含全部 `forbid` 成员），不再截断。
- CLI：`--temperature` 默认 **0.0**（原 0.7）、新增 `--seed`（默认 0）、`--cases-backend`、
  `--knowledge-dir`。

先红测试：`tests/test_sidecar_retrieve.py`（真起 HTTP：`/health` 的能力位两态、
`/v1/retrieve` 的三段返回、`cases_backend=off`、索引缺失时的降级）。

### R4 插件消费（`knowledge/client.py` ＋ `retriever.py` ＋ `headless_runner.py`）

| 落点 | 动作 |
|---|---|
| `block_director/knowledge/client.py` | **新增（无 bpy）**：`KnowledgeClient(transport)`，`health()` 取能力位，`retrieve(query, top_k)` 调 `/v1/retrieve` 并解析成 `RetrieveResponse`；每次调用**回调审计**（`retrieval_call` 事件的唯一生产者），并累计 `retrieval_calls` |
| `block_director/knowledge/retriever.py` | 接上 client：三栏注入（硬约束／经验建议／参考案例）、`dropped_edge_ids` ＋ `quality_fail` 按 `shot_scope`/`plan_scope` 分列、`knowledge_trace()` 完整 payload（含 `lanes`、`cases_backend`、`cases_degraded`、六元指纹引用） |
| `block_director/layer5_orchestrator/headless_runner.py` | 装配 client（`llm.sidecar` 时），把 `rag.max_tokens_per_call` / `rag.plan_prefetch_tokens` / `rag.cases_backend` 真正传下去 |
| `block_director/layer8_delivery/export_director.py` | 收尾写 `knowledge_trace.json`（每次运行必写，含降级后的空 trace） |

先红测试：`tests/test_knowledge_client.py`（真假 transport 两态、计数器、审计事件）、
`tests/test_knowledge_trace.py`（必写、分列、降级、E3）。

### R5 质量闭环（P14-5）

| 落点 | 动作 |
|---|---|
| `tools/knowledge/quality.py` | **新增**：读 held-out ＋ 索引 ＋ 可选实跑产物，算 Q0–Q7 ＋ E1–E3，**每条带分子/分母/k/聚合**，分母为 0 判失败；退出码 0/1/2；写 `docs/evidence/<run-id>/knowledge_quality.json` |
| `tools/knowledge/sample_edges.py` | **新增**：`--n 30` 抽边 → `docs/evidence/<run-id>/edge_spotcheck.jsonl` |
| `tools/ab_triple_baseline.py` | **新增**：同语料/同 top_k/同预算把超边拆成二元三元组走同一注入器，出 `dropped_forbid_members_per_query` 与 `Δ(Q2)/Δ(Q6b)` → `docs/evidence/<run-id>/ab_triple.json` |

先红测试：`tests/test_knowledge_quality.py`（Q6a 分母 ≥1、Q7 分母 0 判失败、E3 = 0）、
`tests/test_ab_triple.py`。

### R6 数据（长跑，可并行，不阻塞 R1–R5 的代码）

1. 修 `tools/kb_fetch/llm.py::OllamaClient` → 走 `/v1/chat/completions`；
   **空 content ＋ 非空 thinking 必须判该次调用失败并重试**（§6 端点陷阱的具名单测）。
2. `holdout_gen.py` 增**逐批落盘 ＋ 断点续跑**（现在只在跑完才写，1 小时崩一次全丢）。
3. 后台跑 held-out 至 **≥1200 条非试点**，过六道门（⑦人审除外）。
4. 生成 ≥300 篇案例语料（R2 的 `build_cases.py`）。

### R7 收尾

- 全量 `python -m pytest` ＋ `powershell -File tools\run_tests.ps1`（31 项）。
- 更新 `AGENTS.md` 状态段、`.scratch/v1.4/p14_plan.md`、`docs/evidence/<run-id>/`。
- **如实报告未达标项**（人审 ⑦、任何 `not_measured`），不隐瞒。

## 3. 自我审核（查漏；先于动手）

| # | 风险 | 处置 |
|---|---|---|
| 1 | `RetrieveResponse` 增字段会打红 #35 与既有构造点 | 新字段**带 `default_factory=list`**；`specs/openapi.yaml` 与数据类**同一提交**内改 |
| 2 | sidecar 在**没有**超图索引时宣告 `hypergraph` → 插件"以为能用" | 能力位由**索引是否加载成功**决定；缺索引时插件按既有逻辑降级并写 `degraded` |
| 3 | `knowledge_trace.json` 变成"被测实现自报"，用于判分＝自证 | 它是**回归留痕**，不作为 Q0–Q7 的判据；判据只读 held-out ＋ 实际注入文本（§4.1b 硬规则 2） |
| 4 | 案例层产出 `forbid` → E3 破功 | `Case` DTO **没有 `forbid` 字段**（结构上不可能），并加一条机制单测 |
| 5 | LightRAG 依赖装不上 → 默认 `lightrag` 空转 | §2.3b 明写：不可用时降级 `hybrid` 并记 `cases_degraded: true`（**这是规范内的路径，不是自创降级**）；`off` 才是显式关闭 |
| 6 | held-out 长跑崩掉 = 全丢 | 先做逐批落盘 ＋ 指纹续跑，并加单测（红→绿） |
| 7 | 本地模型产出的 `must` 取值不在词表 → 门③ 必红 | 逐批校验后**只保留过校验的条目**，未覆盖的取值交给 `sweep_unused` 补；**不降门限** |
| 8 | 门⑥"卡片集合双向相等"要求每张卡至少派生一条 | round-robin 分批（每批 ≥1 条/卡）；未覆盖的卡在报告里点名，**不静默通过** |
| 9 | 质量指标分母为 0 时恒真 | 每条比率型指标都带分母下界，分母 0 → 判失败（§4.1b 硬规则 1） |
| 10 | 删除/弱化既有测试 | 全程只**新增**断言；任何既有断言若因新契约而红，先定位是"契约真的漂了"还是"测试过时"，前者修实现、后者改测试并在提交里说明 |

## 4. 不做的事（红线）

- 不降 K1–K4、Q0–Q7、E1/E3 的任何门限来"让测试通过"。
- 不删测试、不 `--deselect`、不 `-k "not ..."`、不 `try/except` 吞错。
- 不把"人审未完成"写成通过：一律记 `not_measured` 并单独报告。
- 不在 A/B 对照跑不出来时假装结论：按 §2.3d T2 的写死规则处理并记录。
