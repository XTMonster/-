# P9 阻塞缺陷的联合会诊（DeepSeek × GLM-5.3）

日期 2026-10-05。判词归属 `reviewed_by: llm-panel`（**不是 human**）。

## 为什么有这一份

计划 v4 的 P9 要出 hybrid/lexical/lightrag 三臂的 E1 成对读数。2026-10-05 15:28 的
「对齐」跑（`work/_run_ab3.ps1` → `work/ab_v4_aligned/`）三臂全部塌到 ~0
（hybrid 1/153、lexical 2/192、lightrag 0/137），而用发货案例集跑出的 hybrid 是
40/192 = 0.2083。定位到**两个互相独立的缺陷**，按《模型分工契约》走难题攻关会诊。

## 被判的两个缺陷

| # | 缺陷 | 证据 |
|---|---|---|
| **A** | v4 案例层（`work/knowledge_v4_cases/cases/`）**没有中文检索线索** `search_zh.part-*.jsonl`，`read_search_zh` 返回 `search_zh_missing`；BM25 文档只剩英文 `excerpt`，中文散文查询近 0 命中 | `block_director/knowledge/cases.py` 的 `read_search_zh` / `CaseIndex._text` |
| **B** | sidecar 的 `LightRAGIndex.search()` 每次调用 `asyncio.run()`（每次新建事件循环），而 `self._rag` 跨调用复用 —— 异步原语绑定在第一条循环上 | `work/_sidecar4.err`：5771 行 `ERROR: Embedding func: ... is bound to a different event loop`，另 `ERROR: Query failed: __aenter__` ×4 |

## 会诊包（可复算）

* 题目：`work/_q_p9.md`；源码逐字带行号：`tools/lightrag_service/build_index.py:288-331`、
  `block_director/knowledge/cases.py:340-420`；产物：`work/ab_v4_aligned/two_denominators.json`。
* 两侧各自落 `<role>.{glm,deepseek}.json` 与 `<role>.{glm,deepseek}.usage.json`；
  主线程（DeepSeek）以 `--main-answer work/_main_p9.json` 入场，不再走 API。
* 第一次用 `--level low --max-tokens 32768`：GLM `finish_reason=length`、
  32659/32768 全烧在 reasoning、正文为空 ⇒ **判这一次不完整**（按纪律重跑，不读成同意）。
  第二次 `--level high --max-tokens 65536`：两侧 `ok`，`complete=true`。

## usage（真实读数）

| 角色 | 模型 | 档位 | max_tokens | 耗时 | completion | reasoning | prompt | finish |
|---|---|---|---|---|---|---|---|---|
| 实现顾问 | glm-5.3 | high | 65536 | 623.2 s | 40643 | 33156 | 5459 | stop |
| 性能与鲁棒 | glm-5.3 | high | 65536 | 534.5 s | 34838 | 28844 | 5468 | stop |
| 两侧 | main-thread(deepseek) | — | — | — | — | — | — | `main-answer` |

## 结论（四栏）

两个角色各跑一次，四栏计数都是 `both=0 / severity_conflict=0`，
`glm_only` 分别 7 与 5、`deepseek_only` 分别 5 与 2。

**两侧独立指到同两条 blocker**（措辞不同、配对算法未判为「同一件事」，故没落进 `both` 栏，
但内容一致）：缺陷 A 使 hybrid/lexical 的读数来自一台坏仪器；缺陷 B 使 lightrag 臂度量的是
「服务崩了」而不是检索质量。

**GLM-5.3 侧独有的新发现**（DeepSeek 侧未提，值得单列）：

1. **没有「仪器门」消费 `queries_with_no_rows` / `clue_state`** ——
   `two_denominators.json` 如实记了 6 条空查询、5771 行 ERROR，`CaseIndex` 也有
   `cases_clue_state`/`cases_clues` 字段，但**没有任何门把它们升格成「该臂无效」**，
   于是格式完整的三臂数照样出得来。这是 A、B 能以「合法产物」形态存在的共同根因；
   服务侧同时缺熔断（同一类不可自愈错误打了 5771 遍还在继续）。
2. lightrag 失败回退的 BM25 每次失败查询现场重建 783 篇文档的 token 列表（O(N) 性能税）。

**落地形状的分歧（已按主线裁决）**：GLM 两边都主张「同代复用 521 ＋ 现生成 262」，
理由是线索是 `(prompt, model, 原文)` 的纯函数、全量重生成对未变输入引入采样方差；
主线实际落地成**全量重生成**（783 条处理完：542 条出线索、241 条按规则给空串），
因为三臂在**同一代 v4 线索**上比较，臂间差值不因此产生混淆。该分歧与代价如实记在此。

**不变量**：会诊不改判据／门限／阈值。上面第 1 条若要变成机器门，属于新的判据，
须单列 `待裁决`（见 `docs/knowledge/ADJUDICATIONS_v4.md`）。

## 文件

* `panel.md` / `panel.json` —— 人读与机读的会诊纪要（含四栏配对）
* `<role>.glm.json` / `<role>.deepseek.json` —— 两侧逐字判词
* `<role>.<side>.usage.json` —— 逐侧的模型／档位／耗时／token
* `bundle.manifest.json` / `bundle.md` —— 会诊包自己（哪一版、看了什么、逐份 sha256）
