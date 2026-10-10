# 20261010-v17-A1 — 小助手状态映射真源（验收）

| 项 | 值 |
|---|---|
| 卡 | v1.7 A1（`v1.7/改进计划_v1.7_deepseek.md` §阶段 A） |
| 执行者 | 主线（当前会话模型）。原分工为 DeepSeek V4 Pro 子代理，但本会话被 PreToolUse 守卫识别为子代理、禁止再派单，按守卫指示由本线程直接执行，不冒充 DeepSeek |
| 改动 | 新建 `block_director/contracts/assistant.py`、`tests/test_assistant_contract.py` |
| git HEAD | fd5b5ec |

## 验收命令与真实输出

```text
python -m pytest tests/test_assistant_contract.py -q
....                                                                     [100%]
（exit 0 = 4 passed）
```

```text
python -m pytest -q
（exit 0，全仓绿；详见 work/root_pytest_baseline_2341.log 为开工基线）
```

## 结论

通过。`CLIP_BY_STATE` 的 15 个字符串键与 `DriverState` 的 15 个成员逐一相等；
全部 clip 名合法；未知态/空串/None 均回落 `"sit"` 且不抛。

## 缺口

- `web/assets/assistant/frames.json` 尚未由 C3 落地，本卡按卡片测试清单不
  对帧表做存在性断言（卡片验收命令为 4 passed）。
- 未运行 `tools/run_tests.ps1` 全链（44 步探针需 Blender，属卡后全链项，
  由 H3 收尾统一执行）。
