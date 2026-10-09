# `20261009-v16-acceptance` — v1.6 终验收（卡 G2）：样片全链路重跑

| 项 | 值 |
|---|---|
| 剧本 | `fixtures/shotlist_market_v10_nodes1_4.txt`（13 镜，用户剧本前四节点） |
| 通道 | ~~DeepSeek sidecar~~ → **GLM-5.3-Flash**（智谱，127.0.0.1:8782；DeepSeek 上游 402，见过程记录），插件自己的路径（= 面板按钮） |
| 单次调用超时 | **A4 落地后的配置值**（`llm.timeout_s`，驱动脚本不再显式传 `--llm-timeout`） |
| 结构验收 | 先 `--offline --build` 跑第 1/2/6/7/11/13 条，再真模型补其余 |
| 代码基线 | `5ac40c8`（B4 `34dd6e7` ＋ A2 草案缺口修复） |

## 验收清单（卡 G2 逐条对拍，一条不过就不许宣布完成）

| # | 判据（出处） | 读数位置 | 读数 | 判定 |
|---|---|---|---|---|
| 1 | 全片角色 ⊆ 角色表 4 人；构建段 `characters: 4`；`label_report` 只含角色表成员（D-11） | blender.log / shots.json | 24 次 `scene_built` 全部 `characters: 4`；labels 只有 伊恩/偷盗者/米迦尔/莉莉安娜；计划无「优一郎」（A2 闸放行导出） | **PASS** |
| 2 | `unresolved_anchor == 0`；shot_001 首帧 ≥3 个环境元素（D-10） | blender.log / 首帧人审 | shot_001 `elements_in_frame = [env_01, env_03, env_02]` ✓；`unresolved_anchor` 审计无读数；首帧人审本轮无法核验（当前会话模型不支持图像输入） | **未验证** |
| 3 | CU 镜头部占比 55–75%，构图分 ≥70（D-12） | audit_log `shot_audit` | 无成功交付的 CU（R015：镜 4/7 声明 CU 实际排成 MCU/MS）；像素回读全员 `none`（遮罩通道被 workbench 跳过）；构图分 11/13 镜 <70 | **FAIL** |
| 4 | `audit_pass_rate ≥ 10/12`；`degraded ≤ 1`（FR-C5） | 审计汇总 | `shot_audit` 44 条中 `passed=True` 4 条（92.1/77.2/85.3/80.1）；`shot_degraded` 17 条事件 / 9 个不同镜头 | **FAIL** |
| 5 | `E_AXIS_001 ≤ 2`；镜 13 不 `crossed`（FR-C6） | audit_log | E_AXIS_001 出现在 11/13 镜（warning 37 + error 8）；shot_013 未列 crossed | **FAIL** |
| 6 | 同层重叠 ≤1 处/镜；镜 8/10 无穿模（D-16） | blender.log / 首帧 | 审计无 overlap 事件；穿模需逐帧视觉复核，本轮无法核验 | **未验证** |
| 7 | `shots.json` 有 `needs_review`；README 有汇总段（D-07） | 交付包 | 8 镜 `needs_review=True`；README「待人工复核」段列出同 8 镜 | **PASS** |
| 8 | `draft_invalid / react_invalid / repair_invalid` 合计 = 0（D-03） | audit_log | `draft_invalid` 8 + `react_invalid` 18 + `repair_invalid` 0 = **26**；原因全是 GLM 工具参数近失配（`yaw_deg`/`lean_deg`/`cycles` 等未知参数、`pace='sharp'` 越集、形状错误、无工具调用） | **FAIL** |
| 9 | R015 = 0 或每处带 `declared_breaks`（D-15） | audit_log | R015 error ×2（镜 4/7），无 `declared_breaks` | **FAIL** |
| 10 | 环境节拍不再当角色动作（D-17） | blender.log | `script_compliance` 无 D-17 类 finding；shot_001 环境节拍 subject=「镜头」look_at 环境目标 | **PASS** |
| 11 | 交付包含 `elements.json` / `masks/` / `reference/`；`prompts.md` 无表外名（FR-A） | 交付包 + 对拍测试 | `elements.json` ✓；`reference/characters/` 4 PNG ✓；`masks/` **缺失**（README 告警：workbench 跳过遮罩导出）；prompts.md 无表外名（全量 CJK 词表扫描 + 4 角色名出现次数核对） | **FAIL** |
| 12 | `rhythm_reading` 事件存在；README 节奏段与 shots.json 对拍（FR-B） | audit_log / 交付包 | 事件存在（ASL 5.31、CV 0.3574）；README ASL/CV 与事件一致；逐镜 tension 均为「—」且与 shots.json `rhythm`（多数为 `{}`）一致 | **PASS** |
| 13 | 圆柱躯干 AABB max_delta = 0.0（FR-E） | headless 测试 | `test_character_body_ab.py` **5/5 passed**：`max_delta=0.0`、64 顶点、双环 32/32、半径/高度/角度误差 <1e-7 | **PASS** |
| 14 | 超时重试走阶梯、无"原样第三次"（D-02） | audit_log `retry_ladder` | 无 `retry_ladder` 事件、`llm_request` 无 retry/attempt 字段、无 timeout 错误——本次未触发超时重试，D-02 无可读证据 | **未验证** |
| 15 | `python -m pytest` 全绿；`tools/run_tests.ps1` 全绿 | 终端输出 | pytest **3198 passed / 1 skipped / 0 failed**（3199 collected）；`run_tests.ps1` 本轮尚未重跑 | **部分** |
| 16 | 标签全帧两两交叠 ≤5%（覆盖全帧而非采样帧）；交付包含 `label_overlap_report` 汇总（D-19） | headless 测试 / 交付 README | 交付 README **无** `label_overlap_report` 段、审计无 label_overlap 事件；多数标签 `offset_reason=out_of_frame+occluded` | **FAIL** |

