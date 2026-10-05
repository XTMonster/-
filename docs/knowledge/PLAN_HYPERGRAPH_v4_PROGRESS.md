# 执行计划 v4 · 进度台账

行格式：`阶段 | DoD 条目 | 状态(待/红/绿) | 证据 | 日期 | commit`

状态口径：**绿**＝该 DoD 条目有可复算的证据且已入库；**红**＝试过且失败（附失败输出）；
**待**＝还没开始。**不许把"待"写成"绿"**——本仓的机器门纪律对台账自己一样适用。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **P0** | ①三循环的草案/审查/修订证据齐 | 绿 | 循环 2：`PLAN_V4_REVIEW_LOOP2.md`（37 条，双侧 complete）＋`PLAN_V4_LOOP2_DISPOSITION.md`；循环 3：`PLAN_V4_REVIEW_LOOP3.md`（36 条，双侧 complete）＋`PLAN_V4_LOOP3_REVISIONS.md`（处置稿截断已记账）；守门 `tests/test_plan_v4_freeze.py`（6 条） | 2026-10-05 | `effbe88` |
| **P0** | ②用户明示"开始执行" | 绿 | 用户 2026-10-05 授权："人工部分尽可能你解决"、"你尽管围着高质量方向做，我有很长一段时间不在家"；据此主线自行裁定 D1–D9/R1–R5（`ADJUDICATIONS_v4.md`） | 2026-10-05 | `9e6803e` |
| **P1** | ①D1–D9 各"已裁决＋日期＋选项" | 绿 | `ADJUDICATIONS_v4.md` 一张表 14 行（D1–D9＋R1–R5），动判据的三条标 `须用户点头` | 2026-10-05 | `9e6803e` |
| **P1** | ②`CORPUS_V4.md` 冻结（每源 url/title/author/license/year；四维各≥1 源） | **红** | 已产出实测版（321 条来源清点＋OCW 188 条候选＋arXiv 0 条可用），但**书单还没冻结**：D1 的"预算重配"尚未落到 `sources.yaml`。见该文件 §三 的两个缺口 | 2026-10-05 | `e813600` |
| **P1** | ③`tests/plan_v4/instruments.sha256.json` 冻结仪器哈希 | 绿 | 落成 `tests/plan_v4_instruments.sha256.json`（4 个仪器）＋守门 `tests/test_plan_v4_instruments_frozen.py`（7 条，含反面对照）；与 `PLAN_HYPERGRAPH_v4_ANNEX.md` 一起 | 2026-10-05 | 本批 |
| **P1** | ④V1–V9 写进计划（本仓形态：有约束力的附件） | 绿 | `PLAN_HYPERGRAPH_v4_ANNEX.md`："与正文冲突时以本附件为准"，V1–V9 逐条给"覆盖哪里/改成什么/怎么验"；守门 `tests/test_plan_v4_freeze.py::test_the_binding_annex_exists_and_declares_precedence` | 2026-10-05 | 本批 |
| **P2** | ①成对基线（v3pop，只读） | 绿（机制）/待（N≥3） | 两臂各 2 次已在库：`docs/evidence/20261006-e1-baselines/`（hybrid 0.2031/0.2031、lexical 0.1927/0.2292）；判读机制 `tools/knowledge/e1_baseline_summary.py::paired_report`（本批一般化）＋`tests/test_e1_paired_report.py`（8 条）。**N≥3 的补测未做** | 2026-10-05 | `d472e41` |
| **P2** | ②轮记录文件（V1）接到 `e1_panel` 输出旁 | 待 | — | — | — |
| **P3** | ①入口工具（按年门槛选料 ＋ 影子语料分账） | 绿 | `tools/kb_fetch/ingest_corpus.py`（复用 `fetch.py` 的门：scheme／robots／限速／sha256 幂等；新增按 `cutoff=1980` 选料、`excluded.jsonl` 具名原因、`MANIFEST.json` 四字段、`corpus_digest()`、账目闭合断言）；守门 `tests/test_ingest_corpus.py`（6 条，含反面对照） | 2026-10-05 | `c66ca96` |
| **P3** | ②`knowledge/sources.v4.yaml`（带 `year` 的影子来源清单） | 绿 | 新增 `tools/kb_fetch/year_probe.py`（**离线**从 `work/raw/` 的 1201 份已抓正文定年份，纯函数、7 条用例、每条留 `year_basis`）：命中率 **89 → 247/321**（`citation_publication_date` 160／`published_time` 42／JSON-LD 36／版权年 7／课程 slug 2）。据此生成 240 条 `year >= 1980` 的影子清单（Animation Studies 160／BFI 35／StudioBinder 24／Skwigly 16／Frames 3／OCW 2，**旧书 0 条**） | 2026-10-05 | `9b74012` |
| **P3** | ③跑一次入库（`--out work/corpus_v4/`） | 绿 | 真跑 240 条，**kept 240 / excluded 0 / rejects 0**（每条都过了 scheme ＋ robots 门）；产物 `work/corpus_v4/{MANIFEST.json(100KB), fetched.jsonl(36.5MB), excluded.jsonl}`；五字段齐（无缺项）；`corpus_digest = 8179ac69fd881a80da46a622f34f1db0050579f85f74b03db05f57f9a639740e` | 2026-10-05 | 本批 |
| **P3** | ④覆盖偏斜的如实记账 | 红（已知缺口） | v4 的域分布：anime 176／cinematography 49／editing 6／axis_theory 3／storyboard 3／**composition 2／blocking 1**；另有 74 条因缺年份被排除（Gutenberg 47／StudioBinder 26／Animation Studies 1）。`composition`/`blocking` 偏薄是 v4 的既知缺口，P5 的覆盖矩阵要盯它 | 2026-10-05 | 本批 |
| **P4** | ①两趟"分段→归属"抽取器（自研实现，上游只作算法参考） | 绿 | `tools/kb_fetch/extract_segmented.py`：`segment_text()`（确定性、**覆盖全部正文**、超长按句/硬切）、`validate_draft()`（闭集＋出处，**拒收具名**）、`extract()`（两趟驱动，LLM 注入 ⇒ 离线可测）、`DeepSeekClient`（构建期 LLM＝DeepSeek，花费台账落 `work/corpus_v4/spend.jsonl`）；守门 `tests/test_extract_segmented.py`（8 条，含"闭集清单不许抄第二份"与账目闭合） | 2026-10-05 | 本批 |
| **P4** | ②预算可行性实测（D6 的护栏能不能装下） | 红→已更新 | 干跑实测：**240 份来源 → 44,497 段 → 33,060,216 字符 ≈ 2,200 万输入 token**；按域：anime 29,169 段／cinematography 10,644 段（17.1M 字符，StudioBinder 长文）／editing 2,004／storyboard 1,149／composition 917／blocking 346／axis_theory 268。原定 D6（输入 2,000 万）**不够**，已按实测改成输入 4,000 万／输出 1,200 万（见 `ADJUDICATIONS_v4.md` 的 D6 行） | 2026-10-05 | 本批 |
| **P4** | ③真跑一次抽取（`--limit-segments` 试点） | 绿（试点） | 60 段试点：**跳过 31 段过短样板 → 21 条草稿、21 条过粗闭集、0 拒收**，覆盖 8 个边型（TROPE 11／EDIT_RHYTHM 2／PROP_PACK 2／MUSIC_PACK 2／PERFORMANCE_PACK 1／INTENT_PACK 1／SHOT_PATTERN 1／DIALOGUE_PACK 1）。产物 `work/extracted_v4_pilot/` | 2026-10-05 | 本批 |
| **P4** | ④"0 拒收"的**口径**如实记（别把它读成全绿） | 红（已知口径差） | `validate_draft` 只查 type/role/kind ＋ 出处，**不查取值词表与必填槽位结构**。试点样本里出现 `pacing:followed the singer`、`vfx:video feedback`、`allow/applies_to_genre` 这类写法——它们过得了 P4 的粗闭集，过不了 `hypergraph.validate_edge` 的词表关。⇒ **拒绝率的重头戏在 P5**，D9 的 rejects 率护栏到那时才有读数 | 2026-10-05 | 本批 |
| **P3** | ⑤管线第 2 步（HTML→正文） | 绿（修复后重跑） | P4 试点暴露的真缺陷：入库存的是**原始 HTML**（`fetched.jsonl` 36.5MB），抽取器看到样板代码、一条草稿都产不出。补上 `extract_text` 后重跑：`fetched.jsonl` **36.5MB → 7.66MB**，`corpus_digest` `3dc686db432e2cd7727b70684f7cc88efe15dd8d29aef5264ce310e5c5861eb9` | 2026-10-05 | `037aef9` |
| **P5** | ①影子构建器（草稿 → 现役 `to_edge` → 影子目录，**一行不改**被冻结的构建器） | 绿 | `tools/kb_fetch/build_shadow.py`：`segment_cards()`（**片段即卡片**，键＝`seg:<digest>:<start>-<end>`，`source_span` 供 `to_edge` 定位）、`draft_to_raw()`（查不到片段即 `no_segment_for_span` 具名拒收）、`hg_to_edge()`（薄壳直调现役 `to_edge`）、`build_shadow()`（落 `hypergraph.edges.jsonl` ＋ `build_report.json`，账目闭合）；守门 `tests/test_build_shadow.py`（8 条） | 2026-10-05 | 本批 |
| **P5** | ②第一次真实读数（必填槽位门） | 红→已修 | 用 P4 试点的 21 条草稿跑影子构建：**0 kept／21 rejected，全部 `missing_required`**。根因不是模型的错——提示词只列了闭集、**没列每种边型的必填槽位**，模型答的是"这段讲了哪几个槽位"而 schema 要"凑齐哪几个"。已在 `edge_type_menu()` 里逐条写出必填（现读 `REQUIRED_MEMBERS`） | 2026-10-05 | 本批 |
| **P5** | ③改提示词后的第二次读数（质量 ↑ 产量 ↓ 的权衡） | 绿（有保留） | 同一批 60 段重跑：草稿 **21 → 4**，但 **4/4 通过、0 拒收**，影子构建 `closes: true`。⇒ 必填约束让模型变保守：**质量上去了、产量下来了**（4/29 可用段 ≈ 14%）。下一步候选：两段式提问（先问"这段适用哪些边型"，再为那些边型要**完整槽位集**），但这属于 P4 的迭代，如实挂着 | 2026-10-05 | 本批 |
| **P5** | ④取值词表关（`NodeIndex`）——**已接上，并拿到真读数** | 红（关键发现） | 用现役 `vocabulary.run()` 在**新语料**上建 v4 词表（**181 个节点**；`lens` 一类开放值靠正文里的 `\d+mm` 汇出，只跑受控表会少掉它们），再构造 `NodeIndex` 传给 `to_edge`。**接上之后，原先"4/4 通过"的 4 条草稿变成 0/4 全拒**（全部 `missing_required`，原因里带 `dropped=`）。丢掉的取值长这样：`pacing:rapid`（词表是 short/medium/long）、`lens:长镜头`（词表是 24/35/50/85mm——而且**塞错了 kind**）、`genre:music video`、`emotion:non-narrative`、`headroom_policy:一镜到底`。⇒ 模型写的是**语义合理但不在冻结词表里**的取值 | 2026-10-05 | 本批 |
| **P5** | ⑤提示词加"每个 kind 的允许取值" | **红（负结果）** | 已实现（`value_lines()`：给了词表按 kind 列取值、没给退回 `hg.VALUE_DOMAINS`；CLI `--vocab-from-corpus`），但**真实试点是负结果**：<br>· 提示词 **3,302 字符／26 kind／374 取值**，96 字与 1,040 字的段**都返回 `{"drafts":[]}`**；<br>· 同一批 40 段（`--min-chars 200`，14 个实质段）→ **0 草稿**。<br>⇒ **把 374 个取值平铺进一次调用会把模型压死**。约束越加越严的整条曲线：21 条（无必填表）→ 4 条（加必填表）→ **0 条（加取值表）**——精度升、召回降到零 | 2026-10-05 | 本批 |
| **P4/P5** | ⑥两段式提问（已实现） | 绿（实现）／**红（读数）** | 已落 `extract_two_step()` ＋ `type_prompt()`／`member_prompt()`／`parse_types()`／`parse_members()`，CLI `--mode two-step`；17 条用例全绿（含"B 段只带被选中边型的 kind 与取值"）。**但真实读数是 0**：40 段（14 个实质段）→ `calls: 16`（A 段 14 次 ＋ B 段 2 次）→ **0 草稿**。A 段对 700–1,040 字的段**一律返回 `{"types":[]}`** | 2026-10-05 | 本批 |
| **P4/P5** | ⑦语义注解（从 v18 提示词**解析**，不抄第二份）＋ 一致性守门 | 绿（工具）／**红（效果）** | `type_glosses()` 从现役 `build_hypergraph.SYSTEM_PROMPT` 里解析出 **16/16** 个边型的一句人话注解（实测 `ACTION_BEAT` 取到"……叙事**节拍**、强度绑死"），`hg.EDGE_TYPES` 里缺注解就**抛错**（守门用例当场红）。但**把它加进提示词后产量从 4 掉到 0**（pilot8/9，重复两次） | 2026-10-05 | 本批 |
| **P4/P5** | ⑧**实测阶梯**：每加一层 schema 细节，产量掉一截直到归零 | 绿（读数）／已按它回退 | 同一批 60 段／`deepseek-chat`／temperature=0：<br>**只给边型 21 条 → ＋必填槽位 4 条 → ＋允许取值 0 条 → ＋语义注解 0 条（重复两次）→ 两段式（A 问边型／B 填槽位）0 条**。<br>⇒ 处置：**默认单段提示词退回"只给必填槽位"**（已知最好状态），取值表（`value_lines()`）与注解（`type_glosses()`）保留为**可选件**供两段式 B 段用；并写了一条守门用例 `test_the_single_step_menu_deliberately_omits_values_and_glosses` **防止有人再把它们塞回去**。回退后复跑：**4 条草稿**（与 pilot2 一致，可复现） | 2026-10-05 | 本批 |
| **P4/P5** | ⑨结构判断：**分段粒度可能就是根因** | 已选 **A 路** | v18 是在**卡片**（已蒸馏的短知识单元）上抽取，而 v4 把**学术散文段**（700–1,040 字）直接喂进去。⇒ 选 A：抽取前加"片段 → 短知识陈述"的蒸馏，让抽取回到 v18 那套已被验证的输入形状。（B 路"L1 仍由卡片承载"留作对照） | 2026-10-05 | 本批 |
| **P4** | ⑩A 路第一段：蒸馏器（散文 → 短陈述） | 绿 | `tools/kb_fetch/distill_segments.py`：`distill_prompt()`（明写"不要评论／不许发明／不要把例子当规则"）、`parse_statements()`、`distill()`（每条带**出处指针** `source{url,sha256,span}` ＋ 兼容 P4 记录的 `source_ref`；复述整段判 `too_long`；解析失败具名；账目闭合）；守门 `tests/test_distill_segments.py`（5 条）。**真实读数：29 个实质段 → 165 条陈述，0 拒收、0 解析失败（≈5.7 条/段）** | 2026-10-05 | 本批 |
| **P4** | ⑪A 路第二段：陈述喂回抽取 | **红（集成缺陷已定位）** | 165 条陈述 → **3 条草稿**（对照：29 个原始段 → 4 条），而且这 3 条在影子构建里**全被 `no_segment_for_span` 拒**。<br>根因：`extract()` 把每条陈述**又当成一段文本重新分段**，于是草稿的 `span` 是相对**陈述串**的偏移，丢了指向原语料段的指针（我在陈述里存的 `source` 没被透传）。<br>⇒ 修法明确：`extract()` 必须承认"这条记录自带出处指针"（`source`／`statement_of`），把它**当原子段**、直接用那个 span，不许再分一次。修完才谈"蒸馏有没有用" | 2026-10-05 | 本批 |
| **P4** | ⑫蒸馏的**净效果**（在修好 span 之前不下结论） | 待 | 现有读数只说"3 vs 4"，而 3 条因 span 缺陷全废 ⇒ **在修好 ⑪ 之前不许说"蒸馏没用"**。修完要用同配置成对重测一次（同一批 60 段，直接抽取 vs 蒸馏后抽取），并把两臂的**通过影子构建数**一起报 | — | — |
| **P6** | L3 案例与冻结评测集 | 待 | — | — | — |
| **P7** | LightRAG 索引与 sidecar 服务 | 待 | — | — | — |
| **P8** | 插件侧适配器（门控默认关） | 待 | — | — | — |
| **P9** | A/B 双报告（三路由） | 待 | — | — | — |
| **P10** | 指针切换与归档 | 待 | — | — | — |
| **P11** | 长跑与收尾 | 待 | — | — | — |

## 路径口径的落地偏差（如实记）

计划正文写的测试路径是 `tests/plan_v4/…`、`tests/kb_fetch/…`。本仓的既有约定是
**平铺**（`tests/` 下 206 个 `test_*.py`，`pyproject.toml` 里 `testpaths = ["tests"]`）。
本批按既有约定落地为 `tests/test_plan_v4_freeze.py`、`tests/test_plan_v4_instruments_frozen.py`、
`tests/plan_v4_instruments.sha256.json`。子目录本可被收集，但混用两套约定会让
"某个守门在哪"变成要靠找的事——**以既有约定为准**，这条偏差记在这里。

## 当前阻塞与下一步

1. **P1② 是红的**：D1 的书单还没冻结。它的实测底座已经齐（321 条来源清点、
   OCW 188 条候选、arXiv 当晚 0 条），缺的是"把预算从 54 本旧书挪到那 267 条现代来源"
   这一步落到 `sources.yaml`——那是 P3 的第一个动作。
2. **P2②（轮记录文件）** 是 V1 的落地，属于 P2 的剩余项。
3. 数值留白 N1–N5 仍挂着（见 `PLAN_HYPERGRAPH_v4_ANNEX.md` §3），**不影响开工**。
