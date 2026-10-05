# P9（部分）：v4 案例层接上中文线索后的两臂读数

日期 2026-10-05。**只读了 V1／V6 五条判据允许的那一档**：`Cases_clue_state`、
同一份冻结查询、同一台面板、`top_k=3`。判据一个字没动。

## 结论先说

v4 案例层补上中文检索线索之后，**两条进程内臂的 E1 从「坏仪器」回到与发货代同级**：

| 臂 | 无线索（15:28 对齐跑） | 有线索（本次） | 变化 |
|---|---|---|---|
| hybrid | 1/153 = **0.0065** | 36/192 = **0.1875** | ×29 |
| lexical | 2/192 = **0.0104** | 40/192 = **0.2083** | ×20 |

对照发货案例集（`--cases-dir knowledge`，15:16 那次）：hybrid 40/192 = 0.2083、
lexical 43/192 = 0.2240。⇒ **0.0065 那一跑量的是仪器坏掉，不是检索臂差**。

## 证据是怎么来的

* 线索：`tools/kb_fetch/case_search_zh` 在 v4 案例层上跑完 —— 783 条处理完，
  **542 条出线索、241 条按规则给空串**（摘录确实不含工艺信息）。542 条里
  **488 条是同代沿用**（`--seed`：`(摘录, 出处标题)` 逐字节相同且
  `prompt_sha256` 与当前提示词相同——提示词的 user 模板只有这两项，所以那是同一次
  生成的输入）、**54 条现生成**；0 条 `call-failed`。产物：
  `work/knowledge_v4_cases/cases/search_zh.part-000.jsonl`，
  `cases.manifest.json` 记 `clue_attached`（体积门 699 KB / 20 MB，pass）。
  （`cases_sha256 = d916cd78…` = v4 案例集合的字节摘要；`prompt_sha256 = 36069623ca…`，
  与 `case_search_zh.prompt_sha()` 逐字节相同；模型 glm-5.3）。
* 面板：`tools/knowledge/e1_panel.py --queries work/eval_sets/heldout_v4_long21.jsonl \
  --cases-dir work/knowledge_v4_cases --top-k 3 --workers 3`，两位评委
  `deepseek-chat` ＋ `glm-5.3`。
* 本目录的 `reviews.*.rep1.jsonl` 是那一跑的逐行录档（192 行/臂，每行带 `zh`、`clues=542`、
  `cases_digest=d916cd78…`、两位评委的分数）。

## 仍未完成（不隐瞒）

* **lightrag 臂缺读数**：第三臂需要把中文线索也并进 LightRAG 的文档面后重建索引
  （旧索引建于 `clues_off`，事后往目录放线索不会回填）。重建在跑：
  `work/lightrag_v4_clues_local`，2026-10-05 16:26 时 163/783 篇。
  在它建成之前，**D8 不可裁**（三臂必须在同一代案例上跑）。
* **评委覆盖不齐**：hybrid 180/192、lexical 174/192 是「两位评委都回了分」的行数，
  `judge_coverage.complete=false`。按 V1 的「一侧缺席永远不算同意」，这两臂的这一轮
  还不是**有效轮**；要补跑或按 `two_denominators.json` 的覆盖格如实记账。
* `queries_with_no_rows = 0`（两臂各 64/64 条查询都有行，3.0 行/查询），
  所以本轮**不存在 D10 的分母不对称**问题。
