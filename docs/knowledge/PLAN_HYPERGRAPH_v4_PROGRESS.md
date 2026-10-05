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
| **P9** | ①A/B 双报告（三路由 × N 次 ＋ 成对差值 ＋ inconclusive） | **工具绿／读数部分（缺 lightrag）** | **计划里写死的 `e1_report.py` 以前不存在**（`rg` 零命中）——P9① 与 P10 的验收命令都引用它，等于"没有可执行入口"。已补齐：`tools/knowledge/e1_report.py`（编排**冻结仪器** `e1_panel` 的 CLI，判词整份交给 `e1_baseline_summary.paired_report`；噪声带＝各臂同臂极差的最大值，带内一律 `inconclusive`）。<br>本工具另写死两条**前提**（都是本仓实测踩过的坑）：`judge_coverage`＋`all_rounds_complete`（一侧评委缺席不算同意）、`repetition_sufficient`（**1 次重复 ⇒ 噪声带恒 0、`separated` 恒真**，此时 `separation_verdicts_valid=false`）。<br>现有两臂的真数据产物 `work/e1_v4pop_ab.partial.json`：hybrid 0.1875／lexical 0.2083、Δ 0.020833、`noise_band 0.0`（1 次重复）、`all_rounds_complete=false`。**三臂 × 2 次的正式产物待 lightrag 索引建成** | 2026-10-05 | `b11fc21` |
| **P9** | ②E3 双报告（三路由经验越权数） | **工具绿／读数部分（缺 lightrag）** | 同样补上缺失的 `tools/knowledge/e3_report.py`（计划里也是写死命令）。层一级走现役 `quality.e3_cases`（`tools/knowledge/quality.py:617`，含"存在但为空 ⇒ 分母 0 判失败"）；路由一级读 ① 的逐行录档、数**实际召回**里的越权（字段键与线索词表**同源派生**：`tools/kb_fetch/case_search_zh.py:62` 的 `CONSTRAINT_WORDS`）。真数据 `work/e3_v4pop.partial.json`：层 `0/783` pass，hybrid/lexical 召回各 `0` pass | 2026-10-05 | `b11fc21` |
| **P9** | ③PROGRESS 记检查器调用点 ＋ 查询集来源 ＋ 结果表 | 绿 | 调用点：`tools/knowledge/e3_report.py:112`（层一级）、`:97`（字段越权）、`:100`（线索越权）；查询集：`work/eval_sets/heldout_v4_long21.jsonl`（**64 条**，`sha256=e02161be89eef4ab…`，来自真跑 `docs/evidence/20261006-long21/project/project.bdproj` 的逐镜散文；64 × top_k 3 ＝ **192 行/臂**——台账里那个"192 行"就是行数，不是查询数）；结果表见本表 ① ② 两行 | 2026-10-05 | `b11fc21` |
| **P10** | 指针切换与归档 | 待 | — | — | — |
| **P11** | 长跑与收尾 | 待 | — | — | — |

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
| **P9** | 三臂 A/B | **部分**（两臂有读数，lightrag 缺） | 见 `docs/evidence/20261005-p9-clued/`：补线索后 **hybrid 36/192=0.1875、lexical 40/192=0.2083**（补线索前 0.0065／0.0104）；lightrag 臂待索引重建（`work/lightrag_v4_clues_local`，16:26 时 163/783） | 2026-10-05 | 本批 |

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

1. **P1② 是红的**：D1 的书单还没冻结。它的实测底座已经齐（321 条来源清点、
   OCW 188 条候选、arXiv 当晚 0 条），缺的是"把预算从 54 本旧书挪到那 267 条现代来源"
   这一步落到 `sources.yaml`——那是 P3 的第一个动作。
2. **P2②（轮记录文件）** 是 V1 的落地，属于 P2 的剩余项。
3. 数值留白 N1–N5 仍挂着（见 `PLAN_HYPERGRAPH_v4_ANNEX.md` §3），**不影响开工**。
4. **P10 的落地形状有一处必须先解决的偏差（本轮新发现）**：计划 §3.1 写着影子产物
   落在**仓库根**的 `knowledge_v4/`（`git mv` 一次性切成 `knowledge/`，可 `git revert`），
   而 v4 的产物实际落在 **`.gitignore` 掉的 `work/`** 下
   （`work/knowledge_v4` 3.37 MB ＋ `work/knowledge_v4_cases` 8.03 MB，`.gitignore:58` `/work/`）。
   ⇒ P10 的三条动作（`git mv knowledge_v4/...`、`git ls-files knowledge_v4`、
   `Move-Item knowledge_v4/lightrag knowledge/lightrag`）**现在跑不了**：那些文件不在
   git 里，`git mv`/`git ls-files` 无从下手，"单提交完成归档＋切换"这个可回滚形状不成立。
   处置建议（待做）：把 11.4 MB 的产物（edges/cases/manifests）落到**受版本控制**的
   `knowledge_v4/`，再按 P10 走；LightRAG 索引（21.5 MB）体积与现有 `knowledge/` 同级，
   是否入库要单列一条裁决（现役 `knowledge/` 里也没有索引本体，只有它的指纹）。
5. **P10 门的机械口径**：`git grep -n "knowledge_v4" -- tools block_director tests` 现在
   **18 命中**，其中 `tools/`＋`block_director/` **已清零**（本轮把新工具的字面默认值与
   help 文本换成占位符：`tools/knowledge/e1_report.py`、`e3_report.py`、`kb_fetch/build_shadow.py`），
   余下 9 条全在 `tests/`（`tmp_path / "knowledge_v4"` 这类**测试夹具注入**——§3.3 的原文
   本来就允许"或测试夹具注入"）。⇒ 那条门按**字面 grep ＝ 0** 与约束原文自相矛盾，
   落地口径建议改成 `-- tools block_director`（生产代码）＝ 0，并把这条偏差记在这里。
