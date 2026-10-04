# ADR-0014 超图 / GraphRAG：不替换自研超边索引；L3 走已留适配器接缝

状态：Accepted（2026-10-06）。触发：用户裁决（2026-10-05）
「**现成的方案比自己写的成熟**」＋「github 上有方案，你有使用么？」——按 hook 的
《GitHub 复用检查》硬步骤执行：**先全量检索 → 出候选清单与许可门 → 联合会诊对拍 →
再决定**。

## 背景

项目里"RAG"分两层，**只有一层是自研的**：

* **L1/L2 超边索引**（自研）：`block_director/knowledge/hypergraph.py`（68 KB）＋
  `tools/kb_fetch/build_hypergraph.py`（134 KB）。查询是**契约串** `键=值`
  （`hypergraph.py:808`），边是**带槽位的多元边**（`allow`/`forbid`/`qualifier`
  ＋ 必填槽位 ＋ 冻结词表），产物是 `edges/nodes/rejects/vocab` ＋ 六元指纹 manifest。
* **L3 案例层**：**已经声明成 LightRAG**（`specs/config.default.yaml:27`
  `rag.cases_backend: lightrag`），并留了适配器接缝
  （`block_director/knowledge/cases.py:88 register_lightrag_adapter`）。
  当前跑的是文档写明的**降级路径**（仓库没有该依赖与索引 ⇒ `degraded=True`
  ＋ 具名 reason）。**声明是配置意图，不是运行时事实**（联合会诊纠正过这一点）。

## GitHub 复用检查（检索面与候选，原始回包在 `work/*.json`）

检索面：① GitHub repos API（8 个具名仓库）② 搜索 `hypergraph rag`
（6 条）③ 搜索 `hypergraph retrieval augmented generation`（6 条）
④ 搜索 `知识超图 rag`（**0 条**，如实记）⑤ README 形状信号（hyperedge/triple/
neo4j/向量库/embedding）⑥ `LHRLAB/HyperGraphRAG` 的许可/顶层文件/`requirements.txt`。

| owner/repo | ★ | 最近提交 | 许可 | 匹配点 | 不匹配点 |
|---|---|---|---|---|---|
| LHRLAB/HyperGraphRAG | 454 | 2026-05-12 | MIT | **超边**（非三元组） | `torch==2.3.0`、`transformers`、`hnswlib`、`nano-vectordb`、`neo4j`；无槽位/契约串 |
| HKUDS/LightRAG | 39,977 | 2026-10-03 | MIT | 活跃，**L3 已声明** | 三元组＋向量库＋**embedding** |
| microsoft/graphrag | 36,219 | 2026-09-28 | MIT | 社区摘要式全局问答 | 非逐镜契约查询；要 embedding |
| iMoonLab/Hyper-RAG | 325 | — | Apache-2.0 | 超图驱动 | 要向量库＋embedding |
| OSU-NLP-Group/HippoRAG | 4,036 | 2026-10-01 | MIT | 多跳检索 | 实体—关系图＋embedding |
| yifanfeng97/Hyper-Extract | 4,055 | — | **NOASSERTION** | 文本→超图 | **许可不明 ⇒ 不得引入** |
| Encyclomen/HGMem | 130 | — | 无 | 多跳记忆 | **无许可 ⇒ 不得引入** |

**许可门**：上表可引入的只有 MIT / Apache-2.0 那几条；NOASSERTION 与无许可的
**排除**（与仓库既有语料门同一纪律，见 `docs/knowledge/LICENSES.md`）。

## 联合会诊（`reviewed_by: llm-panel`，四栏）

`work/_panel_graphrag2/`（DeepSeek × GLM-5.3，同一份包、同一个角色，两侧都出正文；
另有一次因 bundle 3.3k token 让 GLM 的思考吃满 32k 额度而**空正文**，
按纪律记 `unparsed` 并**拆小重问**——`work/_panel_graphrag/` 是那次失败的原样留证）。
两侧**收敛到同一结论**：

