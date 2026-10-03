# 会诊包（实际送进模型的逐字内容）

## system（角色：实现顾问）

```text
你是这个项目的外部顾问，当次扮演的角色是：**实现顾问**。

这是**会诊**，不是对抗性审查：既要给出判断，更要**解释**——每条结论都要讲清
它的第一原理、为什么在这个项目/这份产物里成立、以及可执行的下一步；
读的人应该能照着你的解释自己复现推理，而不是只知道结论。

硬规矩：
* 只依据 bundle 里**真实出现**的文字与数字说话；引用要逐字照抄（中文就照抄中文）。
* 不发明文件路径、行号、函数名、数字。看不到就写进 `not_checked`。
* 一条精确的结论胜过三条含糊的。
* `severity`：`blocker`（结论/实现是错的）、`major`（真缺陷，有绕法）、`minor`（文档/观感）。
* 只输出**一个 JSON 对象**，不要任何额外说明：
  {"summary": "<一段话>",
    "role": "实现顾问",
    "teaching": "<把这件事讲清楚：第一原理 → 在本项目里为什么成立 → 该怎么做>",
    "findings": [{"id": "F1", "severity": "blocker|major|minor",
                   "title": "<短标题>", "claim": "<结论是什么>",
                   "explanation": "<为什么：原理与在本项目里的落点，讲给能读代码的人>",
                   "where": "<bundle 里的原句/数字>",
                   "why_it_matters": "<后果>",
                   "suggested_check": "<用什么实验/命令可以定案>",
                   "step_by_step": ["<可执行的第 1 步>", "<第 2 步>"],
                   "confidence": "high|medium|low"}],
    "not_checked": ["<bundle 没让你判断的东西>"]}

只谈**怎么落地**：给出改哪个文件/函数、改成什么形状、哪些既有测试会红、该怎么测；每一步都要说明**为什么**要这样改，以及不这样改会怎样。
```

## user（所有角色共用；角色 实现顾问 的包逐字如下）

```text
# 项目现状（自动注入；这是**事实**，不是问题的一部分，别把它当结论）
- 仓库：E:\白模预演codex
- HEAD：a4f7048 docs(P14-73): status line points at the 32/32 chain and records the explanatory consultation
- 最近提交（`git log --oneline -5`）：
    a4f7048 docs(P14-73): status line points at the 32/32 chain and records the explanatory consultation
    b9297f8 feat(P14-73): 会诊改成**解释型**（用户裁决）＋ 把"看不见的换位"接进 R001 消息
    42f4d3a docs(P14-72): status line + the chain evidence for the reverted axis experiments
    26e8e36 docs(P14-72): R001"跟着走位重估"两版都不成立——保留积木、写清正确形状（判据未动）
    c908ac3 docs(P14-71): status line ratio wording + the previous chain evidence
- 未提交改动（`git status --porcelain`）：
    M block_director/cinema/__init__.py
     M block_director/cinema/axis.py
     M block_director/layer3_engine/rule_checker.py
     M block_director/layer3_engine/shot_builder.py
     M tests/test_axis_crossing_events.py
     M tests/test_glm_consult.py
     M tools/blender_tests/test_phase3_audit.py
     M tools/glm_consult.py
    ?? docs/evidence/20261004-055158/
    ?? docs/evidence/20261004-glm-consult-code/
    ?? docs/evidence/20261004-r001-v19/
- `AGENTS.md` 状态块（逐字）：
```
**2026-10-04 05:0x 的账（最新，以这行为准）：门①–⑩ 全 pass；Q0–Q4、Q6a/Q6b/Q7、
Q4_pre、E3、E3_
…[现状摘要已按 --status-chars 截断；完整文本的字数与 sha256 记在 bundle.manifest.json]

# 本次要审的问题

① `crossing_events` 仍然用 `flip = rotated >= 90.0`。你上次说该改成"机位相对 A→B 连线的叉积符号在镜内变号"。可这张事件表是**纯计划函数**（签名里没有机位）。要落地，最小改动是什么形状？给出函数签名与一句话理由。（≤120 字）


## 源码：block_director/cinema/axis.py（第 174–243 行，逐字，带行号）

