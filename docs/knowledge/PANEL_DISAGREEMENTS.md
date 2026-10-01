# 双模型复核：分歧清单（请人只看这些）

- 复核条目 116 条；两模型一致接受 1；一致否决并剔除 93；**分歧 22**。
- 复核者标记为 `llm-panel`（**不是人**）：门⑦ 只认 `reviewed_by == "human"`，所以它没有被这份清单满足。

## hq_0780

查询：`情绪=庄严；强度=high；运镜=tilt_up；禁运镜=tilt_down`

- A（deepseek-chat）：accepted — 卡支持上摇仰视显庄严，q与must取值一致，边类型合规，top1匹配且never无交集。
- B（glm-4.7-flash）：rejected — 运镜取值不规范

## hq_0781

查询：`情绪=庄严；强度=high；运镜=handheld`

- A（deepseek-chat）：accepted — 卡支持庄严严肃格调，q与must取值一致，禁忌冲突成立，never不相交。
- B（glm-4.7-flash）：rejected — 运镜handheld与严肃基调冲突

## hq_0782

查询：`情绪=恐惧；强度=high；景别=ECU`

- A（deepseek-chat）：rejected — 卡片讲死因需符合常理，未涉及恐惧情绪或ECU景别耦合
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_0783

查询：`情绪=恐惧；强度=high；景别=ELS`

- A（deepseek-chat）：rejected — 卡讲低机位权力语法，未支持恐惧+禁ELS的耦合，属硬凑
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_0825

查询：`情绪=焦虑；强度=high；运镜=固定`

- A（deepseek-chat）：rejected — 卡只讲切换频率取舍，未支持焦虑/固定运镜等耦合
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_0839

查询：`情绪=压抑；强度=low；运镜=dolly_in`

- A（deepseek-chat）：rejected — 卡未提运镜/强度耦合，且q与must同kind取值不一致
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_0841

查询：`情绪=压抑；强度=low；运镜=固定；禁运镜=固定`

- A（deepseek-chat）：rejected — 卡片讲暗示优于直给，未涉及压抑情绪或固定运镜的耦合，属硬凑
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_0873

查询：`情绪=平静；强度=low；运镜=follow_subject；禁运镜=固定`

- A（deepseek-chat）：rejected — 卡只讲跟拍运镜，未支持情绪/强度耦合，且禁运镜=固定非卡中禁忌
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_0897

查询：`情绪=压抑；强度=mid；运镜=crane_down；禁运镜=crane_up`

- A（deepseek-chat）：accepted — 键名合规，边类型与槽位齐全，top1与must一致，卡支持降镜情绪逼近与禁升镜。
- B（glm-4.7-flash）：rejected — q键值未在词表中

## hq_0915

查询：`情绪=期待；强度=mid；禁情绪=恐惧`

- A（deepseek-chat）：accepted — 卡区分期待与悬念，q与must同kind取值一致，边类型合规，top1与must一致，never无相交。
- B（glm-4.7-flash）：rejected — q键取值不符合规范，must边类型不符

## hq_1153

查询：`光线=底光；强度=high；禁光线=正面光`

- A（deepseek-chat）：rejected — 卡讲顶灯+脚灯去影过度，未支持底光/高强度/禁正面光耦合
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_1193

查询：`光线=正面光；强度=high；禁光线=顶光`

- A（deepseek-chat）：rejected — 卡讲四周布光弊端，未涉及正面光/顶光/强度high的耦合
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_1216

查询：`光线=逆光；强度=high；禁光线=正面光`

- A（deepseek-chat）：rejected — 卡只讲逆光需遮光，未提强度high或禁正面光，边无依据
- B（glm-4.7-flash）：accepted — 完全匹配协议与卡内内容

## hq_1275

查询：`光线=高调；强度=mid；禁光线=底光`

- A（deepseek-chat）：rejected — 卡只讲舞台灯分四组，未涉及高调/强度/底光耦合
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_1895

查询：`构图=framing；景别=CU；机位=平视；禁构图=rule_of_thirds`

- A（deepseek-chat）：rejected — 卡讲徒手画线忌机械工具，未涉及framing/CU/平视/rule_of_thirds耦合
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_2220

查询：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

- A（deepseek-chat）：rejected — 卡讲孤立单元增重，未涉及balance/MS/平视/rule_of_thirds耦合
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_2221

查询：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

- A（deepseek-chat）：rejected — 卡讲配重勿过重，未支持balance/MS/平视/禁三分等边
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_2230

查询：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

- A（deepseek-chat）：rejected — 卡讲封闭形内部分割，未提balance/MS/平视/rule_of_thirds等耦合
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_2231

查询：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

- A（deepseek-chat）：rejected — 卡只讲丑感判断在心智辨识，未提balance/MS/平视/rule_of_thirds等耦合
- B（glm-4.7-flash）：accepted — 协议键值与must槽位完全一致，意图符合卡中描述。

## hq_2298

查询：`构图=framing；景别=MS；机位=平视；禁构图=headroom`

- A（deepseek-chat）：rejected — 卡讲拱形空间忌横排头，未涉及framing/MS/平视/headroom耦合
- B（glm-4.7-flash）：accepted — 完全匹配协议规范，意图一致

## hq_2300

查询：`构图=headroom；景别=MS；机位=平视；禁构图=rule_of_thirds`

- A（deepseek-chat）：rejected — 卡讲跪姿头部避中线，未涉及headroom/三分法等构图规则
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

## hq_2682

查询：`情绪=悲伤；强度=high；运镜=whip_pan_left`

- A（deepseek-chat）：rejected — 卡只讲五幕情绪配比，未涉及悲伤/高强度/甩镜耦合，属硬凑
- B（glm-4.7-flash）：error — LLMError: glm 调用失败：HTTP 429: {"error":{"code":"1305","message":"该模型当前访问量过大，请您稍后再试"}}

