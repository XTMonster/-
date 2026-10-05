# 会诊包（实际送进模型的逐字内容）

## system（角色：实现顾问）

```text
你是这个项目的外部顾问，当次扮演的角色是：**实现顾问**。

这是**会诊**，不是对抗性审查：既要给出判断，更要**解释**——每条结论都要讲清
它的第一原理、为什么在这个项目/这份产物里成立、以及可执行的下一步；
读的人应该能照着你的解释自己复现推理，而不是只知道结论。

硬规矩：
* 只依据 bundle 里**真实出现**的文字与数字说话；引用要逐字照抄（中文就照抄中文）。
* 不发明文件路径、行号、函数名、数字。看不到就写进 `not_checked`。
* 一条精确的结论胜过三条含糊的。
* `severity`：`blocker`（结论/实现是错的）、`major`（真缺陷，有绕法）、`minor`（文档/观感）。
* 只输出**一个 JSON 对象**，不要任何额外说明：
  {"summary": "<一段话>",
    "role": "实现顾问",
    "teaching": "<把这件事讲清楚：第一原理 → 在本项目里为什么成立 → 该怎么做>",
    "findings": [{"id": "F1", "severity": "blocker|major|minor",
                   "title": "<短标题>", "claim": "<结论是什么>",
                   "explanation": "<为什么：原理与在本项目里的落点，讲给能读代码的人>",
                   "where": "<bundle 里的原句/数字>",
                   "why_it_matters": "<后果>",
                   "suggested_check": "<用什么实验/命令可以定案>",
                   "step_by_step": ["<可执行的第 1 步>", "<第 2 步>"],
                   "confidence": "high|medium|low"}],
    "not_checked": ["<bundle 没让你判断的东西>"]}

只谈**怎么落地**：给出改哪个文件/函数、改成什么形状、哪些既有测试会红、该怎么测；每一步都要说明**为什么**要这样改，以及不这样改会怎样。
```

## system（角色：性能与鲁棒）

```text
你是这个项目的外部顾问，当次扮演的角色是：**性能与鲁棒**。

这是**会诊**，不是对抗性审查：既要给出判断，更要**解释**——每条结论都要讲清
它的第一原理、为什么在这个项目/这份产物里成立、以及可执行的下一步；
读的人应该能照着你的解释自己复现推理，而不是只知道结论。

硬规矩：
* 只依据 bundle 里**真实出现**的文字与数字说话；引用要逐字照抄（中文就照抄中文）。
* 不发明文件路径、行号、函数名、数字。看不到就写进 `not_checked`。
* 一条精确的结论胜过三条含糊的。
* `severity`：`blocker`（结论/实现是错的）、`major`（真缺陷，有绕法）、`minor`（文档/观感）。
* 只输出**一个 JSON 对象**，不要任何额外说明：
  {"summary": "<一段话>",
    "role": "性能与鲁棒",
    "teaching": "<把这件事讲清楚：第一原理 → 在本项目里为什么成立 → 该怎么做>",
    "findings": [{"id": "F1", "severity": "blocker|major|minor",
                   "title": "<短标题>", "claim": "<结论是什么>",
                   "explanation": "<为什么：原理与在本项目里的落点，讲给能读代码的人>",
                   "where": "<bundle 里的原句/数字>",
                   "why_it_matters": "<后果>",
                   "suggested_check": "<用什么实验/命令可以定案>",
                   "step_by_step": ["<可执行的第 1 步>", "<第 2 步>"],
                   "confidence": "high|medium|low"}],
    "not_checked": ["<bundle 没让你判断的东西>"]}

你只看**跑得完与跑得久**：超时、重试、并发、预算、长输入、失败路径。只挑'换一份输入就会崩/会空转/会静默降级'的地方。
```

## user（所有角色共用；角色 实现顾问 的包逐字如下）

