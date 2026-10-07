# 会诊包（实际送进模型的逐字内容）

## system（角色：规格一致性）

```text
你是这个项目的外部顾问，当次扮演的角色是：**规格一致性**。

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
    "role": "规格一致性",
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

你先读执行文档/状态文档里的**验收判据**，再读产物。只挑一种毛病：产物里的结论与判据、或判据与实现**对不上**的地方（含'阈值/分母/期望关系被挪到刚好变绿'的嫌疑）。
```

## system（角色：测试与验收）

```text
你是这个项目的外部顾问，当次扮演的角色是：**测试与验收**。

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
    "role": "测试与验收",
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

你只看**证据强度**：这条结论有没有对照、有没有成对复验、换不变量没有；哪些数字是单跑、哪些是可复算。只挑'证据撑不起结论'的地方。
```

## user（所有角色共用；角色 规格一致性 的包逐字如下）

```text
# 项目现状（自动注入；这是**事实**，不是问题的一部分，别把它当结论）
- 仓库：E:\白模预演codex
- HEAD：4892dc9 feat(v1.5): 结案（裁决=现状）＋ 分镜表解析器认下真实剧本的另一种排版
- 最近提交（`git log --oneline -5`）：
    4892dc9 feat(v1.5): 结案（裁决=现状）＋ 分镜表解析器认下真实剧本的另一种排版
    7bae402 docs(v1.5): 用户点名的「再抽一次」也穷尽——dolly_zoom 是词表漏了别名，尖锐哨音 是抽取器发明的
    7a6042c docs(v1.5): (A) 清洗式重抽取 52 张卡的质量对比——小幅变好，但门③ 红，已回滚
    10066a6 docs(evidence): 执行尝试+回滚之后的完整链读数（35/35 步，唯一红 RK-13）
    0d8b123 docs(v1.5): 22 条裁决的**执行尝试**与实测结论——两条路都撞门，回滚到已验证状态
- 未提交改动（`git status --porcelain`）：
    （工作树干净）
- `AGENTS.md` 状态块（逐字）：
```
**2026-10-07 的账（最新，以这行为准）**：执行文档 **v1.5 已落地**（27 张卡完成 25 张，
另补计划漏掉的阶段 8 共 9 张：8 完成 / 1 阻塞）。链读数见
`docs/evidence/20261007-204326/`：**35/35 步全部跑到**（探针 31 支全 OK、
门①–⑩ 全 pass、`holdout_gates.overall == "pass"`、**Q1 0.9975**（线 0.70）、
attestation 诊断 **0.8682**（换代前 0.2078）、`not passing: E1`）。
知识索引当天走了 `rebind/v1 → rebind/v2`（登记
`docs/knowledge/REGEN_LOG_20261007_rotation.md` §7：v1 把 11 张零边卡追进 `sources[]`
⇒ 门⑥ 孤儿 11 ⇒ 收窄候选池修掉）；索引指纹 **`e5213e1b…`**，
门⑥ `edge_backed 2262 / excluded 91 / 孤儿 0`。**22 份已入库运行的 pin 一律如实标异代、
不 repin**；本代重新落了三份真跑：`docs/evidence/20261007-v15-6shot-ds/`、
`docs/evidence/20261007-v15-long/`、`docs/evidence/20261007-v15-6shot-bailian/`
（后者走**阿里云百炼**的 `qwen3.8-max-0902`）。本轮 `python -m pytest` = **2808 passed /
1 skipped / 0 failed**（那 1 条 skip 仍是 `tests/test_build_ledger.py:68` 的条件守卫，
**不是被绕过的判据**）；链上**唯一红是已结案的 `RK-13`**（E1 ≥ 0.70）——判据一个字没动。
**已落地并留证**：① 长剧本 token 上限随场景缩放（`budget.tokens_per_call_allowance=7000`
＋ `max_tokens_ceiling=4000000`，用户"你看着来"；64 镜真跑 2.76 M / 3.864 M 未触顶）；
② 百炼通道根因与修法（思考模式拒收 `tool_choice=required` ⇒ sidecar 新增
`--tool-choice-mode`，见 `docs/evidence/20261007-v15-bailian/`）。
**等你一句话的一件事**：199 个零候选槽位的裁决已出
（`docs/evidence/20261007-v15-zerocand-verdict/`：keep 177 / wrong_card 20 /
wrong_value 2），但**执行它要换 oracle 一代**（22 条逐条试过都会让门⑩ 判红），
所以记录里 `apply: false`（见 `docs/knowledge/ACCEPTANCE_STATUS.md` §五）。
环境：C 盘可用约 **26.8 GB**（README 的 2.7 GB 已过期）。
```
- `docs/knowledge/ACCEPTANCE_STATUS.md` 末尾 2000 字（逐字）：
```
析期判合法、构建期
`floa
…[现状摘要已按 --status-chars 截断；完整文本的字数与 sha256 记在 bundle.manifest.json]

# 本次要审的问题

# 问：超图 RAG 这一跑的注入，算不算"达预期效果"？

背景：正在跑的一跑（`qwen3.8-max-0902@百炼`，剧本=用户真实分镜表前四节点，13 镜）
里，插件侧确实走了超图通道。请只回答下面三问，每问给"结论 + 依据 + 可证伪的下一步"：

1. `block_director/knowledge/retriever.py:844-884` 的三栏装配把**每条边渲染成
   「[必须（除非声明破例）]」**，而边本身含**条件性**的 `SHOT_PATTERN`
   （例：`shot_size=MS lens=50mm movement=zoom_in 禁={shot_size:CU}`）。
   这一跑里 13 镜**全部**拿到这类硬约束，其中 4 镜的"违反"其实是**剧本声明的
   CU/dolly_in**（剧本写死、且 R015 会因此判红）。这是"按 §2.3b 该有的硬约束"，
   还是**检索精度问题**（把条件边按被禁的那一格命中）？该不该在渲染层区分
   "无条件禁令"与"条件模式的取反"？
2. 三栏**共用一个 token 上限**（`rag.max_tokens_per_call=800` / 计划
   `rag.plan_prefetch_tokens=2000`）是有意设计。实测后果：计划阶段只剩
   【硬约束】栏（19 行 / 2627 字符），【经验建议（软）】与【参考案例】**两栏缺席**；
   逐镜草稿里案例栏在场（10–12 行）而软栏 10/13 缺席。这与"§2.3b 三栏注入"
   的预期一致吗？还是说上限口径需要按栏分配（而不是先到先得）？
3. 有没有**不重跑模型**就能量的"知识被采纳"判据（现有 Q5 是运行侧人工/面板打分）？
   例如把每镜的 `禁={...}` 与最终选择的 `shot_type`/`movement` 求交集，
   并区分"剧本声明导致的合法破例"与"真违反"。


## 源码：block_director/knowledge/retriever.py（第 844–884 行，逐字，带行号）

```
  844|     def _hypergraph_block(self, query: str, *, limit: int, top_k: int,
  845|                           cards_top_k: int, scope: str,
  846|                           shot_id: str = "", analogy_query: str = "") -> str:
  847|         """§2.3b 的**三栏注入**：硬约束 → 经验建议（软）→ 参考案例 → 卡片补充。
  848| 
  849|         R44/Q6b 的硬约束：**三栏共用一个上限**（每镜 ``rag.max_tokens_per_call``、
  850|         整场 ``rag.plan_prefetch_tokens``）。以前硬约束用满上限、卡片再用满一次，
  851|         单块可以到 2×上限——那会让"注入 token ≤ 800"的判定看似通过而实为超发。
  852| 
  853|         v1.4 §2.3b 的两条通道在这一层分开：硬/软两栏用 ``query``（约束串），
  854|         第三栏「参考案例」用 ``analogy_query``（散文）。没有类比查询 ⇒ 第三栏不产出。
  855|         """
  856|         budgets = {"limit": int(limit), "remaining": int(limit)}
  857|         hard, soft = self.edge_columns(query, top_k=top_k, token_limit=limit,
  858|                                        scope=scope, shot_id=shot_id,
  859|                                        analogy_query=analogy_query,
  860|                                        budgets=budgets)
  861|         columns: List[str] = []
  862|         if hard:
  863|             columns.append(hard)
  864|         if soft:
  865|             columns.append(soft)
  866|         #: 条数来自 `rag.cases_top_k`（§3.2）；这里**不许**再写死 3。
  867|         cases_text = self.case_block(analogy_query, scope=scope, shot_id=shot_id,
  868|                                      budgets=budgets)
  869|         if cases_text and self._take(budgets, cases_text, columns):
  870|             columns.append(cases_text)
  871|         if budgets["remaining"] > 0:
  872|             remaining = max(0, budgets["remaining"] - (2 if columns else 0))
  873|             cards = self.block(query, top_k=cards_top_k, token_limit=remaining)
  874|             if cards:
  875|                 cards = self._take(budgets, "【卡片正文补充】\n" + cards, columns)
  876|                 if cards:
  877|                     columns.append(cards)
  878|         #: v1.5 §5.3：**包末**的自由度声明（两行：已约束／留白）。
  879|         #: 它必须走 `_take`——三栏共享同一个 token 上限这条纪律不因它而例外。
  880|         if self.last_freedom and budgets["remaining"] > 0:
  881|             taken = self._take(budgets, self.last_freedom, columns)
  882|             if taken:
  883|                 columns.append(taken)
  884|         return "\n\n".join(columns)
