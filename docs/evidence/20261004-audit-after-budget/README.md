# P14-87：预算触顶**不许**把没审过的镜头丢掉

## 缺陷（long18 的账）

long18（`run_id 7fcbf6b3dfd6`，多轮修复＋观测回灌后的第一趟 64 镜真跑）把 token
用量顶到硬编码的 `BudgetLimits.max_tokens`（2 000 000，`budget.py:19`），于是
`budget_exhausted` → `driver._degrade_to_finish()` → 直接跳 `FINISHING`：

```
long18 有 shot_audit 的镜头: 55
缺: 9  ['shot_056','shot_057','shot_058','shot_059','shot_060',
        'shot_061','shot_062','shot_063','shot_064']
```

**"没审过"与"审过没过"在账上长得一样**——读 `run_manifest` / `rks.json` 的人看到的
是"64 镜的工程、55 条审核"，很容易把缺失当成通过。而审核本身是 bpy 侧的**纯规则
计算**：不调模型、不花 token。用预算去拦它，方向就错了。

## 那 9 镜到底是什么样（零 LLM 复评，`long18_reaudit.json`）

把 long18 保存的工程重新建场景、逐镜跑同一个 `BpyShotAuditor`
（`blender --background --factory-startup --python reaudit_probe.py -- --project
docs/evidence/20261004_chunked_long18/project`）：

| 镜 | 终审 | 构图分 | 红的规则 |
|---|---|---|---|
| shot_056 | 通过 | 91.2 | — |
| shot_057 | 通过 | 89.7 | — |
| shot_058 | **不通过** | 20.0 | COMPOSITION |
| shot_059 | **不通过** | 60.2 | COMPOSITION |
| shot_060 | **不通过** | 58.5 | COMPOSITION |
| shot_061 | **不通过** | 20.0 | COMPOSITION |
| shot_062 | **不通过** | 53.1 | R001、R003、COMPOSITION |
| shot_063 | 通过 | 92.3 | — |
| shot_064 | **不通过** | 20.0 | R001×2、COMPOSITION |

⇒ 缺的那 9 镜里 **6 镜本来就不通过**（占全片 9.4%）。这不是"少记了几行日志"，
是**证据里少了 6 条失败**。

## 修法

`driver._audit_shot(shot_id, *, degraded=False)`：把"跑审核 + 逐字落
`shot_audit`"抽成一个零 LLM 的函数（`_step_checking` 与降级路径共用同一份实现，
形状不许各写一遍）。`_degrade_to_finish()` 在转 `FINISHING` **之前**把
`_shot_queue` 里**还没审过**的镜头补审一遍，并：

* 给这些事件加 `degraded: true`（正常路径的事件形状**一个字节没变**）；
* 写一条 `audit_after_budget` 汇总（`{shots, audited, reason}`）；
* **只审不修**：不调模型、不触发修复、不写 `repair_applied`；
* 已经审过的镜头（通常正是"刚审完、卡在修复上"的队头那一镜）不重复审，
  否则"补审了几镜"会报大。

## 守门

`tests/test_driver_guards.py::test_budget_exhaustion_still_audits_every_remaining_shot`：
三镜的夹具，预算只够"理解 + 计划"，对第一镜的修复被拦下 → 断言**三镜都有
`shot_audit`**、只有补审出来的那些带 `degraded: true`、存在 `audit_after_budget`、
且**没有** `repair_applied`。

`tools/run_tests.ps1` **32/32**、`python -m pytest` **2001 passed / 1 skipped**，
证据 `docs/evidence/20261004-121921/`（RK-13 仍因 Q5/E1 记 failed，口径未动）。
