# P14-71：竖直对准（抬高 0.15 m）——三份冻结工程合计 +13 构图门

**结论**：GLM 5.3 会诊（`docs/evidence/20261004-glm-consult-axis/`，F3）提示
"先按分项拆根因"。照做之后实测到：三份冻结工程里 `rule_of_thirds` 是 **61–63/64
镜**的弱项（出现最多的那一项），而根因是**竖直方向从没对准过三分之一**——
`work/_box_center_probe.py` 量到主体盒中心的**中位纵向偏差 0.13**（横停在画面正中）。

`work/_aim_sweep_probe.py` 把对准点按 −0.4…+0.4 m 扫了一遍（long12 的 40 个
单主体镜）：

| 对准点偏移 | 合计得分增益 |
|---|---|
| −0.4 m | +37.7 |
| −0.2 m | +34.0 |
| −0.1 m | +2.2 |
| **+0.1 m** | **+129.8** |
| **+0.2 m** | **+214.1** |

⇒ 取 **+0.15 m**（夹在两个最优步长之间，避免贴着扫描点选参）。`SHOT_FRAME.target_z`
（§2.2 D2 的**冻结常量**）一个字没动，只加了一层可测的取景偏移
（`solve_framing(aim_offset_y=…)` ＋ `station.HEAD_ROOM_AIM_M`），只作用于单主体镜。

## 三份冻结工程（同一支复评器，只切换这一个偏移）

| 工程 | 逐镜通过（横 → 横+竖） | 构图门 ≥70 | 构图分中位 | COMPOSITION 条数 |
|---|---|---|---|---|
| `long9` | —— | 41 → 39 | 80.3 → 77.3 | —— → 25 |
| `long11` | 21 → **25** | 21 → **25** | 61.9 → **64.1** | 43 → **39** |
| `long12` | 16 → **22** | 24 → **35** | 65.1 → **73.5** | 40 → **29** |

合计 **+13 个构图门镜头**（41+21+24 = 86 → 39+25+35 = 99）、逐镜通过 **+10**
（long11 +4、long12 +6）。`long9` 的构图门 −2，但它的逐镜通过 29（该工程在
只有横向偏移时没跑过逐镜复评，无法成对比较）——如实记。

## 复算

```
blender --background --factory-startup --python work/_composition_items_probe.py -- \
    --project docs/evidence/20261004_chunked_long12/project   # 哪一维在拖后腿
blender --background --factory-startup --python work/_box_center_probe.py -- \
    --project docs/evidence/20261004_chunked_long12/project   # 盒中心离三分之一多远
blender --background --factory-startup --python work/_aim_sweep_probe.py -- \
    --project docs/evidence/20261004_chunked_long12/project   # 抬高多少最划算
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/<run>/project --out <json>
```

## 守门

* 纯层：`tests/test_lead_room_aim.py::test_the_vertical_aim_can_be_raised_without_moving_the_camera`
  （对准点抬高 0.15 m、机位与焦距不变）；
* 场景层：`tools/blender_tests/test_phase3_audit.py::lead_room_shifts_single_subject_shots_only`
  现在同时钉住"单主体抬 `HEAD_ROOM_AIM_M`、双人保持 `SHOT_FRAME.target_z`"。

## 未验证 / 边界

1. 还没有用新树跑真模型；这里是同一份工程重建的引擎账。
2. `long9` 的构图门 −2 说明抬得可能偏多或偏少（该工程的镜头分布不同）；
   彻底的解法仍是**按主体在画框里的余量**自适应（GLM F3 的主张），本轮没做。
3. 双人镜头仍是 `_thirds` 拿**某个人的盒子**去比三分之一交点——两人分开时几乎
   不可能命中。这属于**评分口径**（不是求解器），要动必须先当作规格问题讨论，
   本文件只记录现象（弱项计数 61–63/64 里包含这些镜）。
