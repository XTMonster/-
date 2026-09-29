# ADR-0012 构图门与断言卫生的防自证条款

状态：Accepted（v1.4 / P16）

## 背景

两处"看起来在判、其实判不出"的地方：

1. **构图评分**：主体几乎不在画里时，头部留白、遮挡、重心这些分项都会
   **真空成立**。实测把角色挪到 30 米外（完全出画），总分仍能到 60——
   于是"把镜头做坏 → 分数掉 ≥20"这条反向突变根本立不住，
   把阈值改成 `-1e9` 也能恒绿。
2. **测试套件**：`assert True` 这类恒真式不会被任何别的检查抓到，
   只会让覆盖率看起来很漂亮。

## 决策

- `cinema/composition.py::evaluate_composition` 增加硬闸：主主体的
  `inside_ratio() <= 0.05` 时，总分封顶 **20**；
- 构图门的分子只读 `shot_audit.composition_score ≥ composition_threshold`
  （**不得**用 `passed`——那还包含轴线/穿模/台词等非构图规则），
  阈值必须等于从审核器独立读到的默认 **70.0**；
- 新增 **无 bpy** 的静态检查 `tools/check_assertions.py`：扫"断言里没有任何
  数值/集合比较"的**恒真式**（`assert True`、`assert 1 == 1`、`assert not False`）。
  它刻意**不**把 `assert findings` 这类会因空集合失败的断言算进去。

## 后果

- `tools/blender_tests/test_composition_gate.py` 的通过率在 6 镜夹具上是
  100%，做坏 3 镜后掉到 0%，且每个被做坏的镜掉分 ≥20（实测 50.0 / 62.8 / 62.8）；
- `tests/test_assertion_hygiene.py` 既跑真实扫描（118 个文件、0 命中），
  也用合成片段钉住"恒真式必被报出、有鉴别力的断言不被误报"；
- **被否决的替代方案**：把阈值调低或把 `passed` 当分子——两者都会让
  "系统自己发现这一镜构图不成"这条用户价值失去判据。
