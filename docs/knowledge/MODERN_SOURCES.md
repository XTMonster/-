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

## 五、2026-10-02：`anime` 域的现代来源（用户点名的那一半）

上一节列的是"现代"里**电影**那一半；用户点名的是另一半，原话是
「补充现代知识教材，理论体系，越详细越好」「补一些动漫设计理论」
「**不是角色设计，是动漫那些视频制作理论**」「动漫电影，围绕着动漫视频制作展开」
「理论不要自己写，要别人写的」。此前 `anime` 域的**全部**内容来自 Lutz 1920 那一本。

**这一轮加进来的族**：`Skwigly Animation Magazine`（英国动画行业刊物，2000s–2020s）
的 16 篇**制作用**文章——动画表演（Andy Joule 的 Acting For Animation 系列四篇）、
故事板（Wade Konowalchuk 的 Do's and Don'ts）、角色动画、layout/管线（Unreal、
Cinema 4D）、数字灯光、动态影像技法（Bill Plympton《Cheatin'》的作画）。

**怎么挑的（可复算，不是随手搜）**：

1. `robots.txt` 门：`www.skwigly.co.uk/robots.txt` = `User-agent: * / Disallow:`，
   即不禁止任何路径（与 `fetch.py` 同一条判据）；
2. **全量枚举站点索引**（6 个 `post-sitemap*.xml`，281 条），不按关键词搜；
3. 按正文的**动画工艺关键词打分**（与 `chunk.py` 的 `anime` 词表同源），
   分数 <10 或抽取正文 <2400 字符的丢掉；
4. 人工剔除**纯新闻/评奖/招聘/课程报名**——它们讲产业，不讲拍法。
   最终收 16 条，每条 `chunk_budget: 1`（每篇只取最相关的一段）。

**许可**：Skwigly 是商业刊物，逐篇找不到 CC 声明，因此按用户
「我是个人学习使用的，不用担心版权问题」的口径记 `PersonalStudy`
（白名单内，与已有的 Frames Cinema Journal 三条同口径），**不冒充开放许可**。

**实测后果**（同一次运行里量出来的，不是估算）：

```
sources        59 → 75        （anime 域 1 → 15 条来源）
chunks        635 → 651       （anime 段 43 → 59）
cards        1981 → 1998      （anime 141 → 153、storyboard 227 → 229、cinematography 211 → 214）
超边索引      539 → 541        （--replace-cards 只重抽新增 17 张卡，旧原子的字节没动）
oracle       2953 → 2981 条    （为新增卡补条目后，被双模型复核剔掉 1 条）
卡片全集     2113 → 2130
```

全链复跑：门①–⑩ **全 pass**（门⑥ `expected 2099 / excluded 31 / share 98.5%`）、
RAG 硬门 Q0–Q7 ＋ E3 全 pass、`pytest 1607 passed`、31/31 探针、
`rks.json failed_checks: []`。证据 `docs/evidence/20261002-134053/`。

**仍然够不到的**（按 §2.3c「宁缺勿滥」拒收，不绕门）：`journal.animationstudies.org`
（**没有** robots.txt → 按仓库口径拒收；RFC 9309 允许把 404 读作"无限制"，
但实现比文档严，改它属于放宽抓取纪律，留给裁决）、`*.pressbooks.pub`（403）、
`en.wikipedia.org` / `en.wikibooks.org`（本机超时）、`milneopentextbooks.org`（超时）、
`www.awn.com` / `nofilmschool.com` / `www.bfi.org.uk`（403 或 robots 404）。
`blog.sakugabooru.com` 的 robots.txt 写了 EU DSM 第 4 条的**权利保留**声明，
按"宁缺勿滥"**不收录**。

## 六、2026-10-02：**中文**来源的正面盘点（结论是"今天收不到"，不是"没去找"）

