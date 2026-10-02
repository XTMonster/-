# `20261003_real` — 一次云端 GLM 真实运行（**历史记录**，Q5 **不读**这一份）

| 项 | 值 |
|---|---|
| `run_id` | `b4626c726435`（`DONE`，6 镜 / 792 帧，30 次 LLM 调用，7 次检索） |
| 用途 | 2026-10-03 的第一跑；它**第一次**量出"从 `shots.json` 重推的查询串"与"真实发出的串"不是同一件东西（见 `../20261003_real_glm/README.md` §4 与 `tests/test_q5_audit_channel.py`） |
| **不是**什么 | **不能**当 Q5 / E2 的运行证据：这一跑的交付清单里**没有 `knowledge` 块**（索引代际指纹是 2026-10-03 加上的），`quality.run_evidence_is_stale` 会如实记 `stale_evidence: true` ＋ `not_measured`。链上喂的是 `../20261003_real_glm/`。 |

`audit_log.jsonl` 是这一跑 207 条事件的**逐字节**分片（`tools/extract_run_evidence.py`），
`run_manifest.json` 钉住它的 sha256、`export/shots.json` 与当次 oracle/index。
`blender.log` 是当时的控制台留痕；`sidecar.log` 的**第一行**是这一跑的启动行，
后面那段 `ConnectionResetError` 属于 4:16 那次**中止的尝试**（同一份日志被追加写，
那次重跑没有产物）。`export/` 下的媒体按 `.gitignore` 不入库（可重建）。

复算：

```
python tools/extract_run_evidence.py --run-id b4626c726435 --out docs/evidence/20261003_real --check
python tools/knowledge/quality.py --cases knowledge/cases.jsonl \
    --shots docs/evidence/20261003_real/export/shots.json \
    --audit-log docs/evidence/20261003_real/audit_log.jsonl --out work/_q5_old.json
# → Q5 记 not_measured ＋ stale_evidence（这份运行没有索引代际，不能当现行证据）
```
