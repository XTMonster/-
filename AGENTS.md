# BlockDirector — agent instructions

Project: **BlockDirector**, a Blender add-on that turns a script into a white-model
previs and exports it as a reference video for AI video generation.

## Where things are

- `BlockDirector_执行文档_v1.2.md` — the authoritative execution spec (v1.2). Read it before changing architecture.
- `BlockDirector_执行文档_v1.0.md` — original spec, kept for history only. Do not follow it.
- `block_director/contracts/` — pure-Python contract layer (no `bpy`). Single source of truth for the sidecar wire protocol.
- `specs/openapi.yaml` — the sidecar wire protocol; must stay in sync with `block_director/contracts/`.
- `specs/config.default.yaml` — generated from `block_director/contracts/config.py`; never hand-edit.
- `tests/` — pytest suite. Run `python -m pytest`.
- `tools/` — environment probes and the architecture audit. `tools/run_tests.ps1` runs everything.

## Rules

- `block_director/contracts/` and `block_director/utils/` must never import `bpy`.
- Anything touching `bpy` must go through `block_director/utils/threading_guard.py` (`@main_thread_only`).
- Keep `.ps1` scripts ASCII-only: Windows PowerShell 5.1 parses BOM-less UTF-8 as ANSI.
- Keep `$ErrorActionPreference = 'Continue'` in `.ps1` files that call Blender: it writes logs to
  stderr, which `'Stop'` turns into a terminating error. Check `$LASTEXITCODE` explicitly instead.
- After changing config defaults, run `python tools/gen_specs.py` so `specs/config.default.yaml` stays identical.

## Status

Phases 0-4 and 6 are done:

- **Phase 0** plugin skeleton, state machine, audit logging
- **Phase 1** character geometry, scene executor, collection routing, transactions, camera
- **Phase 2** motion library, layered blending, §9.7 conflict arbitration
- **Phase 3** framing solver (shot type + lens -> distance and placement,
  relative to subject facing, with room clamping), axis controller (180-degree
  rule plus R010), and composition scoring with ray-cast occlusion
- **Phase 4** plan-to-scene: the driver hands the parsed plan to a scene builder
  that creates environment, characters, per-shot cameras, keyframes and cut
  markers in one pass. The builder is behind a protocol so the driver stays
  bpy-free.
- **Phase 4 (eyes and hands)** scene state collection (light vs detailed), the
  four query tools bound into the registry, and a zero-dependency
  OpenAI-compatible transport for direct mode (OpenAI/DeepSeek/Ollama/vLLM).
- **Phase 6** delivery: per-shot mp4 via Blender's built-in FFmpeg, first-frame
  stills, `shots.json`, `prompts.md`, optional `camera_traj.json` and a README.
  Export refuses to run when the render audit finds a helper that would leak
  into the reference video.
- **Layer 2 / Layer 9** the SDL scene-description layer (`contracts/sdl.py`,
  `layer2_sdl/`) and persistence (`layer9_persistence/project_io.py`).
  Build a plan into an `SDLProject`, validate it (rules S1-S7), save it to
  `project.bdproj`, load it back (migrate -> deserialise -> validate), and
  rebuild the scene from it without any LLM call. Character fields serialise
  as `initial_location` / `initial_facing` to match the spec.