## 过程记录

* **2026-10-09 04:4x — B4 提交 `34dd6e7`**：审核/修复回路携带 GuardWarning 证据 ＋ CU/ECU 像素回读
  （全量 pytest 绿、43/43 探针绿；链上唯一红仍是 v1.5 已结案的 RK-13/E1，与本次改动无关）。
* **04:5x — 通道阻塞与替换（留证）**：G2 原计划 DeepSeek 通道，sidecar 探针实测上游
  **HTTP 402（余额不足）** ⇒ 按计划外裁决走用户 2026-10-09 提供的 **GLM-5.3-Flash**
  （智谱，`--tool-choice-mode auto`）。402 证据：本目录 `deepseek-402.txt`。
* **05:0x — GLM 通道的两个实测性质（影响所有跑法）**：
  ① **始终思考模型**：`thinking:{"type":"disabled"}` 被上游 400 拒收
  （`code 1210 "该模型始终思考"`）；
  ② **reasoning 会吃光输出上限**：5.4k token 的 understand 提示在 `max_tokens=8192` 下
  8043/8192 全烧在 reasoning、`content` 为空（`finish_reason=length`）⇒ 计划/理解调用全灭。
  处置：sidecar 加 `--reasoning-effort low`（实测探针 3 个 completion token），
  运行侧 `--llm-max-tokens 24576`（`config.llm.max_tokens`，每次调用输出上限）。证据：
  `glm-always-thinking.json`。
* **05:1x — 真跑 v2 启动**：`work/_g2_glm2/`，DeepSeek→GLM 通道、EEVEE（遮罩通道需要）、
  单次超时 = A4 产品配置值（`llm.timeout_s=300`，驱动脚本不再显式传）。
* **05:3x — 真跑 v2 结局（判红）**：run `a89fa37ebdca`，23.9 分钟 / 55 次 LLM 调用 /
  389k token；计划 13 镜全过、brief 来源 llm、场景建成、44 次审核、
  `guard_warning` 事件 11 条、`repair_rolled_back` 1 次——但**导出被 A2 闸拦停**：
  `计划/草案含角色表外 id：优一郎`（合法表：伊恩/偷盗者/米迦尔/莉莉安娜）。"优一郎"
  在剧本里出现 0 次，是 GLM 的幻觉；`audit_pass_rate 5/12`、R015 error ×4
  （声明 CU 被排成 MS/MCU）、shot_013 crossed。**按"一条不过不许宣布完成"，v2 判红。**
* **05:5x — 根因定位与修复（commit `5ac40c8`）**："优一郎"不是从计划入口进来的
  （`_accept_plan_chunk` 的 A2 校验是活的），而是**从 B1 草案入口**——
  `editor.extract_draft` 只核拍点 subject 引用，从不核 `draft.characters` 的 roster
  成员资格，草案可无校验覆盖计划的镜角色表。修法：`contracts/plan.py` 抽出
  `unknown_cast_members`（成员级判据，计划级 `unknown_cast_ids` 委托它，同源不抄第二份）；
  `extract_draft` 加可选 `roster` 参数（给了就核、不给/空表跳过，与 characters/anchors
  同一纪律）；driver 两个草案入口（B1 与修复/精修的 `emit_shot_draft`）都传
  `roster=self._cast_roster()`。新增测试 8 条（`tests/test_cast_hard_check.py`，
  含 driver 级两条：B1 路径记 `draft_invalid` 且沿用计划角色表、修复路径记
  `repair_invalid` 且计划不动）。`python -m pytest` = **3198 passed / 1 skipped / 0 failed**。
