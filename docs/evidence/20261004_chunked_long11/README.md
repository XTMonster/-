# long11：修复回路收窄之后的真跑——**逐镜通过 15 → 35**，R003 由 173 降到 13

**结论**：`2526558`（纯时间轴审计收窄工具集 ＋ 提示词点明"本次要修的镜头"）
之后的第一次真跑把 §六十 那条最大红源**清掉了**：终审未过镜头里带 R003 的由
**38 个降到 2 个**，落盘的 `project.bdproj` 这一次**校验干净**（long10 报 1 条 S3）。
主要矛盾只剩 `COMPOSITION`（27 个未过镜头），而它的根因已经在
`docs/evidence/20261004-leadroom-finding/` 量出来：机位瞄的是**起始站位**。

## 运行

```
blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/script_long_61.md --build --preset fhd16x9 \
  --out docs/evidence/20261004_chunked_long11 \
  --save docs/evidence/20261004_chunked_long11/project \
  --export --export-dir docs/evidence/20261004_chunked_long11 \
  --wall 7200 --llm-timeout 300 --max-llm-calls 0
```

`run_id = 939ed27395a3`，`state = DONE`，64 镜 / 4584 帧 / `built=true`，
交付 133 个文件，`llm_calls = 324`、`tool_calls = 200`、起草 64/64。
`BLOCKDIRECTOR_SAVED` → `{"validation": {"ok": true, "errors": []}}`。

## 三跑对照（都按**终审轮**统计，同一份 `fixtures/script_long_61.md`）

| 指标 | long9（轴侧前） | long10（轴侧后） | **long11（修复回路收窄后）** |
|---|---|---|---|
| 终审逐镜通过 | 5 / 64 | 15 / 64 | **35 / 64** |
| 构图分中位 | 52.65 | 71.55 | 71.3 |
| 构图门（≥70） | 20 | 37 | 37 |
| R003 动作重叠 | 233 | 173 | **13** |
| R001 越轴 | 64 | 3 | 6 |
| COMPOSITION 低分 | 181 | 126 | 131 |
| R019 / R012 / R010 | 86 / 35 / 11 | 35 / 25 / 10 | 36 / 28 / 14 |
| R005 / R008 / R009 / R004 | 129 / 131 / 64 / 63 | 2 / 0 / 0 / 0 | 16 / 8 / 8 / 12 |
| 未过镜头的成因分布 | R003 44 ／ COMPOSITION 44 ／ R001 21 | R003 38 ／ COMPOSITION 27 ／ R001 1 | **COMPOSITION 27 ／ R003 2 ／ R001 1** |
| 落盘工程校验 | 28 条（S6×26＋S3×2） | 1 条（S3） | **0 条** |

## 这一趟证明的事

1. **修复回路那条修复有效**：R003 的未过镜头 38 → 2。§六十 的账是"117 次修复
   调用里只读工具 218 次对 `emit_shot_draft` 7 次"，收窄工具集 ＋ 点明目标镜头
   之后，模型能真正改到计划的动作表了。
2. **主要矛盾换人**：现在 27 个未过镜头全是 COMPOSITION，且**不是评分口径问题**——
   同一支探针已经量到 64 镜里 20 镜的单主体与"机位用的锚点"差 > 1 m（最远 7.7 m，
   `docs/evidence/20261004-leadroom-finding/`）。下一刀是**锚点**：按"该镜首帧
   人在哪"摆机位，而不是按剧本起始站位。
3. **单跑方差仍在**（19 / 0 / 5 / 15 / 35）：35 这一趟比前几趟好得多，但按 §57.4
   的规矩，**单跑不构成验收**；可复算的那部分（同一份工程重建、成对复验）才是引擎账。

## 产物

`audit_log.jsonl`（2063 事件）、`llm_trace.jsonl`（324 条）、`knowledge_trace.json`、
`run_manifest.json`、`export/`（`shots.json` / `prompts.md` / `script_compliance.json`
＋ 64 段 mp4 与整片，mp4 按 .gitignore 不入库）、`project/project.bdproj`。
