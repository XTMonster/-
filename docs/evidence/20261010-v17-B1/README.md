# 20261010-v17-B1 — 事件收发与环形缓冲验收

| 项 | 值 |
|---|---|
| 卡 | v1.7 B1（TDD §7） |
| 执行者 | 主线（当前会话模型，代执行；派单被 PreToolUse 守卫拦截） |
| commit | `c6ac094`（B1–B7 共用 `tools/sidecar_server.py`，一次落） |
| 改动 | `tools/sidecar_server.py`（`POST/GET /v1/ui/events`）、`tests/test_sidecar_ui_events.py` |

```text
python -m pytest tests/test_sidecar_ui_events.py -q   → exit 0（5 tests）
```

结论：通过。服务端 seq 唯一真源（客户端 seq 忽略）、`since` 增量拉取、无
token 401、坏形状 400、`maxlen=2000` 环形淘汰（monkeypatch 工厂压 3 验证）。
