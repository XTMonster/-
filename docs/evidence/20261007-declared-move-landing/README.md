# `declared.camera_move` 落字段：`movement` 那一族从"没得比"变成"能比"

日期 2026-10-07 02:2x。这是**同一裁决原则的直接应用**（轴族那份："批加字段，但只许照抄生成器
原生值；前置＝生成器今天已内部产出该值"）——`movement` 是成员最多的 kind（本次真跑 300 个），
属"第一批"无疑。

## 一、缺口（在真跑产物上量出来）

* 成片记录里**没有可比的运镜值**：`camera{}` 只有 `lens/name/position`；`declared{}` 有
  `technique`（剧本原话"固定镜头"）却没有归一化枚举；`movements[]` 全片只有 **1** 条。
* 于是诊断里 `movement` 的 **294/300** 个成员落进 `film_side_empty`
  （`docs/evidence/20261007-real-axis/execution_closure.json`）。
* 而**计划里那个值一直在**：`declared_camera_move` ∈ {`static` 63, `dolly_in` 1}
  （`docs/evidence/20261007-real-axis/audit_log.jsonl` 的 `plan_received`——replay 通路就是靠它拿整份计划）。

## 二、改了什么（一处，只抄不改名）

`block_director/delivery/manifest.py::_declared_payload` 增 `camera_move`：**原样抄**
`shot.declared_camera_move`；计划里没有就是 `None`（该 payload 的规矩是**全部可空**）。
诊断侧的绑定随之从**不存在的** `declared_camera_move` 改成 `declared.camera_move`
（`movements[].kind` 保留）。

守门：`tests/test_manifest_fields.py::test_the_delivery_records_the_plans_normalised_camera_move`；
golden 派生夹具按流程用 `tools/gen_golden.py` 重新生成（不是改断言）。

## 三、用真实数据验证（不必再跑一次真跑）

`work/_probe_declared_move.py` 拿 `20261007-real-axis` 的 `plan_received` 里的**真计划**建 manifest：

```json
{"plan_declared_camera_move": {"static": 63, "dolly_in": 1},
 "shots_json_declared_camera_move": {"static": 63, "dolly_in": 1},
 "match": true}
```

⇒ **逐项相等**，64 个值一个不差地进了成片记录。

## 四、影子分析：补上之后会发生什么（**预览，不是读数**）

把 64 个值补进**那次真跑的真实 `shots.json`**（不是从计划重建的 manifest——那样会把 `axis`
那一栏弄丢、别的桶就不可比了），再跑一遍诊断：

| 量 | 落字段前（真跑） | 影子分析（补上之后） |
|---|---|---|
| `movement` 的 `film_side_empty` | **294 / 300** | **0** |
| `movement` 的 `matched` / `unmatched` | 5 / 1 | **267 / 33** |
| 全部 `edge_field_absent` | **53** | **1**（只剩 `axis_side` 那一条） |

⇒ `movement` 从此**真的在比**。**下一次真跑**才给正式读数；本轮**没有**用影子结果更新任何指标。

## 五、未验证 / 边界

1. **影子分析不是读数**：它是"把计划里的值补进旧产物"的模拟，正式读数要等下一次真跑。
2. 这一栏抄的是**计划声明**的运镜，不是"这一镜实际动没动"——`movements[]` 才是实际写入关键帧的
   那一份（本次仍只有 1 条）。两者**不是同一个量**，绑定表里并列着读，别混用。
3. 与轴族那条一样：**只抄不改名、不翻译**；需要"约定"的东西（如 `left/right`）仍然不碰。
