# 执行计划 v4 · 进度台账

行格式：`阶段 | DoD 条目 | 状态(待/红/绿) | 证据 | 日期 | commit`

状态口径：**绿**＝该 DoD 条目有可复算的证据且已入库；**红**＝试过且失败（附失败输出）；
**待**＝还没开始。**不许把"待"写成"绿"**——本仓的机器门纪律对台账自己一样适用。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **P0** | ①三循环的草案/审查/修订证据齐 | 绿 | 循环 2：`PLAN_V4_REVIEW_LOOP2.md`（37 条，双侧 complete）＋`PLAN_V4_LOOP2_DISPOSITION.md`；循环 3：`PLAN_V4_REVIEW_LOOP3.md`（36 条，双侧 complete）＋`PLAN_V4_LOOP3_REVISIONS.md`（处置稿截断已记账）；守门 `tests/test_plan_v4_freeze.py`（6 条） | 2026-10-05 | `effbe88` |
| **P0** | ②用户明示"开始执行" | 绿 | 用户 2026-10-05 授权："人工部分尽可能你解决"、"你尽管围着高质量方向做，我有很长一段时间不在家"；据此主线自行裁定 D1–D9/R1–R5（`ADJUDICATIONS_v4.md`） | 2026-10-05 | `9e6803e` |
| **P1** | ①D1–D9 各"已裁决＋日期＋选项" | 绿 | `ADJUDICATIONS_v4.md` 一张表 14 行（D1–D9＋R1–R5），动判据的三条标 `须用户点头` | 2026-10-05 | `9e6803e` |
| **P1** | ②`CORPUS_V4.md` 冻结（每源 url/title/author/license/year；四维各≥1 源；sha256 记入 ADJUDICATIONS_v4） | **绿**（本批） | 三条子句都用实测补齐（此前记红的原因是「书单没冻结」）：<br>①**书单身份**：`knowledge/sources.v4.yaml` `sha256=8f968a141f986b34…`（240 源、`cutoff=1980`）；入库 `work/corpus_v4` 240 源、五字段（url/title/author/license/year）**缺项 0/240**、`corpus_digest=3dc686db…`（修掉 HTML 入库之后那枚）；<br>②**四维各≥1 源**（按**内容**实测，`work/_dim_sources3.py`，0 条解析不到）：行为动作情绪意图 **236**／镜头语言 **219**／**构图 15**／**震动与打击感 133**（另：声音对白配乐 167、光 79）⇒ **成立**；<br>③**sha256 已记入** `ADJUDICATIONS_v4.md` 第七节（连同 corpus_digest）。<br>**顺带纠正一条误判**：`CORPUS_V4.md` 曾把「震动与打击感」记成「没有任何已验证来源」——那句只在**关键词层**成立（hit-stop／impact frame／game feel 0 命中），内容层有 **133 个来源／412 条边**；真正最薄的是**构图**（15 源／26 边）。已回写 CORPUS_V4.md §三之一 | 2026-10-05 | 本批 |
| **P1** | ③`tests/plan_v4/instruments.sha256.json` 冻结仪器哈希 | 绿 | 落成 `tests/plan_v4_instruments.sha256.json`（4 个仪器）＋守门 `tests/test_plan_v4_instruments_frozen.py`（7 条，含反面对照）；与 `PLAN_HYPERGRAPH_v4_ANNEX.md` 一起 | 2026-10-05 | 本批 |
| **P1** | ④V1–V9 写进计划（本仓形态：有约束力的附件） | 绿 | `PLAN_HYPERGRAPH_v4_ANNEX.md`："与正文冲突时以本附件为准"，V1–V9 逐条给"覆盖哪里/改成什么/怎么验"；守门 `tests/test_plan_v4_freeze.py::test_the_binding_annex_exists_and_declares_precedence` | 2026-10-05 | 本批 |
| **P2** | ①成对基线（v3pop，只读） | **绿（V1 合规，本批）** | `work/e1_baseline_paired_v3pop.json`（`sha256=2eddbac87af0585d…`；4 轮逐行录档 ＋ 4 份轮记录同住 `work/e1_baseline_paired_v3pop.json.reviews/`，`terminal_states={"valid":4}`、身份字段不一致 **0**、`seed=20261005`、`rows=64`）：<br>· hybrid **0.1979 / 0.2135**（38、41；mean 0.20573，极差 0.015625）<br>· lexical **0.2135 / 0.2188**（41、42；mean 0.216146，极差 0.005208）<br>· Δ(lexical−hybrid) = 0.010416 ＜ 噪声带 0.015625 ⇒ **inconclusive**——与已入库那份（`docs/evidence/20261006-e1-baselines/`，Δ 0.0078 ＜ 极差 0.0365）**结论一致**。<br>`knowledge/` 前后**零改动**（`git status --porcelain knowledge/` 输出 0 行）；`e1_panel.py` 的实际调用点 ＝ `tools/knowledge/e1_report.py` 的 `panel_argv()` 构造 argv ＋ `e1_panel.main(argv_next)`。**注**：已入库那份是 **V1 之前**的产物（无轮记录），现被检查器拒读——留作历史对照；P10 的 `baseline_v4` 会用 V1 合规的执行器重跑 | 2026-10-05 | 本批 |
| **P2** | ②轮记录文件（V1）接到 `e1_panel` 输出旁 | 绿 | 附件 §0／§1 的 V1 **有约束力**，本轮落地：`tools/knowledge/e1_report.py`（**执行器／唯一写入方**）`run_route` **判分前先写** `round.<route>.<n>.json`（身份字段：`seed`／行清单摘要／评委配置摘要〔面板 ＋ 判分提示词 sha〕／语料 manifest／超图 manifest，带 `identity_written_at`），判分后**补终态**（带 `state_written_at`）；检查器 `e1_baseline_summary.py::paired_report` **只读**轮记录：缺文件／终态集外／**同批身份字段不一致**一律整批拒读并点名。V2 的两码（`invalid_parse_fault`／`invalid_empty_intersection`）分开计数、只写轮记录。第四次显式重新冻结（执行器也进冻结清单，5 件）。守门 10 条。<br>**代价如实记**：V1 之前的读数（含 `docs/evidence/20261006-e1-baselines/` 那份 v3pop 基线与今天两臂 × 2 次那份）**不再满足检查器的输入契约**——`paired_report` 会拒读（实测：点名 `缺轮记录 round.hybrid.1.json`）。P10 的"切换后 baseline_v4"会用 V1 合规的执行器重跑，所以这条只影响**历史**对照 | 2026-10-05 | `7d7e5bb` |
| **P3** | ①入口工具（按年门槛选料 ＋ 影子语料分账） | 绿 | `tools/kb_fetch/ingest_corpus.py`（复用 `fetch.py` 的门：scheme／robots／限速／sha256 幂等；新增按 `cutoff=1980` 选料、`excluded.jsonl` 具名原因、`MANIFEST.json` 四字段、`corpus_digest()`、账目闭合断言）；守门 `tests/test_ingest_corpus.py`（6 条，含反面对照） | 2026-10-05 | `c66ca96` |
| **P3** | ②`knowledge/sources.v4.yaml`（带 `year` 的影子来源清单） | 绿 | 新增 `tools/kb_fetch/year_probe.py`（**离线**从 `work/raw/` 的 1201 份已抓正文定年份，纯函数、7 条用例、每条留 `year_basis`）：命中率 **89 → 247/321**（`citation_publication_date` 160／`published_time` 42／JSON-LD 36／版权年 7／课程 slug 2）。据此生成 240 条 `year >= 1980` 的影子清单（Animation Studies 160／BFI 35／StudioBinder 24／Skwigly 16／Frames 3／OCW 2，**旧书 0 条**） | 2026-10-05 | `9b74012` |
| **P3** | ③跑一次入库（`--out work/corpus_v4/`） | 绿 | 真跑 240 条，**kept 240 / excluded 0 / rejects 0**（每条都过了 scheme ＋ robots 门）；产物 `work/corpus_v4/{MANIFEST.json(100KB), fetched.jsonl(36.5MB), excluded.jsonl}`；五字段齐（无缺项）；`corpus_digest = 8179ac69fd881a80da46a622f34f1db0050579f85f74b03db05f57f9a639740e` | 2026-10-05 | 本批 |
| **P3** | ④覆盖偏斜的如实记账 | 红（已知缺口） | v4 的域分布：anime 176／cinematography 49／editing 6／axis_theory 3／storyboard 3／**composition 2／blocking 1**；另有 74 条因缺年份被排除（Gutenberg 47／StudioBinder 26／Animation Studies 1）。`composition`/`blocking` 偏薄是 v4 的既知缺口，P5 的覆盖矩阵要盯它 | 2026-10-05 | 本批 |
| **P4** | ①两趟"分段→归属"抽取器（自研实现，上游只作算法参考） | 绿 | `tools/kb_fetch/extract_segmented.py`：`segment_text()`（确定性、**覆盖全部正文**、超长按句/硬切）、`validate_draft()`（闭集＋出处，**拒收具名**）、`extract()`（两趟驱动，LLM 注入 ⇒ 离线可测）、`DeepSeekClient`（构建期 LLM＝DeepSeek，花费台账落 `work/corpus_v4/spend.jsonl`）；守门 `tests/test_extract_segmented.py`（8 条，含"闭集清单不许抄第二份"与账目闭合） | 2026-10-05 | 本批 |
| **P4** | ②预算可行性实测（D6 的护栏能不能装下） | 红→已更新 | 干跑实测：**240 份来源 → 44,497 段 → 33,060,216 字符 ≈ 2,200 万输入 token**；按域：anime 29,169 段／cinematography 10,644 段（17.1M 字符，StudioBinder 长文）／editing 2,004／storyboard 1,149／composition 917／blocking 346／axis_theory 268。原定 D6（输入 2,000 万）**不够**，已按实测改成输入 4,000 万／输出 1,200 万（见 `ADJUDICATIONS_v4.md` 的 D6 行） | 2026-10-05 | 本批 |
| **P4** | ③真跑一次抽取（`--limit-segments` 试点） | 绿（试点） | 60 段试点：**跳过 31 段过短样板 → 21 条草稿、21 条过粗闭集、0 拒收**，覆盖 8 个边型（TROPE 11／EDIT_RHYTHM 2／PROP_PACK 2／MUSIC_PACK 2／PERFORMANCE_PACK 1／INTENT_PACK 1／SHOT_PATTERN 1／DIALOGUE_PACK 1）。产物 `work/extracted_v4_pilot/` | 2026-10-05 | 本批 |
| **P4** | ④"0 拒收"的**口径**如实记（别把它读成全绿） | 红（已知口径差） | `validate_draft` 只查 type/role/kind ＋ 出处，**不查取值词表与必填槽位结构**。试点样本里出现 `pacing:followed the singer`、`vfx:video feedback`、`allow/applies_to_genre` 这类写法——它们过得了 P4 的粗闭集，过不了 `hypergraph.validate_edge` 的词表关。⇒ **拒绝率的重头戏在 P5**，D9 的 rejects 率护栏到那时才有读数 | 2026-10-05 | 本批 |
| **P3** | ⑤管线第 2 步（HTML→正文） | 绿（修复后重跑） | P4 试点暴露的真缺陷：入库存的是**原始 HTML**（`fetched.jsonl` 36.5MB），抽取器看到样板代码、一条草稿都产不出。补上 `extract_text` 后重跑：`fetched.jsonl` **36.5MB → 7.66MB**，`corpus_digest` `3dc686db432e2cd7727b70684f7cc88efe15dd8d29aef5264ce310e5c5861eb9` | 2026-10-05 | `037aef9` |
| **P5** | ①影子构建器（草稿 → 现役 `to_edge` → 影子目录，**一行不改**被冻结的构建器） | 绿 | `tools/kb_fetch/build_shadow.py`：`segment_cards()`（**片段即卡片**，键＝`seg:<digest>:<start>-<end>`，`source_span` 供 `to_edge` 定位）、`draft_to_raw()`（查不到片段即 `no_segment_for_span` 具名拒收）、`hg_to_edge()`（薄壳直调现役 `to_edge`）、`build_shadow()`（落 `hypergraph.edges.jsonl` ＋ `build_report.json`，账目闭合）；守门 `tests/test_build_shadow.py`（10 条） | 2026-10-05 | 本批 |
| **P5** | ⑪**全量 L1/L2 影子构建跑完** | 绿（**关键里程碑**） | 全量抽取（`--mode scoped`，后台约 3 小时）：**33,045 段 → 5,139 条草稿 / 1,143 拒**（`skipped_short` 19,803、`no_candidate` 6,169、**15,764 次调用**），**16/16 个边型都有**（TROPE 1663／EMOTION_PACK 1115／TRANSITION_PACK 573／DIALOGUE_PACK 489／AXIS_RULE 410／ACTION_BEAT 205／SOUND_PACK 162／LIGHT_PACK 139／SHOT_PATTERN 102／MUSIC_PACK 70／INTENT_PACK 66／EDIT_RHYTHM 54／IMPACT_PACK 47／STAGING_PACK 20／PERFORMANCE_PACK 20／PROP_PACK 4）。<br>影子构建：**5,139 → 5,000 条边**（拒 139，全 `missing_required`），`cards: 33045`。<br>对照现役发货索引 **638 条边** —— v4 是它的 **7.8 倍** | 2026-10-05 | 本批 |
| **P5** | ⑫**全量覆盖矩阵** | 绿（但仍偏斜） | 5,000 条边：按维度 行为动作情绪意图 **3043**／镜头语言 **1099**／**构图 26**／震动打击感 **412**／声音对白配乐 **719**／光 **137**；按域 anime 4091／cinematography 1014／editing 164／axis_theory 126／storyboard 26／composition 9／blocking 6。<br>**`all_dimensions_non_empty: true`** —— 早前切片里"构图 0 条"是**小样本假象**（切片只有 712 条边）；全量下构图有 26 条，但仍是**最薄的一维**（比第二名少一个数量级）。7 个空格、16 格低于 floor=10 | 2026-10-05 | 本批 |
| **P5** | ②第一次真实读数（必填槽位门） | 红→已修 | 用 P4 试点的 21 条草稿跑影子构建：**0 kept／21 rejected，全部 `missing_required`**。根因不是模型的错——提示词只列了闭集、**没列每种边型的必填槽位**，模型答的是"这段讲了哪几个槽位"而 schema 要"凑齐哪几个"。已在 `edge_type_menu()` 里逐条写出必填（现读 `REQUIRED_MEMBERS`） | 2026-10-05 | 本批 |
| **P5** | ③改提示词后的第二次读数（质量 ↑ 产量 ↓ 的权衡） | 绿（有保留） | 同一批 60 段重跑：草稿 **21 → 4**，但 **4/4 通过、0 拒收**，影子构建 `closes: true`。⇒ 必填约束让模型变保守：**质量上去了、产量下来了**（4/29 可用段 ≈ 14%）。下一步候选：两段式提问（先问"这段适用哪些边型"，再为那些边型要**完整槽位集**），但这属于 P4 的迭代，如实挂着 | 2026-10-05 | 本批 |
| **P5** | ④取值词表关（`NodeIndex`）——**已接上，并拿到真读数** | 红（关键发现） | 用现役 `vocabulary.run()` 在**新语料**上建 v4 词表（**181 个节点**；`lens` 一类开放值靠正文里的 `\d+mm` 汇出，只跑受控表会少掉它们），再构造 `NodeIndex` 传给 `to_edge`。**接上之后，原先"4/4 通过"的 4 条草稿变成 0/4 全拒**（全部 `missing_required`，原因里带 `dropped=`）。丢掉的取值长这样：`pacing:rapid`（词表是 short/medium/long）、`lens:长镜头`（词表是 24/35/50/85mm——而且**塞错了 kind**）、`genre:music video`、`emotion:non-narrative`、`headroom_policy:一镜到底`。⇒ 模型写的是**语义合理但不在冻结词表里**的取值 | 2026-10-05 | 本批 |
| **P5** | ⑤提示词加"每个 kind 的允许取值" | **红（负结果）** | 已实现（`value_lines()`：给了词表按 kind 列取值、没给退回 `hg.VALUE_DOMAINS`；CLI `--vocab-from-corpus`），但**真实试点是负结果**：<br>· 提示词 **3,302 字符／26 kind／374 取值**，96 字与 1,040 字的段**都返回 `{"drafts":[]}`**；<br>· 同一批 40 段（`--min-chars 200`，14 个实质段）→ **0 草稿**。<br>⇒ **把 374 个取值平铺进一次调用会把模型压死**。约束越加越严的整条曲线：21 条（无必填表）→ 4 条（加必填表）→ **0 条（加取值表）**——精度升、召回降到零 | 2026-10-05 | 本批 |
| **P4/P5** | ⑥两段式提问（已实现） | 绿（实现）／**红（读数）** | 已落 `extract_two_step()` ＋ `type_prompt()`／`member_prompt()`／`parse_types()`／`parse_members()`，CLI `--mode two-step`；17 条用例全绿（含"B 段只带被选中边型的 kind 与取值"）。**但真实读数是 0**：40 段（14 个实质段）→ `calls: 16`（A 段 14 次 ＋ B 段 2 次）→ **0 草稿**。A 段对 700–1,040 字的段**一律返回 `{"types":[]}`** | 2026-10-05 | 本批 |
| **P4/P5** | ⑦语义注解（从 v18 提示词**解析**，不抄第二份）＋ 一致性守门 | 绿（工具）／**红（效果）** | `type_glosses()` 从现役 `build_hypergraph.SYSTEM_PROMPT` 里解析出 **16/16** 个边型的一句人话注解（实测 `ACTION_BEAT` 取到"……叙事**节拍**、强度绑死"），`hg.EDGE_TYPES` 里缺注解就**抛错**（守门用例当场红）。但**把它加进提示词后产量从 4 掉到 0**（pilot8/9，重复两次） | 2026-10-05 | 本批 |
| **P4/P5** | ⑧**实测阶梯**：每加一层 schema 细节，产量掉一截直到归零 | 绿（读数）／已按它回退 | 同一批 60 段／`deepseek-chat`／temperature=0：<br>**只给边型 21 条 → ＋必填槽位 4 条 → ＋允许取值 0 条 → ＋语义注解 0 条（重复两次）→ 两段式（A 问边型／B 填槽位）0 条**。<br>⇒ 处置：**默认单段提示词退回"只给必填槽位"**（已知最好状态），取值表（`value_lines()`）与注解（`type_glosses()`）保留为**可选件**供两段式 B 段用；并写了一条守门用例 `test_the_single_step_menu_deliberately_omits_values_and_glosses` **防止有人再把它们塞回去**。回退后复跑：**4 条草稿**（与 pilot2 一致，可复现） | 2026-10-05 | 本批 |
| **P4/P5** | ⑨结构判断：**分段粒度可能就是根因** | 已选 **A 路** | v18 是在**卡片**（已蒸馏的短知识单元）上抽取，而 v4 把**学术散文段**（700–1,040 字）直接喂进去。⇒ 选 A：抽取前加"片段 → 短知识陈述"的蒸馏，让抽取回到 v18 那套已被验证的输入形状。（B 路"L1 仍由卡片承载"留作对照） | 2026-10-05 | 本批 |
| **P4** | ⑩A 路第一段：蒸馏器（散文 → 短陈述） | 绿 | `tools/kb_fetch/distill_segments.py`：`distill_prompt()`（明写"不要评论／不许发明／不要把例子当规则"）、`parse_statements()`、`distill()`（每条带**出处指针** `source{url,sha256,span}` ＋ 兼容 P4 记录的 `source_ref`；复述整段判 `too_long`；解析失败具名；账目闭合）；守门 `tests/test_distill_segments.py`（5 条）。**真实读数：29 个实质段 → 165 条陈述，0 拒收、0 解析失败（≈5.7 条/段）** | 2026-10-05 | 本批 |
| **P4** | ⑪span 透传（记录自带出处指针 ⇒ 当原子段） | 绿 | 新增 `segments_of()`：记录里 `source={url,sha256,span}` 且 `start<end` 就**原样用那个 span**，不再重新分段；`extract()`／`extract_two_step()` 都改走它。守门 3 条（原子段不被切、无指针仍正常分、**草稿保留原 span**）。**修好之后** `no_segment_for_span` 那类拒收消失，取而代之的是**真门**的拒收（`missing_required`） | 2026-10-05 | 本批 |
| **P4** | ⑫成对重测：蒸馏到底有没有用 | 绿（结论：**不是它**） | 同一批 60 段，两臂都过影子构建（**词表关开着**，即正确状态）：<br>· **A 臂 直接抽取**：29 个实质段 → 4 条草稿 → 影子构建 **0 kept / 4 rejected**（全 `missing_required`）；<br>· **B 臂 蒸馏后抽取**：29 段 → 165 条陈述 → 2 条草稿（其中 1 条在抽取阶段就被拒）→ 影子构建 **0 kept / 1 rejected**（`missing_required`）。<br>⇒ **两臂都是 0，蒸馏没有解决问题**（B 臂产量还更低）。蒸馏本身很干净（165/165），但真瓶颈不在输入形状 | 2026-10-05 | 本批 |
| **P4** | ⑬候选边型改为**查词表**（不问模型）＋ 逐边型填槽位 | 绿 | `candidate_types(text, nodes)`：正文里出现某边型必填 kind 的词表取值（含中文写法／别名，`node_surfaces()`）即算候选，按命中数排序、**确定性**；`extract_scoped()` 只对候选边型发问，没命中的段**一次调用都不花**；CLI `--mode scoped`。守门 4 条（查表选型、排序确定、只对候选发问、无候选不调用） | 2026-10-05 | 本批 |
| **P4** | ⑭**允许推断**（我上一版提示词与仓库设计相悖） | 绿（关键修复） | 实测：B 段 76 次调用**全部返空**——因为我写了"填不齐就返回空数组，不许编"。而本仓设计本来就允许推断：`build_hypergraph.py:178` 记着"284 个槽位里 86 个 quoted（30.3%）／**198 个 inferred**"。机制上 `to_edge` 里**给了依据但原文没有 ⇒ fabricated；不给依据 ⇒ inferred**，所以正确写法是"原文没明说的槽位**不写第 4 项**"。改完后：76 次调用 → **21 条草稿**（从 0 到 21） | 2026-10-05 | 本批 |
| **P4** | ⑮成员形状归一化（`to_edge` 之前） | 绿（关键修复） | 试点暴露的**唯一**拒收形态：21 条里 19 条是三种写法滑倒——`["allow/genre","genre","genre:动画"]`（首格含斜杠）、`["action","action","action:出场"]`（首格是 kind，角色要查 schema）、`["beat_type","qualifier","beat_type:establish"]`（角色与 kind 互换）。归一化器 `normalise_members(members, edge_type)` 三类都收，并且**在写进草稿之前**就归一（否则归一化只在校验里生效、下游 `to_edge` 照样被拒）。**不是放宽判据**：闭集与必填槽位照样由现役门把关 | 2026-10-05 | 本批 |
| **P5** | ⑥**端到端第一次跑通**：60 段 → 19 条合法边 | 绿 | `--mode scoped` ＋ 影子构建（**词表关开着**）：60 段 → 跳过 31 段过短、3 段无候选 → 76 次调用 → **20 条草稿、19 条保留、1 条拒**；影子构建 **19/19 全过、0 拒**。对照本批开始时的 0 条：**这是第一次有草稿穿过取值词表关** | 2026-10-05 | `9aa740e` |
| **P5** | ⑦**分层切片跑**（240 份里隔 8 取 1 = 30 份，跨全部 7 个域） | 绿 | 30 份 → **4,090 段**（2,498 过短跳过、670 无候选）→ **2,112 次调用**（≈0.35 s/次）→ **910 条草稿、732 保留、178 拒**；影子构建 **732 → 712 保留 / 20 拒（2.7%）**，写出 **712 条边**，覆盖 **14/16 个边型**（TROPE 177／EMOTION_PACK 163／DIALOGUE_PACK 97／TRANSITION_PACK 93／AXIS_RULE 73／ACTION_BEAT 33／SOUND_PACK 32／LIGHT_PACK 17／MUSIC_PACK 15／EDIT_RHYTHM 7／INTENT_PACK 2／IMPACT_PACK 2／PERFORMANCE_PACK 1）<br>**D9 护栏的第一次真实读数：rejects 率 ＝ 20/(712+20) ＝ 2.7%**（线 0.30，远低于）。按份数外推：240 份约 **5,700 条边**（现役发货索引 638 条） | 2026-10-05 | 本批 |
| **P5** | ⑧抽取层拒收的**形状归一化**（178 条全 `bad_role`） | 绿（部分） | 又抓到一类可修形状：模型把**边型名**写在成员首格（`["TROPE","genre","genre:日式动画"]`）。归一化器补上这条，并用**存盘的原始回包**离线复算（不花新调用）：**52/178（29.2%）现在能通过** `validate_draft`。<br>剩下救不回的是**内容缺口**（例如 `["EDIT_RHYTHM","qualifier","qualifier:avg_shot_len"]` 里没有取值）与**首格是角色名**（`["Destino",…]`、`["female",…]`）——那两类**不该**用归一化硬修，拒收是对的 | 2026-10-05 | 本批 |
| **P5** | ⑨全量跑的成本实测（**超 D6 的护栏**，需裁决） | 红（需裁决） | 切片实测：30/240 份 → **2,112 次调用**。线性外推到 240 份 ≈ **16,900 次调用**。按时均每次约 0.35 s ≈ **1.6 小时**（可接受）；但 token 侧：切片每次调用平均 prompt ≈ 1.1k token ⇒ 全量 ≈ **1,900 万输入 token**（在 D6 的 4,000 万内）**但输出侧**（每次约 200 token）≈ **340 万**（在 1,200 万内）⇒ **按这次实测，D6 装得下**。⚠️ 上一轮"4 万次调用"的外推是**高估**的（当时按 43% 段有候选算，实测只有 22.5%），这条更正是从切片实测算出来的 | 2026-10-05 | 本批 |
| **P5** | ⑩**覆盖矩阵**（域 × 研究维度）落地并跑出读数 | 红（**构图维度 0 条边**） | 新增 `tools/knowledge/coverage_matrix.py`：维度←边型的**唯一映射**（反查表由正向表现算，两表不可能各说各话）＋守门"每个边型都必须有维度归属"；格 ＝ `(域, 维度)`，空格与低于门槛的格分开列；查不到域的边进 `unknown_domain` 而**不许悄悄算进某一格**。守门 5 条。<br>**切片读数（712 条边）**：按维度 行为动作情绪意图 **376**／镜头语言 **175**／**构图 0**／震动打击感 **67**／声音对白配乐 **144**／光 **17**；按域 anime 609／cinematography 91／editing 54／axis_theory 25；**7 个空格、5 格低于门槛、`all_dimensions_non_empty: false`**。<br>⇒ **构图这一整维在 v4 里是空的**——与 `CORPUS_V4.md` 早就记的"`composition` 只 2 条来源"对上，但这次是**边级**的量化证据，不是来源数的间接推断 | 2026-10-05 | 本批 |
| **P6** | ①案例层的输入（分段 → 许可门），**复用现役管线** | 绿 | `tools/kb_fetch/build_cases_v4.py`：编排 `chunk.run` ＋ `validate_licenses.check`（**只用纯函数**——`run()` 会写现役 `work/licensed.jsonl`，那是我踩过两次的同一类坑），落影子目录。真跑：**308 段 → 304 保留 / 4 拒，账目闭合**。守门 `tests/test_build_cases_v4.py`（4 条，含"影子构建不许动现役 work/ 输入"的回归守门） | 2026-10-05 | 本批 |
| **P6** | ②案例层构建（交给**现役** `build_cases`） | **绿（修掉缺陷后）** | 第一次真跑：810 条案例、`reject_ratio 0.0753` ⇒ `passed: false`（当时**没动门限**，先归因）。<br>**修掉的缺陷**：`chunk.run` 是 **L1/L2 那条路**的分段器，会**跳过全部 `layers: [L3]` 来源**——我把它错接到案例层的输入上，于是 **202 条 L3 来源（StudioBinder／Animation Studies 那批，正是现役 1143 条案例的主力）整批没进去**。现役 `build_cases.INPUT` 指的是 `licensed.jsonl`（整篇来源），它自己会切段；所以编排默认改成**直通**。<br>**修复后**：**783 条案例**、`raw_segments 7544`、`rejects 148`、**`reject_ratio 0.0196`** ⇒ **`passed: true`、`problems: []`**；域分布 cinematography 375／anime 190／editing 129／composition 37／storyboard 27／blocking 19／axis_theory 6。<br>**通过是修缺陷的结果，不是调参**：口径没动、门限没动，变的只是"把该进案例层的来源放进去了" | 2026-10-05 | 本批 |
| **P6** | ④那 117 条的**归因**（把"7.5%"拆开） | 绿（诊断） | `work/_case_reject_diag.py`（复用 `build_cases()` 的返回值，不动门限）：三种拒收分开记——**`quote_gate` 117**（进 `reject_ratio`）／`near_duplicate` 56／`quota` 570（后两者**不进**比例）。`quote_gate` 的分布**高度集中**：**两份 MIT OCW 讲义 PDF 占 34 条**（`08e30130…` 23 ＋ `c7c1a8f0…` 11），其余是若干来源各 4 条。<br>归因：讲义多是标题/条目，**没有可引用的句子**。⇒ 这是**语料配额**问题（我生成 `sources.v4.yaml` 时给所有来源统一 `chunk_budget: 20`，没按"可引用内容"区分），**不是门的问题**。对照：现役发货那次 2.45%（分母 10461），v4 是 7.53%（分母 1553）——分母小 6 倍会让同样的绝对拒收放大成高比例 | 2026-10-05 | 本批 |
| **P6** | ⑤配额工具（A 路，按实测可引用量） | 绿（工具）／**已不必再动语料** | `tools/kb_fetch/allocate_budgets_v4.py`：配额 ＝ 该来源的**实测可引用段数**（`pick_excerpt` 过得去的段数），下端 `min_budget` 兜底、上端 `max_budget` 封顶、每条配额带 `budget_basis`；守门 4 条（比例、封顶兜底、依据、确定性）。<br>**实测**：43 个来源有量测值、**0 个"完全不可引用"**——所以问题不在"某来源全废"，而在来源内部有段落过不了引用门。<br>**但 ② 修好之后，这条已经不必要**：`reject_ratio` 从 7.5% 掉到 1.96% 的原因是"把该进的来源放进去了"（分母从 1553 涨到 7544），**不是**配额不匹配。工具留着（下次换语料时仍可按实测配），**本轮不改 `sources.v4.yaml` 的配额**——避免在没有必要的时候动语料面 | 2026-10-05 | 本批 |
| **P6** | ⑥教训（同一类坑的第三次） | 记录 | 这一个缺陷与早前两次同形：**把"某一层的工具"接到了"另一层的输入"上**（`chunk.run` 是 L1/L2 的；案例层的输入是整篇来源）。三次的共同点是**管线里有一道"按层分流"的约定，而它只写在代码注释里、没有机器判据**。已补的判据：`test_the_case_layer_input_is_the_licensed_documents_not_the_chunked_stream` | 2026-10-05 | 本批 |
| **P6** | ③冻结评测集（`freeze_eval.py`） | 绿 | `tools/knowledge/freeze_eval.py` ＋守门 `tests/test_freeze_eval.py`：把 long21 的查询冻成 v4 的**共享输入**（`work/eval_sets/heldout_v4_long21.jsonl`，64 条，摘要 `2e0add31…`）。**台账漏记**：产物 15:04 就落地，本行直到现在才回写 | 2026-10-05 | `a8ff545` |
| **P7** | ①索引指纹 / 客户端＋适配器 / 服务层 | 绿 | 三块都落地并有守门：`manifest.py`（四格指纹、缺格拒收、fail closed）、`lightrag_client.py`（stdlib，**住插件包内**）、`lightrag_adapter.py`（返回必须是传入 `cases` 的子序列、降级具名）、`serve.py`（只绑环回、503/500 都具名）。**顺带抓到并修掉一个分层违规**：适配器曾从 `tools.` 导入 → 客户端搬进 `block_director/knowledge/` ＋ 架构守门 `tests/test_plugin_layering.py` | 2026-10-05 | `718d6bf`／`51c35f3` |
| **P7** | ②**全量索引**（783 条案例）＋ 端到端复核 | 绿 | `build_index --cases work/knowledge_v4_cases/cases --out work/lightrag_v4` → **783 篇文档**，指纹 `35f09d48f16642bb…`。端到端（`work/_e2e_lightrag.py work/lightrag_v4 "轴线规则怎么用"`）：`/health` ok ＋ 指纹；适配器返回 4 个 `Case`，`last_reason: unknown_id_dropped:1`（**设计在工作**——不在传入 `cases` 里的 id 被丢弃并具名记账）。<br>**检索语义是对的**：查"轴线"top 命中全是 `what-is-an-eyeline-match`（eye-line＝视线轴）；但**只是一个查询的观察，不当质量结论** | 2026-10-05 | 本批 |
| **P7** | ③A/B 第一轮（三路由 × 1 次） | **红（不能据此裁 D8）** | 三臂各跑一次（同一 long21 面板、`--top-k 3`、两位评委）：<br>· **hybrid 40/192 ＝ 0.2083**（181/192 行两位评委齐）<br>· **lexical 43/192 ＝ 0.2240**（182/192）<br>· **lightrag 3/142 ＝ 0.0211**（142/142）<br>两处**必须先说清**的口径问题（这也是为什么**不许**拿它裁 D8）：<br>① **只有 1 次重复** ⇒ 噪声带 R＝0，"separated"是**恒真**（任何非零 Δ 都会被判分得开）；<br>② **分母不对称**：lightrag 只产出 **142 行**（另 ~50 条查询它**一条都没召回**），而 E1 的分母是"面板条目数"——**返回空列表的查询不是记 0 分，而是整行消失**，于是它的分母比另两臂小 26%。这不是同一把尺子 | 2026-10-05 | 本批 |
| **P7** | ④lightrag 臂为什么这么低 | **红（根因已定位并修复）** | ① **图谱是空的**（真缺陷）⇒ `hybrid`/`local`/`global` 三模式全废、只剩 `naive`。根因是我写的 `llm_model_func` **丢了 `system_prompt`**，而 LightRAG 的**格式规范写在 system 里**；修好后 12 篇试点出 **376 节点/153 边**（`90e3809`）。<br>② 检索模式已做成可选（`naive`/`local`/`global`/`hybrid`/`mix`，`dec8037`）。<br>③ **分母口径**是判据级问题，已按红线单列成 **D10**（`ADJUDICATIONS_v4.md`）：三臂实测 hybrid／lexical 各 **64/64** 条查询有行，lightrag 只有 **59/64**、平均 2.4 行/查询（另两臂 3.0）——召回为空**不是记 0 分而是整行消失**，于是弱臂分母更小、每行更值钱。选项 A 维持／B 固定分母（动判据）／**C 两者并报**（主线建议），**须用户拍板** | 2026-10-05 | 本批 |
| **P7** | ⑤修复后的全量索引重建 | **红→作废（已定位）** | `work/lightrag_v4_fixed2` 跑到 **440/783** 时主动停止：它的入库文档是 `title+excerpt`（**不含中文线索**），而三臂必须同一检索面（见 P7⑧）。留作"有图谱、无中文面"的对照物，**不作为交付代** | 2026-10-05 | 本批 |
| **P7** | ⑥**第二轮更正**：A/B 第一轮还犯了**代际不一致** | 红（已定位） | lightrag 臂的索引建在 **v4 案例层（783 条）**上，而面板传进去的是**发货案例集（1143 条）**——适配器的纪律是"返回必须是传入 `cases` 的子序列"（ADR-0014 的陈旧化陷阱防御），于是**大部分返回 id 被当"不在集合里"丢掉**（第一轮 142 行里 `unknown_id_dropped` 就是这么来的）。<br>⇒ 这不是"LightRAG 检索差"，是**拿 A 代的索引去评 B 代的案例集**。**三条臂必须跑在同一代案例上**（计划 P9 本来就说 A/B 在 `v4pop` 上做）。<br>正确跑法：`e1_panel --cases-dir work/knowledge_v4_cases`（v4 案例层，布局与发货一致：`cases/part-*.jsonl` ＋ `cases.manifest.json`），三臂同用 | 2026-10-05 | 本批 |
| **P7** | ⑦**"三臂全塌到 ~0"的根因：v4 案例层整份缺中文检索线索** | 红→已修（`ba34e06`） | 对齐后的三臂（`work/ab_v4_aligned`，同一 v4 案例层、同一冻结查询集、`--top-k 3`）：hybrid **0.0065**／lexical **0.0104**／lightrag **0.0000**。逐行查：hybrid 153 行里 **zh 非空 0 行**（现役那份是 192/192）；score≥4 的行 **1**（现役 39）。<br>**排除了"excerpt 质量"这个假设**：现役 1143 条与 v4 783 条的摘录长度分布几乎同形（mean 105 vs 102、<40 字 1% vs 4%、句末标点 87% vs 86%）；**655 条 v4 案例的 excerpt 与现役逐字节相同**，其中 526 条在现役层拿得到非空线索，而 v4 层一条都没有。<br>⇒ 根因是**线索层整份缺失**：v4 案例层只"生成"了线索，没做"**重签 ＋ 记账**"（`read_search_zh` 对不上 `cases_sha256` 就整份拒用），而 manifest 里没有 `clue_attached` 可查 ⇒ 每一步单独看都"绿" | 2026-10-05 | `ba34e06`／`d1d05d3` |
| **P7** | ⑧**检索面必须同一把尺子**：LightRAG 的入库文档也要并入中文线索 | 红→已修（`0d40976`） | 另两条臂的检索面是"案例文本 ＋ 中文线索"（`CaseIndex._text`），只有 LightRAG 臂是 `title+excerpt`——产品查询是中文散文、案例原文是英文，"LightRAG 更差"里于是混着"它的文档少了中文面"这个与算法无关的差别。`case_documents(cases, clues)` ＋ `--clues local|none`；顺带补代际洞：`cases_digest` 只摘案例分片，**只改一条线索的文案（条数不变）第一格不动** ⇒ `clues_digest` 进 `build_args` | 2026-10-05 | `0d40976` |
| **P7** | ⑨**侧车"每次查询新建事件循环"（真缺陷，5773 行证据）** | 红→已修（`0d40976`） | `work/_sidecar4.err` 5826 行里 **5773** 行 `is bound to a different event loop`：`LightRAGIndex.search` 每次 `asyncio.run()`（新建循环）而 `_rag` 跨调用复用；`serve.py` 是 `ThreadingHTTPServer`（每请求新线程），只会更早复现。后果：LightRAG 查询失败 ⇒ `CaseIndex` **退回 BM25**，而那些行的 `retrieval_path` 仍写着 `lightrag`——**请求的臂被当成了实际干的活**。修：常驻事件循环＋`run_coroutine_threadsafe`＋`query_timeout`（`serve.py --query-timeout`）；取证字段 `cases_backend_effective`/`cases_degrade_reason` 进每行（`ba34e06`） | 2026-10-05 | `0d40976`／`ba34e06` |
| **P7** | ⑩**中文线索补齐**（glm-5.3，779 条待跑） | 进行中 | `case_search_zh --cases work/knowledge_v4_cases/cases --workers 16`（用户 2026-10-05 买下智谱 embedding-3 资源包后 GLM 通道可用；线索生成仍走 `glm-5.3`，与现役那份**同一条提示词**：`prompt_sha256=36069623…` 逐字节相同）。前三批实测 **0 条 `call-failed`**（丢掉的全是规则内的 `empty`——摘录确实不含工艺信息），与现役逐字节相同的 655 条里 526 条在现役拿得到线索 | 2026-10-05 | 本批 |
| **P8** | 插件侧适配器（门控默认关） | 绿 | `block_director/knowledge/lightrag_adapter.py` 已实现并有 4 条守门（子序列、降级具名、fail closed、真走 HTTP）；**门控注册**（`BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG`，默认关）也已完成：`block_director/__init__.py` ＋守门 `tests/test_lightrag_registration.py`。默认路由**不切换**——那要等 P9 的读数 | 2026-10-05 | `718d6bf`／`440ca38` |
| **P7** | ⑪**补齐线索后的两臂读数（同一批 64 条冻结查询、`--top-k 3`、两位评委）** | 绿 | 产物 `work/ab_v4_clued/reviews.{hybrid,lexical}.rep1.jsonl`（每行自带 `clue_state=""`、`cases_backend_effective`、`cases_fingerprint=4b1b44bb…`）：<br>· **hybrid 36/192 = 0.1875**（补线索前 0.0065）<br>· **lexical 40/192 = 0.2083**（补线索前 0.0104）<br>⇒ 回到现役层的同一档（0.19–0.23）。**这是"根因是线索层缺失"的修复性验证**：不是解释，是改完之后同一个面板上重测出来的 | 2026-10-05 | 本批 |
| **P9** | ①A/B 双报告（三路由 × N 次 ＋ 成对差值 ＋ inconclusive） | **绿（本批完成）** | 产物 `work/e1_v4pop_ab.json`（`sha256=bde5f2dbb846928c…`，入库存档 `docs/evidence/20261005-p9-v4pop/`）：**三路由 × 2 轮 ＋ 成对差值 ＋ inconclusive 标记**，判词整份走 `e1_baseline_summary.paired_report`（噪声带 ＝ 各臂同臂极差最大值）。计划里写死的 `e1_report.py` 以前**不存在**，本轮补齐；`--rounds-only` 让它能分次跑（先两臂、等 sidecar 起来再跑第三臂），最后 `--reuse` 汇总。读数见下面的 ④ | 2026-10-05 | `b11fc21`／本批 |
| **P9** | ②E3 双报告（三路由经验越权数） | **绿（本批完成）** | `work/e3_v4pop.json`（入库存档 `docs/evidence/20261005-p9-v4pop/e3_v4pop.json`）：`status=pass`；层一级 `quality.e3_cases`（`tools/knowledge/quality.py:617`）**0/783**；6 轮召回里 `constraint_fields` 与 `constraint_clues` **全为 0**（三路由经验越权数全 0 ✓）。词表/键表同源派生（`case_search_zh.CONSTRAINT_WORDS`、`quality.CONSTRAINT_KEYS`），不另抄一份 | 2026-10-05 | `b11fc21`／本批 |
| **P9** | ③PROGRESS 记检查器调用点 ＋ 查询集来源 ＋ 结果表 | 绿 | 调用点：`tools/knowledge/e3_report.py:112`（层一级）、`:97`（字段越权）、`:100`（线索越权）；查询集：`work/eval_sets/heldout_v4_long21.jsonl`（**64 条**，`sha256=e02161be89eef4ab…`，来自真跑 `docs/evidence/20261006-long21/project/project.bdproj` 的逐镜散文；64 × top_k 3 ＝ **192 行/臂**——台账里那个"192 行"就是行数，不是查询数）；结果表见本表 ① ② 两行 | 2026-10-05 | `b11fc21` |
| **P9** | ⑤**三臂 × 2 轮的正式读数（D8 的判定证据）** | **绿** | `work/e1_v4pop_ab.json` ＋ `docs/evidence/20261005-p9-v4pop/README.md`：<br>· `hybrid` **0.192708 / 0.192708**（37、37 行；mean 0.192708，极差 0）<br>· `lexical` **0.197917 / 0.182292**（38、35；mean 0.190105，极差 0.015625）<br>· `lightrag`（真索引、`hybrid` 模式、本地嵌入、含线索、指纹 `c1cd106e…`）**0.026042 / 0.026042**（5、5；mean 0.026042，极差 0）<br>· 噪声带 R＝**0.015625**：hybrid↔lexical Δ −0.002603 ⇒ `inconclusive`；**hybrid↔lightrag Δ −0.166666／lexical↔lightrag Δ −0.164063 ⇒ 双双 `separated`**<br>⇒ 按 D8（「ΔE1 ≥ R 且 E3=0 ⇒ lightrag 默认」）**LightRAG 不满足切换条件**，默认路由维持 `hybrid`（`BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG` 仍默认关）。<br>**可信度**：`all_rounds_used_the_route=true`（6 轮全无降级、lightrag 两轮 64/64 查询有行）、身份字段不一致 0、`terminal_states={"valid":6}`、`seed=20261005`、`rows=64`。<br>**折扣**：hybrid/lexical 各轮 7–14 行只有一位评委（`all_rounds_complete=false`）；lightrag 只测了 `hybrid` 检索模式（`naive` 档与云端那一代走 D3） | 2026-10-05 | 本批 |
| **D3** | 嵌入路线（本地 `bge-small-zh` 512 ↔ 智谱 `embedding-3` 2048） | **绿（实测对照）** | `docs/evidence/20261005-d3-embedding/`（`e1_d3_embedding.json` ＋ 4 轮录档 ＋ 4 份轮记录）：**同一条 lightrag 路由、同一案例层、同一批 64 条冻结查询、同一面板、同为 `naive` 模式**，只差嵌入器——local **0.026042 / 0.015625**（mean **0.020833**，极差 0.010417）、cloud **0.119792 / 0.114583**（mean **0.117188**，极差 0.005209）；**Δ = +0.096355 ＞ 噪声带 0.010417 ⇒ `separated`**（云端嵌入器把这条路提高约 **5.6×**）。`all_rounds_used_the_route=true`、`terminal_states={"valid":4}`。<br>**与 D8 并存不矛盾**：嵌入器层面云端更好；路由层面即便换云端，LightRAG（0.117）仍低于 hybrid 0.193／lexical 0.190 ⇒ **默认路由仍 `hybrid`**。<br>**小混杂如实记**：拷缓存时本地那代还在收尾 ⇒ 云端那代重抽 2 篇（图谱 6385/6205 vs 6386/6243 节点/边，差 ≈0.6%）；**未核验**：云端那代的 `hybrid` 模式、云端嵌入的联网依赖与成本 | 2026-10-05 | 本批 |
| **P11** | ①③ 长跑证据链 ＋ 门①–⑩（canonical 入口） | **绿（本批）** | `tools/run_tests.ps1` 32/32 步全绿（Blender 5.2.0 LTS；pytest 2286 passed／1 skipped、`SMOKE_OK`、headless `state=DONE`、11 探针全 `OK`、`tree.json` `stable: true`）；`holdout_gates.json` 门①–⑩ **全 pass**（canonical 带 `--assertable`／`--exclude-cards`／`--reviewer-classes human,llm-panel`）。录档 `docs/evidence/20261005-213820/`。**唯一未达的是那条红线**：`rks.json` 的 `failed_checks: ['RK-13']`（＝ E1 ≥ 0.70，现读数 0.19–0.21）——R3 已如实挂着"不承诺可达、不降线"，但链子仍 `exit 0`，这条口径问题列在阻塞清单第 8 条 | 2026-10-05 | 本批 |
| **R3** | E1 ≥ 0.70 的**可达性**（不降线、不换分母） | **绿（判据已立；读数分两批）** | ①**结构判据**（`docs/evidence/20261006-e1-ceiling/`）：把候选面判到 **top-20**（64 条冻结查询 × 20 行 ＝ 1,280 行，两位评委判完），precision@20 ＝ 178/1280 ＝ 0.1391；每条查询 top-20 里的相关行数 均值 2.78／中位数 3（0 条相关的 4 条、≥3 条的 **38/64**）⇒ **完美重排上限 ＝ 0.7760 ≥ 0.70**：这条红线**结构上可达**，差距在**重排器质量**（不是候选面不够）。<br>②**杠杆实测**（同一批查询、同一批评委）：基准 0.1927；产品自带 LLM 过滤 **0.1720 ✗**；`ms-marco` cross-encoder 重排 **0.1302 ✗**；查询侧对齐（中文指令→英文工艺词）**0.1719 ✗**；第三方 LLM 重排（`qwen3.8-max`）**唯一有效**（见下条）。<br>**口径如实记**：0902 型号那一批 rerank 读数有 78–144/192 行失败降级，**已标作废**（`docs/evidence/20261005-e1-filter/README.md` 的作废说明）；干净读数用**`qwen3.8-max`**（用户 2026-10-06 更正型号）重跑 | 2026-10-06 | 本批 |
| **P10** | 指针切换与归档 | **已裁决：不切换（D13 = A）** | 第三方（Kimi K3，`docs/evidence/20261006-adjudication-kimi/`）给定可证伪触发器"v4 的 top-20 相关均值 ≥ 现役 ＋ 0.30 且能回填 oracle 才改判 B"。**实测不响且方向相反**：现役代 **3.422**／v4 三跑 **2.781 / 2.750 / 2.953**（取 v4 最高一跑仍低 **0.469**；v4 自身极差 0.203，落差是它的 2.3 倍）。证据 `docs/evidence/20261006-d13-trigger/`。⇒ **P10 不切换**：门①–⑩ 继续按现役代验收，v4 只作影子对照；"重开条件"已预注册（三跑中位 ≥ 现役＋0.30 且 oracle 先回填） | 2026-10-06 | 本批 |
| **P11** | 长跑与收尾 | **待（依赖 P10）／⑤ 门①–⑩ 现状已实测记账** | ⑤ 现状（canonical 命令逐字：`python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab fixtures/knowledge_holdout.vocab.json --cards fixtures/knowledge_holdout.cards.json --assertable fixtures/knowledge_holdout.assertable.json --exclude-cards knowledge/card_scope.json --json`；录档 `work/_gates_canonical.json`）：**10 绿 1 红**——①总量 2847≥1200、②格式 2847/2847、③种子覆盖、④边类（`--assertable` 补齐后 `short_pairs={}`）、⑤禁忌、⑤b 成员、⑥来源覆盖（`--exclude-cards` 补齐后 `missing 0／ghost 0／share 0.961≥0.95`）、⑧换族、⑨可达、⑩可解析；唯一红的是 **⑦人审 `human_reviewed=0`**（需 212、线 120，门只认 `human`）——**红线不许伪造**，单列 **D12**（见上一步的更正说明：上一版把 ④⑥ 记成红是**漏传了两个已裁决的输入**） | 2026-10-05 | 本批 |

