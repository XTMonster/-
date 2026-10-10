# 20261010-v17-B3 — 静态文件服务验收

| 项 | 值 |
|---|---|
| 卡 | v1.7 B3（TDD §7） |
| 执行者 | 主线（代执行） |
| commit | `c6ac094` |
| 改动 | `tools/sidecar_server.py`（`--web-root` + 静态分支）、`tests/test_sidecar_static.py` |

```text
python -m pytest tests/test_sidecar_static.py -q   → exit 0（5 tests）
```

结论：通过。静态免鉴权、`/static/*` 剥前缀、`resolve()` 后 commonpath 前缀
检查兜住 `..`/%2e%2e/符号链接逃逸（400）、后缀白名单外/缺文件 404、UI 端点
鉴权分层不被静态分支吃掉。