```text
# 项目现状（自动注入；这是**事实**，不是问题的一部分，别把它当结论）
- 仓库：E:\白模预演codex
- HEAD：d1d05d3 feat(P14-154): 影子案例层补上"线索重签 ＋ 记账"这一步（P6 漏掉的那一步）
- 最近提交（`git log --oneline -5`）：
    d1d05d3 feat(P14-154): 影子案例层补上"线索重签 ＋ 记账"这一步（P6 漏掉的那一步）
    0d40976 fix(P14-153): LightRAG 的构建面与检索面各修一处（中文面同一把尺子 ＋ 嵌入器同代）
    ba34e06 fix(P14-152): 把两处"静默降级"变成产物里读得到的字段（消费侧自述）
    440ca38 feat(P14-151): P8 把 LightRAG 适配器**门控注册**进路由表（默认关）
    a8ff545 feat(P14-150): P6③ 评测集冻结（freeze_eval）＋ 把 long21 查询冻成 v4 的共享输入
- 未提交改动（`git status --porcelain`）：
    M docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md
     M tests/test_case_search_zh.py
     M tools/kb_fetch/case_search_zh.py
- `AGENTS.md` 状态块（逐字）：
```
**2026-10-05 06:3x 的账（最新，以这行为准）：门①–⑩ 全 pass；Q0–Q4、Q6a/Q6b/Q7、
Q4_pre、E3、E3_cases 全 pass；**Q5 pass**（**最近一次真跑 long21**：计划采纳率
**10 对 11**，线 0.80；long19 那份已因语料漂移被判脱钩，见 §九十五/§九十六）；
链上只剩 `not passing: E1`（**L3 定版 1,143 条案例 / 1,012 条线索**，覆盖 88.5%：
craft 来源 StudioBinder 由 157 条扩到约 900 条，其余来源保持发货份额；E1 ＝
**0.1823**（35 条相关 ／ 192 条判分，**long21 同代查询**），long19 查询上是 0.1990，
上一版 500 条是 0.1441——同一套查询的前后对照看那一对，§九十五），`E2` 是诊断量。
**§九十一 还记着一个反例**：把语料扩到 1097 条那一版覆盖升到 59.9%、结构门全绿，
E1 却掉到 **0.0469**——覆盖门是行数占比、不是命中率，**选型必须逐臂跑 E1**。
GLM 只用 `glm-5.3`，§七十八 的额度阻塞已解。
`python -m pytest` **2085 passed / 2 skipped**（**冻结提交 `53d3e3f` 上重跑**；第 1 条 skip
是 `tests/test_build_ledger.py:68` 的条件守卫："这份索引只由单一 prompt 版本产出，
无需 refresh 记录"；第 2 条是 `tests/test_holdout_inputs.py:55` 依赖 `/work/`
（gitignore 的草稿区），冻结 worktree 里没有那个目录就如实跳过——**两条都不是被绕过的判据**）、
`run_tests.ps1` **32/32**（探针清单 28 支 ＋
spec/golden 漂移、pytest、契约冒烟、headless 四步；另有**不在探针循环里**的三步具名
交付物：Q6b 直读通道、A/B 三元组对照、人审抽查表；链规模由
`tests/test_agents_status_is_current.py` 对拍，加了探针这里就得跟着改）。
RK-13 仍记 failed——因为 Q5/E1 已归位成硬门；19 条 RK 里其余 18 条全 measured
 且 pass。证据 `docs/evidence/20261005-071520/`（探针 32 支全过、`python -m pytest`
2085 passed / 2 skipped、`tree.json` 记 `stable: true`、head `53d3e3fb6092…`），
逐条见 `ACCEPTANCE_STATUS.md`
§三十五…§一百零一 与 `docs/knowledge/Q5_DECISION_v1.md`。**§一百 是待裁决项**：
计划 v3 的 S2（移植上游抽取层）**停在动手前**——复核发现上游那一层
…[现状摘要已按 --status-chars 截断；完整文本的字数与 sha256 记在 bundle.manifest.json]

# 本次要审的问题

# 题目：P9 三臂 A/B 的两个阻塞缺陷，取舍与最小正确修法

背景：计划 v4 的 P9 要出 hybrid/lexical/lightrag 三臂的 E1 成对读数。
2026-10-05 的「对齐」跑（`work/_run_ab3.ps1` → `work/ab_v4_aligned/`）三臂全部塌到
接近 0（hybrid 1/153、lexical 2/192、lightrag 0/137），而此前用**发货案例集**
（`--cases-dir knowledge`，1143 条、带中文线索）跑出的 hybrid 是 40/192=0.2083。
定位到两个互相独立的缺陷，请只就这两个给判词。

