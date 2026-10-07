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

### 卡片 gen_anime_0391（domain=anime）标题：快速运动元素用空白赛璐珞叠加
正文：表现闪电、快速烟雾等瞬时元素时，在整幅画上覆盖一张空白赛璐珞，逐段绘制该元素并逐段拍摄，画完一段擦掉再画下一段，从而在同一张片上累积出运动过程。
关键词：逐段拍摄、闪电
这张卡当前在索引里支持的耦合（选**一条**）：
  - IMPACT_PACK:vfx=smoke,sfx=低频轰鸣,movement=follow_subject
  - IMPACT_PACK:vfx=spark,sfx=金属撞击,movement=固定
  - IMPACT_PACK:vfx=smoke,sfx=雨声,movement=固定

### 卡片 gen_axis_0119（domain=axis_theory）标题：画面感是导演核心能力
正文：导演的核心能力是画面感/视觉化能力，即把文字剧本转化为具体可拍画面的能力；缺乏此能力者即使在本行是艺术家也常在导演领域失败。
关键词：视觉化、导演能力
这张卡当前在索引里支持的耦合（选**一条**）：
  - INTENT_PACK:intent=揭示,shot_size=MS,movement=固定
  - STAGING_PACK:composition_rule=framing,shot_size=MS,camera_angle=平视

### 卡片 gen_axis_0228（domain=axis_theory）标题：监制统一调度多组
正文：当制片方设多个摄制组时，由总制片导演对各组导演行使实际监督权，组导演须执行其指令，以保证多线风格与质量统一。
关键词：监督
这张卡当前在索引里支持的耦合（选**一条**）：
  - EDIT_RHYTHM:pacing=medium,avg_shot_len=3-8s
  - TRANSITION_PACK:transition=cut,pacing=medium,scene_type=transition

### 卡片 gen_axis_0281（domain=axis_theory）标题：复制作为意义媒介
正文：机械复制在电影空间中不只是生产手段，而成为形式与媒介，生成新的感知方式；因此复制本身即具美学与符号学功能。
关键词：感知
这张卡当前在索引里支持的耦合（选**一条**）：
  - IMPACT_PACK:vfx=glow,sfx=静默,movement=固定
  - SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=cinematic

### 卡片 gen_block_0086（domain=blocking）标题：天幕的反射式布光
正文：若要让舞台光接近自然日光，用天幕（尤其穹顶式）让光在幕面间交叉反射，使舞台主要由反射光照明，避免旧式直射人工强光造成的虚假感。
关键词：反射光、自然光
这张卡当前在索引里支持的耦合（选**一条**）：
  - LIGHT_PACK:lighting=冷光,intensity=low
  - LIGHT_PACK:lighting=冷光,intensity=mid
  - LIGHT_PACK:lighting=暖光,intensity=low,lighting=冷光
  - LIGHT_PACK:lighting=高调,intensity=mid

### 卡片 gen_cine_0001（domain=cinematography）标题：中焦标准视角约53度
正文：4×5画幅配5英寸焦距镜头时视角约53°，属于室内外通用的一般工作视角，适合常规取景。
关键词：通用
这张卡当前在索引里支持的耦合（选**一条**）：
  - SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=cinematic,movement=固定

### 卡片 gen_cine_0002（domain=cinematography）标题：固定焦点免对焦
正文：Williamson等相机在特定距离内因光圈固定焦点而无需对焦，适合日常拍摄；只有需要严格对焦时才启用毛面胶片检查。
关键词：日常拍摄
这张卡当前在索引里支持的耦合（选**一条**）：
  - EDIT_RHYTHM:pacing=medium,avg_shot_len=3-8s

### 卡片 gen_cine_0004（domain=cinematography）标题：干燥前除净表面水分
正文：上晾干架前须用湿麂皮仔细擦去胶片表面水分，否则会轻微渗色、挤水不足导致着色不匀。
关键词：染色、麂皮
这张卡当前在索引里支持的耦合（选**一条**）：
  - TRANSITION_PACK:transition=cut,pacing=short,scene_type=insert
```
