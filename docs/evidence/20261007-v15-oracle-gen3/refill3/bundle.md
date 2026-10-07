# 会诊包（实际送进模型的逐字内容）

## system（角色：标注）：本次**没有** system 提示词（`--plain` 机械标注包，问题自带输出契约）

## user（所有角色共用；角色 标注 的包逐字如下）

```text
# 本次要审的问题

# 给 3 张卡各写一条**检索期望**（oracle 条目）

背景：知识索引做了一次"换卡"（把某些边槽位的来源卡换成真的写了该取值的卡），
其中 3 张卡原来的那条期望**断言的耦合被判错、已从索引摘掉**，所以它们现在没有条目。
现在请**按卡正文**为它们各写一条新期望。

**只输出一个 JSON 数组**，每个元素形如：

```
{"from_card": "<卡 id>",
 "q": "<查询串：用中文查询键写，形如 动作=后退；强度=mid>",
 "must": ["<边写法：TYPE:槽位=取值,槽位=取值>"],
 "top1": ["<与 must 同一条>"],
 "why": "<不超过 30 字：正文的哪句话支持这条>"}
```

规则（照抄边界，别自由发挥）：

1. `must`/`top1` 的边写法里的**边类型与槽位取值**，必须**逐字**取自上表"这张卡当前
   在索引里支持的耦合"里你选中的那一条（顺序可以变，取值一个字不许改）；
2. 选的那一条必须是**卡正文真的支持**的（例如"明暗对比"的卡该选 `lighting=低调`，
   不是 `lighting=高调`）；正文不支持任何一条时，选最接近的一条并在 `why` 里写清；
3. `q` 里的键只能取这些：情绪/动作/运镜/景别/镜头/节奏/特效/音效/机位/光线/构图/轴线/
   题材/桥段/意图/对白/语气/配乐/道具/转场/强度/镜长 —— 没有查询键的槽位
   （`headroom_policy` / `pair` / `axis_side`）**不要写进 q**；取值逐字相同；
4. 长度 = 3，顺序与下面一致。不要任何额外说明。

---

### 卡片 cine_light_contrast（domain=cinematography）标题：明暗对比与藏信息
正文：让画面的一部分留在暗处，是「不必展示全部」的表达。白模里最有效的做法是保留大面积受光面 + 一块明确的阴影，而不是把整体调暗——整体变暗只会让人看不清形体。
关键词：明暗、对比、阴影、低调
这张卡当前在索引里支持的耦合（选**一条**，且必须是正文真的支持的）：
  - LIGHT_PACK:lighting=低调,intensity=low

### 卡片 gen_anime_0391（domain=anime）标题：快速运动元素用空白赛璐珞叠加
正文：表现闪电、快速烟雾等瞬时元素时，在整幅画上覆盖一张空白赛璐珞，逐段绘制该元素并逐段拍摄，画完一段擦掉再画下一段，从而在同一张片上累积出运动过程。
关键词：逐段拍摄、闪电
这张卡当前在索引里支持的耦合（选**一条**，且必须是正文真的支持的）：
  - IMPACT_PACK:vfx=smoke,sfx=低频轰鸣,movement=follow_subject

### 卡片 gen_axis_0262（domain=axis_theory）标题：近景拳击用轻触
正文：拍拳头击中下巴的近景时，演员只轻拍对手，靠镜头与剪辑制造猛烈冲击感，不真打。
关键词：假打
这张卡当前在索引里支持的耦合（选**一条**，且必须是正文真的支持的）：
  - INTENT_PACK:intent=压迫,shot_size=MCU,movement=dolly_in
  - INTENT_PACK:intent=推进,shot_size=MCU,movement=dolly_in
  - INTENT_PACK:intent=揭示,shot_size=MCU,movement=dolly_in
  - INTENT_PACK:intent=揭示,shot_size=MCU,movement=follow_subject
  - INTENT_PACK:intent=揭示,shot_size=MCU,movement=固定
  - INTENT_PACK:intent=铺垫,shot_size=MCU,movement=固定
  - PROP_PACK:prop=手持道具,shot_size=MCU,camera_angle=平视
  - SHOT_PATTERN:shot_size=MCU,lens=35mm,headroom_policy=cinematic,movement=follow_subject
  - SHOT_PATTERN:shot_size=MCU,lens=35mm,headroom_policy=cinematic,movement=lead_subject
  - SHOT_PATTERN:shot_size=MCU,lens=35mm,headroom_policy=cinematic,movement=固定
  - SHOT_PATTERN:shot_size=MCU,lens=50mm,headroom_policy=cinematic,movement=dolly_in
  - SHOT_PATTERN:shot_size=MCU,lens=85mm,headroom_policy=cinematic,movement=follow_subject
  - SHOT_PATTERN:shot_size=MCU,lens=85mm,headroom_policy=cinematic,movement=固定,shot_size=ECU
  - STAGING_PACK:composition_rule=balance,shot_size=MCU,camera_angle=平视,composition_rule=framing
  - STAGING_PACK:composition_rule=lead_room,shot_size=MCU,camera_angle=平视
  - STAGING_PACK:composition_rule=occlusion,shot_size=MCU,camera_angle=平视
  - STAGING_PACK:composition_rule=occlusion,shot_size=MCU,camera_angle=过肩
```