```

## 源码：block_director/layer5_orchestrator/scene_contract.py（第 135–170 行，逐字，带行号）

```
  135| def shot_constraint_query(shot, *, per_kind: int = 3,
  136|                           environment: Any = None) -> str:
  137|     """把**一镜的计划字段**变成 §2.3b 的查询串：``键=值；键=值``。
  138| 
  139|     为什么需要它：超图的入口 ``hypergraph.parse_query`` **只认契约串**
  140|     （``景别=MS；运镜=dolly_in``）。在此之前生产侧没有任何地方产出这种串，
  141|     于是 `block_for_shot` 拿到的中文自由文本一个种子都命中不了，超图那一栏
  142|     （含 ``forbid`` 禁忌）在真实运行里**从来没有被注入过**——三栏里只剩两栏。
  143| 
  144|     纪律：
  145| 
  146|     * **只写有值的键**：计划里没有"情绪"这个字段就不写 ``情绪=``，空值会造出
  147|       永不命中的种子，把 `seed_miss` 伪装成"知识库里没有"；
  148|     * **确定性**：同一镜两次调用得到同一个串（取值按出现顺序去重）；
  149|     * **每个 kind 最多 `per_kind` 个取值**：查询串越长越容易被无关种子稀释。
  150| 
  151|     入参可以是 ``ShotPlan`` 也可以是 :class:`ShotContract`（同名属性）。
  152|     """
  153|     pairs: List[tuple] = []
  154|     used: Dict[str, set] = {}
  155| 
  156|     def add(key: str, values) -> None:
  157|         seen = used.setdefault(key, set())
  158|         for value in values:
  159|             text = _canonical(key, str(value or "").strip())
  160|             if not text or text in seen:
  161|                 continue
  162|             seen.add(text)
  163|             pairs.append((key, text))
  164|             if len(seen) >= per_kind:
  165|                 break
  166| 
  167|     add("景别", [getattr(shot, "shot_type", "")])
  168|     #: v1.5 §2.3d T3 的**意图轴**：这一镜"想干什么"的闭集取值。它必须进搜索串，
  169|     #: 否则 `INTENT_PACK`（意图×景别×运镜）只能靠"景别＋运镜"猜意图——实测 64 镜
  170|     #: 那一跑 shot 域 231/320 次命中的都是 INTENT_PACK，而拿回来的"意图知识"
