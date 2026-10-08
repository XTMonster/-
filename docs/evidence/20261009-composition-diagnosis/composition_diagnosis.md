# 构图门归因诊断（B1 / D-04）

- 运行目录：`E:\白模预演codex\work\_g2_glm3`
- 最终计划来源：`plan_received`
- `config.scene.extent_m`：12
- 重放代码：`E:\白模预演codex`（工具自身所在代码树；工作区含并发未提交改动）
- 诊断方式：读 `audit_log.jsonl` + `llm_trace.jsonl` → 零 LLM 重建计划 → Blender headless 重放场景 → 逐失败镜测量。
- 红线：**不修改被诊断代码**；**归因不给出任何阈值让步**（PASS_SCORE 保持 70）。

## 输入侧缺失（原样报告，不猜）

- 缺少 project.bdproj（找过：项目根与 runs/ 下均无）：无法与落盘工程对拍；诊断改由 audit_log + llm_trace 零 LLM 重建，不影响归因。

## 计划重建

- 重放草案 42 条：接受 24、拒绝 18。
  - shot_002（llm_trace/editor）拒绝：hand_to 的 toward 必须是数字（当前 'camera'）
  - shot_003（llm_trace/editor）拒绝：hand_to 的 toward 必须是数字（当前 'screen_left'）
  - shot_005（llm_trace/editor）拒绝：hand_to 的 toward 必须是数字（当前 'screen_right'）；hand_to 的 toward 必须是数字（当前 'screen_right'）；hand_to 的 toward 必须是数字（当前 'screen_right'）
  - shot_007（llm_trace/editor）拒绝：第 3 个拍点的 pace='sharp' 不在闭集内（slow、normal、brisk）；第 4 个拍点的 pace='sharp' 不在闭集内（slow、normal、brisk）
  - shot_008（llm_trace/editor）拒绝：turn_head 不认识的参数 ['pitch_deg']；允许的键是 ['angle_deg', 'angle', 'degrees']
  - shot_009（llm_trace/editor）拒绝：body_tilt 不认识的参数 ['cycles']；允许的键是 ['angle_deg', 'angle', 'degrees', 'axis', 'toward']；body_tilt 不认识的参数 ['cycles']；允许的键是 ['angle_deg', 'angle', 'degrees', 'axis', 'toward']
  - shot_010（llm_trace/editor）拒绝：第 2 个拍点的 target='伊恩' 既不在角色表也不在锚点表里；第 3 个拍点的 target='伊恩' 既不在角色表也不在锚点表里
  - shot_012（llm_trace/editor）拒绝：walk_to 的 from 必须是坐标（2–3 个数字的数组，当前 'screen_right'）；walk_to 的 to 必须是坐标（2–3 个数字的数组，当前 '莉莉安娜身旁礼貌距离'）；turn_body 不认识的参数 ['axis']；允许的键是 ['angle_deg', 'angle', 'degrees']
  - shot_002（audit_log/repair/react）拒绝：enter_from 的 from 必须是坐标（2–3 个数字的数组，当前 'screen_right'）；walk_to 的 speed 只能是 run/walk（当前 0.7）；turn_body 不认识的参数 ['yaw_deg']；允许的键是 ['angle_deg', 'angle', 'degrees']
  - shot_005（audit_log/repair/react）拒绝：look_at 不认识的参数 ['target_position']；允许的键是 ['yaw_deg', 'pitch_deg']；body_tilt 不认识的参数 ['lean_deg']；允许的键是 ['angle_deg', 'angle', 'degrees', 'axis', 'toward']
  - shot_006（audit_log/repair/react）拒绝：look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']；body_tilt 不认识的参数 ['lean_deg']；允许的键是 ['angle_deg', 'angle', 'degrees', 'axis', 'toward']
  - shot_007（audit_log/repair/react）拒绝：look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']；look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']；body_tilt 不认识的参数 ['lean_deg']；允许的键是 ['angle_deg', 'angle', 'degrees', 'axis', 'toward']
  - shot_007（audit_log/repair/react）拒绝：look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']；look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']；body_tilt 不认识的参数 ['lean_deg']；允许的键是 ['angle_deg', 'angle', 'degrees', 'axis', 'toward']
  - shot_008（audit_log/repair/react）拒绝：turn_body 不认识的参数 ['yaw_deg']；允许的键是 ['angle_deg', 'angle', 'degrees']；body_tilt 不认识的参数 ['lean_deg']；允许的键是 ['angle_deg', 'angle', 'degrees', 'axis', 'toward']
  - shot_008（audit_log/repair/react）拒绝：turn_body 不认识的参数 ['yaw_deg']；允许的键是 ['angle_deg', 'angle', 'degrees']；body_tilt 不认识的参数 ['lean_deg']；允许的键是 ['angle_deg', 'angle', 'degrees', 'axis', 'toward']
  - shot_010（audit_log/repair/react）拒绝：第 1 个拍点的 pace='sharp' 不在闭集内（slow、normal、brisk）
  - shot_011（audit_log/repair/react）拒绝：look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']
  - shot_011（audit_log/repair/react）拒绝：look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']

