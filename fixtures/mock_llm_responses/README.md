# mock_llm_responses

Golden Test（执行文档 v1.2 §21.4）用的确定性 LLM 响应。

- `plan_simple.json` — 阶段 A（Planner）对 `fixtures/script_simple.fountain`
  的分镜计划：3 个镜头、2 个角色、对白均落在镜头时长内（含 §4.4 的收尾余量）。
- `review_ok.json` — 阶段 B3 的 `request_self_review` 响应（Level 2 自审通过）。

这些文件由人手工维护，是"期望输出"的那一侧；`tools/gen_golden.py` 只负责
把它们展开成 `expected_sdl_simple.json` 与 `tool_transcript_simple.jsonl`，
不改动它们。改了计划就要重新生成派生夹具（`python tools/gen_golden.py`）。
