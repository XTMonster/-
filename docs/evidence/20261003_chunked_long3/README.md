# `20261003_chunked_long3` — 分块计划 + 动作参数进提示之后：**64 镜真跑跑到底了**

这是"长剧本 + 真实模型"这条路上第一份**从计划到交付全程走完**的证据（此前三次分别
死在：输出截断 → 0 镜、草案全废 → 场景没有动作、构建期 `E_MOTION_001` → 整轮 ERROR）。

## 怎么跑的（可复现）

```
python tools/sidecar_server.py --host 127.0.0.1 --port 8765 \
  --upstream https://api.deepseek.com --upstream-kind openai --model deepseek-chat \
  --upstream-api-key-env DEEPSEEK_API_KEY --think off --temperature 0 --seed 0 \
  --knowledge-dir knowledge --cases-backend hybrid --timeout 300

blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/script_long_61.md --build --preset fhd16x9 \
  --out docs/evidence/20261003_chunked_long3 \
  --save docs/evidence/20261003_chunked_long3/project \
  --export --export-dir docs/evidence/20261003_chunked_long3 \
  --wall 7200 --llm-timeout 300 --max-llm-calls 0
```

## 结果

```
run_id 05bef091c490   DONE / 64 镜 / 4584 帧 / 1920x1080 / llm_calls 324 ≤ 552
built: true   motions 136   keyframes 5586        （分块前那一跑：motions 2 / keyframes 348）
计划分 3 段；逐镜草案 draft_received 65 / draft_invalid 1   （动作参数表进提示之前：2 / 62）
extract_run_evidence --check：零原因、零警告
```

**`motions 2 → 136` 是这一轮最实在的差别**：B1（执行层）产出第一次真的落进场景，
白模里有了表演；此前草案全被判无效，场景只有计划本身（几乎静止）。

## 同一跑暴露的**下一个**真问题（已记账，未擅改判据）

草案生效之后，审计通过率从 `56/56` 掉到 **29/56**（采样 230 帧、构图分中位 59.8、
阈值 70）。**这不是"变差了"，是"终于有东西可审了"**——此前场景几乎静止，
规则与构图自然全过。要修哪一条，先得有归因；把 126 次修复调用里的
`- [规则] (error|warning)` 逐条数出来：

| 规则 | 出现次数 | 说明 |
|---|---|---|
| **R003** | **383** | 同一角色的**动作时间重叠**（"shot_062#2 turn_head 与 #3 body_tilt"） |
| COMPOSITION | 80 | 构图分低于阈值（主体偏三分线交点、朝向没交代…） |
| R008 / R005 | 70 / 70 | 越轴 / 中性机位 |
| R004 / R009 | 58 / 58 | 穿模 / 视线空间 |
| R011 | 36 | 台词装不下 |
| R010 / R012 / R019 / R001 | 20 / 14 / 14 / 2 | 其它 |

也就是说：**主导项是一条纯机械的调度冲突（R003）**，它一条就占了 383 次，
并拖着 126 次修复调用与 101 次 `shot_degraded`。三条可选处置（都需要你点头，
因为都动"谁负责调度"的语义）：

1. **引擎确定性错开**（保留模型给的动作与顺序，只把重叠的区间按顺序排开，并记
   `draft_actions_retimed` 事件）——不改内容、只改排期；
2. 提示词再收紧（已写"不可重叠"，实测模型做不到）——收益有限；
3. 维持现状（模型改不动就记 degraded）。

顺带落地的一条可诊断性修复（`P14-51`）：`shot_audit` 事件现在带
`rule_ids` 与逐条 `findings`（此前只有 `errors: 2` 这样的计数，上面的归因
只能从修复提示里反推）。