## 2026-10-05 晚：P6③／P7／P8 的补账（P14-150…154）

这一段是**在原有表之后追加**的，不覆盖上面的历史行。触发：对齐跑（`work/ab_v4_aligned/`）
三臂塌到 ~0，会诊（`docs/evidence/20261005-p9-consult/`）与主线各自独立定位到两个缺陷。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **P6③** | 冻结评测集（`freeze_eval`）＋ 把 long21 查询冻成 v4 的共享输入 | 绿 | `work/eval_sets/heldout_v4_long21.jsonl`＋`heldout.manifest.json`（seed 记录在 manifest） | 2026-10-05 | `a8ff545` |
| **P8** | 插件侧适配器**注册进路由表**（环境变量门控、默认关） | 绿 | `block_director/knowledge/cases.py` 的注册行；不设 `BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG` 时行为与 P8 前一致 | 2026-10-05 | `440ca38` |
| **P7⑤/⑥** | 缺陷 **B**：`LightRAGIndex` 每请求 `asyncio.run()` × 复用 `_rag` ⇒ 5771 行 `bound to a different event loop` | 绿（修复） | `tools/lightrag_service/build_index.py` 改自持常驻事件循环 ＋ `run_coroutine_threadsafe` ＋ 超时；`serve.py` 传 `--query-timeout` 并在退出时 `close()`；守门 `tests/test_lightrag_build_index.py`、`tests/test_lightrag_service_http.py` | 2026-10-05 | `0d40976` |
| **P7④** | 顺带修：检索端按**索引指纹第三格**装嵌入器（`cloud:embedding-3:2048` vs `local:bge-small-zh-v1.5:512`），换嵌入器必须 fail closed | 绿 | `embedding_route_of` / `load_embedding_for`；维度不符即抛 | 2026-10-05 | `0d40976` |
| **P7④** | 顺带修：LightRAG 的**文档面**并入中文线索（与 hybrid/lexical 同一把尺子），并把 `clues_digest` 纳入指纹 | 绿 | `case_documents(cases, clues)`；`build_args.clues_digest` | 2026-10-05 | `0d40976` |
| **P6②** | 缺陷 **A**：v4 案例层**缺中文线索**（`search_zh_missing`）⇒ 中文查询对英文 excerpt 近 0 命中 | 绿（补生成） | `work/knowledge_v4_cases/cases/search_zh.part-000.jsonl`：783 条处理完、**542 条出线索／241 条按规则空串**；其中 **488 条按 `--seed` 同代沿用**（`(摘录, 出处标题)` 逐字节相同 ∧ `prompt_sha256` 相同）、**54 条现生成**；`cases_sha256=d916cd78…`、`prompt_sha256=36069623ca…`、glm-5.3；`cases.manifest.json` 记 `clue_attached`（体积门 pass） | 2026-10-05 | `b9a6007` |
| **P6②** | 缺陷 A 从后门回炉：lightrag 失败回退的 BM25 丢了 `search_zh` | 绿 | `block_director/knowledge/cases.py` 回退分支改用 `self._text(case, self.search_zh.get(...))`；守门在 `tests/test_*` | 2026-10-05 | `ba34e06` |
| **P6②** | 影子案例层补上「线索重签 ＋ 记账」（`--attach-clues`） | 绿 | `tools/kb_fetch/build_cases_v4.py::attach_clues_to_layer`；`tests/test_build_cases_v4.py` | 2026-10-05 | `d1d05d3` |
| **P6②** | 两处静默降级变成产物里读得到的字段（`cases_clue_state`/`cases_clues`、每行 `clue_state`/`clues`） | 绿（含第三次显式重新冻结） | `tests/plan_v4_instruments.sha256.json` 的 `_reason` 记明「只加诊断字段、判据零改动」；守门 `tests/test_plan_v4_instruments_frozen.py` 绿 | 2026-10-05 | `ba34e06` |
| **P9** | 三臂 A/B（两臂部分，V1 之前） | **被 ⑤ 取代** | `docs/evidence/20261005-p9-clued/` 与 `work/e1_v4pop_ab.partial2.json` 是**轮记录落地之前**的两臂读数（hybrid 0.1875/0.1927、lexical 0.2083/0.1927，Δ 0.0104 ＜ 带 0.0156 ⇒ inconclusive）——结论与 ⑤ 一致，但**不满足检查器的输入契约**（无 `round.*.json`），留作历史对照 | 2026-10-05 | — |

**仍未完成的**：① lightrag 臂的索引重建（含线索的文档面）跑完后才有三臂同代读数，
在那之前 **D8 不可裁**；② 本轮两臂 `judge_coverage.complete=false`
（180/192、174/192），按 V1 还不算**有效轮**；③ 会诊另提的「把
`queries_with_no_rows`/`clue_state` 升格成机器门」是**新的判据**，本批不动，见
`ADJUDICATIONS_v4.md` 的 D11。

**本批的全量测试**（在 `6a438b4` 上重跑）：`python -m pytest -o addopts="" -q` →
**2261 passed / 1 skipped**（唯一那条 skip 是 `tests/test_build_ledger.py:68` 的条件守卫
「这份索引只由单一 prompt 版本产出，无需 refresh 记录」——**不是被绕过的判据**）。
此前状态块里「2085 passed / 2 skipped」是冻结提交 `53d3e3f` 上的数；
另一条 `/work/` 依赖的 skip（`tests/test_holdout_inputs.py:55`）现在不再触发。
顺带记录：`tests/plan_v4_instruments.sha256.json` 已在 `ba34e06` 里做过**第三次显式重新冻结**
（理由：只往每条判分记录加 `clue_state`/`clues` 两个**诊断字段**，判据零改动），
`tests/test_plan_v4_instruments_frozen.py` 绿。

## 路径口径的落地偏差（如实记）

计划正文写的测试路径是 `tests/plan_v4/…`、`tests/kb_fetch/…`。本仓的既有约定是
**平铺**（`tests/` 下 206 个 `test_*.py`，`pyproject.toml` 里 `testpaths = ["tests"]`）。
本批按既有约定落地为 `tests/test_plan_v4_freeze.py`、`tests/test_plan_v4_instruments_frozen.py`、
`tests/plan_v4_instruments.sha256.json`。子目录本可被收集，但混用两套约定会让
"某个守门在哪"变成要靠找的事——**以既有约定为准**，这条偏差记在这里。

## 当前阻塞与下一步