```

## 产物：work/_rag_lanes.txt

```
trace rows: 16

#2 purpose=plan duration=107.936s truncated=True
   【硬约束（禁/许）】: 19 行 / 2627 字符
   【经验建议（软）】: 缺席
   参考案例（仅参考）: 缺席
   例: [必须（除非声明破例）] [AXIS_RULE] pair=any_two axis_side=neutral axis_topic=越轴 禁={movement:固定}

#3 purpose=editor duration=54.907s truncated=True
   【硬约束（禁/许）】: 7 行 / 781 字符
   【经验建议（软）】: 1 行 / 74 字符
   参考案例（仅参考）: 12 行 / 793 字符
   例: [必须（除非声明破例）] [AXIS_RULE] pair=any_two axis_side=neutral axis_topic=越轴 禁={movement:固定}

#4 purpose=editor duration=128.629s truncated=True
   【硬约束（禁/许）】: 6 行 / 858 字符
   【经验建议（软）】: 1 行 / 79 字符
   参考案例（仅参考）: 11 行 / 705 字符
   例: [必须（除非声明破例）] [INTENT_PACK] intent=intent:揭示 shot_size=shot_size:CU movement=dolly_in

#5 purpose=editor duration=151.468s truncated=True
   【硬约束（禁/许）】: 12 行 / 1451 字符
   【经验建议（软）】: 缺席
   参考案例（仅参考）: 10 行 / 627 字符
   例: [必须（除非声明破例）] [SHOT_PATTERN] shot_size=shot_size:MS lens=lens:35mm movement=movement:固定 headroom_policy=cinematic 禁={movement:dolly_in}

