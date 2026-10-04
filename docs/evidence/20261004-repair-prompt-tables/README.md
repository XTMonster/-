# P14-92：修复提示缺了**动作参数表**——"重提草案"因此必然被退回

## 现场（long19 的日志，逐条可复现）

long19 终审还红着 5 条 R003（同角色动作时间重叠）。逐条看修复回合：

```
[shot_052] AUDIT passed=False score=91.8 ['R003']
   LLM repair tools=4                      ← 工具集收窄到 emit_shot_draft ＋ 控制类
   TOOL emit_shot_draft ok=True            ← 模型**确实**调了正确的工具
   repair_invalid: body_tilt 不认识的参数 ['lean_deg']；允许的键是
                   ['angle_deg','angle','degrees','axis','toward']…
[shot_052] AUDIT passed=False score=91.8 ['R003']   ← 逐字相同：草案被退回，计划没变
   repair_applied: shot_052 已实施定向修复（R003）   ← 于是这条留痕是**假**的
[shot_052] shot_degraded: 达到修复上限（2）
```

`shot_053` 同形（`turn_head ['direction_deg']`）。**根因**：编辑器提示
（`EDITOR_SYSTEM_PROMPT`）带着两张由代码生成的表——
`editor.render_action_params()`（每个动作允许的参数键）与
`render_movement_units()`（运镜 `amount` 的单位）——而**修复提示没有**。
模型在被要求"重新提交这一镜的草案、把起止帧错开"时，手上没有键名，只能自己发明，
整条草案被 `extract_draft` 判非法 ⇒ 计划一个字没改 ⇒ R003 一直红到降级。

## 修法

`REPAIR_SYSTEM_PROMPT` 补两处占位（`{action_params}`、`{movement_units}`），
`build_repair_payload` 用**同一份** `editor.render_action_params()` /
`render_movement_units()` 渲染——两边一份实现，不许各抄。

守门 `tests/test_repair_prompt_picks_the_right_tool.py::`
`test_the_repair_prompt_carries_the_action_and_movement_tables`：
两份表逐字进提示（`render_action_params() in system`）、占位符必须被替换掉、
并且 `body_tilt` 那一行带着它自己的允许键。

## 效果（long20，同剧本、同命令、同后端）

| | long19（修前） | **long20（修后）** |
|---|---|---|
| `repair_invalid` 里的**参数名**报错 | `stand ['base_z']`×7、`turn_head ['toward']`×4 | **0** |
| R003（终审） | 5 | **3** |
| 终审逐镜通过 | 45 | 45 |
| 构图分中位 / 构图门 | 88.0 / 54 | **88.6** / 52 |
| 声明固定却有运动 | 0 | **0** |

参数名那一类报错**整类消失**、R003 由 5 降到 3——但逐镜通过与构图门在噪声范围内
（长跑方差本来就有，见 §八十一）。**不主张**它单独把成绩拉高，只主张
"模型照着提示做不再被自己的键名绊倒"。
