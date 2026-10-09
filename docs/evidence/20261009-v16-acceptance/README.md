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
| 14 | 超时重试走阶梯、无原样第三次 | 真跑实证：shot_011 sidecar 500 → `same_retry` → 500 → `degrade`（只两次）；shot_012 超时 300 s → `slim_retry`；无"原样第三次" | PASS |
| 15 | pytest 全绿；run_tests.ps1 全绿 | pytest **3206 passed / 1 skipped**；探针 **43/43 OK**；唯一红仍是已结案的 **RK-13（E1）** | 部分（RK-13 判据未动）|
| 16 | 标签全帧交叠 ≤5% + 交付含汇总 | 同一终版计划零 LLM 重建（headless）：修复后 **0/1656 帧 >5%、最高 0.0%**（基线 331 帧 / 96.8%）；修法＝双向分摊 + 只对本镜出场角色烘焙/夹回；交付 README 已有「标签全帧自检」段 | PASS（机制已达标；成片真跑的交付包待终验）|

结论：**v4 仍判红**。代码侧缺陷（轴参照系、交付接线、校验域）本轮已修复并提交；
剩余红项集中在"构图门在这份剧本上收敛不了"（站位与视线共线、无人看见的走位跨线）、
模型侧工具 schema 漂移（35 次 invalid）与标签在拥挤帧的容量不足——都不是降级
阈值能掩盖的问题，下一刀需要按 W4A 的钉死归因逐镜修机位/站位/标签容量。

## W4A 钉死归因（`docs/evidence/20261009-v16-w4-pinned/`）

对 run `a966a3b255f2` 的最终计划（`plan_received` 逐字）零 LLM 重建并逐镜归因，
12 个构图失败镜分两类（归因闭集与阈值未动）：

* **camera_misplaced ×5**（shot_002/005/006/009/012）：终版机位与"按首帧实际站位
  重解"偏差 1.5–4.6 m——修复回路挪机位后没挪回来（其中 shot_002 还带
  `dolly_in` 运镜，首帧≠静态解）；
* **solver_no_solution ×7**（shot_003/004/007/008/010/011/013）：机位就是求解器
  的解，构图分项仍低——双人镜的 primary 盒取最近主体（`max(boxes, key=height)`），
  两人沿视线前后站时 framing 实测/预期≈1.75、headroom=0、balance≈0.34
  （shot_013 实测：伊恩 x∈[1.72,3.21] 与莉莉安娜 x∈[2.61,3.39] 前后重叠）。

修卡去向：`camera_misplaced` → 修复回路机位纪律（上一轮 `741f286` 已补提示，
待真跑验证）；`solver_no_solution` → 双人镜"并排站位/组中心锚点"的取景改动——
其中 MS/MCU 双人锚点在 `tests/test_station.py` 被钉死为"对准说话人"
（`test_focus_follows_the_first_speaker`），改为组中心属规格裁决，**本轮未动**。

## 续跑补充（2026-10-09 后半）

* **item 14 转 PASS**：真跑审计实证重试阶梯（shot_011 两次 500 → degrade；
  shot_012 超时 → slim_retry；无"原样第三次"）。
* **item 16 转 PASS**：标签修复（`4f99850`）在同一终版计划上把 331 帧/96.8%
  压到 **0 帧/0.0%**（`work/_g2_diag/verify_label_fix.py`，1656 帧全查）。
* 提示侧追加：计划提示把"声明景别（拍摄距离）"与时长并列为硬约束（治 R015）；
  起草提示写明 `pace≠curve`、拍点 `target` 闭集、动作参数键按行拷贝（治 invalid）。
* 剩余红项收窄为：#3/#4（构图门：5 镜机位漂移 + 7 镜求解器无解，双人锚点语义
  被既有测试钉死，改法需规格裁决）、#5（无人看见的走位跨线 17 条 + 修复挪错侧）、
  #8（模型侧 35 次 invalid，闸均正确拒绝）、#9（R015 ×1，提示已加硬约束待真跑复证）。

## v5 真跑（run `1dcd97979191`，`4f99850`，DeepSeek V4 Pro，EEVEE）

* **item 9 转 PASS**：`script_compliance` R015 = 0（计划提示把声明景别列为硬约束后）。
* **item 16 在全新真跑复证 PASS**：`label_overlap_report` = 0/1656 帧、最高 0.0%，
  交付 README 带「标签全帧自检」段；`masks/` 13 镜、`reference/` 4 卡齐全。
* `draft_invalid` 7 → **2**（起草提示 anti-drift 生效）。
* 仍红：#3/#4 `audit_pass_rate=0/12`（15 次 degraded / 11 镜）；
  #5 轴错 error 42（**unbridged 30**＝无人看见的走位跨线、**wrong_side 12**＝
  修复把机位挪到摆位线反侧）；#8 invalid 39（repair_invalid 15 以幻觉角色名
  `char_a/char_b/艾拉/优一郎` 为主——A2 闸每次正确拒绝并重问）。

## v6 真跑（run `3ebd919f2ea0`，`f74063a`，DeepSeek V4 Pro，EEVEE）

* `move_camera` 平移类运镜轴侧护栏生效：**轴错 error 42 → 5**（v5 vs v6；
  warning 45 主要是中性机位提示）。
