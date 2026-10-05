# 执行计划 v4 的裁决记录（D1–D9 ＋ R1–R5）

裁决人：**主线（DeepSeek）**，依据用户裁决"**人工部分尽可能你解决**"
（2026-10-05）与"**你尽管围着高质量方向做，我有很长一段时间不在家**"。

纪律：**判据／门限／阈值一个字没动**。凡是会动到判据的条目，本文只写"处置程序"，
并显式标注 `须用户点头`——主线不代替用户改红线。

| 项 | 裁决 | 是否动判据 |
|---|---|---|
| D1 新语料来源与书单 | cutoff = **1980**；清单由**实测探针**产出，见 `docs/knowledge/CORPUS_V4.md` | 否（新增判据，见 D9） |
| D2 旧卡与自撰策展卡 | **(a) 全部归档**：旧五件产物 ＋ `block_director/knowledge/cards_*.py` 的自撰策展卡一律不进新总体 | 否 |
| D3 embedding 路线 | **用户 2026-10-05 购买智谱 `embedding-3` 资源包后该路线已可用**（实测 `dim 2048`、单条 0.4 s；`embedding-2` 仍 1113）。⇒ 现状是**两条都已跑通**，可按质量对照后选：**①云端 `embedding-3`（2048 维）／②本地 torch＋CUDA（bge-small-zh，512 维）**；~~ONNX~~ 第三 | 否（但**换路线＝换一代索引**，见下） |
| D4 E1 评委 | **(a) 保持 `("deepseek-chat","glm-5.3")` 不动** | 否（改动才会动判据） |
| D5 重定标时机 | **(a)**：v3pop 读数永久标 `population=v3pop`；切换后成对重定标为 `baseline_v4` | 否 |
| D6 抽取预算上限 | **(a) 数值按 P4 的实测量更新**：输入**4,000 万** token ＋ 输出**1,200 万** token 硬顶，触顶非零退出（与单价解耦）。**依据**：P4 干跑 `python tools/kb_fetch/extract_segmented.py --corpus work/corpus_v4 --dry-run` 实测 **240 份来源 → 44,497 段 → 33,060,216 字符 ≈ 2,200 万输入 token**，原定的 2,000 万**装不下**（差约 10%）；输出按 ~150 token/段估 ≈ **670 万**，原定 200 万也不够。新值各留约 1.8 倍余量。**这是我自己定的新判据（非红线），改它只需记明依据** | 否（新增） |
| D7 旧产物归档 | **(a)**：单提交 `git mv` 进 `knowledge/_archive_v3/`，可 grep、可一键 revert | 否 |
| D8 默认路由 | **(a) 规则制**：`ΔE1(lightrag − hybrid) ≥ 噪声带 R` **且** E3=0 ⇒ lightrag 默认；否则 hybrid 默认、lightrag 可用 | 否 |
| D9 闭集扩展权限 | **(a)**：rejects 率 > **0.30** 即停并上报；扩集**单独提交**且必须让 `schema_fingerprint` 换代 | 否（红线机制本身保留） |
| R1 C6 噪声带的数值与验收地位 | 采纳 `PLAN_V4_LOOP2_DISPOSITION.md` B.1：**N＝8**、成对、降级计数＝0、噪声带 R 由同臂离散推出 | `须用户点头`（R 是否升为验收门限） |
| R2 C8 的 0.30 护栏 | 保留 0.30 作工程护栏，同时把首跑基线 `B0` 记进 manifest；`B0 > 0.30` 必须上报 | 否（新增判据） |
| R3 红线 0.70 不可达时的处置 | 按 B.6 分阶段试点（48→96→192），出"不可达信号"即**冻结读数并上报**——主线**不降线、不换分母** | `须用户点头` |
| R4 192 行评测集的迁移 | **新旧并存**：旧 192 行标 `population=v3pop`、新冻结集标 `v4pop`；跨总体一律不比较 | 否（读数纪律） |
| R5 检索契约字段 | 允许 `Case` **新增可选字段**（`score` / `chunk_ids` / `entity_hits`）并把它们纳入 `schema_fingerprint` 的纳管范围；**改既有字段语义才算法改判据** | `须用户点头`（仅"改既有语义"那一支） |