1. **P1② / P2② 已转绿**（本批；证据见 P1／P2 行）——**P0–P2 三个阶段不再有红项**。
2. 数值留白 N1–N5 仍挂着（见 `PLAN_HYPERGRAPH_v4_ANNEX.md` §3），**不影响开工**。
3. **P10 的落地形状有一处必须先解决的偏差**：计划 §3.1 要求影子产物落在**仓库根**的
   `knowledge_v4/`（`git mv` 一次性切成 `knowledge/`，可 `git revert`），而 v4 的产物实际
   落在 **`.gitignore` 掉的 `work/`** 下（`work/knowledge_v4` 3.37 MB ＋
   `work/knowledge_v4_cases` 8.03 MB；`.gitignore:58` `/work/`）⇒ P10 的三条动作
   （`git mv knowledge_v4/...`、`git ls-files knowledge_v4`、`Move-Item .../lightrag ...`）
   **现在跑不了**。处置建议（待做）：先把产物落到**受版本控制**的 `knowledge_v4/`，再按 P10 走；
   LightRAG 索引（本地那代 90 MB／云端那代 263 MB）是否入库要**单列裁决**
   （现役 `knowledge/` 里也没有索引本体，只有它的指纹）。
4. **P10 门的机械口径**：`git grep -n "knowledge_v4" -- tools block_director tests` 现共 9 命中，
   **全在 `tests/`**（`tmp_path / "knowledge_v4"` 这类**测试夹具注入**——§3.3 原文允许
   "或测试夹具注入"）；`tools/`＋`block_director/` **已清零**。⇒ 那条门按**字面 grep＝0**
   与约束原文自相矛盾，落地口径建议改成 `-- tools block_director`（生产代码）＝0。
5. **门①–⑩ 现状：10 绿 1 红**（**更正上一版"8 绿 3 红"**——那是我漏传了两个**已裁决**的输入，
   不是真红）。canonical 命令逐字：

   ```powershell
   python tools/check_holdout.py fixtures/knowledge_holdout.jsonl `
       --vocab fixtures/knowledge_holdout.vocab.json `
       --cards fixtures/knowledge_holdout.cards.json `
       --assertable fixtures/knowledge_holdout.assertable.json `
       --exclude-cards knowledge/card_scope.json --json
   ```

   * 漏传 `--assertable` ⇒ 门④按**旧判据**（每类硬要 30 对）报红；补上后按 2026-10-01
     用户裁定的 `required = min(30, 该类真能断言的对数)`：IMPACT 24／SOUND 11／MUSIC 21
     **全部交满** ⇒ pass（`short_pairs={}`、`thin_cards={}`）。
   * 漏传 `--exclude-cards` ⇒ 门⑥把 91 张"**索引对该卡零条边**"的卡算进分母，报 20 张缺条目；
     补上后 `missing 0／ghost 0／share 0.9613≥0.95` ⇒ pass——而
     `card_scope.json` 的 `edge_backed_without_entry: 0` 说明**每一张有边的卡都有条目**。
   * 唯一还红的是 **门⑦ 人审**：`needs_human 212／human_reviewed 0／线 120`，门的
     `accepted_reviewers` 只有 `["human"]`——**这条是红线，不许伪造**，单列 **D12** 等你裁决。
6. **P11 的其余四件**（①长跑证据链、②RK-13、③既有探针清单、④终态文档）都排在 **P10 之后**。
7. **更正（本批实测）：门①–⑩ 在 canonical 入口下 11/11 全 pass，且长跑证据链已跑绿。**
   ① `tools/run_tests.ps1` 在 **Blender 5.2.0 LTS**（`D:\Blender 5.2\blender.exe`，经 `BLENDER_EXE`）
   上原样跑完 **32/32 步**：pytest 2286 passed／1 skipped、in-Blender `SMOKE_OK`、
   headless 全链 `state=DONE`（355 步／146 LLM／19 工具／64 镜）、11 个 Blender 探针全 `OK`、
   **树稳定性通过**（`tree.json` 的 `stable: true`）。录档 `docs/evidence/20261005-213820/`。
   ③ 同一份录档里的 `holdout_gates.json`：**门①–⑩ 全 pass**——链子的 canonical 调用带
   `--assertable`＋`--exclude-cards`＋`--reviewer-classes human,llm-panel`（`run_tests.ps1:430`），
   门⑦ 的 `accepted_reviewers=['human','llm-panel']`。⇒ 前面第 5 条那句「10 绿 1 红」
   是**更严的单类读法**（只认 `human`），canonical 口径下**没有红门**；两种读法都留在
   `ADJUDICATIONS_v4.md` 的 D12（A 维持 canonical／B 收紧回 human／C 两口径并报）。
8. **一条链子自身的口径问题（判据级，须你点头）**：`rks.json` 的 `failed_checks: ['RK-13']`
   （RK-13 ＝ **E1 ≥ 0.70 那条红线**，现读数 0.19–0.21，R3 早已如实挂着：不承诺可达、不降线），
   而链子打印 `RK-13 counts as failed` 之后**仍然** `All checks passed.` 并 `exit 0`。
   也就是说「链子绿」**不包含** RK-13。要么把这一栏写进验收状态，要么让链子非零退出——
   两条都不该靠默认沉默。

## 2026-10-06 凌晨：R3 上限的**可复现性**审计（P14-198）

这一段**追加**在上表之后，不覆盖历史行。触发：第三方给 D13 的触发器要"现役代 top-20 相关均值"
做对照，我在复算 v4 那一侧时发现**同一条命令的两次跑对不上**。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 上限的**重复跑极差**（第三方第 1 步"重复 3 次、极差 ≤0.02"的测量侧） | **红（已量到机制）** | `docs/evidence/20261006-e1-ceiling-noise/`：同一命令两次跑，候选面 64/64 逐字相同，**评分行 385/1280（30.1%）不同**（差值 `±0.5` 为主）⇒ **上限 0.7760 ↔ 0.7188（极差 0.0573）**、≥3 相关查询 **38 ↔ 32**；而 **E1@前 3 行 0.2812 ↔ 0.2708（极差 0.0104，在 0.02 带内）**。⇒ 「0.7760 ≥ 0.70 ⇒ 结构可达」的正确读法是**区间 0.719–0.776 ≥ 0.70**：仍可达，但余量（0.019）压在噪声带里 | 2026-10-06 | 本批 |
| **R3** | 上限计算的**可复算入口** | 绿 | 新增 `tools/knowledge/e1_ceiling_report.py`（判据与 `e1_panel`／`e1_baseline_summary` 同源：阈值 4.0；多文件自动报极差）＋守门 `tests/test_e1_ceiling_report.py`（8 条，含 3.5 不算相关、缺 `score` 回退评委均值、`top_k<1` 抛错、极差）。**在此之前这个上限是手算的**——这正是 0.0573 漂移没被拦住的原因 | 2026-10-06 | 本批 |

**在跑的两件（都新增，不改判据）**：① `--top-k 50` 的扩召回跑
（第三方第 3 步"上限 ≥0.85？"的读数，落 `work/ab_e1_candidates/hybrid.top50.v4.rep1.jsonl`）；
② top-20 第 3 跑（把上面那张表补成"重复 3 次"）。

**未验证**：把评委重复 N 次取均值是否能把上限极差压到 ≤0.02——那会改"上限"的定义，
属**仪器改动**，要单独显式重新冻结并写理由，本批不动。

### P14-199：**跨 `--top-k` 的 E1 不可比**（上限证书的第二处缺口）

复算上限时发现 P（`--top-k 3`，18:11，`reviews.hybrid.unfiltered.rep1.jsonl`）与
Q（`--top-k 20`，00:01，`reviews.hybrid.top20.rep1.jsonl`）**指的是同一条检索**：
192/192 条 `(query, case_id)` 相同、`excerpt`/`zh` 逐字节相同、面板与判分提示词 sha 相同
（`9a27df1c…`）、`cases_fingerprint` 同为 `4b1b44bb…`——**只有 `--top-k` 不同**。

但 P 给 **37/192 = 0.1927**，Q 的前 3 行给 **54/192 = 0.2812**。逐评委看：
`deepseek-chat` 均值 **2.547 → 2.807**、`glm-5.3` **3.050 → 3.165**（**两位同向上升**）。

⇒ **评委的给分随"这次调用里看到几条候选"漂移**（清单 3 条 vs 20 条）。
**结论口径**：跨 `--top-k` 的 E1 **不许直接相减／相除／当上界**。特别是
`0.7760 ≥ 0.70 ⇒ 结构可达` 那句——上限是在 **20 条语境**里判出来的，而产品实际量的是
**3 条语境**的 E1，完美重排器拿到的是**低口径**的分 ⇒ **这句不能用那份证书支撑**。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 上限证书的**尺子一致性** | **红（已定位，改口径不改判据）** | `docs/evidence/20261006-e1-judge-context/`：同检索、同内容、同提示词，仅 `--top-k` 3↔20 ⇒ 0.1927 ↔ 0.2812（净 +33.5 分，两位评委同向）。判据一字未动（阈值 4.0／两位取均值／分母不变）；新增一句**可比性条件**：报 E1 必须连同候选语境 | 2026-10-06 | 本批 |

**控制实验（在跑）**：同语料重跑 `--top-k 3`（`work/ab_e1_candidates/hybrid.top3.v4.ctl.jsonl`）——
回到 ~0.19 则"清单长度"成立；给 ~0.28 则要另找原因。

### P14-200：**第三方 D13 触发器实测不响** ⇒ D13 = A 维持（P10 不切换）

第三方把 `D13 = A` 写成**可证伪的**：只有 **v4 的 top-20 相关均值 ≥ 现役 ＋ 0.30** 且能回填
oracle 才改判 B。现役代那一跑已跑完（`--cases-dir knowledge --top-k 20`）：

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **P10/D13** | 触发器的**现役侧读数** | **绿（触发器不响）** | `docs/evidence/20261006-d13-trigger/`（`reviews.current.top20.rep1.jsonl`，sha256 `08746037…`）：现役代 **均值 3.422**／中位数 3.0／≥3 相关 42／0 相关 1；v4 两跑 **2.781 / 2.750**。触发器要 `v4 ≥ 现役 + 0.30`，实测 **v4 比现役低 0.64～0.67**（方向相反）⇒ **D13 = A 维持**：P10 不切换、门①–⑩ 按现役代验收、v4 只作影子 | 2026-10-06 | 本批 |
| **R3** | 复算入口补一格：**每查询相关行数均值/中位数**（就是触发器的那个量） | 绿 | `tools/knowledge/e1_ceiling_report.py` 新增 `mean_relevant_per_query`／`median_relevant_per_query`（＋跨跑极差），守门补 3 条断言 | 2026-10-06 | 本批 |

**顺带记账**：v4 的**边**是现役的 7.8 倍（5,000 / 638），但**案例层更小**（783 vs 1143），
在这批查询上 top-20 召回**反而更低** ⇒ "边多"没转化成"检索面更好"。
**未验证**：现役侧只跑了 1 次（其重复跑极差未测）；不影响方向，但引用精确差值时该补。

### P14-201：控制实验落地——**跨 `--top-k` 不可比已坐实**；重排**装置**是好的（0/192）

两件在跑的都跑完了。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | P14-199 那条"清单长度"解释的**控制实验** | **绿（机理解释坐实）** | `docs/evidence/20261006-e1-judge-context/` 补入同语料 `--top-k 3` 的新跑（sha256 `ec1d98bd…`）：k=3 两次跑 **0.1927 / 0.1771**（互相复现，Δ0.0156），而 k=20 那次把同一批候选抬到 **0.2812** ⇒ 差别只来自"这次调用塞了几条候选"。**判据未动**；新增的是**一句可比性条件**：跨 k 的 E1 不许直接比较、上限是**乐观口径** | 2026-10-06 | 本批 |
| **R3** | 重排**装置**能否做到第三方第 1 步的"0/192 失败" | **绿（装置没问题，问题在 qwen 侧）** | `docs/evidence/20261006-e1-rerank-harness/`（sha256 `e927c1a0…`）：换可靠模型（`deepseek-chat`，`--workers 3`）后 **192/192 行标签正常、失败 0**。⇒ 前述 qwen 各跑的失败（111/96/48/27 行）是 **qwen 侧**（账号/限流），不是装置 ⇒ **qwen 恢复后第 1 步可以直接跑**。<br>**打折如实记**：该重排器与一位评委**同族**（都是 deepseek-chat）⇒ 它的 E1（0.2604 vs 基准 0.1771/0.1927）**不得当作重排质量的证据**，只用来读失败计数 | 2026-10-06 | 本批 |

### P14-202：**重复 3 次齐了**——第 1 步那条阈值分语境成立（k=3 成立、k=20 不成立）

top-20 第 3 跑已回（`docs/evidence/20261006-e1-ceiling-noise/reviews.hybrid.top20.rep3.jsonl`，
sha256 `37dea0ea…`）。3 跑极差：

| 量 | k=20 语境的 3 跑极差 | k=3 语境（对照组） | 第三方第 1 步阈值 0.02 |
|---|---|---|---|
| 上限 | **0.0573**（0.7188..0.7760） | — | ✗ |
| E1（各自语境的前 3 行） | **0.0312**（0.2708..0.3021） | **0.0156**（0.1927 / 0.1771） | ✓（仅 k=3） |
| ≥3 相关查询数 | **6**（32..38） | — | — |

⇒ **"重复 3 次、极差 ≤0.02"这条在这份装置上分语境成立**：产品实际用的 **k=3 语境成立**，
而**上限所处的 k=20 语境不成立**。这把 P14-198/P14-199 两条合成一句可执行的纪律：
**报 E1 必带语境（几条候选）；上限只能用 k=3 语境的重复跑去裁，或者按区间报。**

**D13 触发器再加固**：v4 侧 3 跑均值 2.781 / 2.750 / 2.953，取**最高**一跑（2.953）
与现役 3.422 比仍低 **0.469** ⇒ 即便按对 v4 最有利的一跑读，触发器也不响；
**该结论不依赖现役侧是否重复跑**。

**仍未完成**：`--top-k 50` 的扩召回跑（第 3 步"上限 ≥0.85？"）仍在后台
（`work/ab_e1_candidates/hybrid.top50.v4.rep1.jsonl`）。

### P14-203：扩召回上限 **0.8542 ≥ 0.85**（第 3 步判据过）；第三方通道**改用 Kimi K3**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 第三方第 3 步：扩召回能不能把上限抬到 ≥0.85 | **绿（判据过）** | `docs/evidence/20261006-top50-recall/`（`reviews.hybrid.top50.rep1.jsonl`，sha256 `abd5e204…`）：`--top-k 50` → 3,200 行／相关 300／**上限 0.8542**／≥3 相关查询 **46**／候选面相关均值 **4.688**。判据是"**或**"关系（≥48 **或** 上限 ≥0.85），**上限这条过了** ⇒ 这条扩召回**不判放弃** | 2026-10-06 | 本批 |
| **R3** | 上限口径的第 3 个点（单调性） | 绿（并进 P14-199 的结论） | E1@前 3 行：**k=3 0.177～0.193 → k=20 0.271～0.302 → k=50 0.3177**——同批查询、同检索、同评委 ⇒ 清单越长给分越高，**单调**。所以 0.8542 是**最乐观**的一格 | 2026-10-06 | 本批 |
| **通道** | 第三方裁定／难题攻坚**改用 Kimi K3**（用户 2026-10-06："qwen 不方便"） | 绿（客户端 + 测试） | `tools/kb_fetch/llm.py::KimiClient`（`family="kimi"`，端点 `api.moonshot.cn/v1`，型号 `kimi-k3`）+ `make_client("kimi"/"moonshot")`；守门 `tests/test_llm_kimi.py`（7 条）。**一条硬约束如实写进类里**：`kimi-k3` 只接受 `temperature=1`（传 0 ⇒ HTTP 400），客户端**显式**盖成 1 并把该决定写进 `decode_tag`——不是"被拒再重试" | 2026-10-06 | 本批 |

**在跑**：R3 第 1 步的可靠性三跑（`--cases-rerank llm --rerank-llm-provider kimi --rerank-llm-model kimi-k3 --rerank-llm-prompt select --rerank-retrieve-k 20 --top-k 3` × 3，
落 `work/ab_e1_rerank/kimi.rerank_select.rep{1,2,3}.jsonl`）。跑完才有"0/192 失败 + 极差 ≤0.02"的判词。

### P14-204：第三方裁定**改为代替用户做人工审核**（Kimi K3）——ADR-0015

用户 2026-10-06 两条指示：「qwen 不方便，改成用 kimi k3 做第三方裁定和难题攻坚」＋
「**这个裁定是指代替我做人工审核判断**」。qwen 通道当时已掉出 good standing
（`docs/evidence/20261006-qwen-account/`）。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **通道** | Kimi K3 客户端 | 绿 | `tools/kb_fetch/llm.py::KimiClient`（`family="kimi"`，端点 `api.moonshot.cn/v1`，型号 `kimi-k3`，`make_client("kimi"/"moonshot")`）；守门 `tests/test_llm_kimi.py`（7 条）。硬约束如实写进类里：`kimi-k3` **只接受 `temperature=1`**（传 0 ⇒ HTTP 400），客户端显式盖成 1 并写进 `decode_tag` | 2026-10-06 | 本批 |
| **门⑦** | 用户的"人工审核"由第三方裁定承担 | 绿（判据未动） | `tools/holdout_review_third_party.py`（复用 `holdout_review_llm.SYSTEM` v2 与 `_judge()`，所以逐字可比；产出 `reviewed_by: "third-party"` ＋ `source{model,prompt_sha256,authorized_by}`）＋守门 `tests/test_holdout_review_third_party.py`（9 条）。`tools/check_holdout.py::review_class()` 认 `third-party`（须带 `source.model` ＋ `source.prompt_sha256`，否则具名拒收）——**第十二次显式重新冻结**；默认口径仍是 `("human",)`，链子要显式点名才计数 | 2026-10-06 | 本批 |
| **文档** | 授权与代价入库 | 绿 | `docs/adr/0015-third-party-adjudication-stands-in-for-human-review.md`（含"它仍然不是人""不得把 third-party ≥120 读成人审通过""共同盲区未验证"三条代价）；`~/.codex/hooks/model-routing.md` 路由表改为**第三方裁定／难题攻坚 → Kimi K3**、想法生成／质量审核仍走 GLM-5.3 | 2026-10-06 | 本批 |

**在跑**：覆盖**全部 212 条 `needs_human`** 的第三方裁定
（`work/_run_third_party_review.ps1` → `work/holdout_third_party.reviewed.jsonl` ＋
`work/holdout_third_party_disagreements.md`）；Kimi 侧的重排三跑；Kimi 的四问重裁
（`work/_adjudicate_kimi.py`）。

### P14-205：把判分语境 C 从 `--top-k` 里拆出来——**"上限"与红线终于能同尺**

触发：`docs/evidence/20261006-e1-judge-context/` 实测（评委给分随候选清单长度上漂、单调）
＋ GLM-5.3 联合会诊（`docs/evidence/20261006-r3-ceiling-scale-consult/`，commit `f0d018f`）指出的
"GLM 那个测量需要一个新判分模式，属仪器改动，要单独冻结"。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 判分语境 C 可独立于 `--top-k` | 绿（实现＋守门） | `e1_panel.py` 新增 `--judge-batch N`：把候选按**连续 N 元组**切开分别判，尾部不满一批的**不入证**（条数记进 `partial_batch_dropped`）；默认 0 ＝ C 跟 `--top-k`（**历次读数逐字同口径**）。每条打分记录加两枚自述字段 `judge_batch` / `partial_batch_dropped`，汇总同加——这就是 GLM 第 5 条要求的"把被固定的那个旋钮写进产物"。守门新增 3 条（切开＋尾部丢弃只算一次、默认单批、**一批挂掉不抹掉别的批次**）。**第十三次显式重新冻结**；判据一字未动（阈值 4.0／两位取均值／分母） | 2026-10-06 | 本批 |

**在跑（决定性测量）**：`--top-k 20 --judge-batch 3` → `work/ab_e1_relabel/hybrid.batch3.top20.jsonl`。
它把 K=20 池子的 ranks 1–18 按**连续三元组**在 **C=3 语境**下重判（每查询 6 组 × 2 评委
＝ 12 次调用，64 查询 ⇒ 768 次），再用 `e1_ceiling_report.py --top-k 3` 读 `ceiling`。
**判据**（沿用会诊的判据）：`ceiling ≥ 0.70` ⇒ 该池可达；`< 0.70` ⇒ 该池不可达；
`|ceiling − 0.70| ≤ 0.016` ⇒ 原样重复一次再判。

### P14-206：第三方（Kimi K3）带理由的四问重裁——R3 改判 **OPEN**

`docs/evidence/20261006-adjudication-kimi/`（`verdict.json`，`reviewed_by: "third-party"`，
`model=kimi-k3`，usage prompt 1598 / completion 14268，`decode_tag` 记明 temperature=1 是上游强制）。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **D13/D12/RK-13/R3** | 四问重裁（带理由 + 可证伪下一步） | 绿（判词入库） | 四项**均不翻案**：**D13 维持 A**（触发线 3.722，v4 最高 2.953，差 −0.769，**方向相反**）；**D12 维持 C**（human 0/212 挂账；回归后抽 ≥30 条人审，不一致 >10% 追溯降级）；**RK-13 维持 exit 1 ＋ 加语境断言**（E1 必须带 `{top-k=3, panel sha, prompt sha, judge model, n≥3 取中位}`，缺一即 fail）；**R3 改判 `0.70 结构可达` ＝ OPEN（未证明）**——旧证 0.7760 口径作废（20 候选语境），0.8542 仅超线 0.0042 ＝ 噪声极差的 1/13 且出自最乐观格，**不予受理** | 2026-10-06 | 本批 |
| **R3** | Kimi 标的"全线最大单点风险：0.70 线锚定语境无记录" | **已结清（仓库事实）** | 产品自己就是 **k=3 语境**：L3 案例层按 `rag.cases_top_k: 3` 返回参考案例（`specs/config.default.yaml:28`；同源 `contracts/config.py:100`、`contracts/operations.py:51`、`knowledge/client.py:104`、`openapi.yaml:297`）。⇒ 红线量的就是"导演拿到的 **3** 条里有几条相关"；**钉到 k=3 不是暗中加线，正是产品语境**。无需动线 | 2026-10-06 | 本批 |
| **R3** | Kimi 重排三跑（第 1 步：0/192 失败 ＋ 极差 ≤0.02） | **半过** | `work/ab_e1_rerank/kimi.rerank_select.rep{1,2,3}.jsonl`：**E1 0.2865 / 0.2917 / 0.2865，极差 0.0052 ≤0.02 ✓**（且高于无重排 k=3 基准 0.1771～0.1927）；**失败行 36/33/18（6–12 条查询降级）⇒ "0/192 失败" ✗**。失败数随并发下降（rep3 在 rep1/rep2 结束后跑）⇒ 高度疑似我方并发所致，正在用**顺序静默探针**（`work/_probe_kimi_rerank_quiet.py`）取证 | 2026-10-06 | 本批 |

**仍在跑**：k=3 语境的完美重排上限（`--top-k 20 --judge-batch 3`，768 次判分）；
覆盖 212 条 `needs_human` 的第三方裁定（已 111/212）；Kimi 重排失败根因的顺序探针。

### P14-208：**决定性读数**——产品尺子上这份池子的上限 ＝ **0.5052 < 0.70**

`--top-k 20 --judge-batch 3`（判分语境钉到产品口径 C=3）跑完。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 在**产品自己的尺子**上重发上限证书 | **红（未达线，且推翻旧证）** | `docs/evidence/20261006-c3-ceiling/`（`reviews.v4.batch3.top20.jsonl`，sha256 `1ea2ad53…`）：1,152 行、相关 107、**上限 0.5052**、≥3 相关查询 **15**、候选面相关/查询 **1.672**。对照同一池子按 C=20 尺子：上限 0.7760、≥3 相关 38、相关/查询 2.781 ⇒ **旧证书 0.7760 是尺子膨胀出来的**，**该池在 C=3 口径下 `min-of-3 = 0.5052 < 0.70` ⇒ 不可达**（距线 0.195 ≫ 重复跑粒度 0.016，不需重复跑） | 2026-10-06 | 本批 |
| **R3** | 这份 C=3 标注的**自洽性** | 绿（复现了产品口径） | 同一批查询、无重排、k=3 的独立两跑 **0.1927 / 0.1771**；本文件**前 3 行**给出 **0.1875** ⇒ 三者同档，标注没有引入新偏差 | 2026-10-06 | 本批 |

**含义（不含"降线"）**：不是重排器不够聪明（重排器再好也只能把 0.5052 拿满），
而是**候选池在这个尺子上不够肥**（平均每查询只有 **1.67** 条候选被判相关）。
按第三方预注册，第 3 步（放池子到 50）**前置未过 ⇒ 本轮不做**；留作日后判据。
**这不是判红线不可达**，而是"**在当前候选池上不可达**"——要动的是池子（语料／案例层）。

**在跑**：**发货那一代**（`--cases-dir knowledge`）在同一 C=3 口径下的同一读数
（`work/ab_e1_relabel/current.batch3.top20.jsonl`）。**它才是产品当前实际服务的池子**；
在它跑完之前，上面那句**不许**读成"产品现在到不了 0.70"。

### P14-209：发货代在产品尺子上也是 **0.6615 < 0.70**（差 0.0385）；第三方裁定 212/212 跑完

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 发货代（产品**当前实际服务**的池子）在同一 C=3 口径下的上限 | **红（差 0.0385）** | `docs/evidence/20261006-c3-ceiling/reviews.current.batch3.top20.jsonl`（sha256 `442b3d58…`）：C=3 口径 **上限 0.6615**／≥3 相关 24／相关每查询 **2.281**／E1@3 0.2135；同池按 C=20 尺子 0.8385／42／3.422。⇒ **发货代比 v4 肥得多**（再次支持 D13=A），**但两代在产品口径下都不到 0.70**；发货代只差 **0.0385**（≈2.5 条查询的粒度） | 2026-10-06 | 本批 |
| **门⑦** | 第三方裁定覆盖**全部 212 条** `needs_human` | 绿（产物；**合并进夹具未做**） | `docs/evidence/20261006-third-party-review/`：212 条 → `keep 194 / flag 16 / drop 2 / retry 0`，**与 llm-panel 分歧 27 条**（`disagreements.md`）。记录一律 `reviewed_by: "third-party"` ＋ `source{model=kimi-k3, prompt_sha256, authorized_by=user-2026-10-06:…}`，**没有一条写 human** | 2026-10-06 | 本批 |

**结论句改写**（这是本批最重要的一句）：**在当前两代候选池上，0.70 都不可达**——
发货代上限 0.6615、v4 上限 0.5052（均为产品口径 C=3）。发货代只差 0.0385，
把发货池的相关密度从 **2.281/查询** 抬到约 **2.5/查询** 就可能过线。
**要动的是池子（语料／案例层），不是重排器**（重排器再好也只能把上限拿满）。

**未完成**：① 发货代那个 0.6615 只跑了一次，且离线的距离与噪声同量级 ⇒ 要下
"抬高池子就能过线"这句话**必须先补一次重复跑**；② 212 条 `third-party` 判词**尚未合并**
进 `fixtures/knowledge_holdout.jsonl`（门⑦ 读的是夹具里的 `review` 字段），
合并（含 2 条 `drop` 的剔除）后才能谈"门⑦ 在 third-party 口径下 pass"。

### P14-210：第三方判词的**合并试算**——门⑦ 过（third-party 210/210），但甩出 1 张孤儿卡

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **门⑦** | 把 212 条第三方判词并进 oracle（离线合并，不联网） | **半过→不换夹具** | 新入口 `holdout_review_third_party.py --merge-from … --merged …`（纯函数 `merge_entries()`，keep/flag 写回 review、drop 剔除、retry 不动；守门 1 条）。合并：2847 → **2845**（剔 `hq_0495`、`hq_1057`）。canonical 门在**合并件**上：**门⑦ pass**（`needs 210`／已裁 **210**，`reviewed_by_class {third-party: 210}`），**但门⑥ 由 pass 变 fail**（`missing_cards ["gen_cine_0247"]`） | 2026-10-06 | 本批 |

**根因**：`hq_1057` 是卡 `gen_cine_0247` 的**唯一**一条期望（`hq_0495` 覆盖的
`gen_story_0289` 另有 1 条，剔掉不伤覆盖）。两条驳回本身都站得住（原文见
`docs/evidence/20261006-third-party-review/README.md`）。

⇒ **不能就这么换夹具**：按本仓纪律，正确顺序是**先给 `gen_cine_0247` 补一条合格期望**
（＝ `holdout_review_llm` 当初"剔一条 ⇒ 支撑掉线 ⇒ 补跑一轮"的同一条路），再整体换。
**`fixtures/knowledge_holdout.jsonl` 一个字没动**；合并件与门读数留在证据目录。

