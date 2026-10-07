# v1.6 A1–A4 / A5 dirty：测试与验收有效性审查

日期：2026-10-08。唯一角色：测试与验收。审查者：当前会话模型。
本报告不是双模型会诊，不代表独立人工裁决；未调用 DeepSeek、GLM 或其他外部评审模型。

## 结论

当前状态不能按 A1–A5 验收完成。A5 定向 pytest 已有两个真实失败；
另外，A2/A3/A4 的 25 条新增定向测试虽然全部通过，仍漏掉实际调用链中的
角色表信任边界、草案入口、环境动作错误引导、GUI 超时传递。
A5 缺无人值守导出接线和重复登记次数，都是任务卡明确要求，不是新增需求。

审查范围固定为 `44dea67...2a63f95`（A1–A4 提交）及开工时 A5 工作区：
`delivery/manifest.py`、`modal_operator.py`、`panel_main.py`、
`layer8_delivery/export_director.py`、`tests/test_needs_review.py`。
模型路由文件的并行改动不属于本角色范围。

已完整阅读 `AGENTS.md`、`CONTEXT.md`、`v1.6/TDD_v1.6.md`、
`v1.6/改进计划_v1.6_deepseek.md`、`tools/run_tests.ps1`，并盘点提交与工作区。
按 code-review 技能对拍规格与代码；依主线分工仅交付“测试与验收”视角，
未重复展开其他角色。未修改产品、测试、AGENTS 或验收阈值。

## 实际运行

1. `python -m pytest -q tests/test_needs_review.py`

   结果：`...FF`，3 通过、2 失败。两个失败均为：
   `ModuleNotFoundError: No module named 'bpy'`。
   失败用例：
   `test_readme_has_review_section`、
   `test_readme_omits_review_section_when_none`。

2. `python -m pytest -q tests/test_cast_hard_check.py tests/test_config_v16.py tests/test_rule_levels.py tests/test_tool_bindings_env.py`

   结果：25 个通过标记，退出码 0（四个文件分别 8、8、3、6 条）。

3. `python docs/evidence/20261008-v16-intake/acceptance/probe_current.py`

   结果：退出码 0，输出以下可复现诊断。此脚本绝不请求模型；
   源码抽取只执行具名纯函数/错误返回分支，不能代替整个 Blender 模块导入或渲染验收。

## Findings

### F1 · P1 · A5 的纯 pytest 测试直接导入 bpy，完整链将停在 pytest 步

证据：

- `tests/test_needs_review.py:40`、`:54` 直接导入
  `block_director.layer8_delivery.export_director`。
- `block_director/layer8_delivery/export_director.py:17` 顶层 `import bpy`。
- 上述定向 pytest 已实测两条 `ModuleNotFoundError`。
- `tools/run_tests.ps1:181`–`:183` 在 Blender 探针之前跑纯 pytest，
  非零则退出；因此当前 A5 dirty 不能由完整链验收。
- 额外测试构造风险：`:46` / `:59` 固定写 `DeliveryReport(out_dir="/tmp/out")`，
  而 `_readme` 在 `export_director.py:127` 无条件 `os.listdir(report.out_dir)`。
  即使解决导入，未创建的固定目录还会触发文件系统错误；这不是 README 需求判据。

最小补测与修复方向：

- README 内容组装应有可正常导入的纯层入口，pytest 用 `tmp_path` 创建真实目录；
  产品 exporter 消费同一入口，避免测试私抄实现。
- 保留现有内容断言并增加空目录/含深度目录两种真实目录输入。
- 不安装/伪装 `bpy` 来掩盖分层问题，不跳过两个测试；Blender 实际导出另有入口级测试。

### F2 · P1 · A5 只接 GUI 导出，目标“无人值守跑”没有逐镜请求数据

证据：

- `v1.6/改进计划_v1.6_deepseek.md:183` 明确目标是“无人值守跑时”落产物。
- `driver.py:394` 的 snapshot 把 `review_requests` 写成整数总数；
  `headless_runner.py:77` 起只把该 snapshot 作为 summary，没有补回逐镜列表。
- `tools/run_headless.py:180`、`tools/run_export.py:138`、
  `tools/rebuild_project.py:101`、`tools/replay_project.py:66`
  的 `export_project(...)` 均未传 `review_requests`。
- 只有 `modal_operator.py:212` 与 `panel_main.py:68` 传了它。
- `build_manifest` 缺省 `review_requests=None`，因此对应每镜 `needs_review=False`。
- `probe_current.py` 全量 AST 盘点以上六个生产导出调用点；输出精确的
  `passes_review_requests` 布尔值，四个 tools 入口均为 false。

