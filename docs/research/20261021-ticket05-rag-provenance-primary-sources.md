# BlockDirector Ticket 05：RAG 消费与 provenance 一手依据

日期：2026-10-21

范围：BM25/Lucene/Elasticsearch 的检索语义、W3C PROV、OpenTelemetry GenAI
retrieval 语义约定，以及 RAG 检索质量与溯源研究。

用途：为 `.scratch/blockout-quality-closed-loop/issues/05-rag-consumption-and-provenance.md`
提供依据。本文明确区分“外部规范或论文直接支持的事实”与“BlockDirector 的工程裁决”。
BlockDirector 当前没有声明兼容 W3C PROV 或 OpenTelemetry，也没有把本项目事件结构称为
官方标准。

## 1. 取证方法与边界

本轮按以下口径核验：

1. BM25 原始综述从 DOI/Crossref 元数据核验；实现语义以 Apache Lucene API 文档和
   Elasticsearch 官方参考为准；
2. provenance 数据模型以 W3C Recommendation 为准，不把博客或框架文档抬成规范；
3. OpenTelemetry GenAI 以当前官方 semantic-conventions-genai 仓库和 OpenTelemetry
   成熟度规范为准，逐项区分 `Stable` 与 `Development`；
4. RAG 论文标题、作者、日期与摘要从 arXiv API 原始元数据核验；
5. 论文只支持方法学方向，不直接证明 BlockDirector 的具体字段、阈值或艺术判断。

## 2. BM25、Lucene 与 Elasticsearch

### 2.1 文献与实现事实

