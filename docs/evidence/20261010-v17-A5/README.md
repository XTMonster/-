# 20261010-v17-A5 — 目标模型规格表验收

| 项 | 值 |
|---|---|
| 卡 | v1.7 A5（TDD §12.1） |
| 执行者 | 主线（当前会话模型，代执行） |
| commit | `6a8ac2d`（loader 半）；config 半见 `bbbca2f` |
| 改动 | 新建 `specs/target_models.yaml`、`contracts/target_models.py`、`tests/test_target_models.py` |

```text
python -m pytest tests/test_target_models.py -q   → exit 0（6 tests）
python tools/gen_specs.py --check                  → [OK]
```

结论：通过。三模型齐全、label 非空、区间键 lo<hi；缺文件/缺 label/坏区间一律
`TargetModelError`（抛错不静默）；`unknown_x` 恰好 1 条 CFG_172 warning。
