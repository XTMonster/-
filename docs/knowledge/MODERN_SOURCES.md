# 现代理论语料的来源口径（2026-10-01 重建）

这份文件记录**实测**结论与**当前**来源清单，不是计划。上一版（v1.5）写的是
"现代教材几乎都以 PDF 发布、管线只有纯文本预处理器，所以抓不到"——**那条结论已被
证伪**，见 §一。用户裁决（"理论不要自己写，要别人写的"）之后，全部自撰笔记退出语料，
现代那一半改由**他人著作**承担。

## 一、被证伪的旧结论（留档，避免重犯）

| 旧说法 | 实测 |
|---|---|
| arXiv 的论文抓不到 | **假**。用仓库自己的门：`https://arxiv.org/pdf/2408.17424v1` → 58,884 字符。原先失败是因为 `work/_probe_modern_sources_v2.py` 的候选 URL 写成**明文 http**（`http://arxiv.org/pdf/...` 超时），换成 `https` 即可达。 |
| MIT OCW 的可见正文只有目录、抽不出知识 | **半假**。索引页确实只有目录，但**讲义本身是 PDF**；`extract_text.py` 现在有 PDF 分支，`…MIT21L_011F13_lec_outlines.pdf` 实测抽出 15,410 字符。 |
| 现代材料只能靠自撰笔记补齐 | **假**。见 §二、§三。 |

本机**确实**不可达 / 被 robots 拒绝的域名（按 §2.3c「宁缺勿滥」拒收，不绕门）：
`*.pressbooks.pub`、`milnepublishing.geneseo.edu`、`jamsjournal.com`、
`en.wikisource.org`、`en.wikibooks.org`、`archive.org`、`upload.wikimedia.org`、
`doi.org`、`www.mdpi.com`、`www.oercommons.org`、`open.umn.edu`、`www.saylor.org`。

## 二、当前来源（`knowledge/sources.yaml`，59 条，全部 `http/https`）

* **Project Gutenberg**（`license: PublicDomain`）：公有领域的摄影/电影/舞台/动画
  实务教材。新引入的关键书目（原先没有的域）：
  * **轴线 / 连续性**：`Motion Picture Directing: The Facts and Theories of the
    Newest Art`（Peter Milne，53117）——这一本承担整个 `axis_theory` 域；
  * **剪辑 / 影片理论**：`The Art of the Moving Picture`（Vachel Lindsay，13029）、
    `The soul of the moving picture`（Bloem，73028）；
  * **制片 / 现场**：`Moving Pictures: How They Are Made and Worked`（Talbot，67972）、
    `A-B-C of motion pictures`（74971）、`Behind the Screen`（59730）、
    `Magic Shadows`（64578）、`When the movies were young`（68850）等；
  * **调度 / 舞台**：`Continental stagecraft`（72655）、`Kabuki`（70471）、
    `Secrets of scene painting and stage effects`（76304）、
    `The Greek theater and its drama`（69095）、`A Book of Marionettes`（66391）、
    `Marionettes, masks and shadows`（74969）；
  * **构图 / 透视 / 光线**：`Composition`（Arthur Wesley Dow，45410）、
    `The Elements of Perspective`（Ruskin，60816）、`Pictorial Beauty on the Screen`
    （Freeburg，66049）、`Artificial Light`（Luckiesh，17625）等；
  * **动画**：`Animated cartoons`（Lutz，73455）——公有领域里唯一一本讲动画**生产**
    的整本书，承担整个 `anime` 域（切块预算 45）。
* **MIT OpenCourseWare**（`license: CC-BY-NC-SA`）：`21L.011 The Film Experience`
  的两份讲义 PDF（课程大纲/讲义提纲），进 `editing` / `cinematography`。
* **Frames Cinema Journal**（BAFTSS，同行评审开放获取，ISSN 2053-8812）：
  三篇讨论**空间/方位/连续性**的论文，按 `PersonalStudy` 记名（逐篇找不到具名的
  CC 声明，所以不冒充开放许可）。

## 三、结果（实测，`python tools/knowledge/authorship_report.py`）

```
generated_cards 1981 | external_cards 1981 | self_written_cards 0 | passed True
per_license: PublicDomain 1856 / PersonalStudy 65 / CC-BY-NC-SA 60
```

K3（九域每域 ≥60 张且占比 ≥5%）在 2113 张（生成 1981 ＋ 手写策展 132）上全绿：
最小域 `anime` 141 张 / 6.7%，`axis_theory` 201 张 / 9.5%。

## 四、重跑顺序（改 `sources.yaml` 之后）

```powershell
python -m tools.kb_fetch.fetch            # 过 scheme / robots / Crawl-delay 门
python -m tools.kb_fetch.extract_text     # 纯文本 / HTML / PDF
python -m tools.kb_fetch.dedupe
python -m tools.kb_fetch.validate_licenses
python -m tools.kb_fetch.chunk
python -m tools.kb_fetch.annotate --provider deepseek --incremental --workers 6
python -m tools.kb_fetch.import_cards     # K1–K5
python -m tools.kb_fetch.vocabulary       # nodes + vocab（build_hypergraph 读它们）
python -m tools.kb_fetch.build_hypergraph --provider deepseek --concurrency 6
```

第 8 步之后必须重跑 held-out 的卡片覆盖与词表快照，否则门③/⑥/⑨/⑩ 会如实判红
（语料长大了、oracle 还是旧世代）。
