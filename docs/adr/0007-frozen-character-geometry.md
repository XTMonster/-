# ADR-0007 角色几何冻结为 1.70 与"头球相切"

状态：Accepted（v1.4 / P10）

## 背景

v1.3 的角色几何是 `总高 1.45 / 髋 0.40 / 躯干顶 1.10 / 头心 1.10`：
头球中心**正好等于躯干顶**，于是球的下半埋进躯干，渲染出来"只看到半个球"。
眼睛用 `y = sqrt((head_r - eye_r)² - eye_dx²)` 内切在头球里，突出量恒为 0，
Workbench 下根本渲染不出眼睛。更麻烦的是同一组旧数字被**抄在八个地方**
（`cinema/framing.py`、`composition.py`、`sdl_validator.py`、
`composition_guide.py`、`knowledge/corpus.py`、`cards_cinematography.py`、
`motion/model.py`、`character_factory.py`），改一处不会有任何测试变红。

## 决策

冻结一套**按比例定义**的几何，并让**所有**消费者从同一个 profile 推导：
`total_height = 1.70`、`head_ratio = 0.37`、`torso_ratio = 0.44`、
`leg_ratio = 0.19`。

- 头球与躯干顶**相切**：`head_center_z = leg_h + torso_h + head_r`（容差
  `neck_gap = 0 ± 0.005`）；
- 眼睛按突出量定义：`d = head_r - eye_r + p`，`y = sqrt(d² - eye_dx²)`，
  `p ∈ [0.012, 0.020]`（默认 0.015）；
- 单一真源是新增的**无 bpy** 模块 `block_director/cinema/anchor.py`
  （`CharacterProfile`），`cinema/framing.py` 的 `SUBJECT_HEIGHT` /
  `HEAD_TOP` / `EYE_Z` / `CHEST_Z` / `WAIST_Z` / `KNEE_Z` 与整张 `SHOT_FRAME`
  都从它派生；
- `contracts/config.py::validate` 新增 **CFG_301**：profile 自身不自洽、
  或与 `cinema/framing.py` 的常量不一致，启动前直接报错。

## 后果

- 头球可见比例 ≥99%、含头部景别头顶留白 ≥8% 成为**可渲染验证**的判据
  （`tools/blender_tests/test_character_geometry.py` 的 RK-14 / RK-15）。
- 取景画面高度沿用 v1.3 的**比例**（`h = 比例 × 总身高`）而不是按身体部位
  反推：后者会让中远景突然收紧，两人镜的构图分掉到 70 线下（实测 68.4）。
- **被否决的替代方案**：① 只改 `character_factory.py` 的常量——八个消费者
  会继续量旧几何，而且不会有测试变红；② 把 profile 放进 `layer3_engine/`——
  那个包的 `__init__.py` 会拉起 bpy，纯层的 `cinema/*` 与 `tests/test_framing.py`
  会被一起拖下水。
