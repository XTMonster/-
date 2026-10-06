# 执行闭环诊断 v1：**"0 条违规"不是"成片守规矩"，是"绝大多数边根本判不了"**

日期 2026-10-06 23:5x。裁决依据：人工裁决通道 **GLM-5.3** 的 F2
（`docs/evidence/20261006-channel-fallback/glm53.answer.json`）——
**③ 先诊断、不设门**；先做能**精确映射到成片字段**的 kind，**绑不到的 kind 进"未映射"桶并计数**
（`axis_side` 那批**不许当违规报**）。

工具：`tools/knowledge/execution_closure_report.py`（`--run <运行目录> --edges <索引> --out <json>`）。
"这一镜注入了什么"**只从 `audit_log.jsonl` 的 `retrieval_call` 事件读**（`data.edge_ids`），
**不读** `shots.json` 的自述——§4.1b 硬规则 2。

## 一、判定顺序（照裁决写死，防假阳性）

1. 这条边里**只要有一个成员的 kind 映射不到成片字段** ⇒ **整条边判不了**（`edge_indecidable`），
   记进未映射桶，**绝不当违规**。为什么：本仓实测过"按直觉补 forbid 校验"当场产生假阳性
   （66 条全来自 `axis_side`）。
2. 否则先看**全部前提**（非 `forbid` 成员）是否与成片取值**精确匹配**：不匹配 ⇒ 这条边对这一镜
   **不适用**（`edge_inactive`），`forbid` 不判违。
3. 前提全中 ⇒ 这条边**生效**（`edge_active`）；此时 `forbid` 的值出现在成片字段里才算**违规**。

映射表 v1（**只收能精确对上的三个 kind**）：`shot_size→shot.shot_type`、
`movement→declared_camera_move ＋ movements[].kind`、`intent→intent_type`。

## 二、在真实运行上的读数（`docs/evidence/20261006-long21/`，64 镜）

```powershell
python tools/knowledge/execution_closure_report.py --run docs/evidence/20261006-long21 `
    --out docs/evidence/20261006-execution-closure/report.long21.json
```

| 量 | 值 |
|---|---|
| 有注入的镜头 | **64**（`retrieval_call` 67 条，其中 3 条在镜头建成前／scope 不对） |
| 看过的前提成员 | **380** |
| 边**不适用**（前提不匹配） | **224** |
| 边**判不了**（有成员 kind 映射不到成片字段） | **95** |
| 边**生效**（前提全中） | **1** |
| 生效边上被检查的 `forbid` 成员 | **0** |
| **违规** | **0** |

**未映射的 kind（按出现次数）**：`pair 63`、`axis_side 63`、`axis_topic 63`、`lens 19`、
`headroom_policy 19`、`composition_rule 13`、`camera_angle 13`。

**成片侧的实际取值域**：`shot_type` {MS 79, MCU 68, CU 32, LS 30, MLS 16}、
`intent_type` {推进 72, 铺垫 32, 收束 31, 停顿 28, 对抗 18, 留白 17, 转折 12, 回望 8, 揭示 4, 压迫 3}、
`movements[].kind` {`dolly_in` **4**}、**`declared_camera_move` 空**。

## 三、怎么读（**不许读过头**）

* **"违规 0" 与"成片守规矩"是两回事**：生效的边只有 **1** 条，而它**没有** forbid 成员；
  真正该被检查的那些边，**95 条判不了、224 条不适用**。本次读数支持的**唯一**结论是
  **"这套语料与成片字段之间的可判定性极低"**，不是"知识没被违反"。
* **可判定性缺口有名字**：24 个 kind 里只有 **3** 个能映射到成片字段；而这 3 个里
  `movement` 映射到的两个字段几乎都是空的（`declared_camera_move` 全空、
  `movements[].kind` 64 镜只有 4 处）——这与 **E2 = 0/64**（没有一条运镜来自经验/案例层）
  是**同一件事的两面**。
* **反过来说**：这也解释了为什么"按直觉补 forbid 校验"会出假阳性——前提都没对齐，
  拿 `forbid` 单边去比就是在比两个不同的词表。

## 四、这是诊断，不是门

* **没有 pass line**，产物里明写 `"note": "诊断，不设门…"`；
* **没有接进** `tools/run_tests.ps1` 的通过与否（照 `tools/ab_triple_baseline.py` 的形态）；
* 判据/阈值/分母一个字没动；**没有**因为这次读数改任何产品代码。

## 五、未验证 / 边界（如实挂）

1. **只跑了 1 次运行**（`20261006-long21`）——换运行/换语料未测。
2. 映射表 v1 **只有三个 kind**；其余 21 个 kind 要成为可判定，需要 `APPLICABILITY_SEMANTICS_v1.md`
   那份**逐 kind 适用域语义表**先落成可执行的东西。
3. `axis_side` 等未映射 kind 的**语义**（它该绑到成片的哪个字段）**没有**被本轮回答——
   本轮只把它诚实地记进"判不了"。
4. 违规判定用的是**字面相等**（剥 `kind:` 前缀后），没有做中英词表对齐；
   `movement` 一侧已经能看到词表落差（知识写 `movement:固定`，成片写 `dolly_in`）。
