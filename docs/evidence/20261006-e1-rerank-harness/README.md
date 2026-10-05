# 重排**装置**是好的：换成可靠模型后 **0/192 失败** ⇒ 之前那些失败是 qwen 侧的

日期 2026-10-06 02:02。**这是诊断，不是头条读数**（理由见下面的"打折"一节）。

## 为什么跑它

第三方给 R3 的质量路线**第 1 步**要求："固定 64 条查询的 top-20 候选，强制重排
**0/192 失败**、重复 3 次、极差 ≤0.02"。但 qwen 账号掉出 good standing 之后，
几跑 qwen 重排的失败行数一路涨（`order38` **111/192**、`score38` **96/192**、
`select38` **48/192**）。于是有个问题必须分清：

> 失败是**重排装置**本身不稳，还是 **qwen 那侧**（账号/限流）的事？

如果装置本身会掉调用，那么 qwen 恢复后照样跑不出 0/192。

## 命令（同一批 64 条冻结查询、同一语料层、同一 top-3 口径）

```powershell
python -u -m tools.knowledge.e1_panel --queries work/eval_sets/heldout_v4_long21.jsonl `
    --cases-dir work/knowledge_v4_cases --out work/ab_e1_rerank/diag.rerank_deepseek.jsonl `
    --top-k 3 --workers 3 --adapter none `
    --cases-rerank llm --rerank-retrieve-k 20 `
    --rerank-llm-provider deepseek --rerank-llm-model deepseek-chat --rerank-llm-prompt select
```

（封装脚本 `work/_run_rerank_diag.ps1`，低并发 `--workers 3`——**故意压低**，
否则高并发自身会制造限流失败，把诊断污染掉。）

## 读数

| 项 | 值 |
|---|---|
| 行数 | 192（64 查询 × top-3） |
| **每行的 `cases_rerank` 标签** | **192/192 都是 `deepseek-chat/select`** |
| **失败行数** | **0** |
| E1（两位评委均值 ≥4.0） | 50/192 = **0.2604** |
| 只 deepseek 评委 | 54/191 |
| 只 glm 评委 | 102/181 |

对照（同一语料层、同一 k=3 口径、**不重排**）：`reviews.hybrid.unfiltered.rep1.jsonl`
0.1927（ds 33/192、glm 61/179）与 `reviews.hybrid.top3.v4.ctl.jsonl`
0.1771（ds 32/191、glm 66/179）。

## 结论

1. **装置的 0/192 是做得到的** ⇒ 第三方第 1 步那条要求**不是**被装置卡住的；
   前述 qwen 各跑的失败是 **qwen 侧**（账号状态 / 限流 / 超时）。
   qwen 恢复后，第 1 步可以直接跑。
2. **重排这条杠杆**在**干净（0 失败）**条件下也把 E1 从 0.177～0.193 抬到 **0.2604**，
   而且**两位评委同向上升**（deepseek 33→54、glm 61→102）。

## 打折（务必一起引用）

* **同族**：这里用的重排器是 `deepseek-chat`，它**就是两位评委之一**。按本仓的纪律
  （第七次冻结的注释："重排器与两位评委都不同族，才排除'抬自己人'"），这个 **E1 数值
  不得当作"重排器质量"的证据**。本目录只是用它来读**失败计数**。
* 至于"两位评委同向上升"能不能抵消同族嫌疑——**未验证**：`glm-5.3` 与重排器不同族，
  它也从 61 涨到 102，这是**有利**证据；但两者的候选**不是同一批**（重排换了 3 条），
  所以不能直接与基准做因果推断。**干净的重排读数仍要等 qwen**。
* 只跑了 1 次（无重复跑）。
