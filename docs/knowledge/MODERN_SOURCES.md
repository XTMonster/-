# 现代教材/论文的引入口径（v1.5 探测记录）

这份文件记录**实测**结论，不是计划：现代教材与论文到底能不能进管线、
卡在哪一步、下一步要补什么能力。探测脚本 `tools/probe_modern_sources.py`
用的是管线自己的 `tools/kb_fetch/fetch.py`，
也就是真实入库的同一道门。

## 一、结论

**现代理论语料目前靠自撰笔记补齐（11 篇 `knowledge/source_notes/modern_*.md`），
不靠抓取。** 抓取通道卡在**内容格式**而不是许可：现代教材几乎都以 PDF 或
JS 渲染的页面发布，而管线只有"纯文本 + Gutenberg 样板剥离"这一个预处理器。

## 二、逐条实测（2026-10-01）

| 来源 | 结果 | 说明 |
|---|---|---|
| MIT OCW 21L.011 讲义索引页 | **可达**，54,347 字符 | 页面声明 CC BY-NC-SA；但**可见正文只有约 3,320 字符**，内容是课程目录与讲义标题列表（真正的讲义是 PDF 链接）。可抽的知识≈0。 |
| arXiv 摘要页 | **可达**，42,738 字符 | 同上：正文是导航＋摘要，论文主体在 PDF。 |
| en.wikipedia.org REST API | **拒收** `robots_unavailable` | robots.txt 取不到 → 按 §2.3c 拒收（宁缺勿滥）。 |
| docs.blender.org 手册页 | **拒收** `robots_unavailable` | 同上。 |
| OpenStax 教材页 | 可达，290,652 字符 | 内容与九域无关（物理学），且体积远超单文件门（512 KB）。 |

## 三、因此要补的能力（按优先级）

1. **PDF 正文抽取**（最高优先）：现代讲义/论文/教材的主体都在 PDF 里。
   需要 `tools/kb_fetch/extract_text.py` 增加 `pdf` 分支（先 `robots` 与许可门，
   再抽文本），并把"抽取器版本"写进六元指纹，否则老卡会与新正文混在一起。
2. **HTML 正文抽取**：抽 `<body>` 里的可见文本，丢 `script/style/nav/footer`。
   单独加它**不足以**解决现代教材问题——OCW 的例子说明可见正文可能只有目录。
3. **许可分类**：现代教材/论文用 `PersonalStudy`（个人学习，不外发），
   开放许可（CC BY-NC-SA 等）按页面声明如实记录。白名单与逐条声明见
   `docs/knowledge/LICENSES.md` 第五节。

## 四、抓取通道重开时的操作顺序

```powershell
# 1) sources.yaml 追加带 chunk_budget 的来源（预算跟着来源走，见 §2.3c）
# 2) 过全部机器门
python -m tools.kb_fetch.fetch
python -m tools.kb_fetch.extract_text
python -m tools.kb_fetch.dedupe
python -m tools.kb_fetch.validate_licenses
python -m tools.kb_fetch.chunk
# 3) 只标注新段落（旧段按 pass 复用，不重烧 API）
python -m tools.kb_fetch.annotate --provider deepseek --incremental --workers 6
python -m tools.kb_fetch.import_cards
# 4) 重建索引与词表
python -m tools.kb_fetch.build_hypergraph --provider deepseek --concurrency 6
python -m tools.kb_fetch.vocabulary
```

第 4 步之后**必须**把新卡片补进 held-out（门③/门⑥逐卡覆盖、门⑩/门⑪可达性
与索引可解析），否则门会如实判红——语料长大了，oracle 必须跟着长大。
