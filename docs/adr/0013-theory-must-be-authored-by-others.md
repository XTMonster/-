# ADR-0013 理论必须来自他人著作

状态：Accepted（P14 收口 · 2026-10-01 用户裁决）

## 背景

语料里有一类**自撰理论**：`knowledge/source_notes/*.md` 共 27 篇，以
`mode: manual` ＋ `license: OwnWork` ＋ `repo://` 的 URL 进管线，派生出 **671 张
生成卡**（占 1601 张生成卡的 42%）。它们被写成"当 X 时取 Y，因为 Z"的理论规则，
其中 18 篇（`modern_*.md`）是 v1.5 为了补"数字摄影 / 虚拟制片 / 声音设计 /
动作与打击感 / 现代分镜与演出实务"而**由本项目自己写的**。

用户裁决（2026-10-01）：

> 「注意一下，理论不要自己写，要别人写的」
> 「之前的素材存在自己写的么？我希望都是别人的理论，因为专业的事情交给专业的人做」

证据（`python tools/knowledge/authorship_report.py`，裁决当时的快照
`work/authorship_now.json`）：`generated_cards=1601`、`external_cards=930`、
`self_written_cards=671`、`handwritten_engine_rules=132`。

同时被证伪的一条旧结论：`docs/knowledge/MODERN_SOURCES.md` 曾写"现代教材几乎都以
PDF 发布，管线只有纯文本预处理器，所以抓不到现代理论"。实测（2026-10-01）：
`https://arxiv.org/pdf/2408.17424v1` → 58,884 字符、MIT OCW `…lec_outlines.pdf`
→ 15,410 字符，**都过 `fetch.py` 的 scheme / robots / 限速门**。真正的阻塞是
`work/_probe_modern_sources_v2.py` 里候选 URL 写成了**明文 http**，不是"抓不到"。

## 决策

1. **生成卡只能来自他人著作**：`knowledge/cards_generated/*.jsonl` 每一条的
   `source_ref.url` 必须是 `http://` / `https://`。出现 `repo://` 即判失败。
   判据落成机器门 `tools/knowledge/authorship_report.py`（退出码 0 = 通过），
   由 `tools/run_tests.ps1` 写进 `docs/evidence/<run-id>/authorship.json`
   并把失败归属到 RK-13。
2. **`mode: manual` 从来源清单里删除**：27 篇自撰笔记不再进语料；文件本身留在
   `knowledge/source_notes/` 作**设计文档**（它们记录了引擎落点与规则来源），
   但不再是"知识来源"。`sources.yaml` 里 `mode: manual` 的条数必须为 0。
3. **空出来的域用他人著作补**，而不是缩小语料：Project Gutenberg 的公有领域
   教材/实务书（`license: PublicDomain`）＋ MIT OpenCourseWare 讲义
   （`license: CC-BY-NC-SA`）。K3（九域每域 ≥60 张且占比 ≥5%）一个字不放宽。
4. **手写策展卡不算理论**：`block_director/knowledge/cards_*.py` 的 132 张是本项目的
   **实现规则**（每张都有引擎落点与测试），单独计数、不进"他人著作"分母，
   也不冒充理论。这条边界写进 `authorship_report.run()` 的返回值
   （`handwritten_engine_rules`）与 `tests/test_authorship_report.py`。
5. **抓取纪律照旧**：过不了 `robots` 的域名一律拒收（实测本机不可达或被拒：
   `*.pressbooks.pub`、`milnepublishing.geneseo.edu`、`jamsjournal.com`、
   `en.wikisource.org`、`archive.org`、`upload.wikimedia.org`、`doi.org`）。
   不许为了让语料变大而绕门。
6. **`Crawl-delay` 与 `Disallow` 同级**：`tools/kb_fetch/fetch.py` 新增
   `crawl_delay()`，实际请求间隔取 `max(--rate, Crawl-delay)`。arxiv.org 明写
   `Crawl-delay: 15` 且声明"Indiscriminate automated downloads … are not
   permitted"，忽略它就是违反 robots 协议。

## 后果

- 语料的所有权边界第一次变成**机器可查**的事实，而不是一句口号；
- **未收口**：L3 案例层的 `SEQUENCE_FLOOR = 7` 原先**完全**依赖自撰笔记里的
  箭头枚举（`storyboard_practice.md` 4 条 ＋ `anime_language.md` 3 条）。实测
  外部语料（56 篇，含 5 篇 arXiv PDF）里 `→`/`->` 只有 **1** 个、派生出
  **0** 条 `sequence_pattern`。删掉笔记后这条门必然判红，而"调低门限"与
  "把自撰笔记偷偷留在 L3"都不能由 agent 自己决定——这是留给用户的裁决点，
  见 `docs/knowledge/ACCEPTANCE_STATUS.md`。
- 自撰笔记仍然是**引擎规则的另一份说明**：`docs/adr/0007`…`0012` 记录的几何、
  构图、标签规则有自己的测试，与本次裁决不冲突。