**在跑**：发货代 C=3 上限的**第 2 跑**（`work/ab_e1_relabel/current.batch3.top20.rep2.jsonl`）
——用来判 0.6615 离 0.70 的 0.0385 是"真差一点"还是噪声；以及 Kimi 重排失败根因的
顺序探针（已看到 ~12.5% 失败率，**不是**纯并发所致）。

### P14-212：**战略结论**——发货代 C=3 上限 0.6615 / 0.6719（极差 0.0104）⇒ **换更好的重排器过不了 0.70**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 发货代 C=3 上限的**第 2 跑** | **绿（可复现，且仍在线下）** | `docs/evidence/20261006-c3-ceiling/reviews.current.batch3.top20.rep2.jsonl`（sha256 `d3658f15…`）：相关 153／E1@3 0.1979／≥3 相关 **25**／相关每查询 2.391／**上限 0.6719**。与第 1 跑（0.6615）**极差 0.0104 ≤ 0.02** ⇒ 语境钉住后这个量**稳了**（对照：同一池子在 C=20 语境下极差 0.0573）。两跑均 **< 0.70** | 2026-10-06 | 本批 |
| **RK-13** | 红线能不能靠"把重排器做好"达标 | **红（结构性否）** | 上限是**完美重排器**的分数：发货代在产品口径下 ≈**0.67 < 0.70** 且可复现 ⇒ **重排器再好也只能拿满 0.67**。⇒ 第三方路线第 1、2 步（修重排可靠性、校准重排器）**不可能达标**；它们动的是"能不能拿满"，线要求的是"**池子够不够肥**" | 2026-10-06 | 本批 |

**由此改写的下一步方向**：唯一能过线的是**把候选池变肥**。但"密度 2.3→2.5"是**线性外推**、
不是实测（上限 `mean(min(3,c)/3)` 在 2–3 之间非线性）。**真正的判据是**
**≥3 条相关的查询数要从 24–25 涨到 ≥45**（45/64 ＝ 0.703 ≥ 0.70）。
第 3 步（扩召回）方向对，但**必须在 C=3 口径下重测**——k=50 那次的 0.8542 是 C=50 语境，不算数。

### P14-213：Kimi 重排 **0/192 失败达成**（关键在 completion 预算）；E1 中位 **0.3073**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3-第1步** | 根因：`kimi-k3` 的**空正文陷阱** | 绿（已定位并修） | 顺序探针（**无并发**）64 条：`ok=56 / failures=8`，其中 **7 条**是"正文为空（内容全在 thinking）"——重排写死的 **1024** 预算被思考吃光。修法＝`--rerank-llm-max-tokens`（**默认 1024 不变**，第十四次重新冻结） | 2026-10-06 | `7493f4c` |
| **R3-第1步** | "0/192 失败" ＋ "重复 3 次极差 ≤0.02" | **半过** | `docs/evidence/20261006-kimi-rerank/`（`--rerank-llm-max-tokens 8192`）：三次**全部 0/192 失败** ✓；E1 **0.3385 / 0.3073 / 0.2969**，**中位 0.3073**、极差 **0.0417 ✗** | 2026-10-06 | 本批 |

**极差过不去是上游约束，不是缺陷**：`kimi-k3` **只接受 `temperature=1`** ⇒ 重排器自己就是
随机的（同一查询可能返回不同 3 条），再叠上评委 ±0.5 的抖动 ⇒ 0.04。这正是第三方自己
给的处方："噪声不能调没，只能重复取样压掉，入链必须取**中位**"。

**对照**：无重排 k=3 基准 0.1771～0.1927 ／ Kimi 重排中位 **0.3073**（+0.11～0.13，**杠杆有效**）
／ v4 池 C=3 上限 0.5052 ／ 红线 **0.70** ⇒ 重排拿到该池上限的 **61%**，
而**该池上限本身就低于红线**（与 P14-212 的战略结论一致）。

**在跑**：同一套 Kimi 重排（含 8192 预算）跑在**发货代**池子上
（`work/ab_e1_rerank/kimi.current.rerank.rep{1,2,3}.jsonl`）——发货代 C=3 上限 **0.67**，
那才是产品口径下最有希望的一格。

### P14-215：通道路由改道（用户 2026-10-06）＋ 发货代 Kimi 重排**作废**

用户三条指示：①"**kimi 那部分用不了就用 gpt6A**"；②"**gpt6A 只能用于人工裁决和执行计划书写，
其他的用 glm 和 DeepSeek**"；③"**使用 gpt6A 时思考强度拉到最大**"；并"**这部分写入 hooks 里**（自动触发）"。

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **路由** | GPT-6A 的**用途边界**＋**思考拉满**写进 hooks（自动触发） | 绿 | `~/.codex/hooks/model-routing.md`：路由表加"**人工裁决 → 中转站 GPT-6A**"（Kimi 降为回退）＋§2c 写明"**只许两件事**"；`plan-contract.md` §7 改"由中转站 GPT-6A（思考拉满）起草"。**自动触发**：`inject-context.ps1` 加 `verdict` 触发类（裁决／裁定／人工审核／人审／终审／verdict／adjudicat）→ 注入新模板 `verdict-rule.md`；`plan` 触发类照旧注入 `plan-contract.md`。**hook 自测 121 项全过**（`selftest.ps1`） | 2026-10-06 | 本批 |
| **通道** | 思考强度拉到最大（**可实测**的那条路） | 绿 | `work/_probe_linkai_thinking.py`：同一问题、同一 `max_tokens=2048` —— 裸调用 reasoning **40** → `reasoning_effort=high` **137** → **`=max` 1034**（墙钟 11.1→37.7 s）。**两个坑**：`thinking={"type":"enabled","level":"max"}`（45）与 `extra_body.reasoning_effort`（35）**都被忽略**＝静默降级。`RelayClient` 默认 `reasoning_effort=max`（`LINKAI_REASONING_EFFORT` 可改） | 2026-10-06 | 本批 |
| **门⑦** | 人工裁决的默认通道换成 GPT-6A | 绿（代码）／**待重跑** | `holdout_review_third_party.py` 默认 `--provider relay --model gpt-6-astra`（`--provider kimi` 仍可，历史 212 条判词写着 `kimi-k3`）。**未做**：用 GPT-6A 重跑那 212 条 | 2026-10-06 | 本批 |
| **R3-第1步** | 发货代池子上的重排读数 | **作废（不是读数）** | `work/ab_e1_rerank/kimi.current.rerank.rep{1,2,3}.jsonl`：**失败行 165/159/162（约 85% 降级）** ⇒ 那些"E1 0.2135/0.2188/0.2083"其实是**退回未重排的前 3 条**的基准，**不是重排读数**。**预算不是原因**（失败行与成功行同标 `@8192`，且 v4 池同预算 0 失败）；原因**未定**。⇒ 这条**不许引用**，要重跑 | 2026-10-06 | 本批 |

**结论没变**：P14-212 的战略结论（发货代 C=3 上限 0.6615/0.6719 ⇒ **换更好的重排器过不了 0.70**）
不依赖上面这条作废读数。

### P14-219：发货代重排那 85% 降级的**具名根因**：Kimi 账号余额不足被挂起

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **通道** | Kimi 为什么"用不了" | 绿（具名根因） | `docs/evidence/20261006-kimi-quota/`：顺序静默探针（16 条、无并发）在发货代池上 **`ok=0 / failures=16`，16 条全是同一条 HTTP 429** —— `"Your account org-… <ak-…> is **suspended due to insufficient balance**"`（`exceeded_current_quota_error`）。⇒ P14-215 那条作废读数（165/159/162 行降级）**有了具名根因**；04:00 前后 v4 那三跑是好的，因为当时还有余额 | 2026-10-06 | 本批 |

**处置（与用户指示一致）**：人工裁决 → 中转站 GPT-6A（212 条重跑**在跑**）；
其余（评委／重排器）→ **只许 GLM／DeepSeek** ⇒ 重排通道接下来要用
`--rerank-llm-provider deepseek|glm`，**但这两个族同时是评委**，所以它们的重排读数
带"同族自证"的折扣——这一条必须写进证据。Kimi 客户端与守门保留（余额恢复后可用）。

### P14-220：GPT-6A 人工裁决 212/212（**零剔除**）；夹具**备好但暂不换**；全量红的根因是 C 盘写满

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **门⑦** | 人工裁决改走 GPT-6A（思考拉满） | 绿 | `docs/evidence/20261006-adjudication-gpt6a/`：212 条 → **keep 201 / flag 11 / drop 0 / retry 0**；与 llm-panel 分歧 **33**；通道 `relay`／`gpt-6-astra`／`reasoning_effort=max`，判据 sha 与 llm-panel **逐字同源**（`7d95fbc4…`、`review/v2`） | 2026-10-06 | 本批 |
| **门⑦** | 合并试算（不落） | **备好不换** | 合并件 `work/knowledge_holdout.gpt6a.jsonl`：2847 → 2847、**dropped []**；逐条比对证明**除 `review`／`panel_disagreement` 外零变化**；门①–⑩ 在它上面**全 pass**（门⑥ missing 0、门⑦ third-party 212/212）。**但没换夹具**——见下面那条耦合 | 2026-10-06 | 本批 |
| **链** | oracle 的 pin 耦合 | **红（已具名，代价已量化）** | 每份已入库真实运行把 oracle **整文件 sha256** 钉进 `run_manifest.json.pins.holdout`（`tools/extract_run_evidence.py:343`）；`docs/evidence/` 有 **20 个**这样的目录 ⇒ 换夹具让全部 STALE，**6 条测试必红**（实测）。`repin()` 的安全规则**明确拒绝**把换代洗成没换代（旧 pin 既非归一摘要也非裸字节摘要 ⇒ 跳过并报 STALE）。⇒ 要换就得**重跑 20 份真实运行**（巨量、且会产出新数字） | 2026-10-06 | 本批 |
| **环境** | 全量 pytest 那些"莫名其妙的批量红" | 绿（具名根因） | **C 盘写满**：`OSError: [Errno 28] No space left on device`（pytest 的 tmp_path 在 `%TEMP%`＝C:）。清掉 pip 缓存（`python -m pip cache purge`，释放 ~2.6 GB，C: 0.15 GB → 2.73 GB）后，**同一套代码 2347 passed / 1 skipped 全绿**。⇒ 前面记的"最像机器负载"那两次（101 failed/34 errors、29 failed/62 errors）**应改判为磁盘写满**。**未清理**：`~/.cache/huggingface` 19.2 GB（HF 只有镜像可达，删了会重下，**故意不动**） | 2026-10-06 | 本批 |

### P14-221：**转折点**——候选面 20→50，产品尺子（C=3）上的上限 **0.6615 → 0.8438**，红线**可达**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 把候选面挖深，看产品口径（C=3）的上限能不能过线 | **绿（过线）** | `docs/evidence/20261006-c3-deep-pool/`（`reviews.current.batch3.top50.jsonl`，sha256 `c5c11282…`；`--top-k 50 --judge-batch 3`，3,072 行）：**上限 0.8438**、**≥3 相关查询 46**、相关/查询 **4.359**、E1@前 3 行 0.2188。对照同池 k=20：上限 0.6615/0.6719、≥3 相关 24/25、相关/查询 2.281/2.391 | 2026-10-06 | 本批 |

**判定**：红线 E1 ≥ 0.70 等价于"64 条里 **≥45 条**有 ≥3 条相关"（45/64＝0.703）。
挖到 50 之后是 **46 条**、上限 **0.8438** ⇒ **在产品口径上过线**。
**这不是降线**：红线、阈值 4.0、分母、判分语境（C=3 ＝ 产品自己的 `rag.cases_top_k: 3`）
一个字没动；变的只是**检索取多深**——"取多深再重排到 3"本来就是 retrieve-then-rerank 的标准形状，
**产品对用户仍然只返回 3 条**。

**新的、可执行的缺口**：上限是**完美重排器**的分。k=50 **不重排**只有 0.2188
⇒ 要过线，重排器得把 0.2188 抬到 ≥0.70（＝拿到该池上限的 **83%**），
而已测的最好重排器只拿到 61%（且那还是在更浅的池子上）。
**通道受限**：用户规则（GPT-6A 只做人工裁决与写计划）＋ Kimi 余额挂起 ⇒ 重排只能用
**GLM／DeepSeek**，而这两个族**同时是评委** ⇒ 读数带**同族自证**折扣（必须写进证据）。

**未验证**：① k=50 只跑了 1 次，过线的余量不大（要引用"过线"应补一跑，对照 C=3 两跑极差 0.0104）；
② 挖到 k=100 会不会继续涨，未测；③ 检索深度的**成本**（k=50 的判分调用是 k=20 的 2.67 倍）
要按本仓 `retrieval_calls ≤ (2+N)×lanes` 的预算先算清。

### P14-222：深池 + DeepSeek 重排 → **E1 0.4115/0.4167**（官方口径，0 失败）；跨族评委读 **0.66**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 真重排器在深池上能拿多少 | 绿（读数）／**仍未达线** | `docs/evidence/20261006-deep-rerank/`（sha256 `7d5a6981…` / `64b233d9…`）：`k=50 → 重排到 3`，**官方双评委均值 0.4115 / 0.4167**（极差 0.0052）、**0 降级行**；**只 deepseek 评委 0.43/0.41、只 glm 评委（跨族）0.6557/0.6684** | 2026-10-06 | 本批 |

**三件事同时钉住**：
1. **重排是真杠杆，深池放大了它**：`k=20 不重排` 0.1927 → `k=50 + 重排` **0.41**（＋0.22）。
2. **同族折扣这次是"反的"**：重排器＝`deepseek-chat`（同时是评委之一），而**同族**评委给 0.41、
   **跨族**的 `glm-5.3` 给 **0.66** ⇒ 不能读成"重排器更好"，只能读成"**两位评委对同一批输出分歧很大**"。
   干净读数只能用跨族那位评委（0.66），但那**不是**官方口径。
3. **离线的差距**：官方口径 **0.41 vs 0.70（差 0.29）**；跨族口径 **0.66 vs 0.70（差 0.04）**——
   **本轮最接近的一次**。

**缺口已经换了**：池子不再是不够肥（上限 0.8438），**现在缺的是重排器质量**
（本目录只拿到上限的 49%；早先 Kimi 在更浅的池子上拿到 61%）。这是继"池子不够肥"之后
**下一个、也是最后一个**可执行的缺口。

**未验证**：① 重排提示词只试了 `select`（`order`/`score` 在深池上未测）；
② 重排器与评委同族在官方口径下无法去掉（用户规则限定通道），跨族读数只能当**附加证据**；
③ 两跑各 1 次（极差 0.0052 很稳但无第 3 跑）；④ `k=100` 未测。

### P14-223：重排形状 × 给不给中文线索 —— **`select` ＋线索最好（0.4479 / 0.4375）**；
### 并实测出**两位评委在同一批行上差 0.27**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | `order`／`score`／`select` × 线索 | 绿（读数）／**仍未达线** | `docs/evidence/20261006-rerank-shapes/`（4 份原件，标签自述 `deepseek-chat/<shape>@8192[+clue]`）：`order` **0.2760** ｜ `select` 0.4115/0.4167 ｜ `score` 0.4293 ｜ **`select`＋中文线索 0.4479/0.4375**。⇒ **全序排序最差**；**把中文线索交给重排器确实有用**（＋0.03） | 2026-10-06 | 本批 |
| **R3** | 两位评委的**分辨率** | **红（新发现，挡住红线）** | 同一批 192 行：`deepseek` 评委 0.44～0.46、`glm` 评委 **0.67～0.7120**，**差 0.27**。官方口径（两者均值）⇒ **`select+clue` 官方 0.4375（差 0.26），跨族评委 0.7120（已过线）**。⇒ 现在"过没过线"**取决于用哪把尺** ⇒ 这不是"重排器还差一点"，是**判分器本身的分辨率问题**。**未做**：把两位评委的**判据（不是阈值）**对齐一次（让它们各自先写"为什么相关"再打分），看那 0.27 是真分歧还是打分习惯 | 2026-10-06 | 本批 |

### P14-226：**LLM 重排在 ~0.44 处见顶**（六种配置全试过）——下一处该换"另一类重排器"

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 把重排这条路能调的都调一遍 | **绿（结论明确）** | `docs/evidence/20261006-rerank-shapes/`（10 份原件）：深池（k=50→3）上 **六种配置**的官方口径——`order` 0.2760 ／ `select` 0.4115/0.4167 ／ `score` 0.4293 ／ **`select+clue` 0.4479/0.4375（最好）** ／ `select+clue+title` 0.4346/0.4635 ／ `select+clue+2stage10/3` 0.4271/0.4531。⇒ **除 `order` 明显更差，其余五种全落在 0.41～0.46**；换形状、补信息（线索/标题）、拆小批次**都推不动** | 2026-10-06 | 本批 |

**量化**：同一批查询的重排**上限 0.8438** ⇒ 这个重排器只拿到上限的 **52～55%**，
而"过 0.70"需要拿到 **83%**。

⇒ **本轮关于重排器的最后结论**：`deepseek-chat` 这条"让通用大模型读清单挑 3 条"的路
**已经见顶**。要过红线得换**另一类重排器**，而不是继续调这条路：
最顺的一条是**在中文线索面上做嵌入重排**（本地 `bge-small-zh-v1.5` 已实测在 CUDA 上可编码、
智谱 `embedding-3` 已有资源包；**D3 实测：同一路由换云端嵌入器 E1 提高约 5.6 倍**），
它确定性、便宜、**且与两位评委不同族**——正好把"同族自证"那条折扣也去掉。**未做**。

### P14-230：GPT-6A 会诊定出下一步（**训练一个交叉编码重排器**）；并实测出 GPT-6A 的**包线**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | GPT-6A 单侧会诊（难题攻关） | 绿（判词入库） | `docs/evidence/20261006-gpt6a-consult/`：通道 `gpt-6-astra`／`reasoning_effort=max`／prompt 338 tok／completion 4,943 tok／墙钟 233 s。方案：**固定 50 候选，用原两位评委的标签（均分≥4＝正例）微调预训练交叉编码重排器**，输入＝"分镜需求＋案例正文"，把"排前却不相关"当难负例，按分镜隔离训练/测试；**可证伪判据**＝另取 100 个未见分镜盲评，原口径 <0.70 即失败，并报按分镜重采样的 95% CI | 2026-10-06 | 本批 |
| **通道** | GPT-6A 的**可用包线** | 绿（具名） | `docs/evidence/20261006-gpt6a-envelope/`：`linkai.pics` 在 Cloudflare 后，**单次生成超过约 100 s ⇒ HTTP 524**（大包时三次全 524；改成"一个问题、300 字以内"后成功）。⇒ **包要小、答案要短**；**不许**为绕 524 调低 `reasoning_effort` | 2026-10-06 | 本批 |

**主线对判词的核对**（哪些站得住）：① 本仓**已有这条缝**——`--cases-rerank cross-encoder`
（`load_cross_encoder()`，喂的正是 `(query, excerpt)`），现成 `bge-reranker-v2-m3` 未微调时是
**0.1302**；② **训练集在手上**——C=3 口径 k=50 的 **3,072 行**评委分（`docs/evidence/20261006-c3-deep-pool/`）；
③ 本机 `torch 2.5.1+cu121`＋CUDA＋16 GB，训 cross-encoder 量级可行（**未实测耗时**）。
**要补的两件**：① "另取 100 个未见分镜"——现冻结查询集只有 **64** 条，得新切/多造；
② "按分镜重采样的 95% CI"——现仓只有"同臂极差"口径，CI 可算但要新写。
**风险**：训练标签来自那两位**同批差 0.27** 的评委（P2）⇒ **训之前该先把它们的判据对齐一次**，
否则会把分歧学进去；3,072 行对 cross-encoder 偏小，需按分镜隔离＋早停。

### P14-236：**192 条未见查询上的三方对照**——LLM 重排仍最好；微调重排器**跨项目泛化不住**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 把会诊要的"未见查询"凑齐（原有 64 条不够） | 绿 | `tools/knowledge/collect_shot_prompts.py`：把 `docs/evidence/` 下 **28 份** `project.bdproj` 的逐镜散文（`scenes[].shots[].prompt`）汇成池，**跨项目去重**（`chunked_long*` 是同脚本多次分块跑）→ 全池 **1,315 条**；**排除 `20261006-long21`**（微调训练集那一份）后 **1,251 条"未见"**；`freeze_eval` 冻出 **192 条**（seed 20261006，落 `work/eval_sets/unseen192/`）。**顺手修一个真 bug**：5 条 prompt 带换行 ⇒ 池文件 1,251 条会写成 **1,275 行**（查询池是**一行一条**）⇒ 收集时把内部空白折叠成一个空格；守门 4 条 | 2026-10-06 | 本批 |
| **R3** | 三方对照（同 192 条，官方口径） | 绿（读数）／**都远未达线** | `docs/evidence/20261006-unseen192/`（三份原件）：**不重排 0.2031**（117/576）／**微调 CE 0.2483**（143/576）／**LLM 重排 0.3958**（228/576）。**排序与 64 条那次一致** ⇒ 稳，不是噪声 | 2026-10-06 | 本批 |

**两条结论**：① **微调重排器过拟合了训练域**——同项目留出 16 条是 0.3542、代理口径 0.5625，
**换到别的项目掉到 0.2483**（只比不重排高一点）⇒ 要救它得先解决**训练数据的域覆盖**
（拿 1,251 条池子上的标签去训，而不是只用 long21 那一份）；② **LLM 重排仍是目前最好的，
且跨项目稳**（64 条上 0.44、192 条上 0.40）。

### P14-237：**终审**——"完美重排上限 0.8438"**拿不到**；重新盲评那 3 条只有 **0.4583**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 上限那一格**在真实判分语境下**是多少 | **绿（终审结论）** | `docs/evidence/20261006-fresh-oracle/`（`work/_probe_oracle_triple.py`，64 条查询）：把每条查询的 **oracle 三元组**（原标签分最高的 3 条）**重新盲评** ⇒ **0.4583**（88/192）；而同一条公式给的"完美重排上限"是 **0.8438**（162/192）。**差 0.3855** | 2026-10-06 | 本批 |

**机制**：0.8438 是**数出来的**（数池子里"在各自原三元组里被标过相关"的行数），
而 E1 判的是**重排器自己凑出来的那个三元组**；本仓已实测评委给分**随同批候选变化**
（P14-199／`docs/evidence/20261006-e1-judge-context/`）⇒ **上限不是可达目标，只是一个计数**。

**三句改写（这轮最重要的口径更正）**：
1. **当前协议下 E1 的可达上界约 0.46**（这 64 条），**不是 0.84**；
2. 实测最好的重排器（LLM `select`＋线索 **0.44**）已拿到可达上界的 **约 96%** ⇒
   **缺口不在重排器上**（之前说"只拿到上限 52%"是**拿错了分母**）；
3. **0.70 靠换/训重排器到不了**。只有两条路：① **换更好的候选**（更深的池子／更好的案例层
   ——唯一未被证伪的工程方向，但要先给更深池子打标签才能量）；② **动测量协议**（红线，须用户拍板）。

**未验证**：只做了这 64 条、只判 192 行、没重复跑；更深池子的"最好 3 条"会不会更好**没测**。

### P14-240：**终局**——池子 50→120，可达 E1 只从 0.4583 涨到 **0.4740**；"换更好的候选"也证伪

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 更深池子能不能抬高**可达**上界 | **绿（终局结论：不能）** | `docs/evidence/20261006-deep-pool-refuted/`：`--top-k 120 --judge-batch 3`（7,679 行判分，`reviews.current.batch3.top120.jsonl` sha256 `4b30f55f…`）+ 对它的 oracle 三元组同一次**重新盲评** ⇒ **可达 E1 0.4740**；对照 k=50 的 **0.4583**（**只 +0.0157**）。而"数出来的上限"从 0.8438 涨到 **0.9688**（更深的池子确实还有相关案例：rank 49–128 相关率仍有 0.025～0.048，没归零） | 2026-10-06 | 本批 |

**四句终局**：① 当前测量协议下 **E1 的可达上界约 0.46～0.47**（**不随池子深度变**）；
② 实测最好的重排器（LLM `select`＋线索 **0.44**）已拿到可达上界的 **约 93%** —— **它没得可挖了**；
③ **换/训重排器到不了 0.70，挖深候选也到不了 0.70**；
④ ⇒ 要过 0.70 **只能动测量协议本身**（判分语境／口径／"3 条"的定义）——
那是**红线**，**必须用户拍板**。

**未验证**：只 64 条查询、只判 192 行、没重复跑；只测了 k=50 与 k=120 **两个点**
（"可达值与深度无关"是两点证据，不是曲线）。

### P14-243：**P10／P11 收口**——计划里的最后两格不再是"待"

（本段追加在上表之后。上面表里 **P10** 那行仍写"待"、**P11** 那行写"待（依赖 P10）"——
它们**已被本轮收口**，改在下面记账，不改动原行。）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **P10** | 指针切换与归档 | **已裁决：不切换（D13 = A）** | 第三方（Kimi K3）给的可证伪触发器："v4 的 top-20 相关均值 ≥ 现役 ＋ 0.30 且能回填 oracle 才改判 B"。**实测不响且方向相反**：现役 **3.422**／v4 三跑 **2.781 / 2.750 / 2.953**（取 v4 最高一跑仍低 **0.469**；v4 自身极差 0.203＝落差的 1/2.3）。证据 `docs/evidence/20261006-d13-trigger/`。⇒ 门①–⑩ 继续按现役代验收、v4 只作影子；重开条件已预注册 | 2026-10-06 | 本批 |
| **P11** | 长跑与收尾（四件） | **绿（收口）** | ① **长跑证据链**：冻结树上 32/32 步全跑完（`SMOKE_OK`、headless `state=DONE` 355 步／146 LLM／19 工具／64 镜／4584 帧、**门①–⑩ 全 pass**、口径 `llm-panel 210 + third-party 0 + human-only 0`），链子按裁决**非零退出**并打印 `FAILED: RK-13` ＋ `This run is NOT green.` ⇒ `docs/evidence/20261006-133244/`；② **RK-13**：终审＝"**当前测量协议下不可达**"，要改只能改协议（须用户拍板）；③ **既有探针清单**＝步骤 5–32 的 28 个 Blender 探针 ＋ pytest 全量；④ **终态文档**＝`docs/knowledge/ACCEPTANCE_STATUS.md` 追加"终态"一节 | 2026-10-06 | 本批 |

### P14-248：**GPT-6A 全项目会诊**——旧包喂的是**过期前提**；换代后重发（通道与长跑都取了证）

见 `docs/evidence/20261006-gpt6a-consult-liveness/`。要点：

1. **通道是通的**：探针 `PROBE_OK`（70 prompt token → 2.8 s）；`levels_ignored=["max"]` 说明
   relay 通道不认 `levels`，档位只由 `LINKAI_REASONING_EFFORT` 决定（默认 `max`，与既有口径一致）。
2. **长跑没死也没自旋**：pid 53944 在 2.5 min 采样窗内 `dRead=dWrite=dCpu=0`，连接 `Established`
   → Cloudflare 边缘；生涯 CPU 仅约 0.08 s ⇒ 阻塞在网络读。
3. **同一批抓到并修掉的包缺陷**：旧 `work/_q_gpt6a_full_head.md` 仍写"逐条独立盲评**正在跑**"，
   而该实验 15:43 已出**负结果**（E1 **0.1458**，`docs/evidence/20261006-oracle-alone/`）
   ⇒ 旧包会诱导 GPT-6A 重提**已被推翻**的选项 **B**（它 13:55 那份判词给的正是 B）。
   换代后把"B 已排除／因果改为案例 × 呈现方式／候选只剩 A 与 C"写进包，并**逐字留档**
   （`packs/`，含 sha256 前 12 位）。
4. **已发 5 件**：1 件旧包（只作交叉对照，5,400 s 超时）＋ 4 件换代/拆小包（1.3–5.3 KB，21,600 s），
   并设**安静型心跳巡查**（每 10 min，只在答案落地／进程异常／全空结束时才出声）。

**未验证**：0 条答案落地；长跑那条流**没有 keepalive**，"本机 0 字节"**不能**区分
"远端还在生成"与"远端已经哑了"——本段只主张"任务没死 ＋ 包是对的"，不主张它一定在思考。

