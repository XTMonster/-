# ADR-0017 交付身份由证据唯一派生

状态：Accepted（2026-10-21）

## 背景

交付层同时存在 `full_video`、`final_video.mp4`、`final: true`、
`DeliveryReport.ok`、失败清单和 UI gate 等多个看似能回答“是否完成”的字段。
历史实现允许文件名或局部布尔值单独放行，导致以下风险：

- 含失败镜的 best-effort 包被消费方当成已批准成片；
- `ok` 只表示文件齐全，却被解释成质量 final；
- partial 包没有精确限制在通过镜头；
- 逐镜实际产物缺失时，汇总视频是否仍有资格交付不清楚；
- README、prompts、manifest、failures 与 UI 各自推导出不同的通过集合。

## 决策

1. `delivery_class` 是交付身份的唯一真源，闭集为 `final`、`partial`、
   `diagnostic`、`blocked`。
2. `final` 要求每个计划镜 evidence complete、必需门通过、adopted version
   即 best、完整序列审查通过、没有待复核变更，且实际产物集合精确覆盖全部
   计划镜。
3. `partial` 的选择集合必须精确等于 evidence 派生的 passed 集合；序列审查
   必须精确覆盖该集合，失败和待复核镜不进入视频、首帧、遮罩或深度。
4. `diagnostic` 可以选择全部计划镜并保留失败镜 best，但必须使用 diagnostic
   文件名和文案；不得发布 `final_video.mp4`、`detail_final_manifest.json`
   或 `delivery_class=final` 别名。
5. `blocked` 无条件 fail closed。缺证据、身份字段冲突、用户编辑冲突、必要
   门阻塞或实际逐镜产物集合不匹配都降为 blocked。
6. `DeliveryReport.ok` 只表示包已经完整落盘且内部可用；是否 final 只能读
   canonical `delivery_class`。`final_video.mp4` 或旧 `final: true` 不能单独
   放行。
7. `shots.json`、README、prompts、failures、UI/headless summary 和导出报告
   必须消费同一个 delivery quality 载荷，不得重新计算阈值或通过集合。
8. 文件名固定区分身份：final 用 `blockout_full.mp4`，partial 用
   `blockout_partial.mp4`，diagnostic 用 `blockout_diagnostic.mp4`，blocked
   不生成合片交付。

## 后果

- 任何消费方都必须先验证顶层与嵌套 delivery class 一致；
- 一个包可以 `ok=true` 但不是 final；
- 实际逐镜产物集合成为交付门的一部分，不能只靠汇总视频存在；
- 全失败运行可以保留 diagnostic 审查片，但 pipeline final gate 仍为
  blocked；
- 旧调用方若没有 canonical quality 结果，只能走显式 legacy 路径，不能借此
  冒充 final。

## 验证

- `tests/test_delivery_quality.py` 固定四种身份、严格 80.0、pending、空镜、
  子集序列和产物一致性；
- `tests/test_detail_pipeline.py` 固定 final/partial/diagnostic/blocked 的
  文件暴露面；
- `tests/test_headless_detail_gate.py` 与 `tests/test_pipeline_ui_inputs.py`
  固定 UI/headless 只接受 canonical final；
- `tools/blender_tests/test_phase6_delivery.py` 固定 blocked 不创建交付树；
- 当前代码的真实 Blender 导出与全量 pytest 是验收证据，历史 final 文件不算。
