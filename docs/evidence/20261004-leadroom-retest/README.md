# P14-70：视线留白**重测通过**——三份冻结工程，构图门 30→41 / 17→21 / 25→24

**结论**：`cinema/station.aim_offset_for_lead_room` ＋ `solve_framing(aim_offset_x=…)`
（把单主体镜头的对准点横移 1/6 幅宽，让主体落到背向视线的那条三分线上）在
2026-10-04 第一次接上时是**净负**（`docs/evidence/20261004-leadroom-finding/`：
构图分中位 64.7 → 55.8、25 镜降）。那次负结果的原因是**机位锚点还指着剧本起始
站位**——主体本来就在画框边缘，再横移就出画。

锚点（§六十三）与走位接力（§六十四）落地之后，**同一支探针、同一批冻结工程**
重测（只切换这一个开关）：

| 冻结工程 | 构图门 ≥70（关 → 开） | 构图分中位（关 → 开） | 终审逐镜通过（关 → 开） |
|---|---|---|---|
| `long9` | 30 → **41** | 69.8 → **80.3** | ——（该工程只有重建探针） |
| `long11` | 17 → **21** | 55.2 → **59.2** | 17 → **21** |
| `long12` | 25 → 24 | 65.9 → 65.1 | 15 → **16** |

三份合计 **+14 个构图门镜头**，只有 long12 一例 −1（该工程有几镜的主体本来就
贴边，横移把它推得更偏）。**决定：接上**——它是 §10.4 评分模型想要的东西
（`lead_room` 要朝向侧留白、`rule_of_thirds` 要 1/3 交点），而且没有动任何阈值。

## 复算

```
# 关闭：把 shot_builder.place_shot_camera 里的 aim_offset 两行注释掉再跑
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261004_chunked_long11/project \
    --out docs/evidence/20261004-leadroom-retest/long11_with_offset.json
blender --background --factory-startup --python work/_axis_rebuild_probe.py -- \
    --project docs/evidence/20261003_chunked_long9/project
```

六个 JSON 是逐镜原始产物（`passed` / `score` / `errors` 或六分项与机位坐标）。

## 守门

`tools/blender_tests/test_phase3_audit.py::lead_room_shifts_single_subject_shots_only`
——单主体镜头的对准点必须**离开主体**（>0.15 m），双人镜头的对准点必须**留在
两人中点**（<0.05 m），且单主体那一镜的警告里要出现"视线留白"。这条钉的是
"接上了"，免得哪天被顺手摘掉。

（机制本身的纯层用例仍在 `tests/test_lead_room_aim.py`：8 个 side × 2 个轴侧、
镜像保持夹角、正对镜头不偏移、量纲是幅宽的 1/6。）

## 未验证

* 还没有用新树跑真模型：这里的 30→41 / 17→21 / 25→24 都是**同一份工程重建**
  的引擎账；下一趟 64 镜真跑才是端到端数字。
* long12 的 −1 说明"主体贴边"时横移仍可能帮倒忙——彻底的解法是让偏移量按
  **主体在画框里的余量**收窄（需要投影盒，属 bpy 侧），本轮没做。