### P14-249：**E1 的测量失真**——只有一位评委给分的行被当成了"相关"（两处，都只收紧）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | E1 的分子是否真的按"**两位**评委取均值"算 | **缺陷（已修）** | `docs/evidence/20261006-e1-judge-coverage/`（含探针与逐字输出）：某位评委那一批调用失败时，行里留 `scores: [x, None]`（**失败不许记成低分**，这条本身是对的），但 `e1_panel._score_one` 接着**只按答上来的那一位**取均值 ⇒ 这一行照样被判"相关"、照样进分子；`quality.e1_relevance` 读的正是这个 `score` | 2026-10-06 | 本批 |

**偏差方向四份一致——全是"现在报的数偏高"**：链上**真正消费**的那份
`docs/evidence/20261006-e1-craft/reviews.jsonl`（sha `82d62ebcc485`）**0.1823 → 0.1354**
（192 行里 **17 行**只有一位评委，8.9%）；`c3-ceiling/top20` 0.1267→0.1163、
`c3-deep-pool/top50` 0.0908→0.0837、`c3-deep-pool/top120`（sha `4b30f55f`）0.0611→0.0548。

**修法与方向**：行上新增 `judge_incomplete`、汇总新增 `judge_incomplete_rows`，
这类行**留在分母、绝不算相关**。分母不动是关键——E1 的分母是"交给导演的那 3 条"／面板条目数，
**由检索决定**；探针里那种"把这类行从分母剔掉"的口径会给出 0.1486（**更高**），
**明确不采用**：分母变小会让比率变好看，正是 §4.1b 硬规则 1 要防的事。

**守门**：`tests/test_knowledge_quality.py::test_e1_never_counts_a_row_that_only_one_judge_scored`
（先红：`assert 2 == 1`）＋ `tests/test_e1_panel.py::test_a_single_judge_row_stays_in_the_denominator_but_is_never_relevant`；
既有那条"失败侧不是 1 分"**保留并加强**（新增"这一行必须被标记"），没有放宽。
全量 `python -m pytest -o addopts="" -q` ⇒ **2368 passed / 1 skipped**（原 2365，＋3）。

**未验证**：**没有重跑面板**（改的是"怎么汇总已有的分"，四位评委的原始分数一条没动）；
链上那份仍因缺 `judge_batch` 记 `not_measured`（**另一件事**）；历史台账里引用的
`e1_panel.summarise` 读数（0.4583／0.4740 这类）含同类偏差，**未逐条重算**。

### P14-250：**第十九次显式重新冻结**——`e1_panel.py` 哈希换代 ＋ `quality.py` 新增进清单

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R9** | 判据执行环境逐字节不动 | **绿（重新冻结）** | `tests/plan_v4_instruments.sha256.json`：`e1_panel.py` → `e0844bfa3795…`；**新增** `tools/knowledge/quality.py` → `0db3aaf86cbb…`；`_frozen_at` → **第十九次冻结**，理由写进新增的 `_reason_19`（历史 `_reason` 逐字保留，不改）。守门**先红后绿**：改完代码时 `assert 'e0844bfa3795…' == '85a88eb9ec1b…'`，重新冻结后 9 passed | 2026-10-06 | 本批 |

**为什么要新增 `quality.py`（本轮第二个发现）**：链上**真正报出的那个 E1** 是
`tools/knowledge/quality.py` 算的（`tools/run_tests.ps1:677` 用 `--e1-reviews` 调它写
`knowledge_quality.json`），而它**不在**冻结清单里 ⇒ **E1 这个数的产出方可以被静默改掉**，
"改了要红"的守门覆盖不到。这与本仓已记的两个前例**同形**：S0 的 `QUALIFIER_KINDS` 洞、
S1a 的 `tools/sidecar_server.py` 手抄字面量洞；也与清单里**已经冻结**的
`e1_baseline_summary.py`（同样只是个汇总器）同形。

**一个字没动**：阈值 4.0、两位评委、分母口径、红线 0.70。

### P14-251：GPT-6A 第二轮会诊——**小包也返回空正文**（根因＝思考吃光预算）＋ 第一份答案到手

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 会诊通道到底能不能拿到正文 | **绿（根因已定 ＋ 已修）** | `docs/evidence/20261006-gpt6a-empty-body/`：三个 1.3–1.8 KB 的视角包用 `--max-tokens 4096` **三次全空**（`a_metric` 119.6/244.8/370.1 s、`b_closeout` 122.5/239.7/360.6、`c_arch` 120.0/243.6/366.3），错误文案出自 `tools/kb_fetch/llm.py:158`。根因：relay 通道上 `num_ctx` **就是** `max_tokens`（`tools/relay_consult.py` 传参），而 `reasoning_effort=max` 时 **4096 连思考本身都不够**——本仓既有读数（`tools/kb_fetch/llm.py:48-50`）写着"32768 ⇒ 思考 6.5k–6.9k token ＋ 正文 12–14k 字符；**16384 会截断**"。处置＝**加预算、不降思考**（降思考是静默降级，明令禁止）：全部按 `--max-tokens 32768` 重发 | 2026-10-06 | 本批 |
| **R3** | 拿到第一份正文 | **绿（1/4）** | `docs/evidence/20261006-gpt6a-round2/answers/c_arch.md`（sha256 前 12 `19aa1828d37a`）：18:35 发出、**18:38:13 拿到**（约 3 分钟，806 B）⇒ 32768 确实治好了空正文 | 2026-10-06 | 本批 |

**它给的三条 ＋ 主线的逐条核对**（判词**不是**事实）：① "分层合理，但超图未必必要"，
给了一个**可证伪的消融**——固定生成器与 token 预算、**分别去掉一层**（超图换规则表），
比较**硬违例率与返工次数**，无收益就删复杂度；**这两个量本仓还没有仪表**，要造表才能测。
② "优先混合检索组件（它点名 Haystack）、**只替 L3**"，并点明**图 RAG 不是约束引擎、
超边不会自动执行**（与本仓事实一致：超边是数据，执行在 `rule_checker`/`driver` 的修复环）；
"索引缺失的降级结果必须单报、不能据此证明 LightRAG 增益"（本仓**已在做**：
`cases_degraded` ＋ 指纹为空 ＋ `cases_backend_effective`/`cases_degrade_reason`）。
③ 最疑似遗漏＝**"知识 → Blender 的执行闭环"**：硬规则要有**适用域／对象-时间绑定／可执行判定**，
生成后**校验**、失败**修复或拒绝**，并加一条测试 **"E1＝3 却违反明示站位约束 ⇒ 判失败"**。
它的一句话：**"检索相关不等于镜头可用"**。⇒ 本仓**没有**这条测试、也**没有**它的两个仪表，
属**新的缺口候选**（未做）。

**操作失误（如实记）**：重发时 `Start-Process -RedirectStandardError` **截断**了原来那三个
`.err`，所以"三次全空"的原文只剩当时控制台解出来的版本；替代原件＝**同条件复现**
`probe_budget4096.*`（同包、同 4096 预算）。

**未验证**：另外三件（全面评审／度量可信度／两件收口）**到记账时还没回来**；
"硬规则的适用域／绑定／可执行判定是否条条齐备"**未逐条核**；
GPT-6A 的建议**一条都还不是事实**，落地前必须逐条在仓库里证实或证伪。

### P14-252：GPT-6A 会诊**四件里回来三件**——其中一条**推翻台账的措辞**（"不可达"应降级为"未证不可达"）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 拿到 GPT-6A 的正文 | **绿（3/4）** | `docs/evidence/20261006-gpt6a-round2/answers/`：`c_arch.md`（806 B，18:38:13）、`a_metric.md`（857 B，18:39:54）、**`full_head.md`（2,024 B，18:41:20）**；`b_closeout.md` 仍在跑。空正文的**不失真原件**＝`docs/evidence/20261006-gpt6a-empty-body/probe_budget4096b.err`（394 B；产生处 `llm.py:612` 被 `:617` 包成外层串） | 2026-10-06 | 本批 |

**这一轮最该落地的一条（会诊推翻台账措辞，不是推翻判据）**：
台账 P14-240 写的是"**当前测量协议下 E1 的可达上界约 0.46～0.47（不随池子深度变）**"。
GPT-6A（`answers/full_head.md` 第 3 条）指出：那个 0.4583 的算法是"取**标签分最高的 3 条**再重评"
——**它本身就是一种选择方式**，所以它量的是"**已试方法**的成绩"，**不是组合最优上界**；
而"逐行标签最优 ≠ 三元组最优"（同一份会诊的第 3 条自己也承认相关性依赖同伴）。
⇒ 本仓那句"**不可达**"是**推论**、不是**测量**，应降级为
**"已试过的这些方式到不了 0.70；未证不可达"**。**判据/阈值/分母/红线一个字未动**，
动的只是**对已有证据的措辞**。

**可证伪的下一步（它给的、本仓尚未做）**：在 **C=3 尺子上搜三元组**——对每条查询在
k=20 候选里做贪心/局部搜索找最优三元组，看有没有查询能到 3/3。**没做**。

**它的另外两条（也应记账，未落地）**：
* `full_head` 第 1 条：**RK-13 本版选 A**（正式记"验收未通过"并结案、停止追加重排试验），
  C 须用户明示批准并另立协议版本、重建基线；**门⑦ 本版先不切夹具**，真启用时要在**新目录重跑那 20 份**
  并生成新 manifest，**旧 manifest 不改不重签**，不批预算就明确"尚未启用"。
* `a_metric` 给了**结算式**：固定 Q 个实际三元组与顺序、原判据与两评委版本，
  **预登记 R 轮复评**，`Ê1 = (1/R)Σ_r (1/3Q)Σ_q Σ_i 1{(s1+s2)/2 ≥ 4}`，
  **单侧 95% 置信下界 ≥ 0.70 才通过**，且**必须验收方显式批准**、不能"自行改尺"；
  并提醒 **30% 的分数漂移仍须排除**，否则"呈现效应"与"评委噪声"两个解释分不开。

**未验证**：`b_closeout` 还没回来；上面三条**一条都还没在仓库里证实或证伪**；
"在 C=3 尺子上搜三元组"这个决定性实验**未做**。

### P14-253：GPT-6A 那条挑战的**半张答卷**——2,943 个 C=3 三元组里**没有一个 3/3**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | "上限 0.46～0.47"是**组合最优**还是**已试方法的成绩** | **绿（半张答卷，另一半已开跑）** | `docs/evidence/20261006-e1-triple-ceiling/`（探针 `probe_triple_ceiling.py` ＋ 逐字输出 `probe.out.txt`）：`reviews.current.batch3.top120.jsonl` 带 `judge_batch=3`，**每组连续 3 行就是一次 C=3 判分** ⇒ 每条查询已有 **40 个被判过的三元组**（top-20 那份 6 个），于是**不用新判分**就能问"这些三元组里最好的是多少" | 2026-10-06 | 本批 |

**三条读数**（两口径都列；`strict_two_judge` = P14-249 的"两位评委"）：

| 打分文件 | 查询 | 判过的三元组 | 0/1/2/3 分布 | E1（全部） | E1（**交付的那个**） | E1（**每组取最好**） | 3/3 |
|---|---|---|---|---|---|---|---|
| `c3-deep-pool/…top120` | 64 | **2,559** | 2159 / 379 / **21** / **0** | 0.0548 | 0.1719 | **0.4219** | **0** |
| `c3-ceiling/…top20` | 64 | 384 | 258 / 118 / 8 / **0** | 0.1163 | 0.1875 | **0.3490** | **0** |

1. **2,943 个被判过的 C=3 三元组里没有一个到 3/3**；连 2/3 都只有 21 个（0.8%，top120 那份）
   ⇒ 不是"上限高但选不出来"，是"**3/3 这种组合几乎不存在**"。
2. **"每组取最好" = 0.4219，反而低于**"标签 top-3 重新盲评"的 **0.4583**——
   在**真的判过**的 40 个分组里怎么挑，也挑不出比"标签 top-3"更高的。
3. **交付的那个三元组只有 0.1719**，与既有读数一致（e1-judge-context 的 k=3 → 0.177～0.193）。

**边界（这半张答卷证不了什么）**：它只覆盖**连续分组**（1-3、4-6、…）——因为**只有**这些三元组
有标签；**任意组装**的三元组（rank 2＋9＋17）**一个都没判过**。所以它**既不能证实也不能证伪**
GPT-6A 那条挑战，只把它收窄成：**"在候选池的连续分组里最好也就 0.42；剩下是任意组装能不能更好。"**
另外"最好的三元组"是**事后挑的**（用了同一批标签）⇒ 它是**上界**，**不是可用选择器**的分数。

**另一半（本轮已开工）**：新工具 `tools/knowledge/e1_triple_search.py`——**自己组装**三元组，
再用**与 `e1_panel` 逐字同一份** `judge()`（同 SYSTEM 提示词、同两位评委、同 C=3 语境）判分；
判分清单也从**案例索引**取 `title`/`excerpt`（`CaseIndex.retrieve` 返回的是 `Case`，
**没有 `summary` 字段**，所以 `judge()` 用的是 `title[:60] ｜ excerpt[:220]`）。
守门 **5 条**在 `tests/test_e1_triple_search.py`（先红：两条用例因只给一位评委而 0 分——
这正是 P14-249 的口径在生效；补上第二位评委后 5 passed）。
**已开始跑**：`work/_run_triple_search.ps1`（pool 6 → 20 组/查询 × 64 条查询 × 2 评委，6 并发），
产物 `work/_triple_search.batch3.top120.json`。**记账时还没出结果。**

**未验证**：任意组装那一半的结果；换语料/换查询集未测。

### P14-254：**第二十次显式重新冻结**——`e1_triple_search.py` 新增进清单

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R9** | 判据执行环境逐字节不动 | **绿（重新冻结）** | `tests/plan_v4_instruments.sha256.json`：**新增** `tools/knowledge/e1_triple_search.py`（`3eb6d9be2bec…`，guards = 组装三元组搜索器的上界读数）；`_frozen_at` → **第二十次冻结**，理由写进新增的 `_reason_20`（历史 `_reason`／`_reason_19` 逐字保留）。守门 10 passed（参数化多一条） | 2026-10-06 | 本批 |

**为什么要冻它**：它产出的 `E1_best_of_search` 与 `three_of_three` 会被台账**直接引用**
（是 R3 那条红线的判词依据）——不冻就等于"搜出来的上界"这个数可以被事后悄悄改掉。
**判据一个字未动**：阈值 4.0、两位评委取均值（P14-249 口径）、分母与判分语境均与
`e1_panel` **同源**；新仪器只**读数**。

### P14-255：新工具**违反本仓自己的 JSONL 读入口约定**——全量当场抓到，已改并重跑

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R9** | "读 JSONL 只按换行符切" | **缺陷（已修）＋ 已重跑** | 全量 `python -m pytest -o addopts="" -q` ⇒ **1 failed / 2373 passed**：`tests/test_jsonl_reading_convention.py::test_no_new_splitlines_on_read_text_in_the_pipeline_modules` → `['tools/knowledge/e1_triple_search.py']` | 2026-10-06 | 本批 |

**这是真缺陷不是形式主义**：`str.splitlines()` 按 **Unicode 行边界**切，而
U+0085（NEL）／U+2028／U+2029 都是**合法的 JSON 字符串内容**、`json.dumps` 也不转义它们
——本仓实测在 `work/corpus_v4/fetched.jsonl` 上直接抛 `Unterminated string`。

**修法**：`load_cases` 与 `main` 都改走全仓唯一的 `tools.kb_fetch.common.read_jsonl`（只按 `\n` 切）。
**没有**把文件加进守门的 `WHITELIST`——那是"改守门让我的代码过"，明令禁止。

**代价（如实记）**：上一提交（P14-254）先冻后跑全量，是**顺序错了**；而且**先开跑的那次搜索
用的就是违规版本**，所以把它**停掉重跑**——为了产物的出处与冻结哈希对得上。
本提交按设计让 `test_plan_v4_instruments_frozen.py` 判红（哈希换代），由下一次单独重新冻结收口。

### P14-256：**第二十一次显式重新冻结**——`e1_triple_search.py` 哈希换代（缺陷修复，非判据改动）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R9** | 判据执行环境逐字节不动 | **绿（重新冻结）** | `tests/plan_v4_instruments.sha256.json`：`e1_triple_search.py` → `cc7bea0e6c1b…`；`_frozen_at` → **第二十一次冻结**；理由进 `_reason_21`（含"第二十次先冻后跑全量是错的"这条顺序教训）。守门 10 passed | 2026-10-06 | 本批 |

**判据一个字未动**：阈值 4.0、两位评委、分母与判分语境仍与 `e1_panel` 同源。

### P14-257：链上 **Q6b 读的是上一代真跑**——半边指标因此**永远量不到**（SS84 的同形洞，已修）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **Q6b** | 读数通道必须读**真正发出去的那份 prompt**，而且必须是**当前代**的真跑 | **缺陷（已修 ＋ 反例守门）** | `docs/evidence/20261006-q6b-stale-run/`（两份原件 ＋ 反例脚本与逐字输出） | 2026-10-06 | 本批 |

**事实**：`tools/run_tests.ps1` 里两处喂真跑——knowledge 块（`quality.py` 的 `--shots`/`--audit-log`）
读 `$knowledgeRun = 'docs/evidence/20261006-long21'`（**当前代**，链自己的注释写着
*"the chain now feeds the newest committed REAL run that has the hypergraph channel"*），
而 **Q6b 那一行一直写死 `docs/evidence/20261003_real_long`**——那是 **bm25 时代**的跑
（SS84 的原话：`/v1/retrieve` 从没被调用过、逐镜查询是旧形状）。⇒ **SS84 修的是 Q5 那一侧，Q6b 被漏下了。**

**后果不是"数字难看"，是半边指标永远量不到**（同一份 `injection_audit.py`）：

| 读数 | 喂旧跑 | 喂当前代 |
|---|---|---|
| `token_caps` | pass（775/2000、785/800） | pass（**778**/2000、**788**/800） |
| `required_edges_dropped_by_budget` | **`not_measured`**（join 不上 oracle） | **pass：167 镜头 join 上、167 条 required 边、丢 0** |
| `complete` | **false** | **true** |

**修法（一个真源，而不是换一个日期）**：把 Q6b 也接到**同一个 `$knowledgeRun`**，并把定义
**上移到 Q6b 之前**——PowerShell **自上而下执行**，定义留在下面会让这行拿到空路径
（已用同形状脚本在 **Windows PowerShell 5.1** 下实跑：`run_id=5c7b92d738c0`、`exit=0`、
`status pass / complete true`）。原位置只留一行注释指向上面，**不留两处定义**。

**守门**：`tests/test_chain_evidence_is_measured.py::test_q6b_reads_the_same_real_run_as_the_rest_of_the_knowledge_block`
钉三条——只允许**一处**调用 `injection_audit.py`／那一处必须走 `$knowledgeRun` 且**不许出现
`docs/evidence/<8位日期>` 写死路径**／`$knowledgeRun` **只许一处定义且在该调用之前**。
**反例**：`negcontrol_q6b.py` 拿改前的文件跑同一套判据 ⇒ `guard_fails: True`（三处违规），
改后 `False` ⇒ 这条守门**本来就会红在旧文件上**，不是写给已正确的代码看的。

**判据一个字没动**：两个 token 上限（2000／800）、分母规则、`not_measured` 的处置全部原样，
改的只是"**读哪一跑**"。

**未验证**：只验证了这一个真跑与这一个旧跑；`20261006-long21` 是不是"最新"**没有写进代码断言**
（链仍是显式点名一跑，与本仓既有做法一致）⇒ 守门只能保证"**两处不会各读各的**"，
换语料后仍需人记得换那一个值。

### P14-258：修 P14-257 时撞上一条**把旧跑写死**的既有断言（已在链上跑到第 2 步才暴露）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **Q6b** | 既有断言不得把"上一代真跑"钉死 | **缺陷（已修，未放宽）** | 全量链跑到 `[2/32]` 时 pytest 判红：`tests/test_injection_audit.py::test_the_chain_runs_the_injection_audit_and_requires_the_artifact` —— `assert any("--llm-trace" in line and "20261003_real_long" in line …)` | 2026-10-06 | 本批 |

**这条断言本身把缺陷钉在了墙上**：它要求链上喂的正是那份 **bm25 时代**的跑。
处置**不是**删掉它——那才是"改测试让代码过"。

**改法（保留原意并加强）**：仍要求"喂的是**真跑**的 prompt"，但改成走 `$knowledgeRun`，
并**把那一跑从链里读出来、逐个检查输入文件真的在库里**（`llm_trace.jsonl` 与 `audit_log.jsonl`
必须都是文件）。⇒ 旧写法只能证明"链里出现过某个字符串"，新写法证明"链喂的那一跑**确实存在**"。

**顺序教训（第三次，同类）**：P14-257 改完只跑了定向用例、没跑全量，所以这条既有断言
**是在链上跑到第 2 步才暴露**的。⇒ 任何改动之后都先跑全量 `pytest`，再谈跑链。
全量：**2375 passed / 1 skipped**（+1：本批新增的两条守门）。

### P14-259：**冻结树上重跑 32 步验收链**——Q6b 的 required 半边第一次**量到且 pass**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **全链** | 冻结树 32 步 ＋ 门①–⑩ ＋ RK-1…RK-19 | **绿（除 RK-13）** | `docs/evidence/20261006-192508/`：`tree.json.stable = true`（before == after）；`rks.json` 的 `measured_rks` = **19 条全量**、`failed_checks = ['RK-13']`；`holdout_gates` all passed（queries 2847、must_total 2880） | 2026-10-06 | 本批 |

**链上原话（逐字）**：`injection token caps, read off the real prompt: plan 778/2000, shot 788/800`
＋ `required-edge drop half (needs the run queries to join the oracle): **pass**`
——**改前这一行印的是 `not_measured`**。

**A/B 对照（同一套 32 步，只有这一格不同）**：

| | 上一跑 `20261006-133244` | 本跑 `20261006-192508` |
|---|---|---|
| `measured_rks` / `failed_checks` | 19 / `['RK-13']` | 19 / `['RK-13']` |
| `injection_audit.complete` | **false** | **true** |
| `required_edges_dropped_by_budget` | **not_measured** | **pass**（167 镜头 join、丢 0） |
| 读数喂的那一跑 | `20261003_real_long`（bm25 时代） | `20261006-long21`（当前代） |

**结论**：P14-257／P14-258 两处改动**只动了一格**——把"半边永远量不到"变成"量到且通过"；
RK 的判定结果**一条没变**（仍只有 RK-13 红），链仍按裁决**非零退出**并打印
`FAILED: RK-13 …` ＋ `This run is NOT green.`。

**未验证**：这次只跑了一遍（没有做同臂重复跑）；`20261006-long21` 的"当前代"身份仍由
链里那一个显式值承担（守门只保证两处不会各读各的）。

### P14-260：E1 此前是"**量不到**"——把链喂的**同一次测量**换成可认证版（红线仍红，但变成"量到的红"）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **E1** | 链喂的打分文件必须**能被指标认证** | **缺陷（已修 ＋ 反例守门）** | `docs/evidence/20261006-e1-certified/`：`reviews.jsonl`（sha256 前 12 `663e1aeaaf39`，192 行 / 64 查询）＋ 反例脚本与逐字输出 | 2026-10-06 | 本批 |

**事实**：链一直喂 `docs/evidence/20261006-e1-craft/reviews.jsonl`。逐条核过——它与**当前**索引
**同代**（`cases_digest` 逐字相同 `937a04e052e67548…`）、面板也对（`deepseek-chat` ＋ `glm-5.3`）、
`cases_fingerprint`/`prompt_sha256`/`reviewed_by` 都齐——**只差每一行的 `judge_batch`**（全为 0）。
原因是它产出于 `--judge-batch`（P14-205）**存在之前**。而 `e1_relevance` 的规矩是"没有判分语境
就不能认证" ⇒ 记 `not_measured` ＋ `stale_evidence: true`，把 0.1354 一并报出来。
⇒ RK-13 那条红线的措辞是"**我们量不到**"，不是"量到了、远低于 0.70"。

**修法（同一次测量，不是换尺子）**：先验证"同一次"——那份文件的 64 条查询与 **long21 project
的 64 条查询逐字相同（连顺序都同）**；然后在**同一份索引、同一批查询、同两位评委、同 C=3 产品口径**
下重跑一遍，把语境标记写出来（`--project …/20261006-long21/project/project.bdproj --top-k 3 --judge-batch 3`）。

| | 链之前喂的那份（craft） | 认证版（本批） |
|---|---|---|
| `judge_batch` | **0（缺失）** | **3** |
| `e1_relevance.status` | **`not_measured`** | **`fail`** |
| `stale_evidence` | **true** | 无 |
| 值 | 0.1354（按两位评委口径重算） | **0.1771（34/192）** |

**判据一个字没动**：阈值 4.0、分母＝面板行数、线 0.70、C＝3。**它也翻不了绿**（0.1771 ≪ 0.70）——
只把"量不到的"变成"量到的红"。这正是用户 2026-10-06 要的"**能可信地判成败**"。

**守门**：`tests/test_chain_evidence_is_measured.py::test_the_chain_feeds_e1_a_review_file_the_metric_can_certify`
——链上只允许一处 `--e1-reviews`，且**每一行都必须带产品口径的 `judge_batch`**。
**反例**（改前文件跑同一套判据）：`OLD contexts: [0] → guard_fails: True`；`NEW contexts: [3] → False`。
全量：**2376 passed / 1 skipped**。

**未验证 / 边界（如实挂）**：① **标签是新的**（重跑了两位评委）⇒ 0.1771 与旧那份的 0.1823／0.1354
**不是同一次判分**，不能相减当"变化"；**只有一次**这一版（无重复跑、无置信区间）。② 样本量仍远低于
§4.1b 的 E1 下界 **1200**（`sample_shortfall: 1008`），由 `quality.py` 原样报出、**判据未因此改变**。
③ 192 行里有 **9 行只有一位评委**（按 P14-249 口径不算相关、但留在分母）。④ 这份证书**不能**替代
用户对 A／C 的裁决（GPT-6A `a_metric` 第 2 条：结算方式的改动要验收方显式批准）。

### P14-261：**冻结树上重跑全链**——E1 从"**量不到**"变成"**量到的 fail**"

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **全链** | 冻结树 32 步 ＋ RK-1…RK-19 ＋ E1 必须**可判** | **绿（除 RK-13）** | `docs/evidence/20261006-195300/`：`tree.json.stable = true`；`rks.json` 19 条全量、`failed_checks = ['RK-13']` | 2026-10-06 | 本批 |

**A/B（同一套 32 步，唯一差别就是 P14-260 换的那份 E1 输入）**：

| | `20261006-192508`（换前） | `20261006-195300`（换后） |
|---|---|---|
| `knowledge_quality.json` 的 E1 `status` | **`not_measured`** | **`fail`** |
| E1 值 | 0.1354 | **0.1771** |
| `stale_evidence` | **true** | 无 |
| `measured_rks` / `failed_checks` | 19 / `['RK-13']` | 19 / `['RK-13']` |
| Q6b required 半边 | pass | pass |

**结论**：这条红线现在是"**量到了、0.1771 ≪ 0.70**"，而不是"我们量不到"——
**判据一个字没动，颜色的判定也没变**（两跑都只有 RK-13 红、都按裁决非零退出）。
这正是用户 2026-10-06 要的"**能可信地判成败**"。

**未验证**：只跑了这一遍（`20261006-195300` 与 `20261006-192508` 各一次，没有同臂重复）。

### P14-262：**3/3 存在**——P14-253 那句"没有一个 3/3"被自己的探针推翻（换成一条更锋利的机制）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 组装出来的三元组能不能到 3/3 | **绿（先导探针，已推翻上一句）** | `docs/evidence/20261006-e1-triple-ceiling/` 的追加节 ＋ `probe_best_triple.py` / `probe_best_triple.out.txt` / `probe_best_triple.json` | 2026-10-06 | 本批 |

**做法**（只问那一件事的廉价探针，128 次判分）：每条查询取**在自己的 C=3 语境里被标过相关**的行，
凑够 3 行**组装成一个三元组**，用**冻结的 `e1_panel.judge`**（同 SYSTEM、同两位评委）判一次。

```
{"queries": 64, "judge_calls": 128, "distribution": {"0": 11, "1": 26, "2": 23, "3": 4},
 "three_of_three": 4, "E1_best_single_assembled_triple": 0.4375,
 "queries_with_3_labelled_relevant_rows": 57}
```

**必须收回的那句（P14-253 第四节）**："在 2,943 个被判过的 C=3 三元组里没有一个到达 3/3
⇒ 不是'上限高但选不出来'，是'3/3 这种组合几乎不存在'"。**本探针推翻它**：64 条里有 **4 条**
组装出的三元组拿到 3/3（`[4,4,4]`、`[4,4,4]`、`[4,4,4]`、`[4,5,4]`）。原来那个"0 个 3/3"是
**连续分组这个取法的性质**，不是案例空间的性质——我把"这个取法没撞上"写成了"这种东西几乎不存在"。

