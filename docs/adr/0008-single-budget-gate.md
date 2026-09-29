# ADR-0008 预算门禁单值化：`max(ceiling, formula)` ＋ CLI 才是硬顶

状态：Accepted（v1.4 / P9.4）

## 背景

v1.3 同时存在三套"这次能调用多少次 LLM"的口径：驱动器里的
`DriverLimits.max_llm_calls = 8`、配置里的公式 `shots * 8`、以及面板上的
"调用上限"。三者取小的那个，于是 61 镜的长剧本被 8 次调用卡死；
`config.budget.max_cost_usd` / `max_wall_minutes` 更是**死配置**，没人执行。

## 决策

只保留两条门禁，别的都不算：

```
ceiling_effective = max(budget.max_llm_calls_ceiling, formula(N))   # 额度下限保障
llm_calls        <= ceiling_effective
retrieval_calls  <= (2 + N) × lanes                                  # 与 llm 分列
```

- `budget.max_llm_calls_ceiling`（默认 200）是**下限保障**，不是上限；
- **真正的硬顶只来自 CLI `--max-llm-calls`**（`0 = 不限`，该因子不参与，
  绝不可写成 `min(..., 0)`）；
- `DriverLimits.max_llm_calls` 的初值 = ceiling，CLI 显式给出时覆盖它；
- 面板编辑的仍是 `max_llm_calls_per_scene_formula`（默认 `"shots * 8 + 40"`）。

落点：`layer5_orchestrator/driver.py::_apply_scene_budget`、
`_limits_from`、`contracts/config.py` 的新键、`tools/run_headless.py` 的
`--max-llm-calls` 默认值 0。

## 后果

- 61 镜的计算是 `max(200, 528) = 528`，不会再被 200 卡死；"预算压力测试"
  用 `--max-llm-calls 1` 才能真正触顶并走 `_degrade_to_finish`。
- `shots.json.llm_calls` / `retrieval_calls` 与 `audit_log.jsonl` 的逐次
  `llm_call` / `retrieval_call` 事件**独立对拍**（RK-18）。
- **被否决的替代方案**：`min(ceiling, formula)`——它把 ceiling 当上限用，
  61 镜会被压到 200 并触发降级，与"给多长剧本就生成多长"直接冲突。
