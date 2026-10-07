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

### 卡片 comp_golden_ratio（domain=composition）标题：黄金分割
正文：黄金分割（≈1.618）与三等分构图都在做同一件事：把主体从正中挪开，让画面产生张力。两者差别很小，实用上的区别是黄金分割更靠近中心一点。不要为了「用黄金分割」而放弃已经成立的构图——两者的视觉收益几乎一样，反复调整只会浪费时间。
关键词：黄金分割、黄金比、构图法
这张卡当前在索引里支持的耦合（选**一条**）：
  - STAGING_PACK:composition_rule=rule_of_thirds,shot_size=MS,camera_angle=平视

### 卡片 comp_horizon（domain=composition）标题：地平线位置
正文：地平线压在下三分之一会强调天空（渺小、被压）；抬到上三分之一会强调地面（踏实、环境感）；正好居中则平静、对称、缺少导向。地平线是构图里最容易被忽略的一个大元素，先决定它在哪，再谈别的。
关键词：地平线、水平线、构图
这张卡当前在索引里支持的耦合（选**一条**）：
  - EMOTION_PACK:emotion=孤独,intensity=mid
  - STAGING_PACK:composition_rule=rule_of_thirds,shot_size=LS,camera_angle=平视

### 卡片 comp_lead_room（domain=composition）标题：视线留白
正文：角色看向某个方向时，画面上要在他视线前方留出空间，否则观众会感到「撞墙」。留白方向必须与视线方向一致，这也是视线匹配的另一半。权重 0.20，仅次于遮挡。
关键词：视线留白、lead room、留白、看向
这张卡当前在索引里支持的耦合（选**一条**）：
  - SHOT_PATTERN:shot_size=LS,lens=24mm,headroom_policy=cinematic,composition_rule=lead_room
  - STAGING_PACK:composition_rule=lead_room,shot_size=ELS,camera_angle=低机位
  - STAGING_PACK:composition_rule=lead_room,shot_size=ELS,camera_angle=平视
  - STAGING_PACK:composition_rule=lead_room,shot_size=ELS,camera_angle=高机位
  - STAGING_PACK:composition_rule=lead_room,shot_size=LS,camera_angle=低机位
  - STAGING_PACK:composition_rule=lead_room,shot_size=LS,camera_angle=平视
  - STAGING_PACK:composition_rule=lead_room,shot_size=LS,camera_angle=高机位
  - STAGING_PACK:composition_rule=lead_room,shot_size=MCU,camera_angle=平视
  - STAGING_PACK:composition_rule=lead_room,shot_size=MS,camera_angle=平视
  - STAGING_PACK:composition_rule=lead_room,shot_size=MS,camera_angle=荷兰角
  - STAGING_PACK:composition_rule=lead_room,shot_size=MS,camera_angle=过肩

### 卡片 comp_lines（domain=composition）标题：引导线与框架构图
正文：用环境中的线条（门框、走廊、桌面边缘）把观众视线引向主体，或用前景框（门、窗）把主体包起来。框架构图能强化纵深，也能自然地遮掉杂乱背景。与遮挡的区别：框架是设计，遮挡是事故。
关键词：引导线、框架构图、纵深、前景
这张卡当前在索引里支持的耦合（选**一条**）：
  - STAGING_PACK:composition_rule=lead_room,shot_size=MS,camera_angle=平视

### 卡片 comp_negative_space（domain=composition）标题：负空间
正文：大面积留白不是为了好看，而是把「缺席」表达出来：空椅子、空床、空荡的走廊。负空间要**有内容**（能读出是谁不在），否则只是没拍满。
关键词：负空间、留白、缺席、空镜
这张卡当前在索引里支持的耦合（选**一条**）：
  - STAGING_PACK:composition_rule=lead_room,shot_size=LS,camera_angle=平视

### 卡片 comp_occlusion（domain=composition）标题：遮挡检测
正文：主体被前景物体挡住是最致命的构图问题，因此权重最高（0.25）。本项目的遮挡检测用相机到角色关键点的射线求交（§17.5）：只要关键点被挡，该项评分归零。修复优先级也是第一位的——先把人拍清楚，再谈构图美感。
关键词：遮挡、occlusion、挡板、射线
这张卡当前在索引里支持的耦合（选**一条**）：
  - STAGING_PACK:composition_rule=occlusion,shot_size=MS,camera_angle=平视

### 卡片 comp_widescreen_grouping（domain=composition）标题：宽画幅里的多人排布
正文：横向空间越大，越容易排成「一字长蛇阵」而失去关系。宽画幅里的多人应该沿**纵深**分层，或者用间距分组（谁和谁站得近，谁被隔开），而不是平均铺开。
关键词：宽画幅、多人、分组、纵深
这张卡当前在索引里支持的耦合（选**一条**）：
  - STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视

### 卡片 gen_anime_0282（domain=anime）标题：动画入门先练走路
正文：动画初学者应把"画走路"作为第一项训练：逐帧画出四肢与躯干各阶段的连续姿态，使按序放映时产生行走的视觉合成。
关键词：走路循环、逐帧、姿态序列
这张卡当前在索引里支持的耦合（选**一条**）：
  - ACTION_BEAT:action=走位,beat_type=coverage,intensity=mid
```
