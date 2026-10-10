# 20261010-v17-B5 — 思考强度映射验收

| 项 | 值 |
|---|---|
| 卡 | v1.7 B5（TDD §4.2） |
| 执行者 | 主线（代执行） |
| commit | `c6ac094` |
| 改动 | `tools/sidecar_server.py`（`_apply_thinking` + `thinking_provider` + call_upstream 挂接 + `--upstream-kind` 显式位）、`tests/test_thinking_map.py` |

```text
python -m pytest tests/test_thinking_map.py -q   → exit 0（21 tests）
```

结论：通过。16 格矩阵逐格快照；off/未知 level 零改动透传（CLI 键原样保留）；
openai 写 `reasoning_effort`；deepseek 切 `deepseek-reasoner`＋max_tokens 下限
（低/中/高 = 8192/16384/32768，high 另发超时 ≥600 s 提示）；百炼
`enable_thinking`＋budget 且 `tool_choice=required` 自动降 `auto` 并记
`tool_choice_downgraded`；ollama `think=true`（high 加 num_ctx 提示）；未知
provider 透传。

解释说明（如实标注）：TDD §4.2 表是描述性格子，本卡把"小/默认/大 budget"与
"提示"落地为上述数值档与 stderr 观测提示；"响应 trace"落在 sidecar 的 stderr
观测通道（B5 只许改 sidecar，`ChatReply` wire 形状未动）。
