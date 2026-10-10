# 20261010-v17-B4 — 知识统计端点验收

| 项 | 值 |
|---|---|
| 卡 | v1.7 B4（TDD §7） |
| 执行者 | 主线（代执行） |
| commit | `c6ac094` |
| 改动 | `tools/sidecar_server.py`（`GET /v1/ui/knowledge/stats`）、`tests/test_sidecar_knowledge_stats.py` |

```text
python -m pytest tests/test_sidecar_knowledge_stats.py -q   → exit 0（3 tests）
```

结论：通过。计数口径钉死（cards=`cards_generated/*.jsonl` 行数和、edges=
`hypergraph.edges.jsonl` 行数、cases=`cases/part-*.jsonl` 行数和，`cards_note`
说明 132 张自撰卡不在文件计数内）；逐行数不读内容；缺目录全 0；clue 源不计入。
