# 缺陷 B 的真栈验证：sidecar 连续两次 /query 不再跨事件循环崩溃

日期 2026-10-05。**这是"真栈"证据**——回归用例（`tests/test_lightrag_build_index.py`）
用的是注入的假 rag；这一份打的是真的 LightRAG 索引。

## 结论

| # | 结论 | 证据 |
|---|---|---|
| 1 | 连续两次 `/query` 都 **200**，各回 3 条命中 | `queries.jsonl` |
| 2 | `bound to a different event loop` 出现次数 **0** | `_smoke2.err`（`Select-String` 计数） |
| 3 | 语义对得上：`轴线规则怎么用` 的 top-3 全是 `what-is-an-eyeline-match_*`（eye-line ＝ 视线轴） | `queries.jsonl` 第 1 行 |
| 4 | 没有 manifest 的索引被 **fail closed**：`work/lightrag_v4_fixed2` 只有 `lightrag/`、没有 `INDEX_MANIFEST.json` ⇒ `index_error:ValueError`（501/500），**不出数** | 见下"对照" |

## 命令

```
# 起服务（真索引；那份有 manifest 的完整索引）
work\_venv_lr\Scripts\python.exe -m tools.lightrag_service.serve \
    --index-dir work/lightrag_v4 --port 8796 --mode naive

# 连着发两次（就是旧实现必然崩的第二次）
python work/_smoke_query.py http://127.0.0.1:8796
```

输出（逐字，见 `queries.jsonl`）：

```
{"call": 1, "status": 200, "hits": 3, "ids": ["case_what-is-an-eyeline-match_013", "case_what-is-an-eyeline-match_023", "case_what-is-an-eyeline-match_010"]}
{"call": 2, "status": 200, "hits": 3, "ids": ["case_rack-focus-shot-camera-movement-angles_034", "case_different-types-of-camera-movements-in-film_028", "case_rack-focus-shot-camera-movement-angles_019"]}
```

`_smoke2.err` 里 `bound to a different event loop` 计数 = **0**（旧实现在同样的两次调用上
每次必抛，`work/_sidecar4.err` 5771 行）。

## 对照：无 manifest 的索引必须拒

第一次 smoke 打的是 `work/lightrag_v4_fixed2`（`_ab2` 那一跑留下的残件：目录里**只有**
`lightrag/`，没有 `INDEX_MANIFEST.json`）。两次都回
`{"status": "error", "reason": "index_error:ValueError"}` ——
那是 `build_index.LightRAGIndex` 读到空的 `cells.embedding` 后，`embedding_route_of("")`
按"嵌入格形状不对"抛出来的。**这是设计内的 fail closed**：拿不到嵌入器就拒绝出数，
而不是"用本地的先跑着看"。⇒ 修好事件循环之后，坏的索引**照样不会**悄悄给出读数。

## 仍未验证

* `hybrid`/`local`/`global` 三种**非 naive** 模式需要非空图谱；本 smoke 用的是
  `naive`（向量面）。含线索的那份索引（`work/lightrag_v4_clues_local`）2026-10-05 16:2x
  仍在建（177/783），建成后要按 P9 的跑法再验一次。
* 并发查询：`LightRAGIndex.search` 现在用 `_query_guard` 串行化，本 smoke 也是串行发的；
  并发下的行为未验证（设计上串行，见 `build_index.py` 的注释）。
