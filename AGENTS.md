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
- **Light RAG** (`block_director/knowledge/`, no `bpy`): a 37-card corpus
  across the five spec domains, a built-in Okapi BM25 (same algorithm and
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
  it, and `max_llm_calls_per_scene_formula` (`"shots * 6"`) is applied once the
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

Phases 0-4 and 6 are done; Phase 5 is nearly done (all eleven rules R001-R011,
loop detection, budget limits, checkpoint/rollback, the human gate and Level 2
self-review; only a dedicated debug panel is pending). Layer 1 (script parsing,
dialogue timing and coreference) is done.

`depth` and `full_concat` are declared in the config but produce a warning
instead of silently doing nothing.

`tools/run_tests.ps1` runs all twenty-three checks: spec + golden drift, pytest, in-Blender
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
Plus the extended tool layer, cast management, and the LLM trace contents.

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