- **Light RAG** (`block_director/knowledge/`, no `bpy`): a hand-written card
  corpus in `knowledge/corpus.py` (132 cards across the five v1.3 domains;
  P14 expands it to nine domains), a built-in Okapi BM25 (same algorithm and
  parameters as `rank_bm25`, which Blender's Python does not ship) with a
  `rank_bm25` preference when present, and a retriever with bm25 / vector (RRF)
  / digest modes plus the 800- and 2000-token injection caps. Exposed to the
  LLM as the `search_knowledge` tool and injected into the plan prompt.
- **Replay** (`layer9_persistence/replay.py`, `tools/replay_project.py`):
  rebuild a run from `audit_log.jsonl` with no LLM call - read the full plan
  from the `plan_received` event, build the scene, then re-apply the recorded
  tool calls in order. Logs are found both at the project root and under
  `runs/`.
- **Golden Test** (`fixtures/`, `tools/gen_golden.py`, `tests/test_golden.py`,
  `tools/blender_tests/test_golden.py`): a hand-written mock plan
  (`fixtures/mock_llm_responses/plan_simple.json`) plus derived artefacts
  (`expected_sdl_simple.json`, `tool_transcript_simple.jsonl`). Regenerate the
  derived ones with `python tools/gen_golden.py` after editing the plan; the
  test chain runs `--check` so drift fails fast.
- **Scene sync and single-shot regeneration** (`layer3_engine/scene_sync.py`,
  `layer3_engine/shot_regenerator.py`, `layer7_ui/panel_shots.py`): user edits
  are found by comparing object transforms against the baseline recorded after
  each plugin build (the depsgraph handler is only an accelerator).
  `regenerate_shot(shot_id)` re-reads user placements, swaps only that shot's
  camera and keyframes, and leaves `bd_user_animated` characters untouched. The
  frame schedule lives in `cinema/schedule.py` (pure, shared by the builder,
  the regenerator and the SDL round trip).
- **UI panels** (`layer7_ui/panel_shots.py`, `panel_debug.py`): the 13.2 shot
  list (thumbnail / status / intent / size / actions) with a per-row regenerate
  button, and the 13.3 debug panel (LLM calls, tokens, cost, elapsed, audit
  pass/fail, repairs, budget left) plus actions to open the LLM trace, export
  the SDL (validated first) and export the scene state. Per-shot status is
  derived by the pure `layer5_orchestrator/shot_status.py`.
  Note: `ImagePreview.icon_id` is always 0 under `--background` (icons are
  allocated by the UI layer), so the headless test asserts the pixel data
  loaded instead.
- **Viewport overlay and the path tool** (`overlay/geometry.py`,
  `layer7_ui/draw_overlay.py`, `layer7_ui/operator_path_draw.py`): the overlay
  geometry (thirds grid, title/action safe areas, dashed axis, frustums,
  movement paths) is pure and unit-tested; only the GPU drawing lives in the UI
  layer. `draw_handler` never fires under `--background`, so the tests assert
  registration plus geometry instead of pixels.
  `commit_drawn_path()` is split out of the modal operator so the
  "RDP -> Catmull-Rom -> keyframes" pipeline is testable headlessly, and the
  `BD_Path_*` curve goes into Guides with `hide_render=True`.
- **Depth sequence and full concatenation** (`delivery/depth.py`,
  `layer8_delivery/depth_pass.py`, `layer8_delivery/concat.py`):
  `export_depth` renders 16-bit grey depth PNGs per shot using the camera's
  View Z Depth through `view_layer.material_override` (Blender 5.x's compositor
  File Output can only write multi-layer EXR, and Workbench has no depth
  shading), normalised to a fixed 0.1-50 m range that is written into the
  README. `full_concat` joins the per-shot clips inside Blender's own sequencer
  (no external ffmpeg) and pins each strip to the frame count known from the
  per-shot render, because VSE's `frame_final_end` is exclusive.
- **Tool layer** (`layer3_engine/tool_bindings.py`, `cinema/camera_motion.py`,
  `layer5_orchestrator/timing_tool.py`): all 17 tools from the spec are
  registered. `move_camera` moves the Track-To target along an arc instead of
  rotating the camera (no euler flips); `reframe` reuses the existing camera
  object; `move_character` defaults the walk's `from` to the character's
  current position; `estimate_shot_duration` is pure and unit-tested.
  The three control tools (`request_self_review`, `finish_shot`, `abort`) are
  registered from `layer5_orchestrator/control_tools.py` and handled by the
  driver: `request_self_review` only sets `_pending_review` (no extra LLM
  call), `finish_shot` sets `_pending_finish` so CHECKING skips the repair loop
  for that shot while still recording the audit, and `abort` sets
  `abort_reason`, which `step()` turns into CANCELLED (not a success).
- **Cast management** (`layer7_ui/panel_cast.py`, `layer3_engine/cast_editor.py`):
  list / colour / add / remove. Each edit touches three places - the Blender
  objects, `SceneContext.spec` (which the SDL and the project file are exported
  from) and the reference check that refuses to delete a character a shot still
  uses. `next_character_id` lives in `contracts/cast.py` so it is unit-testable
  outside Blender. Registration order matters for a `CollectionProperty` of a
  `PropertyGroup`, and `register_all` swallows per-module failures, so a test
  compares `registration.MODULES` against what actually registered.
- **Run settings and delivery** (`layer7_ui/panel_main.py`,
  `layer7_ui/run_settings.py`): provider / model / audit level / budget /
  preset / appearance / backend plus an export button. The panel never edits
  the config file - it deep-copies the loaded config, applies the panel values
  and runs `config.errors()` before starting, so a bad combination (depth with
  workbench) is reported instead of run.
  `config.budget` used to be dead: the driver now builds its budget limits from
  it, and `max_llm_calls_per_scene_formula` (`"shots * 8 + 40"`) is applied once the
  plan is known - taking the stricter of the formula and the static ceiling, so
  the Phase 4 "<= 8 calls" target cannot be silently exceeded.
- **LLM trace** (`layer6_audit/audit_logger.py`): records the full prompt and
  response per call, as 11.3 requires - `prompt` is the rendered message list
  and `response` is `{content, tool_calls}` with a fixed shape even for failed
  calls. Metadata stays as it was. `llm.trace_max_chars` truncates each field
  (marking `truncated: true`, 0 = no cap) and `llm.trace_prompts=false` falls
  back to metadata only - the trace carries script text, so that switch is the
  escape hatch.
- **Stage B5 and context governance** (`layer5_orchestrator/react.py`,
  `context_budget.py`): `should_react()` encodes the three trigger conditions
  from the spec and the driver runs a bounded tool loop (tool_choice auto, once
  per shot, `react_max_steps`, 0 = off), re-auditing afterwards. The loop trims
  its own conversation to `context_window_tokens` each turn, keeping the system
  message and the newest turn. Completed shots are summarised into the prompt
  instead of replaying history.
  `driver.pause()/resume()` stop the state machine advancing without losing the
  built scene; `orchestration.mode = react_only` is refused (CFG_013) rather
  than silently ignored.
- **Real-protocol end to end** (`tests/test_protocol_end_to_end.py`): a stdlib
  HTTP server speaks both the sidecar wire protocol and the OpenAI-compatible
  one, and the whole chain (plan -> repair -> per-shot review) runs over each.
  Both modes produce an identical plan and the same call count - that is the
  evidence behind 2.4's "both modes are first class".
- **Stage B1, the editor** (`layer5_orchestrator/editor.py`): the plan schema is
  now a shot list (7.2), and each shot gets one strict-schema draft call whose
  result is merged back - id/order/duration stay owned by the plan, and an
  invalid draft only marks that shot instead of failing the run. B1 runs only
  when a builder exists (nothing to execute otherwise). The offline transport
  answers per stage too, so `--offline --build` still produces the identical
  scene while the call count went 3 -> 5 (a 3-shot sample is 7, still within
  Phase 4's "<= 8").
- **Real-model integration** (`tools/sidecar_server.py`,
  `tools/probe_local_model.py`, `fixtures/local_*.config.yaml`): the sidecar
  reference server (2.5) exists now - stdlib only, loopback only, and it owns
  the provider specifics the plugin should not: Ollama's OpenAI-compatible layer
  ignores `num_ctx`/`think`, and its default `num_ctx=4096` truncates a thinking
  model mid-reasoning. The first real run (qwen3-vl:30b) is written up in the
  spec's 21.10; it exposed four defects: truncated replies were reported as
  "no tool call", the step guard counted polling ticks (a slow model looked
  like an infinite loop), `emit_plan` could rewrite the plan after stage A, and
  no tool could retime a dialogue so R011 failures were unrepairable.
- **Stage S, the script read** (`contracts/brief.py`, `layer5_orchestrator/understand.py`,
  `DriverState.UNDERSTANDING`): before planning, one structured call produces a
  `SceneBrief` (speakers / gaze / beats / space / arc / props / notes). It is
  injected into the plan prompt as system text (so `trim_messages` cannot drop
  it), it drives the station via `SceneSpec.from_plan(..., brief=...)`, and R013
  compares its `gaze[]` against the plan's `shot.gaze[]`. Two failures fall back
  to `deterministic_brief()` (shot-list declarations and dialogue adjacency
  only - never a guessed pronoun) and record `E_BRIEF_001`. The brief travels
  into `project.bdproj`. `brief.enabled=false` restores the v1.2 path.
- **Contracts 1.3 and SDL 1.3** (`contracts/sdl.py`, `layer2_sdl/sdl_migrate.py`):
  the movement vocabulary, `EngineSupport`, `VfxType`, `CrowdMode` and
  `Purpose.UNDERSTAND` live in `contracts/enums.py`; `cinema/camera_motion.py`
  imports `MOVEMENT_TYPES` from there and refuses to load if its grouping tables
  drift. SDL 1.3 adds `camera.movements`, `shot.gaze`, `shot.vfx`,
  `environment.crowd` and `brief`. `KNOWN_VERSIONS` spells out `"1.2"`, and the
  roster repair only runs for files older than 1.2 (a v1.2 file always carries a
  complete roster, so a dangling reference there is real corruption).
- **All 24 movements, end to end** (`cinema/camera_motion.py`,
  `layer3_engine/cinema_engine/camera_motion.py`): the pure solver emits
  position + look-at + lens; the bpy side writes location keyframes on the
  camera, `data.lens` keyframes on the camera *data* (a bare `lens` does not
  exist and `data.lens` from the object raises "path spans ID blocks"), and
  samples the subject's own path for follow/lead/steadicam after the motion bake.
  `camera.movements` in the plan drives `build_scene` directly, and the shot
  list's "camera instruction" column is pinned onto the plan when B1 did not
  supply one. `check_shot` now evaluates at the shot's first frame, restores it
  afterwards, and takes the composition minimum over first/middle/last.
- **Crowd, VFX and prop shapes** (`contracts/cast.py`, `layer3_engine/scene_executor.py`):
  `crowd_from_script` reads what the director actually wrote ("about 30
  extras"), returns at most one group (the maximum, not the sum) capped by
  `crowd.max_instances`, and the builder makes shared-mesh instances that live in
  `context.crowd` - never in `characters`, so the cast panel, scene state,
  composition score and labels do not see them. `create_vfx` builds renderable
  `BD_VFX_<id>` proxies with a keyframed visibility window; Workbench has no
  alpha and the warning says so. `create_prop` honours `shape`.
- **One-command delivery** (`run_headless --export`): the scene is exported
  while it is still in memory, so 15's "one command -> complete export dir"
  holds for real-model runs too, not just the offline path. The chain's step 4
  now runs with `--export` and asserts the export marker.

Phases 0-4 and 6 are done; Phase 5 is done (all eleven rules R001-R011, loop
detection, budget limits, checkpoint/rollback, the human gate, Level 2
self-review and the 13.3 debug panel). Layer 1 (script parsing, dialogue timing
and coreference) is done.

### v1.4 (`改进执行文档v1.4.md`) — P9.4 … P16

| 阶段 | 落地要点 |
|---|---|
| **P9.4** | 契约删死字段 `screen_direction`、加 `declared_shot_number`/`dialogue_pins`；配置删 5 个零消费者的几何字段、加 `budget.max_llm_calls_ceiling`(200)/`orchestration.max_shots`(0=不限)/`rag.plan_prefetch_tokens`/`rag.cases_backend`/`framing.headroom_policy`，公式改 `"shots * 8 + 40"`、墙钟 120 分钟、`full_concat=True`；SDL 升 1.4 并把 `with_labels` 真正落盘/读回/迁移；SDL 校验器坏数据只报 finding；R014 空镜分支删除（X6）、`CODE_SCRIPT` 字面量删除（F5）；R012 收窄 + 新增 R019（X9/X10）；预算单值化（X14，见 ADR-0008）；`shot_audit` 增 `composition_score/threshold`、`repair_applied` 一镜一条；离线通路按声明镜数出计划 |
| **P9.5** | `build_run_context` 抽成可测函数并注入 builder/auditor/parsed_script/limits；收尾就地导出并写 `export_started`；`SUFFIX_HELP` 与 `SUFFIX_FORMATS` 同源 |
| **P10** | 冻结几何 1.70 与"头球相切"（ADR-0007），所有消费者从 `cinema/anchor.py` 派生 |
| **P11** | 行内台词（D-1）、中文数字与分句否定（D-2）、括注别名（D-3）、SemanticContract（ADR-0010）、R015 的镜号/身份错位 |
| **P12** | `body_tilt` 允许键表（BW-1）、`stand` 末帧绝对落地 + R008 双向（BW-4a）、行走起伏非负（RK-6）、标签互斥避让与描边几何（ADR-0011）、运镜确定性 RK-17、群众/特效可见性按差分掩膜重写 RK-16 |
| **P13** | 长剧本不被截断（提示侧无"其余 N 个镜号略"；显式上限超限报 `E_SCRIPT_002`）、连续成片默认产出 |
| **P15** | `shots.json` 补齐 §3.3 全字段；同层动作自动错开并留痕（US-17）；`prompts.md` 逐字段可对拍且不含引擎内部键 |
| **P16** | 构图门 ≥70% + 反向突变（ADR-0012）；无 bpy 的空断言静态检查 `tools/check_assertions.py`；探针清单双向断言与 `docs/evidence/<run-id>/{rks.json,config.fingerprint.json}` 收尾钩子；`CONTEXT.md` + `docs/adr/0007…0012` |
| **P14** | 知识栈三层：语料 1075 卡 / 九域（`knowledge/cards_generated/`）、超图索引（`knowledge/hypergraph.{nodes,edges}.jsonl`，**`hg/v2`：13 类边 / 307 节点 / 382 边**，其中带 `forbid` 成员的边 21 条（24 个 forbid 成员），arity 2–6，`rejects 0/667`，`processed == total == 250`）、L3 案例层（`knowledge/cases.*`）；`/v1/retrieve` 三通道 `cards[]/edges[]/cases[]` ＋ `trace{}`（`contracts/knowledge.py` 的 `HyperEdge`/`Case` DTO，`specs/openapi.yaml` 同批）；`Capability.HYPERGRAPH` 由**索引是否加载成功**决定；插件侧 `knowledge/client.py` 每次检索写一条 `retrieval_call` 审计事件，`knowledge_trace.json` 每次运行必写；`tools/holdout_score.py` 判 Q1–Q4/Q6a/Q6b/Q7（**Q5 属人裁决，见下**）、`tools/knowledge/quality.py` 判 Q0 ＋ E1–E3 并落 `docs/evidence/<run-id>/knowledge_quality.json`；`tools/ab_triple_baseline.py` 出三元组对照；`tools/knowledge/sample_edges.py` 出 30 条人工抽查样本（`verdict` 留空，不预填） |

**v1.5（用户裁决 D6/D7）已落地**：节点 **16 → 17**（+`intent`）、超边 **6 → 13**
（+`ACTION_BEAT`/`PERFORMANCE_PACK`/`INTENT_PACK`/`IMPACT_PACK`/`STAGING_PACK`/`SOUND_PACK`/
`TRANSITION_PACK`），`hypergraph.SCHEMA_VERSION` 升 `hg/v2`。
**schema 的单一真源是 `block_director/knowledge/hypergraph.py`**（`NODE_TYPES`/`QUALIFIER_KINDS`/
`EDGE_TYPES`/`REQUIRED_MEMBERS`/`OPTIONAL_MEMBERS`/`TYPE_PRIORITY`/`VALUE_DOMAINS`/`QUERY_KEYS`）；
`tools/check_holdout.py`、`tools/kb_fetch/{build_hypergraph,holdout_gen,vocabulary}.py` 一律**导入**它，
不得再抄第二份——本次扩类暴露的正是"各抄一份 6 类型 / 16 kind"的漂移。
`INTENT_PACK` 的查询键是 `意图`（`QUERY_KEYS`），取值是 12 个中文闭集（`VALUE_DOMAINS["intent"]`）。
标注通道可选 GLM（`tools/kb_fetch/llm.py::GLMClient`，`family=zhipu`，`GLM_API_KEY` 只从环境变量读）
或本地 `qwen3-vl:30b`；**无论走哪条都必须与抽取族（DeepSeek）不同**，`annotator.family` 写进每条。
Q5/Q7/E3 走 `tools/holdout_review_llm.py` 的**双模型复核通道**（`reviewed_by: "llm-panel"`，
**绝不写 `human`**）。门⑦ 在**默认口径**（`--reviewer-classes human`，协议原样）下仍判红；
2026-10-01 用户明确授权"机器侧承担这一层"之后，**验收链显式传**
`--reviewer-classes human,llm-panel`，报告里 `reviewed_by_class` 如实写清是谁裁的
（当前实测 `{"llm-panel": 7}`）——记录本身一个字节都没被改写。
口径与理由见 `docs/evidence/<run-id>/holdout_gates.json` 的 `gate_7_human_review`，
不变量由 `tests/test_check_holdout.py`（"门⑦ 只在已记录的口径下转绿"）与
`tests/test_acceptance_fixtures_present.py`（链上每一步必须活着且会判）钉住。

**L3 案例层（P14-3）已落地**：`block_director/knowledge/cases.py`（三态 `lightrag`/`hybrid`/`off`、
`CaseIndex`、`render_cases`，**没有 `forbid` 字段**——E3 的机制保证）＋
`tools/kb_fetch/build_cases.py` ＋ `knowledge/cases.{jsonl,manifest.json}`（**2026-10-02 实测 810 篇**，
`narrative=751/lesson=58/sequence_pattern=1`，`source_ref` 六字段全非空、许可全在白名单、
摘要过"≤2 句 / ≤120 字"门、重复构建逐字节相同）。
`case_type=sequence_pattern` 现在有**两条**判据分支：`sequence_pattern_of` 只认**显式箭头枚举**
（`→`/`->`，每段各自落到一个节拍、不同节拍 ≥2、`beat_sequence` 严格按文本顺序），
`prose_sequence_pattern_of` 认**散文里的显式顺序词枚举**（`先/然后/最后` 这类，节拍约束同上）；
两条的 `excerpt` 都是原文的连续子串。
**⚠️ 门限与授权出处（2026-10-02 盘点，待用户确认）**：本节此前写"`SEQUENCE_FLOOR = 7`…
**只许升**…'散文里猜套路'的分支已删除"——**与 HEAD 不符**。现行
`tools/kb_fetch/build_cases.py:137` 是 `SEQUENCE_FLOOR = 1`，散文分支在 `:325`
**被重新加回**（`:447-455` 两条分支一起进候选）。唯一的落地记录是
`build_cases.py:120-137` 的注释与 `docs/knowledge/AUDIT_RESIDUAL_20261001.md:21` 里
"我按用户'改门限吧'落地（`9d2bc62`）"——**属 agent 转述，出处未被追平**；而
`ACCEPTANCE_STATUS.md:132` 与本节下方的"拍板前不要改门限"两条反向条款仍在库里。
本文件按"缺证据不得当成通过"的纪律把现状记清并列为**待裁决项**，不替用户判定合规。
`sidecar_server.py` 不再自带第二份
实现，改用包里的 `CaseIndex`，trace 补上 `lightrag_index_fingerprint` /
`cases_index_fingerprint`；插件侧检索器现在真的会**分三栏注入**
（硬约束／经验建议（软）／参考案例），且**三栏共用同一个 token 上限**；
`rag.cases_backend` / `rag.cases_top_k` 也终于有了生产者
（`off` ＝ 恒空、**不向 sidecar 索要案例**、不算降级；条数不再是写死的 3）。
同时补上一个真实缺陷：`hypergraph.parse_query` 只认 `键=值`，而此前**没有任何生产侧
生产者**，于是含 `forbid` 的那一栏在真实运行里一个种子都命中不了——
`layer5_orchestrator/scene_contract.py::shot_constraint_query()` 就是那个生产者
（`editor.py` 每镜用它取知识）。证据：`docs/evidence/20260930-071500/`。

**2026-10-01 语料重建（用户裁决：理论不要自己写，要别人写的）——这一版是当前口径**：
`sources.yaml` 里 27 条 `mode: manual`（自撰笔记）全部移除，换成 41 条**他人著作**
（Gutenberg 公有领域教材 ＋ MIT OCW `CC-BY-NC-SA` 讲义 ＋ Frames Cinema Journal
`PersonalStudy` 论文）；生成卡 **1981 张、自撰 0 张**（重建前 1601 张里 671 张自撰），
`python tools/knowledge/authorship_report.py` → `passed: true`，并接进
`tools/run_tests.ps1` 的证据钩子（`authorship.json`，失败归属 RK-13）。
K1–K5 全绿（2113 张 = 1981 生成 ＋ 132 手写策展；最小域 `anime` 141 张 / 6.7%）；
超图 **890 条边 / 2843 原子**，Q0 pass，13 类边全部非空（`extract/v6` 的"逐类自问"把
`IMPACT_PACK` 15→23、`INTENT_PACK` 45→56、`SOUND_PACK` 21→24 等补了回来），
但 **`AXIS_RULE` 37 → 11**（去重口径的必然结果，见待裁决清单）；
`python -m pytest` = **1367 passed / 0 failed**。
**仍红的**：held-out 的 ③/⑥/⑨/⑩ —— 根因不再是实现缺陷，而是
**oracle 是上一代语料的产物**（卡 id 换代），必须重标一轮（⑦ 当时 0/120，
**后按上文的机器复核授权处理**）；
以及 **L3 `SEQUENCE_FLOOR = 7` 现在无解**（外部语料里箭头枚举实测只有 1 个、派生 0 条）。
逐项对账与必须由用户拍板的四件事见 `docs/knowledge/ACCEPTANCE_STATUS.md`，
裁决理由见 `docs/adr/0013-theory-must-be-authored-by-others.md`。

### P14 现状（2026-10-02 13:40 起 —— **下面那块数字自此作废**）

**2026-10-03 09:4x 的账（最新，以这行为准）：门①–⑩ 全 pass（第一次）；Q0–Q4、Q6a/Q6b/Q7、
Q4_pre、E3、E3_cases 全 pass；链上只剩 `not passing: Q5,E1`（Q5 是结构性不可达、E1 是语料
适配度），`E2` 是诊断量。`python -m pytest` 全绿、`run_tests.ps1` 31/31。
RK-13 仍记 failed——因为 Q5/E1 已归位成硬门。证据 `docs/evidence/20261003-094528/`，
逐条见 `ACCEPTANCE_STATUS.md` §三十五…§三十九。**

**2026-10-02 20:0x 的历史账：门①–⑥、⑧–⑩ pass；门⑦ fail；Q4/Q6b 差 5 条；RK-13 记 failed。**
（⑪ 是**诊断**，不参与判定。）`python -m pytest`＝全绿；`powershell -File tools\run_tests.ps1`
＝ 31/31 探针。**这一轮不是全绿，别照抄旧结论。**

* **门⑦ fail**：`needs_human 157 / reviewed 0`（口径要 ≥ min(157, 120)）。成因**不是**标注没做，
  而是双模型复核（DeepSeek＋GLM 两族）对 `needs_human` 条目的通过率只有 **8%**
  （150 条里 139 条一致否决，理由全是"这张卡不支持这条边"）。三个对照排除了"证据没给全"、
  "forbid 类特有"、"出处挂错卡"：改喂全部来源卡仍然否、随机 12 条**非**禁忌条目 11/12 否、
  v14 修好出处之后仍然 11/12 否。根因是**复核判据 4 与 schema 的冲突**——必填槽位是
  推断填满的（卡里只写"留出前方空间"，抽取器必须补 `景别=LS`／`机位=平视`），
  复核看到卡里没写就判"不支持"。**没有应用那 139 条否决**：应用它会让门⑥ 同时红
  （72 张卡失去唯一条目，其中 71 张的边全带 forbid），而门⑦ 要的 120 条在这个通过率下
  结构性不可达。逐条见 `ACCEPTANCE_STATUS.md` §二十八，证据在 `work/glm_sb3/`。
* **Q4/Q6b = 3019/3024**：差的 5 条全是同一条 `AXIS_RULE`（`axis_topic=运动轴`）——
  它的 `pair`/`axis_side` **没有查询键**，同一话题下区分不开，top-3 装不下。
  即待裁决清单第 12 条在指标上的第一次显形。
* **E1 的落点仍然是语料**（§二十七.7）：L3 的 810 篇里**有中文摘句的 0 篇**，
  6 个中文查询逐镜命中 **0**；换成英文查询打英文语料也只有 **1/18**。中文来源经正面盘点
  **整族不可达**（DNS 投毒＋TLS 阻断）。

**⚠️ 2026-10-02 20:4x 追加：知识栈的"证据支持率"第一次被量出来，只有 21.2%**

`tools/knowledge/attestation.py`（每次链运行都会写
`docs/evidence/<run-id>/knowledge_attestation.json`，**诊断不判门**）：拿每条边**自己的
来源卡正文**回查它的每个槽位取值。入库（700 条边）实测：可查槽位 1793 个里 **只有
21.19%** 能在卡里找到依据；**只有 41/700 = 5.86% 的边每个槽位都有依据**（另一次抽样
上是 20.7% / 5.4% —— 两次几乎相同，所以它是这条抽取口径的**稳定性质**）。这与独立复核面板判掉 92% 是
同一件事的两面（`ACCEPTANCE_STATUS.md` §二十九）。结构证据：2909 个「卡 × 边」只有
743 个不同成员集，**55.9% 的链接属于被 ≥10 张卡共用**的模板集，最热的一条被 173 张
互不相干的卡共用。病根是**提示词与校验器自相矛盾**（提示说"不需要在一张卡里凑齐整套
pack"，`to_edge` 却强制必填槽位写全 ⇒ 模型只能填）。四代"硬弃边"实测全败
（700 → 616 → 32 → 25 条边），所以**没有**把它做成硬门，而是记账 ＋ 诊断。
**原子缓存在位之后，反复构建会收敛到不动点并逐字节一致**（§29.4 的 run4 == run5），
这才是 oracle 能稳定重标的前提。
**"索引换代 ⇒ 整份 oracle 必须同批重标"这条已经跑完（2026-10-02 22:45）**：
把索引/节点/卡片清单/词表**快照**到 `work/snap/`，用显式路径重跑整池（`work/glm_v20/`，
2948 条 / 88 批 / 0 拒收），合并 0 unknown / 0 unresolvable / cards_covered 2331，
门①–⑥、⑧–⑩ **全 pass**，只剩门⑦（见上）。**教训**：池标注、合并、门必须对**同一份
快照**跑——第一次合并时盘上的索引/词表被另一条 lane 的一次构建换掉（池用含 `MLS` 的词表、
盘上那份没有），当场拒收 890 条（3 词表外 ＋ 887 不可解析）。证据
`docs/evidence/20261002-224500/`（`holdout_gates.json` / `knowledge_quality.json` /
`knowledge_attestation.json` / `rks.json`）。

**规模（2026-10-02 20:5x 实测，别再用旧数字）**：`sources.yaml` 来源 **286** 条
（L1/L2 **106** ＋ `layers: [L3]` 的 **167** 篇，含 Animation Studies 161 篇 CC-BY 4.0；
新增的 50 条 StudioBinder 是 `PersonalStudy`，见 `MODERN_SOURCES.md` §七）；
生成卡 **2221** 张，卡片全集 **2353**；超边索引 **700** 条边（`extract/v14` ＋ `gate/v2`：
`raw_edges 700 = valid_unique 700`、`rejects 0`、原子 **2909**）；oracle **2948** 条；
L3 案例 **810** 篇。门⑥ 的明细：
`cards 2353 / cards_expected 2331 / excluded 22 / expressible_share 99.07% / missing 0`。
manifest 另带 §2.3 的 per-chunk 账 `chunks`（708 条，`--refresh-ledger` 可复算）。

**2026-10-02 23:5x 追加（`c2d7b98`）：L3 补了 BFI 的 35 篇逐片分析，同语言对照仍在噪声级。**

* **来源**：BFI / Sight & Sound 的 **35 篇逐片评论与制作分析**入库（robots 404 ⇒ RFC 9309
  放行；标题与署名读页面自带元数据块，不从 slug 猜）。**许可如实记 `PersonalStudy`**，
  `/terms-use` 2.2 那句 "you may not … copy … reproduce … any information or content
  obtained from the Site unless expressly authorised by us" 原文逐字写在 `sources.yaml`
  与 `MODERN_SOURCES.md` §八里，**待用户复核**。来源 286→**321**（L3 167→202）；
  案例 810 篇里 BFI **35 篇**；`chunks` 仍 **709**（`layers: [L3]` 不进 `chunk.py`
  ⇒ **索引与 oracle 不受影响**）。
* **顺手修掉两个真缺陷，都在案例层的"取段"上**：① `pick_excerpt` 取段首 ⇒
  标题/导航（"TV Writing and Development"／"MEDIUM CLOSE-UP SHOT DEFINITION"）被当成
  参考案例（与 §24.2 的 OCR 说明文字同一形状）→ 改成**按内容打分选窗**＋子句/词边界兜底；
  ② `segments_of` 只切固定 3 句窗 ⇒ 现代网页（句子 200–300 字、页头是一整块 515 字的
  "句子"）**整篇 0 段**（反向门 `tests/test_source_traces.py` 抓到 6 条来源零产物）→
  窗口改成**自适应 3→2→1 句**。`build_cases` 回到 `passed: true`
  （`quote_gate` 拒收 798 → **117 / 9121 = 1.3%**，上限 5%）；那 6 篇从 0 段变成 8–20 段。
  例外表因此**按设计清空**（原先唯一的例外 Skwigly 那页也产出案例了）。
* **E1 的实测（照实报）**：同语言对照（英文查询打英文语料）**1/18 → 0/18 → 1/18 → 0/18**，
  四个状态之间是噪声（样本 18 条）。**补现代逐片分析没有抬动它**；门限一个字没动，
  E1 仍 `not_measured`。结论：E1 的瓶颈不止"有没有逐片分析"，还有**查询与语料对不上**
  （产品查询是"这一镜怎么拍"的具体描述，L3 里能命中的多是定义/教学页）。
* 终态：`python -m pytest` 全绿；`run_tests.ps1` 31/31 探针，**RK-13 仍判 failed**
  （门⑦ ＋ Q4/Q6b，未变）；证据 `docs/evidence/20261002-235414/`。

**2026-10-03 00:4x 追加（`knowledge/cases.search_zh.jsonl`）：E1 第一次量到非零。**

* **病状**：`CaseIndex._text` 刻意只吃**作者写的字**（`excerpt` ＋ 出处标题），
  而 L3 的 810 篇**含中文的 0 篇**、产品查询是中文散文 ⇒ BM25 对 6 个镜头
  **一个都不返回**，E1 **连分母都没有**。
* **修法**：`tools/kb_fetch/case_search_zh.py` 为每条案例生成一句 ≤90 字的
  **中文检索线索**（GLM 通道，与抽取族 DeepSeek 不同族；只搬运作者摘录里已有的信息）。
  它**只是检索键**：`render_case` 的输出与有没有线索逐字相同；
  出现 `必须/禁止/不得/务必` 的线索丢弃（E3）；文件带 `cases_sha256`，
  案例层换代就**整份不用**（`search_zh_stale`）。产出 739/810 = **91.2%** 覆盖，
  作为产物入库（检索是离线的）。
* **实测**：E1（产品的 6 个中文镜头查询 × top-3 = 18 条，跨族面板）
  **0 命中 → 3/18 = 0.1667**，三次独立运行（第三次带索引指纹）**同样的三条命中**，
  不是噪声。证据 `docs/evidence/20261003-e1-zh/`。链上现在写 **`E1=fail`**
  （0.1667 < 0.70），不再是 `not_measured`——打分行自带 `cases_fingerprint`，
  陈旧门认它是这一份索引的证据。**门限一个字没动。**
* **怎么读**：接上了，但够到的常常不是"讲这一镜怎么拍"的那一段——18 条里一半是 1–2 分。
  与 §三十.4 的英文对照（0/18）指向同一层：**语料适配度**是下一个缺口。
* 用例：`tests/test_case_search_zh.py`（9 条：匹配/陈旧/缺失/读不出 + 不污染渲染 +
  标签不许进检索 + 生成器的 E3/长度/语言守卫 + 入库产物同代）；`test_knowledge_cases_wiring.py`
  里"纯中文查询拿不到案例"那条按新契约改写（同一意图的更准写法）。

**2026-10-03 01:xx 追加：给 L3 做**相关性过滤**——机制留下，**默认关闭**（三次实测否决）。**

* 动机：E1 量的是**精确率**（返回的案例里相关的比例），而 top-3 里一半是噪声
  （查询"…表情从困惑转为狂喜"的 top-1 是 1900 年代"银幕明星…"句）。
* 先量了两条确定性路，**都无效**（免得重走）：分数下限抬不动（`work/zz_e1_floor_sim.py`）；
  按查询语言选检索面几乎不改排序（`work/zz_e1_zhonly_sim.py`）。
* 机制：`CaseIndex.case_filter`（`(query, cases) -> 子集`，**只做减法**，失败回退并写
  `cases_filter_reason`）＋ `tools/sidecar_server.py --cases-filter {off,llm}`（**默认 off**，
  上游模型装配，插件侧零新依赖）；用例 `tests/test_case_filter.py`（7 条，含上游 URL 拼接
  ——那里踩过一次 404 静默回退）。
* **实测三次都不如不过滤**：不过滤 3/18 = **0.1667**；离线实验 3/7 = 0.429（看着好）；
  产品路径严提示 **0/1**（6 条查询里 5 条被清空，分母塌掉）；宽提示 **1/11 = 0.0909**。
  根因是**判据本身不稳**（同一提示两次结果差很远，GLM 在 temperature=0 下并不可复现），
  不只是实现。所以默认关闭，机制留作扩展点。
* 结论：E1 的精确率要靠**检索器本身能判语义**（多语言向量；GLM `embedding-3` 目前 429）
  或**语料与查询同层**（"这一镜怎么拍"而非"这部电影讲了什么"），不是事后过滤。

**2026-10-03 02:xx 追加（`extract/v18`）：那本"看着像测量其实是常量"的账做成真的了。**

* 病：`extractor.member_grounding` 是**常量**（8087/8087 全 `inferred`）——提示词只要
  一条边级 `quote`，成员都是三元组。**一个只能取一个值的指标不是测量。**
* 修：把"逐槽位依据"加回提示、但**仍然只当账**（不弃边）。索引不塌：
  **638 条边 / expressible 96.13%**；账变成 **quoted 6.3% / inferred 93.3% /
  fabricated 0.3%**，且分类型有信息量：`MUSIC 17.2% / EMOTION 16.3% / LIGHT 15.0%` …
  `TROPE 3.1% / STAGING_PACK 3.0% / PERFORMANCE_PACK 1.4%` ——**垫底的正是复核拒得最狠的两类**。
* 路上撞到并修掉两个真缺陷：① "缺依据就写空字符串"会**教模型省必填槽位**
  （`missing_required` 30→2321、索引 700→544）**并且**让模型系统性写坏 JSON
  （`batch 238` 在 0.0/0.2/0.4 三个温度下逐字相同地失败）⇒ 改成"只写前 3 项"；
  ② `DeepSeekClient` 的 `max_tokens=4096` 会**截断** v18 的长回复 ⇒ 与 `decode` 声明的
  `ctx=8192` 对齐。另加"解析失败时换一次取样"（传输错误仍按原温度重试）。
* 收益：**Q6b 转 pass**、**Q4 从差 14 条降到差 2 条**（那 2 条仍是 `AXIS_RULE`
  没有可区分查询键那件事，待裁决第 12 条）。链上现在只剩 `not passing: Q4`。
* 终态：索引 638 条边 / oracle 2847 条；门①–⑥、⑧–⑩ pass、⑦ fail；E1=fail；
  pytest 全绿；31/31 探针；证据 `docs/evidence/20261003-021437/`。

**2026-10-03 04:xx 追加（P14-25）：Q5 的运行侧第一次按"真通道"量出来，量到的是 0——判失败。**

* 真实运行（云端 `glm-4.7`，`DONE`／6 镜／792 帧／50 次 LLM 调用／7 次检索）落
  `docs/evidence/20261003_real_glm/`：`export/shots.json` ＋ `audit_log.jsonl`
  分片 ＋ `llm_trace.jsonl` 分片 ＋ `knowledge_trace.json` ＋ `run_manifest.json`
  （四个 sha256 的**单一真源**，`tools/extract_run_evidence.py --check` 复算）。
* **通道本身是判据的一部分**（§4.1b 硬规则 2）：Q5 以前从 `shots.json` **重推**
  查询串再 join，而 `shots.json` 是**收尾快照**——逐镜检索发生在每镜 editor
  调用**之前**，实测这一跑 **6/6 镜**重推串 ≠ 发出串（`镜头/运镜/特效` 都是后补的）。
  现在 join 键只取 `audit_log.jsonl` 的 `retrieval_call.data.query`
  （`tools/knowledge/run_evidence.py`；多跑混在一份日志里时**拒绝作答**），
  重推串降级为 `drift` 诊断。判据一个字没改。
* 量出来的数：夹具侧 70 ≥ 30 **pass**；运行侧相等命中 **0**（连子集也 0）⇒
  按硬规则 1 **fail**（旧写法记 `not_measured`，与硬规则原文冲突，已改正＝收紧）。
  要让它有分母，得让计划的**形状**（检索那一刻的键集）能被夹具 `q` 命中——
  属契约/标注口径，列在待裁决里，**没动**。
* 顺带两个真缺陷：① 分子侧 `VALUE_ALIASES.get(kind, "")` 把**不在别名表**里的
  取值（`dolly_in`…）折成空串丢掉 ⇒ 每一镜都被当成"锁死（`固定`）"，
  期望 `固定` 的条目会被 `dolly_in` **骗成命中**；改 `(值, 值)` 兜底。
  ② 链上 Q5/E1 挂在 `SOFT_IDS`（"没有输入"）⇒ 输入接上之后
  `tools/knowledge/hard_gates.py` 把它们**归位成门**，只剩 §2.3b 明写
  "只记录、不设门"的 E2 留软项。
* 用例：`tests/test_q5_audit_channel.py`（通道/漂移/多跑拒答/相等不放松/
  分母 0 判失败/夹具下界/stale）、`tests/test_extract_run_evidence.py`（分片逐字节、
  tamper/换代判红、入库证据同代）、`tests/test_chain_evidence_is_measured.py`
  （链上活行必须真的带 `--shots/--audit-log/--e1-reviews`）。
* 这一轮之后的账：门①–⑥、⑧–⑩ pass、⑦ fail；**Q4 2878/2880**（差 2 条仍是
  `AXIS_RULE`「运动轴」）；**Q5 fail（分母 0）**；E1 fail 0.1667；E2 0/6（诊断）。

**2026-10-03 05:1x 追加（`f146de4`）：打分缺"对靶度"，补上之后 Q4 第一次全绿。**

那 2 条差的 `AXIS_RULE` 不是"没有查询键"，而是**排序里少一项**：查询 `轴线=运动轴`
下四条边的 coverage/precision 全是 1.0/0.3333，差别只在成员与 occurrences ——
`_edge_precision` **故意把 `forbid` 排除在分母外**，于是"同靶、只是多带一个没被问到的
禁忌"（真实索引里是 `hg:a0561faf2b48`）一分不扣，靠 occurrences 把**精确匹配**的
`hg:bc1080003563` 挤到第 4 名，而 held-out 的 `must` 正是按成员集完全相等解析出来的。
新增 `Hypergraph._edge_off_target`（查询点名的 kind 里带了别的取值就扣分，[0,1] 封顶）
与 `SCORE_WEIGHTS["specificity"] = 0.10`。权重扫参（`work/zz_rank_specificity.py`，
同一份 2847 条 oracle ＋ 300 条标定抽样）：平台 **[0.04, 0.20]**，Q1 0.9726 → **0.9975**、
Q4 0.9993 → **1.0000**、Q6b 1.0 → 1.0、标定 Q1 0.9067 → 0.9133、标定 Q2 0.9933 → 0.9967；
0.30/0.60 起四项一起退化。**判据与门限一个字没动**。证据 `docs/evidence/20261003-052055/`
（`not passing: Q5,E1`），用例 `tests/test_hypergraph_ranking.py`（含"归零该项名次就回去"
的自证与"惩罚有界、不是过滤"的负对照）。

**两件这一轮才立起来的不变量**（都是真缺陷的修法，用例在 `tests/`）：

* **零原子卡的有界补抽**（`build_hypergraph.backfill_empty_cards`）：抽取器**不可复现**
  （同一份语料连建两次 662/667 条边），一次抽样会让门⑥ 的覆盖率在 80%–99% 之间随机漂移。
  现在只对"一条原子边都没拿到"的卡换一次取样（温度 0.2），账写进 `merge.backfill`，
  `--rematch` 无条件续用。**全量重建仍会重抽**，逐字节可复现要等按 chunk 的原子缓存。
* **出处必须逐字可回查**（`PROMPT_VERSION = extract/v14`）：v13 的抽取只写 `source_card`、
  没有任何校验，实测把"空气透视"的卡标成 `景别=LS/35mm/lead_room` 的唯一来源。
  v14 要求逐字给出 `quote`，机器回查并**改判归属**；哪张卡都不含就丢弃。
**真实模型运行**（sidecar→GLM 云端，`docs/evidence/20261002_real/`）：`DONE / 6 镜 /
792 帧 / built=true / 导出 17 文件 / llm_calls 38 / retrieval_calls 7`，超图通道**未降级**，
`knowledge_provenance` **每一镜都有 `experience`（L2）桶**——L2 经验层第一次真的参与成片。

**仍未完成、且都不是"实现缺陷"的四项**（`ACCEPTANCE_STATUS.md` §20.8）：

1. **抽取提示与 schema 漂移（已实测：不是文本修复，别再当成三行字的活）**：规则 4b 仍写着
   "挂到 `EMOTION_PACK` 上"（与规则 4 的 v1.6 措辞自相矛盾）、规则 1／1b 仍写"13 类"、
   规则 6b 的逐类自问清单只列 **13** 类（漏 `DIALOGUE_PACK`／`MUSIC_PACK`／`PROP_PACK`）。
   2026-10-02 把这条当文本修复做了三次，**三次都被 §4.1b 的分母下界判红**：

   | 提示文本 | 原子边 | 有边可标注的卡 | 下界 ≥95% |
   |---|---|---|---|
   | 原文（已入库） | 2846 | **2099 / 2130 = 98.5%** | 过 |
   | 只改计数 ＋ 补 6b 三行 | 2528 | 1786 = 83.9% | **红** |
   | 再把 4b 改成"别现编宿主" | 2160 | 1688 = 79.2% | **红** |
   | 4b 再加"不等于少写边" | 2213 | 1734 = 81.4% | **红** |

   原因：**原文那句"出现避免 X 就必须写成 forbid"本身是跨卡归并的主要来源**
   （`multi_card_edges` 191 → 129），它逼出的边里既有编造的宿主，也有大量真实耦合。
   所以要从根上改，必须**改提示 ＋ 整库重抽 ＋ 重标整份 oracle 同批落地**，并把
   覆盖率一起当验收指标；四版实测账见 `ACCEPTANCE_STATUS.md` §二十三。
   代码注释里已留档（`PROMPT_VERSION` 上方"被实测否决的一次尝试"）。
   **标注通道的现状（2026-10-02 实测，别再照抄旧结论）**：`glm-4.7` **可用**
   （`GLM_API_KEY` 只从环境变量读；端点 `open.bigmodel.cn/api/paas/v4`）；
   `glm-4.7-flash` 返回 HTTP 429 code 1305（容量）、`glm-4.6` 报余额不足、
   `glm-4-flash` 可用；本地 `qwen3-vl:30b` 的 blob 是坏修订（输出纯噪声）。
   **2026-10-02 17:5x 复测（当前状态，与前一句的"可用"不矛盾：**那把钥匙当时设置了，
   现在没有**）**：本机环境变量里 **`GLM_API_KEY` 未设置**、只有 `DEEPSEEK_API_KEY`
   （OpenAI／Anthropic 也没有）⇒ `python tools/holdout_expect_movements.py --limit 1`
   直接 `LLMError: 缺少 GLM_API_KEY`、exit=1。**这是当前唯一的硬阻塞**：它同时卡住
   ① oracle 重标（任何索引变动都必须做）② Q5 的 `expect_movements` 独立标注
   ③ 门⑦／E1 要求的**跨族**复核面板（抽取族是 DeepSeek，面板必须换族）。
   解它只能由用户提供钥匙或授权另一条非 DeepSeek 族通道。
   **⚠️ 2026-10-03 起这条阻塞已解除，别照抄上面那段**：用户提供了 `GLM_API_KEY`
   （`glm-4.7` 实测可用，Q5 的独立标注与真实运行都跑通了）。**但 `embedding-3`
   仍然不可用**——实测 `POST /api/paas/v4/embeddings` 返回
   `429 {"code":"1113","message":"余额不足或无可用资源包，请充值"}`（`embedding-2`
   同样）⇒"多语言向量检索"这条路当前**走不通**，E1 只能从语料/查询同层入手。
   **离线兜底已在位**：`unsupported_prohibition_hosts` 那道精确度门会在归并期拒收
   这类没有依据的禁令边（索引里那条编出来的边已被它删掉，账在 manifest 的
   `merge.unsupported_prohibition_hosts`）。
2. **schema 没有能诚实承载"运镜政策"的边型**（`gen_cine_0247` 的禁半因此进不了索引）；
   加边型要跟着一次重抽才有意义（门④ 要求每类 ≥30 对 ≥10 卡）。
3. **Q5 的基准串口径仍未拍板，但链上已经按 §4.1b 硬规则 2 选了 audit 通道**
   （2026-10-03 实测）：计划期真正发出的 `retrieval_call.query` 与 build 后从
   `shots.json` 重推的串在同一次真实运行里 **6/6 镜都不同**（`镜头` 由取景求解器
   后补、`运镜` 由工具调用后补，而逐镜检索发生在 editor 调用**之前**）。硬规则 2
   只允许读 audit 的逐次事件，所以 `quality.py` 的 join 键改为 emitted、重推串降级
   为 `drift` 诊断（`tools/knowledge/run_evidence.py`）。那一跑发出的 6 条与 70 条
   带 `expect_movements` 的 `q` **相等 0 条**（子集也 0）⇒ 分母 0 ⇒ 按硬规则 1
   **判 fail**；同日把 Q5/E1 从软项**归位成硬门**（见下）。证据
   `docs/evidence/20261003_real_glm/`，逐条见 `ACCEPTANCE_STATUS.md` §三十五。
3a. **Q5 的夹具侧已达标（70 ≥ 30），但那 70 条里只有 18 条能证伪**（2026-10-03
   盘点，数字被用例钉住）：**52** 条的 `q` 自带 `运镜=<值>` 且期望正是它（join 上
   就必中）、**10** 条期望与 `q` 里的运镜**不同**（反向样本）、**8** 条 `q` 不点名
   运镜（真预测）。所以"Q5 变绿"在今天这套夹具上还证明不了"计划采纳了理论"——
   待裁决的其实是**入口形状**（条目自身不该点名被量的字段；或计划要不要在检索前
   就带上焦段与运镜）。**不动 oracle、不动判据、不重标**。逐条见
   `ACCEPTANCE_STATUS.md` §35.6 ＋ `tests/test_q5_run_join.py`。
3b. **E1（经验引用相关性 ≥70%）第一次被量出来就是 0**，而且**两个口径都是 0**：
    路由修好前用契约串打 L3 是 **0/24**，按 §2.3b 改用散文类比查询后仍是 **0/16**
    （跨族双模型面板，`reviewed_by: llm-panel`，提示指纹在
    `docs/evidence/20261002_real/e1_reviews.jsonl`）。根因**不是路由**（那一层已修）：
    §2.3b 把 L3 定义成"**拉片/复盘/影评**"，而现在的案例层是从**同一份 L1/L2 语料**
    切出来的 1900 年代老书散句。要它达标得给 L3 补"对具体影片的逐镜分析"这类来源，
    **不是**调 E1 的门限。逐条见 `ACCEPTANCE_STATUS.md` §二十四。
3c. **L3 现在有陈旧门**：`build_cases` 记 `cards_sha256`（与超图同一个
    `corpus_digest`），`tests/test_cases_corpus.py` 拿它与
    `hypergraph.manifest.json` 对拍——语料一变、哪一层没重建就按名字报错。
    2026-10-02 实测过一次代价：案例层漏跑一天（`anime` 13 篇 vs 重建后 120 篇）而链路全绿。
3d. **`sources.yaml` 新增两个分层旋钮**（2026-10-02，取值写错会报错）：
    `layers: [L3]` ＝ **只喂案例层**（`chunk.py` 跳过并计入 `l3_only_skipped`；影评不是
    镜头层硬约束，也不该抬高门⑥ 的分母）；`case_budget: N` ＝ 这份来源在 L3 的**份额上限**
    （轮转配额会让来源数一涨就摊薄稠密来源——实测 161 篇进来后 `anime` 120→628、
    同语言 E1 对照 1/18→**0/18**，限 1 之后回到 1/18 且现代材料在场）。
3e. **robots 口径 = RFC 9309**：**404/410 ⇒ 没有规则 ⇒ 放行**（并把这件事缓存留痕）；
    **403／5xx／断网 ⇒ 仍拒收**。旧口径"拿不到就拒"把 `journal.animationstudies.org`
    （*Animation Studies*，CC-BY 4.0，文章页 4.9 万字符）整站挡在外面——那正是 §2.3b 给
    L3 定义的"拉片/影评"档。全部 161 篇已按 `layers: [L3]` 入库。
4. **用户手工项**：`%USERPROFILE%\.ollama\models\blobs` 里的旧修订
   （`sha256-0373edb0…`，18.25 GiB）与中断下载残件——**Codex 工具策略拒绝工作区外的
   删除**，只能用户手工执行（§9.6 给了命令）。注意该 blob **仍被 `qwen3-vl:30b` 的 tag
   引用**，删它等于卸载这个模型（用户已据此授权）。

**以下为重建前的历史数字（保留以供对照；上面的 §"P14 现状"已把它作废）**：**P14 未完成（不得当作通过）**（2026-10-01 02:20 复跑的准确数字，证据 `docs/evidence/20261001-0220/`；
**索引与 oracle 仍在重建中，数字会动 —— 复跑上面那两条命令，以最新一次输出为准**）：
`fixtures/knowledge_holdout.jsonl` 已落地 **4539 条**（下界 1200），但**五道门是红的**：

- `python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab fixtures/knowledge_holdout.vocab.json --cards fixtures/knowledge_holdout.cards.json`
  现在报 **gate 1/2/4/5/5b/8 = pass**、**gate 3（词表双向覆盖）= fail**、
  **gate 6（来源覆盖）= fail（1733 张卡里 687 张零条目、29 条引用已消失的卡 id）**、
  **gate 7（人审）= fail（0/120）**、**gate 9（可达性）= fail（970/4539 = 21.4%）**、
  **gate 10（可解析）= fail（8617/13713 = 62.8%，索引 683 条边）**。
  gate 3/6/9 只取决于 oracle 与词表快照，本轮索引重建（579 → 683 条边）动不了它们，
  必须**用当前语料重标一次 oracle 并重建词表快照**；gate 10 已从 68.6% 降到 62.8%。
  gate 3/6 在 `docs/evidence/20261001-011631/` 还是绿的，转红的分界点是
  **语料从 1075 张长到 1733 张** —— oracle 与词表快照都是旧世代，需要
  **用当前语料重标一次**，不是改判据。门⑨/⑩ 是 R54 新加的**机器检查**
  （协议 §3.1 与 §2.3 Q6b 前置① 早就写了规则，只是没人查）。
- `tools/check_holdout.py` 的门⑪ 现在给出**根因分类**（`unresolved_by_cause` /
  `unresolved_by_edge_type` / `unresolved_closeness`，**纯诊断，不改判据**）：
  7307 条 `no_edge_with_those_plain_members`、705 条 `plain_subset_but_forbid_differs`、
  570 条 `plain_subset_index_has_extra_members`、35 条 `value_not_in_index`。
- `tools/holdout_merge.py` 已在**合并**这一步就按门③ 的 unknown 侧与门⑨ 的可达性拦截
  （import `check_holdout.query_shortfall` / `holdout_fill.unknown_values_in`，**不另写第二份判据**），
  三类拒收**分开记账**进报告 —— oracle 只有一个入口，不能等收尾才发现"格式对但语义不可达"。
  实测 `work/glm_v10|v11|v12` 的一批分片 5368 条 → 4722 条合规
  （248 条不可达 + 398 条词表外取值被拦下并报出）。
- `tools/holdout_score.py` 的 Q4 曾是**恒真式**（分子＝分母），R54 已按 §4.1 的定义改成
  `Σ_q|required∩top-k| / Σ_q|required|`，实测 **1356/1846 = 0.735**；不可解析的 `must` 也从
  "静默丢掉"改成"单独记账并判失败"（**3197/5043**，即 §2.3 Q6b 前置① 的"索引构建失败"）。
- **Q1/Q2 不达标的主因是 oracle 与索引不同构，不是排序**：全量实测 `must` 能进候选集的 query
  只有 1277/4539（**Q2 天花板 0.281**）、目标边在候选集里的名次中位数＝**1**。所以
  并行 lane 正在用 `holdout/v12` 提示重标（提示里新增"查询必须覆盖目标边 ≥2 个成员"，
  实测该子集 **Q1=0.727 / Q2=0.917**）。**在没有重标完之前不要动 `SCORE_WEIGHTS`**——
  动它只会掩盖 oracle 缺陷。证据：`docs/evidence/20261001-0057/`。
  （上面那组天花板数字来自 `docs/evidence/20261001-0057/` 的那一版索引。2026-10-01 02:20 重测：
  `python tools/knowledge/holdout_ceiling.py` → **Q1 0.357 / Q2 0.375 / Q4 0.366 / Q6b 0.366**，
  `ceilings_below_lines` 四条全列；实际 Q1=933/4539=0.206、Q2=1350/4539=0.297。
  索引已从 579 条边长到 683 条，上限却仍只有 ~36% —— 这就是"**先修 oracle/索引，
  不是先改检索**"的直接证据，也说明改 `SCORE_WEIGHTS` 永远到不了线。）
- **门⑩ 的判据本身待用户裁决**：§2.3 Q6b 前置① 要求 `norm_key` 完全相等（含**完整成员集**），
  而 §2.3c 又写死"标注方不可见索引"。同一 fixture、同一索引下的四档上限实测
  A=31.4% / B=35.3% / C=40.3% / D=99.7%（四档定义见
  `docs/evidence/20261001-0207/p14_measurement_round.md` §4 与
  `docs/evidence/20261001-0159/gate10_rootcause.md` §5）。
  **在用户拍板前不要改 `SCORE_WEIGHTS`、不要改门限、不要用脚本机械补 `q`。**
  **2026-10-02 补注（盘点的结论，别把这条当成已解决）**：仓库里已经有**一处**
  门限下调发生了——`tools/kb_fetch/build_cases.py:137` 的 `SEQUENCE_FLOOR` 由
  **7 降到 1**（散文枚举分支同时被加回），落地依据只有 `AUDIT_RESIDUAL_20261001.md:21`
  的一条 agent 转述（"我按用户'改门限吧'落地"）。本文件不追认也不推翻它：
  它现在记在 `docs/knowledge/ACCEPTANCE_STATUS.md` 的待裁决清单里，
  **在用户确认出处之前，不要再动任何门限**。
- **人审 ≥120 条**（协议门⑦）与 **Q5/Q7/E3 的最终裁定**必须由人做，agent 不可代替。
  Q5 只在真实模型运行（§4.4 步骤 2）上判：链上喂的是**入库的那一次真实运行**
  （`docs/evidence/20261003_real_glm/` 的 `export/shots.json` ＋ `audit_log.jsonl`），
  所以它**不再**在 CI 上记 `not_measured`——2026-10-03 起 Q5/E1 是硬门（分母 0 → fail），
  只有 §2.3b 明写"只记录、不设门"的 E2 留在软项。
- 重跑长标注仍须知：本机 `qwen3-vl:30b` 是思考模型，走 `/api/chat` 加 `think:false`
  也**恒无正文**（`docs/evidence/20260930-070000/knowledge_annotator_blocker.json`），
  必须走 `/v1/chat/completions` 或加 **assistant 预填**（`tools/kb_fetch/llm.py` 的
  `OLLAMA_ASSISTANT_PREFILL`，默认关闭）；一次 4.7 s，跑满 1200 条要数小时墙钟，且
  `tools/holdout_fill.py` 支持断点续跑与逐批落盘。
- 提示侧修掉一条真缺陷：`EDIT_RHYTHM` 模板曾写成 `avg_shot_len=<<1s|1-3s|3-8s|>8s>`
  （取值表外层尖括号与取值自带的尖括号叠成 `<<1s`），标注员逐字照抄 → 35 条 `must`
  带词表外取值、**从构造上**解析不到索引边。已改并加回归测试
  （`tests/test_knowledge_holdout.py::test_holdout_prompt_spells_inline_enum_values_verbatim`）。
还剩一条口径未收口：**LightRAG 的真实索引**——仓库里没有 `lightrag` 依赖、也没有它建的索引，
所以 `rag.cases_backend=lightrag` 走的是 §2.3b **写明允许**的降级路径
（`cases_degraded=true` ＋ `lightrag_adapter_unavailable`），`lightrag_index_fingerprint` 如实为空。
（`hypergraph.manifest.json` 的 `rejects` 账目已对平，Q0 现在实测 **pass**。）

安全审计（并行角色）另修了两条：`shot_id` 不再能越过导出目录
（`contracts/plan.py::validate_shot_id` + SDL 的 S11），GUI 的"清空场景后构建"
改成显式开关且清空前先拍检查点。

`depth` and `full_concat` are implemented and probed, not stubs: `delivery.export_depth`
raises `CFG_102` unless the backend is EEVEE, `layer8_delivery/depth_pass.py` writes
the 16-bit grey sequence (0.1-50 m, documented in the README), and
`layer8_delivery/concat.py` joins the per-shot clips in Blender's own sequencer.
Evidence: `tools/blender_tests/test_delivery_extras.py` - `t_depth_sequence_is_written`,
`t_depth_frames_are_16bit_grey_with_range`, `t_full_concat_produces_one_video`,
`t_readme_documents_the_depth_range`, `t_depth_without_eevee_warns_instead_of_failing`.
(The old line here said they "produce a warning instead of silently doing nothing",
which described the pre-P13 tree and contradicted the status section above.)

`tools/run_tests.ps1` drives a hard-coded manifest of Blender probes plus four
non-probe steps (spec + golden drift, pytest, the in-Blender contract smoke
test, and one headless end-to-end run). Its evidence hook then runs the four
knowledge-side reports - `holdout_score.py` -> `holdout_quality.json` (Q1-Q7),
`knowledge/quality.py` -> `knowledge_quality.json` (Q0, E1-E3 and the same
Q1-Q7 scorer, imported rather than re-implemented), `check_holdout.py` ->
`holdout_gates.json`, and `knowledge/authorship_report.py` -> `authorship.json`
- and attributes RK-13 from `knowledge/hard_gates.py`, which judges the report
**by id**: a hard id that is missing counts as failed. Since 2026-10-03 `Q5` and
`E1` are hard ids too (the chain feeds the committed real-run evidence plus the
recorded panel scores; a zero denominator or a missing id counts as failed), and
only `E2` stays soft - the spec says E2 records the adoption rate and sets no
gate. One name, one schema: the chain used
to write holdout_score's report under the name AGENTS.md gives to quality.py, so
Q0 and the hard gate E3 were measured by nothing. A probe whose
`BD_TEST_RESULT` payload cannot be parsed now ends the run with `INCOMPLETE:`
and a non-zero exit code, instead of a WARN followed by "All checks passed".
The probe list lives in `$checks` and
the script asserts it **in both directions** (every listed file exists; every
`tools/blender_tests/test_*.py` on disk is listed); `$total` derives from
`$checks.Count` so the `[n/N]` counter follows automatically. The current
checks are: spec + golden drift, pytest, in-Blender
contract smoke test, a headless run of the full chain (plan -> scene), the
Phase 1 scene build, Phase 2 motion baking, the Phase 3 framing solver, the
Phase 3 axis / composition audit, the Phase 4 plan-to-scene build, the Phase 4
scene state / query tools, the Phase 4 rule check / repair loop, the Phase 5
checkpoint and rollback, the Phase 6 delivery export, the Layer 2/9
save/load/migrate/rebuild round trip, the replay round trip, and the Golden
Test against the expected SDL, and the scene-sync / single-shot regeneration
round trip, and the shot list / debug panel checks.
It also covers the viewport overlay and the path-drawing tool, and the depth
sequence plus full concatenation.
Plus the extended tool layer, cast management, the LLM trace contents, the
declarative camera movements (`test_camera_motion.py`, with the smoothness probe
and RK-17 determinism), the crowd / VFX / prop-shape checks
(`test_crowd_vfx.py`, with RK-16), and the v1.4 probes:
`test_operator_end_to_end.py` (RK-9), `test_character_geometry.py`
(RK-4/14/15), `test_scene_contract.py` (RK-3), `test_label_toggles.py` (X11),
`test_label_layout.py` (RK-1/2/5) and `test_composition_gate.py` (RK-10).

The end-to-end commands are:

```
blender --background --factory-startup --python tools/run_headless.py -- --offline --build
blender --background --factory-startup --python tools/run_export.py -- --offline --out <dir>
blender --background --factory-startup --python tools/rebuild_project.py -- --project <dir> [--export]
```

Motion math lives in `block_director/motion/` (no `bpy`, unit-tested). The bpy side
(`layer3_engine/character_system/motion_library.py`) only maps channels onto object
properties and writes keyframes.

Framing math lives in `block_director/cinema/` (same rule: no `bpy`, unit-tested);
`layer3_engine/cinema_engine/framing_solver.py` applies it to a camera.

Script parsing lives in `block_director/layer1_input/` (also no `bpy`). Those
modules must not import `layer5_orchestrator`; LLM-backed steps (coreference) take
an injected callable instead.

Blender-side integration tests live in `tools/blender_tests/` and print a
`BD_TEST_RESULT {json}` marker.

## Agent skills

### Issue tracker

Issues and specs live as local markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles map 1:1 to identically named label strings. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## 工作流程注意事项

1. 每次改动完成后，都必须创建一个对应的 Git commit，以便后续的追踪和回滚。
2. 每次改动后，都必须编写或者更新相关对抗性测试，并在交付给用户前，确保所有测试和验证确保通过。
3. 围绕着设计 blender 白模预演，尽可能并行处理任务，执行任务之前审查当前的进度以及遇到的问题，拥有初步了解后查阅相关文献、原理以及算法。然后提出修改方案，自我审核并精炼方案，以做到查漏补缺。未经允许不可使用降级方案。
4. 不许按需搜索，而是要全量审查，以免有缺漏。
5. 请根据执行规划开始开发，按计划的顺序一步一步连续完成，每完成一个阶段都要添加并运行有效测试，测试失败就先定位并修复，通过后再继续下一个阶段。
6. 持续执行，直到开发完成。
7. 不允许通过删除测试、跳过测试或降低验收标准让测试跳过。全部完成后运行所有测试。
