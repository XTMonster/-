# 执行闭环诊断 v2：把"相等式"的 kind 从 **3 个扩到 7 个**，并第一次量出**词表落差**

日期 2026-10-07 00:3x。裁决依据不变（GLM-5.3 F2：**先诊断、不设门**）；
这一步做的是 `docs/knowledge/APPLICABILITY_SEMANTICS_v1.md` **第四节"第一步"**点名的那批：
**只做相等式的 kind**（`shot_size` / `movement` / `intent` / `lens` / `vfx` / `action` / `transition`），
②③ 类先在报告里**显式列为未纳入**。

工具：`tools/knowledge/execution_closure_report.py`（`--run … --out …`）。

## 一、绑定表（每个 kind 对着成片的哪个字段）

| kind | 成片侧字段 | 归一化 |
|---|---|---|
| `shot_size` | `shot_type` | — |
| `intent` | `intent_type` | — |
| `lens` | `camera.lens` | `35mm` / `35` / `35.0` ⇒ 同一个 |
| `movement` | `movements[].kind` ＋ `declared_camera_move` | — |
| `action` | `action_types[]` | — |
| `transition` | `declared.transition` ＋ `transition_in/out` | — |
| `vfx` | `vfx[].type` | — |

## 二、这一轮**被注入的到底是什么**（先把语料摊开，免得读错结论）

`docs/evidence/20261006-long21/` 的 67 条 `retrieval_call` 一共注入 **344 条边**，
只有 **4 种类型**：`INTENT_PACK 243`、`AXIS_RULE 66`、`SHOT_PATTERN 22`、`STAGING_PACK 13`。
成员 kind 的分布：`movement 329`、`shot_size 290`、`intent 243`、`pair 66`、`axis_side 66`、
`axis_topic 66`、`lens 22`、`headroom_policy 22`、`composition_rule 13`、`camera_angle 13`。

> 复算：`docs/evidence/20261007-execution-closure-v2/probe_injected_members.py`。
> **注意**：`action` / `transition` / `vfx` **一次都没被注入**——所以它们在这份证据里是
> `no_data`（**没数据**），不是"没有违规"。

## 三、逐边判定（判定顺序照裁决写死，防假阳性）

| 量 | 值 |
|---|---|
| 有注入的镜头 | 64 |
| 看过的前提成员 | 380 |
| 边**判不了**（有成员 kind 映射不到成片字段） | **95** |
| 边**不适用**（前提不匹配） | **224** |
| 边**生效**（前提全中） | **1** |
| 生效边上被检查的 `forbid` 成员 | **0** |
| **违规** | **0** |

未映射的 kind：`pair 63`、`axis_side 63`、`axis_topic 63`、`headroom_policy 19`、
`composition_rule 13`、`camera_angle 13`。（`lens` 已经从"判不了"里**移出**——它现在有绑定。）

## 四、**新量出来的东西：词表落差**（`vocabulary_gap`）

只判等还不够——要先问"两边是不是在说同一种话"：

| kind | 状态 | 知识侧取值（前几个） | 成片侧取值 | 交集 |
|---|---|---|---|---|
| `shot_size` | **重叠** | CU / ECU / ELS / LS / MCU / MLS / MS | CU / LS / MCU / MLS / MS | 成片的 5 个全中 |
| `intent` | **重叠** | 停顿/压迫/回望/对抗/推进/揭示/收束/留白/转折/铺垫 | 同左 | 10/10 |
| `lens` | **重叠** | 35.0 / 50.0 | 50.0 / 85.0 | `50.0`（归一化生效） |
| `movement` | **部分重叠** | `dolly_in` / `dolly_out` / `push_through` / `zoom_in` / **`固定`** | `dolly_in` | 只有 `dolly_in` |
| `action` / `transition` / `vfx` | **`no_data`** | — | — | 本轮**没有被注入** |

⇒ **两件事同时成立**：① `shot_size`/`intent` 这两条通道**真的能判**（词表是同一个）；
② `movement` 只有**部分**能判——知识侧还写着 `固定` 这种中文取值，而成片侧是英文枚举
（`dolly_in`）。这不是"成片没违反"，是**两边词表没对齐**。

## 五、顺手抓出并修掉**我自己工具里的两个 bug**（都写成了守门）

1. **只归一了一边**：`lens:35mm`（索引）撞不上成片的 `35.0`，真违规会被记成 `no_match`
   ——**漏判比假阳性更隐蔽**。修法：比较时**两边都过 normalizer**；
   守门 `test_lens_values_are_normalised_before_comparison`。
2. **词表统计写在判定的 `continue` 之后**：于是只有"生效"的那条边被统计，
   `action`/`transition`/`vfx` 一起变成空集合、看着像"没问题"。修法：注入即统计；
   守门 `test_the_vocabulary_counters_cover_every_injected_edge_not_just_active_ones`。

（两条都是"**报告看起来更干净**"的错误，方向都是**让结论显得更好**——所以必须由守门钉住。）

## 六、这是诊断，不是门

没有 pass line、**没有接进** `run_tests.ps1` 的通过与否；判据/阈值/分母一个字没动；
**没有**因为这次读数改任何产品代码。守门 10 条（`tests/test_execution_closure_report.py`）。

## 七、未验证 / 边界（如实挂）

1. **只有 1 次运行**（`20261006-long21`，64 镜）：`action`/`transition`/`vfx` 三条通道
   **本轮零数据**，换一次运行才谈得上它们。
2. **②类（成片里没字段）与③类（话题/标注）仍未纳入**：`emotion`、`intensity`、`beat_type`、
   `lighting`、`music`、`sfx`、`delivery`… 报告只保证了"①类里能判的都判了"，
   **不等于**整个执行闭环被覆盖。
3. `movement` 的中英词表**没有**做别名映射（`固定` ↔ `static` 之类）——本轮只**量**出落差，
   **没有**替它编一份词表（那要么是新的判据，要么得先有 schema 层面的决定）。
4. `composition_rule` / `pacing` / `camera_angle` 属"区间/阈值"型，按提案**需要新判据**，
   本轮**没做**（要动先得裁定）。
