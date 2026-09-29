# v1.4 执行计划（对照 `改进执行文档v1.4.md`）

基线：commit `51c71f1`，`python -m pytest` 全绿（796 passed），
`tools/run_tests.ps1` 25 项全绿，Blender 5.2 位于 `D:\Blender 5.2\blender.exe`。

## 阶段顺序（§5）

P9.4 → P9.5 → P10 → P11 → P12 → P13 → P14(-1..5) → P15 → P16

## P9.4 子步骤（W1a＋W1b）

| 子步 | 内容 | 关键落点 |
|---|---|---|
| a | 契约：删 `screen_direction`、加 `declared_shot_number`/`speaker_*`/`dialogue_pins`；`enums` 加 `RagBackend.HYPERGRAPH`/`Capability.HYPERGRAPH`/`E_MOTION_*`/`E_SCRIPT_002` | `contracts/plan.py` `contracts/enums.py` `contracts/errors.py` |
| b | 配置：删 5 个死几何字段；加 `character.*`、`budget.max_llm_calls_ceiling`、`orchestration.max_shots`、`rag.plan_prefetch_tokens`、`framing.headroom_policy`；改默认值（formula/max_wall/full_concat）；`crowd.enabled` 三态；`gen_specs` | `contracts/config.py` `specs/config.default.yaml` |
| c | SDL 1.4 ＋ `with_labels` 落盘/读回/迁移；版本串回归面（#27–33） | `contracts/sdl.py` `layer2_sdl/*` `layer9_persistence/project_io.py` |
| d | `sdl_validator` 守卫（X2）＋ 枚举单源（X8/S8） | `layer2_sdl/sdl_validator.py` |
| e | `compliance` 删 R014 空镜分支（X6）＋ 删 `CODE_SCRIPT`（F5）＋ 档位表（X12 之 R016） | `layer5_orchestrator/compliance.py` |
| f | R012 收窄（X9）＋ `screen_facing_for` 抽取＋新增 R019 | `layer3_engine/rule_checker.py` `layer3_engine/scene_context.py` |
| g | 预算单值（X14）＋ 守卫拆分（X7）＋ `shot_audit` 增 `composition_score/threshold`（R45）＋ `repair_applied` 事件 | `layer5_orchestrator/driver.py` |
| h | replay 消费 `brief_received`（X5） | `layer9_persistence/replay.py` |
| i | manifest 增 `llm_calls`/`retrieval_calls`/`crowd{}`（R45） | `delivery/manifest.py` |
| j | `orchestration.max_shots` 取值接线；`planner` 不限时省略 `maxItems`；离线按剧本镜数出 mock 计划（含 `duration_frames`） | `layer1_input/shotlist.py` `layer5_orchestrator/planner.py` `layer5_orchestrator/offline.py` |
| k | `headless_runner.save_run_project`；`run_export.py` 补参；`run_headless.py` 补 `--preset` | `layer5_orchestrator/headless_runner.py` `tools/run_*.py` |
| l | 长夹具 `script_long_61.md`、`plan_long.json`、`gen_golden` 扩展、重生成派生夹具 | `fixtures/` `tools/gen_golden.py` |
| m | `.gitignore` 三通配；`run_tests.ps1` 缺 Blender 非零退出＋`rks.json` 钩子 | `.gitignore` `tools/run_tests.ps1` |
| n | 先红/新测试全部落地并全绿 | `tests/` `tools/blender_tests/` |

## 已完成

- [x] 全量审查现状（git/测试/文档）
- [x] 全量阅读 `改进执行文档v1.4.md`（§0–§7）

## 进度

- P9.4：**完成**（a–n 全部落地；`python -m pytest` 850 passed；
  `tools/run_tests.ps1` 25 项全绿；§4.4 步骤 1 / 步骤 3 按字面跑通，
  证据在 `docs/evidence/offline_run1`）。
- P9.5：**完成**（`build_run_context` / `export_finished_run`，四件套注入、
  `export_started`、`SUFFIX_HELP`；新探针 `test_operator_end_to_end.py` 已登记，
  `run_tests.ps1` 25 → 26 项全绿）。
- P10：**完成**（`cinema/anchor.py` + profile 派生的 `SHOT_FRAME`/`HEAD_SHOTS`，
  角色工厂/构图/校验器/知识卡/动作模型全部收敛；新探针
  `test_character_geometry.py`（RK-4/RK-14/RK-15）已登记，27 项全绿）。
- P11：进行中
