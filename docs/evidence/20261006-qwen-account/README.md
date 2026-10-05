# 第三方通道（qwen）**account 状态**实测：`Access denied ... account is in good standing`

日期 2026-10-06 01:37。**这是用户侧账号状态，不是本项目代码。**

## 时间线（都留了证据）

| 时刻 | 观测 | 证据 |
|---|---|---|
| 01:1x | `qwen3.8-max` 串行 2.4 s、**4 路并发全部 200** | 当时的连通性探针（本目录同批记录） |
| 01:33 | `select38` 跑完：E1 **0.2448**（47/192），但 **48/192 行的重排调用失败并降级** | `work/ab_e1_rerank/hybrid.rerank_select38.rep1.jsonl`（每行自带 `cases_rerank`） |
| **01:37** | **每一次调用都失败**（9 路并发 9 失败，统一 400） | `work/_probe_qwen_concurrency.py` 的输出（下） |

```
c-0..c-8 HTTP 400 {"error":{"message":"Access denied, please make sure your account is
in good standing. For details, see: https://help.aliyun.com/zh/model-studio/error-code#over...
```

## 含义（对 R3 路线的影响）

* 第三方（`qwen3.8-max`）**现在不可用**：不是模型白名单、不是并发限流（429），
  是**账号状态**（"in good standing"／链接指向欠费一类）。
* 因此第三方给的**质量路线第 1 步**（"强制 0/192 失败、重复 3 次、极差 ≤0.02"）
  **暂时做不了**——那一步正是要先修调用可靠性。
* **已经拿到的读数仍然有效、但带折扣**（必须与失败数一起引用）：
  `select38` = 0.2448，其中 **48/192 行是失败降级**（那些行退回未重排的前 3 条）。
  早前 0902 型号那两批（78/192、144/192 失败）**已标作废**。
* **不需要第三方的那条测量不受影响**：门线那一代案例层的 top-20 判分（deepseek ＋ glm）
  正在跑——它是第三方给 D13 的**可证伪触发器**（"v4 的 top-20 相关均值 ≥ 现役 ＋0.30
  且能回填 oracle 才考虑 B"）。

## 用户侧要做的一件事

把百炼账号恢复成"good standing"（充值／解除欠费），然后第三方通道与质量路线第 1 步即可继续；
`work/_probe_qwen_concurrency.py` 可以随时复验（一条命中即恢复）。
