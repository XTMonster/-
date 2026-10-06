# §7 D1b 落地：躯干换成**圆角方体** —— 顺带抓出并修掉两个**探针缺陷**（判据一个字没动）

日期 2026-10-06 23:1x。裁决：人工裁决通道 **GLM-5.3** 判 **② 圆角方体**
（同一问 GPT-6A 当晚也独立回了②，两份一致）。落地与证据见下。

## 一、生产改了什么（只有构造，没有常量）

* `block_director/layer3_engine/character_system/character_factory.py`
  —— 新增 `_add_rounded_box_body()` ＋ 常量 `BODY_BEVEL_RATIO = 0.25`、`BODY_BEVEL_SEGMENTS = 4`；
  躯干从 `primitive_cylinder_add(radius=BODY_RADIUS, depth=BODY_HEIGHT)` 换成
  **等外接盒**的圆角方体（cube → `transform_apply(scale)` → Bevel(`0.25 × r`) → apply）。
* **宽/深/高与所有定位常量一个都没动**——`docs/evidence/d1b_body_shape/README.md` 早量过：
  两种形状的世界 AABB `max_delta = 0.0`，所以 bbox／构图常量**不需要**补偿。
* 探针 `tools/blender_tests/test_character_body_ab.py` 的语义随之改成**回归对拍**：
  A ＝**显式**建的旧圆柱、B ＝**显式**建的圆角方体（不再让 A 走工厂默认，否则会退化成"自己跟自己比"），
  并新增 `d1b_shipped_torso_is_the_rounded_box` 钉住**生产默认**真的是新形状。

## 二、四个 D1b 检查（`blender --background --factory-startup --python tools/blender_tests/test_character_body_ab.py`）

| 检查 | 读数 |
|---|---|
| `d1b_torso_footprint_unchanged` | AABB 两种形状都是 `(0.5, 0.5, 0.748)`，**`max_delta = 0.0`** |
| `d1b_anchor_contract_unchanged` | `head_center_z 1.3855` / `label_anchor_z 2.0`，两形状**逐位相同** |
| `d1b_silhouette_differs` | MS/front **10194 px（4.42%）**、CU/left **12739 px（5.53%）**（下界 460、上界 69120） |
| `d1b_shipped_torso_is_the_rounded_box` | 生产 152 顶点 == 圆角方体参照 152、≠ 圆柱 64；AABB 仍 = `(0.5,0.5,0.748)` |

⇒ 四条全绿（`passed` 4 / `failed` 0）。剪影差分的两个数**与改形状之前那次测量逐位相同**
——说明这一支的 A/B 对拍在重构后仍然是同一件事。

## 三、换形状之后**两条探针检查当场变红**：都不是产品回归，是**探针缺陷**

改完先跑受影响的 Blender 探针，`tools/blender_tests/test_phase2_motion.py` 报
**2 条红**：`rk8_body_tilt_matches_the_registered_angle`（12° 变成 **90°**）与
`render_frames_differ`。逐条查到底：

### 缺陷 A：幂迭代的**种子陷阱**（RK-8 量错了，不是产品错了）

`_principal_axis()` 用世界空间顶点云的协方差做幂迭代、**种子写死 `+X`**。幂迭代只会放大
初始向量沿某个特征向量的分量——**若种子与主轴正交，它永远爬不到主轴上去**。

* **圆角方体**的顶点云在倾斜时关于 X 轴**精确对称**（`cov_xy = cov_xz` 在浮点里恰好为 0）
  ⇒ 迭代被锁死在 X 上 ⇒ 报 **90°**；
* 同一套场景、同一动作，只把躯干换回**旧圆柱**：n 边形顶点的 `cos/sin` 留下 ±1e-17 级残差，
  迭代反而爬得上去 ⇒ 报 **12.0°**。

本目录 `probe_rk8_diag.py` 把这对**同场景对照**跑出来（复算命令见文件头）：

```
旧实现（seed = +X）：圆角方体 measured_deg = 90.0   ／ 圆柱 measured_deg = 12.0
新实现（四种子取 Rayleigh 商最大）：圆角方体 12.0 ／ 圆柱 12.0   （principal 都是 (0, 0.2079, -0.9781)）
```

⇒ **修的是仪器**：`_principal_axis()` 改成四个种子（±X/±Y/±Z 的代表 ＋ 归一化 `(1,1,1)`）
各跑一遍、取 Rayleigh 商最大的那个。**判据（主惯性轴与 +Z 夹角 = 登记倾角 ±3°）一个字没动**，
改的只是"能不能量到主轴"。并新增后置条件检查
`rk8_principal_axis_is_the_dominant_one` 把它钉住（实测返回 17.72 ＞ 三个坐标轴的 7.21/7.67/17.27
⇒ 旧实现当场红）。

### 缺陷 B：`render_frames_differ` 用**均值亮度**当"画面变了"的代理，一线之隔

旧口径 `|luma_48 − luma_01| > 0.005`；换形状后实测 **0.0048**（0.27213 vs 0.26737）——差 0.0002 就翻。
判据的**意图**是"这一帧和那一帧不是同一张图"，所以改成**直接数变了的像素**：
`floor(1% 画面 = 144 px) ≤ changed ≤ ceiling(60% = 8640 px)`。实测 **changed_pixels = 2252**
（三个亮度值仍原样打出来，便于与历史对照）。**这不是放宽**：新口径有**下界也有上界**，
比"均值动了一点点"更贴意图、更不易被着色变化糊弄。

### 修完的结果

`test_phase2_motion.py` **12 passed / 0 failed**（含新钉的那条后置条件），
`test_character_geometry.py` **5 passed / 0 failed**（RK-4/RK-14/RK-15 全绿）。

## 四、未验证 / 边界（如实挂）

1. **完整 32 步链还没在改动后的树上跑过**——本目录记的是**受影响的单支探针**；
   全链结果（含 RK-9 掩膜、标签烘焙、群众/特效这些像素级检查是否受形状影响）**待补**。
2. `rk8` 的**数值后置条件**只证明"返回的是 Rayleigh 商最大的特征向量"，
   没有证明"它与几何主轴一致"——后者由 `r8` 的实测值（两种形状都 12.0°）间接支持。
3. 圆角半径比例 `0.25 × BODY_RADIUS` 沿用**已出图、被裁决的那一对**；**没有**扫过别的比例。
