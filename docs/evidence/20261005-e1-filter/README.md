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

## 补二：**第三方 LLM 重排实测**——三条杠杆里唯一**把 E1 抬起来**的那条

命令（主环境；重排器＝第三方裁决通道 `qwen3.8-max-0902`，与两位评委**都不同族**）：

```powershell
python -m tools.knowledge.e1_panel --queries work/eval_sets/heldout_v4_long21.jsonl `
    --cases-dir work/knowledge_v4_cases --out work/ab_e1_rerank/hybrid.rerank_llm.rep1.jsonl `
    --top-k 3 --workers 3 --adapter none `
    --cases-rerank llm --rerank-retrieve-k 20 --rerank-llm-model qwen3.8-max-0902
```

| 杠杆 | E1 | deepseek 评委 | glm 评委 |
|---|---|---|---|
| 基准（BM25 ＋ 中文线索） | **0.1927**（37/192） | 0.172 | 0.318 |
| 产品自带 LLM 过滤 | 0.1720（27/157） ✗ | 0.140 | 0.376 |
| cross-encoder（bge-reranker-v2-m3，top-20） | 0.1302（25/192） ✗ | 0.135 | 0.240 |
| **第三方 LLM 重排（qwen3.8-max-0902，top-20→3）** | **0.2812（54/192）** ✓ | **0.240** | **0.542** |

> **⚠️ 型号更正与作废说明（2026-10-06）**：上表第 4 行用的型号 `qwen3.8-max-0902`
> 是**带日期的 snapshot**，用户 2026-10-06 更正为 **`qwen3.8-max`**（实测 0902 现在
> **403**、`qwen3.8-max` 200）。那一跑里有 **78/192 行**的重排调用失败并**具名降级**
> 回未重排的前 3 条（当时记的 27 行是只数了 `LLMError` 的一种写法）⇒ **0.2812 是"部分降级"
> 的读数**；同目录 `reviews.hybrid.rerank_select/score`（0:30 那两份）失败 **144/192 行**，
> **整份作废**。干净读数在 `hybrid.rerank_{order38,select38,score38}.rep1.jsonl`
> （同一型号 `qwen3.8-max`、同一批查询与评委）里重跑。

* **相对基准 +46%**（0.1927 → 0.2812）；**两位评委同向上升**（deepseek +0.068、glm +0.224）
  ⇒ 不是评委偏好：重排器（qwen）**与两位评委都不是同一族**，它不可能"抬自己人"；
* 27 行的重排调用失败（`cases_rerank: failed:LLMError`，第三方通道的限流/超时）——
  那些行**具名降级**回未重排的前 3 条；只用**重排成功的那 165 行**算，
  E1 = **0.2970** ⇒ 把失败率压下去还能再高一点；
* 三条杠杆的次序因此很清楚：**"让模型读懂中文指令↔英文摘录的关系"有效，"
  问答式 cross-encoder"与"在 top-3 上删行"都无效**。

**仍未达线**：0.2812 对 0.70 还差 2.5 倍。R3 的可达性结论写成两句：
① **后处理能抬 E1（+46%），但单靠它到不了 0.70**；
② 下一个该试的是**把"候选面"与"重排器"一起放大**（retrieve-k 20→50、
  重排失败重试、以及重排提示词的形状），以及**查询侧对齐**（把中文指令先译成
  语料的英文工艺说法再检索）——两条都在"语料/查询同层"这一族里。

## 补三：**查询侧对齐**（把中文指令改写成英文工艺词检索串）——**也降**

命令（判分查询仍是冻结的 64 条原文；只有**检索串**换成「原文 ＋ 英文改写」）：

```powershell
python -m tools.knowledge.e1_panel --queries work/eval_sets/heldout_v4_long21.jsonl `
    --cases-dir work/knowledge_v4_cases --out work/ab_e1_expand/hybrid.expand_union.rep1.jsonl `
    --top-k 3 --workers 3 --adapter none `
    --query-expand llm --expand-provider deepseek --expand-model deepseek-chat --expand-mode union
```

改写本身是**干净的**（样例：`extreme long shot, establishing shot, static tripod shot, 50mm,
dock market, Block 14, afternoon sunlight, diagonal light, row of stalls, …`），但

| 杠杆 | E1 | deepseek 评委 | glm 评委 |
|---|---|---|---|
| 基准 | **0.1927** | 0.172 | 0.318 |
| 查询侧对齐（union） | **0.1719** ✗ | 0.161 | 0.323 |

⇒ **把英文工艺词加进检索串反而稀释了**已有的中文线索面**（BM25 因此多召回了"英文词面像、
但讲的是另一回事"的案例）。**五条杠杆的账**（同一批 64 条冻结查询、同一批评委）：

| # | 杠杆 | E1 | 判定 |
|---|---|---|---|
| 0 | 基准（BM25 ＋ 中文线索） | 0.1927 | — |
| 1 | 产品自带 LLM 过滤 | 0.1720 | ✗ |
| 2 | cross-encoder 重排（top-20） | 0.1302 | ✗ |
| 3 | **第三方 LLM 重排（top-20→3）** | **0.2812** | ✓ **唯一有效** |
| 4 | 查询侧对齐（union） | 0.1719 | ✗ |

**可读的结论**：这条链上，"**让一个强模型读懂中文指令↔英文摘录的关系并重排**"是唯一有效的
杠杆；**任何"加更多词面"或"按问答相关性筛"的做法都降**。R3 的下一步只剩两件：
①把重排的**失败率**压下去（第三方额度已恢复）+ 把候选面放大（top-20→50）看上限；
②判 **top-20 的"完美重排"上限**（正在跑：`work/ab_e1_candidates/hybrid.top20.rep1.jsonl`）——
它一条就能判定"0.70 是否**结构上**可达"。
