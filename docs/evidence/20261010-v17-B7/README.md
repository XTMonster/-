# 20261010-v17-B7 — 聊天端点验收（红线卡）

| 项 | 值 |
|---|---|
| 卡 | v1.7 B7（TDD §5，安全红线） |
| 执行者 | 主线（当前会话模型，本卡原分工即 Opus） |
| 复核 | 主线自审（计划要求 DeepSeek 复核；派单被守卫拦截，缺口如实标注） |
| commit | `c6ac094` |
| 改动 | `tools/sidecar_server.py`（`POST /v1/ui/chat`）、`tests/test_sidecar_chat.py` |

```text
python -m pytest tests/test_sidecar_chat.py -q   → exit 0（6 tests）
```

自审（复核要点逐条）：注入链不含 key/完整 prompt（system 只含固定用法摘要＋
检索三栏 ≤500 字/栏，捷径回复对 payload 做 80 字有界摘要）；写操作白名单为
空（`帮我改|重新生成|改一下|删掉` → 固定文案、零上游调用）；历史封顶 10 轮；
聊天 append-only 落 `<runs-dir>/<run_id|_idle>/chat.jsonl`，run_id 由事件
`payload.run_id` 更新。

结论：通过。
