# 联合会诊纪要（DeepSeek × GLM-5.3）

- 模型：`deepseek-chat`（deepseek 族） × `glm-5.3`（zhipu 族）——**天然换族**
- 判词归属：`reviewed_by: llm-panel`（**不是** human，也不冒充 human）
- 输入：2 份源码、1 份产物；逐份 sha256 见 `bundle.manifest.json`
- 纪律：**一侧缺席不算同意**；会诊结论不改判据/门限/阈值。

## 角色：实现顾问

- 状态：deepseek=`main-answer`，glm=`ok`；完整=True
- usage：{"deepseek": {"model": "main-thread(deepseek)", "source": "main-answer"}, "glm": {"model": "glm-5.3", "requested_model": "glm-5.3", "level": "high", "max_tokens": 65536, "elapsed_s": 623.2, "usage": {"completion_tokens": 40643, "completion_tokens_details": {"reasoning_tokens": 33156}, "prompt_tokens": 5459, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 46102}, "finish_reason": "stop", "attempts": [{"model": "glm-5.3", "requested_model": "glm-5.3", "level": "high", "max_tokens": 65536, "elapsed_s": 623.2, "usage": {"completion_tokens": 40643, "completion_tokens_details": {"reasoning_tokens": 33156}, "prompt_tokens": 5459, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 46102}, "finish_reason": "stop"}]}}

### 两侧都提（严重度一致）（0）
（无）

### 两侧都提但**严重度不同**（0）
（无）

### 只有 GLM-5.3 提（7）
- **每请求 asyncio.run ＋ 复用 self._rag 是确定性必炸，不是偶发**（blocker）：缺陷 B 的根因是事件循环寿命违约：asyncio.run 每次新建并关闭循环，而 self._rag 的 asyncio 原语（嵌入批处理的 PriorityQueue、锁）绑定在第一个循环上；从第二次调用起每次必然抛 bound to a different event loop。lightrag 臂 E1=0 是崩溃伪影。最小正确修法：专用循环线程 + run_coroutine_threadsafe，且初始化必须跑在同一循环上。
- **ThreadingHTTPServer 是第二个独立的坑：它规定修法必须是单循环**（major）：线程与循环是两个独立维度。当前代码里线程坑被循环坑掩盖；若用『每线程缓存一个循环』的直觉修法，多请求线程会并发从多个循环碰同一个 self._rag，构成数据竞争（asyncio 原语非线程安全）。run_coroutine_threadsafe 提交到唯一循环的修法同时消解两个维度，ThreadingHTTPServer 本身可原样保留。
- **缺陷 A 使 hybrid/lexical 的 E1≈0 成为构造性结果**（blocker）：v4 案例目录缺 search_zh 文件时，BM25 文档只含英文 excerpt ＋ 出处标题，中文散文查询近似零命中，top-3 退化为噪声、双评委 1–2 分，E1 塌到 0.0065/0.0104——与发货集 0.2083 的差全部是仪器差，不是臂差。
- **lightrag 失败回退的 BM25 丢 search_zh：缺陷 A 从后门回炉**（major）：cases.py 里 lightrag 查询失败分支重建 BM25 语料时用 tokenize(self._text(case))（不带线索），与第 359 行正常路径 self._text(case, self.search_zh.get(case.case_id)) 不一致；即使 A 修好，任何一次 lightrag 故障都会静默退回『缺陷 A 的失效模式』。
- **缺陷 A 的落地形状：同代复用 521 ＋ 同代补生成 262，绝不混代**（major）：正确形状是『excerpt 字节级 join 复用 521 条 + 用同代工具补生成剩余 262 条』产出单一 sha 的 search_zh.part-000.jsonl，并把 reused/generated/mismatch/missing 记进 manifest。复用不算降级 iff（excerpt 逐字节相同 ∧ 同 prompt_sha256 ∧ 同模型）∧ 记账可见；算降级：excerpt 不同硬贴、混代拼装、静默替换。
- **A 修好后 lightrag 索引必须重建（或先核对它以哪个目录构建）**（major）：build_index.py 在建索引时消费 <案例目录>/search_zh.part-*.jsonl；v4 目录当时没有线索，索引的 clue_state 落在 clues_off。事后往目录放线索文件不会回填已建索引——不重建，lightrag 臂即使修好 B 也仍在测一张没有中文面的索引。另一可能：索引若以发货目录（1143 条）构建，则三臂语料根本未对齐——两种情况都必须从索引 manifest 读出来再定动作。
- **修完后的读数纪律：同查询、逐臂、分母与 confound 写明**（minor）：当前 two_denominators.json 显示三臂 judge 覆盖不齐（rows 153/192/137、rows_missing 36/0/52、lightrag queries_with_no_rows=6），E1-A 分母各异。修复重跑后应：同一份冻结查询、三臂 queries_with_no_rows 全 0、逐臂报 E1，并把 783 vs 1143 语料差与线索覆盖差作为 confound 明写。

