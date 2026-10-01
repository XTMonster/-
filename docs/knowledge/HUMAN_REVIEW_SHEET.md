# held-out 人审裁决表（门⑦）

- 需要人裁决的条目：**74** 条（门⑦ 要求其中至少 `min(总数, 120)` 条带上 `reviewed_by == "human"`）。
- 本表列出 **74** 条（`--limit` 控制）。

**怎么填**：每节末尾的打勾位从 `[ ]` 改成 `[x]` 表示这条期望成立；不成立就删掉那行、改写成 `rejected: 原因`；要改写成别的就写 `amended: 改成什么`。三种写法 `tools/holdout_review.py apply` 都认。

填完执行：

```powershell
python tools/holdout_review.py apply --entries fixtures/knowledge_holdout.jsonl \
  --sheet docs/knowledge/HUMAN_REVIEW_SHEET.md \
  --out fixtures/knowledge_holdout.jsonl
```

（只有当你确认整表都填过之后才跑 `apply` —— 它有 `must_touch` 守卫，漏填会直接拒绝写回。）

## hq_0474 · gen_perf_0521 · Q7 冲突 2 处

查询 A：`情绪=压抑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0475 · gen_edit_0239 · Q7 冲突 2 处

查询 A：`情绪=压抑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0483 · gen_story_0237 · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=high；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=high,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0485 · gen_story_0027 · Q7 冲突 1 处

查询 A：`情绪=恐惧；强度=high；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0486 · cine_low_angle · Q7 冲突 1 处

查询 A：`情绪=恐惧；强度=high；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0487 · gen_story_0284 · Q7 冲突 2 处

查询 A：`情绪=恐惧；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0488 · gen_perf_0406 · Q7 冲突 2 处

查询 A：`情绪=恐惧；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=恐惧,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0503 · gen_story_0211 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=high；运镜=whip_pan_left`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=high,forbid_movement=whip_pan_left` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0504 · gen_edit_0075 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0509 · gen_perf_0494 · Q7 冲突 1 处

查询 A：`情绪=愤怒；强度=high；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0510 · gen_prod_0245 · Q7 冲突 1 处

查询 A：`情绪=愤怒；强度=high；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0512 · gen_perf_0040 · Q7 冲突 2 处

查询 A：`情绪=愤怒；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0513 · gen_perf_0111 · Q7 冲突 2 处

查询 A：`情绪=愤怒；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0514 · gen_perf_0513 · Q7 冲突 2 处

查询 A：`情绪=愤怒；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0515 · gen_story_0241 · Q7 冲突 2 处

查询 A：`情绪=愤怒；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=愤怒,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0517 · gen_edit_0026 · Q7 冲突 1 处

查询 A：`情绪=期待；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0527 · cine_move_whip_pan_left · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_left`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=whip_pan_left` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0528 · cine_move_whip_pan_right · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_left`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=whip_pan_left` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0529 · cine_move_whip_pan_left · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_right`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=whip_pan_right` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0530 · cine_move_whip_pan_right · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=whip_pan_right`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=whip_pan_right` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0531 · cine_dutch_angle · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0532 · gen_perf_0554 · Q7 冲突 1 处

查询 A：`情绪=混乱；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0538 · gen_axis_0285 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0539 · cine_move_dolly_in · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0540 · gen_edit_0009 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0541 · gen_edit_0012 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0542 · gen_edit_0131 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0543 · gen_perf_0077 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0544 · gen_story_0236 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0545 · gen_cine_0211 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=high；音效=低频轰鸣`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=high,forbid_sfx=低频轰鸣` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0554 · gen_edit_0128 · Q7 冲突 1 处

查询 A：`情绪=冷漠；强度=low；运镜=orbit_cw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0556 · gen_axis_0105 · Q7 冲突 2 处

查询 A：`情绪=压抑；强度=low；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0557 · gen_perf_0475 · Q7 冲突 2 处

查询 A：`情绪=压抑；强度=low；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0558 · gen_prod_0241 · Q7 冲突 2 处

查询 A：`情绪=压抑；强度=low；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=压抑,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0582 · gen_perf_0444 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=low；运镜=handheld；景别=CU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=handheld,forbid_shot_size=CU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0583 · gen_perf_0447 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=low；运镜=handheld；景别=CU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=handheld,forbid_shot_size=CU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0584 · gen_edit_0059 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=low；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0585 · gen_edit_0060 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=low；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0586 · gen_perf_0563 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=low；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0587 · gen_story_0286 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=low；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0591 · gen_story_0241 · Q7 冲突 1 处