### D10（新，**须用户点头**）：某臂"召回为空"时，E1 的分母怎么算

**触发**：A/B 第一轮（2026-10-05）三臂实测的**分母不对称**——

| 臂 | 行数 | 有行的查询数 | 平均行/查询 |
|---|---|---|---|
| hybrid | 192 | **64/64** | 3.0 |
| lexical | 192 | **64/64** | 3.0 |
| lightrag | **142** | **59/64** | 2.4 |

E1 的分母是"**面板条目数**"（`tools/knowledge/e1_panel.py::summarise` 里
`len(rows)`）。当某臂对某个查询**一条都没召回**时，它**不是记 0 分，而是整行消失**
——于是召回差的臂分母更小、**每一行更值钱**。这不是同一把尺子。

**三个选项与代价**：

| 选项 | 内容 | 代价 |
|---|---|---|
| **A** 维持现状 | 分母＝实际打出来的行数 | 跨臂比较不对等；弱臂的分母会缩水（本题里小 26%） |
| **B** 固定分母 | 分母＝查询数 × top-k，召回为空**记 0 分** | 语意上更对，但它**改变历史读数的含义**（台账里的 0.1823／0.2135 都是按 A 算的）⇒ 等于动判据 |
| **C** 两者并报 | 每次面板同时给出 A 与 B 两个值，**D8 的判定读 B**，历史对照仍用 A | 多一份计算与记录；不改变任何既有读数 |

**主线建议：C**——它既不让历史数字失真，又让 D8 建立在"召回为空算失手"这件
语义正确的事上。**但这是判据级问题，按红线只能由用户拍板**，主线不自行选。

### D11（新，**须用户点头**）：把"看得见的降级"升格成"该臂无效"的机器门

**触发**：2026-10-05 的 P9 对齐跑（`work/ab_v4_aligned/`）产出了一份**格式完整**的三臂读数，
而它的三条臂里：hybrid/lexical 是在**没有中文线索层**的案例集上量的（BM25 对中文查询
近 0 命中），lightrag 是在**每请求崩一次事件循环**的服务上量的（`work/_sidecar4.err`
里 5771 行 `bound to a different event loop`）。产物如实记了
`queries_with_no_rows: 6`、每行 `zh: ""`，`CaseIndex` 也早就有
`cases_clue_state`/`cases_clues` 字段——但**没有任何门消费它们**，于是
lightrag 臂照常给出对照值 `0.0`，混进"三臂比较"里。

这条是联合会诊两侧各自独立指到的（`docs/evidence/20261005-p9-consult/`）：
"看得见的降级"没有被升格成"该臂无效"，是缺陷 A、B 能以合法产物形态存在的**共同根因**。

**选项与代价**：

| 选项 | 内容 | 代价 |
|---|---|---|
| **A** 维持现状 | 读数照出，靠人看 `clue_state` / `queries_with_no_rows` 自己判断 | 弱臂的数字会继续以合法形态进入对外结论（本项目最怕的那类静默） |
| **B** 加一道"仪器门" | 任一臂满足 `clue_state != ""`（线索层缺失/陈旧）**或** `queries_with_no_rows > 0` ⇒ 该臂这一轮标 `invalid_arm`，**不出对照值**；批终态记 `invalid` | 会改"哪些读数算数"⇒ 属判据级；且历史读数的追溯口径要一并说清 |
| **C** 两者并报 | 照出对照值，但同时在报告头部打 `instrument_warning` 与具名原因 | 不改"哪些读数算数"；但**不阻止**弱臂数字被误引 |

**主线建议：B**——它把"服务崩了/仪器缺了一件"变成**机器看得见的不出数**，而这两件事
（`clue_state` 非空、`queries_with_no_rows > 0`）都不是"检索质量差"，不该有一个数。
**但这是判据级问题，按红线只能由用户拍板**，主线不自行选。
（会诊的另一条——服务侧对"同一类不可自愈错误"加熔断——是工程护栏，不属判据，
可在用户点头前先按普通缺陷单独立项。）

## 一、D1：新语料来源（**P3 的阻塞项**）

**为什么必须换**：现役 L1/L2 共 2221 张卡，其中 1856 张（83.6%）来自 Project Gutenberg
的 1900–1920 公有领域旧书；研究目标里的"**震动与打击感**"这一整条表现轴
（hit-stop / impact frame / game feel）在该年代**根本不存在**，旧语料**结构性地覆盖不到**。

