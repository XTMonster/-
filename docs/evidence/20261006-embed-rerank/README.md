# 嵌入重排（本地 `bge-small-zh-v1.5`，中文线索面）：**负结果**，0.0938 / 0.0833

日期 2026-10-06 07:11。命令（侧车 venv，torch+CUDA；同批查询/同语料 `48df4a53`/同评委/同深池）：

```powershell
work\_venv_lr\Scripts\python.exe -m tools.knowledge.e1_panel `
    --queries work/eval_sets/heldout_v4_long21.jsonl --cases-dir knowledge `
    --out work/ab_e1_rerank/embed.rerank.rep1.jsonl --top-k 3 --workers 4 --adapter none `
    --cases-rerank embedding --rerank-retrieve-k 50 --rerank-embed-model BAAI/bge-small-zh-v1.5
```

## 读数（原文 `reviews.embed_rerank.rep{1,2}.jsonl`，sha256 `0fc45c33…` / `f77180dc…`）

| 跑 | 官方口径 | 只 deepseek 评委 | 只 glm 评委 | 标签自述 |
|---|---|---|---|---|
| 1 | **0.0938**（18/192） | 0.0895 | 0.1596 | `embed:BAAI/bge-small-zh-v1.5+clue(fallback=excerpt)` |
| 2 | **0.0833**（16/192） | 0.0842 | 0.1746 | 同上 |

## 判定：**这条路（本地小模型 + 线索面余弦）不行**

把同一批查询上的几种做法并排（官方口径）：

| 做法 | E1 |
|---|---|
| **不重排**（k=50 的前 3 条） | 0.2188 |
| 嵌入重排（本目录） | **0.083～0.094** |
| LLM 重排（最好的 `select+clue`） | 0.4375～0.4479 |
| 完美重排上限 | 0.8438 |

⇒ 它**比不重排还差一半以上**，两位评委都低（0.08～0.17）。**不是一个可用的重排器。**

**为什么（推测，未验证）**：① 被编码的候选文本是**很短的中文线索**，`bge-small-zh-v1.5`
（512 维、~24M 参数）在这么短的文本上分不出"这条能不能指导这一镜"；
② 查询是**一整段镜头指令**（含景别/机位/运镜/构图/光线多要素），单一向量把它压成一个点，
与线索的点积丢掉了要素结构。**这两条都未做对照实验**。

## 还没试的（都要留档，别再重复本目录这条路）

### 追加（同日）：**零样本交叉编码器在深池上也是负结果** `0.1094`

`BAAI/bge-reranker-v2-m3`（`--cases-rerank cross-encoder --rerank-retrieve-k 50 --top-k 3`，
侧车 venv）：官方口径 **0.1094（21/192）**，只 deepseek 0.1211、只 glm 0.2448
（原件 `reviews.cross_encoder_deep.rep1.jsonl`）。

⇒ 与早先 k=20 那次（**0.1302**）一致：**零样本 cross-encoder 在"中文镜头指令 ↔ 英文摘录"
这件事上就是不行**（它是按"问答式段落相关"训的）。**但"微调过的" cross-encoder 还没试过**——
这正是 GPT-6A 会诊给的下一步（`docs/evidence/20261006-gpt6a-consult/`）。

* **换更强的嵌入器**：智谱 `embedding-3`（用户已有资源包）——D3 实测过"同一路由换云端嵌入器
  E1 提高约 **5.6 倍**"，但那是在 LightRAG 路由上测的，**没在"重排"这个位置上测过**。
* 被编码的文本换成 **摘录＋线索**（而不是只用线索）。
* **多向量/要素分解**（把查询按景别/机位/运镜拆成几个向量分别匹配）。
* `bge-reranker-v2-m3` 那条（cross-encoder）在 k=20 上已经测过是 **0.1302**（也是负结果）。
