# v1.7 J 阶段冻结基线汇总（H3-③）

采集时间：2026-10-17（Asia/Shanghai），Blender 5.2.0 LTS
（hash fbe6228777e7 built 2026-07-14），HEAD `d3025db`。

采集脚本：`tools/collect_r_baseline.py`（load_project → build_scene →
逐镜 `BpyShotAuditor().audit()` → 统计 R020–R025 warning/error）。
只记录、不判红（附录 X1 A-V2-2 纪律）；阈值未改。

| 规则 | market4（6 镜） | market13（13 镜） | long61（64 镜） | 说明 |
|---|---|---|---|---|
| R020 | 0 | 0 | 28 | long61 为旧长片工程，多镜角色世界高度漂移 |
| R021 | 0 | 0 | 0 | 相机航向突变+复合上限，本批工程无触发 |
| R022 | 0 | 0 | 0 | 右向量投影翻转，本批工程无触发 |
| R023 | 0 | 0 | 0 | 二阶差分×fps²，本批工程无触发 |
| R024 | 0 | 0 | 0 | 分工 skip 与白模主体矛盾，本批工程无触发 |
| R025 | 0 | 0 | 0 | prompt 文本-实测运镜矛盾，默认关，未开测 |

逐镜明细见同目录 `baseline_<工程>.json`（`totals` / `per_shot`）。
另附 `r025_on_off_3shot.json`（J4 卡 3 镜开关对拍）：开关关时
`measured_camera` 键不出（零形状差），开关开时无运动采样同样不出键
（headless 采样管线依赖 bpy 场景；该基线证明默认关时零行为差）。
golden 夹具（附录 X1 第 1 份）走 `tests/test_golden.py` 的确定性对拍
（9 passed，见 H3-④ pytest 尾行），不在 Blender 基线内重复计数。
