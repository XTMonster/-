# 20261009-composition-diagnosis — 构图门归因诊断（v1.6 卡 B1 / D-04）

## 结论（先结论后证据）

对 `docs/evidence/20261008-v10-nodes1-4-run`（用户真实剧本前四节点那一跑）的
9 次 `E_CAM_001`（涉及 **3 个镜头**：shot_002 / shot_003 / shot_004）做零 LLM
重放诊断，全部用**该跑当时的提交 `4892dc9`** 复现（46.9 / 60.3 / 30.4，对照
记录 46.4 / 60.3 / 30.4），归因如下：

| 归因类 | 镜数 | 镜头 | 落到哪张 v1.6 卡修 |
|---|---|---|---|
| `camera_misplaced` | 1 | shot_002 | 卡 B4（FR-C5：审核/修复回路接入 + reframe 菜单，含机位/锚点回读；D-12/D-13 同尺回读） |
| `solver_no_solution` | 2 | shot_003、shot_004 | 卡 D-12（CU/ECU 像素可测约束反解 + `readback_shot_size()`，不满足时自动调距离档；B4 reframe 菜单） |
| `script_scale_exceeds_extent` | 0 | — | 场景范围（`config.scene.extent_m` 与卡 D-10/FR-A1 环境边界；扩范围属用户裁决） |

`PASS_SCORE`（70）一个字没动；没有任何一条归因建议放宽阈值。

## 三个镜头各自的证据（决定性数字）

* **shot_002**（CU，记录 46.4）：机位不在求解器对"该镜首帧实际站位"的解上——
  实际机位 (6.62, 2.75) vs 求解器重解 (7.08, 3.13)，**偏差 0.60 m > 0.5 m 容忍**；
  首帧 71.7 已过门，dolly_in 0.6 + handheld 0.03 把末帧带出（46.9，headroom
  0.00 / framing 0.19 / balance 0.00）→ **机位摆错（含运镜终点）**。
* **shot_003**（MS，记录 60.3）：机位与求解器完全一致（偏差 0.0 m、目标点即主体），
  仍 60.3：正对镜头的中景主体居中，`rule_of_thirds=0.44`、`occlusion=0.00`
  （搭档米迦尔站在机位正后方把主体挡掉）→ **求解器在这组参数下无解**。
* **shot_004**（CU，记录 30.4）：机位与求解器完全一致仍 30.4：
  `headroom=0.00 / occlusion=0.00 / framing=0.04`——主体盒躺在画面下沿
  （世界 AABB 顶高仅 0.80 m：上一镜 body_tilt 姿态**泄漏**进本镜），且
  莉莉安娜与米迦尔站位重合把主体挡住 → **求解器无解**（根因还包括姿态连续性
  与站位碰撞，详见 `shots/shot_004.json`）。

## 方法（零 LLM）

1. 读 `runs/audit_log.jsonl` + `runs/llm_trace.jsonl`。该日志**没有
   `plan_received` 事件**（旧日志形状），基计划取自 `emit_plan` 工具参数；
   13 镜逐镜草案按时间顺序、用与驱动器**同一条**校验路径
   （`layer5_orchestrator/editor.extract_draft`）逐条合并：**10 接受 / 8 拒绝**，
   与审计里的 `draft_received` / `draft_invalid` / `repair_invalid` /
   `react_invalid` 逐条吻合（接受草案的动作/对白计数与 10 条 `draft_received`
   一一相等）。
2. Blender headless 重放：`build_scene(最终计划, SceneSpec.from_plan(brief))`，
   不发起任何 LLM 调用。对每个失败镜取首/中/尾三帧
   `evaluate_camera_composition` 的最小分，并量主体包围盒（世界 AABB +
   归一化视口盒）、机位/焦距、首帧目标点（`BD_CamTarget_<shot>`）vs 主体实际
   站位、六分量与求解器重解（`cinema.framing.solve_framing`）。
3. 归因判定是纯函数（`tools/diagnose_composition.py::classify`）：
   `extent` → script_scale_exceeds_extent；机位/距离/目标点偏离求解器输出 →
   camera_misplaced；其余（含房间夹回 `clamped`）→ solver_no_solution。
   纯层 19 条用例（`tests/test_diagnose_composition.py`）逐类用合成输入钉死。

## 为什么主报告用 `4892dc9` 重放（保真性证据）

用**当前工作区**重放时 shot_002/004 变成 71.7 / 55.5（对照 `current_worktree/`
目录），记录分 46.4 / 30.4 不被复现。逐帧探针（`.scratch/probe_yaw_diag.py`）
定位到：当前工作区有**并发未提交的 v1.6 改动**（`beat_compiler.py` 的
`PACE_FRAME_MULTIPLIER`/`CURVE_PROFILE` + `contracts/beats.py` + 新增
`contracts/rhythm.py`），逐镜 beat 编译时长变化后，米迦尔在 shot_002 末帧的
根节点 yaw 从 `+12°`（4892dc9）变成 `0°`（当前），随后 shot_004 的机位与评分
全部跟着变。因果注入实验证实：`4892dc9` 树 + 当前 `beat_compiler.py`（含其新
依赖）即可复现新轨迹；反之，纯 `4892dc9` 树逐镜复现记录分。

因此主报告用 `git archive 4892dc9` 解出的**干净代码树**重放；工具提供
`--code-dir` 把 Blender 重放钉到指定代码树（纯层计划重建仍用本工具所在树；
要整条链都用旧代码，把本工具拷进旧代码树运行即可，本目录就是这么跑的）。

## 复现

```powershell
git archive -o $env:TEMP\bd4892dc9.zip 4892dc9
# 解压到 $env:TEMP\bd4892dc9\src，并把 tools/diagnose_composition.py 拷进去
python $env:TEMP\bd4892dc9\src\tools\diagnose_composition.py `
    docs\evidence\20261008-v10-nodes1-4-run `
    --out-dir docs\evidence\20261009-composition-diagnosis
# 当前工作区对照：
python tools\diagnose_composition.py docs\evidence\20261008-v10-nodes1-4-run `
    --out-dir docs\evidence\20261009-composition-diagnosis\current_worktree
python -m pytest -p no:cacheprovider -o addopts="" tests\test_diagnose_composition.py -q
```

## 输入侧缺失（原样报告，不猜）

* 该运行目录**没有 `project.bdproj`**（项目根与 `runs/` 下均无）：无法与落盘
  工程对拍；诊断改由 `audit_log` + `llm_trace` 零 LLM 重建，不影响归因。
* 日志**没有 `plan_received`**：计划取自 `emit_plan` 工具参数（已在报告中标注
  来源 `emit_plan`）。

## 交付物

* `composition_diagnosis.md` — 主报告（逐镜表 + 根因注记 + 归因分布 + 修卡去向）
* `shots/shot_002.json` / `shot_003.json` / `shot_004.json` — 逐镜完整证据
* `measurements.json` / `inputs_plan_payload.json` / `blender_run.log` /
  `summary.json` — 重放原始产物
* `current_worktree/` — 当前工作区重放对照（记录"重放与原始运行不一致"的两镜）

## 剩余风险与未覆盖

* shot_002 重放 46.9 vs 记录 46.4（差 0.5）：末帧浮点级差异，同一侧同一类
  （camera_misplaced），不改变归因；原因未再深挖（无落盘工程可对拍）。
* 本报告只归因构图门失败的镜头；该跑另有 10 次 `E_AXIS_001`（R001 越轴）不在
  D-04 范围内（那是 B5 的活）。
* 工具与报告**没有修改任何被诊断的代码**，也**没有改动任何阈值/断言**。