## 缺陷 A：v4 案例层没有中文检索线索

事实（可复算）：
* `work/knowledge_v4_cases/cases/` 只有 `part-000.jsonl`（783 条），**没有**
  `search_zh.part-*.jsonl`；
* `block_director/knowledge/cases.py` 的 `read_search_zh` 在没有线索文件时返回
  `({}, "search_zh_missing")`；`CaseIndex.__post_init__` 于是用
  `self.search_zh.get(case_id)` 为空来建 BM25 文档；
* 产品查询是**中文散文**，v4 案例的 `excerpt` 是**英文**。BM25 对中文查询近似 0 命中，
  top-3 退化成噪声 → 双评委打 1–2 分 → E1≈0；
* 对照：发货案例集带 `search_zh`（1012 条，`prompt_sha256=36069623ca…`，与当前
  `case_search_zh.prompt_sha()` **逐字节相同**，模型 glm-5.3），所以发货集能拿到 0.21；
* v4 的 783 条里 **650 条的 case_id 与发货集重合，且 `excerpt` 逐字节相同**，
  其中 521 条在发货线索里有非空 `zh`。

约束：`case_search_zh.py` / `cases.py` **不在**冻结仪器清单
（`tests/plan_v4_instruments.sha256.json` 只冻结 `e1_panel.py`、`hypergraph.py`、
`e1_baseline_summary.py`、`check_holdout.py`）；`read_search_zh` 有一条硬规则：
同一份线索文件里所有行的 `prompt_sha256` 必须一致，且要与 manifest 的
`clue_attached.prompt_sha256`（若有）一致，否则整份拒用。

## 缺陷 B：sidecar 的 LightRAG 检索跨事件循环崩溃

事实（可复算）：
* `tools/lightrag_service/serve.py` 用 `ThreadingHTTPServer`，每个请求一个 OS 线程；
* `LightRAGIndex.search()` 每次调用都 `asyncio.run(_run())`——**每次新建一个事件循环**，
  而 `self._rag` 是**跨调用复用**的对象，它的异步原语建在**第一次**的那个循环上；
* `work/_sidecar4.err` 里 5826 行、其中 5771 行是同一条
  `ERROR: Embedding func: Critical error in worker: <PriorityQueue at 0x…> is bound to a different event loop`，
  另有 `ERROR: Query failed: __aenter__` ×4；
* 结果：lightrag 臂 6/63 条查询返回空，E1=0——**不是检索质量差，是根本查不动**。

顺带的第二处：`cases.py` 里 lightrag 查询失败时的 BM25 回退
（`documents = [tokenize(self._text(case)) for case in self.cases]`）**丢了 `search_zh`**，
与正常建索引那条路径（`self._text(case, self.search_zh.get(case.case_id))`）不一致。

## 要的两件事

1. **原理**：为什么"每请求 `asyncio.run()` + 复用对象"必然踩 `bound to a different
   event loop`？`ThreadingHTTPServer` 在这里是不是第二个独立的坑（线程 vs 循环）？
2. **最小正确修法**：给出可执行到文件与行的改法，并给出**能离线跑、不依赖 lightrag**
   的回归用例该断什么、断在哪一层；同时说明缺陷 A 的正确落地形状（复用同代线索 vs
   全量重生成），以及"复用"在什么条件下**不算降级**、什么条件下**算**。


## 源码：tools/lightrag_service/build_index.py（第 288–331 行，逐字，带行号）

