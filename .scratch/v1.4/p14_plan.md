# P14 执行方案（知识栈：P14-1…P14-5）

依据：`改进执行文档v1.4.md` §2.3 / §2.3b / §2.3c / §2.3d、§3.1–§3.3、§4.1（RK-13）、
§4.1b、§4.2、§4.4、§4.5、§5 的 P14 行、§B.3 的 P14 行。
基线：`06baeed`（P12 切片一），`python -m pytest` → 892 passed。

## 0. 环境事实（实测，非假设）

| 事实 | 命令 / 证据 |
|---|---|
| DeepSeek OpenAI 兼容端点可达（返回 `deepseek-flash`） | `POST https://api.deepseek.com/chat/completions` → 200 |
| 本地 `qwen3-vl:30b`（ollama）在 `127.0.0.1:11434` 可用 | `GET /api/tags` → 1 model |
| `www.gutenberg.org` 可达（PD 文本来源） | `GET /robots.txt` → 200 |
| `en.wikipedia.org` / `archive.org` / `upload.wikimedia.org` 不可达 | 三次 `URLError 10060` |
| PyYAML 6.0.3 只在开发环境；Blender 的 Python **没有** PyYAML | 仓库规则：`block_director/` 只用 stdlib ＋ bpy |

## 1. 交付物与落点（P14-1）

| 落点 | 内容 |
|---|---|
| `knowledge/sources.yaml` | 人工维护的来源清单；字段 `url/title/author/license/domain/mode` ＋ 选填 `note/genre` |
| `knowledge/source_notes/*.md` | **OwnWork** 语料（自撰笔记），补 `lighting/color/camera_angle/editing/anime/storyboard` 的主题配额 |
| `tools/kb_fetch/{fetch,extract_text,dedupe,validate_licenses,chunk,annotate,import_cards}.py` | 七脚本管线，纯 Python、无 bpy |
| `knowledge/cards_generated/<domain>.jsonl` | **运行时**卡片投影（stdlib 可解析，进 `CARDS`） |
| `knowledge/cards_generated/<domain>.yaml` | 同一次运行产出的**人类/审计**副本（计划书字面要求 `*.yaml`） |
| `work/import_report.json` | `cards_candidates / cards_kept / cards_deduped / cards_rejected` ＋ K1–K5 报告 |
| `docs/knowledge/LICENSES.md` | 逐来源的许可与归属声明 |
| `fixtures/knowledge_holdout.jsonl` | ≥1200 条独立标注（换族 annotator） |
| `fixtures/knowledge_holdout.vocab.json` ＋ `fixtures/knowledge_holdout.cards.json` | 门③/门⑥ 的外部输入 |
| `.gitignore` | `work/`（原文快照与抓取缓存）不入库 |

## 2. 关键设计决策（含理由）

1. **一句话一条管线**：`mode: http`（Gutenberg PD）与 `mode: manual`（OwnWork 笔记）走**同一**七步管线，
   只有 `fetch.py` 分叉。理由：许可门、去重、引用块长度门、导入计数必须是同一份实现，否则口径会漂。
2. **双格式卡片**：`import_cards.py` 从同一份内存列表同时写 `.jsonl`（运行时）与 `.yaml`（审计）。
   理由：计划书要求 `cards_generated/*.yaml`，而 `block_director/knowledge/corpus.py` 必须在 Blender 的
   stdlib-only 解释器里加载卡片。两份由**同一次运行、同一个列表**产出，并由测试断言逐字段相等——
   不存在"两处手改"的漂移面。
3. **换族（§2.3c 第 1 条）**：抽取器 = DeepSeek（`family: deepseek`），标注器 = 本地 `qwen3-vl:30b`
   （`family: qwen`）。两者 model_id 不同族 → `independence: strong`。`manifest` 里断言
   `annotator.model_id != extractor.model_id`。
4. **引用块可判定**（§2.3d）：`quote` 单独字段，句数 ≤2（CJK `。！？` ＋ ASCII `.!?`）、总字数 ≤120，
   正文必须是改写。违反者进 `cards_rejected`（不是"警告后仍入库"）。
5. **幂等**：`fetch.py` 按 sha256 缓存；`import_cards.py` 按 `(domain, id)` 与内容 SimHash 去重；
   重跑不产生重复条目。