现有测试为什么漏：
`test_needs_review.py:18` 起手工把正确列表直接送进 `build_manifest`，
没有经过 `request_self_review → driver → headless summary → exporter`。

最小补测：

- 同一镜真实 dispatch 两次自审请求，再让 headless summary/CLI 导出接收真实状态；
  断言导出的该镜为 true、未请求镜为 false。
- 为所有生产导出调用点补字段接线守卫，可沿用
  `tests/test_manifest_fields.py:118` 的现有 AST 对拍形式，
  但不能仅用 AST 替代一次真正的无人值守落盘对拍。
- 重建/回放是否必须恢复历史复核请求，应明确其持久化来源；
  当前没有验证其保存/恢复能力，不能把缺数据当“无请求”。

### F3 · P2 · A5 丢失“登记次数”；现有测试只断言去重镜数

证据：

- 任务卡 `v1.6/改进计划_v1.6_deepseek.md:193` 钉死：
  README「待人工复核」列镜号 + 登记次数。
- `manifest.py:57`–`:58` 先转为 set，只保留是否登记；
  `export_director.py:133`–`:139` 只列镜号和去重镜数。
- 真实调用 `PrevisDriver._dispatch_tool_calls` 两次请求 `shot_001` 的诊断输出：

  ```text
  actual_registered_count = 2
  snapshot_review_requests = 2
  manifest_review_fields = {"needs_review": true}
  readme_review_section = 以下 1 个镜头在运行中被模型请求自我审核：shot_001
  ```

- `tests/test_needs_review.py:43`–`:50` 只输入一条，断言“1 个镜头”，
  不可能发现计数丢失。

最小补测：输入 `shot_001` 两次、`shot_002` 一次、
`shot_003` 零次，经真实登记通道后断言 README 分别显示 2/1 次，
每镜布尔值分别 true/true/false；登记总次数也与审计事件数对拍。

### F4 · P1 · A2 测试没有覆盖“角色表由谁建立”，驱动让候选计划自证合法

证据：

- A2 任务卡 `:113`–`:137` 要成员资格校验，不是按 id 形状放行。
- `driver.py:548`–`:567` 把 `self.plan` / 待收 `include_from`
  内任何 `char_` 加数字的字符串并入“已分配”表。
- `driver.py:2051`–`:2057` 拿这张混入候选值的表校验同一个候选计划。
- 实际纯驱动复现（没有造 Blender 对象）：

  ```text
  declared_roster = ["甲"]
  candidate = "char_999"
  pure_check = ["char_999"]
  driver_roster = ["甲", "char_999"]
  driver_accepted = true
  ```

- `tests/test_cast_hard_check.py:29`–`:53` 只测
  `unknown_cast_ids(plan, 人工提供的可信名单)`，没有驱动边界断言。
  同文件 `:64`–`:70` 还明确假定“校验在 plan 被收下之前做”，
  但并未执行这一步验证。

最小补测：用已解析的单人剧本，在 `_accept_plan_chunk`/实际 plan tool 通道
提交从未分配的 `char_999`，必须拒绝并保留旧计划；
另以真实分配记录提供合法 `char_001`，必须通过。
正反例须同走生产 roster 构造，不能继续只测手工 roster 的 helper。

### F5 · P1 · A2 的草案与批处理导出闸没有需求测试，仍可绕过

证据：

- `editor.py:496`–`:543` 的 `characters=` 只校拍点引用，
  不校 `draft.characters` 本身。
- `editor.py:611`–`:612` 直接以草案替换角色；
  `driver.py:1261` / `:2237` 的 B1 与修复合并均调用它，
  不经过 `_accept_plan_chunk` 的新增检查。
- 同一诊断脚本实测：

  ```text
  supplied_known_characters = ["甲"]
  accepted_draft_characters = ["char_a"]
  merged_plan_characters = ["char_a"]
  ```

- exporter 的 `_cast_id_errors` 在 `export_director.py:152` 遇
  `roster=None` 直接返回无错；上述四个 tools 导出入口也都未传 roster。
- `tests/test_cast_hard_check.py` 共八条，没有一个调用实际 exporter，
  没有一个调用 `extract_draft` / `merge_draft` / 驱动草案入口。
  其文件开头“交付拒绝导出”的说明不是已执行断言。

最小补测：