## 逐镜诊断表

| 镜号 | 景别 | 记录分 | 重放分 | 主体站位 (x,y) | 机位 (x,y,z) | 焦距 | 首帧目标点 (x,y,z) | 目标-主体 (m) | 六分量 | 归因 | 决定性证据 | 建议修卡 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| shot_011 | MS | 56.0 | 56.0 | [2.25, 0.0] | [-0.3438, 0.0, 0.9497] | 28.0 | [2.25, -0.5558, 1.0997] | 0.5558 | headroom 1.00 / lead_room 1.00 / rule_of_thirds 0.47 / balance 0.52 / occlusion 0.00 / framing 0.63 | **solver_no_solution** | camera_matches_solver=True；replayed_score=56.0；threshold=70.0；components.headroom=1.0；components.lead_room=1.0；components.rule_of_thirds=0.465 | 卡 D-12（CU/ECU 像素可测约束反解 + readback_shot_size()，不满足时自动调距离档；B4 的 reframe 菜单）——不动 PASS_SCORE |

## 逐镜根因注记（由实测证据机械生成）

- **shot_011**（MS）：弱项：rule_of_thirds=0.47、balance=0.52、occlusion=0.00、framing=0.63；首帧即 67.2，低于门 70

## 重放与原始运行不一致（需人工复核，不参与归因分布）

- shot_002：记录分 49.9，重放分 72.9（差 23.0）。说明：重建现场与原始运行的评分对不上（可能是代码漂移或计划重建差异）；该镜不参与三类归因分布。
- shot_003：记录分 92.1，重放分 92.1（差 0.0）。说明：重放现场已通过构图门：原始失败未被复现（代码漂移或计划重建差异）；该镜不参与三类归因分布。
- shot_004：记录分 59.1，重放分 89.8（差 30.7）。说明：重建现场与原始运行的评分对不上（可能是代码漂移或计划重建差异）；该镜不参与三类归因分布。
- shot_005：记录分 49.4，重放分 59.2（差 9.8）。说明：重建现场与原始运行的评分对不上（可能是代码漂移或计划重建差异）；该镜不参与三类归因分布。
- shot_006：记录分 62.1，重放分 90.4（差 28.3）。说明：重建现场与原始运行的评分对不上（可能是代码漂移或计划重建差异）；该镜不参与三类归因分布。
- shot_007：记录分 64.4，重放分 79.2（差 14.8）。说明：重建现场与原始运行的评分对不上（可能是代码漂移或计划重建差异）；该镜不参与三类归因分布。
- shot_008：记录分 57.8，重放分 93.0（差 35.2）。说明：重建现场与原始运行的评分对不上（可能是代码漂移或计划重建差异）；该镜不参与三类归因分布。
- shot_009：记录分 77.2，重放分 77.2（差 0.0）。说明：重放现场已通过构图门：原始失败未被复现（代码漂移或计划重建差异）；该镜不参与三类归因分布。
- shot_010：记录分 45.3，重放分 65.9（差 20.6）。说明：重建现场与原始运行的评分对不上（可能是代码漂移或计划重建差异）；该镜不参与三类归因分布。
- shot_013：记录分 80.1，重放分 80.1（差 0.0）。说明：重放现场已通过构图门：原始失败未被复现（代码漂移或计划重建差异）；该镜不参与三类归因分布。

## 归因分布与修卡去向

| 归因类 | 镜数 | 镜头 | 落到哪张 v1.6 卡修 |
|---|---|---|---|
| camera_misplaced | 0 | — | 卡 B4（FR-C5：审核/修复回路接入 + reframe 菜单，含机位/锚点回读；D-12/D-13 的同尺回读）——把机位按该镜首帧实际站位重摆，不动 PASS_SCORE |
| solver_no_solution | 1 | shot_011 | 卡 D-12（CU/ECU 像素可测约束反解 + readback_shot_size()，不满足时自动调距离档；B4 的 reframe 菜单）——不动 PASS_SCORE |
| script_scale_exceeds_extent | 0 | — | 场景范围（config.scene.extent_m 与卡 D-10/FR-A1 的环境边界）——走位目标越界属剧本尺度问题；是否扩大 extent 由用户裁决，不动 PASS_SCORE |

## 未覆盖 / 剩余风险

- 重放代码：`E:\白模预演codex`（工具自身所在代码树；工作区含并发未提交改动）；重放分与记录分的对拍见上表（不一致的镜头先核对代码版本再读归因）。
- 报告只归因构图门失败的镜头；R001/E_AXIS_001 等其他发现不在此列。
- 逐镜完整证据（包围盒、六分量明细、首/中/尾三帧评分、求解器重解）见 `shots/<shot_id>.json`。