* **05:5x — 真跑 v3 启动**：`work/_g2_glm3/`，通道/参数与 v2 完全相同
  （GLM-5.3-Flash、`--reasoning-effort low`、`--tool-choice-mode auto`、EEVEE、
  `--llm-max-tokens 24576`），代码 = `5ac40c8`。

## 2026-10-09 续跑：DeepSeek V4 Pro 通道 + 三处代码修复后的 v4 验收

* 通道：官方 DeepSeek `deepseek-v4-pro`（思考型，`--tool-choice-mode auto`、
  `--reasoning-effort max`、`--llm-max-tokens 24576`），插件路径，EEVEE。
* 代码：`5ac40c8` → `3ed5a1a`（轴摆位线同源 + 空镜豁免 + 校验/执行域对齐 +
  交付接线）→ `741f286`（修复提示：遮挡先挪主体、主体保持相机前方）。
* 真跑：第一轮 `4bee011cde08`（71 次调用后主动停止：460 次轴错 + 455 次回滚风暴，
  定位为轴参照系不一致）；第二轮 `a966a3b255f2` 完整跑完并导出。

### v4 终验收（run `a966a3b255f2`，13 镜 / 4 角色，`export_finished: ok`）

| # | 判据 | 读数 | 判定 |
|---|---|---|---|
| 1 | 全片角色 ⊆ 角色表 4 人 | `scene_built: characters=4`；导出闸放行 | PASS |
| 2 | `unresolved_anchor==0`；shot_001 ≥3 环境元素 | 无 unresolved 事件；`elements_in_frame=[env_01,env_02,env_03]` | PASS（首帧人审待用户）|
| 3 | CU 头部占比 55–75% 且构图 ≥70 | 终审 shot_005=20.0、shot_006=64.7、shot_013=57.6 … | FAIL |
| 4 | `audit_pass_rate ≥10/12`；degraded ≤1 | `audit_pass_rate=1/12`；21 次 degraded（11 镜）| FAIL |
| 5 | `E_AXIS_001 ≤2`；镜 13 不 crossed | error 17 / warning 27（多为"无人看见的走位跨线"）| FAIL |
| 6 | 同层重叠 ≤1/镜；镜 8/10 无穿模 | `action_conflicts=[]`；穿模逐帧视觉未核验 | 部分/未验证 |
| 7 | `needs_review` + README 汇总 | 10 镜 `needs_review=True`，README「待人工复核」同列 | PASS |
| 8 | 三类 invalid 合计 = 0 | `draft_invalid` 7 + `repair_invalid` + `react_invalid` = 35 | FAIL |
| 9 | R015=0 或每处带 declared_breaks | `script_compliance` R015 error ×1（镜2 CU→MS，无破例）| FAIL |
| 10 | 环境节拍不再当角色动作 | 无 D-17 类 finding | PASS |
| 11 | `elements.json`/`masks/`/`reference/`；prompts 无表外名 | 13 镜 masks、4 定妆卡、elements；prompts 表外名闸放行 | PASS |
| 12 | `rhythm_reading` 事件；README 与 shots.json 对拍 | ASL 5.31 / CV 0.3574 三处一致 | PASS |
| 13 | 圆柱躯干 AABB max_delta=0.0 | body-ab 探针 5/5 | PASS |
| 14 | 超时重试走阶梯、无原样第三次 | 本轮无超时（机制由 `test_driver_retry_ladder.py` 钉住）| 未行使（如实）|
| 15 | pytest 全绿；run_tests.ps1 全绿 | pytest **3206 passed / 1 skipped**；探针 **43/43 OK**；唯一红仍是已结案的 **RK-13（E1）** | 部分（RK-13 判据未动）|
| 16 | 标签全帧交叠 ≤5% + 交付含汇总 | 331/1656 帧 >5%，最高 **96.8%**；README 已有「标签全帧自检」段 | FAIL |

结论：**v4 仍判红**。代码侧缺陷（轴参照系、交付接线、校验域）本轮已修复并提交；
剩余红项集中在"构图门在这份剧本上收敛不了"（站位与视线共线、无人看见的走位跨线）、
模型侧工具 schema 漂移（35 次 invalid）与标签在拥挤帧的容量不足——都不是降级
阈值能掩盖的问题，下一刀需要按 W4A 的钉死归因逐镜修机位/站位/标签容量。

## 07:0x 续跑复核（本会话）——结论：**G2 判红，不允许宣布完成**

