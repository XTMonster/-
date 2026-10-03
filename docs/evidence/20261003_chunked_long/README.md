# `20261003_chunked_long` — **长剧本分块出计划之后，64 镜真跑第一次跑通**

同一份剧本、同一个上游（DeepSeek，输出上限 8k tokens）：

* 分块**之前**（`docs/evidence/20261003_intent_long/`）：`state=ERROR`、**0 镜**，
  两次重试都在 `emit_plan` 参数 ≈16.5 KB 处被切断；
* 分块**之后**（本目录）：`state=DONE`、**64 镜**、`llm_calls 289`、
  三段计划各一次成功（+1 次段内重问）。

## 怎么跑的（可复现）

```
python tools/sidecar_server.py --host 127.0.0.1 --port 8765 \
  --upstream https://api.deepseek.com --upstream-kind openai --model deepseek-chat \
  --upstream-api-key-env DEEPSEEK_API_KEY --think off --temperature 0 --seed 0 \
  --knowledge-dir knowledge --cases-backend hybrid --timeout 300

blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/script_long_61.md --build --preset fhd16x9 \
  --out docs/evidence/20261003_chunked_long \
  --save docs/evidence/20261003_chunked_long/project \
  --export --export-dir docs/evidence/20261003_chunked_long \
  --wall 7200 --llm-timeout 300 --max-llm-calls 0
```

## 结果

```
run_id d9cc454db43a   DONE / 64 镜 / 4584 帧 / 289 次 LLM 调用
ceiling_effective = max(200, 64×8+40) = 552                     未触顶
plan_chunk_received ×2（第 1/3、第 2/3 段；第 3 段到齐即落成计划）
extract_run_evidence --check：零原因、零警告
```

计划分段的证据是审计里那两条 `plan_chunk_received`（最后一段不记事件——它到齐就
直接落成计划），加上 `llm_trace` 里三次 `purpose=plan` 的调用。

## 这一跑顺带暴露的第二个真缺陷（已修，见下一跑）

**62/64 条逐镜草案被判无效**，理由清一色"这个动作不认识的参数"：
模型写 `stand: {base_z}`、`look_at: {toward}`、`nod: {degrees}` 这类同义词，
而工具 schema 只声明了**全部动作的键的并集**——等于告诉模型"这些键都能用"。
无效草案是**整条丢掉**的（这一镜没有动作、没有取景、没有对白时间轴），
于是 B1（执行层）在真实长剧本上形同虚设：`draft_received 2 / draft_invalid 62`。

修法（`layer5_orchestrator/editor.py::render_action_params`）：把"动作 → 允许的键"
这张表**从 `motion/model.py::ACTION_PARAMS` 生成**并放进逐镜提示词（单一真源，
改表即改提示），用例 `tests/test_editor_action_params_prompt.py` 钉住不许漂。