**来源纪律（不放松）**：每条必须 `http/https` ＋ 过 `tools/kb_fetch/fetch.py` 的
robots 门 ＋ `license` 在白名单内 ＋ 记 `url/title/author/license/year`。
本机已实测**不可达**的域名（`huggingface.co` 主站、`pressbooks.pub`、`archive.org`、
`doi.org`、`en.wikipedia.org`、各类 OER 站）——**不收录**，改用镜像或换馆藏。

**探测记录**：`work/modern/arxiv_v4_candidates.json`（arXiv，含许可映射与逐条验证）、
`work/ocw_v4_candidates.json`（MIT OCW 讲义 PDF）。两处都复用仓库既有探测器
（`tools/kb_fetch/find_arxiv_sources.py` / `find_ocw_sources.py`），不新造检索面。

清单冻结在 `docs/knowledge/CORPUS_V4.md`（P1 的产物之一）。

## 二、D3：embedding（**已被实测改写**）

ADR-0014 原写"本机能否跑轻量本地 embedding **未验证**"。2026-10-05 实测：

| 通道 | 实测 | 结论 |
|---|---|---|
| 智谱 `embedding-3` / `embedding-2` | 返回 1113「无可用资源包」；`GET /api/paas/v4/models` 只列 11 个**对话**模型 | 需用户开通资源包后才能用 |
| DeepSeek | `/v1/embeddings`、`/embeddings`、`/beta/embeddings` 皆 404；`GET /models` 405 | **没有 embedding 端点**，此路不通 |
| **本地 torch ＋ CUDA** | sidecar 解释器：`torch 2.5.1+cu121`、`cuda True`、`RTX 4070 Ti SUPER 16 GB`、`transformers 5.15.0`；`BAAI/bge-small-zh-v1.5` 已在 CUDA 上完成编码（`dim 512`、`ok: true`） | **已跑通，首选** |
| 本地 ONNX | `onnxruntime` **未安装**（PyPI 可达） | 降为第三，仅在前两条都不可用时考虑 |

**两条路线是两代索引**：指纹第三格写成 `<路由>:<模型>:<维度>`
（`local:bge-small-zh-v1.5:512` vs `cloud:embedding-3:2048`），换路线必然换代、
旧索引不可能被误用。`tools/lightrag_service/build_index.py::embedding_cell()` 是它的
唯一实现，守门 `tests/test_lightrag_build_index.py::test_the_embedding_cell_names_the_route_model_and_dimension`。

附录：`work/_facts_embed.md`、`work/_probe_embed.py`。

## 三、R1/R2：把"护栏"与"阈值"分开

循环 2 的 37 条 finding 里有两条 blocker 打在同一个地方：**判读线低于噪声**。
算术是硬的——原稿"|ΔE1| < 0.02 标 inconclusive"，而同一配置的同臂极差实测是
**hybrid 4/192＝0.0208、lexical 7/192＝0.0365**，两条都 ≥ 0.02。
所以 0.02 不是阈值，是掷硬币。处置（B.1）：**R 由同臂离散推出**，N＝8 写死，
只有"成对 ＋ 降级计数＝0 ＋ 单一生产者"的轮次才算有效轮。

**R 是否升为验收门限**需要用户点头（那会改验收标准的形状）；在此之前
`inconclusive` 只是读数标注，**不改任何既有门限**。

## 四、R3：红线 0.70 的可达性（**不承诺、不降线**）

现状读数带 0.18–0.23，红线 0.70 是 3 倍以上跳变。主线**不做"承诺可达"**这种没有证据的
陈述，也不降线；按 B.6 分阶段试点（48 → 96 → 192 行），任一层出"不可达信号"
即冻结当阶段读数并上报。**这是本计划里唯一可能让整个方案停下来的点，如实挂着。**

## 五、D2：为什么把自撰策展卡也归档

用户裁定"**理论不要自己写，要别人写的**"。`block_director/knowledge/cards_axis.py` /
`cards_blocking.py` / `cards_cinematography.py` / `cards_composition.py` /
`cards_performance.py` 里的卡片是本仓自撰的**策展**内容，不是他人著作。
它们进 `knowledge/_archive_v3/` 后**仍可 grep 与检索**（学习价值不丢），
但**不进新总体**、不计入 D9 的覆盖矩阵。