```
  288| 
  289|     async def call(prompt, system_prompt="", **kwargs):
  290|         if not key:
  291|             raise RuntimeError("缺少 DEEPSEEK_API_KEY（只从环境变量读）")
  292|         body = json.dumps({
  293|             "model": "deepseek-chat", "temperature": 0,
  294|             #: **`system_prompt` 一定要传**（格式规范在它里面，见 `chat_messages`）。
  295|             "messages": chat_messages(prompt, system_prompt),
  296|         }).encode("utf-8")
  297|         request = urllib.request.Request(  # noqa: S310 - 固定 https 端点
  298|             "https://api.deepseek.com/chat/completions", data=body, method="POST",
  299|             headers={"Authorization": "Bearer " + key,
  300|                      "Content-Type": "application/json"})
  301|         with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
  302|             payload = json.loads(response.read().decode("utf-8"))
  303|         return str(((payload.get("choices") or [{}])[0].get("message") or {})
  304|                    .get("content") or "")
  305| 
  306|     return call
  307| 
  308| 
  309| def build(cases_path: pathlib.Path, out_dir: pathlib.Path, *,
  310|           llm_model_func: Optional[Callable] = None,
  311|           embedding_model: str = "BAAI/bge-small-zh-v1.5",
  312|           embedding_route: str = "local",
  313|           mode: str = "naive", limit: int = 0,
  314|           batch_size: int = 40, max_parallel_insert: int = 8,
  315|           clue_mode: str = "local") -> Dict:
  316|     """真建索引。`out_dir/lightrag/` 是 LightRAG 的 working_dir。"""
  317|     import asyncio
  318|     import lightrag as lightrag_pkg
  319|     from lightrag import LightRAG
  320|     from lightrag.utils import EmbeddingFunc
  321| 
  322|     cases = load_cases(cases_path)
  323|     if limit:
  324|         cases = cases[:limit]
  325|     #: 中文线索（与案例分片同住 `<案例目录>/search_zh.part-*.jsonl`）。缺/陈旧
  326|     #: **不抛**——那是设计内的降级（退回"只吃原文"），但状态会如实写进 manifest，
  327|     #: 于是"这一代索引没有中文面"在产物里**看得见**：v4 那次三臂 E1 从 0.20 塌到
  328|     #: 0.0065 就是因为这条降级**没有任何痕迹**。
  329|     clues: Dict[str, str] = {}
  330|     clue_state = "clues_off"
  331|     if str(clue_mode) == "local":
```

## 源码：block_director/knowledge/cases.py（第 340–420 行，逐字，带行号）