上一会话在 06:51 停在 v3 的归因分析中途（`work/_g2_glm3/_analysis*.txt`、
`docs/evidence/20261009-composition-diagnosis/summary.json` 留了
`replay_mismatch` 10 镜、只归因 shot_011）。本会话按 16 条判据逐条复核并把
上方表填实：**PASS 5（#1/#7/#10/#12/#13）、FAIL 7（#3/#4/#5/#8/#9/#11/#16）、
未验证 3（#2/#6/#14）、部分 1（#15）**。

根因（都已在产物/日志中留证，未改任何判据与阈值）：

1. **后端没上 EEVEE**（#11/#3/#16 的共同根因）：`tools/run_headless.py` 根本没有
   `--render-backend` 覆盖项，`config.delivery.render_backend` 默认 `workbench`。
   README 里写的"EEVEE"是启动记录里的意图，实际进程用的是 workbench → `masks/`
   被跳过、CU/ECU 像素回读全员 `none`、`label_overlap_report` 不产出。这不是
   resume 丢配置（resume_state.json 本来就不存 config），是**启动参数缺失**。
2. **GLM 工具参数近失配**（#8）：26 条无效调用全部是模型侧 schema 漂移——
   `turn_body.yaw_deg`/`body_tilt.lean_deg`/`body_tilt.cycles`/`turn_head.pitch_deg`
   等未知参数名、`pace='sharp'` 越闭集、`walk_to.from` 形状错、以及 react 回复
   无工具调用。`data.reason` 为 null（原因只在 `message` 里），审计可观测性也有缺口。
3. **构图门大面积不过 + 归因不完整**（#3/#4）：44 条审计只有 4 条 `passed=True`，
   11 镜 <70；D-04 诊断在本工作区重放 10/11 镜 `replay_mismatch`（运行态来自
   24 次增量 rebuild/rollback 的就地改动，不是最终计划的干净一次 build），
   只有 shot_011 归因 `solver_no_solution`。要先在 `5ac40c8` 钉死重放才能逐镜归因。
4. **R015 无法自愈**（#9）：镜 4/7 声明 CU 被排成 MCU/MS，修复回路两次草案也因
   #2 的校验失败被拒，镜头尺寸始终没纠正。
5. **轴线红遍 11/13 镜**（#5）：R001 修复回路对"走位跨线/机位摆错"两类纠正不足。
6. **D-02 本次未触发**（#14）：重试阶梯机制在库且被 `tests/test_driver_retry_ladder.py`
   钉住（`retry_ladder` 事件三键 stage/shot_id/elapsed_s），但 v3 全程没有超时/5xx，
   一次重试都没发生，所以本轮没有阶梯事件可读——判据未被行使，不是机制缺失。

核验通道的如实声明：

* 本轮 `python -m pytest` = **3198 passed / 1 skipped / 0 failed**；
  `test_character_body_ab.py` = **5/5 passed**（圆柱逐顶点几何校验在，AABB
  `max_delta=0.0`）。
* `tools/run_tests.ps1` 尚未在本会话重跑（修复提交后统一跑）。
* **画面效果的人眼复核本轮无法执行**：当前会话模型不支持图像输入
  （`view_image` 被拒），按「通道不可用如实报错」纪律，把 #2/#6 的"首帧人审"
  与标签/穿模视觉项标为未验证，不伪称看过；像素回读与掩码是可执行的量化替代，
  待 EEVEE 修复后补。

下一步（按修复阶梯，执行丢给 DeepSeek V4 Pro，主线审核 diff 并复跑测试）：

* W1：`run_headless.py` 加 `--render-backend`（经 `config.errors()` 校验）并把
  生效配置快照进 `resume_state`，resume 时恢复；回归测试覆盖「eevee 覆盖 + resume
  往返仍为 eevee」。
* W2：`draft_invalid`/`react_invalid` 把拒绝原因写进 `data.reason`（与 `message`
  同源；只补审计字段，不改任何校验语义）。D-02 机制已在库，不需新增。
* W3：工具参数**同义别名规范化**（`yaw_deg→angle_deg`、`lean_deg→angle_deg` 等）
  逐条钉死语义等价与测试；越集值（`pace='sharp'`）与"无工具调用"不静默吞掉，
  是否接纳由规格裁决，不自行放宽。
* W4：构图归因钉死 `5ac40c8` 重放 → 逐镜归因 → 修机位/距离档（D-12/B4 已在库）。
* W5：R015/轴线修复回路收口；随后 EEVEE 真跑 v4 + 16 条全量对拍 + 全链测试。

这些是修复任务书，不是通过证据；G2 的完成定义一个字没改。
