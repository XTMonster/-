# `20261009-v16-v4-attempt` — v1.6 G2 第一次 DeepSeek V4 Pro 真跑与三处代码修复

| 项 | 值 |
|---|---|
| 通道 | DeepSeek 官方 API `deepseek-v4-pro`（思考型；`--tool-choice-mode auto`、`--reasoning-effort max`、`--llm-max-tokens 24576`）|
| 剧本 / 预设 | `fixtures/shotlist_market_v10_nodes1_4.txt`（13 镜）/ `hd16x9` / EEVEE |
| 代码基线 | `89404b0` ＋ 本会话三处未提交修复（见下）|
| run_id | `4bee011cde08`（71 次 LLM 调用后被主线主动停止——发现修复风暴，不必再烧）|

## 结论（先结论后证据）

这一跑再次判红，且把三个**代码侧**根因钉死了（都不是换模型能解决的）：

1. **R001 "机位在错侧"的参照系不一致**（最大红源）：构建器按"摆位时的连线"定侧，
   审核却拿"走位后的当前连线"量相机。角色一走位、线一转，没挪过的机位被批量误判
   （本跑 **460 次** error，19 次 unbridged_rebuild、1 次 screen_flip 之外全部是它），
   修复提示又让模型挪机位 ⇒ 引入 `subject_behind_camera` ⇒ 回滚 ⇒
   **455 次 `repair_rolled_back`** 的振荡风暴。
2. **校验域与执行域不一致的假 invalid**：prop 类 `toward`（执行层收 `left/right/...`，
   解析层按"必须是数字"误拒）、`target_position`（schema 要 3 项，执行层收 2–3 项）。
3. **交付接线缺口**（同前一轮结论）：面板路径 shots.json 不带 `audit_pass_rate`、
   README 无标签全帧自检段、`label_overlap_report` 事件无运行时生产者。

## 本会话的修复（文件:位置）

* `rule_checker.py::_camera_on_wrong_side`：参照线优先取构建器记录的摆位线
  （`context._axis_lines_used`），与期望侧同源；走位跨线仍由
  `crossing_events`/`_axis_rebuild` 判。
* `shot_builder.py::_axis_for_placement`：摆位时把那条线记进
  `context._axis_lines_used`。
* `rule_checker.py::check_shot`：空镜（无角色）豁免"机位在错侧"（观众看不到任何
  左右关系）；单人镜轴侧语义不变。
* `motion/model.py`：prop `toward` 与执行层同一 `_axis_from_toward` 判域；
  `TOWARD_WORDS` 方向词闭集进 `action_param_domains` 单一真源（提示词随之自动更新）。
* `editor.py::EMIT_SHOT_DRAFT_PARAMETERS`：`target_position` minItems 3 → 2
  （执行层 2–3 项同域）。
* 交付接线：`modal_operator.py` 传 `audit_pass_rate`；`delivery/readme.py` 增
  「## 标签全帧自检」段；`driver.py::label_overlap_event_fields` 在每次构建后写
  `label_overlap_report` 审计事件（`fullframe_verify=true`）。

新增/扩展测试：`tests/test_readme_label_overlap.py`（新）、
`tests/test_action_param_values_are_checked.py`、
`tests/test_action_params_are_constrained.py`、
`tools/blender_tests/test_operator_end_to_end.py`（audit_pass_rate 对拍）、
`tools/blender_tests/test_scene_contract.py`（空镜豁免 + 摆位线两个探针）。

## 本跑读数（`runs/audit_log.jsonl` 过滤 `run_id=4bee011cde08`）

* `llm_request` 71、`draft_invalid` 5、`repair_invalid` 7、`react_invalid` 21；
* `scene_built` 471、`shot_audit` 499、`repair_applied` 12、`repair_rolled_back` 455、
  `shot_degraded` 19（shot_001–012）；
* 轴错：error 480（wrong_side_current_line 460 / unbridged_rebuild 19 /
  screen_flip 1）、warning 487；
* guard_warning 类型分布：framing_too_tight 947、occlusion 907、edge_clip 499、
  thirds_deviation 477、subject_not_visible 45、headroom_off 19 …；
* `label_overlap_report`：1656 帧里 10 帧交叠 >5%（最高 34.6%）——标签全帧判据
  在本剧本上仍未达标，下一轮需归因是拥挤帧容量还是插值残留。

## 未验证 / 剩余风险

* 本跑被主线主动停止，未到 FINISHING：无 `plan_received` 事件、无最终交付包，
  无法零 LLM 重建终版计划做逐镜归因（下一轮跑完再归因）。
* 构图分 30–62 的根因仍是**站位与视线共线**（v3 探针已证实：9 条射线全部命中
  站在机位与主体之间的另一角色），求解器/计划提示是否要加"清线站位"约束，
  待下一轮归因后定，不预先放宽任何阈值。
* `char_a/char_b`、`伊萨克`、`琳` 等表外 id 与"辩护缺 rule"仍由模型侧产生；
  A2 闸按设计拒绝并重问，本轮未改判据。
