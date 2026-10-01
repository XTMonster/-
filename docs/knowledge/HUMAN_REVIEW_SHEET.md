# held-out 人审裁决表（门⑦）

- 需要人裁决的条目：**146** 条（门⑦ 要求其中至少 `min(总数, 120)` 条带上 `reviewed_by == "human"`）。
- 本表列出 **146** 条（`--limit` 控制）。

**怎么填**：每节末尾的打勾位从 `[ ]` 改成 `[x]` 表示这条期望成立；不成立就删掉那行、改写成 `rejected: 原因`；要改写成别的就写 `amended: 改成什么`。三种写法 `tools/holdout_review.py apply` 都认。

填完执行：

```powershell
python tools/holdout_review.py apply --entries fixtures/knowledge_holdout.jsonl \
  --sheet docs/knowledge/HUMAN_REVIEW_SHEET.md \
  --out fixtures/knowledge_holdout.jsonl
```

（只有当你确认整表都填过之后才跑 `apply` —— 它有 `must_touch` 守卫，漏填会直接拒绝写回。）

## hq_0245 · cine_move_track_right · Q7 冲突 1 处

查询 A：`运镜=track_right；轴线=运动轴；禁运镜=track_left`

| 族 | 必须边 |
|---|---|
| A | `AXIS_RULE:pair=any_two,axis_side=left,movement=track_right,forbid_movement=track_left,axis_topic=运动轴` |

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0246 · cine_move_and_axis · Q7 冲突 1 处

查询 A：`运镜=orbit_cw；轴线=越轴；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `AXIS_RULE:pair=any_two,axis_side=neutral,movement=orbit_cw,forbid_movement=固定,axis_topic=越轴` |

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0247 · cine_move_and_axis · Q7 冲突 1 处

查询 A：`运镜=track_right；轴线=越轴；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `AXIS_RULE:pair=any_two,axis_side=neutral,movement=track_right,forbid_movement=固定,axis_topic=越轴` |

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0320 · gen_perf_0313 · Q7 冲突 1 处

查询 A：`语气=平淡；节奏=long；强度=low；禁语气=喊叫`

| 族 | 必须边 |
|---|---|
| A | `DIALOGUE_PACK:delivery=平淡,pacing=long,intensity=low,forbid_delivery=喊叫` |

不该召回：`['DIALOGUE_PACK:delivery=画外音,pacing=medium,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0678 · gen_perf_0521 · Q7 冲突 4 处

查询 A：`情绪=压抑；强度=high；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0679 · gen_edit_0239 · Q7 冲突 4 处

查询 A：`情绪=压抑；强度=high；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0683 · gen_perf_0416 · Q7 冲突 1 处

查询 A：`情绪=喜悦；强度=high；禁情绪=悲伤`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=喜悦,intensity=high,forbid_emotion=悲伤` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0687 · gen_story_0237 · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=high；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=high,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0688 · gen_story_0027 · Q7 冲突 1 处

查询 A：`情绪=恐惧；强度=high；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0689 · cine_low_angle · Q7 冲突 1 处

查询 A：`情绪=恐惧；强度=high；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0690 · gen_story_0025 · Q7 冲突 1 处

查询 A：`情绪=恐惧；强度=high；禁情绪=期待`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_emotion=期待` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0691 · gen_story_0284 · Q7 冲突 4 处

查询 A：`情绪=恐惧；强度=high；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0692 · gen_perf_0406 · Q7 冲突 4 处

查询 A：`情绪=恐惧；强度=high；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0707 · gen_story_0211 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=high；运镜=whip_pan_left`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=high,forbid_movement=whip_pan_left` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0708 · gen_edit_0075 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0713 · gen_perf_0494 · Q7 冲突 1 处

查询 A：`情绪=愤怒；强度=high；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0714 · gen_prod_0245 · Q7 冲突 1 处

查询 A：`情绪=愤怒；强度=high；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0716 · gen_perf_0040 · Q7 冲突 4 处

查询 A：`情绪=愤怒；强度=high；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0717 · gen_perf_0111 · Q7 冲突 4 处

查询 A：`情绪=愤怒；强度=high；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0718 · gen_perf_0513 · Q7 冲突 4 处

查询 A：`情绪=愤怒；强度=high；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0719 · gen_story_0241 · Q7 冲突 4 处

