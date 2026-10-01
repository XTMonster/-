# held-out 人审裁决表（门⑦）

- 需要人裁决的条目：**133** 条（门⑦ 要求其中至少 `min(总数, 120)` 条带上 `reviewed_by == "human"`）。
- 本表列出 **133** 条（`--limit` 控制）。

**怎么填**：每节末尾的打勾位从 `[ ]` 改成 `[x]` 表示这条期望成立；不成立就删掉那行、改写成 `rejected: 原因`；要改写成别的就写 `amended: 改成什么`。三种写法 `tools/holdout_review.py apply` 都认。

填完执行：

```powershell
python tools/holdout_review.py apply --entries fixtures/knowledge_holdout.jsonl \
  --sheet docs/knowledge/HUMAN_REVIEW_SHEET.md \
  --out fixtures/knowledge_holdout.jsonl
```

（只有当你确认整表都填过之后才跑 `apply` —— 它有 `must_touch` 守卫，漏填会直接拒绝写回。）

## hq_0253 · gen_anime_0355 · Q7 冲突 1 处

查询 A：`动作=动作；桥段=coverage；强度=mid；禁动作=动作规范`

| 族 | 必须边 |
|---|---|
| A | `ACTION_BEAT:action=动作,beat_type=coverage,intensity=mid,forbid_action=动作规范` |

不该召回：`['ACTION_BEAT:action=准备,beat_type=establish,intensity=low']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0336 · cine_move_and_axis · Q7 冲突 1 处

查询 A：`运镜=orbit_cw；轴线=越轴；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `AXIS_RULE:pair=any_two,axis_side=neutral,movement=orbit_cw,forbid_movement=固定,axis_topic=越轴` |

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0337 · cine_move_and_axis · Q7 冲突 1 处