6. **运行时合并（T8）**：`CARDS = 手写卡 + 生成卡`，按 id 排序，重复 id 以手写卡为准并**报警**
   （`GeneratedCardIdCollision` 收集，测试断言集合为空）。
7. **9 域（T7）**：`DOMAINS` 扩到 9，`DOMAIN_DIGESTS` 同步补 4 条，并加
   `set(DOMAINS) == set(DOMAIN_DIGESTS)` 的显式断言。

## 3. 阶段顺序与验收

| 子阶段 | 内容 | 验收/测试 | commit |
|---|---|---|---|
| P14-1a | 管线骨架（7 脚本 ＋ sources.yaml ＋ LICENSES ＋ .gitignore），先跑通 pilot 子集 | `tests/test_kb_pipeline.py`（许可门、引用块门、去重幂等、chunk 边界、import 四计数） | `feat(P14-1)` |
| P14-1b | 语料落地：OwnWork 笔记 ＋ Gutenberg PD 文本 → 卡片 ≥900、9 域每域 ≥60、主题配额 K5 记账 | `tests/test_kb_corpus.py`（K1–K4 全绿 ＋ 每域计数 ＋ 卡片字段完整性） | `feat(P14-1)` |
| P14-1c | 词表冻结 ＋ held-out ≥1200（换族标注）＋ 六道覆盖门 | `tools/check_holdout.py` 全绿（非 pilot）＋ `tests/test_knowledge_holdout.py` | `feat(P14-1)` |
| P14-2 | 超图 schema ＋ 9 条校验门 ＋ 两段式抽取 ＋ 索引落盘 ＋ manifest 断点续跑 | `tests/test_hypergraph_schema.py`；Q0 构建门 | `feat(P14-2)` |
| P14-3 | L3 案例层（≥300 篇；`lightrag` 默认、`hybrid` 降级、`off` 显式关闭） | `tests/test_cases.py` | `feat(P14-3)` |
| P14-4 | sidecar `/v1/retrieve` 返回 `edges[]`＋`cases[]`；插件消费（原子注入/三栏/`knowledge_trace.json`/预算接线） | `tests/test_knowledge_trace.py`；`tests/test_openapi_matches_contracts.py` | `feat(P14-4)` |
| P14-5 | 质量闭环 Q0–Q7 ＋ E1–E3 ＋ 三元组对照留档 | `tests/test_knowledge_quality.py`；`docs/evidence/<run-id>/` | `feat(P14-5)` |

## 4. 自我审核（查漏，先于动手）

| # | 风险 | 处置 |
|---|---|---|
| 1 | **同族标注**（extractor 与 annotator 同族 → Q1/Q2 退化成自洽性） | 已按第 2.3 条换族；manifest 断言 + 每条 entry 记 `annotator.family` |
| 2 | **人抽查不可由 agent 代替**（§2.3c 第 4 条：Q5/Q7/E3 最终裁定必须人做，人审 10–15% 一致率 ≥90%） | **不伪造**：管线产出 `review` 字段与待裁决清单，把"人审未完成"如实写进交付报告，并作为 P14-5 的**未达标项**上报——不得静默判过 |
| 3 | 语料数量不足导致 Q1/Q2 线（70%/90%）不可达 | 先按 K3（每域 ≥60、占比 ≥5%）把卡片铺开，再按 held-out 门④（每类边 ≥30 条）倒推标注预算；不达标就继续采，不降线 |
| 4 | 9 域扩容会打红既有断言（`len(cards)==len(DOMAINS)`、BM25 排序、"每域都有卡"） | 先加"9 域 ＋ DIGEST 一一对应"的显式断言把它变红，再补数据到绿（红→绿） |
| 5 | 生成卡进 `CARDS` 会让 892 条既有测试里依赖 132 卡的那些变红 | 先跑 `python -m pytest` 取基线，逐条定位；不得改断言规避，只修实现/数据 |
| 6 | `work/` 原文快照入库撑爆仓库 | `.gitignore` 加 `work/`；体积门（单文件 ≤512 KB、总量 ≤20 MB）写成测试 |
| 7 | LLM 生成内容不可控（幻觉、模板化） | 强制 `quote` 必须**逐字来自 chunk**（导入时子串校验），正文必须含可执行规则；模板化由去重门（SimHash）拦截 |
| 8 | 网络不可达导致 http 源全挂 | OwnWork 路径不依赖网络；http 失败明确记 `rejects` 并报错，不用空数据蒙混 |

