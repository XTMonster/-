# 轴族**落字段**已在真跑里验证：`shots[].axis{pair, side_sign, status}`

日期 2026-10-07 01:4x。依据：轴族裁决（`../20261007-axis-family-ruling/`，两角色一致）——
"**批加字段**，但只许照抄生成器原生值：**有序 pair ＋ Z 符号（±1/0）＋ 可选 status**；
**刻意不叫 `axis_side`**；`left/right` 在约定定案前**不进成片**"。

## 一、真跑读数（不是单测，是导出产物）

```powershell
blender --background --factory-startup --python tools\run_export.py -- --offline --out work\_axis_check
# 读 work\_axis_check\export\shots.json
```

```json
"axis": {"pair": ["char_001", "char_002"], "side_sign": -1, "status": "correct"}
```

* **`pair` 是角色 id 的有序对**（`char_001 → char_002`）——`side_sign` 就是**相对这个次序**的
  叉积符号（`cinema/axis.py:136`）；换人次序它就会翻，所以**必须一起落盘**（这正是"约定"缺的那一层）。
* `status` 是 `axis_status`（`cinema/axis.py:452`）的原样输出：`correct` / `neutral` / `crossed`。
* **没有** `left`/`right` ——按裁决它们不进本批（索引侧 `left/right` 与产品侧 ±1 的校准**已经失败过一次**，
  见 `../20261007-axis-family-ruling/axis_convention_calibration.json`）。

## 二、落在哪三处（只加不改名）

| 位置 | 改了什么 |
|---|---|
| `block_director/layer3_engine/shot_builder.py` | `ShotBuildResult` 增 `axis_pair` / `axis_side_sign` / `axis_status`；在建镜循环里**从已有的 `context.axis` ＋ 已摆好的机位**取值（`axis_side_sign = camera_side_of(span[0], span[1], cam)`、`axis_status = axis_status(axis, cam_xy)`、`pair = axis.left_label/right_label` **原样**） |
| `block_director/delivery/manifest.py` | 每镜的 `shots[].axis{pair, side_sign, status}`；**生成器没算过时是 `[]/0/""`，不补默认、不猜** |
| `tests/test_manifest_fields.py` | 新增 `test_the_axis_field_carries_the_generators_native_values_only`：键名不含 `axis_side`、**不许出现翻译后的 `left/right`**、没算过时是空值 |

**golden 派生夹具按仓库流程重新生成**（`python tools/gen_golden.py`，**不是改断言**）——
只有 `fixtures/expected_shots_long.json` 变了（多了这一栏）。

## 三、全链覆盖

`docs/evidence/20261007-013420/`：HEAD `277b8e3`、`tree.json` `stable=true`、32/32 全过、
`failed_checks=['RK-13']`（就是那条已结案为"不可达"的红）。

## 四、未验证 / 边界

1. **`axis_side` 仍然没有绑定进诊断**：字段是落下来了，但索引侧还是 `left/right/neutral`，
   而校准已经证明它跟 `±1` **对不上**。按裁定，下一步是**弃 `left/right`、索引改用符号域**
   （知识侧换取值域＝换代），**本轮没做**。
2. `pair` 在别的运行里是不是也稳定给**角色 id**（本目录只看了 2 镜的离线导出，8 镜的
   `long21` 是**旧产物**、没有这一栏）——**没逐份核**。
3. `status` 只在**双人轴线存在**时才非空；单人镜头沿用已确立的 pair（本目录的 `shot_002`
   就是单人镜，pair 仍是两人那条轴）——这是继承行为，**但不是本轮新引入的**。
