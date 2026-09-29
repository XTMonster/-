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
| **P14** | 知识栈三层：语料 1075 卡 / 九域（`knowledge/cards_generated/`）、超图索引（`knowledge/hypergraph.{nodes,edges}.jsonl`，143 边含 **19 个 `forbid` 成员**、最大 arity 4）、L3 案例层（`knowledge/cases.*`）；`/v1/retrieve` 三通道 `cards[]/edges[]/cases[]` ＋ `trace{}`（`contracts/knowledge.py` 的 `HyperEdge`/`Case` DTO，`specs/openapi.yaml` 同批）；`Capability.HYPERGRAPH` 由**索引是否加载成功**决定；插件侧 `knowledge/client.py` 每次检索写一条 `retrieval_call` 审计事件，`knowledge_trace.json` 每次运行必写；`tools/holdout_score.py` 判 Q1–Q7、`tools/knowledge/quality.py` 判 Q0 ＋ E1–E3 并落 `docs/evidence/<run-id>/knowledge_quality.json`；`tools/ab_triple_baseline.py` 出三元组对照；`tools/knowledge/sample_edges.py` 出 30 条人工抽查样本（`verdict` 留空，不预填） |

**L3 案例层（P14-3）已落地**：`block_director/knowledge/cases.py`（三态 `lightrag`/`hybrid`/`off`、
`CaseIndex`、`render_cases`，**没有 `forbid` 字段**——E3 的机制保证）＋
`tools/kb_fetch/build_cases.py` ＋ `knowledge/cases.{jsonl,manifest.json}`（**733 篇**，
`narrative=654/lesson=72/sequence_pattern=7`，`source_ref` 六字段全非空、许可全在白名单、
摘要过"≤2 句 / ≤120 字"门、重复构建逐字节相同）。
`case_type=sequence_pattern` 的判据**只认显式箭头枚举**（`→`/`->`，每段各自落到一个节拍、
不同节拍 ≥2、`beat_sequence` 严格按文本顺序），`excerpt` 就是那一行套路本身；门
`SEQUENCE_FLOOR = 7` 正好是已提交语料里显式枚举的套路条数（`storyboard_practice.md` 4 ＋
`anime_language.md` 3），**只许升**——此前那条"散文里猜套路"的分支会把
"准备—执行—收势"判成套路且把节拍顺序写反，已删除（宁缺勿猜）。
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

**P14 未完成（不得当作通过）**：`fixtures/knowledge_holdout.jsonl` 仍是 **0 字节**，
本地标注器的长跑**尚未跑满 1200 条**（写作时 `work/holdout.partial.jsonl` 有 402 条
真实 `qwen3-vl:30b` 标注，`work/holdout_run3.log` 停在 `batch 85/180`），因此
**RK-13 = `not_measured`**（`docs/evidence/20260930-071539/rks.json` 里 19 条 RK 中
唯一未度量的那一条）。`python tools/check_holdout.py fixtures/knowledge_holdout.jsonl
--vocab fixtures/knowledge_holdout.vocab.json --cards fixtures/knowledge_holdout.cards.json`
现在报 **gate 1/2/3/4/5/5b/6 = fail、gate 7 = not_measured**（空 oracle 就该判失败，
不许当成"还没判")。`fixtures/knowledge_holdout.cards.json` 已从 `["gen_cine_0001"]`
这条调试残留改正为**运行时卡片 id 全集（1075 个）**——门⑥ 的输入只有 1 个 id 时恒真，
那等于自己把门拆了。
`tools/holdout_score.py` 与 `ab_triple_baseline.py` 会打印 `INCOMPLETE` 并非零退出。
根因是本机标注通道：`qwen3-vl:30b` 是思考模型，官方三条关思考开关全无效
（`docs/evidence/20260930-070000/knowledge_annotator_blocker.json`）；给 `/api/chat`
加 **assistant 预填**可把它从"context 打满仍无正文"变成 4.7 s/次（`tools/kb_fetch/llm.py`
的 `OLLAMA_ASSISTANT_PREFILL`，默认关闭），之后 1200 条的本地生成才成为可能，但需要数小时墙钟。
**人审 ≥120 条**（协议门⑦）与 **Q5/Q7/E3 的最终裁定**必须由人做，agent 不可代替。
还剩一条口径未收口：**LightRAG 的真实索引**——仓库里没有 `lightrag` 依赖、也没有它建的索引，
所以 `rag.cases_backend=lightrag` 走的是 §2.3b **写明允许**的降级路径
（`cases_degraded=true` ＋ `lightrag_adapter_unavailable`），`lightrag_index_fingerprint` 如实为空。
（`hypergraph.manifest.json` 的 `rejects` 账目已对平，Q0 现在实测 **pass**。）

安全审计（并行角色）另修了两条：`shot_id` 不再能越过导出目录
（`contracts/plan.py::validate_shot_id` + SDL 的 S11），GUI 的"清空场景后构建"
改成显式开关且清空前先拍检查点。

`depth` and `full_concat` are declared in the config but produce a warning
instead of silently doing nothing.

`tools/run_tests.ps1` drives a hard-coded manifest of Blender probes plus four
non-probe steps (spec + golden drift, pytest, the in-Blender contract smoke
test, and one headless end-to-end run). The probe list lives in `$checks` and
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
