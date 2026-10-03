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
    ?? docs/evidence/20261004-glm-consult-v19a/
    ?? docs/evidence/20261004-r001-v19/
- `AGENTS.md` 状态块（逐字）：
```
**2026-10-04 05:0x 的账（最新，以这
…[现状摘要已按 --status-chars 截断；完整文本的字数与 sha256 记在 bundle.manifest.json]

# 本次要审的问题

② `_axis_rebuild` 现在这样判越轴：`规范首镜线 vs 当前派生线` 夹角 ≥30°、且 `bridged` 为假就报 error；`bridged` = 本镜机位中性 或 任一镜 `visible` 且 `rotated_deg ≥ 5°`。这算不算"规则与被检实现同源"的自证？给一个**具体反例**：什么坐标/走位会让它误判或放过？（≤150 字）


## 源码：block_director/layer3_engine/rule_checker.py（第 231–265 行，逐字，带行号）

```
  231| def _axis_rebuild(context, camera) -> Dict[str, Any]:
  232|     """轴线被走位重建了多少度、以及这次重建**有没有被拍出来**（会诊 A2/A3）。
  233| 
  234|     * `angle`：**规范首镜线** 与 **当前派生线** 的夹角（两条线都由几何给出，
  235|       与被检的"构建器挑了哪条法线"无关）；
  236|     * `bridged`：这次重建有没有合法交代——① 到此为止有**看得见的换位**
  237|       （`crossing_events.visible`），或 ② **本镜机位中性**（落在线上，§6.2 的桥梁）。
  238| 
  239|     会诊 A1 还列了另外两种重建（摄影机自身跨轴、主体转向形成新轴），它们需要
  240|     逐镜机位/朝向的历史，本条先按上面两种判；更细的桥接集合留给下一阶段。
  241|     """
  242|     base = getattr(context, "axis", None)
  243|     if base is None:
  244|         return {"angle": 0.0, "bridged": True, "note": ""}
  245|     live = current_line(base, _character_xy_by_label(context))
  246|     if live.length < 1e-6 or base.length < 1e-6:
  247|         return {"angle": 0.0, "bridged": True, "note": ""}
  248|     dx0, dy0 = base.direction
  249|     dx1, dy1 = live.direction
  250|     if (dx0, dy0) == (0.0, 0.0) or (dx1, dy1) == (0.0, 0.0):
  251|         return {"angle": 0.0, "bridged": True, "note": ""}
  252|     cosine = max(-1.0, min(1.0, dx0 * dx1 + dy0 * dy1))
  253|     angle = math.degrees(math.acos(cosine))
  254|     bridged = _camera_is_neutral(live, camera)
  255|     if not bridged:
  256|         for event in _crossing_map(context).values():
  257|             #: 观众**看得见**这次重建（两人同框、连线确实转了）⇒ 合法。
  258|             if event.visible and event.rotated_deg >= 5.0:
  259|                 bridged = True
  260|                 break
  261|     note = (f"轴线已被走位重建：规范首镜线 {base.start}→{base.end} 与当前派生线 "
  262|             f"{live.start}→{live.end} 相差 {angle:.0f}°"
  263|             f"（≥{AXIS_DRIFT_DEG:.0f}°）")
  264|     return {"angle": angle, "bridged": bridged, "note": note}
  265| 
```
```
