# 20261010-v17-A2 — 配置新键（UI 组）验收

| 项 | 值 |
|---|---|
| 卡 | v1.7 A2（`v1.7/改进计划_v1.7_deepseek.md` §阶段 A）＋A5 的 config 半（共享 `contracts/config.py`，见下） |
| 执行者 | 主线（当前会话模型，代执行；派单被 PreToolUse 守卫拦截） |
| commit | `bbbca2f`（config 半）；A5 loader 半见 `6a8ac2d` |
| 改动 | `contracts/config.py`、`specs/config.default.yaml`（gen_specs 重生成）、`tests/test_config_v17_keys.py` |

## 验收命令与真实输出

```text
python -m pytest tests/test_config_v17_keys.py -q   → exit 0（5 tests）
python tools/gen_specs.py                           → [OK] 写入 specs/config.default.yaml
python tools/gen_specs.py --check                   → [OK] 与代码一致
```

## 结论

通过。新增 `llm.thinking_level`（CFG_170 warning）、`audit.rules_disabled`
（CFG_171 warning）、既有 `UIConfig` 追加三键、新建 `ScriptPolishConfig`
（挂 `script_polish:` 节），`CONFIG_VERSION` 升 1.4.0；旧形态配置零 error 加载；
serde 往返幂等。

## 缺口

- A5 的 `delivery.target_model` / CFG_172 与本卡共用 `config.py`，同一 commit
  落盘（commit message 已注明）；不影响二者各自的判据。
