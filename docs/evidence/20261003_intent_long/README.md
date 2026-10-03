# `20261003_intent_long` — 长剧本**没跑完**的那一跑：`emit_plan` 撞上供应商的输出上限

这一跑不是成功证据，是**缺陷现场**。留着它是因为 `Q5_DECISION_v1.md` 与 `P14-46`
引用了它，而且它解释了"为什么今天拿不到一份 64 镜、带意图轴的真实运行"。

## 怎么跑的

```
blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/script_long_61.md --build --preset fhd16x9 \
  --out docs/evidence/20261003_intent_long \
  --save docs/evidence/20261003_intent_long/project \
  --export --export-dir docs/evidence/20261003_intent_long \
  --wall 7200 --llm-timeout 300 --max-llm-calls 0
```

sidecar 上游仍是 DeepSeek（`--max-tokens` 用默认的 8192）。

## 现场

```
run_id 1a1c850d6711   state ERROR / 8 步 / 0 镜 / llm_calls 3 / 交付 0
审计：
  plan_invalid: 参数不是合法 JSON: Unterminated string starting at: line 1 column 16664
  plan_invalid: 参数不是合法 JSON: Unterminated string starting at: line 1 column 16452
  run_failed:   分镜计划生成失败（已达最大尝试次数）
```

两次重试都在 **≈16.5 KB** 处被切断：64 镜的 `emit_plan` 参数**正好贴着** DeepSeek
的输出上限（8k completion tokens）。这不是模型写错 JSON，是"这次请求的输出预算不够"——
而旧实现把它报成了"JSON 非法"，于是同一个预算白重试两次然后整跑失败。

## 它带来了两个后果（都已处理或已记录）

1. **`P14-46`**：`contracts/transport.py` 现在把"`finish_reason=length` **且**某个工具
   调用的参数 JSON 解析不了"判成**截断**，错误文案直接给出"提高 `llm.max_tokens`
   或改用输出上限更大的模型"，并用例钉住"参数完整时不许误报"。
2. **Q5 的 64 镜实读数仍然只能来自 `20261003_real_long`**（那一跑没有意图轴）。
   要拿到"带意图轴的 64 镜"要么换输出上限更大的上游（GLM-5.3 有 32k），
   要么把长计划**按场拆成多次 `emit_plan`**——后者是设计变更，已写进
   `Q5_DECISION_v1.md` 等你批准。