Robertson 与 Zaragoza 的 *The Probabilistic Relevance Framework: BM25 and Beyond*
发表于 *Foundations and Trends in Information Retrieval* 4(1-2), 1-174, 2009，
DOI [10.1561/1500000019](https://doi.org/10.1561/1500000019)。该综述把 BM25 放在
概率相关性框架中讨论，而不是把它定义成语义相似度或经过校准的相关概率。

Apache Lucene 10.3.1 的 `BM25Similarity` 文档给出：

- 默认 `k1 = 1.2`、`b = 0.75`、`discountOverlaps = true`；
- `k1` 控制词频的非线性归一化，即 term-frequency saturation；
- `b` 控制文档长度对词频分数的归一化程度；
- IDF 实现为
  `log(1 + (docCount - docFreq + 0.5) / (docFreq + 0.5))`；
- 平均字段长度实现为 `sumTotalTermFreq / docCount`。

来源：
[Lucene 10.3.1 BM25Similarity](https://lucene.apache.org/core/10_3_1/core/org/apache/lucene/search/similarities/BM25Similarity.html)。

Elasticsearch 官方参考把 BM25 列为默认 similarity，并给出与 Lucene 相同含义的
`k1` 和 `b` 参数；官方默认也是 `1.2` 与 `0.75`。来源：
[Elasticsearch similarity settings](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-modules-similarity.html)。

### 2.2 对 BlockDirector 的直接含义

- BM25 返回的是当前集合、当前 tokenization 和当前参数下的排序分数，不是“知识正确”
  或“模型已采纳”的证明。
- `top_k` 只规定最多召回多少条；它与最终进入 prompt 的条目、token 数不是同一个量。
- Lucene/Elasticsearch 的默认值与项目实现不能混写。BlockDirector 的内置
  `BM25Okapi` 路径使用 `k1=1.5`、`b=0.75`、负 IDF 的
  `epsilon * average_idf` 处理，并声明与 `rank_bm25.BM25Okapi` 同算法同参数。
  这里的 `1.5` 是项目兼容选择，不是 Lucene 默认值。

工程裁决：每次实际调用都要记录 query、top-k、实际 backend、命中 ID、预算丢弃和真正
注入的 ID/token。BM25 分数不能作为 provenance；provenance 由“哪一段文本实际进入最终
prompt”决定。

## 3. W3C PROV

### 3.1 规范事实

W3C *PROV-DM: The PROV Data Model* 是 2013-04-30 Recommendation。其摘要把 provenance
定义为关于产生数据或事物的 entities、activities 与 people 的信息，用于评估质量、可靠性
或可信度。规范的核心包括：

- `Entity`：某个时间存在的数字或物理对象；
- `Activity`：随时间发生、使用或生成 entities 的过程；
- `Agent`：对 activity、entity 或另一 agent 承担责任的行动者；
- `Generation`、`Usage`、`Derivation`：从使用/生成/派生关系连接 entities 与
  activities；
- `Bundle`：支持 provenance of provenance 的命名实例集合。

来源：
[W3C PROV-DM](https://www.w3.org/TR/prov-dm/)。

W3C *Constraints of the PROV Data Model* 进一步定义 uniqueness、event ordering、typing、
impossibility 等约束，并通过 normalization 判定实例的 validity 与 equivalence。来源：
[W3C PROV-CONSTRAINTS](https://www.w3.org/TR/prov-constraints/)。

PROV-O 给出 RDF 映射，包括 `prov:Entity`、`prov:Activity`、`prov:Agent`、
`prov:used`、`prov:wasGeneratedBy`、`prov:wasDerivedFrom` 等术语。来源：
[W3C PROV-O](https://www.w3.org/TR/prov-o/)。

### 3.2 对 BlockDirector 的工程映射

以下映射是项目设计，不是宣称当前 JSON 已满足 PROV-DM 的全部约束：

- retrieval query、数据源快照和最终 prompt block 可视为 entity；
- retrieval activity 使用 query，并生成 hit set；
- prompt assembly activity 使用实际 injected block，并生成最终 LLM prompt；
- `RetrievalEvent` 记录 activity 身份、stage/scope/shot、backend、hits、drops、
  actual injected tokens 与 prompt-block digest；
- 未进入最终 prompt 的 hit 只能出现在 `hit_*` 或 `drops`，不得出现在
  `injected_*`；
- plan、editor、coarse、detail、repair、react 的事件必须由同一 canonical ID 贯穿
  audit、knowledge trace 与 ShotEvidence。

W3C 对 validity/equivalence 的要求说明：只写“有 provenance 字段”并不够；时间、类型、
引用和派生关系必须自洽。当前项目以 schema、不可变证据 digest 和跨账本 ID 对拍实现
可验证性，但尚未实现 PROV-N/PROV-O 导出器，因此不能标成“PROV conformant”。

## 4. OpenTelemetry GenAI 与 retrieval span

### 4.1 当前成熟度

GenAI semantic conventions 已移至 OpenTelemetry 独立的
[semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai)
仓库。其 GenAI 文档当前总状态为 **Development**，不是 Stable。

OpenTelemetry 的成熟度规范说明：Development 组件的部分能力尚未到位，配置和接口可能变化，
不应视为生产稳定约定；Stable 才表示可以 general availability，并在特殊情况下才允许
破坏性变更。来源：
[OpenTelemetry maturity levels](https://raw.githubusercontent.com/open-telemetry/opentelemetry-specification/main/specification/maturity-levels.md)。

当前文档实际使用 `Development` 这一成熟度标签，不把 GenAI retrieval 写成
“Stable”或“Incubating”。本文不创造官方没有使用的状态名。

### 4.2 retrieval span 事实

当前 GenAI span 文档定义 `gen_ai.retrieval.client`：

- span 表示一次从 vector database 或 search system 检索相关信息/上下文的逻辑操作；
- `gen_ai.operation.name` SHOULD 为 `retrieval`；
- span name SHOULD 为 `{gen_ai.operation.name} {gen_ai.data_source.id}`；
- span kind SHOULD 为 `CLIENT`；
- `gen_ai.retrieval.top_k` 是请求检索器返回的最大文档数；
- `gen_ai.retrieval.query.text` 与 `gen_ai.retrieval.documents` 是 opt-in，
  documents 的可用属性为 `id` 与 `score`；
- retrieval-specific 的 `gen_ai.*` 属性均为 **Development**；
- `error.type`、`server.address`、`server.port` 等通用属性可为 **Stable**。

来源：
[OpenTelemetry GenAI spans — Retrievals](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md#retrievals)。

### 4.3 对 BlockDirector 的工程裁决

OpenTelemetry 当前没有稳定、完整且可直接照搬的“RAG 注入 provenance”标准。其 retrieval
span 可支持 operation、data source、top-k、query 与 documents 这几个通用维度，却不能
原生表达本项目需要的：

- 请求 backend 与实际 degraded backend；
- hit 与 actual injected 的区分；
- token budget 导致的 dropped ID/reason；
- prompt block SHA-256；
- plan/editor/coarse/detail/repair/react 的 stage 与 shot scope。

因此 `RetrievalEvent` 是项目内部 canonical ledger。它可以映射到 OTel 的 retrieval
operation/top-k/query/document 字段，但当前不宣称 OTel conformance。

## 5. RAG 研究与项目含义

### 5.1 Lewis et al., RAG

*Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*，arXiv
[2005.11401](https://arxiv.org/abs/2005.11401)，2020-05-22。作者为 Patrick Lewis、
Ethan Perez、Aleksandra Piktus 等。摘要明确指出：为模型决策提供 provenance，以及更新
模型世界知识，仍是开放研究问题。

支持：RAG 把参数记忆与非参数检索结合可以提高知识密集任务表现。

不支持：一次检索、一个 top-k 或一个生成回答足以证明来源可靠。

### 5.2 Self-RAG

*Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection*，
arXiv [2310.11511](https://arxiv.org/abs/2310.11511)，2023-10-17。作者为 Akari Asai、
Zeqiu Wu、Yizhong Wang、Avirup Sil、Hannaneh Hajishirzi。摘要指出：无论是否需要都
固定检索、固定注入若干段落，会降低模型可塑性，甚至产生无用回答；方法强调按需检索和
反思段落相关性。

支持：检索发生、命中与相关性必须分开观察；“检索了”不等于“应该注入”。

### 5.3 Corrective RAG

*Corrective Retrieval Augmented Generation*，arXiv
[2401.15884](https://arxiv.org/abs/2401.15884)，2024-01-29。作者为 Shi-Qi Yan、
Jia-Chen Gu、Yun Zhu、Zhen-Hua Ling。摘要指出 RAG 很依赖检索文档相关性，并用轻量
retrieval evaluator 判断检索质量、触发不同检索动作，同时过滤无关信息。

支持：检索失败、低相关和降级行为必须显式，而不是伪装成正常命中。

### 5.4 Ragas

*Ragas: Automated Evaluation of Retrieval Augmented Generation*，arXiv
[2309.15217](https://arxiv.org/abs/2309.15217)，2023-09-26。作者为 Shahul Es、
Jithin James、Luis Espinosa-Anke、Steven Schockaert。摘要把 RAG 评估拆成至少三类：
检索器是否能找出相关且集中的 context、LLM 是否忠实利用这些 context、以及生成本身
质量如何。

支持：retrieval quality、context use 与 output quality 不是同一个指标。

### 5.5 项目工程裁决

论文共同支持以下方向，但不直接规定当前字段：

1. 每次真实检索形成 canonical event，即使没有网络调用；
2. 空命中、全部 dropped 和部分 injection 都是合法、可审计结果；
3. provenance 只引用 actual injected 内容；
4. requested backend 与 actual backend 分开，degraded 不得宣称未发生的 hypergraph
   provenance；
5. plan/editor/coarse/detail/repair/react 共用同一 event ID；
6. audit、knowledge trace 与 ShotEvidence 必须能对拍 event count、IDs 和 token 汇总；
7. prompt digest 必须能证明对应注入块确实进入最终 prompt，而不是只证明检索器返回过
   一段文本。

## 6. 当前仓库证据

### 6.1 规范与实现

- `block_director/contracts/knowledge.py::RetrievalEvent`：canonical event schema，
  记录 stage/scope/shot/query/analogy/top-k/token budget、requested/actual backend、
  capability、degradation、network call、hit/injected/drop、actual token 与 block digest。
- `block_director/knowledge/retriever.py::_record_retrieval_event`：同一事件追加到
  retriever ledger，并通过 audit callback 写 JSONL。
- `KnowledgeRetriever.trace_payload()`：以 canonical events 覆盖 sidecar 上游 trace，
  输出 `retrieval_event_count` 与 `retrieval_events`。
- `block_director/layer5_orchestrator/planner.py::build_plan_payload`：plan 调用
  `block_for_plan` 后把返回块嵌入 system prompt。
- `block_director/layer5_orchestrator/editor.py::build_editor_payload`：editor 调用
  `block_for_shot(..., stage="editor")` 后嵌入 prompt。
- `block_director/layer5_orchestrator/coarse_agent.py::_knowledge_for_shots`：逐失败镜
  检索，把新增 canonical events 同时写入 proposal 的 `per_shot_events` 与 summary。
- `block_director/layer5_orchestrator/coarse_pipeline.py`：轮次复制 proposal，
  保留 knowledge provenance。
- `block_director/cinema/evidence_builder.py::_rag_for_shot`：只投影该镜事件，并派生
  event_count、hit/injected IDs 与 token 汇总。
- `block_director/layer3_engine/detail_session.py::record_evidence`：细排版本证据也走
  同一 ShotEvidence 构造器。

### 6.2 现有回归

- `tests/test_knowledge_retrieval_events.py` 已覆盖 BM25 plan/editor、hypergraph、
  空结果、全部 dropped、部分注入、digest、process-local case、sidecar 成功/失败恢复、
  错误 backend proof、repair tool context。
- `tests/test_coarse_evidence_builder.py` 已覆盖粗排 prompt 内容、trace/audit/proposal
  event ID 完全相等，以及 proposal 到 ShotEvidence 的逐镜投影。
- `tests/test_coarse_agent_proposals.py` 已覆盖多镜累计 trace 的逐镜归属。
- 仍需要补一条显式 plan/editor 合同测试：把返回注入块、prompt 中真实存在的文本和
  `injected_sha256` 串起来。
- 仍需要补一条 detail 公共接缝测试：完整 proposal event ledger 穿过 detail loop /
  session 后，进入 ShotEvidence 的 count、ID、token 与 trace/audit 完全相等。

## 7. 参考来源

1. Stephen Robertson, Hugo Zaragoza. *The Probabilistic Relevance Framework:
   BM25 and Beyond*. DOI [10.1561/1500000019](https://doi.org/10.1561/1500000019).
2. [Apache Lucene 10.3.1 BM25Similarity](https://lucene.apache.org/core/10_3_1/core/org/apache/lucene/search/similarities/BM25Similarity.html).
3. [Elasticsearch similarity settings](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-modules-similarity.html).
4. [W3C PROV-DM Recommendation](https://www.w3.org/TR/prov-dm/).
5. [W3C PROV-CONSTRAINTS](https://www.w3.org/TR/prov-constraints/).
6. [W3C PROV-O](https://www.w3.org/TR/prov-o/).
7. [OpenTelemetry GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai).
8. [OpenTelemetry GenAI retrieval spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md#retrievals).
9. [OpenTelemetry maturity levels](https://raw.githubusercontent.com/open-telemetry/opentelemetry-specification/main/specification/maturity-levels.md).
10. Patrick Lewis et al. *Retrieval-Augmented Generation for Knowledge-Intensive NLP
    Tasks*. [arXiv:2005.11401](https://arxiv.org/abs/2005.11401).
11. Akari Asai et al. *Self-RAG*. [arXiv:2310.11511](https://arxiv.org/abs/2310.11511).
12. Shi-Qi Yan et al. *Corrective Retrieval Augmented Generation*.
    [arXiv:2401.15884](https://arxiv.org/abs/2401.15884).
13. Shahul Es et al. *Ragas*. [arXiv:2309.15217](https://arxiv.org/abs/2309.15217).

## 8. 残余风险

- BM25 是词法排序，不等同于电影知识的相关性或正确性；当前评估仍需 held-out、人工抽查
  和真实运行质量证据。
- 当前 event schema 借鉴 PROV/OTel 的概念，但不是二者的正式序列化。
- `injected_sha256` 当前证明注入块文本；仍须用 prompt-content 测试证明该块被构造进最终
  LLM payload，不能从 digest 单独推断完整 prompt。
- sidecar 返回内容的自报 backend 只能作为输入证据；事件账必须继续以实际响应、实际注入
  和显式 degradation 为准。
