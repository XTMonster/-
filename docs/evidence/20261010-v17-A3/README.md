# 20261010-v17-A3 — UIEvent DTO 验收

| 项 | 值 |
|---|---|
| 卡 | v1.7 A3（TDD §2.1） |
| 执行者 | 主线（当前会话模型，代执行） |
| commit | `4ab7506` |
| 改动 | 新建 `contracts/ui_events.py`、`tests/test_ui_events.py` |

```text
python -m pytest tests/test_ui_events.py -q   → exit 0（3 tests）
```

结论：通过。`seq/ts/kind` 必填、`state/shot_id/payload` 缺省，`payload` 两次
构造不共享同一 dict，缺省键反解不抛。
