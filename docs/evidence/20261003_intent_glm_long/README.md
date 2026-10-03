# `20261003_intent_glm_long` — 用 GLM-5.3 做上游的那一跑：**300 秒上游超时，没跑成**

留着它是为了让下一次不必重踩：这是"换一个输出上限更大的上游"这条路的实测现场。

## 怎么跑的

```
python tools/sidecar_server.py --host 127.0.0.1 --port 8765 \
  --upstream https://open.bigmodel.cn/api/paas/v4 --upstream-kind openai \
  --model glm-5.3 --upstream-api-key-env GLM_API_KEY --think off \
  --temperature 0 --seed 0 --knowledge-dir knowledge --cases-backend hybrid \
  --timeout 300 --max-tokens 32768

blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/script_long_61.md --build --preset fhd16x9 \
  --out docs/evidence/20261003_intent_glm_long ... --wall 10800 --llm-timeout 600
```

## 现场

```
UNDERSTANDING → CALLING_LLM 的第一次调用：
  duration_s 300.093   error "TransportError: [E_LLM_001] sidecar 返回 500"
```

即 **sidecar 到 GLM 的上游调用在 300 s（`--timeout 300`）处超时**；同一时刻直接对
GLM API 发一个小的 tool-call 请求只要 **19.8 s**（`tool_choice=required` ＋
`thinking` 默认），所以不是"额度不够"也不是"GLM 不支持工具调用"，而是**这一路的
延迟预算不够**（理解阶段的 prompt 是整段剧本 ＋ 时序表，GLM-5.3 强制思考）。

## 结论与后续

* **不需要走这条路**：同一份剧本用 DeepSeek（输出上限 8k）在**分块出计划**之后
  已经跑通（`docs/evidence/20261003_chunked_long3/`，64 镜 / `DONE` / `built=true`）。
* 若将来要用 GLM 做上游：把 sidecar 的 `--timeout` 与插件的 `--llm-timeout` 一起放大
  （≥600 s），并接受更长的单次调用；`cases_filter` 在非 ollama 上游下会硬写
  `thinking: {"type":"disabled"}`，而 GLM-5.3 只接受 `low|high|max`——**要用
  GLM 上游就不要开 `--cases-filter llm`**（默认就是 off）。
