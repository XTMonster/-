# 双模型复核：分歧清单（请人只看这些）

- 复核条目 102 条；两模型一致接受 79；一致否决并剔除 1；**分歧 16**；**一条模型没答上来、因此没有记录 6**。
- 复核者标记为 `llm-panel`（**不是人**）：门⑦ 只认 `reviewed_by == "human"`，所以它没有被这份清单满足。

## hq_0122

查询：`动作=后退；桥段=establish；强度=mid；禁运镜=lead_subject`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never与must不相交，边与q相关。
- B（glm-4.7）：amended — 卡片主题为运镜lead_subject，q中禁运镜=lead_subject逻辑矛盾

## hq_0460

查询：`语气=平淡；节奏=medium；强度=mid；禁语气=画外音`

- A（deepseek-chat）：rejected — 禁语气=画外音与must的forbid_delivery=画外音同值，构成禁忌冲突
- B（glm-4.7）：accepted — q与must同kind取值一致，never与must无交集，可达性满足

## hq_0782

查询：`情绪=庄严；强度=high；禁运镜=tilt_up`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never与must不相交，边与q相关。
- B（glm-4.7）：amended — q禁止了卡的核心运镜tilt_up，与卡矛盾。

## hq_1136

查询：`光线=低调；强度=low；禁光线=高调`

- A（deepseek-chat）：accepted — q与must同kind取值一致，top1与must相同，never无相交，可达可判定。
- B（glm-4.7）：amended — q与卡意图相反，卡主张大面积受光(高调)非整体调暗(低调)

## hq_1869

查询：`景别=ELS；镜头=24mm；运镜=tilt_up`

- A（deepseek-chat）：accepted — q的景别/镜头/运镜在must中同类同值可达，never与must不相交，边与q相关
- B（glm-4.7）：amended — expect_movements与卡中“仰摇”意图不符，应改为tilt_up

## hq_1881

查询：`景别=LS；镜头=24mm；运镜=crane_arc_down`

- A（deepseek-chat）：rejected — q的运镜crane_arc_down与卡意图crane_arc_up矛盾，且与expect_movements冲突
- B（glm-4.7）：amended — q与must的运镜crane_arc_down与卡片及expect_movements矛盾

## hq_1918

查询：`景别=MS；镜头=35mm；运镜=dolly_in`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never不相交，边与q相关，可判定。
- B（glm-4.7）：amended — expect_movements为单纯位移，违背卡中意图

## hq_1923

查询：`景别=MS；镜头=50mm；运镜=dolly_in`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never不相交，运镜符合意图
- B（glm-4.7）：amended — expect_movements与卡中移焦意图不符，卡未写运镜期望应为空

## hq_1925

查询：`景别=MS；镜头=35mm；运镜=follow_subject`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never不相交，运镜期望符合卡意
- B（glm-4.7）：amended — q与must运镜应为orbit_ccw而非follow_subject

## hq_1929

查询：`景别=MS；镜头=35mm；运镜=follow_subject`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never不相交，边与q相关，可判定
- B（glm-4.7）：amended — expect_movements未体现卡片“推轨叠加摇移”的复合运动意图

## hq_1945

查询：`景别=MS；镜头=35mm；运镜=orbit_ccw`

- A（deepseek-chat）：rejected — 卡讲跟拍，q却点orbit_ccw，与must同kind不同值且与卡意图矛盾
- B（glm-4.7）：amended — q运镜orbit_ccw与卡片跟拍意图矛盾，应改为follow_subject

## hq_1947

查询：`景别=MS；镜头=35mm；运镜=orbit_ccw`

- A（deepseek-chat）：rejected — q运镜orbit_ccw与卡及expect_movements的orbit_cw矛盾
- B（glm-4.7）：amended — q与must中运镜为逆时针，与卡顺时针矛盾

## hq_2018

查询：`景别=MS；镜头=50mm`

- A（deepseek-chat）：accepted — q取值MS/50mm与must同类同值可达，never不相交，边相关，可判定。
- B（glm-4.7）：amended — 卡写镜头外移，zoom_in矛盾，应留空

## hq_2612

查询：`构图=occlusion；景别=MS；机位=平视；禁构图=rule_of_thirds`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never与must不相交，边与构图相关
- B（glm-4.7）：rejected — never禁高机位违背卡意图，且缺expect_movements

## hq_2731

查询：`转场=cut；节奏=medium；对白=transition；禁运镜=固定`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never与must不相交，边与q相关。
- B（glm-4.7）：rejected — q中“对白”与must中“scene_type”非同kind，且“转场=cut”不符舞台换景卡语义

