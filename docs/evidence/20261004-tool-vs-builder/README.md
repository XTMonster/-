# 修复工具与主构建器**解出的不是同一台相机**（P14-84）

## 这一轮要回答的问题（§79.3）

long16 那一跑的统计是：**104 个修复回合、204 次工具调用，其中"改动类"只有 9 次**
（`get_scene_state` 100、`search_knowledge` 45、`check_composition` 29、`check_axis` 21）。
而在**真的动了手**的 7 个回合里，复核结果 **0 个通过**——4 次 `setup_camera` 之后
构图分一律掉到 **20.0**。

先量"改动类工具的比例与收益"（`_repair_yield.py` 的结论），再问一句更基本的：
**按计划自己的参数把同一镜的机位重设一次，本该什么都不变。它变了吗？**

## 结论：变了，而且是系统性的

`work/_tool_vs_builder_probe.py`——重建冻结工程 → 逐镜记录基线 →
用**计划自己声明的** `shot_type/side/lens` 调一次工具 → 再记录一次。

| 工程 | 工具 | 构图变差 | 由通过变不通过 | 最差一镜 |
|---|---|---|---|---|
| long16 | `setup_camera` | **34 / 64** | **10** | `shot_027` 83.2 → 20.0 |
| long16 | `reframe` | **9 / 64** | **3** | `shot_019` 91.9 → 57.1 |

修后（同一批工程、同一条命令）：

| 工程 | `setup_camera` 变差 / 翻红 | `reframe` 变差 / 翻红 |
|---|---|---|
| long11 | 0 / 0 | 0 / 0 |
| long12 | 0 / 0 | 0 / 0 |
| long15 | 0 / 0 | 0 / 0 |
| long16 | 0 / 0 | 0 / 0 |

四份工程 × 两个工具 × 64 镜 = **512 次重设，全部零差**。

## 根因：工具层自己抄了一份解算

`setup_camera` 以前自己拼 `axis_dir/axis_side` 再直调 `place_camera_for_shot`，
而主构建走 `place_shot_camera`。两者差的不是一点：

| 构建器有 | 工具层丢的 |
|---|---|
| 视线留白对准点偏移（§10.4） | ✗ |
| 头顶留白 `HEAD_ROOM_AIM_M`（§六十九） | ✗ |
| `spec.room` 房间钳制 | ✗ |
| **逐镜**轴侧（顺序状态机 `_axis_sides_used`） | 读的是全片一个常数 `context.axis.established_side` |
| 先 `frame_set(该镜首帧)` 再读人在哪 | 读的是**当前帧** |
| 声明式运镜（§3.6） | 重建相机对象后**没重放** |

`reframe` 是同一类：抬头写着"与主构建、setup_camera 共用同一套参考系与同一套
side 解析"，代码却写死 `side="front"` 并直调 `solve_framing`。

### 修法

1. **唯一入口**：两个工具都走 `shot_builder.place_shot_camera`
   （`reframe` 多传 `reuse=`，复用同一台相机对象与同一个对准 Empty）。
2. **轴线记账**：`axis_for_shot` 让工具读构建器**当时用过**的那张表；
   轴还没确立的镜头单独记在 `_axis_absent_shots`（塞 `None` 进
   `_axis_sides_used` 会把 `rule_checker._axis_sides` 的 `int()` 打崩——踩过）。
3. **运镜一份实现**：`apply_declared_movements` 由主构建与 `setup_camera` 共用。
4. **删干净**：`release_shot_camera` 连相机**数据块**与对准 **Empty** 一起放掉。
   只删对象会留下同名残留，下一次建的相机只能叫 `….001`，而按名字查对准点的
   地方（`_shot_target_object`、主构建的运镜段）拿到的还是**旧的那一只**。

## 过程中被自己的测量抓住的一个错

把运镜落地抽成共用函数时，第一版在函数里调 `get_context()` 取相机——
而 `build_scene` 直到**收尾**才 `set_context(context)`，构建期间那个全局上下文
是**上一次**的场景（新检出上干脆是 None）。后果：整场 64 镜的运镜被静默跳过，
相机 0 关键帧。是 `kf_probe.py`（数 `bpy.data.actions` 里的相机 action）把它抓出来的，
不是任何断言。现在 `camera=`/`target=` 是**必传**参数，并有守门钉住。

## 复现

```
blender --background --factory-startup --python work/_tool_vs_builder_probe.py -- \
    --project docs/evidence/20261004_chunked_long16/project --out work/_x.json
blender --background --factory-startup --python work/_tool_vs_builder_probe.py -- \
    --project docs/evidence/20261004_chunked_long16/project --tool reframe --out work/_y.json
python work/_repair_yield.py docs/evidence/20261004_chunked_long16/audit_log.jsonl
```

守门：`tests/test_repair_tool_matches_builder.py`（4 条，源码级反漂移）＋
`tools/blender_tests/test_phase4_repair.py::repair_tools_reproduce_the_builder`
（运行时不变量：两个工具各跑一遍，位置/焦距/对准点/关键帧数/对象与数据块名
全部必须逐字节相同，且 `reframe` 不许换对象）。

## 仍未做

* 这一轮**没有**重跑真模型（n=1 的长跑方差本来就大）。验的是**结构性不变量**，
  不是"通过率因此变高"。
* 修复回路剩下的问题仍在：只读工具占比 95%（195/204）——工具集与提示词该不该
  更硬地约束，是下一步。
