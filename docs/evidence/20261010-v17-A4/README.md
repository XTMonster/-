# 20261010-v17-A4 — 规则元信息目录验收

| 项 | 值 |
|---|---|
| 卡 | v1.7 A4（TDD §7 末段） |
| 执行者 | 主线（当前会话模型，代执行） |
| commit | `441d6f2` |
| 改动 | 新建 `contracts/rule_catalog.py`（18 条）、`tests/test_rule_catalog.py` |

```text
python -m pytest tests/test_rule_catalog.py -q   → exit 0（4 tests）
```

结论：通过。双正则双文件静态对拍（rule_checker 的 `_error`/`_warning`/三元形态
＋ compliance 的 `RULE_*` 常量）并集 == catalog id 集且恰 18 条；severity 按
消费侧形态对拍；`COMPOSITION` 不入册。
