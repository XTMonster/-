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

## user（所有角色共用；角色 规格一致性 的包逐字如下）

```text
# 项目现状（自动注入；这是**事实**，不是问题的一部分，别把它当结论）
- 仓库：E:\白模预演codex
- HEAD：f95cd2d fix(hooks): follow the selected session model without fixed execution routing
- 最近提交（`git log --oneline -5`）：
    f95cd2d fix(hoo
…[现状摘要已按 --status-chars 截断；完整文本的字数与 sha256 记在 bundle.manifest.json]

# 本次要审的问题

# 裁定：历史默认值断言与现行 v1.6 的冲突

你是既有规则授权的 GLM-5.3 独立裁定侧；执行由当前会话选择的模型负责。
只裁这一件事，不写实现，不改任何质量阈值，不把判词当测试结果。

事实：

- 用户要求按 v1.6 改进，禁止删除/跳过测试或放宽验收标准。
- v1.6 PRD FR-D D-06 明确核验 top_k=15 / rule_top_k=8，不改 cases_top_k。
- 已有提交 133f4b8 将默认值从5改为8；旧测试仍精确断言默认5，当前全量因此失败2条。
- 生产校验仍只允许整数3至8。明确提供的旧配置5可正常往返；缺键的配置采用新默认8。
- 原始失败输出已保存，不能抹去；不允许把断言变宽为“在范围内”，不允许恢复生产默认5。

请裁定：是否应将仅针对“缺省值”的两条旧断言精确同步为8，并保留全部
3至8合法值、所有 CFG_020 非法输入拒收样例，再新增显式旧值5的兼容测试？
若同意，明确这是同步已指定配置默认值而不是改变质量验收阈值，列出准许变更的边界。
若不同意，给出同时满足v1.6默认8与旧默认5断言、且不伪造/绕过的可执行方案。
写出清晰 yes/no、依据、不得修改的项；记录身份应为 third-party，绝不写 human。


## 源码：block_director/contracts/config.py（第 96–104 行，逐字，带行号）

```
   96|     #: "命中≥2 个查询槽位"的边**恒为 5 条**，20 以上七成以上是擦边。
   97|     top_k: int = 15
   98|     #: v1.5 §7（P2-T5）：规则包（P4-T1 ``rulepack``）每镜注入的规则条数上限。
   99|     #: 校验 3–8——太少约束不足，太多会把候选挤掉。消费者在 P4-T1 落地。
  100|     #: 规则包渲染条数上限（合法区间 **3–8**，`CFG_020`）；取合法上限。
  101|     rule_top_k: int = 8
  102|     #: 2026-10-08 用户裁决："把这个调高到五六万这样子"——三栏注入的**每镜**上限。
  103|     #: 改的是**预算**（上限），不是判据；实际注入多少仍由检索宽度决定
  104|     #: （`top_k` / `rule_top_k` / `cases_top_k`），**上限抬了不等于注入变多**。
```

## 源码：block_director/contracts/config.py（第 440–445 行，逐字，带行号）

```
  440|         rule_top_k = self.rag.rule_top_k
  441|         if (isinstance(rule_top_k, bool)
  442|                 or not isinstance(rule_top_k, int)
  443|                 or not (3 <= rule_top_k <= 8)):
  444|             err("CFG_020", "rag.rule_top_k",
  445|                 f"规则包条数上限必须是 3–8 的整数（当前 {rule_top_k!r}）")
```

## 源码：tests/test_config_vlm_review.py（第 35–54 行，逐字，带行号）

```
   35| # ------------------------------------------------------------------ rule_top_k
   36| def test_rule_top_k_default_is_five_and_legal():
   37|     cfg = AppConfig()
   38|     assert cfg.rag.rule_top_k == 5
   39|     assert cfg.errors() == []
   40| 
   41| 
   42| @pytest.mark.parametrize("value", [3, 4, 5, 6, 7, 8])
   43| def test_rule_top_k_in_range_has_no_error(value):
   44|     cfg = AppConfig()
   45|     cfg.rag.rule_top_k = value
   46|     assert cfg.errors() == [], [str(i) for i in cfg.errors()]
   47| 
   48| 
   49| @pytest.mark.parametrize("value", [2, 9, 0, -1, 3.5, 5.0, "5", True, None])
   50| def test_rule_top_k_out_of_range_or_non_int_is_cfg_020(value):
   51|     cfg = AppConfig()
   52|     cfg.rag.rule_top_k = value
   53|     codes = {i.code for i in cfg.errors()}
   54|     assert "CFG_020" in codes, (value, codes)
```

## 源码：tests/test_config_vlm_review.py（第 102–110 行，逐字，带行号）

```
  102| def test_a_config_without_the_new_keys_falls_back_to_defaults():
  103|     """旧配置文件里没有这两个键 ⇒ 必须回落到缺省，而不是崩（兼容纪律）。"""
  104|     data = AppConfig().to_dict()
  105|     data["rag"].pop("rule_top_k")
  106|     data.pop("vlm_review")
  107|     restored = AppConfig.from_dict(data)
  108|     assert restored.rag.rule_top_k == 5
  109|     assert restored.vlm_review.enabled is False
  110|     assert restored.vlm_review.max_shots == 0
```

## 源码：v1.6/PRD_v1.6.md（第 114–116 行，逐字，带行号）

```
  114| | D-05 | RAG 把"条件模式取反"当无条件禁令发出（E-run ⑤） | 渲染层区分无条件禁令（硬栏）与条件模式（软栏/"若…则…"句式） | 注入审计测试：条件边不进硬栏 |
  115| | D-06 | 三栏注入宽度（E-run ⑥/§8） | **核验** `top_k=15`/`rule_top_k=8` 已随 commit 落盘且测试绿；不再动 `cases_top_k`（E1 证书语境） | `git log` 有记录；相关 8 个测试文件全绿 |
  116| | D-07 | 无人值守时 `request_self_review` 没有承接者（E-run ⑦ + E-video P2-1） | "待人工复核"落产物：`shots.json` 每镜 `needs_review: true` + 交付 README 汇总段 | 产物字段对拍；无人值守跑也能在交付包里看到清单 |
```
```