查询 A：`情绪=平静；强度=low；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0595 · gen_perf_0432 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=low；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0597 · gen_edit_0194 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=low；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=low,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0598 · gen_edit_0209 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=low；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=low,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0599 · gen_perf_0505 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=low；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=low,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=讽刺,intensity=mid']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0603 · gen_axis_0288 · Q7 冲突 1 处

查询 A：`情绪=冷漠；强度=mid；运镜=dolly_in`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=冷漠,intensity=mid,forbid_movement=dolly_in` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0610 · gen_axis_0160 · Q7 冲突 1 处

查询 A：`情绪=压抑；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=压抑,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0617 · gen_perf_0469 · Q7 冲突 1 处

查询 A：`情绪=喜悦；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=喜悦,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0621 · cine_high_angle · Q7 冲突 1 处

查询 A：`情绪=孤独；强度=mid；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=孤独,intensity=mid,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0636 · gen_perf_0352 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0637 · gen_perf_0468 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0638 · gen_perf_0472 · Q7 冲突 2 处

查询 A：`情绪=平静；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=平静,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0645 · gen_comp_0161 · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=handheld`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=handheld` |

不该召回：`['EMOTION_PACK:emotion=冷漠,intensity=low,forbid_movement=orbit_cw']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0646 · cine_move_orbit_ccw · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=orbit_ccw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=orbit_ccw` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0647 · cine_move_orbit_cw · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=orbit_ccw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=orbit_ccw` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0648 · cine_move_orbit_ccw · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=orbit_cw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=orbit_cw` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0649 · cine_move_orbit_cw · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=orbit_cw`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=orbit_cw` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0650 · gen_edit_0206 · Q7 冲突 1 处

查询 A：`情绪=庄严；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=庄严,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0657 · gen_prod_0258 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；景别=CU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_shot_size=CU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0658 · gen_edit_0027 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0659 · gen_perf_0474 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0660 · gen_prod_0231 · Q7 冲突 1 处

查询 A：`情绪=悲伤；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=悲伤,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0668 · gen_story_0288 · Q7 冲突 1 处

查询 A：`情绪=期待；强度=mid；运镜=dolly_in`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=dolly_in` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0675 · gen_edit_0068 · Q7 冲突 2 处

查询 A：`情绪=期待；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0676 · gen_perf_0446 · Q7 冲突 2 处

查询 A：`情绪=期待；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=期待,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0678 · gen_story_0076 · Q7 冲突 2 处

查询 A：`情绪=混乱；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0679 · gen_edit_0157 · Q7 冲突 2 处

查询 A：`情绪=混乱；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |
| A | `EMOTION_PACK:emotion=混乱,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0685 · gen_edit_0137 · Q7 冲突 1 处

查询 A：`情绪=温柔；强度=mid；景别=ELS`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=温柔,intensity=mid,forbid_shot_size=ELS` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0688 · gen_prod_0141 · Q7 冲突 1 处

查询 A：`情绪=焦虑；强度=mid；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0689 · cine_move_steadicam · Q7 冲突 2 处

查询 A：`情绪=焦虑；强度=mid；运镜=steadicam`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_movement=steadicam` |
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_movement=steadicam` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0690 · gen_cine_0295 · Q7 冲突 2 处

查询 A：`情绪=焦虑；强度=mid；运镜=steadicam`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_movement=steadicam` |
| A | `EMOTION_PACK:emotion=焦虑,intensity=mid,forbid_movement=steadicam` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0691 · gen_story_0146 · Q7 冲突 1 处

查询 A：`情绪=荒诞；强度=mid；景别=ECU`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=荒诞,intensity=mid,forbid_shot_size=ECU` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0692 · cine_move_zoom_out · Q7 冲突 1 处

查询 A：`情绪=荒诞；强度=mid；运镜=dolly_in`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=荒诞,intensity=mid,forbid_movement=dolly_in` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

## hq_0697 · gen_perf_0359 · Q7 冲突 1 处

查询 A：`情绪=讽刺；强度=mid；运镜=固定`

| 族 | 必须边 |
|---|---|
| A | `EMOTION_PACK:emotion=讽刺,intensity=mid,forbid_movement=固定` |

不该召回：`['EMOTION_PACK:emotion=平静,intensity=low,movement=follow_subject,forbid_movement=handheld']`

**这条期望成立吗？**（查询里点名的取值，正是 must 那条边禁止的——引擎要能靠它拦住那个取值）

采纳 A ？ [ ]

<!-- 74/74 -->
