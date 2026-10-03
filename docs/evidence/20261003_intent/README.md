# `20261003_intent` — **意图轴进检索之后的第一跑**（真实模型 + 超图，未降级）

`ACCEPTANCE_STATUS.md` §五十 / 执行文档 R55→R56 的证据：逐镜检索的契约串从
`景别=…；运镜=…` 变成 `景别=…；意图=…；运镜=…`，并且**这不是"我调了那个函数"**——
是同一份剧本、同一个索引、同一个 sidecar 上**真实发出**的串变了。

## 怎么跑的（可复现）

```
python tools/sidecar_server.py --host 127.0.0.1 --port 8765 \
  --upstream https://api.deepseek.com --upstream-kind openai --model deepseek-chat \
  --upstream-api-key-env DEEPSEEK_API_KEY --think off --temperature 0 --seed 0 \
  --knowledge-dir knowledge --cases-backend hybrid --timeout 300

blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/shotlist_market.md --build \
  --save docs/evidence/20261003_intent/project \
  --export --export-dir docs/evidence/20261003_intent \
  --wall 2400 --llm-timeout 300 --max-llm-calls 120
```

`tools/extract_run_evidence.py --run-id 291d91046ae8 --check`：**零原因、零警告**
（`shots.json.retrieval_calls` 与审计里的 `retrieval_call` 事件数一致）。

## 结果

```
run_id 291d91046ae8   DONE / 6 镜 / 792 帧 / llm_calls 44 / retrieval_calls 7
backend hypergraph（未降级）  lanes 2  crowd 30
```

**逐镜真正发出的契约串**（`audit_log.jsonl` 的 `retrieval_call.data.query`）：

| 镜 | 修复前（`20261003_real_ds` 同形态） | 修复后（本跑） |
|---|---|---|
| `shot_001` | `景别=MCU；运镜=固定` | **`景别=MCU；意图=铺垫；运镜=固定`** |
| `shot_002` | `景别=CU；运镜=dolly_in；对白=dialogue` | **`景别=CU；意图=推进；运镜=dolly_in；对白=dialogue`** |
| `shot_003` | `景别=MCU；运镜=固定；对白=dialogue` | **`景别=MCU；意图=收束；运镜=固定；对白=dialogue`** |
| `shot_004` | `景别=CU；运镜=固定；对白=dialogue` | **`景别=CU；意图=铺垫；运镜=固定；对白=dialogue`** |
| `shot_005` | `景别=MS；运镜=follow_subject` | **`景别=MS；意图=转折；运镜=follow_subject`** |
| `shot_006` | `景别=MCU；运镜=固定；对白=dialogue` | **`景别=MCU；意图=释放；运镜=固定；对白=dialogue`** |

计划侧的字段也落了盘：`export/shots.json` 每镜带 `intent_type`（取值全在 12 值闭集内），
且 `plan_query_of_shot(该记录)` 与 `shot_constraint_query(计划那一镜)` **逐字符相等**
（这是 Q5 的 `derived` 诊断栏不漂的前提，用例钉住）。

## 这一跑到底改善了什么（同一引擎内的 A/B，`work/_intent_ab.py`）

同索引、同 6 条查询，只改"查询里有没有 `意图=`"：

```
before：返回的 INTENT_PACK 17 条，其中**承载这一镜自己意图**的 1 条 → 5.9%
after ：返回的 INTENT_PACK 22 条，其中**承载这一镜自己意图**的 9 条 → 40.9%
```

也就是说，"意图知识"从**几乎全是别人的**（同一个景别＋运镜下，`铺垫` 与 `对抗`
被同等检索回来）变成四成真的对得上；这条轴以前**根本不在查询里**，所以这个数
在结构上不可能高于噪声。剩下的差距来自 `SCORE_WEIGHTS` 的混排（覆盖率/优先级/
频次），本跑**没有**动任何权重——那是另一件事，要动得先有独立的排序 oracle。

## 没证明的事

* **Q5 仍然 fail**：这条轴让 join *可能*发生，但 oracle 里那 176 条
  `意图/景别/运镜` 形状的条目**还没有** `expect_movements`（分母仍为 0）。
  补它要走 `tools/holdout_expect_movements.py`（GLM 换族标注）＋面板复核，
  本轮 GLM 一直在 429（额度到账后做）。
* 6 镜样本只说明"轴通到了发出的串"，样本量不支持对 40.9% 做统计推断。
