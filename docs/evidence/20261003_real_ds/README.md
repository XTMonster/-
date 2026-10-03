# `20261003_real_ds` — 真实运行 #2（DeepSeek 上游）：**逐镜查询带上声明手法之后的第一跑**

这一跑的用途与 `20261003_real_glm/` 不同：那一跑证明"Q5 的 join 通道是 audit"，
这一跑证明**上游修复真的改变了引擎发出的契约串**，并且顺带给出第一份**契约字段
自洽**的真实运行证据。

## 怎么跑的（可复现）

```
python tools/sidecar_server.py --host 127.0.0.1 --port 8765 \
  --upstream https://api.deepseek.com --upstream-kind openai --model deepseek-chat \
  --upstream-api-key-env DEEPSEEK_API_KEY --think off --temperature 0 --seed 0 \
  --knowledge-dir knowledge --cases-backend hybrid --timeout 300

blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/shotlist_market.md --build \
  --save docs/evidence/20261003_real_ds/project \
  --export --export-dir docs/evidence/20261003_real_ds \
  --wall 2400 --llm-timeout 300 --max-llm-calls 120
```

密钥只从环境变量读（`--upstream-api-key-env` 传的是**变量名**）。
**为什么换上游**：2026-10-03 本轮结束时 GLM 的余额耗尽（`429 code 1113`），
而 DeepSeek 仍可用；这一跑量的是**引擎行为**（发出的契约串），不是哪个模型更会拍片。
协议没有规定这一跑必须用哪个模型——§4.4 步骤 2 只要求"一次真实模型运行"。

## 结果

```
run_id 37d8ad2294df   DONE / 6 镜 / 792 帧 / llm_calls 36 / retrieval_calls 7
backend hypergraph（未降级）  lanes 2  cases 3
shots.json.retrieval_calls = 7  ← 与审计里的 7 条 retrieval_call 一致（**没有**契约警告）
```

**逐镜真正发出的契约串**（`audit_log.jsonl` 的 `retrieval_call.data.query`）：

```
shot_001 景别=MCU；运镜=固定
shot_002 景别=CU；运镜=dolly_in；对白=dialogue
shot_003 景别=MCU；运镜=固定；对白=dialogue
shot_004 景别=CU；运镜=固定；对白=dialogue
shot_005 景别=MS；运镜=follow_subject
shot_006 景别=MCU；运镜=固定；对白=dialogue
```

对照 `20261003_real_glm/` 那一跑（同一份剧本、同一个 `shotlist_market`）：
`shot_001` 当时发出的是 **`景别=MCU`**——剧本写"拍摄手法：固定镜头"，
而超图那一栏一个运镜种子都没有。差别就是本轮修的那一处：
`ShotPlan.declared_camera_move`（声明）＋ `shot_constraint_query` 把它折进查询词表。

## 这一跑**不**证明的事

* **不证明 Q5 达标**：发出的串与 held-out 那 70 条 `expect_movements` 的 `q` 仍
  匹配 0 条（它们的 `q` 带 `镜头=`，而检索时焦段还没定）。这是
  `ACCEPTANCE_STATUS.md` §三十八 记的**结构性**问题，不是这一跑能改的。
* **不代表构图质量**：`audit_pass_rate` 与交付件只是副产品；这一跑的目的是
  "契约串里到底有什么"。
