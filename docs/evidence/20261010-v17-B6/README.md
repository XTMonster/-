# 20261010-v17-B6 — 四个只读端点验收

| 项 | 值 |
|---|---|
| 卡 | v1.7 B6（TDD §7） |
| 执行者 | 主线（代执行） |
| commit | `c6ac094` |
| 改动 | `tools/sidecar_server.py`（state_map/rules/target_models/shots + `--runs-dir`）、`tests/test_sidecar_ui_readonly.py` |

```text
python -m pytest tests/test_sidecar_ui_readonly.py -q   → exit 0（4 tests）
```

结论：通过。state_map 与 `CLIP_BY_STATE` 一致；rules 回 catalog＋当前
`rules_disabled`（每请求重读配置）；target_models 回三模型 raw＋current；
shots 只服务 `--runs-dir` 树内导出，run id 正则校验且 `..` 越界 400、缺文件
404；四端点无 token 均 401。