背景：E1（经验引用相关性 ≥70%）的落点已经被量出来了——L3 的 810 篇**全英文**、
产品查询**全中文**、6/6 逐镜查询命中 **0** 条，而把查询改写成英文再打英文语料也只有
**1/18** 条 ≥4 分（`docs/evidence/20261002-180124/e1_lane_diagnosis.json`）。
所以"补中文的逐镜分析（拉片/影评）"是 E1 唯一有希望的路。本 lane 的正面任务就是这个，
下面是**实测**（每条都走仓库自己的 `tools/kb_fetch/fetch.py`，UA 与生产一致，
robots 按 RFC 9309，不伪造浏览器、不关 TLS 校验）：

| 候选 | 许可 | 实测结果 |
|---|---|---|
| `zh.wikipedia.org`（景别/运镜/场面调度/蒙太奇/分镜头/动画 6 条） | CC-BY-SA | **整站不可达**：`robots_unavailable:URLError` |
| `zh.wikisource.org`（民国影戏学） | PublicDomain | **不可达**：`URLError: handshake operation timed out` |
| `zh.wikibooks.org`（电影制作） | CC-BY-SA | **不可达**：同上 |
| `zhuanlan.zhihu.com` | Unknown（全版权） | **robots 明文拒绝**（`robots_disallow:/`）→ 按纪律拒收 |
| `movie.douban.com/review/…` | AllRightsReserved | 页面到达，但**返回的是反爬壳页**：缓存原文标题只有"豆瓣"、正文 2950 字符里没有文章体——**不是可入库的正文** |
| `www.bilibili.com/read/cv…` | AllRightsReserved | 同上：3318 字符是 SPA 外壳，不是文章 |
| `www.107cine.com`（影视工业网） | AllRightsReserved | **不可达**（`URLError`） |
| `www.animation-baike.com`（动画学术趴） | AllRightsReserved | **不可达**（`URLError`） |

**根因不是许可，是网络路径。** 对维基家族的独立复测（`socket.getaddrinfo` ＋
`https://<host>/robots.txt`，同一 UA）：

```
zh.wikipedia.org     DNS 31.13.94.49     URLError: <urlopen error timed out>
en.wikipedia.org     DNS 31.13.112.9     URLError: <urlopen error timed out>
zh.wikisource.org    DNS 103.102.166.224 URLError: _ssl.c:990: The handshake operation timed out
zh.wikibooks.org     DNS 103.102.166.224 URLError: _ssl.c:990: The handshake operation timed out
common.wikimedia.org                    gaierror: [Errno 11001] getaddrinfo failed
```

`zh/en.wikipedia.org` 解析到 **31.13.x.x（Facebook 网段）**、其余主机 TLS 握手超时、
`common.wikimedia.org` 直接解析失败——这是**DNS 投毒 + TLS 阻断**的形态，
不是 robots 或 UA 的问题（这也是 §五 里 `en.wikipedia.org` 那条"本机超时"的真正原因）。

**结论（三选一，都需要用户拍板）**：

1. **给出网络路径**（代理/镜像/离线快照）：维基家族的 CC-BY-SA/PublicDomain 中文内容
   立刻可收，且**不需要任何许可妥协**——这是唯一"零许可风险"的选择；
2. **授权 `PersonalStudy` 口径用于中文影评站**：豆瓣/知乎/B站等的许可是全版权保留，
   且其中知乎 robots 明文拒绝、豆瓣/B站还要先解决反爬（同一次实测里它们只返回壳页）——
   这一步至少在口径之外还要额外解技术问题；
3. **不在中文来源上投入**：那就必须承认 E1 在"中文查询 + 开放许可语料"这个组合下
   **无解**，把 E1 长期留在 `not_measured`（`docs/knowledge/ACCEPTANCE_STATUS.md` §27.1）。

证据：`work/zz_zh_candidates.txt`（候选清单与判据）、`work/zz_zh_hunt.json`（逐条实测）、
`work/raw/`（同一批请求的原文缓存）。
