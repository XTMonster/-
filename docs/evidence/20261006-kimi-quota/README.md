# Kimi 通道**已停用**：账号余额不足被挂起（`exceeded_current_quota_error`）

日期 2026-10-06 05:45。这不是代码问题，是**账号状态**。

## 原始回包（逐字，直接调 `POST /v1/chat/completions`）

```json
{"error":{"message":"Your account org-40ba69f60d3543b788f381d8d5dc5809 <ak-fd3yswyhswci11gfg5mi>
is suspended due to insufficient balance, please recharge your account or check your plan and
billing details","type":"exceeded_current_quota_error"}}
```

HTTP **429**。

## 它解释了哪条读数

顺序静默探针（16 条查询、无并发）在**发货代**池子上跑重排：
`ok=0 / failures=16`，**16 条全是同一条 429**（见 `work/_quiet_shipped.out`）。

⇒ `work/ab_e1_rerank/kimi.current.rerank.rep{1,2,3}.jsonl` 里那 **165/159/162 行降级**
（约 85%）**就是这条 429 造成的**——所以那三个"E1 0.2135/0.2188/0.2083"是**退回未重排前 3 条**
的基准，**不是重排读数**（P14-215 已判作废，现在有了具名根因）。

**为什么 v4 那三跑是好的**：`kimi2.rerank_select.rep{1,2,3}` 跑在 04:00 前后，
当时账号还有余额；05:11 的发货代那批撞上了余额耗尽。

## 处置（与用户 2026-10-06 的指示一致）

用户已说"**kimi 那部分用不了就用 gpt6A**"＋"**gpt6A 只能用于人工裁决和执行计划书写，
其他的用 glm 和 DeepSeek**"。所以：

* **人工裁决** → 中转站 GPT-6A（`reasoning_effort=max`）：212 条的重跑**正在进行**；
* **其余**（评委、重排器）→ **只许 GLM / DeepSeek** ⇒ 重排那条通道接下来要用
  `--rerank-llm-provider deepseek|glm`（**注意**：这两个族**同时是评委**，
  所以它们的重排读数带"同族自证"的折扣，这一条要在证据里写清）。
* Kimi 客户端与守门**保留**（`--provider kimi`）：余额恢复后仍可用，
  历史那 212 条判词与 v4 三跑读数也都是它出的、写着 `kimi-k3`。

**未验证**：余额充上之后 429 是否消失（没有充值，无法复验）。