## hq_2750

查询：`转场=whip；节奏=short；对白=transition；禁运镜=固定`

- A（deepseek-chat）：accepted — q取值均能在must同类同值找到，never与must不相交，边与q相关。
- B（glm-4.7）：amended — q的对白与must的scene_type不同类，违反同类同值对应

## hq_0363

查询：`景别=CU；轴线=中性机位；禁轴线=越轴`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，无矛盾，never为空不相交
- B（glm-4.7）：amended — 期望偏离知识卡核心(视线高度匹配)，且q与must取值不逐字相同。

## hq_0366

查询：`景别=CU；轴线=中性机位；禁轴线=越轴`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，无矛盾，top1一致，never为空
- B（glm-4.7）：amended — q与must同kind取值不逐字相同(轴线/axis_side)，且禁轴线与forbid_axis_topic不匹配

## hq_0382

查询：`运镜=固定；轴线=中性机位；禁轴线=越轴`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，无矛盾，never为空不相交
- B（glm-4.7）：rejected — 卡讲30°规则，期望却写越轴，张冠李戴

## hq_0383

查询：`运镜=固定；轴线=中性机位；禁轴线=越轴`

- A（deepseek-chat）：accepted — q取值均能在must同类同值找到，无矛盾，可判定。
- B（glm-4.7）：amended — q中轴线与禁轴线键值映射错误，应改为轴线=中性及禁桥段=越轴

## hq_0892

查询：`情绪=庄严；强度=mid；禁运镜=orbit_cw`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never与must不相交，边与q相关
- B（glm-4.7）：amended — q与must同时禁止本卡核心运镜orbit_cw，属禁忌冲突

## hq_1234

查询：`光线=正面光；强度=mid；禁光线=暖光`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never与must不相交，边与q相关
- B（glm-4.7）：rejected — never禁止正面光与must要求正面光矛盾

## hq_1285

查询：`光线=高调；强度=high；禁光线=正面光`

- A（deepseek-chat）：rejected — 卡讲弧光灯隔离易燃物，与高调/强度/正面光完全无关，边对不上q
- B（glm-4.7）：accepted — q与must同类同值完全对应，无矛盾，可判定。

## hq_1286

查询：`光线=高调；强度=high；禁光线=正面光`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never与must不相交，边与q相关
- B（glm-4.7）：rejected — 期望与知识卡内容完全无关，属幻觉编造

## hq_1868

查询：`景别=ELS；镜头=35mm；运镜=pan_right`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never不相交，边与q相关，可判定。
- B（glm-4.7）：amended — 运镜pan_right与卡中长跟拍矛盾

## hq_1914

查询：`景别=MS；镜头=50mm；运镜=zoom_in；禁景别=CU`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never与must不相交，边类型合规
- B（glm-4.7）：amended — 运镜取值zoom_in不符卡中规范术语变焦

## hq_1972

查询：`景别=MS；镜头=35mm；运镜=track_left`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never不相交，边与q相关
- B（glm-4.7）：amended — expect_movements违背卡片复合运动意图

## hq_1974

查询：`景别=MS；镜头=50mm；运镜=track_left`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never不相交，边与横摇运镜相关
- B（glm-4.7）：amended — 卡讲横摇，q与must却用track_left，与expect_movements及卡矛盾

## hq_2004

查询：`景别=MS；镜头=85mm；运镜=固定`

- A（deepseek-chat）：accepted — q取值MS/85mm/固定均在must同类同值可达，never不相交，边相关。
- B（glm-4.7）：rejected — 卡片为硬件对焦操作，未提及MS/85mm/固定，期望属编造

## hq_2692

查询：`转场=cut；节奏=medium；对白=transition；禁节奏=long`

- A（deepseek-chat）：accepted — q取值均能在must同类同值找到，never与must不相交，边与q相关
- B（glm-4.7）：amended — q中对白=transition在must无同类同值对应，不可达且违背卡片禁对白意图

## hq_2730

查询：`转场=cut；节奏=medium；对白=transition；禁运镜=固定`

- A（deepseek-chat）：accepted — q取值与must同类同值可达，never与must不相交，边与q相关。
- B（glm-4.7）：rejected — q中对白=transition在must中无同类对应，不可达

## hq_1949

查询：`景别=MS；镜头=35mm；运镜=orbit_cw`

- A（deepseek-chat）：rejected — q运镜orbit_cw与卡意图orbit_ccw矛盾，且must同kind取值不同
- B（glm-4.7）：amended — q与must的运镜为cw，与卡片ccw及expect_movements矛盾