* **L1/L2 不换**：五个候选没有一个以"契约串精确查询 ＋ 按 `allow`/`forbid`/`qualifier`
  槽位判形"为原生接口；换过去必须外挂槽位匹配翻译层，而那层就是现有自研匹配逻辑的
  复制品（**等于没换**），或者改门（红线）。
* **embedding 无解 ⇒ 正解是不用 embedding**：额度只有 `glm-5.3`（`embedding-*`
  不在包里），Blender 自带 Python 装不了 torch ⇒ 任何需要 embedding 的方案跑不起来。
  可行路径是**走已留接缝**做"精确契约匹配 → 标准库词法召回（bigram TF-IDF）→
  `glm-5.3` 重排"。
* **HyperGraphRAG 是"假同源"**：词对上了（超边），数据模型没对上（节点集合 vs
  命名槽位），依赖同时撞死两条硬约束 ⇒ 出局。
* **两条我原判断错的地方**（GLM 侧独有，已采纳）：
  ① "装不了 torch"限定的是 **Blender 的解释器**；sidecar 是独立进程，可用别的解释器，
  `onnxruntime` 一类轮子不依赖 torch ⇒ 我草稿里"本机不可能有本地 embedding"是**未验证的推断**，
  降级为待验证；
  ② 将来真接第三方索引有**陈旧化陷阱**：adapter 必须把 `retrieve(query, *, top_k, cases)`
  收到的 `cases` 当**唯一权威全集**并在返回前按 ID 过滤，且 `index_dir` 下的派生物
  必须以**案例集合摘要**为失效钥匙。

## 决策

1. **L1/L2 超边索引继续自研**（契约层、槽位校验、指纹留痕）——它是门③⑥⑨⑩ 与
   E3 能被机器判的前提，没有候选能原样产出它。
2. **L3 保持已声明的适配器接缝**，下一步实现**零依赖适配器**（精确契约匹配 →
   标准库词法召回 → `glm-5.3` 重排），**不引入需要 embedding 的框架**。
3. **不引入** `Hyper-Extract`（NOASSERTION）、`HGMem`（无许可）；
   **不直接替换** `HyperGraphRAG` / `Hyper-RAG` / `HippoRAG` / `microsoft-graphrag`
   （形状不同构 ＋ 依赖撞死硬约束）。
4. **命名债**：`register_lightrag_adapter` 若承载非 LightRAG 工厂，就是名不副实
   （契约其实是通用的 `(index_dir) -> adapter`）——落地时加通用别名并保留旧名。
5. **未验证清单**：本机能否在 **sidecar 的解释器**里跑一个轻量本地 embedding
   （onnxruntime 路线）——没测过，不许当结论。

## 后果

* 自研层继续承担契约与门；框架只在**接缝之后**作为可选实现出现。
* 真接第三方索引时必须遵守两条纪律（`cases` 为权威全集；摘要为失效钥匙），
  并把**许可证与出处**写进 `docs/knowledge/LICENSES.md`。
* 本 ADR 不改变任何判据/门限/阈值。

## 附：**四选一逐候选表**（2026-10-06 补，按 hook《GitHub 复用检查》④ 的固定格式）