```
  174|                 flip=rotated >= 90.0)
  175|     return out
  176| 
  177| 
  178| def _rotation_deg(a_start: Sequence[float], b_start: Sequence[float],
  179|                   a_end: Sequence[float], b_end: Sequence[float]) -> float:
  180|     """配对连线在这一镜里转过多少度（0–180）。"""
  181|     fx0, fy0 = float(b_start[0]) - float(a_start[0]), float(b_start[1]) - float(a_start[1])
  182|     fx1, fy1 = float(b_end[0]) - float(a_end[0]), float(b_end[1]) - float(a_end[1])
  183|     n0 = math.hypot(fx0, fy0)
  184|     n1 = math.hypot(fx1, fy1)
  185|     if n0 < EPS or n1 < EPS:
  186|         return 0.0
  187|     cosine = max(-1.0, min(1.0,
  188|                            (fx0 / n0) * (fx1 / n1) + (fy0 / n0) * (fy1 / n1)))
  189|     return math.degrees(math.acos(cosine))
  190| 
  191| 
  192| def _after_own_walks(shot, positions: Dict[str, Sequence[float]]
  193|                      ) -> Dict[str, Sequence[float]]:
  194|     """最后一镜没有"下一镜"可用时：把这一镜自己的行走终点算进去。"""
  195|     out = dict(positions)
  196|     for raw in getattr(shot, "actions", None) or []:
  197|         if not isinstance(raw, dict):
  198|             continue
  199|         if str(raw.get("action_type") or "") not in ("walk_to", "run_to"):
  200|             continue
  201|         character_id = str(raw.get("character_id") or "")
  202|         params = dict(raw.get("params") or {})
  203|         target = params.get("target_position") or raw.get("target_position")
  204|         if character_id and isinstance(target, (list, tuple)) and len(target) >= 2:
  205|             out[character_id] = (float(target[0]), float(target[1]))
  206|     return out
  207| 
  208| 
  209| def axis_state(axis: Axis, plan, initial: Dict[str, Sequence[float]]
  210|                ) -> Dict[str, int]:
  211|     """逐镜的**轴侧状态机**（纯函数）：每一镜机位该待在当前连线的哪一侧。
  212| 
  213|     第一原理（GLM 5.3 会诊 A3，2026-10-04）：**合法的状态机只能建立在可观测量上**；
  214|     冻结线是"会失真的隐藏状态"——走位一动就与真实锚点脱钩。所以：
  215| 
  216|     * **线**每镜从两人**当前**坐标派生（`current_line`）；
  217|     * **侧**继承，只在**合法桥接**处翻转——首版只认一种：**看得见的换位**
  218|       （`crossing_events` 里 `visible=True`，即两人同框时走过去）。会诊 A1 还列了
  219|       另外三种（摄影机自身跨轴、主体转向形成新轴、插入无方向镜头）；它们需要
  220|       画面/机位信息，由规则侧用**已经建好的相机**补判（那仍然是可观测量），
  221|       不在这个纯函数里假装知道。
  222| 
  223|     产物 `{shot_id: ±1}` 给构建器与规则**共用**；规则另有一条独立内容
  224|     （"规范首镜线 vs 当前派生线"的偏差），所以两边不会退化成自证。
  225|     """
  226|     sides: Dict[str, int] = {}
  227|     if not axis.left_label or not axis.right_label:
  228|         return sides
  229|     events = crossing_events(axis, plan, initial)
  230|     side = int(axis.established_side) or SIDE_POSITIVE
  231|     for shot in getattr(plan, "shots", []) or []:
  232|         shot_id = str(shot.shot_id)
  233|         sides[shot_id] = side
  234|         event = events.get(shot_id)
  235|         if event is not None and event.visible and event.flip:
  236|             #: 看得见的换位 ⇒ 观众看到并接受这次重建：此后从另一侧继续。
  237|             side = -side
  238|     return sides
  239| 
  240| 
  241| def current_line(axis: Axis, positions: Dict[str, Sequence[float]]) -> Axis:
  242|     """把轴线的**线**更新到两人**此刻**的连线；侧别（`established_side`）继承。
  243| 
```
```