**换来的更锋利的机制**：**57/64** 的查询都有 **≥3 行曾被标过相关**，但**组装起来仍能 3/3 的只有 4 条**
（57 → 4）⇒ 原始材料几乎每条查询都有，**换个同伴就散**。这是"相关与否是'案例 × 呈现方式'的共同属性"
这句话**更硬的证据**。

**对"上限"的三路交叉（同一把尺子、都是用了标签的 oracle）**：

| 选择方式 | E1 |
|---|---|
| 标签分最高的 3 条重新盲评（`20261006-fresh-oracle`） | 0.4583 |
| 连续 40 组里取最好（P14-253 上半） | 0.4219 |
| **组装**最可能的那一组（本节） | **0.4375** |

⇒ 对 GPT-6A 那条挑战的回答是：**"在'用现有标签去搜'这个空间里，换三种搜法、结果收敛到 ~0.44"**。
它**推翻了"0.46 就是组合最优"这个措辞**（GPT-6A 说得对：那是已试方法的成绩），
但同时说明**换搜法并没有把上界抬起来**。

**边界**：这是 **oracle**（三元组用同一批标签挑的），回答的是"**有没有**"不是"**能不能找到**"；
只有一次；64 条查询、同一份索引。大搜索（`work/_triple_search.batch3.top120.json`）**仍在跑**，
**跑完若与本节不一致，以它为准并在这里更正**。

### P14-263：承重的"上限 0.4583"**没有原件、而且重跑不出来**（已补原件；实测单次散布 ~±0.04）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 承重数字必须可复算 | **缺陷（已补原件）＋ 新读数** | `docs/evidence/20261006-fresh-oracle/`：新增 `reviews.oracle_triple.json`（79 KB 原始分数）＋ `probe_oracle_triple2.py` ＋ `rerun.out.txt`，README 追加一节 | 2026-10-06 | 本批 |

**缺陷**：`0.4583（88/192）` 是**承重**的（RK-13 的整个论证架在它上面），但原实现
`work/_probe_oracle_triple.py` **只打印汇总、不落盘**，而 `work/` 是 gitignore ⇒
**库里任何地方都没有这次判分的原始分数**。不可复算的承重数字，正是本仓反复收口的那类洞。

**补齐 ＋ 重跑**（除写盘外一切照旧：同一份 labels、同一条"按标签分取前 3"、同两位评委、
同一个冻结的 `e1_panel.judge`；两种口径都记）：

| 口径 | 分子/分母 | 值 |
|---|---|---|
| 原 README（**一次**读数） | 88/192 | **0.4583** |
| 重跑 · `loose`（与原来同口径） | 81/192 | **0.4219** |
| 重跑 · `strict`（P14-249 两位评委口径） | 77/192（5 行只有一位评委） | **0.4010** |

⇒ **同一测量重跑差 0.0364（7 行）**；0.4583 **不是**可复现到优于 ~±0.04 的数。
逐三元组分布（loose）：`0 相关 10 / 1 相关 32 / 2 相关 17 / 3 相关 5`
——**5 条查询的 oracle 三元组拿到 3/3**，与 P14-262 的组装探针（4 条）互相印证。

**口径更新（不改判据，改措辞）**：台账里的"可达上界 ≈ 0.46"应读作
**"可达上界约 0.40～0.46（单次读数之间差 ~0.04）"**——**带噪声带的区间**，不是点估计；
任何拿它做小数点后两位推理的地方都要按这个带宽重读。方向不变：全都在 0.70 之下很远。

**未验证**：只重跑**一次**；0.4583 与 0.4219 谁更接近真值**没有定论**，能说的只有散布约 ±0.04。

### P14-264：**§A.3 的 17 条用户故事逐条对账**——整份验收面收窄到"**一格红**"

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **§A.3** | 每条 AC 都必须能用 §4 的 oracle 或命令客观判定 | **绿（16/17）**；唯一不满足的是 **US-11⑥** | `docs/evidence/20261006-us-traceability/README.md`；权威读数为 `docs/evidence/20261006-195300/`（同一次冻结树全链） | 2026-10-06 | 本批 |

**这一步此前没人做过**：§A.3 的抬头写着"每条 AC 都必须能用 §4 的 oracle 或命令客观判定"，
但**17 条从没逐条对过账**。

**权威读数**：`rks.json` → **19 条 RK 全部 measured，18 pass、唯一 fail 是 `RK-13`**（185 条 check）；
`holdout_gates.json` → **门①–⑩ 全部到位且 pass**；`knowledge_quality.json` →
`Q0/K1/Q1–Q7/E3` 全 pass、**`E1 fail 0.1771`**、`E2 not_measured`；`tree.json.stable = true`。

**结论**：**17 条里 16 条的全部 AC 都有"已登记且量到"的 oracle／契约用例**；
唯一不满足的是 **`US-11`，而且只差第 ⑥ 项（E1 ≥ 70%）**——就是 RK-13，现在是**量到的 fail**，
不再是"量不到"。⇒ **整份 v1.4 的验收面收窄到一格**：`US-11⑥ = RK-13 = E1`。
这一格要不要动、怎么动，**是用户对 A／C 的裁决**（GPT-6A 的 `a_metric` 与 `full_head` 都指出
"改测量协议必须用户明示批准"）。

**顺带核过 §5 的 R43 贯穿规则**：`test_operator_end_to_end.py`／`test_scene_contract.py`／
`test_label_layout.py`／`test_label_toggles.py`／`test_knowledge_holdout.py`／`test_knowledge_trace.py`
**全部存在**，前四个已作为 `operator-e2e`／`scene-contract`／`label-layout`／`label-toggles`
**登记在链的 32 步清单里**（`run_tests.ps1:138-143`）。

**未验证 / 我依赖了什么（如实挂）**：**逐条读过断言的只有 5 处**（US-1③、US-13、US-14、US-15、US-17）；
其余各条**依赖"链上该 RK 已 measured 且 pass"**（本仓的权威读数），**不是**逐个 AC 去核措辞。
⇒ 本表证明"**每格都有已登记的测量**"，**不等于**"逐字核过每条 AC"。
另外 **US-16 的负例链里不跑**（`INCOMPLETE` 分支读了代码，但"清空变量"是 §4.4 的手工步骤）；
**§A.4 的成功指标表与 §6 的风险取证表未在本轮逐条对账**。

### P14-265：**§6 的"取证落点表"逐条对账**——没有"写了却没做"的格子

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **§6** | 每条风险的"取证"必须是具名产物/测试/阶段 | **绿（逐条有实物）** | `docs/evidence/20261006-us-traceability/README.md` 第五节 | 2026-10-06 | 本批 |

§6 自己写着"不得写'报告/CI'这类不存在的东西"，所以这张表**可以被机械核对**。逐条结果：

| 风险 | 点名要有的东西 | 结论 |
|---|---|---|
| 抽取噪声 | `tools/knowledge/sample_edges.py` → `edge_spotcheck.jsonl`；`rejects ≤ 5%` | ✅ 脚本在；本跑 28,759 B；**`rejects = 0`** |
| 超边重复与爆炸 | `hypergraph.manifest.json` 的四计数 | ✅ **638 / 638 / 0 / 0** |
| 检索"半条边" | Q6b = 100%（读**实际 prompt**）＋ Q7 = 100% | ✅ 两者 `pass`（含 required 半边） |
| 评测无公开基准 | `fixtures/knowledge_holdout.jsonl`（≥1200）＋ `check_holdout.py` | ✅ 门①–⑩ 全 pass（queries 2847） |
| 重抽取成本／确定性 | `tests/test_hypergraph_determinism.py` | ✅ **文件在**（只核存在，未读断言） |
| 通用·预算 | `shots.json` 与 `audit_log` 独立对拍 | ✅ **RK-18 `pass`** |
| 通用·依赖 | `tests/test_knowledge_trace.py`；trace 的 `lanes`/`cases_degraded` | ✅ 文件在；long21 trace 六个键全在 |

**一条如实记的观察（未定性为缺陷）**：链上那次**离线** headless 跑的 `knowledge_trace.json`
写在**临时目录**（逐字 `C:\Users\…\Temp\bd_run_194204\knowledge_trace.json`），
**没进 `docs/evidence/<run-id>/`** ⇒ 那次运行的证据目录里没有 trace，能引用的是**真实模型跑 long21** 那份。
产品行为合格（trace 确实被写、内容齐），但按本仓那句"能悄悄消失的具名产物＝能悄悄消失的门"值得记一笔；
**未定性为缺陷**——§6 只要求"必写"，**没要求落在证据目录**，要不要收紧是**新的选择题**，本轮不擅自改。

### P14-266：**§A.4 成功指标表逐行对账**——八行里七行满足，唯一不满足的仍是 `E1`

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **§A.4** | "全部可度量"的八行 | **绿（7/8）** | `docs/evidence/20261006-us-traceability/README.md` 第六节 | 2026-10-06 | 本批 |

读数（`20261006-195300`，冻结树）：出片/规模/几何/标签/构图/预算六行分别由 **RK-9、RK-11、
RK-14+RK-6+RK-4、RK-2、RK-10、RK-18 全部 `pass`** 兜住；知识那一行 **K1 `1.0` / K2 `1.0` /
K3 每域最小 154 张、占比 0.0654 / K4 `1.0` / Q1 `0.9975` / Q2 `1.0` / Q3 `0.0` / Q4 `1.0` /
Q6b `1.0` / Q7 `1.0` / E3 `0` 全 pass，`E1 = fail 0.1771`**；回归那一行由 `pytest`（2376 passed）＋
32 步链＋空断言扫描 **[OK] 272 文件** 兜住，`#34`（生产常量）由 **RK-14/RK-15 输入侧**量住且两者 `pass`。

⇒ **与 §A.3、§6 的结论互相同证：整份 v1.4 的验收面就是一格**（`US-11⑥ = §A.4 知识行 E1 = RK-13`）。

**未验证（如实挂）**："33 条断言不得被**弱化**"这一格，我核的是**"在执行、没被跳过"＋"没有空断言"**，
**没有**逐条拿 §1.6 的 `文件:行号` 去比对今天的断言是否仍**等强**——那是一次**独立的逐条审计**，本轮没做。

### P14-267：**§1.6 的 ⚠"会量错"类逐条查完**——全收敛到 profile；抓到一条**真的没闭合**（#20，已修）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **§1.6** | ⚠ 类"不会红、只会量旧几何"必须闭合 | **绿（全收敛）＋ 抓到 #20 未闭合（已修）** | `docs/evidence/20261006-us-traceability/README.md` 第七节 | 2026-10-06 | 本批 |

**⚠ 类（最危险的一类）**：§3.1 点名的"十个硬编码位置 ＋ 三个必改消费者"逐个查——
`cinema/framing.py`（`_PROFILE.total_height/eye_z/chest_z`）、`cinema/composition.py`、
`sdl_validator.py`、`composition_guide.py`（改为 import `SUBJECT_HEIGHT`）、
`knowledge/corpus.py`（digest 与卡正文改为**插值** `EYE_Z`/`CHEST_Z`）、`motion/model.py:306`、
**`cards_cinematography.py`（文档说它"没有任何测试对拍、最隐蔽"的那处）**、
`character_factory.py`（`EXPECTED_TOTAL_HEIGHT = _PROFILE.head_top_z`）——**全部改成了 profile 派生**。
唯一剩下的字面数字是 `framing.py` 的 `_FRAME_HEIGHT_RATIO`（`"CU": 0.90 / 1.45`），
但注释写明那是"**v1.3 比例**、随 profile 身高缩放"（`:116`）并对含头景别加下限 `_MIN_HEAD_FRAME`（`:99`）
⇒ 与 RK-7 `pass` 一致，**是设计选择不是漏网**。

**抽样复核的"会变红"类**：#6 `full_concat: true` ✅；#15/#25 `max_wall_minutes == 120.0`
＋ `formula == "shots * 8 + 40"`（**改期望值，不是删断言**）✅；#21 `AGENTS.md` 已对齐 ✅；
#26 `rag.backend is HYPERGRAPH` ✅；#27–33 六处改 `== SDL_VERSION`、golden 快照 `"1.4"` ✅。

**抓到的那一条（§1.6 #20，本提交修掉）**：§3.1 的模块表明写"`budget_formula.py` 的注释里
`"shots * 6"` 同步改（§1.6 #20）"，实测**两条都还在**：`budget_formula.py:4` 的 docstring 举例、
以及 `tests/test_budget_formula.py::test_documented_default_formula`——**名字说"文档里的默认公式"，
断言的却是 v1.3 的旧默认 `shots * 6`**。这是 F7"同源文档漂移"里最难发现的一种：**测试是绿的**，
名字还在替一个**已经不存在的默认值**作证。修法是**加强不是替换**：docstring 改真默认；
那一格**从配置读真源**再算，**同时保留** `shots * N` 形状的覆盖。
守门：全量 **2376 passed / 1 skipped**；`check_assertions.py` **[OK] 272 文件**。

**未验证 / 观察**：**只逐条查了 ⚠ 类 ＋ 抽样 6 条**，**不是全部 34 条**（#2/#3/#5/#7/#9/#11/#12/#19/#24/#35
的"是否等强"没逐条比）；两处**未定性**观察：`fixtures/local_model.config.yaml:39` 仍写 `"shots * 6"`、
`fixtures/local_sidecar.config.yaml:47` 仍写 `"shots * 8"`（探针用的显式配置、非默认值，§1.6 未列，**本轮不改**）。

### P14-268：**§1.6 剩下的补完**——34 行全部有结论；又抓到一条没闭合（**#8 / T7**，已修）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **§1.6** | 34 行逐条有结论 | **绿（补完）＋ 抓到 #8 未闭合（已修）** | `docs/evidence/20261006-us-traceability/README.md` 第八节 | 2026-10-06 | 本批 |

P14-267 只查了 ⚠ 类 ＋ 抽样 6 条，把其余挂在"未验证"里。本轮**补完**：**§1.6 的 34 行现在全部有结论**。
补查的 13 行全部闭合（#2 `== []` 已恢复；#3 R014 空镜分支已删、归 R017；#4 白名单改到
`collection_router.audit_renderable_objects` 且**不再读对象自报的 `bd_element_type`**；
#5 `INCOMPLETE` ＋**"执行集合 == 清单"是构造保证**（探针循环直接 `foreach` 清单）＋缺 marker 判失败；
#7 `expected_calls()` 不许写死 7；#9 `CH_ROOT_LOC` 随 root 落地重写；#11 `test_manifest_fields` 全覆盖；
#12 30/20/12；#13 改遍历 `SHOT_FRAME`；#16 原样在；#19 条件项原样；#24 transcript **0 命中**
`screen_direction`；#35 `RetrieveResponse` 三字段全 `default_factory=list`、openapi 版本仍 1.3.0）。

**抓到的那一条（#8 / §2.3d T7）**：文档三处都要求新增显式断言
`set(DOMAINS) == set(DOMAIN_DIGESTS)`，实测 **`rg -l DOMAIN_DIGESTS tests/` 为空——从没写出来过**。

**顺带修准文档自己说的病因**：原话是"漏配 digest **不会红、会直接 `KeyError`**"。按实现读，
`digest_cards()` 按 `DOMAIN_DIGESTS.items()` 遍历 ⇒ **单纯加域会少一张卡、条数不等 ⇒ 旁边那格会红**；
真正不红的是 ① **换名**（条数相等、集合不同）② digest 有而 `DOMAIN_LABELS` 没有 ⇒ `KeyError`。
⇒ **药方（集合相等）对，而且比它说的理由更必要**（它抓的是换名）。

**修法（纯增不改）**：新增两格——三个集合两两相等 ＋ 一条"换名"负例（证明旁边那格抓不住、这格抓得住）。
`git diff --stat` = **27 insertions / 0 deletions**；全量 **2378 passed / 1 skipped**；`check_assertions.py` **[OK] 272 文件**。

**仍未验证**：`fixtures/local_model.config.yaml:39`（`"shots * 6"`）与 `local_sidecar.config.yaml:47`
（`"shots * 8"`）两处**未定性**观察（探针用显式配置、非默认值，§1.6 未列，**本轮不改**）。

### P14-269：**§B（TDD）与 §7 也走完**——文档级审计到此结束，只剩一格 ＋ 两处未验证

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **§B / §7** | §B.3–§B.5 的具名测试与突变用例、§7 的待拍板项 | **绿（可核对部分全过）** | `docs/evidence/20261006-us-traceability/README.md` 第九节 | 2026-10-06 | 本批 |

**§B.3**：约 30 个具名文件**全部存在**，且用例名与其"预期红的原因"对得上——含两处易漏的
`tests/test_script_inline_dialogue.py`（P11）与 `tests/test_shotlist_render.py`（P13，其中的
`test_the_fixture_really_crosses_the_old_cutoff` 正是"跨过旧 60 闸"）；四个 Blender 探针**都已登记进链**。
**§B.4**：6 个夹具**全部入库**，且 `tools/gen_golden.py:41 LONG_PLAN_FILE` 证明"生成器吃长夹具"确实做了。
**§B.5**：六条反向突变**逐条在**（`rk1_hidden_label_goes_red`／`rk2_overlapping_labels_go_red`／
`rk6_floating_goes_red`／`operator_refuses_without_a_builder`／`rk10_breaking_the_framing_drops_the_rate`／
`rk14_lowered_head_goes_red`）；P16 的静态检查 `tools/check_assertions.py` **不依赖 bpy**，
且 `tests/test_assertion_hygiene.py` 专守"它存在、并且**能红**"。

**§7**：唯一一条是 **D1b 躯干形状**（默认 ①圆柱），当前实现是圆柱 ⇒ **与默认一致、不阻塞**；
但**"P10 内以 A/B 截图裁决"有没有做过，我没查到证据** ⇒ 如实列为**未验证**，不替它下结论。

### 文档级审计总账（到此为止）

**§A.3 / §A.4 / §B.3 / §B.4 / §B.5 / §1.6 / §6 全部走完**；途中抓到并修掉**两条真缺陷**
（§1.6 **#20**、**#8/T7**），两条都有守门。整份 v1.4 的验收面收窄到**一格**：
`US-11⑥ = §A.4 知识行 E1 = RK-13 = E1`（**量到的** fail，0.1771）。

**仍未验证只剩三件**：① 那一格的 A／C 裁决（**用户**）；② §7 的 D1b A/B 截图裁决**有没有做过**；
③ 大搜索（pid 49548）与 GPT-6A `b_closeout`（pid 4484）两条长跑的结果。

### P14-270："知识→成片"的执行闭环：**没人管**是真的，但**naive 的补法当场假阳性**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **越界项（非 v1.4）** | GPT-6A `c_arch` 第 3 条"执行闭环"是意见还是事实 | **绿（已量化，并给出反例）** | `docs/evidence/20261006-forbid-vs-plan/`（探针 ＋ 原始产物 ＋ 那一镜的逐字注入块） | 2026-10-06 | 本批 |

**结构侧（读码两处）**：`rule_checker.py` 对 `knowledge` **只有一行**引用（`last_edges_query`，是**记账**）；
R001–R019 全是几何/连续性规则，**没有一条由 `forbid` 驱动**；注入那一路只把边渲染进 prompt、**不产出断言**。
⇒ **注入 ≠ 执行**，GPT-6A 那条**成立**。

**但更值钱的是反例**：最直觉的检查（逐镜取实际 prompt 的 `禁={...}` ∩ 该镜计划运镜）跑在
唯一真跑 long21 上，**一枪命中** `shot_005`：计划 `dolly_in`、注入里也有 `forbid movement:dolly_in`。
**可它不成立**——把那一镜的完整注入块读出来：三条 `[INTENT_PACK] shot_size=MCU … movement=dolly_in`
（**MCU×dolly_in 是被允许的**），而那条 `forbid` 挂在 **`shot_size=MS`** 上；`shot_005` 的
`shot_type` 是 **MCU** ⇒ **适用域不匹配，我的"1 条违规"是忽略适用域造出来的假阳性**。

**还有一条更硬的**：那一镜的运镜 `source` 是 **`declared`**（**剧本自己声明的**），
而全片 64 镜**只有 1 镜有运镜**（其余 static）⇒ 在**现有证据**上，"计划违反注入约束"
**连一次真冲突都还没发生**，风险大小**量不出来**。

**三句结论**：① 闭环确实缺；② **不能照直觉补**——任何"成员交集即违规"必须先绑**适用域**
（这正是 GPT-6A 原话里的"适用域／对象-时间绑定"，这里给了它具体形状）；③ 要量化风险，
得先有**真会动镜头**的跑或一条**合成夹具**（注入一条明确适用本镜的 `forbid`，看有没有东西拦住）。

**边界**：只查了 `movement`/`shot_size` 两类成员、只用了一份真跑；
**没有实现那条闭环**——文档的规则集是 R001–R019，**没有一条**要求"校验超边约束的执行"，
所以这是**超出 v1.4 的新选择题**（做成**诊断**还是**新规则 R0xx**），按本仓纪律单列待裁，不擅自加。

### P14-271：**勘误**——§7 的 D1b A/B **早就做了**，是我"没搜就断言没有"

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **§7** | 待拍板项的 A/B 证据是否存在 | **勘误（我先前记错）** | `docs/evidence/d1b_body_shape/`（四张图 ＋ 已登记进链的 `test_character_body_ab.py`） | 2026-10-06 | 本批 |

P14-269 里我写过"§7 的 D1b A/B 截图裁决**有没有做过，我没查到证据**"，并列为未验证。
**这是错的**：`docs/evidence/d1b_body_shape/` **一直存在**（`A_cylinder.png`／`B_rounded_box.png`／
`A_CU_left.png`／`B_CU_left.png` ＋ 探针）。我那次**没有去搜证据目录**就断言了"没有"——
正是本仓最忌讳的"**用没搜到冒充不存在**"。那条 A/B 还**反过来修正了文档**：
文档担心"选项 ② 需改 bbox/构图常量"，实测**不成立**（同盒，`max_delta = 0.0`）。
⇒ 该项状态是"**证据已备、只差用户一句话**"。已同步勘误 `docs/evidence/20261006-us-traceability/README.md`。

### P14-272：**决策简报换代**——`DECISION_BRIEF_RK13.md` 此前仍推荐**已被推翻的 B**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **交付物** | 用户据以裁决的那份文件必须**与当前证据一致** | **缺陷（已修）** | `docs/knowledge/DECISION_BRIEF_RK13.md` 顶部新增"更新：本节覆盖下文旧结论" | 2026-10-06 | 本批 |

**缺陷**：那份简报写于当天早些时候，其"三、第三方判词"给的建议是 **选 B（逐条独立盲评）**——
而 **B 在几小时后就已被实测排除**（`docs/evidence/20261006-oracle-alone/`：oracle-3 逐条单独判
E1 **0.1458**，**比三元组的 0.4583 还差**）。它还写着"可达上界 **0.4583**"（点估计，
实际单次散布 ~±0.04），以及"3/3 几乎不存在"（已被 P14-262 推翻）。
⇒ **用户一回来读到它，会被引去重走一条已经堵死的路。**

**修法（只加"上层更新节"，不改写历史）**：顶部插入一节逐条覆盖旧结论——
① B 已排除（附证据）；② 上界是 **0.40–0.46 的带**（附重跑读数）；③ 3/3 存在且"换个同伴就散"；
④ E1 已从 `not_measured` 变成**量到的 `fail` 0.1771**；⑤ 第三方**后来的**两条建议
（`full_head`：本版选 A 并结案；`a_metric`：C 的结算式 ＋ 必须显式批准）；
⑥ 另两件在用户桌上的事（D1b 的 A/B 证据已备；执行闭环缺失且 naive 补法假阳性）。
并把"要用户回答的"从**一个**问题改成**两个**（E1 的 A/C；执行闭环要不要做成诊断）。

**判据一个字没动**：这一段只改"摆在桌面上的选项与其代价"，**没有**替用户做任何裁决。

### P14-273：把适用域**绑一半**——违规数从 **1** 跳到 **66**，而且全来自同一条边

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **越界项（非 v1.4）** | "执行闭环"到底缺什么 | **绿（三层测下来，缺的是语义层不是 `if`）** | `docs/evidence/20261006-forbid-vs-plan/`（`probe_forbid_apply.py` ＋ `domain_bound_check.json` ＋ README 第六节） | 2026-10-06 | 本批 |

P14-270 的假阳性说明"不绑适用域不行"。那就**绑一半**：把能对上的 kind
（`shot_size`/`movement`/`intent` ↔ 镜的 `shot_type`/运镜/`intent_type`）当适用条件，
**两边都过 `hypergraph.VALUE_ALIASES`** 折到同一规范写法（`static → 固定`），只比适用边：

```
{"edges_applying": 135, "violations": 66, "unbound_members": 0}
violating edge shapes: {('AXIS_RULE', ()): 66}     ← 全是 AXIS_RULE，plain 成员**空**
distinct shots flagged: 63
```

**原因在渲染形式上**：`[SHOT_PATTERN]` 用 `kind:value` 风格（`shot_size=shot_size:MS`），
而 `[AXIS_RULE]` 用**质词风格**（`pair=any_two axis_side=neutral axis_topic=…`）——
我的绑定器读不出"质词是不是适用条件"，于是把它当**无条件**。
回**结构化索引**（唯一真源）数：`AXIS_RULE` 里 forbid 落在 `movement` 上的只有 **3 条**，
真正在响的是 **`hg:6982a3446c7f`**（**hard/theory**）：`axis_side=neutral` ＋ `axis_topic=越轴`
→ **`forbid movement:固定`**；而**全片 63/64 镜都是 `static`（＝`固定`）** ⇒ 一旦被当成无条件就在几乎每一镜上响。

**结论（比前两节更硬）**：**违规数完全取决于你实现了多少"适用域"**——0 层 → **1**（假阳性）、
1 层 → **66**（仍全来自一条**绑不上**的边），**两个数都不是可信的违规率**。
缺的不是一个 `if`，而是**一套 per-kind 的适用域语义表**（哪些 kind 是条件、各自映射到成片的哪个属性：
`axis_side` 绑什么？`pair=any_two` 算什么？`axis_topic` 是话题还是条件？）。
本仓没有这张表——`REQUIRED_MEMBERS`/`OPTIONAL_MEMBERS` 只说"哪些槽位必填"，
不说"它是不是适用条件、对着场景哪个字段"。**这就是 GPT-6A 说的"适用域／对象-时间绑定"在代码里的确切形态。**

**未验证**：只覆盖 `movement`/`shot_size`/`intent` 三类可绑定 kind；`axis_side` 等质词的绑定没做
⇒ **"66 条里有几条是真违规"在语义表落地之前不可答**；仍只跑一份真跑。

### P14-274：把 P14-273 的结论做成**提案**——per-kind 适用域语义表（**未实施**）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **越界项（非 v1.4）** | "执行闭环"要落地，先要什么 | **绿（提案成文，只提设计）** | `docs/knowledge/APPLICABILITY_SEMANTICS_v1.md` | 2026-10-06 | 本批 |

P14-273 证明"缺的是 per-kind 语义表"。本批把那张表**写成提案**（**不改代码、不改判据、不设门**）：

* **现状盘点**（从唯一真源 `knowledge/hypergraph.edges.jsonl` 638 条边统计）：
  索引里实际出现 **24 个 kind**；其中 `camera_angle`(175)／`intensity`(228)／`beat_type`(97)／
  `headroom_policy`(83) 等**只出现在质词位**，而 `emotion`(173 allow/9 forbid)／`lighting`(36/13)／
  `pacing`(42/4) 等出现在 allow/forbid 位。schema 只说"哪些槽位必填"，
  **不说"它是不是适用条件、对着成片的哪个字段"**。
* **三类分法**：① **可绑定**（`shot_size`/`movement`/`intent`/`lens`/`vfx`/`action`/`transition`/`pacing`/
  `composition_rule`/`camera_angle`——都能对到 `SDLShot`/`SDLCamera` 的实测字段）；
  ② **成片里没有字段**（`emotion`/`intensity`/`beat_type`/`genre`/`music`/`sfx`/`lighting`…——
  要落地得**先加字段**，那是扩范围）；③ **不是条件、只是话题/标注**（`axis_topic`/`example_shot`/
  `applies_to_*`，以及**所有只出现在质词位的 kind**）。