### 只有 DeepSeek 提（5）
- **v4 案例层缺中文线索，必须先补线索再评 E1**（blocker）：work/knowledge_v4_cases/cases/ 只有 part-000.jsonl，无 search_zh.part-*.jsonl；read_search_zh 返回 search_zh_missing，CaseIndex 用空 clue 建 BM25，中文查询对英文 excerpt 近似 0 命中。修法：先在 v4 案例层上生成同代线索文件（cases_sha256=v4 digest、prompt_sha256=当前 prompt_sha），再跑三臂；E1 的判据一个字不动。
- **650/783 的 v4 案例与发货集 case_id+excerpt 逐字节相同，可复用同代线索**（major）：prompt_sha256 与 excerpt 都相同 ⇒ 同一条提示词作用在同一段摘录上，复用 zh 文本不是降级；但必须由库内脚本重建（写工具，不手改 jsonl），并把 cases_sha256 重新盖成 v4 digest。剩余 v4_only 133 条 + 无线索的重合条目需要用 glm-5.3 现生成。
- **LightRAGIndex 每次 search 都 asyncio.run，跨循环复用 _rag ⇒ 必然崩**（blocker）：asyncio.run 每次新建事件循环；_rag 的异步队列/锁建在首个循环上，第二次调用即 bound to a different event loop。修法：LightRAGIndex 自持一个常驻事件循环（单线程后台 loop，run_coroutine_threadsafe 提交），或在同一循环上跑全部查询。
- **ThreadingHTTPServer 让请求落在不同线程，加重跨循环/跨线程问题**（major）：serve.py 用 ThreadingHTTPServer，每次请求一个新线程；即使修了 asyncio.run，也必须在固定线程上跑常驻循环，否则 loop 与线程绑定会把问题换个样子复现。
- **lightrag 查询失败的 BM25 回退丢了 search_zh**（major）：cases.py:416 的 fallback 用 self._text(case) 建文档，而正常路径 cases.py:351 用 self._text(case, search_zh.get(case_id))；两条路不一致，回退后中文查询同样 0 命中。

## 角色：性能与鲁棒

- 状态：deepseek=`main-answer`，glm=`ok`；完整=True
- usage：{"deepseek": {"model": "main-thread(deepseek)", "source": "main-answer"}, "glm": {"model": "glm-5.3", "requested_model": "glm-5.3", "level": "high", "max_tokens": 65536, "elapsed_s": 534.5, "usage": {"completion_tokens": 34838, "completion_tokens_details": {"reasoning_tokens": 28844}, "prompt_tokens": 5468, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 40306}, "finish_reason": "stop", "attempts": [{"model": "glm-5.3", "requested_model": "glm-5.3", "level": "high", "max_tokens": 65536, "elapsed_s": 534.5, "usage": {"completion_tokens": 34838, "completion_tokens_details": {"reasoning_tokens": 28844}, "prompt_tokens": 5468, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 40306}, "finish_reason": "stop"}]}}

### 两侧都提（严重度一致）（0）
（无）

### 两侧都提但**严重度不同**（0）
（无）