| 候选（HEAD） | ①直接采用 | ②魔改点与量级 | ③撞了哪条本项目约束 | ④结论 | ⑤证据 |
|---|---|---|---|---|---|
| LHRLAB/HyperGraphRAG（MIT，`d587cdf8c3fe`） | 否 | 移植 `hypergraphrag/prompt.py`(351 行) 的**超边抽取提示词** ＋ `operate.py` 的 `_handle_single_hyperrelation_extraction` / `_merge_hyperedges_then_upsert` / `_merge_nodes_then_upsert`（约 300–400 行）；**槽位映射属自研** | ①运行时 `torch`/`transformers`/`neo4j`/`nano-vectordb` 进不了插件进程；②"改它去适配我们的槽位模型"＝写一层翻译器 ≈ 既有匹配逻辑（**改造量 ≈ 自研**） | **②魔改·缓议**：触发条件＝门⑨（可达性）或门⑩（`must` 可解析）成为瓶颈；**执行时第一条验收必须是 `cache_key` 指纹已变化** | `work/upstream_files.json`；`tools/kb_fetch/build_hypergraph.py:182`（`PROMPT_VERSION = "extract/v18"`）与 `:252`（八分量 cache_key） |
| HKUDS/LightRAG（MIT，`453dce83d6d0`） | 否（检索要 embedding） | **只**移植 `lightrag/prompt.py` 的**关键词抽取提示词**（运行期资产，不进构建缓存键） | 检索层 `operate.py`(7,127 行) 要 embedding；本账号无 embedding 额度 | **②魔改·可执行**（下一步）：接到 L3 适配器的"查询→关键词"一步，召回用自研 BM25、重排用 `glm-5.3`；**必须给 L3 自建小评测**（manifest 看不住运行期提示词） | `work/upstream_files.json`；接缝 `block_director/knowledge/cases.py:88` |
| microsoft/graphrag（MIT） | 否 | 社区摘要管线（要 embedding＋LLM） | 与"逐镜契约串查询"不同路 | **③弃用** | `work/graphrag_survey.json` |
| iMoonLab/Hyper-RAG（Apache-2.0） | 否 | 与 HyperGraphRAG 重叠，且 Apache 还要 NOTICE | 重叠＋依赖 | **③弃用** | `work/hypergraph_search.json` |
| OSU-NLP-Group/HippoRAG（MIT） | 否 | 实体—关系＋embedding | 形状＋依赖 | **③弃用** | 同上 |
| yifanfeng97/Hyper-Extract（**NOASSERTION**） | 否 | — | **许可门：不能复制也不能改** | **③弃用（许可）** | 同上 |
| Encyclomen/HGMem（**无许可**） | 否 | — | **许可门** | **③弃用（许可）** | 同上 |

### 附二、会诊（`work/_panel_moagai/`，两侧都出正文）对这张表的裁决

* **GLM 侧（难题攻关以它为主）**：
  * F2（**blocker**）：魔改档"跑通全套 pytest"**检测不到它最可能的失败模式**——
    移植了新提示词但没 bump 指纹的"提示词版本"分量 ⇒ 断点续跑命中旧缓存 ⇒
    **新提示词从未执行、一切照绿**。⇒ 若确要移植，**第一条验收＝manifest 指纹已变化**。
  * F1/F4：超边提示词移植**缓议**（诚实标注已自我否定其价值）；`operate.py` 的归并/去重
    **不是**漏掉的划算面——本仓归并窗口是"同 domain ＋ 一跳 related ＋ 每批 ≤8 张卡"，
    判据不同源，且改第 2 段语义必然 bump 第 7 个指纹分量、连锁翻转 E1 的代际钥匙。
  * F3：**embedding 这题不必解**——`键=值` 查询要的是谓词匹配，召回面是
    "别名归一化 ＋ BM25 ＋ `glm-5.3` 重排"；`VALUE_ALIASES` 的 540→539 是已验证杠杆。
  * F5：L3 关键词提示词**可以借**，但它是"组件内部资产"（不是"零依赖适配器"的另一种写法），
    **必须自建小评测**。
* **DeepSeek 侧**：与上表一致（移植提示词＋解析；槽位映射记自研；检索层不换）。
* 两边都同意的一条：**别为框架而框架**——当前红门是 E1 与 RK-13，不是"检索框架不够强"。

### 附三、因此**现在**执行什么（顺序）

1. **不移植**超边提示词（缓议；触发条件写在上表）。
2. **先做 L3 适配器的零依赖实现**（精确契约匹配 → 自研 BM25 召回 → `glm-5.3` 重排），
   关键词那一步**借**上游提示词（MIT，注明 commit），并给 L3 自建小评测。
3. **别名覆盖**（`VALUE_ALIASES`）作为**召回面**的独立小批次——它有实测先例（540→539），
   且零依赖、零新概念。
