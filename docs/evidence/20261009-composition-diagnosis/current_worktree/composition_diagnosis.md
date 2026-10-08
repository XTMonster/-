# 构图门归因诊断（B1 / D-04）

- 运行目录：`E:\白模预演codex\docs\evidence\20261008-v10-nodes1-4-run`
- 最终计划来源：`emit_plan`
- `config.scene.extent_m`：12
- 重放代码：`E:\白模预演codex`（工具自身所在代码树；工作区含并发未提交改动）
- 诊断方式：读 `audit_log.jsonl` + `llm_trace.jsonl` → 零 LLM 重建计划 → Blender headless 重放场景 → 逐失败镜测量。
- 红线：**不修改被诊断代码**；**归因不给出任何阈值让步**（PASS_SCORE 保持 70）。

## 输入侧缺失（原样报告，不猜）

- 缺少 project.bdproj（找过：项目根与 runs/ 下均无）：无法与落盘工程对拍；诊断改由 audit_log + llm_trace 零 LLM 重建，不影响归因。

## 计划重建

- 重放草案 18 条：接受 10、拒绝 8。
  - shot_003（llm_trace/editor）拒绝：hand_to 的 toward 必须是数字（当前 '木围栏'）
  - shot_004（llm_trace/editor）拒绝：hand_to 的 toward 必须是数字（当前 [0.7, 1.1, 0.3]）；hand_to 的 toward 必须是数字（当前 [0.75, 1.15, 0.25]）；hand_to 的 toward 必须是数字（当前 [0.8, 1.2, 0.2]）
  - shot_006（llm_trace/editor）拒绝：hand_to 的 toward 必须是数字（当前 'camera'）；hand_to 的 toward 必须是数字（当前 'camera'）
  - shot_008（llm_trace/editor）拒绝：hand_to 的 toward 必须是数字（当前 '偷盗者所在的画右开阔通道口'）
  - shot_003（audit_log/repair/react）拒绝：第 1 个拍点的 subject='char_01' 不在本镜角色里；第 2 个拍点的 subject='char_01' 不在本镜角色里；第 3 个拍点的 subject='char_01' 不在本镜角色里
  - shot_003（audit_log/repair/react）拒绝：第 1 个拍点的 subject='char_01' 不在本镜角色里；第 2 个拍点的 subject='char_01' 不在本镜角色里；第 3 个拍点的 subject='char_01' 不在本镜角色里
  - shot_003（audit_log/repair/react）拒绝：stand 不认识的参数 ['base_z']；允许的键是 ['drop', 'leg_fold_deg', 'lean_deg']；turn_body 不认识的参数 ['speed', 'toward', 'yaw_deg']；允许的键是 ['angle_deg', 'angle', 'degrees']；turn_head 不认识的参数 ['pitch_deg', 'toward', 'yaw_deg']；允许的键是 ['angle_deg', 'angle', 'degrees']；look_at 不认识的参数 ['speed', 'toward']；允许的键是 ['yaw_deg', 'pitch_deg']；hand_to 不认识的参数 ['speed', 'to']；允许的键是 ['prop', 'angle_deg', 'toward']；body_tilt 不认识的参数 ['lean_deg', 'speed']；允许的键是 ['angle_deg', 'angle', 'degrees', 'axis', 'toward']；look_at 不认识的参数 ['toward']；允许的键是 ['yaw_deg', 'pitch_deg']
  - shot_003（audit_log/repair/react）拒绝：stand 不认识的参数 ['base_z']；允许的键是 ['drop', 'leg_fold_deg', 'lean_deg']；turn_body 不认识的参数 ['speed', 'toward', 'yaw_deg']；允许的键是 ['angle_deg', 'angle', 'degrees']；turn_head 不认识的参数 ['pitch_deg', 'toward', 'yaw_deg']；允许的键是 ['angle_deg', 'angle', 'degrees']；look_at 不认识的参数 ['speed', 'toward']；允许的键是 ['yaw_deg', 'pitch_deg']；hand_to 不认识的参数 ['speed', 'to']；允许的键是 ['prop', 'angle_deg', 'toward']；body_tilt 不认识的参数 ['lean_deg', 'speed']；允许的键是 ['angle_deg', 'angle', 'degrees', 'axis', 'toward']

## 逐镜诊断表

| 镜号 | 景别 | 记录分 | 重放分 | 主体站位 (x,y) | 机位 (x,y,z) | 焦距 | 首帧目标点 (x,y,z) | 目标-主体 (m) | 六分量 | 归因 | 决定性证据 | 建议修卡 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| shot_003 | MS | 60.3 | 60.3 | [-0.75, 0.0] | [3.8818, 0.0, 0.9497] | 50.0 | [-0.75, 0.0, 1.0997] | 0.0 | headroom 1.00 / lead_room 0.75 / rule_of_thirds 0.44 / balance 1.00 / occlusion 0.00 / framing 0.88 | **solver_no_solution** | camera_matches_solver=True；replayed_score=60.3；threshold=70.0；components.headroom=1.0；components.lead_room=0.75；components.rule_of_thirds=0.438 | 卡 D-12（CU/ECU 像素可测约束反解 + readback_shot_size()，不满足时自动调距离档；B4 的 reframe 菜单）——不动 PASS_SCORE |

## 逐镜根因注记（由实测证据机械生成）

- **shot_003**（MS）：弱项：rule_of_thirds=0.44、occlusion=0.00；首帧即 60.3，低于门 70

## 重放与原始运行不一致（需人工复核，不参与归因分布）

- shot_002：记录分 46.4，重放分 71.7（差 25.3）。说明：重建现场与原始运行的评分对不上（可能是代码漂移或计划重建差异）；该镜不参与三类归因分布。
- shot_004：记录分 30.4，重放分 55.5（差 25.1）。说明：重建现场与原始运行的评分对不上（可能是代码漂移或计划重建差异）；该镜不参与三类归因分布。

## 归因分布与修卡去向

| 归因类 | 镜数 | 镜头 | 落到哪张 v1.6 卡修 |
|---|---|---|---|
| camera_misplaced | 0 | — | 卡 B4（FR-C5：审核/修复回路接入 + reframe 菜单，含机位/锚点回读；D-12/D-13 的同尺回读）——把机位按该镜首帧实际站位重摆，不动 PASS_SCORE |
| solver_no_solution | 1 | shot_003 | 卡 D-12（CU/ECU 像素可测约束反解 + readback_shot_size()，不满足时自动调距离档；B4 的 reframe 菜单）——不动 PASS_SCORE |
| script_scale_exceeds_extent | 0 | — | 场景范围（config.scene.extent_m 与卡 D-10/FR-A1 的环境边界）——走位目标越界属剧本尺度问题；是否扩大 extent 由用户裁决，不动 PASS_SCORE |

## 未覆盖 / 剩余风险

- 重放代码：`E:\白模预演codex`（工具自身所在代码树；工作区含并发未提交改动）；重放分与记录分的对拍见上表（不一致的镜头先核对代码版本再读归因）。
- 报告只归因构图门失败的镜头；R001/E_AXIS_001 等其他发现不在此列。
- 逐镜完整证据（包围盒、六分量明细、首/中/尾三帧评分、求解器重解）见 `shots/<shot_id>.json`。