查询 A：`运镜=track_right；轴线=越轴；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `AXIS_RULE:pair=any_two,axis_side=neutral,movement=track_right,forbid_movement=固定,axis_topic=越轴` |

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0413 · gen_perf_0313 · Q7 冲突 1 处

查询 A：`语气=平淡；节奏=long；强度=low；禁语气=喊叫`

| 族 | 必须边 |
|---|---|
| A | `DIALOGUE_PACK:delivery=平淡,pacing=long,intensity=low,forbid_delivery=喊叫` |

不该召回：`['DIALOGUE_PACK:delivery=画外音,pacing=medium,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0771 · gen_perf_0521 · Q7 冲突 4 处

查询 A：`情绪=压抑;强度=high;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0772 · gen_edit_0239 · Q7 冲突 4 处

查询 A：`情绪=压抑;强度=high;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0776 · gen_perf_0416 · Q7 冲突 1 处

查询 A：`情绪=喜悦;强度=high;禁情绪=悲伤`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=喜悦,intensity=high,forbid_emotion=悲伤` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0780 · cine_move_tilt_up · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=high；运镜=tilt_up；禁运镜=tilt_down`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=high,movement=tilt_up,forbid_movement=tilt_down` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0781 · gen_story_0237 · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=high；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=high,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0782 · gen_story_0027 · Q7 冲突 1 处

查询 A：`情绪=恐惧；强度=high；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0783 · cine_low_angle · Q7 冲突 1 处

查询 A：`情绪=恐惧；强度=high；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0784 · gen_story_0025 · Q7 冲突 1 处

查询 A：`情绪=恐惧；强度=high；禁情绪=期待`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_emotion=期待` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0785 · gen_story_0284 · Q7 冲突 4 处

查询 A：`情绪=恐惧；强度=high；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0786 · gen_perf_0406 · Q7 冲突 4 处

查询 A：`情绪=恐惧；强度=high；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0801 · gen_edit_0026 · Q7 冲突 1 处

查询 A：`情绪=期待；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0808 · cine_move_handheld · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=handheld；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,movement=handheld,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0809 · cine_move_speed · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=handheld；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,movement=handheld,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0810 · cine_move_stacking · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=handheld；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,movement=handheld,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0811 · cine_move_whip_pan_left · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_left；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,movement=whip_pan_left,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0812 · cine_move_whip_pan_right · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_left；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,movement=whip_pan_left,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0813 · cine_move_whip_pan_left · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_right；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,movement=whip_pan_right,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0814 · cine_move_whip_pan_right · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_right；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,movement=whip_pan_right,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0815 · cine_dutch_angle · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0816 · gen_perf_0554 · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0822 · cine_move_dolly_in · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=dolly_in；禁运镜=dolly_out`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,movement=dolly_in,forbid_movement=dolly_out` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0823 · gen_axis_0285 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0824 · gen_edit_0009 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0825 · gen_edit_0012 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0826 · gen_edit_0131 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0827 · gen_perf_0077 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0828 · gen_story_0236 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0837 · gen_edit_0128 · Q7 冲突 1 处

查询 A：`情绪=冷漠；强度=low；运镜=orbit_cw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0839 · gen_perf_0475 · Q7 冲突 1 处

查询 A：`情绪=压抑；强度=low；运镜=dolly_in`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=dolly_in` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0840 · gen_axis_0105 · Q7 冲突 4 处

查询 A：`情绪=压抑；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0841 · gen_prod_0241 · Q7 冲突 4 处

查询 A：`情绪=压抑；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0864 · gen_perf_0444 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=low；运镜=handheld；景别=CU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=handheld,forbid_shot_size=CU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0865 · gen_perf_0447 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=low；运镜=handheld；景别=CU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=handheld,forbid_shot_size=CU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0866 · gen_edit_0059 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；景别=ECU；禁景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0867 · gen_edit_0060 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；景别=ECU；禁景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0868 · gen_perf_0563 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；景别=ECU；禁景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0869 · gen_story_0286 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；景别=ECU；禁景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0870 · gen_edit_0177 · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；禁情绪=喜悦`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_emotion=喜悦` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0871 · cine_move_follow_subject · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=follow_subject；禁运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0872 · cine_move_motivation · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=follow_subject；禁运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0873 · cine_move_follow_subject · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=follow_subject；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0874 · cine_move_motivation · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=follow_subject；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0875 · gen_story_0241 · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0877 · gen_cine_0077 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0878 · gen_perf_0469 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0879 · gen_prod_0209 · Q7 冲突 4 处

查询 A：`情绪=平静；强度=low；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0883 · gen_perf_0432 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=low；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0885 · gen_edit_0194 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=low；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=low,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0886 · gen_edit_0209 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=low；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=low,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0887 · gen_perf_0505 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=low；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0891 · gen_axis_0288 · Q7 冲突 1 处

查询 A：`情绪=冷漠；强度=mid；运镜=dolly_in`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=冷漠,intensity=mid,forbid_movement=dolly_in` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0897 · cine_move_crane_down · Q7 冲突 1 处

查询 A：`情绪=压抑；强度=mid；运镜=crane_down；禁运镜=crane_up`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=mid,movement=crane_down,forbid_movement=crane_up` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0898 · gen_axis_0160 · Q7 冲突 1 处

查询 A：`情绪=压抑；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0905 · gen_edit_0027 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0906 · cine_move_tilt_down · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；运镜=tilt_down；禁运镜=tilt_up`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,movement=tilt_down,forbid_movement=tilt_up` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0907 · gen_perf_0474 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0908 · gen_prod_0231 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0915 · gen_story_0025 · Q7 冲突 1 处

查询 A：`情绪=期待；强度=mid；禁情绪=恐惧`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_emotion=恐惧` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0916 · gen_story_0288 · Q7 冲突 1 处

查询 A：`情绪=期待；强度=mid；运镜=dolly_in`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=dolly_in` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0917 · gen_edit_0068 · Q7 冲突 4 处

查询 A：`情绪=期待；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0918 · gen_perf_0446 · Q7 冲突 4 处

查询 A：`情绪=期待；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0920 · gen_story_0076 · Q7 冲突 4 处

查询 A：`情绪=混乱；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0921 · gen_edit_0157 · Q7 冲突 4 处

查询 A：`情绪=混乱；强度=mid；运镜=固定；禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0927 · gen_edit_0137 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=mid；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=mid,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0930 · gen_prod_0141 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=mid；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0931 · gen_cine_0295 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=mid；运镜=steadicam`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_movement=steadicam` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0932 · gen_story_0146 · Q7 冲突 1 处

查询 A：`情绪=荒诞；强度=mid；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=荒诞,intensity=mid,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0933 · cine_move_zoom_out · Q7 冲突 1 处

查询 A：`情绪=荒诞；强度=mid；运镜=dolly_in`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=荒诞,intensity=mid,forbid_movement=dolly_in` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1147 · gen_prod_0059 · Q7 冲突 1 处

查询 A：`光线=侧光；强度=mid；禁光线=底光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=侧光,intensity=mid,forbid_lighting=底光` |

不该召回：`['LIGHT_PACK:lighting=低调,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1148 · gen_prod_0063 · Q7 冲突 1 处

查询 A：`光线=侧光；强度=mid；禁光线=底光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=侧光,intensity=mid,forbid_lighting=底光` |

不该召回：`['LIGHT_PACK:lighting=低调,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1149 · gen_block_0006 · Q7 冲突 1 处

查询 A：`光线=侧光；强度=mid；禁光线=正面光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=侧光,intensity=mid,forbid_lighting=正面光` |

不该召回：`['LIGHT_PACK:lighting=低调,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1153 · gen_block_0355 · Q7 冲突 1 处

查询 A：`光线=底光；强度=high；禁光线=正面光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=底光,intensity=high,forbid_lighting=正面光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1192 · gen_block_0005 · Q7 冲突 1 处

查询 A：`光线=正面光；强度=high；禁光线=侧光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=正面光,intensity=high,forbid_lighting=侧光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1193 · gen_block_0024 · Q7 冲突 1 处

查询 A：`光线=正面光；强度=high；禁光线=顶光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=正面光,intensity=high,forbid_lighting=顶光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1216 · gen_cine_0224 · Q7 冲突 1 处

查询 A：`光线=逆光；强度=high；禁光线=正面光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=逆光,intensity=high,forbid_lighting=正面光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1273 · gen_prod_0055 · Q7 冲突 1 处

查询 A：`光线=高调；强度=mid；禁光线=底光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=高调,intensity=mid,forbid_lighting=底光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1274 · gen_prod_0057 · Q7 冲突 1 处

查询 A：`光线=高调；强度=mid；禁光线=底光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=高调,intensity=mid,forbid_lighting=底光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1275 · gen_prod_0062 · Q7 冲突 1 处

查询 A：`光线=高调；强度=mid；禁光线=底光`

| 族 | 必须边 |
|---|---|
| A | `LIGHT_PACK:lighting=高调,intensity=mid,forbid_lighting=底光` |

不该召回：`['LIGHT_PACK:lighting=侧光,intensity=high']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1429 · gen_axis_0159 · Q7 冲突 1 处

查询 A：`情绪=平静；动作=动作规范；机位=平视；禁动作=人物一致性`

| 族 | 必须边 |
|---|---|
| A | `PERFORMANCE_PACK:emotion=平静,action=动作规范,camera_angle=平视,forbid_action=人物一致性` |

不该召回：`['PERFORMANCE_PACK:emotion=庄严,action=出场,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1677 · gen_axis_0304 · Q7 冲突 1 处

查询 A：`景别=CU;镜头=50mm;构图=framing;禁景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `SHOT_PATTERN:shot_size=CU,lens=50mm,headroom_policy=board,forbid_shot_size=ELS,composition_rule=framing` |

不该召回：`['SHOT_PATTERN:shot_size=ELS,lens=24mm,headroom_policy=cinematic,composition_rule=balance']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_1895 · gen_comp_0232 · Q7 冲突 1 处

查询 A：`构图=framing；景别=CU；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=framing,shot_size=CU,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=lead_room,shot_size=LS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2217 · gen_comp_0107 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=occlusion`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=occlusion` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2218 · gen_comp_0031 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2219 · gen_comp_0033 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2220 · gen_comp_0034 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2221 · gen_comp_0035 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2222 · gen_comp_0037 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2223 · gen_comp_0040 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2224 · gen_comp_0041 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2225 · gen_comp_0042 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2226 · gen_comp_0044 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2227 · gen_comp_0045 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2228 · gen_comp_0063 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2229 · gen_comp_0209 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2230 · gen_comp_0211 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2231 · gen_comp_0212 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2232 · gen_comp_0213 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2233 · gen_comp_0216 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2297 · gen_comp_0144 · Q7 冲突 1 处

查询 A：`构图=framing；景别=MS；机位=平视；禁景别=CU`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=framing,shot_size=MS,camera_angle=平视,forbid_shot_size=CU` |

不该召回：`['STAGING_PACK:composition_rule=lead_room,shot_size=LS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2298 · gen_comp_0086 · Q7 冲突 1 处

查询 A：`构图=framing；景别=MS；机位=平视；禁构图=headroom`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=framing,shot_size=MS,camera_angle=平视,forbid_composition_rule=headroom` |

不该召回：`['STAGING_PACK:composition_rule=lead_room,shot_size=LS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2300 · gen_comp_0006 · Q7 冲突 1 处

查询 A：`构图=headroom；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=headroom,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2301 · gen_comp_0051 · Q7 冲突 1 处

查询 A：`构图=headroom；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=headroom,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2367 · gen_comp_0056 · Q7 冲突 1 处

查询 A：`构图=occlusion；景别=MS；机位=平视；禁构图=balance`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=occlusion,shot_size=MS,camera_angle=平视,forbid_composition_rule=balance` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2368 · gen_comp_0110 · Q7 冲突 1 处

查询 A：`构图=occlusion；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=occlusion,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2398 · gen_comp_0028 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=高机位；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=高机位,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2528 · gen_prod_0258 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；景别=CU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_shot_size=CU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2529 · gen_perf_0359 · Q7 冲突 1 处

查询 A：`情绪=讽刺；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=讽刺,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2550 · gen_axis_0146 · Q7 冲突 1 处

查询 A：`情绪=平静；动作=反派表演；机位=平视；禁动作=人物一致性`

| 族 | 必须边 |
|---|---|
| A | `PERFORMANCE_PACK:emotion=平静,action=反派表演,camera_angle=平视,forbid_action=人物一致性` |

不该召回：`['PERFORMANCE_PACK:emotion=庄严,action=出场,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2551 · gen_perf_0382 · Q7 冲突 1 处

查询 A：`景别=CU；镜头=85mm；禁景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `SHOT_PATTERN:shot_size=CU,lens=85mm,headroom_policy=cinematic,forbid_shot_size=ECU` |

不该召回：`['SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board,composition_rule=balance']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2639 · comp_widescreen_grouping · Q7 冲突 1 处

查询 A：`构图=balance；景别=LS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=LS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2640 · gen_comp_0003 · Q7 冲突 1 处

查询 A：`构图=balance；景别=LS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=LS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2682 · gen_story_0211 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=high；运镜=whip_pan_left`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=high,forbid_movement=whip_pan_left` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2827 · gen_cine_0077 · Q7 冲突 6 处

查询 A：`情绪=平静;强度=low;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2828 · gen_cine_0087 · Q7 冲突 6 处

查询 A：`情绪=平静;强度=low;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2829 · gen_perf_0469 · Q7 冲突 6 处

查询 A：`情绪=平静;强度=low;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2830 · gen_prod_0209 · Q7 冲突 6 处

查询 A：`情绪=平静;强度=low;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2831 · gen_perf_0324 · Q7 冲突 6 处

查询 A：`情绪=平静;强度=low;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2832 · gen_perf_0329 · Q7 冲突 6 处

查询 A：`情绪=平静;强度=low;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2833 · gen_perf_0537 · Q7 冲突 6 处

查询 A：`情绪=平静;强度=low;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2834 · gen_perf_0538 · Q7 冲突 6 处

查询 A：`情绪=平静;强度=low;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2850 · gen_perf_0352 · Q7 冲突 4 处

查询 A：`情绪=平静;强度=mid;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2851 · gen_perf_0468 · Q7 冲突 4 处

查询 A：`情绪=平静;强度=mid;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2852 · gen_perf_0472 · Q7 冲突 4 处

查询 A：`情绪=平静;强度=mid;运镜=固定;禁运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_2853 · gen_comp_0161 · Q7 冲突 1 处

查询 A：`情绪=庄严;强度=mid;运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_3128 · gen_comp_0066 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_3129 · gen_comp_0150 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_3130 · gen_comp_0152 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_3131 · gen_comp_0154 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_3132 · gen_comp_0156 · Q7 冲突 1 处

查询 A：`构图=balance；景别=MS；机位=平视；禁构图=rule_of_thirds`

| 族 | 必须边 |
|---|---|
| A | `STAGING_PACK:composition_rule=balance,shot_size=MS,camera_angle=平视,forbid_composition_rule=rule_of_thirds` |

不该召回：`['STAGING_PACK:composition_rule=framing,shot_size=MLS,camera_angle=低机位']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

<!-- 133/133 -->
