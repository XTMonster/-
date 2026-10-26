# BlockDirector

Blender add-on that turns a script into a white-model (blockout) previs and
exports it as a reference video for AI video generation.

## What it does

1. Parse a screenplay/shot list and drive an LLM to produce a plan.
2. Build the plan as a 3D blockout scene: environments, characters, per-shot
   cameras, keyframes and cut markers (no LLM call needed for rebuilds).
3. Audit the result (framing, axis, composition, occlusion) and deliver
   per-shot mp4 renders, first-frame stills, `shots.json` and `prompts.md`.

## Repository layout

| Path | Contents |
|---|---|
| `block_director/` | Add-on source. `contracts/` and `utils/` are pure Python (no `bpy`); `layer1..9` cover UI, SDL, engine, orchestrator, persistence |
| `contracts/` / `specs/` | Sidecar wire protocol; `specs/openapi.yaml` and `specs/config.default.yaml` are generated — edit `block_director/contracts/` and run `python tools/gen_specs.py` |
| `tests/` | pytest suite (`python -m pytest`) |
| `tools/` | Environment probes, golden-test generator, architecture audit, `tools/run_tests.ps1` full runner |
| `fixtures/` | Golden test plan and acceptance shot lists |
| `docs/` | Execution specs (see below), acceptance evidence |
| `knowledge/` | Light-RAG card corpus and hypergraph index (9 domains / 2,353 cards) |

## Authoritative spec

`BlockDirector_执行文档_v1.2.md` is the authoritative execution spec. Read it
before changing architecture. `BlockDirector_执行文档_v1.0.md` is history only.

## Development rules

- `block_director/contracts/` and `block_director/utils/` must never import `bpy`.
- Anything touching `bpy` must go through `block_director/utils/threading_guard.py`.
- After changing config defaults, run `python tools/gen_specs.py`.

## Tests

```bash
python -m pytest          # unit tests
tools/run_tests.ps1       # full runner incl. headless Blender probes
```