查询 A：`情绪=愤怒；强度=high；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0721 · gen_edit_0026 · Q7 冲突 1 处

查询 A：`情绪=期待；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0728 · cine_move_handheld · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=handheld；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,movement=handheld,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0729 · cine_move_speed · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=handheld；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,movement=handheld,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0730 · cine_move_stacking · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=handheld；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,movement=handheld,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0731 · cine_move_whip_pan_left · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_left`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=whip_pan_left` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0732 · cine_move_whip_pan_right · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_left`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=whip_pan_left` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0733 · cine_move_whip_pan_left · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_right`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=whip_pan_right` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0734 · cine_move_whip_pan_right · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_right`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=whip_pan_right` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0735 · cine_dutch_angle · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0736 · gen_perf_0554 · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0742 · gen_axis_0285 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0743 · cine_move_dolly_in · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0744 · gen_edit_0009 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0745 · gen_edit_0012 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0746 · gen_edit_0131 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0747 · gen_perf_0077 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0748 · gen_story_0236 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0749 · gen_cine_0211 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；音效=低频轰鸣`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_sfx=低频轰鸣` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0758 · gen_edit_0128 · Q7 冲突 1 处

查询 A：`情绪=冷漠；强度=low；运镜=orbit_cw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0760 · gen_axis_0105 · Q7 冲突 4 处

查询 A：`情绪=压抑；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0761 · gen_perf_0475 · Q7 冲突 4 处

查询 A：`情绪=压抑；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0762 · gen_prod_0241 · Q7 冲突 4 处

查询 A：`情绪=压抑；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0785 · gen_perf_0444 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=low；运镜=handheld；景别=CU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=handheld,forbid_shot_size=CU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0786 · gen_perf_0447 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=low；运镜=handheld；景别=CU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=handheld,forbid_shot_size=CU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0787 · gen_edit_0059 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；景别=ECU；禁景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0788 · gen_edit_0060 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；景别=ECU；禁景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0789 · gen_perf_0563 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；景别=ECU；禁景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0790 · gen_story_0286 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；景别=ECU；禁景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0791 · gen_edit_0177 · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；禁情绪=喜悦`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_emotion=喜悦` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0792 · cine_move_follow_subject · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=follow_subject；禁运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0793 · cine_move_handheld · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=follow_subject；禁运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0794 · cine_move_motivation · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=follow_subject；禁运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0795 · cine_move_follow_subject · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=固定；禁运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=固定,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0796 · cine_move_handheld · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=固定；禁运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=固定,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0797 · cine_move_motivation · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=固定；禁运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=固定,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0798 · cine_move_speed · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=steadicam；禁运镜=track_left`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=steadicam,forbid_movement=track_left` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0799 · cine_move_steadicam · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=steadicam；禁运镜=track_left`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=steadicam,forbid_movement=track_left` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0800 · cine_move_track_left · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=steadicam；禁运镜=track_left`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=steadicam,forbid_movement=track_left` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0801 · gen_story_0241 · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0802 · gen_cine_0077 · Q7 冲突 6 处

查询 A：`情绪=平静；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0803 · gen_prod_0209 · Q7 冲突 6 处

查询 A：`情绪=平静；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0804 · gen_cine_0247 · Q7 冲突 6 处

查询 A：`情绪=平静；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0808 · gen_perf_0432 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=low；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0810 · gen_edit_0194 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=low；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=low,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0811 · gen_edit_0209 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=low；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=low,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0812 · gen_perf_0505 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=low；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0816 · gen_axis_0288 · Q7 冲突 1 处

查询 A：`情绪=冷漠；强度=mid；运镜=dolly_in`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=冷漠,intensity=mid,forbid_movement=dolly_in` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0823 · gen_axis_0160 · Q7 冲突 1 处

查询 A：`情绪=压抑；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0830 · gen_perf_0469 · Q7 冲突 1 处

查询 A：`情绪=喜悦；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=喜悦,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0834 · cine_high_angle · Q7 冲突 1 处

查询 A：`情绪=孤独；强度=mid；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=孤独,intensity=mid,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0835 · cine_move_crane_up · Q7 冲突 1 处

查询 A：`情绪=孤独；强度=mid；运镜=crane_up；禁运镜=dolly_out`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=孤独,intensity=mid,movement=crane_up,forbid_movement=dolly_out` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0836 · cine_move_dolly_out · Q7 冲突 1 处

查询 A：`情绪=孤独；强度=mid；运镜=crane_up；禁运镜=dolly_out`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=孤独,intensity=mid,movement=crane_up,forbid_movement=dolly_out` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0837 · cine_move_crane_up · Q7 冲突 1 处

查询 A：`情绪=孤独；强度=mid；运镜=crane_up；禁运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=孤独,intensity=mid,movement=crane_up,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0838 · cine_move_dolly_out · Q7 冲突 1 处

