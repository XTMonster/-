# P14-65：`walk_to` 的缺省起点必须**接力**，而不是每次都回到剧本起始站位

**结论**：`motion/model.py` 的 `walk_to`/`run_to` 在**没有 `from`** 时把
`target_position` 当成**相对位移**（`base + target`，`work/_walk_once_probe.py`
三组对照实测），而规划器几乎从不写 `from` ⇒ 构建器一直拿
`CastMember.initial_location` 当缺省起点，同一角色的一串行走**累加**：
`long9` 重建里伊恩从起始站位一路加到 **(13.0, −12.6)**，而计划里每个目的地都在
9.5 m 以内。同一座场景里"人越走越远"就是这么来的。

修法：`cinema/schedule.travelled_positions(plan, initial)` —— 按**计划顺序**推算
"到这一镜开始时人在哪"（上一次行走的**绝对**终点就是下一次的起点），
构建器把它当作 `walk_to` 的缺省 `from`。纯计算、可单测
（`tests/test_travelled_positions.py`，6 条：接力 / 顶层 `target_position` /
非行走动作不接力 / 缺目的地不接力 / 2 元组补 z / 缺初始值不炸）。

## 效果（同一份 `long9` 工程重建，零 LLM）

| 指标 | 只有锚点修复（行走会累加） | **加上接力** |
|---|---|---|
| 伊恩最远位置 | (13.0, −12.6) | **(8.6, −6.0)**（= 计划里的目的地） |
| 位置 > 8 m 的镜头 | 18 | **5** |
| 构图分中位 | 70.0 | 69.8 |
| 构图门（≥70） | 32 / 64 | 30 / 64 |
| R001 越轴 | 2 | 10 |

构图门从 32 退到 30、R001 从 2 涨到 10，**是"人站对了地方"之后的真实读数**：
改前那些镜头是"镜头跟着一个站错位置的人"，分数好看但不是 SDL 里写的场面。
与锚点修复之前的基线（63.8 / 20）比，两步合起来仍是 **+10 镜**。

R001 涨到 10 是**新暴露出来的下一层**：§10.3 的轴线是**首镜一次性确立**的
（"首镜决定整场方向感"），而角色现在真的会走到别处 ⇒ 那条线不再代表后来的
两人连线，机位按同侧摆就会被判越轴。这属于"轴线要不要跟着走位重估"的
**规格裁决**，本轮不动，已记进 `ACCEPTANCE_STATUS.md` §六十四。

## 复算

```
blender --background --factory-startup --python work/_walk_once_probe.py     # 相对位移语义
blender --background --factory-startup --python work/_drift_probe.py -- \
    --project docs/evidence/20261003_chunked_long9/project --character 伊恩
blender --background --factory-startup --python work/_axis_rebuild_probe.py -- \
    --project docs/evidence/20261003_chunked_long9/project --out work/_handover_fix.json
python -m pytest tests/test_travelled_positions.py -q
```

## 仍未做（计划面）

LLM 的目标位置本身仍然会写到 8–9.5 m（`shot_041` 9.5、`shot_061` 8.2），
而场景没有"房间/边界"概念（`SceneSpec.room` 目前是空，只有机位会被它夹）。
下一件事是给**走位**也一个边界：提示词里给出场景尺寸与站位预算，
或在解析期拒绝越界目的地并回灌原因。
