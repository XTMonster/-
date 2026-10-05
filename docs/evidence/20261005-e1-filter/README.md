# R3（E1 ≥ 0.70 的可达性）：**产品自带的过滤器实测**——它在这批查询上是反选择的

日期 2026-10-05。命令逐字：

```powershell
python tools/knowledge/e1_panel.py --queries work/eval_sets/heldout_v4_long21.jsonl `
    --cases-dir work/knowledge_v4_cases --out work/ab_e1_filter/hybrid.filtered.rep1.jsonl `
    --top-k 3 --workers 3 --adapter none --cases-filter llm --filter-model deepseek-chat
```

（过滤器判据＝**产品 sidecar 那份提示词**，`tools/sidecar_server.py::CASE_FILTER_SYSTEM`，
经单一真源 import；`--cases-filter` 是本次新加的缝，第五次显式重新冻结。）

## 读数（同一份 64 条冻结查询、top-3、评委 deepseek-chat ＋ glm-5.3）

| 配置 | 行数 | 相关（两位评委均值 ≥4） | E1 | 只用 deepseek 评委 | 只用 glm 评委 |
|---|---|---|---|---|---|
| 未过滤（现行 hybrid） | 192 | 37 | **0.1927** | 33（0.1719） | 61（0.3177） |
| 加产品过滤器 | 157 | 27 | **0.1720** | 22（0.1401） | 59（0.3758） |

* 过滤器丢掉 **35 行**，其中 **10 行是相关的**；
* ⇒ 被丢行的相关率 **28.6%** ＞ 基线相关率 **19.3%**——**反选择性**（它删相关行比删无关行更狠）。
* 两位评委方向相反（deepseek 评委 0.172→0.140 降；glm 评委 0.318→0.376 升），
  但**官方口径是两位取均值**（0.1927→0.1720，**下降**）。

## 为什么这条重要（R3 的"不可达信号"第一次被量化）

E1 是**精确率**，分母 ＝ 返回行数。从 27/157 走到 ≥0.70，过滤器必须**一条相关行都不丢**、
同时再丢掉 ~118 行无关行 ⇒ 需要 **≈91% 的无关行识别率 ＋ 100% 的相关行召回**。
换句话说：**在 top-3 结果上"再过滤"这条路上，0.70 不可达**——
要动的是"**哪 3 条被返回**"（更宽的候选 ＋ 重排），而不是"返回之后删几条"。

## 未验证／下一步

* 只跑了 1 次（`rep1`）。噪声带约 0.0156（同批两条 BM25 臂的极差），
  两条口径的差 0.0207 略大于它——**方向可信、幅度待重复**。
* 下一步（按《模型分工契约》先会诊再执行）：**先取宽候选（top-k=20）再用 cross-encoder
  重排取 3**，候选模型已过许可证检查（`BAAI/bge-reranker-v2-m3` apache-2.0、
  `Qwen/Qwen3-Reranker-0.6B/4B` apache-2.0；jina v2 是 cc-by-nc ⇒ 出局）。
  会诊包：`work/_q_e1_lever.md` ＋ `work/_reuse_check.out`。

## 补：**retrieve-then-rerank 实测**（同日，第二条杠杆）

命令（在 sidecar 的 venv 里跑，CUDA 可用；模型 `BAAI/bge-reranker-v2-m3` apache-2.0）：

```powershell
work\_venv_lr\Scripts\python.exe -m tools.knowledge.e1_panel `
    --queries work/eval_sets/heldout_v4_long21.jsonl --cases-dir work/knowledge_v4_cases `
    --out work/ab_e1_rerank/hybrid.rerank20.rep1.jsonl --top-k 3 --workers 3 --adapter none `
    --cases-rerank cross-encoder --rerank-retrieve-k 20
```

| 配置 | 行数 | 相关 | E1 | deepseek 评委 | glm 评委 |
|---|---|---|---|---|---|
| 未过滤（基准） | 192 | 37 | **0.1927** | 33（0.172） | 61（0.318） |
| LLM 过滤（产品自带） | 157 | 27 | **0.1720** | 22（0.140） | 59（0.376） |
| **cross-encoder 重排（top-20 → 3）** | 192 | 25 | **0.1302** | 26（0.135） | 46（0.240） |

**两条"后处理"杠杆都让 E1 下降**（过滤 −0.021、重排 −0.063），而且**两位评委方向一致**
（重排：deepseek 0.172→0.135、glm 0.318→0.240）⇒ 不是评委偏见。

**这条为什么可信**：`cross-encoder/ms-marco` 系重排器是按"**问答式段落相关**"训的，
而这里的查询是**200 字的中文镜头指令**、候选是**英文学术摘录**——跨语、跨形状，
它排出来的序**不如**BM25 在中文线索面上的序。⇒ 换重排器（多语/LLM 排序）
**值得再试一轮**（LLM 排序那一轮已在进行：`--cases-rerank llm` 走第三方 `qwen3.8-max-0902`，
与两位评委都不同族，见第七次冻结）。