* **必须由用户拍板的三件**：②那批**要不要扩范围**（不做就写明"不校验"，别留未定义）；
  ①里的**区间/阈值型**（`pacing`/`composition_rule`/`camera_angle`）判据怎么定（定阈值＝新判据，须批准）；
  报出来的数是先做**诊断**还是直接**设门/R0xx**（我建议**先诊断**）。
* **建议的第一步（最小可回退）**：只做①类里**相等式**的那几个，产 `forbid_vs_plan.json` 诊断，
  **不设门、不改链的退出码**；②③类在报告里**显式列为"未纳入"**（依 §4.1b 的精神，未纳入要写出来）。

**未验证**：分类是**人工判断**（基于 schema＋索引实测＋成片字段清单），**没有**逐条核对每个 kind × 每条边；
`pair`/`prop`/`axis_side` 标"待定"正是因为它们**看名字像能绑、但没有机械可推的字段**；
只统计一份索引与一份真跑。**本文只是一份 markdown，没动任何代码或判据。**

### P14-275：**大搜索跑完——它推翻了"不可达"，也推翻了我自己的"三路收敛"**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 在 C=3 尺子上搜组装三元组，看 0.70 到底可不可达 | **绿（终审读数）** | `docs/evidence/20261006-e1-triple-ceiling/full_search.json`（1280 个三元组、`exit=0`、20:48:56 落地） | 2026-10-06 | 本批 |

```
{"queries": 64, "triples_judged": 1280,
 "distribution": {"0": 308, "1": 547, "2": 376, "3": 49},
 "three_of_three": 49, "E1_best_of_search": 0.7448}
```

**每条查询的最佳三元组**：`0/1/2/3 相关` = **1 / 5 / 36 / 22** 条；均值 **0.7448**；
**64 条里 22 条（34%）能凑出 3/3**；只有 1 条查询在 20 个组合里一个相关都找不到。

**推翻之一（改台账口径，不改判据）**：P14-240 的"终局"写着
*"当前测量协议下 E1 的可达上界约 0.46～0.47；要过 0.70 只能动测量协议"*。
现在**在同一把尺子上**（同索引、同 64 查询、同两位评委、同 `judge_batch=3`），只要把候选
**重新组装**成三元组再搜（每条 20 组合），**最佳三元组均值 0.7448 ≥ 0.70**
⇒ **红线在冻结协议下可达**；卡住的是**"挑哪 3 条"**，不是"尺子"。
**⇒ 选项 C（改测量定义）的前提没了**；这条从"判据问题"回到"**选择器问题**"。

**推翻之二（改我自己的口径）**：P14-262/263 我把 0.4583／0.4219／0.4375 三个 oracle 写成
"换三种搜法、收敛到 0.42–0.46"。**第四路（组装 20 组）到 0.7448** ⇒ 那三个数**不是上界**，
是**搜得不够宽**——**GPT-6A 第 3 条（"0.46 是已试方法的成绩，不是组合最优"）说对了**。

**边界（必须挂）**：`E1_best_of_search` 是**用了标签的 oracle**（在 20 个组合里挑最好的），
**不是**现有选择器能拿到的分——**实测最好的真重排器仍是 0.44**。正确的说法是
**"红线可达，瓶颈在'挑'不在'有没有'"**，不是"我们能拿到 0.74"。池子由同一批标签排出，
"不知判分结果的选择器能到多少"**没测**；一次搜索一次判分、**无重复**；只 64 查询一份索引；
每查询 20 组合是**全枚举**（池 6 的 C(6,3)），**扩池未测**。

### P14-276："gpt6A 有点问题"是对的——**请求被丢掉后静默挂着，而且没有单次上限**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **通道** | 咨询通道"跑很久没结果"是慢还是坏 | **缺陷（已修 ＋ 守门）** | `docs/evidence/20261006-gpt6a-silent-hang/`（三兄弟对照 ＋ 修复 ＋ 巡查改造） | 2026-10-06 | 本批 |

**诊断**：同一秒（18:34:45）发出、**同样 1.3–1.8 KB 的包**、同样 `max_tokens=32768`＋
`reasoning_effort=max` 的三件——`c_arch` **3.4 分钟**、`a_metric` **5.1 分钟**返回正文；
`b_closeout` **137 分钟零字节**（`dRead=0/40s`、`dCpu=0/40s`、连接 `Established`）。
⇒ **同输入同参数：它是被丢掉了，不是在思考。**（20:53 掐掉。）中转站**没有 keepalive**，
所以"在思考"与"被丢掉"在本机**无法区分**。

**根因（造成伤害的那一半）**：socket 超时是**每次读**的超时 ⇒ 它就是"多久没数据就放弃这次尝试"；
而调用方给的是**总预算**（`--timeout 21600`）⇒ 静默请求占位 **6 h**，`consult` 还重试 3 次 ⇒ **最坏 18 h**。
**它不是慢，是没人给它设放弃线。**

**修复**：`tools/relay_consult.py` 加**单次无数据上限** `attempt_timeout`（默认 1800 s；
实际 `min(总预算, 上限)`；传 0 才退回旧行为）、**每次尝试新建客户端**、上限写进
`usage.attempt_timeout_s` 与失败记录；`work/_gpt6a_ask.py` 增加 `--attempt-timeout`（用 900 s）。
守门 2 条在 `tests/test_llm_relay.py`；全量 **2380 passed / 1 skipped**。
⇒ 现在最坏约 **45 分钟**必有**明确结果或明确失败**。**不冲突于"给更多时间"**：上限是单次**无数据**的，
数据在流就一直等。

**顺带抓到的操作缺陷**：掐掉的那件（pid 51912，19:18 起 100 分钟零字节）问的是
`work/_q_gpt6a_decides.md`——与主线**同一意图**（"你是验收方，直接下决定"），
而它**是本仓库的定时巡查任务发起的**（它本该只观察）⇒ 重复占通道且用旧的无上限封装。
**处置**：巡查改成**只观察**（不许跑 `_gpt6a_ask.py`／不许写新问题／不许改仓库），发现为空只报告。

**未验证**：丢请求的**发生率**没有统计；中转站/上游的丢包原因本机看不到。

### P14-277：**漂移检查**——文档内部零漂移；`AGENTS.md` 抓到并修掉 1 处（§1.6 #21 没对齐干净的那格）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **漂移** | 文档／说明与事实是否漂移 | **绿（1 处已修）** | `docs/evidence/20261006-drift-check/`（探针 ＋ 逐字输出 ＋ 判定） | 2026-10-06 | 本批 |

**文档内部：零漂移**（机械核对 §0.1 自称的"单一真源"）：阶段 9/9、BW 行 7/7、D 5/5、
F/S 19/19、X 17/17、**§1.6 条目 34/34**、oracle 19/19、用户故事 17/17、§B.4 夹具 6/6 且在盘上。
**两处"像漂移"的是取数方式不同、文档是对的**：① BW 是"6 条观察 / **7 行**"（BW-4 拆 a/b，§0.1 自己写明）；
② §1.6 按**行**只有 28，因为 `#27–33` 七条挤在一行，按**条目**展开才是 34。

**跨文件抓到 1 处真漂移（已修）**：`AGENTS.md:52-54`（**Status 段**）仍写
"hand-written corpus … **132 cards across the five v1.3 domains**; P14 **expands** it to nine domains"
——而 P14 的九域扩容**早已完成**（实测 **9 域 / 2,353 卡**，索引覆盖 **2,221**，L3 **1,143**，边 **638**）。
⇒ 这正是 §1.6 **#21** 里**没对齐干净的那一格**（公式与 Phase 5 早已对齐，语料那条留在 v1.3）。
已改成"9 域 / 2,353 卡 ＋ 132 张手写子集**尚未进索引**（已知缺口 OPEN_PROBLEMS ⑲）"并附**可复核来源**。
**判据一个字没动**（改的是给 agent 看的事实陈述，不是验收判据）。

**没有算漂移的两处**：`AGENTS.md:288` 的"现行口径 2353 张卡 / 638 条边"**与我实测一致**，
且它**明说**"别照抄下面那组数字"；下面那组是**那一次重建的原始记录** ⇒ **历史读数有标注 ≠ 漂移**。

**未验证**：`CONTEXT.md`／`docs/adr/*`／其余证据 README 的陈述**没有逐条对**；
**行号漂移**（§1.6 的 `文件:行号` 因演进偏移）没逐条修——本仓一直当"已知噪声"。

### P14-278：**重新规划**已发出（GPT-6A 起草 ＋ 5 轮精炼，进行中）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **计划** | 用 GPT-6A 重新规划下一步执行计划 | **进行中（已发，包合规）** | `work/_plan_replan/`（`bundle.manifest.json` 先写证再联网） | 2026-10-06 | 本批 |

`tools/plan_writer.py --provider relay --question work/_q_gpt6a_replan.md --question-only
--out work/_plan_replan/ --rounds 5 --max-prompt-chars 3100`。**包合规**：
`bundle.manifest.json` 记 `status.sent_chars = 2068`（≤ 预算）。
**两处值得一提**：① 工具**在联网前**先按预算拒过一次（3,234 > 3,000）——**守门有效**，
我把问题压到 2,016 字符重发；② 预算显式放宽到 3,100 的依据是**中转站侧的实测包线**
（`work/_q_gpt6a_full_head.md` 5,309 B 在 6 分钟内返回正文），不是拍脑袋。

### P14-279：漂移检查补完另一半——`CONTEXT.md` 干净，**`ADR-0015` 又抓到一处（承重的）**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **漂移** | `CONTEXT.md`／`docs/adr/*` 的事实陈述 | **绿（1 处已修）** | `docs/evidence/20261006-drift-check/README.md` 第五节 | 2026-10-06 | 本批 |

**`CONTEXT.md` 干净**：65 行，术语表与目录地图与当前代码一致；可疑旧数扫描只剩
`knowledge/` 行"（**P14 起**）超图/案例层"——那是**事实陈述**（P14 之后确实多了一层），不是过期状态。

**`ADR-0015` 是真漂移，而且承重**：它授权"第三方裁定代替人审"，标题与决定①都写着通道是
**Kimi K3**——但同一天通道换了**两次**（Kimi 额度挂起 → 用户"难题攻关和会诊 gpt6A" →
**中转站 GPT-6A `gpt-6-astra`**），ADR **没跟上**。读者照它去用 Kimi 会发现通道是死的。

**处置（不改历史，只追加）**：标题加"通道已换代，见文末"；正文顶部加醒目指引
"下文凡写 Kimi K3 的**通道**应读作 GPT-6A"；文末追加**「通道换代」**一节，写清两次换道、
现行分工表（GPT-6A 想/判、DeepSeek 做、GLM 对拍、Kimi 仍不可用）、以及
"**GPT-6A 代替用户做决定**"对"要不要动"类推定的适用范围。
**三条决定一个字没动**（不冒充 `human`／必须自带 `source{model, prompt_sha256, authorized_by}`／
门⑦ 认哪些类别由 `--reviewer-classes` 显式点名）；门①–⑩ 阈值、E1 的 4.0 与分母也一个字没动。

**仍未验证**：`docs/evidence/*/README.md`（约几十份）的陈述没逐条对；`ADR-0007…0014` **只核了标题**。

### P14-280：漂移检查收官——`ADR-0007…0014` 正文也核了，**没有更多漂移**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **漂移** | `ADR-0007…0014` 的决策陈述 | **绿（无更多漂移）** | `docs/evidence/20261006-drift-check/README.md` 第六节 | 2026-10-06 | 本批 |

逐条对回当前事实：**0007** 几何 1.70 ＋ 头球相切（八处硬编码已全改 `_PROFILE` 派生，RK-14/RK-7 pass）；
**0008** `max(ceiling, formula)` ＋ CLI 硬顶（`test_long_script_ceiling_is_the_max_not_the_min`，RK-18 pass）；
**0009** SDL 格式 1.4 ＋ `with_labels`／包协议版本不动（7 处改 `== SDL_VERSION`、openapi 仍 1.3.0）；
**0010** 不许伪造 `character_id`；**0011** 两个标签开关各有生效域（链上 `label-toggles` 步骤）；
**0012** 构图门 ＋ 断言卫生（`check_assertions.py` [OK] 272 文件）；**0013** 理论必须他人著作（现行自撰 0 张）；
**0014** 不替换自研超边索引、L3 走适配器接缝 —— **全部与当前事实一致**。
⇒ **ADR 0007–0015 里只有 0015 有漂移（通道身份），已修**。

**边界**：只核了各 ADR 的**背景与决策陈述**（~130 行），**没逐条核它们引用的 `文件:行号`**；
`docs/evidence/*/README.md`（约几十份）**仍未对**——那类按本仓惯例是"某一刻的记录"，
过期属正常；真正危险的是像 `DECISION_BRIEF_RK13.md` 那样**断言当前状态**的文档，那一份早前已换代。

### P14-281：包线能不能到"四五万字符"？——**实测说不**；但"一刀切 3,000"确实错了（已改成按通道）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **包线** | 用户问"能不能加到四五万／或者自适应" | **绿（按通道 ＋ 实测验证）** | `docs/evidence/20261006-prompt-budget/` | 2026-10-06 | 本批 |

**先答"能不能"**：实测的**可用点**是 **5,309 B**（6 分钟返回正文），**死亡点**是 **17.5 KB**
（64 分钟零输出；~6k token 的包同样 64 分钟无输出）。⇒ **40–50 KB 是死亡点的 2.3–2.9 倍，
没有任何实测支持**；按"生成时间随输入膨胀"的规律只会更糟。**不能靠改常数拿到它。**

**但"一刀切 3,000"确实是错的**：那 3,000 是 **GLM-5.3** 那一档的安全区，却被套到所有通道上，
于是中转站白扔了实测余量（先前那次"压到 2,016 字符"就是这个错配逼出来的）。已改为：

```python
DEFAULT_MAX_PROMPT_CHARS_BY_PROVIDER = {"glm": 3000, "relay": 6000}
```

`--max-prompt-chars` **不填 = 按通道自动**（relay 6000 ／ glm 3000），显式给数仍覆盖，`0` 仍是"不限"。
中转站取 6000：比实测可用的 5,309 B 留余量，离实测死亡的 17.5 KB 有 **2.9×** 安全距离。

**实测验证（不是"参数传对了"）**：同一个 9,046 字符的包 —— `--provider relay`（不填）拒绝并写明
**超过预算 6000**；`--provider glm`（不填）拒绝并写明**超过预算 3000**。守门
`tests/test_plan_writer.py::test_the_prompt_budget_is_per_channel_and_grounded_in_measurements`；
全量 **2381 passed / 1 skipped**。

**"自适应"现在到哪一步**：预算**按通道**（已做）；**要往上抬的唯一正当办法是实测包线扫描**
（6/9/12/15 KB 各发一次，钉在最大的实测可用点）——**本轮没做**（通道上正跑两个任务），**可随时做**；
**不做**的是"超预算静默截断"（会悄悄丢内容，是降级）。

**未验证**：预算比的是**用户消息**（可变包），不含 ~5 KB 的工具契约常量；正在跑的重规划包
用户消息 ≤6,000、全文 8,064，落在 **5.3–17.5 KB 的未测带**上——它能不能按时返回本身是一次抽样。

### P14-282：GPT-6A"写计划"**实测失败**——它回了 524 字符的**行动旁白**，没写计划（根因已定位并修）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **计划** | 用 GPT-6A 重新规划下一步执行计划 | **缺陷（根因已定位＋已修，修复未实测）** | `docs/evidence/20261006-plan-writer-narration/`（原件 ＋ 根因 ＋ 修法） | 2026-10-06 | 本批 |

**那次真跑没有产出计划**：`work/_plan_replan/plan.md`（1,332 B）是模型的**行动旁白**——
「…**我正在调用只读检查命令**；如果当前会话**没有暴露终端工具**…」；
`plan.usage.json`：`elapsed_s = **903.5**`、`finish_reason = stop`、`usage = {}`；
`plan.round{1..5}.md` **不存在**；`work/_replan.out` 只有第 0 轮一行 ＋ `exit=-1`，`stderr` 空。

**根因**：发出去的 system 是**写作契约全文**（~5 KB），而那份契约的措辞是"先全量检索 → 逐行核对 →
留证 → 写 `文件:行号`"——**它是对着"一个能动手的执行者"写的**。模型于是把**指令演成了动作**：
整轮都在描述"我将要做什么"。**903 s 的推理全花在这上面。**

**修法**：`tools/plan_writer.py` 新增 `NO_TOOLS_NOTICE`，**拼在起草与精炼两侧 system 的最前面**
（"你没有工具…不要写旁白…看不到的写『材料未覆盖』"）。守门
`tests/test_plan_writer.py::test_the_system_prompt_says_the_model_has_no_tools`；
`tests/test_plan_writer.py` **15 passed**。**判据一个字没动**（改的是"怎么把话说给模型听"）。

**未验证**：① **修完没有再跑真实的"写计划"**（通道上有两个长任务，再叠并发会污染包线观测）
⇒ "这句提示词真能让它写出计划"**尚未实测**；② **`exit=-1` 的原因没定位**（`stderr` 空、
只落第 0 轮、没打到 provenance 那一行，工具里能走到非零退出的路径都对不上）——如实记**未定位**；
③ 同形风险还在 `work/_gpt6a_ask.py` 与 `tools/relay_adaptive.py` 的角色提示里，**本轮没一并改**。

### P14-283：**勘误**——新包络的"最坏多久"我报小了一倍（45 → **90 分钟**）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **包络** | `attempt_timeout` 之后最坏要等多久 | **勘误（口径，不改代码）** | `docs/evidence/20261006-gpt6a-silent-hang/README.md` 第七节 | 2026-10-06 | 本批 |

我先前写"按新包络最坏约 **45 分钟**必有结果或明确失败"——**错了**。对回源码：
`RelayClient.chat()`（`tools/kb_fetch/llm.py:603-617`）一次调用里**先走流式**（每次读超时＝
`attempt_timeout`），**失败后还会退回非流式 `_post`（同一个超时）** ⇒ **一次 `chat` 最坏 ≈ 2×**；
而 `relay_consult.consult` 又**重试 3 次** ⇒ 最坏 ＝ **3 × (900＋900) ≈ 5400 s = 90 分钟**。

**可观测迹象**：那条裁定请求到 **46 分钟**还在跑——**在 90 分钟包络之内**，不是"没生效"，
是我把包络说小了一半。**只改口径不改代码**；要收紧就把 `attempt_timeout` 调小（300 s ⇒ 最坏 ~30 分钟），
但那会同时缩短"合法长生成"的耐心——同一个旋钮，按需取舍。

### P14-284：**GPT-6A 的 RK-13 裁定到手**——维持红线、转向"三元组选择器"、**不另立协议版本**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| **R3** | 那条红线怎么收口（由 GPT-6A 裁定） | **绿（裁定已下，含可证伪判据）** | `docs/evidence/20261006-rk13-ruling/`（逐字原件 ＋ usage ＋ 口径更新） | 2026-10-06 | 本批 |

21:41:33 落地，`elapsed_s = 2900.0`（48 分钟）。**裁定原文要点**：

* **维持 E1 ≥ 0.70**；当前仍为 `measured / fail`。**不另立 E1 测量协议版本**，只更新**选择器版本、
  运行编号与证据**。⇒ **C（改测量定义）被明确否掉**。
* **转向"整组三条联合打分"的选择器**：沿用每查询 20 组三元组的生成办法，**预测每组的相关条数**再选一组；
  训练/调参数据**另取查询、与这 64 条隔离**；**oracle 只能用于诊断**、不许当"按查询查答案的选择器"。
* **这 64 条已用于探索** ⇒ 后续成绩只能叫**固定集回归验收**，**不是新留出集**。
* 冻结实现/模型/参数后**预先指定一次正式验收运行**：完整跑 64 条、**评分前封存交付的三条**、
  再由**同两位评委按原 C=3 语境**评分；**需要这次完整重跑**，但不必无改动反复刷分。
* **可证伪判据：≥ 135/192 = 0.703125 才通过；≤134/192 继续红；不得跨运行拼接最好结果。**

⇒ **把 A／C 那个二选一改掉了**：不是 A（承认到不了就收摊），也不是 C（改尺子），
而是"**维持红线 ＋ 造选择器 ＋ 预先登记一次正式跑**"。

**这次真跑顺带把通道的两件事实测了**（`usage.attempts` 逐字）：
① **`attempt_timeout` 真的生效**——第 1 次尝试在 **928.9 s** 被掐（正是我设计并被本地静默服务验过的行为，
现在**在真实通道被同一份日志复现**），第 3 次尝试成功返回；
② 总 `elapsed_s = 2900.0`，与 P14-283 的"最坏按 90 分钟报"一致。

**未验证**：① 裁定**只有第 1 问**（原件在"研究重排器的 0.44"处被截断，`finish_reason=stop`），
第 2/3 问**未答**——已按"只问两问"重发（`work/_q_gpt6a_decide23.md`），**结果未知**；
② 那个选择器**没实现、也没验证过能否到 135/192**——裁定给的是方向＋预先登记＋判据，不是成绩；
③ 训练/调参要的**"另取查询"数据集本轮没准备**（而裁定恰恰说这 64 条不能再当留出集）；
④ `HTTP 524` 那次为何耗时 2281.6 s（而非 ~100 s）**没查**。

### P14-285：HEAD 终于被**一条完整 32 步链**覆盖——树守卫 `stable=true`，唯一红仍是 RK-13/E1

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| 验收 | HEAD `c328e91` 上跑满 32/32 | **绿（覆盖）＋1 红（RK-13＝E1）** | `docs/evidence/20261006-220213/tree.json`（`head=c328e914…`、`digest_before == digest_after`、`stable=true`）；同目录 11 份产物 | 2026-10-06 | 本批 |

* `python -m pytest -o addopts="" -q` → **2388 passed, 1 skipped**（205.10 s）。
* 链：32 个 check **全 `OK`**；`held-out coverage gates: all passed`；
  `authorship: every generated card comes from an external work`；
  `RK-13 measured from the held-out (exit 0)` 但**判红** ⇒ `not passing: E1; not measured: E2=not_measured`，
  `chain exit=1`。
* **这不是新红**：红的仍是此前就挂着的那一格 E1（认证版读数 **0.1771 < 0.70**），
  **判据/分母/阈值一个字没动**；链的结论原话就是 "the criteria were not lowered"。
* 与 19:55 那次（`20261006-195300`）的差别：这次 HEAD 把 P14-257…284 全部提交一起覆盖了，
  而 19:55 之后**没有任何证据目录**——那份缺口由本条补上。

**未验证／边界**：① 本链**不量 E2**（结构性 `not_measured`，manifest 不记知识来源）；
② 链里那份 30 条 `edge_spotcheck.jsonl` 的判词格**依旧空白**（那是人填的，脚本拒绝预填）；
③ **门⑦ 的校口径**：`reviewer calibers (D12): accepted-class reviewed 210 = llm-panel 210 +
  third-party 0 + human-only 0`——**third-party 这一格是 0**，因为那 212 条代裁产物
  **还没并进夹具**（换夹具会让 20 份已入库运行整文件 sha 全 STALE）。

### P14-286：**特征信号探针：负结果**——"像元数据"的那些特征解释不了命中条数（三份草案同时入库）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| R3 | 选择器**动手前**先问："手里这些不看判分的特征有没有解释力" | **绿（负结果，可复算）** | `docs/knowledge/E1_LEVERS_v1.md` §1；脚本 `work/_probe_feature_signal.py` | 2026-10-06 | 本批 |

* 用 **192 条未见查询**（`docs/evidence/20261006-unseen192/reviews.unseen192.norerank.jsonl`，
  `judge_batch=3`）算"去标签特征 ↔ 命中条数"的相关：
  `hits` 分布 `{0:111, 1:61, 2:20, 3:0}`（均值 /3 ＝ **0.1754**，与链上现役 **0.1771** 同量级
  ⇒ 口径互证）；**最强的 `mean_clue_len` 只有 r=0.1333**，其余 |r| ≤ 0.08。
* **怎么读（不许读过头）**：它证伪的是"**跨查询**预测命中条数"，**没有**证伪裁定要的
  "**同查询内**给 20 组排序"——这 192 条**每条只有 1 组**，组间方差没被采到。
  真正的 go/no-go 要等去标签池（每查询 20 组）的读数。
* 同批入库三份：`docs/knowledge/SELECTOR_PIPELINE_v1.md`（步骤 0-5 流水线）、
  `docs/knowledge/RULING_CHECK_RK13.md`（对裁定的逐条核对）、
  `docs/knowledge/E1_LEVERS_v1.md`（三根杠杆＋**预登记决策规则**：
  去标签池 oracle **< 135/192 就带实测回 GPT-6A**，≥135 才走选择器）。

**未验证**：① 三个探针脚本**仍在 `work/`**（未入库）⇒ §1 那张表目前**不能从库里复算**，
 提升进 `tools/knowledge/` 是紧随其后的待办；② 去标签池 64 条的 oracle **尚无读数**；
 ③ "云端嵌入重排"（`docs/knowledge/OPEN_PROBLEMS.md` P3）**没试**——它天然不看判分，
 是候选池侧的合法杠杆。

### P14-287：**步骤 0 落地**——三元组搜索器把"判过的每一个三元组"落盘（第二十二次重新冻结）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| R3 | 让"整组三条联合打分"的选择器**有评估集可用** | **绿（先红后绿，离线）** | `tools/knowledge/e1_triple_search.py`＋`tests/test_e1_triple_search.py`（新增 3 条）＋`tests/plan_v4_instruments.sha256.json`（第二十二次冻结） | 2026-10-06 | 本批 |

**改了什么（只增不改）**：`search()` 的产物除原有 6 个键外新增
`triples[]`（`{query, triple[3], values[3], hits}`，顺序＝`jobs` 枚举序）与
`pools{}`（每条查询当时的候选池，**按检索名次**）；
`candidate_triples()` 里原本内联的那三行排序**提成** `candidate_pool()` 给两处共用
（`candidate_triples()` 的枚举序、`E1_best_of_search`／`three_of_three`／`distribution`／
`best_per_query` 的算法逐字未动；`judge_triple()` 未动）。

**证据归属（不许混）**：这三条新守门是**子 agent 写的**，"先红"（实现前 `KeyError: 'triples'`）
是它的报告、**主线没有复演那一步**；主线**实测**的是实现后
`python -m pytest -o addopts="" -q tests/test_e1_triple_search.py tests/test_plan_v4_instruments_frozen.py`
⇒ **`18 passed in 0.21s`**（8 条工具守门 ＋ 10 条冻结守门）。已按该读数改写（子 agent 报的
"20 passed"与主线的 18 对不上，以主线实测为准）。第三条守门钉的是"每条查询 C(5,3)=10、
截断到 5 ⇒ 2×5=10 个三元组**逐个**都要在产物里"，第二条钉"只有一位评委 ⇒ `values` 全 `None`、
`hits=0`（P14-249 口径）"，第一条钉"同输入两次运行逐条同序同值"。

**为什么要它**：上一版 `full_search.json` 把 1,280 个被判三元组只落盘了 64 个
（`best_per_query`）⇒ 选择器**无法被评分**（回答不了"它挑的那组比最好那组差多少"），
而重判一轮是 **1h50m**。这条把"实验过程"变成可复算的产物。

**判据一个字没动**：相关阈值 4.0、两位评委取均值、分母与判分语境仍与 `e1_panel` 同源；
新增字段只被**写入**，不参与任何计算或筛选。第二十二次重新冻结的理由已写进
`tests/plan_v4_instruments.sha256.json::_reason_22`（含"先改完、先跑守门、再冻结、
最后才重跑"的顺序纪律，照 `_reason_21` 的教训）。

**未验证／边界**：① 重跑那 1,280 次判分**尚未开始**（本节只落"仪器＋守门＋冻结"）；
② 去标签池（每查询 20 组）的 64 条**仍无读数** ⇒ 135/192 这个门槛是否建立在标签池上
**仍未被量**；③ 选择器要的"检索名次/检索分数、逐人评委分、`judge_batch` 语境、标签池标识"
四项是否够用，正在由审核侧逐条对拍（缺项会单列成下一批的补丁）。

