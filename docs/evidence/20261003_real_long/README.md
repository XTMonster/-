# `20261003_real_long` — **长剧本（61+ 镜）的第一次真实模型运行**

§4.4 步骤 1 与 P13 的验收都围绕"61 镜不降级"，而**真实模型**那条路此前只跑过 6 镜
（`20261003_real_glm` / `20261003_real_ds`）。这一跑把它补上：同一套 sidecar
（DeepSeek 上游）＋ `fixtures/script_long_61.md` ＋ `--preset fhd16x9`，
命令就是 §4.4 步骤 2 的形态（只把上游换成 DeepSeek，原因见下）。

## 怎么跑的（可复现）

```
blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/script_long_61.md --build --preset fhd16x9 \
  --save docs/evidence/20261003_real_long/project \
  --export --export-dir docs/evidence/20261003_real_long \
  --wall 7200 --llm-timeout 300 --max-llm-calls 0
```

sidecar 起法与 `20261003_real_ds/README.md` 同（`--upstream https://api.deepseek.com`，
`--upstream-api-key-env DEEPSEEK_API_KEY`）。**为什么不是 GLM**：本轮 GLM 余额耗尽
（`429 code 1113`）。这一跑量的是**长路径上的引擎行为**，与上游是谁无关。

## 结果（`run_id 926a717a2861`）

```
state DONE / 64 镜 / 4584 帧 / 133 个交付文件
llm_calls 213      ≤ ceiling_effective = max(200, 64×8+40) = 552   ← 未触顶、未降级
retrieval_calls 65 （hypergraph，degraded=false）
audit_pass_rate 56/56（采样 133 帧）        repairs 66 / failed_audits 11
budget.exhausted = null                    运行时长约 18 分钟（含 FHD 渲染 292 s）
```

`tools/extract_run_evidence.py --check` 对它是**零原因、零警告**
（`shots.json.retrieval_calls` 与审计里的 `retrieval_call` 事件数一致）。

**这一跑回答的三件事**

1. **长路径在真实模型上真的能跑完**：64 镜全部产出、终态 `DONE`、预算未触顶
   （此前只有离线路径量过这条）。
2. **构图门在长剧本上不降级**：`audit_pass_rate 56/56`，比 6 镜那几次（3/5、0/5）
   好得多——短剧本那几次的失败集中在个别镜，长剧本反而稳定。
3. **Q5 的运行侧在 64 条真实查询上仍是 0 命中**：夹具那 70 条 `expect_movements` 的
   `q` 带 `镜头=`，而 stage A 的计划 schema（`additionalProperties: false`、**没有
   `camera`**）让焦段在检索前**结构上不存在**（`ACCEPTANCE_STATUS.md` §三十八）。
   样本从 6 条扩到 64 条，结论不变——这是那条"两条规则互斥"的第二个、更大的独立证据。

**没证明的事**：E2（经验采纳率）仍是 `0/64`——那是 `declared` 优先级造成的结构性 0
（§2.3b 只要求记录、不设门）；这一跑也没有覆盖 GUI 手工交互。

> **2026-10-03 17:0x 的 pins 重签（运行数据一字未改）**：oracle 当天在 16:5x
> 重标过一次（给 `INTENT_PACK` 那一族补了 176 条独立标注），`--check` 因此报
> "held-out oracle 已换代"。本目录的运行分片逐字节未动，只按当前 oracle 重跑了
> `tools/extract_run_evidence.py`（重算 pins、重写 `run_manifest.json`）。
> 同一轮的 Q5 实读数（诊断）在这跑上是 **23/31 = 0.7419**，见 `Q5_DECISION_v1.md`。
