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
- HEAD：e6351f4 fix(P14): 证据摘要与检出形态无关（换行归一）＋ repin 重签入库清单
- 最近提交（`git log --oneline -5`）：
    e6351f4 fix(P14): 证据摘要与检出形态无关（换行归一）＋ repin 重签入库清单
    a4f7048 docs(P14-73): status line points at the 32/32 chain and records the explanatory consultation
    b9297f8 feat(P14-73): 会诊改成**解释型**（用户裁决）＋ 把"看不见的换位"接进 R001 消息
    42f4d3a docs(P14-72): statu
…[现状摘要已按 --status-chars 截断；完整文本的字数与 sha256 记在 bundle.manifest.json]

# 本次要审的问题

① `crossing_events` 仍然用 `flip = rotated >= 90.0`（见下方 `axis.py` 第 174 行）。你上次说该改成"机位相对 A→B 连线的叉积符号在镜内变号"。可这张事件表是**纯计划函数**（签名里没有机位），而 `axis_state` 只在 `visible and flip` 时翻侧。要落地，最小改动是什么形状？给出函数签名与一句话理由。（≤100 字）


## 源码：block_director/cinema/axis.py（第 158–175 行，逐字，带行号）

```
  158|         following = before.get(str(shots[index + 1].shot_id)) if index + 1 < len(shots) else None
  159|         end = following or _after_own_walks(shot, start)
  160|         a_start, b_start = start.get(left), start.get(right)
  161|         a_end, b_end = end.get(left), end.get(right)
  162|         if not (a_start and b_start and a_end and b_end):
  163|             continue
  164|         #: 连线在这一镜里转了多少度（配对两点自己就是线，所以只能比**方向**）。
  165|         rotated = _rotation_deg(a_start, b_start, a_end, b_end)
  166|         #: 小于半度的差是数值噪声（走位精确停在目标上时仍会差一点点）。
  167|         if rotated >= 0.5:
  168|             out[shot_id] = CrossingEvent(
  169|                 shot_id=shot_id,
  170|                 visible=len([cid for cid in (shot.characters or [])
  171|                              if str(cid) in (left, right)]) >= 2,
  172|                 people=(left, right),
  173|                 rotated_deg=rotated,
  174|                 flip=rotated >= 90.0)
  175|     return out
```

## 源码：block_director/cinema/axis.py（第 209–238 行，逐字，带行号）

```
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
```
```