查询 A：`情绪=孤独；强度=mid；运镜=crane_up；禁运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=孤独,intensity=mid,movement=crane_up,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0851 · gen_perf_0352 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0852 · gen_perf_0468 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0853 · gen_perf_0472 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0860 · gen_comp_0161 · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0861 · cine_move_orbit_ccw · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=orbit_ccw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=orbit_ccw` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0862 · cine_move_orbit_cw · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=orbit_ccw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=orbit_ccw` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0863 · cine_move_orbit_ccw · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=orbit_cw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=orbit_cw` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0864 · cine_move_orbit_cw · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=orbit_cw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=orbit_cw` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0865 · gen_edit_0206 · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0872 · gen_prod_0258 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；景别=CU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_shot_size=CU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0873 · gen_edit_0027 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0874 · gen_perf_0474 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0875 · gen_prod_0231 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0882 · gen_story_0025 · Q7 冲突 1 处

查询 A：`情绪=期待；强度=mid；禁情绪=恐惧`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_emotion=恐惧` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0883 · gen_story_0288 · Q7 冲突 1 处

查询 A：`情绪=期待；强度=mid；运镜=dolly_in`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=dolly_in` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0890 · gen_edit_0068 · Q7 冲突 4 处

查询 A：`情绪=期待；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0891 · gen_perf_0446 · Q7 冲突 4 处

查询 A：`情绪=期待；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0893 · gen_story_0076 · Q7 冲突 4 处

查询 A：`情绪=混乱；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0894 · gen_edit_0157 · Q7 冲突 4 处

查询 A：`情绪=混乱；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0900 · gen_edit_0137 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=mid；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=mid,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0903 · gen_prod_0141 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=mid；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0904 · cine_move_steadicam · Q7 冲突 4 处

查询 A：`情绪=焦虑；强度=mid；运镜=steadicam；禁运镜=steadicam`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_movement=steadicam` |
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_movement=steadicam` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0905 · gen_cine_0295 · Q7 冲突 4 处

查询 A：`情绪=焦虑；强度=mid；运镜=steadicam；禁运镜=steadicam`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_movement=steadicam` |
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_movement=steadicam` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0906 · gen_story_0146 · Q7 冲突 1 处

查询 A：`情绪=荒诞；强度=mid；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=荒诞,intensity=mid,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0907 · cine_move_zoom_out · Q7 冲突 1 处

查询 A：`情绪=荒诞；强度=mid；运镜=dolly_in`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=荒诞,intensity=mid,forbid_movement=dolly_in` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0912 · gen_perf_0359 · Q7 冲突 1 处

查询 A：`情绪=讽刺；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=讽刺,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1028 · gen_cine_0247 · Q7 冲突 1 处

查询 A：`意图=留白；景别=MS；运镜=follow_subject；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `INTENT_PACK:intent=留白,shot_size=MS,movement=follow_subject,forbid_movement=固定` |

不该召回：`['INTENT_PACK:intent=揭示,shot_size=LS,movement=dolly_out']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1141 · gen_prod_0059 · Q7 冲突 1 处

查询 A：`光线=侧光；强度=mid；禁光线=底光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=侧光,intensity=mid,forbid_lighting=底光` |

