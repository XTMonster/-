# P14 收口：理论必须来自他人著作 ＋ 超边类型供需失衡

来源：2026-10-01 用户裁决（本仓库会话记录）

* 「注意一下，理论不要自己写，要别人写的」
* 「之前的素材存在自己写的么？我希望都是别人的理论，因为专业的事情交给专业的人做」
* 「轴线规则只有『配对方式＋轴线侧』两个必填位，『轴线主题』是可选；而冻结的标注提示词
  只允许标注者写必填的两个槽位 …… 供需严重失衡 …… 瓶颈是**边类型覆盖**，不是单纯堆数量。
  还有就是你缺少了一些超边，你看一下怎么修复」
* 「能派多一些 agent 处理就多派一些」

## 一、现状（全量盘点，实测）

| 项 | 当前值 | 证据 |
|---|---|---|
| 生成卡 | 1601（`knowledge/cards_generated/*.jsonl`） | `knowledge/cards_generated/import_report.json` |
| 其中自撰（`source_ref.url` = `repo://…`，`license: OwnWork`） | **671** | `python tools/knowledge/authorship_report.py` |
| 其中他人著作（http/https，PublicDomain） | 930 | 同上 |
| 手写策展卡（实现规则，单独计数） | 132 | `block_director/knowledge/corpus.py::HANDWRITTEN_CARDS` |
| 自撰笔记 | `knowledge/source_notes/*.md` 共 **27** 篇（9 老 ＋ 18 modern） | `knowledge/sources.yaml` |
| 超图索引 | 683 条边（重建中） | `knowledge/hypergraph.edges.jsonl` |
| L3 案例 | 733 篇，**全部**源自 `repo://` 笔记 | `knowledge/cases.jsonl` |

### 1.1 实测阻塞与已证伪的结论

* `docs/knowledge/MODERN_SOURCES.md` 写着「现代教材几乎都以 PDF 发布，管线只有纯文本预处理，
  因此抓不到」。**这条已被证伪**：`extract_text.py` 现在有 PDF/HTML 分支，实测
  `https://arxiv.org/pdf/2408.17424v1` → 58,884 字符；
  MIT OCW `…lec_outlines.pdf` → 15,410 字符（均过 `fetch` 的 scheme/robots/限速门）。
* `work/_probe_modern_sources_v2.py` 的候选 URL 全是**明文 http**；换成 `https` 后同一批 PDF 可达。
  这是脚本缺陷，不是网络阻塞。
* 真的过不了门的（按 §2.3c 拒收，不得绕行）：`*.pressbooks.pub`、`milnepublishing.geneseo.edu`、
  `jamsjournal.com`（robots 403 / 不可达）、`en.wikisource.org`、`archive.org`、
  `upload.wikimedia.org`、`doi.org`（20 s 超时，本机不可达）。

## 二、验收（硬门，一条都不许降）

* **A1 署名门**：`tools/knowledge/authorship_report.py` 退出码 0，即
  `self_written_cards == 0`，且 `generated_cards ≥ 1601`（不许靠"删空语料"过关）。
* **A2 语料门**：`import_report.json` 的 K1–K5 全绿（九域每域 ≥60 张 **且** 占比 ≥5%）。
* **A3 索引门**：`build_hypergraph` 的 Q0 恒等式 pass；`knowledge/hypergraph.*` 重建后
  `tools/check_holdout.py` 的可解析率不低于重建前，且 `tests/test_hypergraph_index_content.py` 全绿。
* **A4 超边覆盖**：类型供需失衡收窄 —— `AXIS_RULE` 的**可选**成员必须能被标注方写出
  （`axis_topic` 进查询键/提示词），`IMPACT_PACK`/`SOUND_PACK`/`TROPE`/`INTENT_PACK`
  从"需求远大于索引持有"改善到可测量地收窄（数字进证据，不许只改门限）。
* **A5 回归**：`python -m pytest` 全绿；`tools/run_tests.ps1` 31/31 全绿（含 headless 端到端）。
* **A6 L3 案例层**：`knowledge/cases.jsonl` 的 `SEQUENCE_FLOOR = 7` **不许下调**。
  删掉自撰笔记后箭头套路数会掉，所以必须由**他人著作**补上显式箭头枚举的套路；
  若外部语料确实提供不了 ≥7 条，则这是必须上报的用户裁决点，不得改门限糊过去。

## 三、方案（分阶段，逐段测试）

| 阶段 | 内容 | 交付物 |
|---|---|---|
| **S0** | 冻结现状：把已完成的 `extract_text` PDF/HTML 支持 ＋ `authorship_report` 落成提交 | 提交 1 |
| **S1** | 来源 curation：PD（Gutenberg）＋ 现代（arXiv/OCW/开放期刊），逐条过 `fetch`＋`extract` 门，字符数落盘 | `work/sources/*.json` |
| **S2** | 语料重建：删 27 篇 `repo://` 来源 → 重跑 fetch/extract/dedupe/license/chunk/annotate/import | `knowledge/cards_generated/*` |
| **S3** | 索引与 oracle：build_hypergraph ＋ vocabulary ＋ held-out 卡片覆盖 | `knowledge/hypergraph.*` |
| **S4** | 超边覆盖收窄：`axis_topic` 可选槽位进提示词/查询键；类型分布实测 | 提交 ＋ 证据 |
| **S5** | 验收：pytest ＋ `run_tests.ps1` ＋ 证据归档 ＋ 文档/ADR | `docs/evidence/<run-id>/` |

## 四、风险

1. **anime / axis_theory / editing / production 四个域的他人著作不足**（自撰占比最高）。
   K3 要求每域 ≥90 张（total 1800 时 5%）。找不到就得如实上报，不得保留自撰笔记。
2. `SEQUENCE_FLOOR` 的外部来源依赖（见 A6）。
3. 标注调用成本：`deepseek` 每段一次调用，新增语料会按段数线性增长。
