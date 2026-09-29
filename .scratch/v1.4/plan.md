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
- P11：**完成**（D-1 行内台词、D-2 中文数字/分句否定、D-3 括注别名、
  `scene_contract.py` 语义收敛层、F2 不伪造说话人、F4 的 R015 顺序/身份错位；
  新探针 `test_scene_contract.py`（RK-3）已登记，28 项全绿）。
- P12：**部分完成**（`7b5c893`）
  - ✅ BW-1 姿态别名 + `INTERACTION_PARAMS` 同批；BW-4a `stand` 末帧绝对落地；
    R008 双向（`06baeed`）
  - ✅ X11 两个标签开关的生效域 + `test_label_toggles.py`（`7b5c893`）
  - ⛔ 待办：BW-2 标签**标签间**避让（`label_baking.py` 目前只有"出画推回"与
    "遮挡上移"，没有标签互相让位）；RK-1/RK-2/RK-5 的
    `test_label_layout.py`；RK-6 的悬空双向探针；RK-16/RK-17 的探针重写
    （S6/S7/X13）
- P12：完成（含安全审计修出的 F1/F2）
- P13：完成（`tests/test_shotlist_render.py` + 64 镜端到端，证据 `docs/evidence/offline_run2`）
- P14：P14-1 / P14-2 完成（1075 卡 + 超图索引 + 九道门）；P14-3（案例层）与
  P14-4 的线协议由并行 agent 进行中；P14-4 的检索消费部分完成
  （`rag.backend=hypergraph` 默认、降级留痕、`knowledge_trace.json`）；
  P14-5 的打分器与 A/B 完成（`tools/holdout_score.py`、
  `tools/ab_triple_baseline.py`）。
- P15：完成（manifest 全字段 + 冲突错开 + prompts 逐字段对拍）
- P16：完成（构图门 RK-10、空断言检查、探针清单双向断言、证据钩子、
  `CONTEXT.md` + `docs/adr/0007…0012` + AGENTS.md 状态）

## 仍未完成（如实记录）

1. **held-out ≥1200 条**：需要换族标注器（本地 `qwen3-vl:30b`）跑数小时；
   当前 `fixtures/knowledge_holdout.jsonl` 为空 → `tools/holdout_score.py`
   一律报 `INCOMPLETE`，RK-13 的 Q1–Q7 在 `rks.json` 里是 `pass: null`。
2. **人审 ≥120 条**：§2.3c 的约束④要求人复核 10–15%，agent 不能替代
   （`tools/check_holdout.py` 的门⑦专门拒绝 agent 自评）。
3. **RK-7**（台词三方对拍）探针尚未编写。

## P14-3 收尾（本轮，`docs/evidence/20260930-071500/`）

- [x] `block_director/knowledge/cases.py`（新增，无 bpy）：`CaseIndex` 三态、
      `load_index`、`render_cases`、`carries_constraint`；**Case 无 `forbid` 字段**。
- [x] `block_director/knowledge/tokens.py`（新增）：超边与案例**同一个** token 估算。
- [x] `tools/kb_fetch/build_cases.py`（新增）＋ `knowledge/cases.{jsonl,manifest.json}`：
      **726 篇**（≥300），K1/K2 = 100%，体积门 pass，`--check` 幂等。
- [x] `tools/sidecar_server.py`：删掉内联 `CaseLane`，改用包里的 `CaseIndex`；
      trace 增 `lightrag_index_fingerprint` / `cases_index_fingerprint`。
- [x] `retriever.py`：三栏注入（硬约束／经验建议（软）／参考案例）＋软边单独成栏
      ＋**三栏共用一个 token 上限**（此前硬约束与卡片各自用满一次 = 2× 上限）。
- [x] `scene_contract.py::shot_constraint_query()`：**契约串的生产者**——
      在此之前超图那一条通道在真实运行里一个种子都命中不了（`parse_query` 只认 `键=值`）。
- [x] **顺带修掉的三条真实缺陷**（都是本轮回溯出来的，不是重命名）：
      ① 分栏只看 `hardness` 会把"带 `forbid` 的软边"降级进「经验建议（软）」栏
      （索引里实测有 1 条）——禁忌永远进硬约束栏；
      ② `block_for_plan` 拿中文摘要去查超图，一整场预取的超图那栏恒空——
      `declared_constraint_query()` 从分镜表的**声明**（镜别/手法）拼出契约串；
      ③ **RK-6/RK-8 静默掉成 `not_measured`**（上一轮证据 18/19，本轮一度 16/19）：
      **真因是 PowerShell 5.1 用 ANSI 代码页解码 Blender 的 UTF-8 stdout**——
      探针标记里的中文（规则名、冲突文案）被解成乱码字节，`ConvertFrom-Json`
      整行失败，该探针的 `passed` 名单丢失，挂在上面的 RK 就变成"未量"。
      修法：`run_tests.ps1` 在任何子进程之前把控制台/管道编码设成 UTF-8 ＋
      `PYTHONIOENCODING=utf-8`；并把标记负载改成**按大括号配对重拼**（抗流交错），
      解析不到时把负载写进 `work/probe_parse_fail-<label>.txt`。
      （顺带修的另一条：`test_phase2_motion.py` 曾上报 `"min_z": NaN`——那是
      **非法 JSON**，本身也该修：`_min_z` 改为 `None`，
      `tools/check_assertions.py` 新增"探针不得出现非有限浮点"的静态规则。
      早先把它当成了 RK 掉线的**唯一**原因，实测不是。）
      **仍未收口**：`cast-panel` 与 `llm-trace` 两个探针的负载仍解析不出来
      （转义层级不一致／仍有乱码字节），它们**不承载任何 RK**，因此不影响验收；
      证据留在 `work/probe_parse_fail-*.txt`。
- [x] 测试：`tests/test_cases.py`(15)、`tests/test_cases_corpus.py`(10)、
      `tests/test_knowledge_cases_wiring.py`(7)、`test_scene_contract.py` 的
      "生产 → 解析 → 命中"整链；`python -m pytest` = **1250 passed**。
- [ ] held-out 长跑（后台进行中）→ 之后才能跑 `holdout_score` / `ab_triple_baseline`。
- [ ] 人审 ≥120 条（只能由人做）。