不该召回：`['LIGHT_PACK:lighting=低调,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1142 · gen_prod_0063 · Q7 冲突 1 处

查询 A：`光线=侧光；强度=mid；禁光线=底光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=侧光,intensity=mid,forbid_lighting=底光` |

不该召回：`['LIGHT_PACK:lighting=低调,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1143 · gen_block_0006 · Q7 冲突 1 处

查询 A：`光线=侧光；强度=mid；禁光线=正面光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=侧光,intensity=mid,forbid_lighting=正面光` |

不该召回：`['LIGHT_PACK:lighting=低调,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1147 · gen_block_0355 · Q7 冲突 1 处

查询 A：`光线=底光；强度=high；禁光线=正面光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=底光,intensity=high,forbid_lighting=正面光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1219 · gen_prod_0055 · Q7 冲突 1 处

查询 A：`光线=高调；强度=mid；禁光线=底光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=高调,intensity=mid,forbid_lighting=底光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1220 · gen_prod_0057 · Q7 冲突 1 处

查询 A：`光线=高调；强度=mid；禁光线=底光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=高调,intensity=mid,forbid_lighting=底光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1221 · gen_prod_0062 · Q7 冲突 1 处

查询 A：`光线=高调；强度=mid；禁光线=底光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=高调,intensity=mid,forbid_lighting=底光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1355 · gen_axis_0159 · Q7 冲突 1 处

查询 A：`情绪=平静；动作=动作规范；机位=平视；禁动作=人物一致性`

| 族 | 必须边 |
|---|---|
| A | `PERFORMANCE_PACK:emotion=平静,action=动作规范,camera_angle=平视,forbid_action=人物一致性` |

不该召回：`['PERFORMANCE_PACK:emotion=庄严,action=出场,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1419 · gen_axis_0146 · Q7 冲突 1 处

查询 A：`情绪=平静；动作=反派表演；机位=平视；禁动作=人物一致性`

| 族 | 必须边 |
|---|---|
| A | `PERFORMANCE_PACK:emotion=平静,action=反派表演,camera_angle=平视,forbid_action=人物一致性` |

不该召回：`['PERFORMANCE_PACK:emotion=庄严,action=出场,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1595 · gen_axis_0304 · Q7 冲突 1 处

查询 A：`景别=CU;镜头=50mm;构图=framing;禁景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `SHOT_PATTERN:shot_size=CU,lens=50mm,headroom_policy=board,forbid_shot_size=ELS,composition_rule=framing` |

不该召回：`['SHOT_PATTERN:shot_size=ELS,lens=24mm,headroom_policy=cinematic,composition_rule=balance']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1617 · gen_perf_0382 · Q7 冲突 1 处

查询 A：`景别=CU;镜头=85mm;禁景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `SHOT_PATTERN:shot_size=CU,lens=85mm,headroom_policy=cinematic,forbid_shot_size=ECU` |

不该召回：`['SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board,composition_rule=balance']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1862 · gen_comp_0232 · Q7 冲突 1 处

查询 A：`构图=framing；景别=CU；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=framing,shot_size=CU,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=lead_room,shot_size=LS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1979 · comp_widescreen_grouping · Q7 冲突 1 处

查询 A：`构图=balance；景别=LS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=LS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1980 · gen_comp_0003 · Q7 冲突 1 处

查询 A：`构图=balance；景别=LS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=LS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2253 · gen_comp_0107 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=occlusion`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=occlusion` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2254 · gen_comp_0031 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2255 · gen_comp_0033 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2256 · gen_comp_0034 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2257 · gen_comp_0035 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2258 · gen_comp_0037 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2259 · gen_comp_0040 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2260 · gen_comp_0041 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2261 · gen_comp_0042 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2262 · gen_comp_0044 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2263 · gen_comp_0045 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2264 · gen_comp_0063 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2265 · gen_comp_0209 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2266 · gen_comp_0211 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2267 · gen_comp_0212 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2268 · gen_comp_0213 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2269 · gen_comp_0216 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2332 · gen_comp_0144 · Q7 冲突 1 处

查询 A：`构图=framing；景别=MS；机位=平视；禁景别=CU`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=framing,shot_size=MS,camera_angle=平视,forbid_shot_size=CU` |

不该召回：`['STAGING_PACK:composition_rule=lead_room,shot_size=LS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2333 · gen_comp_0086 · Q7 冲突 1 处

查询 A：`构图=framing；景别=MS；机位=平视；禁构图=headroom`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=framing,shot_size=MS,camera_angle=平视,forbid_composition_rule=headroom` |

不该召回：`['STAGING_PACK:composition_rule=lead_room,shot_size=LS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2344 · gen_comp_0028 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=高机位；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=高机位,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2515 · gen_anime_0355 · Q7 冲突 1 处

查询 A：`动作=动作;桥段=coverage;强度=mid;禁动作=动作规范`

| 族 | 必须边 |
|---|---|
| A | `ACTION_BEAT:action=动作,beat_type=coverage,intensity=mid,forbid_action=动作规范` |

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2524 · gen_block_0006 · Q7 冲突 1 处

查询 A：`光线=侧光;强度=mid;禁光线=正面光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=侧光,intensity=mid,forbid_lighting=正面光` |

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2525 · gen_block_0355 · Q7 冲突 1 处

查询 A：`光线=底光;强度=high;禁光线=正面光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=底光,intensity=high,forbid_lighting=正面光` |

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2535 · gen_block_0005 · Q7 冲突 1 处

查询 A：`光线=正面光;强度=high;禁光线=侧光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=正面光,intensity=high,forbid_lighting=侧光` |

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2536 · gen_block_0024 · Q7 冲突 1 处

查询 A：`光线=正面光；强度=high；禁光线=顶光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=正面光,intensity=high,forbid_lighting=顶光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2554 · gen_cine_0224 · Q7 冲突 1 处

查询 A：`光线=逆光；强度=high；禁光线=正面光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=逆光,intensity=high,forbid_lighting=正面光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2688 · gen_comp_0006 · Q7 冲突 1 处

查询 A：`构图=headroom；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=headroom,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2689 · gen_comp_0051 · Q7 冲突 1 处

查询 A：`构图=headroom；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=headroom,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2752 · gen_comp_0056 · Q7 冲突 1 处

查询 A：`构图=occlusion；景别=MS；机位=平视；禁构图=balance`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=occlusion,shot_size=MS,camera_angle=平视,forbid_composition_rule=balance` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2753 · gen_comp_0110 · Q7 冲突 1 处

查询 A：`构图=occlusion；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=occlusion,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

<!-- 146/146 -->
