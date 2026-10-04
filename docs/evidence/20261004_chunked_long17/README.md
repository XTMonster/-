# long17：修复工具与主构建器**同一份解算**之后的第一次 64 镜真跑

**结论**：`state=DONE`、场景建成、交付 **133** 个文件、终审**逐镜通过 33/64**
——这是 long9 以来最好的一次真跑（long14 29、long15 29、long16 23）。但这一页
**不拿总分当证明**：长跑之间方差本来就大（同一条命令、同一后端，long14 与 long15
都是 29，long16 却是 23）。真正的证明是**修复回合的产出结构**，见下一节。

## 这一趟是什么

| 项 | 值 |
|---|---|
| `run_id` | `2ac8f25023c9` |
| 剧本 | `fixtures/script_long_61.md`（64 镜 / 4584 帧） |
| 通道 | sidecar `127.0.0.1:8765` → DeepSeek `deepseek-chat` |
| 结果 | `DONE`、`built=true`、交付 **133** 个文件（含 64 支分镜 mp4 ＋ 合片） |
| LLM | **277** 次调用（上限 552）、工具 **348** 次、检索 **67** 次 |
| 代码基线 | `c1e1fdb`（P14-84：修复工具走 `place_shot_camera`） |

复算：

```
python work/_repair_yield.py docs/evidence/20261004_chunked_long17/runs/audit_log.jsonl
python tools/extract_run_evidence.py --run-id 2ac8f25023c9 \
    --out docs/evidence/20261004_chunked_long17 \
    --audit-log docs/evidence/20261004_chunked_long17/runs/audit_log.jsonl \
    --llm-trace docs/evidence/20261004_chunked_long17/runs/llm_trace.jsonl \
    --knowledge-trace docs/evidence/20261004_chunked_long17/knowledge_trace.json \
    --shots docs/evidence/20261004_chunked_long17/export/shots.json
```

## 这一页真正要报的：**动手的修复回合第一次修对了**

`work/_repair_yield.py` 把每个修复回合拆开，看它调了哪些工具、有没有**成功执行**
改动类工具、以及复核回来之后那一镜有没有通过。两跑同口径对照：

| 修复回合 | long16（修前） | **long17（修后）** |
|---|---|---|
| 回合数 | 104 | 104 |
| 回合内工具调用 | 204 | 211 |
| **改动类**调用 | 9（`setup_camera` 5 ＋ `emit_shot_draft` 4） | 7（`setup_camera` 6 ＋ `reframe` 1） |
| **动了手**的回合 | 7 ⇒ **0 个通过** | 7 ⇒ **6 个通过** |
| 只读回合的平均构图分变化 | **−2.65** | **−0.39** |

根因在 `c1e1fdb` 里写清楚了：`setup_camera` / `reframe` 以前自己抄了一份机位解算，
丢了主构建器有的六样东西（§10.4 视线留白、§六十九 头顶留白、`spec.room` 钳制、
逐镜轴侧、时间点、声明式运镜）。拿**计划自己的参数**重设一次机位，long16 里
**34/64 镜构图更差、10 镜由通过变不通过**（`reframe` 是 9 / 3）。也就是说：
修复回合里"动手"的那些，**本来就在把镜头改坏**。同一份探针在修后跑四份冻结工程
× 两个工具 × 64 镜 = **512 次重设全部零差**（`docs/evidence/20261004-tool-vs-builder/`）。

## 四跑对照（终审逐镜，同一份剧本、同一条命令）

| 跑 | 逐镜通过 | COMPOSITION | R001 | R003 | R011 | 构图中位 | 构图门 ≥70 | LLM | 工具 |
|---|---|---|---|---|---|---|---|---|---|
| long14 | 29 | 24 | 13 | 6 | 1 | 77.3 | 40 | 291 | 200 |
| long15 | 29 | 25 | 25 | 6 | 1 | 74.3 | 39 | 272 | 200 |
| long16 | 23 | 28 | 41 | 7 | — | 72.0 | 36 | 319 | 442 |
| **long17** | **33** | **16** | **27** | **1** | — | **85.6** | **48** | 277 | 348 |

**读法**：long17 每一项都是四跑最好，且方向与"修复不再把镜头改坏"一致；但
long14→long16 的波动说明**单一跑次不足以证明因果**，所以这一页的主张只到
"structural fix 落地 ＋ 修复产出变好"，**不到**"总分变好是它的功劳"。

## 这一跑顺带暴露的下一刀（已在本轮修掉，见 §八十）

104 个修复回合里 **97 个一个改动类工具都没调**，其中 **72 个**恰好是
`search_knowledge` ＋ `get_scene_state` 两次只读调用。根因不是模型懒：

* 修复回合只有**一轮** LLM（`tool_choice=required`，但只要求"调一个工具"）；
* 而 `driver.repair_messages` 是一张**只写不读的草稿单**——`_dispatch_tool_calls`
  把工具观测写进去，**从来没有人把它发回模型**。

于是"查资料 + 看场景"把唯一一轮用光，模型连自己刚查到的观测都看不见。
long17 的 `loop_warning` 有 **174** 条、`shot_degraded` **43** 镜，正是这条的
下游。修法与守门见 `ACCEPTANCE_STATUS.md` §八十。
