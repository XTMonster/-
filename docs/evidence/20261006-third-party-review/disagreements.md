# 第三方（Kimi K3）与 llm-panel 的分歧清单

授权：`user-2026-10-06:third-party adjudication stands in for my human review`。裁决者写的是 `third-party`，不是 `human`。

- **hq_0122**：llm-panel `amended`（）／ third-party `accepted`（q 键合法，取值与 must 逐字一致，top1 相符，never 无交集，可达可判定）
- **hq_0363**：llm-panel `amended`（）／ third-party `accepted`（q三值在must中同类同值可达，top1逐字一致，never为空，无①②③矛盾）
- **hq_0366**：llm-panel `amended`（）／ third-party `accepted`（q三键合法，取值在must同类同值可达，top1与must一致，never无交集）
- **hq_0382**：llm-panel `amended`（）／ third-party `accepted`（q 三个取值在 must 中均同类同值可达，top1 与 must 一字不差，never 为空无冲突）
- **hq_0383**：llm-panel `amended`（）／ third-party `accepted`（键值合法且与 must 逐字一致，AXIS_RULE 槽位齐全，top1=must，never 为空，q 各值均可达）
- **hq_0460**：llm-panel `amended`（）／ third-party `accepted`（q四键均为协议键，取值在must/top1同类同值可达，top1一致，never无交集）
- **hq_0495**：llm-panel `accepted`（）／ third-party `rejected`（卡讲相邻镜景别差异防跳切，期望却写短节奏/短镜长，与卡完全无关）
- **hq_0782**：llm-panel `amended`（）／ third-party `accepted`（q 三值在 must 中同类同值可达，top1 一致，never 不相交）
- **hq_0892**：llm-panel `amended`（）／ third-party `accepted`（键合法、同kind取值逐字一致，top1=must，never不相交，q三值均可达）
- **hq_0970**：llm-panel `amended`（）／ third-party `accepted`（q键合法、取值与must逐字一致，top1相符，never无交，可达可判定）
- **hq_1057**：llm-panel `amended`（）／ third-party `rejected`（卡主张持续运动、避免固定，q/must/top1 却取运镜=固定，与卡意相反且与 expect_movements 矛盾）
- **hq_1136**：llm-panel `amended`（）／ third-party `accepted`（q 键合法，取值与 must 逐字一致，top1 命中，never 不相交，可判定）
- **hq_1234**：llm-panel `amended`（）／ third-party `accepted`（q 三键取值在 must/top1 均同类同值可达，never 与 must 无交集，槽位齐全）
- **hq_1285**：llm-panel `amended`（）／ third-party `accepted`（q 三键取值与 must 同类同值可达，top1 一致，never 无交集）
- **hq_1286**：llm-panel `amended`（）／ third-party `accepted`（q与must同类同值逐字一致且可达，top1与must相符，never不相交，可判定）
- **hq_1809**：llm-panel `accepted`（）／ third-party `amended`（卡文无运镜意图，expect_movements 填「固定」无依据，应为空）
- **hq_1819**：llm-panel `accepted`（）／ third-party `amended`（q/must/top1 可达且无冲突，但卡片只讲调焦，未涉及运镜，expect_movements 无依据）
- **hq_1868**：llm-panel `amended`（）／ third-party `accepted`（键合法、边类型与槽位合规，q三值在must/top1可达，never无相交，运镜期望与卡意相符）
- **hq_1887**：llm-panel `accepted`（）／ third-party `amended`（卡未写运镜期望，expect_movements 填「固定」无卡内依据）
- **hq_1914**：llm-panel `amended`（）／ third-party `accepted`（q 四值与 must 逐字对应可达，top1 一致，never 不相交，槽位按 schema 补全合规）
- **hq_1918**：llm-panel `amended`（）／ third-party `accepted`（q三值与must同类同字可达，top1逐字一致，never不相交，dolly_in符合卡意图）
- **hq_1929**：llm-panel `amended`（）／ third-party `accepted`（键值合规，q 与 must 同值逐字一致，top1 匹配，never 无交集，可达可判定）
- **hq_1945**：llm-panel `amended`（）／ third-party `accepted`（q与must同kind同值可达，top1一致，never不相交，expect_movements合卡意）
- **hq_1972**：llm-panel `amended`（）／ third-party `accepted`（q 与 must 同类同值可达，top1 逐字一致，never 无交集，运镜符合卡意）
- **hq_2004**：llm-panel `amended`（）／ third-party `accepted`（q 三键合规，取值与 must/top1 同类同值可达；never 不相交；必填槽位齐全）
- **hq_2612**：llm-panel `amended`（）／ third-party `accepted`（q 与 must 同kind同值逐字一致，top1 命中，never 无交集，可判定）
- **hq_2692**：llm-panel `amended`（）／ third-party `accepted`（键合法且与must同值逐字相同，top1一致，never不相交，无矛盾，可判定。）
