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
| `export.arxiv.org`（API） | **可查**：11 个新词条 → `found=178`、`on_topic=14`、`dropped_by_relevance=164`（`work/_arxiv_v4.log`） | 动画/分镜/构图/动作的**学术**面 |
| `arxiv.org`（`/abs/` 页） | **实测不可达**：许可只写在摘要页上（`find_arxiv_sources.py:48` 原文："the Atom feed has no `rel=\"license\"`"），而当晚该域名 **7/7 逐条超时**（`WinError 10060`）⇒ `--licences 0` 那一跑 `licence_clean=0`、`candidates: []` | ⇒ **arXiv 当晚产不出可用来源**（不是"没有相关论文"，是"许可读不到"） |
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
| **震动与打击感** | 动画／电影来源里的**动作与冲击**段落（anime 98 ＋ cinematography 26 ＋ …） | **本条此前记错了，已按实测改正（2026-10-05）**：关键词层仍然 0 命中（hit-stop／impact frame／game feel 在 321 条来源题名里没有），但**内容层有 133 个来源、412 条边**——详见下面「四维按源实测」 |
| **动漫视频制作理论** | Animation Studies 161 ＋ Skwigly 16 | 有料但**集中在评论/访谈**，缺"演出/分镜/时间控制"的**教材级**来源 |

**这两处曾被记成本计划里唯一"没有现成来源"的地方**，处置写在下面第四节，
并作为 `ADJUDICATIONS_v4.md` 里 `须用户点头` 的候选（换馆藏＝换语料面）。
**但下面「三之一」的实测把其中一条推翻了**：震动与打击感在**内容层**有 133 个来源
（关键词层没命中 ≠ 这一维没有料）；动漫那条（评论/访谈多、教材级少）仍成立。

### 三之一、**四维按源实测**（2026-10-05 补；P1② 的"四维各≥1 源"就是这一条）

上一张表的"缺口"是**按关键词**在来源题名里检索得出的；而"这一维有没有料"应该看
**入库内容里抽出了什么**。做法（可复算，`work/_dim_sources3.py`）：维度←边型的映射
取 `tools/knowledge/coverage_matrix.py`（唯一映射，不另抄一份），边的
`sources: ["seg:<digest>:<start>-<end>"]` 里的 `digest` ＝ `sha256(source_ref.sha256)[:12]`，
对 240 条语料解析（**0 条解析不到**），再按源去重：

| 维度 | 边数 | **来源数**（去重，共 240 条语料） |
|---|---|---|
| 行为／动作／情绪／意图 | 3043 | **236** |
| 镜头语言 | 1099 | **219** |
| 构图 | 26 | **15**（最薄） |
| 震动与打击感 | 412 | **133** |
| 声音／对白／配乐 | 719 | **167** |
| 光 | 137 | **79** |

⇒ **四维各≥1 源成立**；此前的"震动与打击感＝缺口"**被实测推翻**（关键词层没命中，
不等于内容层没有料）。真正最薄的是**构图**（15 源／26 边），它才是后续要盯的那一维。
冻结身份（书单 sha256、`corpus_digest`）记在 `ADJUDICATIONS_v4.md` 第七节。

## 四、P3 的可执行动作（按顺序）

1. **重配 L1/L2 卡片预算**：把 `chunk_budget` 从 54 本 Gutenberg 旧书上按比例下调，
   让第一节里那 267 条现代来源承担主产能；旧书只保留"跨年代仍成立"的基础原理域
   （构图/透视/基础剪辑），并在 `sources.yaml` 的注释里逐条写明保留理由。
2. **接入 OCW 的 188 条**：从 `work/ocw_v4_candidates.json` 里按域名与字符数筛，
   逐条过 `tools/kb_fetch/fetch.py` 的 robots 门后进 `sources.yaml`。
   注意：OCW 的 `license: CC-BY-NC-SA` 是**课程**的许可，个别 PDF 可能是第三方读物，
   按用户"个人学习、版权不设门"的裁决可用，但 `LICENSES.md` 要如实记来源。
3. **补"震动与打击感"**：arXiv 那 14 条主题命中**当晚不可用**（许可页超时，见第二节）。
   三条出路按优先级：①换时段重跑 `find_arxiv_sources.py --licences N`（许可页有时可达，
   工具自己的 docstring 记着"单次摘要页抓取成功过一次、15.5 s"）；②改抓 `/pdf/` 并把许可
   记为 `PersonalStudy`（用户已裁决个人学习、版权不设门，且白名单本就含 `PersonalStudy`）；
   ③换馆藏——**换馆藏属于换语料面，单列待裁决**。
4. **补"动漫制作教材级来源"**：优先找开放获取的动画课程讲义（与第 2 步同一管线），
   而不是再抓评论。

## 五、未核验（如实挂账）

### 5.1 影子入库的实测结果（2026-10-05，本批新增）

`knowledge/sources.v4.yaml`（240 条 `year >= 1980`）真跑了一次
`python tools/kb_fetch/ingest_corpus.py --sources knowledge/sources.v4.yaml --out work/corpus_v4`：

```
{"overall": "pass", "kept": 240, "excluded": 0, "rejects": 0, "input": 240,
 "corpus_digest": "8179ac69fd881a80da46a622f34f1db0050579f85f74b03db05f57f9a639740e"}
```

**240 条全部过了 scheme ＋ robots 门**（0 拒绝）——这是"这些馆藏可用"的第一次端到端证据，
不再是文档里的断言。域分布与年份分布如实记在
`docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md` 的 P3②/④ 两行。

**年份字段的 caveat（必须知道）**：`year` 只当 **cutoff 的地板**用，不是精确发表日期。
实测年份直方图里 **2026 有 39 条**（2004–2026 的其余年份分布平滑）——多出来的那一块
多半来自站点的**动态页脚版权年**。这不影响 cutoff 判定（一个显示 2026 的页面必定是现代页面，
**只会正确地纳入、不会错误地纳入旧料**），但**不许**把它当成"这篇是 2026 年发表的"。
要精确年份，得在 P5 之前按站点补一次逐条元数据核对。

* arXiv 那条探针**已跑完**（`--per-term 20 --licences 0 --verify 0`，退出码 0）：
  `work/modern/arxiv_v4_candidates.json` 里 `candidates: []`、`licence_clean=0`。
  **"14 条主题命中"只记在日志里，没有落成候选条目**——因为工具只在通过许可门后才写条目。
  换时段重跑才会拿到条目；本条如实挂着，不当成"已经找到 14 条来源"。
* 第一节的域分布是**按 `sources.yaml` 的 `domain` 字段**统计的，不是按卡片数——
  卡片数按域分布要用 `tools/knowledge/authorship_report.py`，本文没有重复测。
* 没有实际跑一次"重配预算后的构建"：那属于 P5，本文只给配比与依据。
  （**已部分销账**：`ingest_corpus.py` 那一步跑通了，见 §5.1；"构建"指 P5 的 L1/L2 影子构建，仍未跑。）