* 修复提示列角色表生效：**repair_invalid 15 → 2**；draft_invalid 3、react_invalid 18
  （react 提示此前没有角色表/红线，`c6f727f` 已补）。
* `audit_pass_rate 0/12 → 2/12`（shot_004=84.9、shot_005=78.1 构图过门，
  但终审仍带 E_AXIS_001 warning）；label 0/1656、R015=0 保持。
* 剩余差距：构图 10/12 不达标（主因仍是双人镜前后站位）、轴错 5 条
  （无人看见的走位跨线）、react_invalid 18（动作词汇漂移）。

## v7 真跑（run `4ed8eb72cf16`，`c6f727f`，DeepSeek V4 Pro，EEVEE）

* `audit_pass_rate 2/12`（shot_009、shot_012）、label 0/1656、R015=0 保持；
  repair_invalid 2；react_invalid 18（本轮漂移以 `walk_to.speed='slow'`、
  `camera.:movements` 这类 pace/字段混淆为主，`03ac81c` 已补 speed≠pace 说明）。
* 轴错 error 26（v6 为 5）：**逐跑方差来自计划本身**——每轮 DeepSeek 产出的
  走位编排不同，无人看见的跨线数随之波动；规则抓的都是真实违规。
* 结论：机械侧修复已收敛（label/交付/重试/轴护栏/R015/role 表全部绿），
  剩余 #3/#4/#5/#8 由"双人镜锚点语义（规格裁决）＋模型词汇/调度方差"决定。

## 用户裁决落地（2026-10-09 后半，提交 `a71f287`）

1. **双人镜锚点**：`cinema/station.py::GROUP_SHOT_TYPES` 增 `MCU`——双人 MCU
   锚点取两人质心（单人 MCU 质心=自身，行为不变）；`tests/test_station.py`
   的 `test_focus_follows_the_first_speaker` 按授权改为
   `test_two_person_mcu_anchors_on_the_pair_center`（CU 仍对准说话人，既有
   tight-shot 断言保留）。
2. **无歧义别名归一**：`motion/model.py::ACTION_PARAM_ALIASES` 只收
   `turn_head.yaw_deg→angle_deg`、`body_tilt.lean_deg→angle_deg`、
   `look_at.angle_deg→yaw_deg`；校验/草案存储/工具执行三处同源归一，其余
   近义词照旧拒绝。新测试 `tests/test_action_param_aliases.py` 7 条。
3. **AGENTS.md**：Status 区新增「v1.6 / G2 终验收现状」块。

验证：`python -m pytest` = **3213 passed / 1 skipped / 0 failed**；
`tools/run_tests.ps1` 探针 **43/43 OK**（唯一红仍是已结案的 RK-13/E1）。

## v8/v9 真跑（`a71f287` 之后，DeepSeek V4 Pro，EEVEE）

* v8（run `4293a78a42b2`）：模型中途调用 `abort`（"无工具可用"）→ CANCELLED，
  且该跑计划带 10 条自由文本 `unresolved_anchor`（item 2 也随计划波动）。
* v9（run `1c0ae62505e4`）：DONE。`audit_pass_rate 3/12`（shot_003=92.5、
  shot_006=91.6、shot_009=90.6）；label 0/1656、R015=0；轴错 error 44
  （逐跑 5→26→44，主因仍是无人看见的走位跨线）；invalid 32。
* 趋势：锚点裁决后 apr 0→2→**3/12** 逐轮上升；#5/#8 仍由模型调度/词汇方差
  主导，规则抓到的都是真实违规。

## v10 真跑（run `43a32863b2d6`，`6e845c6`，DeepSeek V4 Pro，EEVEE）

* 新前置闸：`unseen_axis_crossing`（`driver.py`，纯 `crossing_events`，≥90° 翻转
  ＋单人镜）在 B1 与修复两处草案合入前拒绝；新测试 4 条。
* 读数：`audit_pass_rate 3/12`（shot_002/003/006）、label 0/1656、R015=0；
  **轴错 error 44 → 15**（unbridged 4 ＋ wrong_side 11）；invalid 25
  （draft 2 / repair 6 / react 17）。
* 趋势（轴错 error）：v6=5、v7=26、v9=44、v10=15——跨线前置闸拦掉了 ≥90° 的
  隐蔽翻转让最坏情况收敛；30–90° 漂移与修复重摆机位的 wrong_side 仍在
  模型方差范围内。

## v11 真跑（run `b59ac46ebb82`，`deb04e0`，DeepSeek V4 Pro，EEVEE）

* 跨线闸扩到 30° 审计带（起点+终点双查、可见旋转偿债记账，`drift_is_bridged`
  同口径）；新测试 2 条（≥30° 隐蔽走位拒绝、<30° 小走位放行）。
* 读数：**轴错 error 5**（追平最优轮；跨线闸把最坏情形压进 5–15 带）、
  `audit_pass_rate 2/12`（shot_005/013）、label 0/1656、R015=0；
  invalid 28（react 21 / repair 4 / draft 3）。
* 累计趋势（轴错 error）：44(v9) → 15(v10) → **5(v11)**；构图 apr 在 2–3/12
  波动，剩余失败镜以修复回路的机位漂移（camera_misplaced 1.2–9.3 m）为主。

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
