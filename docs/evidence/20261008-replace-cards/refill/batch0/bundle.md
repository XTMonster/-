# 会诊包（实际送进模型的逐字内容）

## system（角色：标注）：本次**没有** system 提示词（`--plain` 机械标注包，问题自带输出契约）

## user（所有角色共用；角色 标注 的包逐字如下）

```text
# 本次要审的问题

# 给下面每张卡各写一条**检索期望**（oracle 条目）

背景：知识索引刚做过一次"清洗式重抽取"（把一批卡的原子边重抽了一遍），
有几张卡因此没有条目了。请**按卡正文**为它们各写一条。

**只输出一个 JSON 数组**，每个元素形如：

```
{"from_card": "<卡 id>",
 "q": "<查询串：用中文查询键写，形如 动作=后退；强度=mid>",
 "must": ["<边写法：TYPE:槽位=取值,槽位=取值>"],
 "top1": ["<与 must 同一条>"],
 "why": "<不超过 30 字：正文的哪句话支持这条>"}
```

边界（照抄，别自由发挥）：

1. `must`/`top1` 的**边类型与取值**必须逐字取自下面"这张卡当前在索引里支持的耦合"；
2. 挑的那一条必须是**卡正文真的支持**的；正文都不太支持时挑最接近的，并在 `why` 里写清；
3. `q` 的键只能取：情绪/动作/运镜/景别/镜头/节奏/特效/音效/机位/光线/构图/轴线/题材/
   桥段/意图/对白/语气/配乐/道具/转场/强度/镜长；没有查询键的槽位（`headroom_policy`/
   `pair`/`axis_side`）**不要写进 q**；取值逐字相同；
4. 长度 = 下面卡的张数，顺序一致。不要任何额外说明。

---

### 卡片 cine_light_contrast（domain=cinematography）标题：明暗对比与藏信息
正文：让画面的一部分留在暗处，是「不必展示全部」的表达。白模里最有效的做法是保留大面积受光面 + 一块明确的阴影，而不是把整体调暗——整体变暗只会让人看不清形体。
关键词：明暗、对比、阴影、低调
这张卡当前在索引里支持的耦合（选**一条**）：
  - LIGHT_PACK:lighting=低调,intensity=mid

### 卡片 cine_move_crane_arc_down（domain=cinematography）标题：下降弧
正文：与上升弧镜像。下降弧把观众「放进」场景，适合开场揭示空间。禁忌：下降弧的终点必须落在主体上，否则像摄影机掉下去了。
关键词：下降弧、摇臂、crane arc
这张卡当前在索引里支持的耦合（选**一条**）：
  - INTENT_PACK:intent=揭示,shot_size=ELS,movement=crane_arc_down

### 卡片 cine_move_crane_arc_up（domain=cinematography）标题：上升弧
正文：相机沿弧线上升：一边抬高一边改变水平角度。它比纯升镜更有「告别「的意味——既拉开距离，又回头看了一眼。禁忌：弧线上升时不要再叠变焦，两件事一起做，观众一件都读不出来。
关键词：上升弧、摇臂、crane arc
这张卡当前在索引里支持的耦合（选**一条**）：
  - INTENT_PACK:intent=收束,shot_size=LS,movement=crane_arc_up

### 卡片 cine_move_dolly_zoom（domain=cinematography）标题：推拉变焦（眩晕镜头）
正文：相机前推的同时焦距变短（或反之），主体大小不变而透视剧烈变化。它表达的是一种**心理断裂**：世界在塌陷，人还站在原处。整场戏最多用一次——滥用会让它变成杂技。禁忌：整场戏最多用一次；滥用会把它变成杂技。
关键词：推拉变焦、眩晕、dolly zoom、vertigo
这张卡当前在索引里支持的耦合（选**一条**）：
  - EMOTION_PACK:emotion=混乱,intensity=high,movement=zoom_in

### 卡片 cine_move_whip_pan_right（domain=cinematography）标题：右甩镜
正文：与左甩镜像。甩镜的两次落点必须都值得看，否则观众只记得「晃了一下」。禁忌：甩镜之间不要插静止镜头，节奏一断就没有冲击力。
关键词：甩镜、whip pan、快速摇
这张卡当前在索引里支持的耦合（选**一条**）：
  - AXIS_RULE:pair=any_two,axis_side=neutral,movement=pan_right,axis_topic=视线轴
  - AXIS_RULE:pair=any_two,axis_side=left,movement=whip_pan_left,axis_topic=关系轴
  - AXIS_RULE:pair=any_two,axis_side=right,axis_topic=运动轴
  - EDIT_RHYTHM:pacing=short,avg_shot_len=<1s,pacing=long
  - IMPACT_PACK:vfx=impact_frame,sfx=低频轰鸣,movement=whip_pan_right
  - IMPACT_PACK:vfx=impact_frame,sfx=金属撞击,movement=whip_pan_right
  - INTENT_PACK:intent=揭示,shot_size=MS,movement=pan_right
  - INTENT_PACK:intent=收束,shot_size=MS,movement=pan_right
  - INTENT_PACK:intent=留白,shot_size=MS,movement=pan_right
  - INTENT_PACK:intent=铺垫,shot_size=LS,movement=pan_right
  - SHOT_PATTERN:shot_size=ELS,lens=24mm,headroom_policy=cinematic,movement=pan_right
  - SHOT_PATTERN:shot_size=MS,lens=24mm,headroom_policy=cinematic,movement=pan_right
  - SHOT_PATTERN:shot_size=ELS,lens=35mm,headroom_policy=cinematic,movement=pan_right
  - SHOT_PATTERN:shot_size=LS,lens=35mm,headroom_policy=cinematic,movement=pan_right
  - SHOT_PATTERN:shot_size=MS,lens=35mm,headroom_policy=cinematic,movement=pan_right

### 卡片 cine_move_zoom_in（domain=cinematography）标题：变焦推近
正文：机位不动、焦距变长。与推镜的区别是**透视不变**：背景只被放大、不被重新组织，观众会感到「凝视」甚至「盯住」。禁忌：变焦太快像电子放大，除非刻意要那种业余质感。
关键词：变焦、zoom、拉近
这张卡当前在索引里支持的耦合（选**一条**）：
  - EMOTION_PACK:emotion=孤独,intensity=low,movement=zoom_in
  - EMOTION_PACK:emotion=恐惧,intensity=high,movement=zoom_in
  - EMOTION_PACK:emotion=混乱,intensity=high,movement=zoom_in
  - INTENT_PACK:intent=压迫,shot_size=CU,movement=zoom_in
  - INTENT_PACK:intent=推进,shot_size=MS,movement=zoom_in
  - SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=cinematic,movement=zoom_in,shot_size=CU
  - SHOT_PATTERN:shot_size=MS,lens=85mm,headroom_policy=cinematic,movement=zoom_in

### 卡片 comp_balance（domain=composition）标题：画面重心
正文：画面重心不能偏塌：主体与背景重量要大致均衡。单人主体加死区后可居中，多人镜头则要避免所有人都挤在一边。重心问题常常与留白问题同时出现。
关键词：重心、平衡、balance、偏塌
这张卡当前在索引里支持的耦合（选**一条**）：
  - STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视

### 卡片 comp_framing（domain=composition）标题：景别与主体占比匹配
正文：画面里主体的占比必须与声明的景别一致：说是特写就不能拍到半身，说是全景就必须从头到脚。占比不匹配时，观众读到的情绪强度会与导演意图错位。该项权重 0.10，但它常是景别写错的信号。
关键词：景别匹配、主体占比、framing
这张卡当前在索引里支持的耦合（选**一条**）：
  - STAGING_PACK:composition_rule=framing,shot_size=CU,camera_angle=平视
```