### 只有 GLM-5.3 提（5）
- **每请求 asyncio.run() × 跨调用复用 _rag：第二次调用起必然炸；ThreadingHTTPServer 是正交的第二坑**（blocker）：LightRAGIndex.search() 的『每次 asyncio.run(_run()) ＋ 复用 self._rag』在第二次及以后的调用上必然抛 bound to a different event loop，与负载、并发、输入内容无关；ThreadingHTTPServer 带来的是独立于循环绑定的第二个问题（多线程并发触碰共享可变状态），只修其一都不算修好。lightrag 臂的 E1=0.0（relevant 0／分母 137／6 条空查询）度量的是『服务崩了』，不是检索质量。
- **缺陷 A 判词：对齐跑的 hybrid/lexical 测的是『没有中文线索层』；落地＝按身份复用同代线索＋增量重生成＋覆盖上账**（blocker）：v4 案例目录缺 search_z 文件使 BM25 语料退成英文原文、中文查询近 0 命中，hybrid 1/153、lexical 2/192 不是臂间差异，是同一台坏仪器的两次读数。正确落地是混合：650 条 case_id 重合且 excerpt 逐字节相同、发货线索 prompt_sha256=36069623ca… 与当前 prompt_sha() 逐字节相同、模型 glm-5.3——满足这些身份条件时复用不是降级（线索是 (prompt, model, 原文) 的纯函数，复用＝同代备忘录）；excerpt 变了、prompt/模型变了、或 262/783≈33.5% 的无线索缺口不上账，才算降级。全量重生成浪费 650 个未变输入并给重合子集引入不必要的采样方差。
- **lightrag 失败回退的 BM25 丢了 search_zh：失败路径与正常路径的语料不一致**（major）：cases.py 里 lightrag 查询失败后的 BM25 回退用 documents = [tokenize(self._text(case)) for case in self.cases]（不带 search_zh），与正常建索引的 self._text(case, self.search_zh.get(case.case_id)) 不一致——lightrag 一失败，回退检索在中文查询上立刻退化成缺陷 A 的形态；若该 documents 列表每次失败查询都现场构建，还叠加每次 O(783) 的全量重 tokenize 性能税。
- **跑批缺『仪器门』：6 条空查询与 5771 行 ERROR 仍产出格式完整的三臂数**（major）：two_denominators.json 如实记了 queries_with_no_rows: 6，cases.py 也早有 cases_clue_state/cases_clues 字段，但没有任何门消费它们——lightrag 臂照常出对照值 0.0，对齐跑产物头部也没有 clue_state。『看得见的降级』没有被升格为『该臂无效』，是缺陷 A、B 能以合法产物形态存在的共同根因；服务侧同时缺熔断：同一类不可自愈的错误打了 5771 遍还在继续跑。
- **复用 precondition 锚在 prompt_sha() 上，而 case_search_zh.py 正带着未提交改动**（minor）：判词引用的身份条件『发货线索 prompt_sha256=36069623ca… 与当前 case_search_zh.prompt_sha() 逐字节相同』锚在活代码上；git status 显示 tools/kb_fetch/case_search_zh.py 与 tests/test_case_search_zh.py 均有未提交修改，且该文件不在冻结仪器清单里。若改动触及 prompt 文案，prompt_sha() 不再等于 36069623ca…，F2 的复用条件失效，read_search_zh 的『整份拒用』会把线索文件整体判死，跑批退回缺陷 A 形态。

### 只有 DeepSeek 提（2）
- **常驻事件循环需要显式超时与失败具名，否则单查询会挂住整个 sidecar**（major）：把 asyncio.run 改成常驻循环后，一次查询卡死会阻塞后续；应给 run_coroutine_threadsafe 加 timeout，超时抛具名错误，由 serve.py 映射成 500 index_error 而不是静默空列表。
- **回归用例应能离线跑：注入一个会二次 await 的假 rag，断言两次 search 不抛**（major）：不依赖 lightrag 也能钉住这个缺陷：把循环管理抽成一个可注入的 runner（或让 _rag 可注入），用纯 asyncio 假对象调用两次 search，第二次必须成功——当前实现必红。
