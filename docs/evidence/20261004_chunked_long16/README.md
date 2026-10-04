# long16：工具预算不再饿死修复回路——**但这一跑的结果没有变好**（如实记）

## 发现的缺陷（已修）

`DriverLimits.max_tool_calls` 原来是**与场景无关的固定 200**。long15（64 镜）实测：

```
200th tool call at +362s        ← 额度用光
first 超限 repair at +367s      ← 此后每一次修复都被拒
超限 repairs: 57, last +479s    ← 占整跑最后 117 s（24%）
```

也就是说**片子后四分之一一次也没被修过**，37 镜撞上修复上限被降级——而 LLM 预算
（512）与墙上时间都还剩着。修法是让工具预算跟着场景走：`tool_call_budget()`
= `max(静态下限, 本场 LLM 回合上限)`（工具调用是 LLM 回合的**动作**，上限不该低于
回合上限；真正的节流仍在 LLM 预算与墙上时间），并在 `budget_scoped` 事件里留痕。

## 这一跑的测量（同一份剧本、同一条命令、同一后端）

| | long15（固定 200） | **long16（512）** |
|---|---|---|
| `budget_scoped.tool_calls_effective` | 200 | **512** |
| 实际工具调用 | 200（**撞顶**） | **442** |
| `repair_invalid: 工具调用次数超限` | **57** | **0** |
| LLM 调用 | 272 | 319 |
| 检索调用 | 68 | 67 |
| 终审逐镜通过 | **29** | **23** |
| 错误 | COMPOSITION 25 / R001 25 / R003 6 / R011 1 | COMPOSITION 28 / R001 41 / R003 7 |
| 构图中位 | 74.3 | 72.0 |

**饥饿是真缺陷，但它不是结果差的主因**：额度放开之后修复回合**跑得更多**（319 次
LLM 调用、442 次工具调用），终审却更差。⇒ 真正的杠杆是**修复是否有效**，不是
"允不允许修"。（n=1 对 n=1，且长跑方差本来就大——见 long14 与 long15 的对照；
这一页只主张"饥饿消失了"，**不主张**结果变好。）

## 顺带修掉的一条**假问题**（也是这一轮的最大收获）

`_dispatch_tool_calls` 的收尾判据是 `if not plan_seen: return "没有收到 emit_plan 调用"`，
**与阶段无关**；而修复回合在上面**明确拒绝** `emit_plan`（"emit_plan 只在阶段 A 被
接受"）⇒ **每一轮修复**都必然返回这条问题、被记成 `repair_invalid`：

| `repair_invalid` 的构成 | long15 | long16 |
|---|---|---|
| 工具调用次数超限（真错） | 57 | **0** |
| 没有收到 emit_plan 调用（**假问题**） | 39 | **89** |

89 条假错与真错混在同一个事件名里，"这一轮到底错没错"就判不出来了——而它正是排查
修复回路时唯一能依赖的信号。已改成**只有阶段 A** 才要求 `emit_plan`（守门用例
`tests/test_repair_applied_means_something_changed.py::test_a_repair_round_is_not_judged_by_the_plan_contract`，
含反面对照：阶段 A 的判据一个字不放宽）。**long16 跑在这次修复之前**，
所以它日志里那 89 条仍是旧的假问题。

## 复算

```
python tools/extract_run_evidence.py --run-id 6ebe55cfbe63 \
    --out docs/evidence/20261004_chunked_long16 \
    --audit-log .../runs/runs/audit_log.jsonl --llm-trace ... --shots .../shots.json
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261004_chunked_long16/project --out <json>
```

`project.bdproj` 的落盘校验报 7 条 S3（动作重叠）——`save_run_project` 如实带回结论、
文件照写（§14 的口径）。