#6 purpose=editor duration=116.858s truncated=True
   【硬约束（禁/许）】: 8 行 / 916 字符
   【经验建议（软）】: 缺席
   参考案例（仅参考）: 11 行 / 772 字符
   例: [必须（除非声明破例）] [AXIS_RULE] pair=any_two axis_side=neutral axis_topic=越轴 禁={movement:固定}

#7 purpose=editor duration=98.934s truncated=True
   【硬约束（禁/许）】: 9 行 / 1286 字符
   【经验建议（软）】: 缺席
   参考案例（仅参考）: 10 行 / 682 字符
   例: [必须（除非声明破例）] [INTENT_PACK] intent=intent:推进 shot_size=shot_size:MS movement=dolly_in

#8 purpose=editor duration=175.62s truncated=True
   【硬约束（禁/许）】: 12 行 / 1455 字符
   【经验建议（软）】: 缺席
   参考案例（仅参考）: 10 行 / 735 字符
   例: [必须（除非声明破例）] [SHOT_PATTERN] shot_size=shot_size:MS lens=lens:35mm movement=movement:固定 headroom_policy=cinematic 禁={movement:dolly_in}

#9 purpose=editor duration=123.443s truncated=True
   【硬约束（禁/许）】: 7 行 / 1236 字符
   【经验建议（软）】: 1 行 / 113 字符
   参考案例（仅参考）: 10 行 / 615 字符
   例: [必须（除非声明破例）] [INTENT_PACK] intent=intent:揭示 shot_size=shot_size:CU movement=dolly_in

#10 purpose=editor duration=139.762s truncated=True
   【硬约束（禁/许）】: 6 行 / 874 字符
   【经验建议（软）】: 4 行 / 568 字符
   参考案例（仅参考）: 11 行 / 742 字符
   例: [必须（除非声明破例）] [SHOT_PATTERN] shot_size=shot_size:MCU lens=lens:85mm movement=movement:固定 headroom_policy=cinematic 禁={shot_size:ECU}

