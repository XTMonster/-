# 杠杆 A 在**交付位**上的真判分读数：云端 `embedding-3` 重排**更差**

日期 2026-10-06。回答 `docs/knowledge/E1_LEVERS_v1.md` 的**杠杆 A**：
"换一条更好的**去标签**候选生成（云端嵌入重排），红线够不够得着"。

## 这一条为什么值得量

* 判据是 `E1 ≥ 0.70`（＝**≥135/192 行**），而它的依据 0.7448 是**按标签**取 top-6 的池子上搜出来的
  ⇒ 选择器**不许看判分**，只能用**去标签池**，而那条池子的上界实测只有 **0.375**（8 条盲判）。
* `docs/knowledge/OPEN_PROBLEMS.md` P3 记着：本地 `bge-small-zh` 做重排是**负结果**，
  但**云端 `embedding-3` 没在"重排位"试过**（D3 只在 **LightRAG 路由**上量过 ~5.6 倍的提升）。
  ⇒ 它是当时**唯一没被证伪的正向杠杆**。

## 命令（可复算）

```powershell
# 两条臂并行；密钥在**这个 shell**里从 HKCU 读进环境，子进程继承
#（2026-10-06 那次"仪器坏了"的事故正是子进程没有 key）
powershell -NoProfile -ExecutionPolicy Bypass -File work\_launch_cloud_arms.ps1
```

每条臂的实际命令（`work/_e1_cloud_arm.py`）：

```
python -u work/_e1_cloud_arm.py --workers 5 --retrieve-k 20 --tag k20 --out docs/evidence/20261006-e1-cloud-embed/reviews.k20.jsonl
python -u work/_e1_cloud_arm.py --workers 5 --retrieve-k 50 --tag k50 --out docs/evidence/20261006-e1-cloud-embed/reviews.k50.jsonl
```

**尺子没有重写**：`e1_panel.judge` / `summarise` / `rerank_cases` / `score_queries` 全是**导入**的；
同一批 64 条查询、同两位评委、同 C=3 语境、同阈值 4.0、同一条线 0.70。
唯一换掉的是"**由哪个不看判分的重排器挑那 3 条**"（经**冻结的缝** `score_queries(rerank=…)` 注入），
编码器是 `tools/kb_fetch/embedding_cloud.py`（离线单测 13 条，缺 key／额度／维度不符一律具名抛错）。

## 读数（逐字取自 `work/_cloud_k20.out` / `work/_cloud_k50.out`）

| 臂 | 取宽 | 重排标签 | 判分条数 | 相关 | **E1** | 判分语境 | 尾部丢弃 | 只有一位评委的行 |
|---|---|---|---|---|---|---|---|---|
| `k20` | 20 | `cloud:embedding-3+clue` | 192 | 32 | **0.1667** | `judge_batch=3` | 0 | 3 |
| `k50` | 50 | `cloud:embedding-3+clue` | 192 | 22 | **0.1146** | `judge_batch=3` | 0 | 8 |
| （对照）现役认证版 | 3 | — | 192 | 34 | **0.1771** | `judge_batch=3` | 0 | — |

同批离线 proxy（`../20261006-pool-depth-ceiling/`，只用银行里已判过的分）：
三面里最好的"标题＋摘录＋中文线索" **0.1667** vs "检索原序" **0.1562**（只 +0.0105），
离"按标签取 top-6"的 0.8177 差一个量级。

## 判定：杠杆 A **在上界位与交付位两处都被否**

1. **上界位**：换云端嵌入重排**不抬高**去标签池的上界（proxy 只 +0.0105；同深度的 ceiling 与检索原序一字不差）。
2. **交付位**：真判分下 k20 **0.1667**、k50 **0.1146**，**都低于现役 0.1771** ⇒ 不是"不够好"，是**更差**。
   （k50 更差这点很合理：取宽到 50 条之后，重排器被要求在一次调用里把 50 条排明白——本仓已实测
   "一次看太长的清单"本身就是弱点。）
3. ⇒ 杠杆 A **不值得再花 1h50m 真判**；红线的事回到裁定通道（现在是 **GLM-5.3**）。

## 未验证／边界（如实挂）

* **这是原型不是冻结仪器**：上面的数字是**方向读数**——要当官方 E1，必须把云端嵌入这条路
  **升进 `e1_panel.load_embedder`** 并**单独提交一次重新冻结**后再跑。本目录**不**声称官方读数。
* 只试了"**原样余弦 + 中文线索**"这一种用法；线索的加权／改写／多线索聚合**没试**。
* `judge_incomplete_rows` = 3（k20）／8（k50）：这些行只有一位评委给分，按 P14-249 **留在分母、不算相关**
  ——方向不受影响，但如实记。
* 两个 `.jsonl` 是**逐行打分文件**（每行含 `case_id`／`score`／`judge_batch`／指纹），可直接用
  `tools/knowledge/quality.py --e1-reviews` 复算。
