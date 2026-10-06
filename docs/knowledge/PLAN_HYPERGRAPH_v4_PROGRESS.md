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
| **P10** | 指针切换与归档 | 待 | — | — | — |
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