## 5. 不做的事（红线）

- 不降低任何门限（≥900 / ≥60 / ≥5% / ≥1200 / rejects ≤5% / Q 线）来"让测试通过"。
- 不删除、跳过、弱化既有测试；不改断言以迁就实现。
- 不把"抓不到/标不完"写成通过：`not_measured` 一律单独报告。

## 6. 实施记录（边做边记）

### P14-1a 管线骨架（已落地）

- `tools/kb_fetch/`：`fetch → extract_text → dedupe → validate_licenses → chunk →
  annotate → import_cards` 七脚本 ＋ `common.py` / `llm.py` / `vocabulary.py` /
  `holdout_gen.py` / `build_hypergraph.py`。
- 词表与超边 schema 的**闭集**落在 `block_director/knowledge/hypergraph.py`
  （纯 stdlib，可在 Blender 进程里导入）。
- 运行时的生成卡加载落在 `block_director/knowledge/generated.py`（T8 合并 + 撞 id 报警）。
- `tests/test_kb_pipeline.py`（24 条）、`tests/test_hypergraph_schema.py`（28 条）、
  `tests/test_knowledge_holdout.py`（15 条）全部离线可跑。

### 实测记录（可复算）

| 事项 | 结果 |
|---|---|
| SimHash 误判（按词频加权） | 26 份语料里 79 对被判成"近重复"；改**按词表二进制加权**后降为 0 |
| 均匀取样 vs 关键词取样 | 均匀取样 8 段里 6 段抽不出卡片（老书大半是商业与器材广告）；按域关键词取样后每段都能出卡 |
| 单次标注吞吐 | DeepSeek `temperature=0`：约 3.5–4 s/段，约 2.5–3.5 张卡/段 |
| 单元测试污染真实 `work/` | `validate_licenses.run()` 的单元测试把真实 `licensed.jsonl` 覆盖成 1 条 → 已用 autouse fixture 钉住全部输出路径 |

### P14-1b/P14-2（已落地，commit 50c8a98 / b6cb899）

- 语料：**1075 张卡**（943 生成 ＋ 132 手写），九域 72–196 张，全部 ≥60 且 ≥5%；
  `knowledge/cards_generated/import_report.json` 的 K1/K2/K4 都是 1.0，`passed: true`。
- 超图：**295 节点 / 168 条超边**（658 raw → 473 合并、17 拒收 = 2.6% ≤ 5%，
  `processed == total == 250`）→ 构建门通过，落 `knowledge/hypergraph.{nodes,edges}.jsonl`
  与 `hypergraph.manifest.json`；`fixtures/knowledge_holdout.vocab.json` 冻结了 86 个
  查询取值（14 类，另加 character/object 空占位）。
- 检索冒烟：`Hypergraph.retrieve("情绪=荒诞；动作=跺脚；运镜=固定", top_k=3)` 返回
  3 条**整条**超边（含 `禁=` 成员）。

### 待办（本阶段未完成，不得当作通过）

1. **`fixtures/knowledge_holdout.jsonl` ≥1200 条**：生成器已就绪（`holdout_gen.py`，
   换族 = 本地 qwen3-vl:30b）。**实测该本地模型对本任务的单批（4 张卡）响应超过
   10 分钟**，1200 条需要数小时；本轮没有跑满，因此六道门里只有门①②④⑤可判定，
   门③⑥与门⑦（人审）未判定。工作区里残留的 `fixtures/knowledge_holdout.jsonl`
   是空文件（曾在调试中写过），**不得**当作正式 oracle；正式集必须重新生成。
2. **人抽查 ≥120 条**（协议 §5.5 / 门⑦）：agent 不能代替，必须由人裁决并署名
   `review.reviewed_by = "human"`；这是 RK-13 的前置。
3. P14-3（L3 案例层 ≥300 篇）、P14-4（sidecar `edges[]`/`cases[]` ＋ 插件消费与
   `knowledge_trace.json`）、P14-5（质量闭环 Q0–Q7/E1–E3 ＋ 三元组对照）。
4. 已记录但不隐藏的抽取质量缺口：抽取器偶尔把非镜头节点（`ECU`、`movement:static`）
   塞进 `lens` 槽——门③/⑨ 抓不到（`lens` 没有冻结取值域），Q1/Q2 会抓到。