## 六、D12（新，**须用户点头**）：门⑦ 人审 0/212 —— 扩口径，还是你亲自补

**触发**（2026-10-05 实测；命令与录档见 `PLAN_HYPERGRAPH_v4_PROGRESS.md` 的 P11 行）：
门⑦ 现在报 `needs_human 212 / human_reviewed 0 / min_human_review 120`，而库里那
**210 条**是 `llm-panel`（`reviewed_by_class: {"llm-panel": 210}`）——门的
`accepted_reviewers` 只有 `["human"]`。

**为什么这条必须你来**：`reviewed_by` 记的是"**谁**裁的"。把 `llm-panel` 写成
`human` 就是**伪造证据**（本仓的硬红线），所以主线不许自己把它抹平——这一点上
"人工部分尽可能你解决"也越不过去。

**三个选项**：

* **A（推荐；最小的诚实解）**：你抽时间把 `docs/knowledge/HUMAN_REVIEW_SHEET.md`
  的 120 条 verdict 填掉（表格已备好，判词只需回答"这条期望是否真由该卡支持"）。
  这是唯一能**真正**让门⑦ 变绿的路。
* **B**：把门⑦ 的口径**显式**扩成 `--reviewer-classes human,llm-panel`（**动判据**，
  须你点头），并在验收文档里写明"人审由双模型复核替代"——那 210 条立刻计入。
* **C**：维持现状（门⑦ 红），P11 的"门①–⑩ 全绿"因此**不可能达成**，
  验收状态改写为"8 条绿 ＋ 3 条具名红"。

在你就此拍板之前，本仓的立场是：**继续推进能自动化的门④（标注供给）与门⑥
（卡片可表达性），门⑦ 如实红着**。

## 七、D1／P1② 的**冻结记录**（书单与语料从此有名字）

P1② 的 DoD 逐字要求："`docs/knowledge/CORPUS_v4.md` 冻结（每源 url/title/author/license/year；
四维各≥1 源；sha256 记入 `ADJUDICATIONS_v4`）"。本节的三个数字即那条 DoD 的证据
（全部可复算，命令写在 `CORPUS_V4.md` §三）：

| 冻的是什么 | 值 | 怎么复算 |
|---|---|---|
| 影子书单 | `knowledge/sources.v4.yaml`<br>`sha256 = 8f968a141f986b3461c62cac4b5822865d8c1a0a65236c1ab9325675b420a73c` | `python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('knowledge/sources.v4.yaml').read_bytes()).hexdigest())"` |
| 入库语料 | `work/corpus_v4`，240 源、`cutoff=1980`<br>`corpus_digest = 3dc686db432e2cd7727b70684f7cc88efe15dd8d29aef5264ce310e5c5861eb9`（**修掉 HTML 入库之后**的那一枚） | `work/corpus_v4/MANIFEST.json` 的 `corpus_digest`；五个字段（url/title/author/license/year）**缺项 0/240** |
| 四维 ≥1 源 | 行为动作情绪意图 **236**／镜头语言 **219**／**构图 15**／**震动与打击感 133**（另有 声音对白配乐 167、光 79） | 见 `CORPUS_V4.md` §三 的 `work/_dim_sources3.py`——维度←边型的映射取 `tools/knowledge/coverage_matrix.py`（唯一映射），段的 `seg:<digest>` 里的 digest ＝ `sha256(source_ref.sha256)[:12]`，对 240 条语料 **0 条解析不到** |

**顺带纠正一条此前的误判（本批实测推翻）**：`CORPUS_V4.md` 曾把"震动与打击感"记成
**"没有任何已验证来源／缺口"**。那句在**关键词层**成立（hit-stop／impact frame／
game feel 在 321 条来源的题名里 0 命中），但被**推广**成了"这一维没有来源"——
v4 实测**这一维有 133 个来源、412 条边**（分布在 anime 98／cinematography 26 等）。
⇒ 该维不是洞；真正最薄的是**构图**（15 来源，边 26 条）。这条已回写 `CORPUS_V4.md`。
