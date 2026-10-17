# 白模参考包 · 目标模型 Seedance 2.5

- 总镜数：64；白模视频段数：64。
- 提示词模板：`prompt_seedance_2.5.txt`（Seedance 2.5）。

## 角色名册

| 角色名 | 占位色 | 身高 | 定妆卡文件 | 出场镜号 |
| --- | --- | --- | --- | --- |
| char_001 | #FF6B6B | 1.70 | reference/characters/char_001.png | shot_001、shot_002、shot_003、shot_004、shot_006、shot_008、shot_009、shot_011、shot_013、shot_014、shot_016、shot_017、shot_018、shot_020、shot_021、shot_023、shot_024、shot_025、shot_026、shot_028、shot_029、shot_031、shot_032、shot_033、shot_034、shot_036、shot_037、shot_039、shot_040、shot_041、shot_042、shot_044、shot_045、shot_047、shot_048、shot_049、shot_050、shot_052、shot_053、shot_055、shot_056、shot_057、shot_058、shot_060、shot_061、shot_062、shot_064 |
| char_002 | #6BC5FF | 1.70 | reference/characters/char_002.png | shot_002、shot_005、shot_006、shot_007、shot_009、shot_010、shot_012、shot_013、shot_015、shot_018、shot_019、shot_021、shot_022、shot_024、shot_026、shot_027、shot_029、shot_030、shot_032、shot_034、shot_035、shot_037、shot_038、shot_040、shot_042、shot_043、shot_045、shot_046、shot_048、shot_050、shot_051、shot_053、shot_054、shot_058、shot_059、shot_061、shot_063、shot_064 |

## 交付物

| 文件 | 用途 |
| --- | --- |
| `README.md` | 交付清单、角色名册与切片建议总览 |
| `prompt_seedance_2.5.txt` | 给目标视频模型的逐字提示词（模板渲染结果） |
| `shot_cards.md` | 逐镜镜头卡：景别、时长、运镜文字与出场角色 |
| `continuity.json` | 整场连续性快照：每镜屏幕左右分组与朝向 |
| `responsibility.md` | 各镜分工声明：白模/提示词/参考图职责分区 |

## 切片建议

时间线超出单段上限，已建议切为 7 段（切点全在镜头切换处，见 README）；逐段喂入并保持段序。