```
  340|     _engine: Optional[Any] = field(default=None, init=False, repr=False)
  341| 
  342|     def __post_init__(self) -> None:
  343|         self.cases = list(self.cases)
  344|         self.requested = str(self.backend)
  345|         self.effective = str(self.backend)
  346|         self.degraded = False
  347|         if self.backend == "off":
  348|             return
  349|         if self.reason:                      # 索引缺失/读不出来：明确降级
  350|             self.degraded = True
  351|             self.effective = "off"
  352|             return
  353|         if self.backend == "lightrag" and self.adapter is None:
  354|             # §2.3b 的降级路径：退到 hybrid，并留下具名原因（不是静默）。
  355|             self.degraded = True
  356|             self.effective = "hybrid"
  357|             self.reason = DEGRADED_NO_ADAPTER
  358|         if self.effective == "hybrid" and self.cases:
  359|             documents = [tokenize(self._text(case, self.search_zh.get(case.case_id)))
  360|                          for case in self.cases]
  361|             self._engine, _name = make_bm25(documents)
  362| 
  363|     # --------------------------------------------------------------- 自述
  364|     @property
  365|     def enabled(self) -> bool:
  366|         return self.requested != "off" and self.effective != "off"
  367| 
  368|     @property
  369|     def lanes(self) -> int:
  370|         """§2.4：L3 开启时检索是两通道（``lanes = 2``），关闭时一条。"""
  371|         return 2 if self.enabled else 1
  372| 
  373|     def describe(self) -> Dict[str, Any]:
  374|         return {"cases_backend": self.effective,
  375|                 "cases_requested_backend": self.requested,
  376|                 "cases_degraded": bool(self.degraded),
  377|                 "cases_degraded_reason": self.reason,
  378|                 "cases": len(self.cases),
  379|                 #: 线索层的自述（缺/陈旧/可用）＋ 实际挂在索引上的条数。
  380|                 #: 没有这两个字段，"索引缺了中文线索"只能靠人去看每行的 `zh` 是空的。
  381|                 "cases_clue_state": self.search_zh_reason,
  382|                 "cases_clues": len(self.search_zh),
  383|                 "cases_filter": "on" if self.case_filter is not None else "off",
  384|                 "cases_filter_reason": self.filter_reason,
  385|                 "lanes": self.lanes,
  386|                 "lightrag_index_fingerprint": self.lightrag_index_fingerprint,
  387|                 "cases_index_fingerprint": self.fingerprint}
  388| 
  389|     # --------------------------------------------------------------- 检索
  390|     @staticmethod
  391|     def _text(case: Case, extra: Optional[str] = None) -> str:
  392|         """检索**只吃作者写的字**：`excerpt` ＋ 出处标题。
  393| 
  394|         为什么不能把 `case_id` 与 `title` 也算进去（2026-10-02 实测）：`title` 是我们
  395|         生成的标签（`镜头与焦距：Practical Cinema摘记086`），`case_id` 是
  396|         `case_pg76304_txt_007` —— 两者都不是作者写的。把标签喂进 BM25 的直接后果是
  397|         **拿中文查询去"命中"中文标签前缀**：`偷盗者奔逃中…` 会命中 `镜头与焦距：…`
  398|         里的 `镜/头` 两个字，于是案例层总是返回一堆与作者原文毫无关系的 1900 年代
  399|         散句（双模型面板 1–2 分，E1 = 0/16）。`source_ref.tags` 同样是**我们的**域标签
  400|         （`色彩`／`剪辑与节奏`），实测它让中文查询单字命中（查询里的 `色`／`画`／`向`
  401|         命中标签里的同一个字），所以一并去掉。去掉之后中文查询不再有词命中
  402|         ——**返回空是诚实的"没有参考案例"，返回噪声不是**。
  403|         `extra` 是这条案例的**中文检索线索**（有的话）。它不是我们编的理论——它是
  404|         `tools/kb_fetch/case_search_zh.py` 对**作者自己的摘录**做的中文改写，存在的
  405|         唯一理由是"产品的查询是中文、语料是英文"：没有它，BM25 对中文查询**恒 0 命中**
  406|         （实测 6/6 逐镜查询命中 0，E1 连分母都没有）。上面那条"不要把**我们的标签**喂进来"
  407|         的纪律不受影响：线索是**内容的翻译**，不是分类标签。
  408|         """
  409|         source = case.source_ref if isinstance(case.source_ref, dict) else {}
  410|         parts = [case.excerpt, str(source.get("title", ""))]
  411|         if extra:
  412|             parts.append(str(extra))
  413|         return "\n".join(parts)
  414| 
  415|     def retrieve(self, query: str, top_k: int = 3) -> List[Case]:
  416|         """取参考案例；不可用/无命中返回 ``[]``（**不抛**，也不造假数据）。"""
  417|         if not self.enabled or not self.cases:
  418|             return []
  419|         limit = max(1, int(top_k))
  420|         if self.effective == "lightrag" and self.adapter is not None:
```

## 产物：work/ab_v4_aligned/two_denominators.json

```
{
  "reference": "work\\ab_v4_aligned\\reviews.hybrid.rep1.jsonl",
  "query_count": 63,
  "arms": {
    "hybrid": {
      "relevant": 1,
      "queries": 63,
      "top_k": 3,
      "judge_coverage": {
        "rows": 153,
        "two_judge_rows": 152,
        "single_judge_rows": 1,
        "complete": false
      },
      "queries_with_no_rows": 0,
      "rows_missing": 36,
      "A": {
        "denominator": 153,
        "value": 0.006536
      },
      "B": {
        "denominator": 189,
        "value": 0.005291
      }
    },
    "lexical": {
      "relevant": 2,
      "queries": 63,
      "top_k": 3,
      "judge_coverage": {
        "rows": 192,
        "two_judge_rows": 191,
        "single_judge_rows": 1,
        "complete": false
      },
      "queries_with_no_rows": 0,
      "rows_missing": 0,
      "A": {
        "denominator": 192,
        "value": 0.010417
      },
      "B": {
        "denominator": 189,
        "value": 0.010582
      }
    },
    "lightrag": {
      "relevant": 0,
      "queries": 63,
      "top_k": 3,
      "judge_coverage": {
        "rows": 137,
        "two_judge_rows": 132,
        "single_judge_rows": 5,
        "complete": false
      },
      "queries_with_no_rows": 6,
      "rows_missing": 52,
      "A": {
        "denominator": 137,
        "value": 0.0
      },
      "B": {
        "denominator": 189,
        "value": 0.0
      }
    }
  }
}
```
```
