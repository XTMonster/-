# `20261007-v15-6shot-ds` — `rebind/v2` 换代后的 6 镜真实运行（本代"干净证据件"）

这一跑是知识索引换代（`rebind/v1` → `rebind/v2`，见
`docs/knowledge/REGEN_LOG_20261007_rotation.md` §7）之后的第一份**同代**真实运行证据。
它的用途是把 `tests/test_extract_run_evidence.py` 与
`tests/test_q5_audit_channel.py` 的"当前代证据"从上一代的
`20261003_real_ds` / `20261006-long21` 换到本代——判据与断言强度一个字没动
（换代之后旧跑的 `pins.index` 必然失配，而 `repin()` 会拒；见 REGEN_LOG §5）。

## 1. 这一跑是什么

| 项 | 值 |
|---|---|
| `run_id` | `330e6c8298bd` |
| 终态 | `DONE`（`success: true`） |
| 剧本 / 预设 | `fixtures/shotlist_market.md` / `hd16x9` |
| 镜数 / 总帧 | 6 / 792（33.0 s @24fps） |
| 步骤 / LLM 调用 / 工具调用 | 107 / **57** / 83（调用硬顶 `shots*8+40 = 88`） |
| 检索调用（`retrieval_call`） | **7**（1 次 plan scope ＋ 6 次逐镜） |
| 知识后端 | `hypergraph`（2353 张卡、`lanes=2`、案例 3、`degraded=false`） |
| 索引代际 | `hypergraph_fingerprint = e5213e1b64781c24103eecae15a4921b5766f75c4709672fa48997de692cdf89` |
| 案例层代际 | `cases_index_fingerprint = 48df4a53c2c95637dd4150499320b1a87fab201645ec4bacec605eb3a8f44a86` |
| 墙钟 | 109.1 s（渲染另计） |

## 2. 怎么跑的（可复现）

```
python tools/sidecar_server.py --host 127.0.0.1 --port 8772 \
  --upstream https://api.deepseek.com --upstream-kind openai --model deepseek-chat \
  --upstream-api-key-env DEEPSEEK_API_KEY --knowledge-dir knowledge \
  --cases-backend hybrid --temperature 0 --seed 0 --timeout 600

blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/shotlist_market.md --build \
  --out docs/evidence/20261007-v15-6shot-ds \
  --save docs/evidence/20261007-v15-6shot-ds/project \
  --export --export-dir docs/evidence/20261007-v15-6shot-ds/export \
  --wall 3000 --llm-timeout 300 --max-llm-calls 200
```

密钥只从环境变量读（`--upstream-api-key-env` 传的是**变量名**）。
**上游为什么是 DeepSeek**：这一跑量的是**引擎行为**，不是哪个模型更会拍片
（与 `20261003_real_ds` 同一条理由）。新通道（中继 `qwen3.8-max-0902` ＋
`reasoning_effort=max`）在**计划调用**上实测不稳定，见
`docs/evidence/20261007-v15-relay-502/`——那一份记的是它两次失败的全过程，
不当作合格证据用。

## 3. 复算

```
python tools/extract_run_evidence.py --out docs/evidence/20261007-v15-6shot-ds --check
  -> {"ok": true, "reasons": [], "warnings": []}

python tools/knowledge/quality.py --cases knowledge \
  --shots docs/evidence/20261007-v15-6shot-ds/export/export/shots.json \
  --audit-log docs/evidence/20261007-v15-6shot-ds/audit_log.jsonl --out work/_q5.json
```

Q5 的运行侧（`run_denominator=1`、`run_numerator=1`、`stale_evidence` 为空 ⇒ 本代）与
逐镜重推/发出的漂移（**6/6 镜**不同，含 `shot_001`/`shot_003`）见上一条命令的输出；
`tests/test_q5_audit_channel.py::test_the_committed_real_run_drift_is_reproducible`
读的就是这一份。

## 4. 这一跑**不**证明的事

* 不证明 Q5 达标：运行侧分母只有 **1** 条（6 镜里能逐字 join 上的就这一条），
  分母这么小的比值不具统计效力——判据没变，读数也不该被当成结论。
* 不代表构图质量：`audit_pass_rate = 0/5`，与 `20261003_real_ds` 同档。
