# 联合会诊纪要（DeepSeek × GLM-5.3）

- 模型：`deepseek-chat`（deepseek 族） × `glm-5.3`（zhipu 族）——**天然换族**
- 判词归属：`reviewed_by: llm-panel`（**不是** human，也不冒充 human）
- 输入：2 份源码、0 份产物；逐份 sha256 见 `bundle.manifest.json`
- 纪律：**一侧缺席不算同意**；会诊结论不改判据/门限/阈值。

## 角色：实现顾问

- 状态：deepseek=`ok`，glm=`unparsed`；完整=False
- usage：{"deepseek": {"model": "deepseek-flash", "requested_model": "deepseek-chat", "usage": {"prompt_tokens": 3321, "completion_tokens": 4413}}, "glm": {"model": "glm-5.3", "requested_model": "glm-5.3", "level": "low", "max_tokens": 32768, "elapsed_s": 372.2, "usage": {"completion_tokens": 32768, "completion_tokens_details": {"reasoning_tokens": 31301}, "prompt_tokens": 3466, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 36234}, "finish_reason": "length", "attempts": [{"model": "glm-5.3", "requested_model": "glm-5.3", "level": "low", "max_tokens": 32768, "elapsed_s": 372.2, "usage": {"completion_tokens": 32768, "completion_tokens_details": {"reasoning_tokens": 31301}, "prompt_tokens": 3466, "prompt_tokens_details": {"cached_tokens": 0}, "total_tokens": 36234}, "finish_reason": "length"}]}}

### 两侧都提（严重度一致）（0）
（无）

### 两侧都提但**严重度不同**（0）
（无）

### 只有 GLM-5.3 提（0）
（无）

### 只有 DeepSeek 提（5）
- **覆盖门量的是行数占比，不是检索命中率——59.5% 可能是假覆盖**（major）：`assert len(lines) >= 0.5 * len(cases)` 只保证线索行数够，不保证这些线索能被中文查询命中；实测「查询点名的 309 个工艺词里 153 个在库里没有对应键」说明近半数查询词根本无键可查，59.5% 的覆盖里含这部分假覆盖。
- **旧提示词 739 条里的 8 行元话术会随 `after=810` 保护带原样进新索引，全量判据会红**（blocker）：`apply_clue_gate` 对 `index < after` 的案例无条件保留（第 781 行），`attach_clues` 只按 `keep_ids` 和 `zh` 非空筛行（第 820–821 行），不跑 `ZH.classify`；因此旧线索里那 8 行按现行判据该丢的元话术，只要对应案例在前 810 条内，就会进新索引，触发 `shipped_clue_problems` 全量扫开火。
- **重签必须发生在最终案例集合确定之后，否则 `cases_sha256` 对不上、整份线索被拒用**（major）：`attach_clues` 的注释明确：过滤之后案例集合变了 ⇒ 摘要变了 ⇒ 不重签，新索引会一条线索都用不上；因此 `build_cases` 必须按「gate 定集合 → 算 digest → attach_clues 重签」的顺序执行，且 digest 必须来自**过滤后**的案例集合。
- **manifest 必须按过滤后集合重算，否则 `cases` 与 `per_type` 自相矛盾**（major）：`recount` 的注释指出：不重算就会留下「`cases` 少了、`per_type` 还是老的」这种自相矛盾的账，`tests/test_cases_corpus.py::test_the_manifest_accounting_adds_up` 会红；这次 gate 会丢案例，所以必须调 `recount`。
- **E1 提升未达 5% 显著，不能把这次扩库当作「检索质量已改善」的证据**（minor）：词表同源新线索 E1 由 0.0920 涨到 0.1198，池化 z=1.53 未达 5% 显著；按查询配对 B 好 35 / 差 14、符号检验 p≈0.004。两个检验结论不一致，说明整体提升的证据强度不足以支撑「扩库即改善」的结论。
