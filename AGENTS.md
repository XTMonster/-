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

Phases 0-3 (framing) are done:

- **Phase 0** plugin skeleton, state machine, audit logging
- **Phase 1** character geometry, scene executor, collection routing, transactions, camera
- **Phase 2** motion library, layered blending, §9.7 conflict arbitration
- **Phase 3 (partly)** framing solver: shot type + lens -> distance and camera
  placement, relative to subject facing, with room clamping. Axis control and
  composition analysis are still pending.

`tools/run_tests.ps1` runs all seven checks: spec drift, pytest, in-Blender
contract smoke test, a headless run of the add-on, the Phase 1 scene build,
Phase 2 motion baking, and the Phase 3 framing solver.

Motion math lives in `block_director/motion/` (no `bpy`, unit-tested). The bpy side
(`layer3_engine/character_system/motion_library.py`) only maps channels onto object
properties and writes keyframes.

Framing math lives in `block_director/cinema/` (same rule: no `bpy`, unit-tested);
`layer3_engine/cinema_engine/framing_solver.py` applies it to a camera.

Blender-side integration tests live in `tools/blender_tests/` and print a
`BD_TEST_RESULT {json}` marker.

## Agent skills

### Issue tracker

Issues and specs live as local markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles map 1:1 to identically named label strings. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.