### P14-288：**去标签池的第一份实测**——oracle **0.375**、3/3 **零个**（判据门槛 135/192 的证据基础被当场动摇）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| R3 | 门槛 135/192 的**依据**（"oracle 约 143/192"）用的是哪个池子 | **绿（实测；结论对裁定不利，如实报）** | `work/_labelfree_pool.out`（8 条查询、池深 6）：`{"queries":8,"triples":160,"labelfree_oracle":0.375,"three_of_three":0,"delivered_first_triple":0.125}`；仪器 `tools/knowledge/e1_labelfree_pool.py`＋`tests/test_e1_labelfree_pool.py`（7 passed）；第二十三次冻结 | 2026-10-06 | 本批 |

**做了什么**：写了一把**新的尺子**——池子**只取产品检索器的原始名次**
（`index.retrieve(query, top_k=6)`，不读任何判分字段），三元组＝池子的全组合 C(6,3)=20 组，
判分**复用** `e1_triple_search.judge_triple`（同 SYSTEM、同两位评委、同 C=3 语境、
P14-249 的"少一位评委不发分"），**每一个判过的三元组都连同 `pool_rank` 落盘**。

**为什么必须量它**：`docs/knowledge/RULING_CHECK_RK13.md` ② 指出，裁定那条
"≥135/192（依据 oracle 约 143/192）"**用的是标签池的上界**（0.7448），
而裁定同时**禁止选择器看判分** ⇒ 选择器只能用去标签池。**去标签池的 oracle 之前没人量过。**

**首跑读数（8 条查询，池深 6，160 个三元组）**：

| 池子 | oracle（每组取最好） | 3/3 组数 | 不做选择（检索前 3 条） |
|---|---|---|---|
| **按标签**取 top-6 再全组合（旧） | **0.7448**（64 条） | 49/1,280 组 | — |
| **去标签**（检索名次 top-6，本批） | **0.375**（8 条） | **0/160 组** | **0.125** |

⇒ **同一批语料、同一把判分尺子，只把"池子怎么来"从标签换成检索名次，上界从 0.7448 掉到 0.375**，
而这 8 条里**一个 3/3 组都不存在**。**门槛 135/192 = 0.703125 高于这个池子的上界** ⇒
**"造个选择器就能过线"目前没有证据基础**（n=8、且是文件序前 8 条，**样本小、未分层**，
不能当终值）。按 `docs/knowledge/E1_LEVERS_v1.md` §3 的**预登记决策规则**：
去标签池 oracle **< 135/192 ⇒ 带实测回 GPT-6A**（它是裁定人，主线不自行改门槛）。

**已经启动**：64 条全量（池深 6、6 workers，`work/_labelfree_pool64.jsonl`，约 2h）——
**它才是那个决策该用的数**；本条那 8 条只是**先声**。

**未验证／边界**：① 8 条是**文件序前 8 条**，不是分层样本 ⇒ 0.375 是**方向**不是终值；
② 这次读数由 `work/_probe_labelfree_pool.py`（未入库的原型）产出，**入库的
`tools/knowledge/e1_labelfree_pool.py` 与它逐条同逻辑、但那份原型产物还不是"用入库仪器复算过"的**——
64 条落地后要用入库仪器再跑一次抽查并对比（**没做，如实挂**）；
③ "更好的去标签池"（`docs/knowledge/OPEN_PROBLEMS.md` P3 的云端嵌入重排）**没试**：
它天然不看判分，是这条上界的**唯一正向杠杆**；④ 池深只试了 6（=产品交付形状），
更深池子的"去标签 oracle"**没量**。

### P14-289：**通道可用性实测**——GPT-6A 能出正文但慢且脆；GLM-5.3 同一份包 5 分钟就回来了（用户："如果现在还是用不了 gpt6A，就改用 glm5.3 吧"）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| — | 用户问的"换不换通道"必须由**实测**回答，不许猜 | **绿（四条实测，方向已定）** | `docs/evidence/20261006-channel-fallback/`（`README.md` ＋ `glm53.answer.json`／`glm53.usage.json`／`glm53.failed.json`）＋ `tests/test_glm_consult.py`（新增 3）＋ `tests/test_panel_consult.py`（新增 2） | 2026-10-06 | `5f26314` |

**四条实测（都不是推断）**：① GPT-6A 的 RK-13 裁定**成功但被截断**（467 字符、第 2/3 问没答；
总 `elapsed_s=2900.0`＝48 分钟，前两次分别被掐在 **928.9 s**／**2281.6 s**）；
② **直接喂大包**（74,565 字符）**50 分钟零输出**——25 s 采样读字节 0／CPU 0，进程卡在 socket 读上；
③ GLM-5.3 同一份两问包在 `--level max` 下 **900.1 s 零字节超时**，且 `attempts` 里**只有 max 一档**；
④ **同一份包、同一组参数重跑** ⇒ **275.6 s 成功**（`completion_tokens=21068`，其中 reasoning **18615**，正文完整）。

**要读准**：③ 与 ④ 是同包同参数 ⇒ 900.1 s 不是"`max` 档不可用"的**确定性性质**而是**抖动**
⇒ 正确处置是**重试／降档**，不是"换模型"。而 ② 说明**"直接喂大包"这条路实测是负面的**
（且 `attempt_timeout=900` **这次没有按时掐断**，与 `…-gpt6a-silent-hang` 的设计行为不一致，**根因未查**）。

**落地（判据一个字没动，只动"谁来想"与"换档要不要继续"）**：
① `tools/glm_consult.py` 新增 `why_not_step_down()`——**同模型换档换不来额度 ⇒ 只有额度类才停手**
（`429`／`1113`／余额／资源包／quota／rate limit／insufficient／suspended），
**传输类（超时、断连、空正文）继续降档**并在 `attempts` 里留 `stepped_down_to`，停手则留 `step_down_refused`；
② `tools/panel_consult.py::relay_caller()`——relay 三次重试全废后**自动改走 GLM-5.3**（守 `max→high→low`），
判词 usage 里逐字写 `fallback_from`；`except (Exception, SystemExit)`（本仓通道用 `SystemExit` 报错，
只接 `Exception` 会让回退形同虚设）；**没配回退型号时失败照旧上报**（"一侧缺席永远不算同意"）。

**顺带闭合的一格**：④ 的成功同时给出了那两问的**完整裁定**——问题一选 **② 圆角方体**
（`max_delta=0.0` 只证明同外接盒、不证明形状等价 ⇒ 尺寸常量不动，只需换构造 ＋ 新增圆角半径常量；
风险是身体构造**之外**若还有代码直接引用圆柱半径会静默错位）；问题二选 **③ 先诊断、不设门**
（`R001–R019` 没有一条要求校验超边执行，设门＝用实现反向发明规范；66 条全来自 `axis_side` 这条
绑不到成片字段的边 ⇒ 先做 `shot_size`＋`movement`，未映射 kind 默认"不适用"并单独计数）。
GPT-6A 侧对这两问**至今没有正文**（pid 40360，21:46:54 起 30 分钟以上零输出）⇒ 按用户指示**这一格归 GLM-5.3**。

**编号说明（如实记）**：本节的提交 `5f26314` 的 subject 里写的是 `P14-288`，与同一批另一个提交
`0f7014f`（去标签池首测，也是 `feat(P14-288)`）**撞号**；内容以 `0f7014f` 与本节正文为准，编号以本节 `P14-289` 为准。

**未验证／边界**：① **`attempt_timeout` 为什么这次没在 900 s 处掐断**根因未查；
② `HTTP 524` 那次为什么耗时 2281.6 s 未查（沿用 `…-rk13-ruling` 的挂账）；
③ **大包直喂没有终局**（进程仍在，既没成功也没报错）；
④ **GLM 侧只重跑了一次**（n=1 vs n=1）⇒ 差别有实测支持，但**抖动频率没量**；
⑤ 本节**尚未据此改代码**——圆角方体要连带查"圆柱半径的外部引用"，落在下一批。

### P14-290：**去标签池 64 条首跑是"仪器坏了"，不是读数**——子进程缺 `GLM_API_KEY` ⇒ 1,280 行全 None、四分钟"跑完"

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| R3 | 长跑的产物**必须是读数**（不是"没判到"被读成 0 分） | **绿（根因已定位、守卫补齐、重跑已起）** | `work\_labelfree_pool64.KEYMISSING.jsonl`（1,280 行全 `values:[null,null,null]`，4 分钟产出 1.0 MB）／`.out`（`labelfree_oracle 0.0`）；`work\_smoke_labelfree1.jsonl`（补上 key 后单条查询：`unscored 0`、`oracle 0.6667`）；重跑 pid **56660**（22:22:53 起） | 2026-10-06 | 本批 |

**事故经过（P14-288 那 8 条之后我立刻放大了 64 条）**：`Start-Process` 起的子进程
**没有 `GLM_API_KEY`**（它只在我那条 shell 的会话里被临时设过，registry 里有、但没进子进程环境）。
后果：`DeepSeekClient` 正常、`GLMClient` **每次立刻**抛 `LLMError: 缺少 GLM_API_KEY`，
`e1_panel.judge` 按设计记空 ⇒ 1,280 行**全是"没判到"**，而汇总行写着
**`labelfree_oracle 0.0`** —— 一个**看起来像"上界归零"的灾难性读数、其实是仪器坏了**的数。

**我为什么没把它当结论**：① 4 分钟跑完 2,560 次判分**物理上不可能**；
② 行内 `values` 全是 `null`（P14-249 的体裁是"少一位评委不发分"，不该全空）；
③ 直接单点复现：`e1_panel.judge` 对 `glm-5.3` 抛的就是 `缺少 GLM_API_KEY`。
**没有**把这个 0.0 写进任何结论。

**补的守卫（判据一个字没动）**：① 产物新增 `unscored_rows`，并加
`instrument_looks_broken()` —— **`unscored_rows == triples_judged` ⇒ CLI 打具名原因并非零退出**
（产物照落盘，供取证）；② 汇总里那个 `three_of_three` **改名**成 `perfect_groups`（组数）＋
`queries_with_a_perfect_group`（查询条数）——`e1_triple_search.py` 有**同名键**数的是"组"，
同名两量纲正是本仓明令禁止的引用方式；③ 第二十四次重新冻结（`_reason_24` 写清两处理由）。

**测试**：`tests/test_e1_labelfree_pool.py` **10 passed**（含"全 None ⇒ 非零退出"与"部分未判到 ⇒
不算仪器坏"两条新守门；全套 `python -m pytest -o addopts="" -q` ⇒ **2404 passed, 1 skipped**）。

**未验证／边界**：① **64 条重跑还没跑完**（22:22 起，按单条实测推约 1.5h）⇒
P14-288 那 8 条的 0.375 仍是**唯一**的去标签池读数；② **前置校验没做**：
脚本仍然不会在开跑前先探一次两位评委是否可用（这次只靠"事后守卫"兜住），
**下一个长跑要补**；③ 别的 runner（`e1_panel.py` 那条链）是否也会因缺 key 静默产出全空行，
**没查**。

### P14-291：把 P14-290 的坑**前置**堵住——开跑前先握手（`e1_panel.preflight`，第二十五次重新冻结）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| R3 | 长跑开始前先确认"评委在不在" | **绿（工具＋守门＋冻结；两条长跑都已接上）** | `tools/knowledge/e1_panel.py::preflight`；`tests/test_e1_judge_preflight.py`（6 条）；第二十五次冻结 | 2026-10-06 | 本批 |

**做法**：开跑前拿**同一个 `judge()`** 走一次小自检（自检案例 id 都是 `preflight_` 前缀，
**不可能**与真案例同 id ⇒ 自检永远混不进任何分母）。任何一位评委抛错、或**回了包但分不出来**
（空正文），就返回**具名**失败；`e1_labelfree_pool.main()` 与 `e1_triple_search.main()`
拿到失败就**拒绝开跑、退出码 3、不产出任何"读数"文件**——后者一轮 1h50m，
更等不起"跑完才发现评委不在"。

**口径一个字没动**：`judge()` 本体未改、阈值 4.0 未动、两位评委取均值与 P14-249 的
"少一位评委不发分"未动、分母未动、红线 0.70 未动；`preflight` 只读一次握手，**不写产物、
不进分母、不参与任何计算**。`--scripted`（离线桩，测试专用）显式跳过握手并在注释里写明理由——
"测试不许碰网络"本身就是判据的一部分，不是放水。

**守门**：抛错的评委被**具名**（错误原文带出来，不许只说"失败"）；空回包也算失败；
两个长跑工具在握手失败时**拒绝开跑且不落文件**。

**三个入口都接上了**：`e1_labelfree_pool.main()`、`e1_triple_search.main()`、
**以及 `e1_panel.main()` 那条 CLI**（它一轮也是一小时以上，本来最容易"跑完才发现评委不在"）。
守门 7 条，含三条"握手失败 ⇒ 拒绝开跑且**不落文件**"。

**未验证／边界**：① 握手是**一次**采样 ⇒ 抖动型故障（P14-289 实测 GLM-5.3 同一份包一次 900 s
零字节超时、重跑 275.6 s 成功）它**挡不住**，只能挡住"确定不在"这一类——**这是设计上限，不是漏项**；
② 握手本身**会多花每位评委一次调用**（一轮长跑里可忽略，但如实记）；
③ 正在跑的那条 64 条（pid 56660）用的是**早期原型**，**没有**握手——它已跑到一半，
不重启（重启等于扔掉 1.5h）；它的产物仍由 P14-290 那条事后守卫兜（`unscored_rows` 全满 ⇒ 判仪器坏）。

### P14-292：**去标签池的上界曲线**——深 6 只有 0.31～0.38（门槛 0.703 的一半），云端嵌入原样重排**不改上界**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| R3 | 门槛 135/192 的参照物是**标签池**（选择器不许构造）；**去标签池够不够得着**必须量到底 | **绿（曲线已成，方向不利，如实报）** | `docs/evidence/20261006-pool-depth-ceiling/`（`README.md` ＋ `pool_ceiling.json` ＋ `pool_probe_depth6.json` ＋ 两份探针源码留档） | 2026-10-06 | 本批 |

**做了什么（零判分成本）**：`docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl`
已经是 **64 条 × top-120 的逐案例 C=3 判分**（7,679 行）⇒ **同一批 top-120 里的任何重排，
都可以离线量它的上界**。于是枚举三种池子（检索原序 / 按标签分〔阳性对照〕/ 智谱 `embedding-3`
原样余弦，三种文本面）× 六种深度（3/6/9/12/20/40），每条查询取**命中最多**的那组。

**三个锚点（这把尺子准不准）**：① 交付形状 `retrieval_order@3` = **0.1719**，对链上认证版 E1
**0.1771**，差 **0.005**（逐位吻合 ⇒ 交付形状上它准）；② `retrieval_order@6` = 0.3125，
对 `e1_labelfree_pool.py` 8 条试点 **0.375**；③ `label_top@6` = 0.9531，对 `e1_triple_search.py`
64 条 **0.7448**。②③ 说明"**重新组装的三元组**"会被整组重判抬 ~0.06 / 压 ~0.21
⇒ **方向与量级可信，绝对值不可当真**（本仓纪律：两个量纲不许互换引用）。

**曲线（上界，proxy）**：`retrieval_order` 0.1719(深3) → **0.3125(深6)** → 0.4219(9) → 0.5365(12)
→ 0.6563(20) → 0.8125(40)；`embed3:title+excerpt+zh` 0.1875 → **0.3281(6)** → 0.4635(9) →
0.5312(12) → **0.7031(20)** → 0.8594(40)；`label_top` **任何深度都 ≈0.9531（57/64 条有 3/3 组）**。
⇒ 两个读法：**(a) 深度是主导变量，把 top-120 的排序换掉（原序 → 嵌入余弦）几乎不改上界**
（同深度差 ≤0.06 ⇒ "换更好的重排器"在本表覆盖的两种排序下**没有证据支持**）；
**(b) 门槛贴着标签池那一列**——裁定参照的 143/192 **只在标签池出现**。

**两点线性校准（明确是估计）**：`fresh ≈ 0.375 + (proxy − 0.3125) × 0.577`
⇒ 深 6 的嵌入池 **0.384**、深 20 的检索原序 **0.573**、深 40 的嵌入池 **0.691**、标签池深 40 **0.745**。
**在"去标签 + 近乎完美的选择器"这个最有利假设下，估计值仍落在 0.66～0.69，够不到 0.703125。**

**第二个探针：交付形状的可达工作点**（`delivered_sim.json`，同一批银行标签）。
做法：池子＝检索原序前 N，选择器＝池内按**去标签标量**排序交前 3。
**锚点**：`retrieval_order@3` = **0.1719** 对官方 **0.1771**（差 0.005 ⇒ 交付形状上逐位吻合）。
读数：`retrieval_order` 任何深度都是 0.1719；`embed3:title+excerpt+zh` 深 6 **0.2292**、
深 12 **0.2396**；`prior+embed3(z)`（名次先验＋余弦各半）深 12 **0.2500**（全表最好）；
`clue_len` / `has_clue` ≤0.1562 且随深度掉（**噪声或负**）。
⇒ ① 云端 `embedding-3` 放进**交付位**是**真收益**（+0.06～0.08，相对 +33～45%）——
与 P3 那条「本地 bge 重排是负结果」**不矛盾**（那是 512 维本地模型）；
② **整个简单打分器空间的上沿只有 0.25**，离 0.703 差 0.45；
③ 三张表并起来：**交付位最好的简单选择器 ≈0.25 ／ 已知最好的真重排器 ≈0.44 ／ 去标签池深 6 上界
0.31～0.38 ／ 门槛 0.703（它的参照物 0.7448 只存在于标签池）**。

**承重墙补成全量**：`docs/evidence/20261006-pool-depth-ceiling/bank_order_check.json`
—— "银行文件序前 6 == `CaseIndex.retrieve(query, top_k=6)`" 初版只在**第一条查询**上验过，
本批 64 条**逐条对**：**64/64 完全相等、0 条不符**（`probe_bank_order.py`）。
它保证 `retrieval_order` 那一列真的是"去标签池"，否则 P14-292 整张表都不成立。

**这意味着什么**：问题从"造不造得出那个选择器"变成"**要不要为一个够不着的门槛改池子形状**"
——按 `E1_LEVERS_v1.md` §3 的**预登记决策规则**，这组数**要带回裁定通道**（用户 2026-10-06：
GPT-6A 不可用时改 GLM-5.3），**主线不自行改门槛、不改判据**。

**未验证／边界**：① 整组重判的 64 条**还没落地**（见下条）；② 嵌入只试了"原样余弦"，
"查询改写 / 线索加权 / 混合 BM25"这些重排形状**没试**⇒ 只能说"原样余弦不提升上界"，
不能说"嵌入这条路死了"；③ 银行只覆盖 top-120，更深池子**没量**；④ 两点线性校准是**粗略**的
（若真实曲线在高分端饱和，深 40 那几行可能偏低）⇒ 主结论只依赖**深 6 那一行**（0.31～0.38 ≪ 0.703）；
⑤ **本探针不是冻结仪器**（在 `work/`，未进 `plan_v4_instruments.sha256.json`）——要变成读数得单独一次重新冻结（挂 P14-293）。

### P14-293（**待办，本条只记状态**）：原型那条 64 条长跑**死了且没留产物**；仓库里跑的是仪器那条

* 22:22:53 起的 `work/_probe_labelfree_pool.py --limit 64`（pid **56660**）在 **22:32:36 还活着**
  （CPU 3.80 s），**22:35 已不在**，`work/_labelfree64.out` / `.err` **都是 0 字节**、
  `work/_labelfree_pool64.jsonl` **不存在** ⇒ **既没成功也没报错地没了**（根因未查，与 P14-289①
  "`attempt_timeout` 这次没按时掐断"同属"进程生命周期没人管"这一类）。
* **仍然活着的是仪器那条**：pid **57312**，`tools/knowledge/e1_labelfree_pool.py --queries … --limit 64
  --workers 6 --pool 6 --out work/_labelfree_pool64.jsonl`（22:19:27 起）⇒ **它才是那份读数**。
* **注意**：57312 起于 22:19:27，**早于** P14-291 的握手（22:29）⇒ 它**没有**前置握手；
  而它导入的是**当时的**模块 ⇒ **没有** P14-290 的 `unscored_rows` 守卫。
  ⇒ 它落地后**必须先查** `unscored_rows` 与 `values` 是否全空，**再**决定要不要当读数（不许直接读汇总行）。

### P14-294：**裁决通道静默退出**——`relay_adaptive.py` 漏接 `SystemExit`，一次 70 分钟的裁决请求"人没了、产物 0 字节"

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| R3 | 通道失败必须**留证**（不许"进程没了但没人知道为什么"） | **绿（根因已定位、修复＋守门已落）** | `tools/relay_adaptive.py`（两处 `except` 补 `SystemExit`）＋ `tests/test_relay_adaptive.py` 新增 2 条（含**端到端**：`main()` 在通道全死时仍写 `answer.md`/`calls.json` 并非零退出）；`python -m pytest tests/test_relay_adaptive.py` ⇒ **7 passed**，同族 `panel_consult/glm_consult/plan_writer` ⇒ **53 passed** | 2026-10-06 | 本批 |

**现场**：pid **56348**（`work/_gpt6a_ask.py --question work/_q_big_feed.md`，44 KB 材料一次喂）
21:27:09 起、**21:27 之后什么都没写**，22:34:53 还在、22:37 前后**消失**；
`work/_big_feed.out`/`.log`/`.err` **全是 0 字节**、`work/_big_feed_answer.md` **不存在**。
⇒ 与 P14-289 ② 的"50 分钟零输出"合起来看，这条路线是**双重失败**：喂不动**而且**不留痕。

**根因（可复现的那一半）**：`tools/glm_consult.py:108` 是 `class ConsultFailed(SystemExit)`——
**本仓通道用 `SystemExit` 报"缺 key／没正文"**。`plan_writer.py:258` 与 `panel_consult.py:296/344/356`
**早就**改成 `except (Exception, SystemExit)`（P14-289 那批），而
`tools/relay_adaptive.py` 的**两处**（抽取块 :120、最终答复 :151）**仍只接 `Exception`**
⇒ `ConsultFailed` 直接穿出 `main()`，**`answer.md` / `calls.json` 一个都不写**，
只剩"进程不见了"。`work/_gpt6a_ask.py`（裁决通道在用的那个草稿）**同一形状的洞**，
本批一并补（它不属仓库文件，不入库，只在台账记明）。

**未验证／边界**：① 那条 70 分钟到底是"三次 900 s 上限没生效"还是"服务器间歇吐字节把
每读计时器一直重置"，**根因仍未查**（与 P14-289 ① 同一条挂账）；
② 修复只保证"**失败一定留证**"，不保证"喂得动大包"——大包仍然是负面结果。

### P14-292：**通道改判**——不再默认 GPT-6A，改用 GLM-5.3（代码默认 ＋ hooks 契约同批改）

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| 路由 | 用户改判「不用 gpt6A 了，改用 glm5.3 吧，不然太耗时间了」 | **绿（代码＋契约＋守门三处同源）** | `tools/plan_writer.py::DEFAULT_PROVIDER == "glm"`；`tools/panel_consult.py::DEFAULT_PARTNER == "glm"`＋`build_parser()`；`tests/test_plan_writer.py`／`tests/test_panel_consult.py`；`~/.codex/hooks/model-routing.md` §1b | 2026-10-06 | 本批 |

**改了什么**：① `plan_writer` 默认起草通道 `relay` → **`glm`**（`--provider relay` 仍可显式选）；
② `panel_consult` 默认第二侧 `--partner relay` → **`glm`**，并把解析器抽成 `build_parser()`
好让"默认是谁"能被守门钉住；③ **hooks 契约**同步改判：路由表里"想法生成／难题攻关／人工裁决／写执行计划"
的默认位全部由 GPT-6A 改成 GLM-5.3，插入 §1b「通道改判（2026-10-06，用户原话）」，
并把表里残留的旧引语逐条标成"**同日改判、以改判为准**"（`work/_switch_routing.py`
与 `_switch_routing_pass2.py` 两遍跑，**每处替换都要求命中恰好一次**，否则一个字节不写）。

**为什么（全是实测，不是偏好）**：GPT-6A 能出正文但**慢且脆**——一次裁定 `elapsed_s=2900.0`、
前两次尝试分别被掐在 **928.9 s／2281.6 s**、正文还被截断（467 字符，第二问没答）；
**直接喂 74,565 字符的大包 50 分钟零输出**。对照 GLM-5.3：**同一份两问包 275.6 s 回完整正文**
（reasoning 18,615 token）。那条挂着的"大包直喂"进程（pid 56348，21:27 起）已按本条**停掉**，
它的读数（50 分钟零输出）在停之前已经留证。

**判据一个字没动**：换的是"谁来想"，不是"按什么尺量"。GPT-6A **不是被禁**——
显式 `--partner relay`／`--provider relay` 仍可用，`relay_caller` 的"三次全废自动改走 GLM-5.3"
那条回退也原样保留。

**顺带闭合的一格**：GPT-6A 在 22:34 终于回了那两问（`work/_gpt6a_decide23_answer.md`，
200 字符，2830.8 s）：**① 选② 圆角方体；② 选③ 先诊断、不设门**——
与 GLM-5.3 早先那份裁定（275.6 s）**逐条一致**。两条都已开工（`d1b_body_shape`／`execution_closure` 两条 lane）。

**未验证／边界**：① GLM-5.3 的抖动只测到 n=1 vs n=1（900.1 s 超时 vs 275.6 s 成功），
**频率没量**；② 改判只改了**默认值**，历史计划与判词的溯源里那些 `relay` 字样仍在（不应追溯改写）。

### P14-293：云端嵌入客户端入库 ＋ **去标签池的"嵌入重排"杠杆在 proxy 上被否**

| 阶段 | DoD 条目 | 状态 | 证据 | 日期 | commit |
|---|---|---|---|---|---|
| R3 | `OPEN_PROBLEMS.md` P3：「云端嵌入重排」这个空位值不值得真判 | **绿（proxy 上否掉，省下 1h50m 真判）** | `work/_probe_embed_pool.py`＋`work/_embed_pool64.out`；新入库 `tools/kb_fetch/embedding_cloud.py`＋`tests/test_embedding_cloud.py`（13 passed） | 2026-10-06 | 本批 |

**新入库的能力**：`tools/kb_fetch/embedding_cloud.py`——智谱 `embedding-3` 的**同步**客户端
（端点／模型／2048 维与 `lightrag_service/build_index.py` 一致），**确定性 ＋ 落盘缓存**
（同一 (model, text) 永远同向量，第二次跑零网络调用），缺 key／额度不足／维度不符**一律具名抛错**、
**不许**静默退回别的模型或返回零向量——否则"云端嵌入臂"的读数会被污染成"某个替代品"的读数。

**实测（`work/_embed_pool64.out`，64 条查询、池深 6；**proxy 口径**）**：

| 池子怎么来（都不看判分） | proxy_oracle | 检索第 1 组 | 与"标签 top-6"平均重合条数 |
|---|---|---|---|
| 检索原序 | 0.1562 | 0.1719 | 0.73 / 6 |
| `embed3` 只用英文摘录 | 0.1276 | 0.1198 | 0.75 / 6 |
| `embed3` 摘录＋中文线索 | 0.1380 | 0.1198 | 0.83 / 6 |
| `embed3` 标题＋摘录＋中文线索 | 0.1667 | 0.1875 | 0.92 / 6 |
| （对照）**按标签**取 top-6 | 0.8177 | 0.9531 | 6.0 / 6 |

**怎么读（不许读过头）**：这是 **proxy**——相关＝该案例在**银行**里的分 ≥ 4.0
（`docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl`，
7,679 行逐案例 C=3 判分），它**不是**冻结仪器、**不许**与 `e1_triple_search` 的 0.7448 互换引用；
本探针自己的用法说明就是"**只看方向**：嵌入重排有没有把池子推向标签池？没有就该如实否掉这条杠杆，
有才值得花 1h50m 去真判"。

⇒ **方向是"没有"**：最好的一面（标题＋摘录＋线索）比检索原序只高 **+0.0105**（0.1667 vs 0.1562），
而离标签池的 0.8177 差一个量级。**D3 那条"换云端嵌入器 E1 提高约 5.6 倍"是在 LightRAG 路由上量的，
在"重排位"上不成立**——这条杠杆**按 proxy 否掉**，不必再花真判分。

**未验证／边界**：① proxy ≠ 盲评 ⇒ 否掉的是"值得花 1h50m 真判"这件事，不是"云端嵌入无用"；
② 新客户端**还没接进** `e1_panel --cases-rerank embedding` 的云端档（现在只被自己的守门与探针用到）——
**这是待办**；③ 缓存 `work/_embed3_cache.jsonl` 是 57 MB 的**可重建中间产物**，故意不进库。
