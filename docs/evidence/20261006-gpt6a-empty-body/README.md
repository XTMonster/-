# GPT-6A 通道：**小包也会返回空正文**——根因是"思考把 completion 预算吃光"

日期 2026-10-06 18:2x。这是 `docs/evidence/20261006-gpt6a-consult-liveness/` 那一批
（18:22:17 发出去的三个"拆小包"问题）**失败**的证据与根因。

## 一、现象：三个小包全失败

`a_metric`（1.7 KB）／`b_closeout`（1.8 KB）／`c_arch`（1.3 KB），`--max-tokens 4096`，
`--provider relay`（`gpt-6-astra`，`reasoning_effort=max`）。三个都**返回空正文**，
各试 3 次（带退避），耗时几乎一样：

| 问题包 | 三次尝试的 `elapsed_s` |
|---|---|
| `a_metric` | 119.6 / 244.8 / 370.1 |
| `b_closeout` | 122.5 / 239.7 / 360.6 |
| `c_arch` | 120.0 / 243.6 / 366.3 |

错误正文（当时的控制台输出，`LLMError` 文案由 `tools/kb_fetch/llm.py:158` 产生）：

```
中转站没给出正文：[{"error": "LLMError: relay(gpt-6-astra) 返回失败：模型返回的空正文（内容可能全在 thinking 字段里）", "elapsed_s": 119.6},
                  {"error": "…", "elapsed_s": 244.8}, {"error": "…", "elapsed_s": 370.1}]
```

**操作失误（如实记）**：重发这四件时 `Start-Process -RedirectStandardError` **截断**了
原来那三个 `.err`，所以上面这段是我从当时的控制台读到的原文，**不是可再打开的原件**。
作为替代，本目录保留一份**同条件复现**：`probe_budget4096.*`（同 `a_metric` 包、
同 4096 预算）——它给出的是同一个失败的**可引用原件**。

## 二、根因（代码路径，逐条可核）

1. `tools/relay_consult.py::consult` 调 `client.chat(..., num_ctx=max_tokens, ...)`
   ⇒ relay 通道上 **`num_ctx` 就是 `max_tokens`**（OpenAI 兼容的 completion 预算）。
2. `reasoning_effort` 默认 **`max`**（`tools/kb_fetch/llm.py:113`；用户明令"思考强度拉到最大"）。
3. 正文被抓空时 `tools/kb_fetch/llm.py:158` 抛"模型返回的空正文（内容可能全在 thinking 字段里）"。
4. 本仓**早有同形记录**（`tools/kb_fetch/llm.py:48-50`）：开思考时 `max_tokens=32768`
   ⇒ **思考 6.5k–6.9k token ＋ 正文 12–14k 字符**；**`max_tokens=16384` 会截断**。
   ⇒ **4096 这个预算连思考本身都不够**，所以正文必然是空的。

同一形状的更早记录：`docs/evidence/20261006-kimi-rerank/`——`kimi-k3` 有 7 条
`模型返回的空正文（内容可能全在 thinking 字段）`，处置也是**加完预算**而不是降思考。

## 三、处置

**不许**为绕这个去调低 `reasoning_effort`（那是静默降级，本仓明令禁止）。
正确的做法是**加完成预算**：四个问题（全面评审包 ＋ 三个视角包）全部按
`--max-tokens 32768` 重发，脚本 `work/_run_gpt6a_aspects2.ps1`；
复现探针**保留 4096** 作对照。

## 四、与 P14-247 的关系（"慢"这条规律要分两半）

`docs/evidence/20261006-gpt6a-consult-liveness/` 记的是"**大包慢到不可用**"（17.5 KB → 64 分钟无输出；
1.2 KB 那份跑了 65 分钟无输出）。本目录补上另一半：**小包不是"慢"，是"空"**——
它在 ~2 分钟内就回来了，只是**没有正文**。两者是**不同的失败模式**，
合起来才解释得清"为什么小包也没出结果"。

## 五、未验证

* `--max-tokens 32768` 是否**足够**让这四个问题出正文——18:3x 刚重发，**结果未知**。
  按 `llm.py:48-50` 的既有读数，32768 的正文量级 12–14k 字符，而本批问题都要求
  ≤400–800 字，理论上余量充足；但**未实测**。
* 中转站是否对这个型号的 `max_tokens` 有**上限截断**（例如实际按 16384 处理）——未测。
