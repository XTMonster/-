# 20261010-v17-B2 — 配置读写与 key 掩码验收（红线卡）

| 项 | 值 |
|---|---|
| 卡 | v1.7 B2（TDD §4.3/§7，安全红线） |
| 执行者 | 主线（当前会话模型，代执行） |
| 复核 | 主线自审（红线卡按计划应由 DeepSeek 复核 diff；派单被守卫拦截，此缺口如实标注，未冒充跨模型共识） |
| commit | `c6ac094` |
| 改动 | `tools/sidecar_server.py`、新建 `block_director/utils/secret_store.py`、`tests/test_secret_store.py`、`tests/test_sidecar_ui_config.py` |

```text
python -m pytest tests/test_secret_store.py tests/test_sidecar_ui_config.py -q
    → exit 0（11 tests：10 passed / 1 skipped——0600 仅 POSIX，Windows 按 NTFS 继承权限跳过）
```

自审（复核要点逐条）：掩码无旁路（GET 出口过 `mask_key`；PUT config 写盘前
强制 `api_key=""`；PUT secret 只回 `{saved:true}`）；key 不进日志/审计；PUT
config 有 error 级 Issue 时先校验后写盘、磁盘字节不变。另修复一处测试自污染：
早期版本误写真实 `%APPDATA%/BlockDirector/secrets.json`，已清空并让测试对
`save_secret`/`load_secrets` 完全打桩，不再触真实密钥库。

结论：通过。
