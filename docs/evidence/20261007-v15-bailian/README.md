# `20261007-v15-bailian` — 引擎真跑改用**阿里云百炼**的 qwen3.8-max-0902：根因不是通道，是 `tool_choice`

用户 2026-10-07："试试看用 qwen 的阿里云百炼，一样是 qwen3.8max0902"。这一份记两件事：
**① 为什么中继/百炼都会 502**（真根因），**② 修好之后引擎真跑在百炼上跑通了**。

## 1. 根因：思考模式拒收 `tool_choice=required`，而 sidecar 把任何上游非 2xx 都翻成 502

两次"计划调用 0.7 s 就 502"的现场（中继 `docs/evidence/20261007-v15-relay-502/`、
百炼第一次尝试）都不是超时、不是额度，而是**上游的 400**：

```
GET/POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
  model = qwen3.8-max-0902
  messages = <插件真实计划提示>  tools = [emit_plan]  tool_choice = "required"

<400> InternalError.Algo.InvalidParameter:
      The tool_choice parameter does not support being set to required or object
      in thinking mode
```

插件发的正是 `tool_choice="required"`（`block_director/contracts/transport.py:229`）；
`tools/sidecar_server.py` 的 `do_POST` 把 `TransportError` 一律翻成 **502**
（`sidecar_server.py:444-445`），所以插件那侧只看到"sidecar 返回 502"。
**思考模式与"强制工具调用"在这家上游互斥。**

复算（直接打百炼，不走 sidecar）：

```
python - <<'PY'
import json, os, urllib.request, urllib.error
body = {"model": "qwen3.8-max-0902", "stream": False,
        "messages": [...], "tools": [...], "tool_choice": "required"}
PY
  -> HTTP 400 InternalError.Algo.InvalidParameter（同一条消息）
```

## 2. 修法：sidecar 新增 `--tool-choice-mode`（默认 passthrough，逐字节不变）

`tools/sidecar_server.py::_openai_body`：

| 模式 | 行为 |
|---|---|
| `passthrough`（**默认**） | 原样透传 `tool_choice` —— 历史配置一个字节都不变 |
| `auto` | 只把 `required`／对象改写成 `auto`（`auto`/`none`/具名函数原样透传） |
| `drop` | 整格不发 |

为什么保思考而不是保 `required`：用户 2026-10-07 的指令是"**思考强度拉到最大**"，
所以这里保思考、把"必须调工具"交给提示词（驱动的 `plan_attempts`/`draft_invalid`
仍然守着"没调工具就重问"）。测试：`tests/test_sidecar_retrieve.py::test_tool_choice_translation_is_opt_in_and_provider_local`。

## 3. 百炼上的两个实测（都影响以后怎么用它）

| 事实 | 实测 |
|---|---|
| 模型 id | **`qwen3.8-max-0902`** 可用；`qwen3.8-max` 被这枚 key 的范围挡掉（403 access_denied） |
| 思考旋钮 | `reasoning_effort` 与 `enable_thinking`＋`thinking_budget` **都认**，但**同时发会 400**（`cannot be set simultaneously`）；短问题实测 reasoning token：裸 497 / `effort=max` 466 / `enable_thinking+32k` 434 ⇒ 这个部署**默认就在想**，旋钮不改变量级 |
| **非流式** | 10 k 字符的裁决题包：**26 分钟不返回**（进程 CPU 0.1 s，挂在 read 上） |
| **流式** | 同一题包：**1.0 s 回第一个 chunk、605 s 拿完整正文**（6469 个 chunk）⇒ 与 GPT-6A 那次同形（`docs/evidence/20261006-linkai-streaming/`）；`tools/glm_consult.py` 因此加了 `GLM_STREAM=1` 的 opt-in 流式通道 |

## 4. 引擎真跑

* `docs/evidence/20261007-v15-6shot-bailian/`：6 镜真跑（sidecar → 百炼，
  `--reasoning-effort max --tool-choice-mode auto`）。它证明**引擎这条路在百炼上通**
  ——中继那 6/6 次 502 是 `tool_choice` 这一格，不是"qwen 不能做引擎"。
* 长剧本那一跑的落库证据仍走 DeepSeek：百炼在思考档下单次调用要 1–10 分钟，
  64 镜会远超墙钟预算（那一跑的用途是"长路径 + Q5/E2 运行侧"，不是比谁的模型好看）。
