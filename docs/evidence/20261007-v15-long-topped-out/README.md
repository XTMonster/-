# `20261007-v15-long-topped-out` — 长剧本**第一次**尝试：`run_id 7053f80d4fa5`

这一份是 2026-10-07 长剧本真跑的**第一次**：终态 `DONE`、
64 镜、133 个交付文件都产出了，但 `budget.exhausted` **非空**——

```
{"llm_calls": 317, "prompt_tokens": 1881090, "completion_tokens": 119484,
 "total_tokens": 2000574,
 "limits": {"max_llm_calls": 552, "max_tokens": 2000000, "max_cost_usd": 5.0,
            "max_wall_seconds": 7200.0},
 "exhausted": "token 用量已达上限（2000000）"}
audits 163 / failed_audits 96 / repairs 72 / audit_pass_rate 34/56
```

**为什么单独留档**：`tests/test_extract_run_evidence.py` 有一条判据要求长剧本那一跑
"**没有触顶降级**"（`assert not payload["budget"]["exhausted"]`）。这一跑触顶了，
所以它**不能**被当成那条判据的证据件——把它摆在那里当合格证据就是把红的说成绿的。
判据一个字没改：重跑了一次（`c923e61e0c28`，见 `docs/evidence/20261007-v15-long/`）
——**那一跑同样触顶**（2,004,960 tokens）。两次读数一起说明：
"长剧本会不会吃满 2 M token"在当前代码上**不是抽样运气**（对照 v1.4 时代的
`20261003_real_long`：213 次调用 / 723 k tokens / 未触顶）。

**这一跑本身仍然是有价值的读数**（不进验收，但如实记）：

* `max_tokens = 2_000_000` 是 `block_director/layer5_orchestrator/budget.py`
  里的**代码默认值**（`LedgerLimits.max_tokens`），**不在 `specs/config.default.yaml`**
  ⇒ 它不可配置、也不随镜数缩放。这一次 317 次调用正好把它吃满。
* 对照同一天的第一次长跑（`20261003_real_long`，213 次调用、`audit_pass_rate 56/56`、
  未触顶）：**同一套代码、同一份剧本**，这一跑的返工量大得多
  （`failed_audits 96` vs 11）。差异来自模型采样，不是判据——但它说明
  "长路径会不会吃满 2M token 预算"取决于当次返工量，不是个稳定属性。

复算：

```
python tools/extract_run_evidence.py --out docs/evidence/20261007-v15-long-topped-out --check
```
