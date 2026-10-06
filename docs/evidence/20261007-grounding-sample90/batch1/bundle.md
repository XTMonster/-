# 会诊包（实际送进模型的逐字内容）

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

## user（所有角色共用；角色 测试与验收 的包逐字如下）

```text
# 本次要审的问题

# 只做一件事：给这 8 条"未被佐证"的边槽位做**三分类**

背景（一句话）：这套知识索引里，**1,593 个可检槽位只有 331 个（20.78%）能在自己的来源卡正文里
找到取值本身**。现在要分清这 1,262 条"未被来源佐证"里，各有多少属于下面三类——

* `hidden`：**蕴含未写出**（卡在讲对的东西，只是没写出这个取值本身的词）——良性；
* `wrong_card`：**挂错卡**（卡的**主题**与这个取值不是一回事，比如拿"三脚架调平"的卡去挂
  `composition_rule:balance`）——腐蚀下游；
* `wrong_value`：**取错值**（卡在讲对的主题，但取值本身抄错/编错）——腐蚀下游。

**判法**：只看下面给的证据（成员取值、来源卡的 `topic` 字段、卡正文节选）。
拿不准就判 `hidden` 但把理由写清（宁可漏报错，不要乱扣帽子）。

**只输出一个 JSON 数组**，长度 = 8，每条形如
`{"i": 1, "class": "hidden"|"wrong_card"|"wrong_value", "why": "<不超过 20 字>"}`。
不要任何额外说明。

---

## 1. `camera_angle:平视`（边 hg:02f85ddd6d24，类型 PERFORMANCE_PACK）
- 来源卡：gen_axis_0321
- 来源卡的 `topic` 字段：（空）
- 卡正文节选：快慢场景的表演速度 该快节奏的场景在棚内按正常速度演；为强调某个强烈戏剧点而放慢的场景，通常要比正常呈现速度再慢一点演。 节奏 戏剧点 节奏

## 2. `camera_angle:平视`（边 hg:03fd3a9f91eb，类型 PERFORMANCE_PACK）
- 来源卡：gen_anime_0417, gen_anime_0420, gen_perf_0415, gen_perf_0459, gen_perf_0479, gen_perf_0527, gen_perf_0536, gen_perf_0548, perf_emotion, gen_prod_0176, gen_prod_0241, gen_axis_0203, gen_perf_0361, gen_perf_0401, gen_perf_0471, gen_prod_0179
- 来源卡的 `topic` 字段：, character_design, performance
- 卡正文节选：动画表演更近舞台 动画表演与实拍电影表演有本质区别，更接近舞台表演：需靠夸张、可读性强的外部动作传达内心，而非依赖镜头前的细微自然主义。 舞台表演 实拍差异 夸张 风格

## 3. `headroom_policy:board`（边 hg:03fd45465d41，类型 SHOT_PATTERN）
- 来源卡：gen_cine_0364
- 来源卡的 `topic` 字段：shot_language
- 卡正文节选：手持与跳切并用 在法国新浪潮式段落中，可将手持镜头与跳切结合使用，以制造断裂、躁动的节奏，这种组合当时被视为非正统。 新浪潮 节奏 剪辑

## 4. `headroom_policy:cinematic`（边 hg:04baa311f000，类型 SHOT_PATTERN）
- 来源卡：gen_anime_0413
- 来源卡的 `topic` 字段：anime
- 卡正文节选：螺旋桨分层连续换位 飞机剪纸模型上，螺旋桨做成独立剪出的小片，按顺序连续安放在机头位置，同时模型在摄影机下横移过天空。 循环 剪纸动画 循环动作

## 5. `camera_angle:平视`（边 hg:05c36cb730e7，类型 PROP_PACK）
- 来源卡：gen_perf_0420, gen_perf_0422, gen_perf_0532, gen_perf_0539, gen_block_0096, gen_block_0097, gen_anime_0265, gen_cine_0294, gen_cine_0392, gen_edit_0241, gen_prod_0220, gen_story_0119, gen_story_0128, gen_anime_0301, gen_block_0073, gen_block_0260, gen_block_0325, gen_perf_0563, gen_axis_0183, gen_perf_0497, gen_perf_0498, gen_cine_0065, gen_perf_0450, gen_perf_0484, gen_perf_0575, gen_prod_0023, gen_prod_0136, gen_axis_0222, gen_block_0035, gen_block_0262, gen_block_0300, gen_block_0353
- 来源卡的 `topic` 字段：, anime, camera_angle, editing, lighting, shot_language, storyboard
- 卡正文节选：道具随身上场 戒指、药瓶、匕首、信件等舞台上没有的道具由演员随身携带上场（side-props），需在排练时与正式演出同样使用，确保演员熟悉携带与交接。 随身道具 排练 道具管理 表演准备

## 6. `headroom_policy:cinematic`（边 hg:069c51b68414，类型 SHOT_PATTERN）
- 来源卡：gen_cine_0081, gen_cine_0088, gen_cine_0261, gen_cine_0262, gen_cine_0399, gen_cine_0400, gen_cine_0355, gen_cine_0390, gen_cine_0392, gen_cine_0438, gen_edit_0029, gen_edit_0182, gen_edit_0284, gen_perf_0434, gen_perf_0476, gen_prod_0140, gen_prod_0245, gen_prod_0210, gen_prod_0212, gen_edit_0179, gen_perf_0413, gen_perf_0556, cine_depth_of_field, cine_lens
- 来源卡的 `topic` 字段：, editing, shot_language
- 卡正文节选：附加镜缩短焦距 若既无长皮腔也无短焦镜头，可在原镜头遮光罩上加装附加翻拍镜（如Ideal Copying Lens），通过缩短组合焦距来获得所需放大倍率与清晰度。 近摄镜 翻拍 翻拍 近摄 光学

## 7. `camera_angle:平视`（边 hg:0957b1746e03，类型 PERFORMANCE_PACK）
- 来源卡：gen_perf_0525
- 来源卡的 `topic` 字段：（空）
- 卡正文节选：迟缓如蜗牛的肢体动作 表现伪善或压抑的角色时，肢体动作应像大蛞蝓或蜗牛：伸出头又缩回壳中，面部以昏睡的静止等待和谋划，掩盖坚硬不屈的意志。 静止 意志 肢体语言 节奏

## 8. `camera_angle:平视`（边 hg:09bd54e4dba1，类型 STAGING_PACK）
- 来源卡：gen_comp_0020, gen_axis_0234, gen_anime_0327, gen_block_0047, gen_anime_0316, gen_block_0322
- 来源卡的 `topic` 字段：, anime, color
- 卡正文节选：前景硬线引眼远景放松 前景用切割感强的硬边线条吸引视线，同时让远景保持柔和松弛，形成前紧后松的对比，使眼睛被前景抓住后能在远处休息。 硬边 虚实对比 视觉引导
```
