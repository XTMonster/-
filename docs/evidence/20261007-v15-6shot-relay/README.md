# `20261007-v15-6shot-relay` — 中继通道做引擎真跑的**原始现场**（两次都失败）

这个目录是"新通道（中继 `qwen3.8-max-0902` ＋ `reasoning_effort=max`）做引擎真跑"
两次尝试留下的**原始**运行现场（`runs/audit_log.jsonl`、`runs/llm_trace.jsonl`、
`knowledge_trace.json`）。两次都以 `分镜计划生成失败（已达最大尝试次数）` 收场，
**没有** `run_manifest.json`，也**不作**任何验收证据。

整理过的读数与结论见 `docs/evidence/20261007-v15-relay-502/README.md`
（那条通道在**会诊/标注**上当天是好的，失败只出现在"长提示 ＋ 工具调用"的计划那一步）。