#11 purpose=editor duration=115.124s truncated=True
   【硬约束（禁/许）】: 12 行 / 1451 字符
   【经验建议（软）】: 缺席
   参考案例（仅参考）: 10 行 / 636 字符
   例: [必须（除非声明破例）] [SHOT_PATTERN] shot_size=shot_size:MS lens=lens:35mm movement=movement:固定 headroom_policy=cinematic 禁={movement:dolly_in}

#12 purpose=editor duration=97.641s truncated=True
   【硬约束（禁/许）】: 13 行 / 2030 字符
   【经验建议（软）】: 1 行 / 87 字符
   参考案例（仅参考）: 6 行 / 338 字符
   例: [必须（除非声明破例）] [SHOT_PATTERN] shot_size=shot_size:MCU lens=lens:85mm movement=movement:固定 headroom_policy=cinematic 禁={shot_size:ECU}

#13 purpose=editor duration=77.661s truncated=True
   【硬约束（禁/许）】: 12 行 / 1455 字符
   【经验建议（软）】: 缺席
   参考案例（仅参考）: 10 行 / 659 字符
   例: [必须（除非声明破例）] [SHOT_PATTERN] shot_size=shot_size:MS lens=lens:35mm movement=movement:固定 headroom_policy=cinematic 禁={movement:dolly_in}

#14 purpose=editor duration=158.723s truncated=True
   【硬约束（禁/许）】: 16 行 / 2262 字符
   【经验建议（软）】: 缺席
   参考案例（仅参考）: 缺席
   例: [必须（除非声明破例）] [SHOT_PATTERN] shot_size=shot_size:MS lens=lens:35mm movement=movement:push_through headroom_policy=cinematic 禁={movement:orbit_cw}

#15 purpose=editor duration=80.866s truncated=True
   【硬约束（禁/许）】: 12 行 / 1451 字符
   【经验建议（软）】: 缺席
   参考案例（仅参考）: 10 行 / 640 字符
   例: [必须（除非声明破例）] [SHOT_PATTERN] shot_size=shot_size:MS lens=lens:35mm movement=movement:固定 headroom_policy=cinematic 禁={movement:dolly_in}

```

## 产物：work/_rag_adoption.txt

```
shot_001  type=LS   moves=-                禁=['movement:固定'] OK
shot_002  type=CU   moves=dolly_in,handheld 禁=['movement:dolly_in', 'shot_size:CU'] 违反=['movement:dolly_in', 'shot_size:CU']
shot_003  type=MS   moves=-                禁=['movement:dolly_in', 'movement:固定'] OK
shot_004  type=CU   moves=-                禁=['movement:固定', 'shot_size:CU'] 违反=['shot_size:CU']
shot_005  type=CU   moves=dolly_in,handheld 禁=['movement:dolly_in', 'shot_size:CU'] 违反=['movement:dolly_in', 'shot_size:CU']
shot_006  type=MS   moves=-                禁=['movement:dolly_in', 'movement:固定'] OK
shot_007  type=CU   moves=dolly_in         禁=['movement:dolly_in', 'shot_size:CU'] 违反=['movement:dolly_in', 'shot_size:CU']
shot_008  type=MCU  moves=orbit_ccw,follow_subject,handheld 禁=['composition_rule:framing', 'shot_size:ECU'] OK
shot_009  type=MS   moves=-                禁=['movement:dolly_in', 'movement:固定'] OK
shot_010  type=MCU  moves=pan_right,whip_pan_right,dolly_in 禁=['composition_rule:framing', 'shot_size:ECU'] OK
shot_011  type=MS   moves=-                禁=['movement:dolly_in', 'movement:固定'] OK
shot_012  type=MS   moves=follow_subject,push_through 禁=['movement:orbit_cw'] OK
shot_013  type=MS   moves=-                禁=['movement:dolly_in', 'movement:固定'] OK

带禁项的镜：13　未违反 9　违反(记在审计里) 4

```
```
