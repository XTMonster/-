# 独立验收：三栏注入在真 HTTP 上是活的（P14-3 落地后复验）

执行者：`/root`。日期：2026-09-30 07:0x。目的：`7889716` 声称"三栏注入（硬约束／
软先验／参考案例）终于有第三栏了"，这里不看代码自述，直接问服务。

```powershell
python tools/sidecar_server.py --port 8797 --knowledge-dir knowledge
# -> capabilities: ["llm", "bm25", "hypergraph"]
```

```python
# POST /v1/retrieve  {"query": "情绪=荒诞；景别=MS", "top_k": 3}
cards 3   edges 3   cases 3
backend hypergraph | cases_backend hybrid | degraded True lightrag_adapter_unavailable
lanes 2
trace keys: backend, cases_backend, cases_degraded, cases_degraded_reason,
            cases_index_fingerprint, cases_requested_backend, dropped_edge_ids,
            expanded_edges, expansion_truncated, lanes, lightrag_index_fingerprint,
            provenance, quality_fail, query, scores, seed_miss, seeds, selected
first case keys: beat_sequence, case_id, case_type, excerpt, score, source_ref, title
```

结论：

* **三条通道都真的回了东西**（此前 `cases[]` 恒空：插件侧根本没有 L3 通道的消费方）。
* `cases_backend=hybrid` ＋ `cases_degraded=true` ＋ 具名原因 `lightrag_adapter_unavailable`
  ——这是 §2.3b **预先授权**的降级路径（本机没装 LightRAG 依赖，也没有它建的索引），
  不是静默空返回；`off` 才是"用户显式关闭且不报错"。
* 案例对象**结构上没有 `forbid`**（E3「经验越权率 = 0」是类型级保证，不是约定）。
* trace 里补上了 §2.3b 要求、此前没人写的 `cases_index_fingerprint` 与
  `lightrag_index_fingerprint`。

## 语料实测（重新统计，不读 manifest 自述）

```python
# knowledge/cases.jsonl
cases 726
case_type Counter({'narrative': 653, 'lesson': 71, 'sequence_pattern': 2})
license    Counter({'PublicDomain': 680, 'OwnWork': 46})
with beat_sequence 2      # 两条 sequence_pattern 都带
has forbid field? False
```

`≥300` 篇达标（规格要求），许可全在允许集合内，逐篇带 `source_ref`。
`sequence_pattern` 只有 2 篇是**语料形态决定的**（叙事型摘录占绝大多数），不是筛漏；
门限是"`sequence_pattern` 若存在必须带 `beat_sequence`"，两条都带。

## 同批修掉的一个真实预算 bug（值得单记）

`7889716` 顺带修了注入侧的**双份预算**：此前超边栏用满 `plan_prefetch_tokens` 之后，
卡片栏又用满一次，实际注入可达文档上限的 **2 倍**——而 Q6b 是"读真实 prompt"量出来的，
这种超预算会直接把 Q6b 判红归因到错误的地方。现在三栏共用同一份预算。
