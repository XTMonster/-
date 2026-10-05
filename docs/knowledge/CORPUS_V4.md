# v4 语料清单（D1 的产物；**冻结前先读本文件的实测段**）

日期 2026-10-05。口径：`docs/knowledge/ADJUDICATIONS_v4.md` 的 D1（cutoff = **1980**）
与 D2（旧卡与自撰策展卡一律归档）。

## 一、先测量，再换料（这一步推翻了"缺现代来源"的诊断）

只读清点 `knowledge/sources.yaml`（脚本 `work/_corpus_inventory.py`，输出 `work/_corpus_inventory.txt`）：

```
total sources: 321
per-domain: anime 178 / cinematography 81 / editing 12 / storyboard 12 /
            blocking 10 / composition 10 / production 8 / performance 6 / axis_theory 4
top hosts:  journal.animationstudies.org 161 / www.gutenberg.org 54 /
            www.studiobinder.com 50 / www.bfi.org.uk 35 / www.skwigly.co.uk 16 /
            framescinemajournal.com 3 / ocw.mit.edu 2
licenses:   CC-BY 161 / PersonalStudy 104 / PublicDomain 54 / CC-BY-NC-SA 2
modes:      http 321
```

**结论与本轮之前的假设相反**：语料库里**已经有 267 条非 Gutenberg 的现代来源**
（Animation Studies 161、StudioBinder 50、BFI 35、Skwigly 16、Frames 3、OCW 2），
`sources.yaml` 也不是 59 条而是 **321** 条。真正出问题的是**卡片供应链**：
L1/L2 的 2221 张卡里 1856 张（83.6%）来自那 **54 本 Gutenberg 旧书**，
上面那 267 条现代来源在 L1/L2 上几乎没有产能。

⇒ **D1 的主线不是"去别处找新馆藏"，而是"把预算配比从 54 本旧书挪到已经证明可抓的现代来源"**
（与 `ACCEPTANCE_STATUS.md §九十五` 对 L3 做过的那次 `case_budget: 40` 重配同形，
只不过那次只动了 L3 的案例预算，这次要动 L1/L2 的卡片预算）。

## 二、可抓馆藏的实测状态

| 馆藏 | 实测 | 用途 |
|---|---|---|
| `journal.animationstudies.org` | 已在库（161 条，CC-BY） | **动画/动漫制作理论**的主力 |
| `www.studiobinder.com` | 已在库（50 条，PersonalStudy） | 镜头语言/构图/调度工艺 |
| `www.bfi.org.uk` | 已在库（35 条，PersonalStudy） | 电影理论/影评 |
| `www.skwigly.co.uk` | 已在库（16 条，PersonalStudy） | 动画行业访谈/管线 |
| `ocw.mit.edu` | **新探针实测：25 门课 / 298 页 / 209 个 PDF / 188 条通过既有门**（含抽出字符数），见 `work/ocw_v4_candidates.json` | 电影课讲义（21L.011 已在库） |
| `export.arxiv.org`（API） | 可查（已用 11 个新词条查询，178 命中 / 14 通过主题词过滤） | 动画/分镜/构图/动作的**学术**面 |
| `arxiv.org`（`/abs/` 页） | **实测超时**（`WinError 10060`，逐条重试仍失败） | ⇒ 只能用 API ＋ `/pdf/`（后者在本仓历史记录里可达） |
| `huggingface.co` | **超时**（`hf-mirror.com` 通） | 模型权重（与语料无关，见 D3） |
| `www.gutenberg.org` | 可达，但**正是要减少的部分**（54 本 1900–1920） | 只保留跨年代仍成立的基础原理 |

本机**不可达/被 robots 拒**（沿用 `MODERN_SOURCES.md` 的黑名单，不撞）：
`*.pressbooks.pub`、`milnepublishing.geneseo.edu`、`jamsjournal.com`、
`en.wikisource.org`、`archive.org`、`upload.wikimedia.org`、`doi.org`、
`www.mdpi.com`、`www.oercommons.org`、`open.umn.edu`、`www.saylor.org`。

## 三、四维覆盖（研究目标）与**如实挂着的缺口**

| 维度 | 现在靠什么 | 状态 |
|---|---|---|
| 行为／动作／情绪／意图 | StudioBinder ＋ Animation Studies（表演/作画） | 有料，需在 L1/L2 提预算 |
| 镜头语言（景别/运镜/轴线） | StudioBinder ＋ BFI ＋ OCW 21L.011 ＋ 少量 Frames | 有料；轴线域仍薄（`axis_theory` 仅 4 条来源） |
| 构图 | StudioBinder ＋ 旧书（构图原理跨年代仍成立） | 有料 |
| **震动与打击感** | **没有任何已验证来源** | **缺口**：hit-stop / impact frame / game feel 在本库 321 条来源里 **0 命中**；arXiv 的 14 条主题命中最接近，但 `arxiv.org/abs` 不可达、需改走 API＋PDF |
| **动漫视频制作理论** | Animation Studies 161 ＋ Skwigly 16 | 有料但**集中在评论/访谈**，缺"演出/分镜/时间控制"的**教材级**来源 |

**这两个缺口是本计划里唯一"没有现成来源"的地方**，处置写在下面第四节，
并作为 `ADJUDICATIONS_v4.md` 里 `须用户点头` 的候选（换馆藏＝换语料面）。

## 四、P3 的可执行动作（按顺序）

1. **重配 L1/L2 卡片预算**：把 `chunk_budget` 从 54 本 Gutenberg 旧书上按比例下调，
   让第一节里那 267 条现代来源承担主产能；旧书只保留"跨年代仍成立"的基础原理域
   （构图/透视/基础剪辑），并在 `sources.yaml` 的注释里逐条写明保留理由。
2. **接入 OCW 的 188 条**：从 `work/ocw_v4_candidates.json` 里按域名与字符数筛，
   逐条过 `tools/kb_fetch/fetch.py` 的 robots 门后进 `sources.yaml`。
   注意：OCW 的 `license: CC-BY-NC-SA` 是**课程**的许可，个别 PDF 可能是第三方读物，
   按用户"个人学习、版权不设门"的裁决可用，但 `LICENSES.md` 要如实记来源。
3. **补"震动与打击感"**：arXiv 的 14 条主题命中改走 `/pdf/`（`/abs/` 不可达）；
   若仍不足，**换馆藏属于换语料面，单列待裁决**。
4. **补"动漫制作教材级来源"**：优先找开放获取的动画课程讲义（与第 2 步同一管线），
   而不是再抓评论。

## 五、未核验（如实挂账）

* arXiv 那条探针**仍在跑**（`work/modern/arxiv_v4_candidates.json` / `_verified.json`）；
  本文的"178 命中 / 14 主题命中"是它跑到一半时的**过程输出**，不是终值。
* 第一节的域分布是**按 `sources.yaml` 的 `domain` 字段**统计的，不是按卡片数——
  卡片数按域分布要用 `tools/knowledge/authorship_report.py`，本文没有重复测。
* 没有实际跑一次"重配预算后的构建"：那属于 P5，本文只给配比与依据。
