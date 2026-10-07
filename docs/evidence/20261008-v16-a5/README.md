# A5：自审登记进入本次运行的交付包

## 已实现

- `request_self_review` 的现有登记/GUI行为不变。
- 运行快照保留原 `review_requests` 总数，同时输出深拷贝
  `self_review_requests[]`，无人值守调用者能得到逐镜明细。
- 两个 CLI 与两个 GUI 运行导出入口都传递登记明细。
- `shots.json` 每镜包含 `needs_review: bool`、`review_request_count: int`。
- README 固定标题「待人工复核」，逐镜列真实登记次数。
- README 内容组装移至纯层 `delivery/readme.py::render_readme`；
  exporter 保留原 `_readme` 入口并消费同一个实现。
  原有标题、尺寸/帧率、使用说明、标签、合片、轨迹、深度范围及告警内容保留。

## 补线范围与自审

原 A5 卡漏列实际调用者。为满足同一项“无人值守落产物”需求，本轮补入：

- `driver.py::snapshot`：原摘要只有整数，不能给 CLI 提供明细。
- `tools/run_headless.py`、`tools/run_export.py`：实际无人值守导出装配者。
- `delivery/readme.py`：让既有 README 内容有可正常导入的纯层测试入口。
- 已登记探针 `test_phase6_delivery.py`：新增真实控制登记→场景构建→渲染导出对拍；
  原十项探针全部保留，不需新增探针清单条目。
- `fixtures/expected_shots_long.json`：仅由 `python tools/gen_golden.py`
  重新生成；差异恰为64镜各增加上述两个交付字段，其他生成文件无差异。

这是原需求的生产/消费接线，不新增功能或改低判据。原 README 两条测试的
内容断言逐字保留，仅改为调用真正的纯层入口，并使用 `tmp_path` 创建目录。
不安装或伪装 bpy，不跳过原失败。

## 真实验证

- `red.xml`：改前新增用例与原用例暴露7项失败。其中初版运行测试夹具误将
  完整 Plan 的引擎字段送给 Stage A schema；修正为合法工具请求后单独复跑，
  确认真实失败是 `KeyError: self_review_requests`，而非错误夹具造成的假红。
- `green-golden.xml`：A5、golden、manifest、控制工具、纯层边界合计45项通过。
- `default-and-review.xml`：默认值裁定同步后，相关49项通过。
- `blender-delivery.log`：Blender真实执行 `test_phase6_delivery.py`，
  **11项通过、0失败**。新增项实测：
  `registered=2`、`rendered_shots=2`、
  `review_counts={shot_001:2, shot_002:0}`；
  两镜真实mp4、首帧和README均由生产导出器生成。
- `full-before-default-ruling.xml`：全量 **2879 passed / 2 failed / 1 skipped**。
  仅剩两条过时默认5断言；其原始失败保留。
  同步范围已由 `../20261008-v16-default-ruling/decision.json` 单独裁定，
  不是修改检索质量阈值。

## 边界与后续

本项只证明“本次运行→直接交付”。旧工程重建/回放恢复历史复核登记的持久化，
本轮未实现或验证，不扩张声明。A2可信角色表、A3真实工具错误引导、
A4 GUI/CLI超时覆盖的审查缺口仍待修，阶段A与整个v1.6均未验收完成。
完整链测试将在固定工作树上运行，结果另行落盘；不会用本探针替代全链验收。
