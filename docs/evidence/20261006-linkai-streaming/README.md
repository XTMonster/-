# 流式绕开 Cloudflare 524：**"gpt6A 生成慢"不再是限制**

日期 2026-10-06 07:5x。用户指出「gpt6A 生成很慢，我觉得要给很多时间」——**对**，
而且这条已经找到真正的解法。

## 先说结论

**524 是 Cloudflare 边缘的等待超时（约 100 s），不是我们的客户端超时，也不是模型不行。**
解法不是"把 client timeout 调大"（那没用——超时在边缘那一侧），而是**让响应以流式回来**：
流式下**响应头立刻返回**、之后分块持续流动，边缘就不会判"源站没响应"。

## 实测（`work/_probe_linkai_stream.py`）

| 方式 | 结果 |
|---|---|
| 非流式（`stream` 不给） | **三次全 `HTTP 524`**（127 / 257 / 389 s）——`work/_panel_e1gap`、`_panel_e1gap2` 两份 usage 留证 |
| **流式（`stream:true`）** | **HTTP 200 ＋ `text/event-stream`；132.7 s 拿到完整正文**（266 个 chunk、正文 351 字符、思考 172 字符） |

同一条"要想一会儿"的问题，**非流式死在 100 s，流式跑满 132.7 s 还成功**。

## 落地

`tools/kb_fetch/llm.py::RelayClient`：

* 新增 `_stream()`（SSE 逐行解析：累加 `delta.content`、忽略 `reasoning_content`、
  收 `usage`、认 `[DONE]`）；
* **`chat()` 与 `chat_json()` 都默认先走流式**；流式这条路挂了才**退回非流式**（不许把一次调用判死）；
* `decode_tag` 里如实写 `stream=true`。

守门 `tests/test_llm_relay.py` 新增 3 条：① 默认请求流式（`stream:true` ＋
`Accept: text/event-stream`）且分块被拼起来；② 流式 JSON 走同一个解析器；
③ **流式挂了退回非流式**。

## 与之前那条"包线纪律"的关系（并更新）

前一份证据（`docs/evidence/20261006-gpt6a-envelope/`）写的是"包要小、答案要短"。
**流式之后这条不再必要**——现在**给它多少时间都行**。仍然成立的是：

* **不许**为绕任何超时去调低 `reasoning_effort`（那是静默降级）；
* 一次只问一件事仍然更好读——但那是**可读性**的理由，不是超时的理由。