- A2 错误草案分别从 B1、repair/react 实际入口送入，断言拒绝、
  旧计划不变、错误码和合法名单存在；合法已分配 id 对照放行。
- Blender 批处理导出构造存在表外角色的计划，断言拒绝且未生成视频/错误交付包，
  合法名单对照真的落产物。
- 不把导出闸缺省 `None` 当成通过；调用者必须提供明确可信来源或明确报告缺少数据。

### F6 · P1 · A4 配置单测绕开真实 GUI 装配，面板超时仍落成 120 秒

证据：

- `driver.py:206`–`:209` 仅在 `limits is None` 时读 `config.llm.timeout_s`。
- `modal_operator.py:179` 永远传 `limits=limits or DriverLimits()`；
  未显式传入时也因此不是 None。
- `driver.py:86` 的 `DriverLimits.llm_timeout_s` 默认是 120.0。
- 组合复现：

  ```text
  configuration_timeout = 750.0
  direct_driver_timeout = 750.0
  same_expression_with_no_override_timeout = 120.0
  ```

- `tests/test_config_v16.py:49`–`:60` 直接构造 driver，完全避开 GUI 的装配表达式；
  `:63`–`:72` 只测显式覆盖，无法识别“装配层默认值冒充显式覆盖”。
- `tools/run_headless.py:50` CLI 默认 120.0，`:151` 构造显式 `DriverLimits`，
  同样让不带 `--llm-timeout` 的 CLI 不读新配置。

最小补测：

- 真实 `build_run_context` 输入面板值 750，截获 transport.chat 真正接收的 timeout，
  必须是 750；配置对象 deep-copy 不回写也一并断言。
- CLI “未给参数”读配置 750，“明确给 120”覆盖为 120 两条对照。
- 保留现有显式 DriverLimits 覆盖行为，不能为修接线删掉覆盖测试。

### F7 · P2 · A3 环境动作引导只测辅助方法，实际工具提前返回另一条消息

证据：

- `tool_bindings.py:246`–`:248` 先 `_require_character`；
  环境主体根本不在角色表时立即返回，不执行 `:249` 新增的在场检查。
- 直接执行实际工具错误返回函数体，`environment_flag` 的结果：

  ```text
  ok = false
  message = 找不到角色 environment_flag。现有角色: 甲
  contains_vfx_guidance = false
  ```

- `tests/test_tool_bindings_env.py:22`–`:33` 绕过引擎包导入，
  `:60`–`:65` 仅调用 `SceneContext.require_character_in_shot`。
  这证明新文案存在，却没有证明模型调用 `character_action` 会收到它。
- A3 任务卡 `:140`–`:148` 针对的正是干鱼串/彩旗等非角色主体，
  不是只针对“已存在但不在本镜”的角色。

最小补测：在 Blender 注册表上执行 `character_action`，
分别输入不存在环境主体、存在但不在镜头的角色、在镜角色；
前两者错误必须含当前镜角色表与 vfx 指引，后者仍执行合法动作。
现有 helper 单测保留，但不能独自计为工具层验收。

## A1 与其他观察的边界

- `tools/run_tests.ps1:141` 已登记 `test_cylinder_body.py`，
  满足探针清单接线；代码有世界 AABB、锚点、高度、网格顶点数四个断言。
  本角色未启动 Blender，因此没有声称该探针通过，也未声称画面外观验收完成。
- A3 的 R015 三条新增纯层测试已通过；本报告未找到由这三条直接证实的反例。
- A4 任务卡要求 CFG_022，而实现/测试使用 CFG_023；
  现行 CFG_022 已用于 `orchestration.draft_candidates`
  （`config.py:458`、`tests/test_best_of_n.py:62`）。
  这是规格编号冲突，需要统一文档与错误码分配，不能直接把实现改回已占编号。
  此项交规格角色，不冒充本报告的运行失败。
- 完整 pytest、全部 Blender 探针、真实模型样片、已有 RK-13 红线均由主线负责。
  本角色没有执行它们，也不继承旧证据声称当前通过。

## 建议主线修复顺序

先修 A5 pytest 导入/目录夹具（恢复测试可执行），再按卡序补 A2 可信名单与草案/导出
入口测试、A3 工具入口测试、A4 GUI/CLI 实参测试，最后完成 A5 真实登记→无人值守交付
与计数对拍。每段有正反例，失败先修，再继续；最终完整套件不得跳过。

本目录的 probe 是只读诊断和复现辅助，不是新增产品验收标准；
源码 AST 抽取不应作为最终替代真实入口测试的降级方案。
