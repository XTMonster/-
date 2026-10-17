# 白模参考包 · 目标模型 Seedance 2.5

- 总镜数：13；白模视频段数：13。
- 提示词模板：`prompt_seedance_2.5.txt`（Seedance 2.5）。

## 角色名册

| 角色名 | 占位色 | 身高 | 定妆卡文件 | 出场镜号 |
| --- | --- | --- | --- | --- |
| char_001 | #FF6B6B | 1.70 | reference/characters/char_001.png | shot_002、shot_004、shot_005、shot_007、shot_008、shot_010 |
| char_002 | #6BC5FF | 1.70 | reference/characters/char_002.png | shot_003、shot_009、shot_012、shot_013 |
| char_003 | #FFD166 | 1.70 | reference/characters/char_003.png | shot_006 |
| char_004 | #9B8CFF | 1.70 | reference/characters/char_004.png | shot_011、shot_013 |

## 交付物

| 文件 | 用途 |
| --- | --- |
| `README.md` | 交付清单、角色名册与切片建议总览 |
| `prompt_seedance_2.5.txt` | 给目标视频模型的逐字提示词（模板渲染结果） |
| `shot_cards.md` | 逐镜镜头卡：景别、时长、运镜文字与出场角色 |
| `continuity.json` | 整场连续性快照：每镜屏幕左右分组与朝向 |
| `responsibility.md` | 各镜分工声明：白模/提示词/参考图职责分区 |

## 切片建议

时间线超出单段上限，已建议切为 3 段（切点全在镜头切换处，见 README）；逐段喂入并保持段序。
