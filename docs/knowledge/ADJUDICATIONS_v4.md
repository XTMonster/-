# 执行计划 v4 的裁决记录（D1–D9 ＋ R1–R5）

裁决人：**主线（DeepSeek）**，依据用户裁决"**人工部分尽可能你解决**"
（2026-10-05）与"**你尽管围着高质量方向做，我有很长一段时间不在家**"。

纪律：**判据／门限／阈值一个字没动**。凡是会动到判据的条目，本文只写"处置程序"，
并显式标注 `须用户点头`——主线不代替用户改红线。

| 项 | 裁决 | 是否动判据 |
|---|---|---|
| D1 新语料来源与书单 | cutoff = **1980**；清单由**实测探针**产出，见 `docs/knowledge/CORPUS_V4.md` | 否（新增判据，见 D9） |
| D2 旧卡与自撰策展卡 | **(a) 全部归档**：旧五件产物 ＋ `block_director/knowledge/cards_*.py` 的自撰策展卡一律不进新总体 | 否 |
| D3 embedding 路线 | **①本地 GPU（torch＋CUDA，已实测跑通）为首选**；②智谱 `embedding-3` 为备选（需用户开通资源包）；~~ONNX~~ 降为第三 | 否 |
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
