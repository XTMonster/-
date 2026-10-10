# 20261010-v17-A6 — 分工声明契约验收

| 项 | 值 |
|---|---|
| 卡 | v1.7 A6（TDD §14.1；SDL 升 1.7） |
| 执行者 | 主线（当前会话模型；原计划即 Opus 卡） |
| commit | `6e6dc6b` |
| 改动 | `contracts/plan.py`（`Responsibility` + `ShotPlan.responsibility` 恒出键）、`contracts/sdl.py`（`SDLShot.responsibility` + 版本 1.7）、`layer2_sdl/sdl_migrate.py`（1.6→1.7 补 null + 坏类型 finding）、`layer2_sdl/sdl_builder.py`（build_sdl/sdl_to_plan 双向搬运）、`layer5_orchestrator/planner.py`（`_SHOT_ITEM_SCHEMA` 可选键）、golden 三件重生成、`tests/test_responsibility_contract.py`（新，6 tests）＋三个 SDL 版本 pin 测试升 1.7 |

## 验收命令与真实输出

```text
python -m pytest tests/test_responsibility_contract.py -q   → exit 0（6 tests）
python -m pytest -q（全仓）                                  → exit 0
python tools/gen_golden.py                                  → 重生成 3 件派生夹具
python tools/gen_golden.py --check                          → [OK] 零漂移
python tools/check_assertions.py                            → [OK]
```

## golden diff 口径（与卡片④的差异说明）

卡片④写"diff 只许出现 `responsibility: null` 新增键"。实测 diff 另含
`"version": "1.6" → "1.7"` 一行——这是卡片自己"SDL 升 1.7"命令的直接结果，
不是实现偏差；其余全部为每镜新增 `responsibility: null`，`expected_shots_long.json`
零改动（manifest 不涉及本卡）。

## 范围漂移（已记台账）

卡片"只许改"清单未列 `sdl_builder.py` 与 `SDLShot.responsibility` 字段，但
卡片的 golden 口径与往返测试要求 responsibility 经 SDL 持久化；另有三处既有
测试把 SDL 版本 pin 在 "1.6"，升版必改。以上均为卡片语义的唯一解，非降级，
已在 `v1.7/PROGRESS.md` 漂移笔记登记。

## 结论

通过。v1.6 文件迁移零 error 且每镜 `responsibility is None`；plan/SDL 双向
往返相等；序列化恒出键；emit_plan schema 收/不收可选键均可、坏类型被拒；
迁移遇 `responsibility: "yes"` 只记 finding 不崩。
