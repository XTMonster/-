# 上游 LightRAG：接入面与实测事实（2026-10-05）

上游：`HKUDS/LightRAG`，许可 **MIT**，PyPI 包名 `lightrag-hku`。
本文件只记**在仓库里核过的事实**，不转述印象。

## 一、为什么单独留一份

计划 v4 要"真接入 LightRAG"（用户 U5），并把它的内部 LLM 换成 DeepSeek（用户 U10 的
适用范围："只针对用别人的方案"）。这两件事能不能同时成立，取决于一个具体问题：
**`only_need_context=True` 是不是等于"检索路径完全不调用 LLM"**。
答案是**不是**——实测如下。

## 二、实测（抓取 + 逐行定位，不是推断）

抓取命令（本机实跑）：

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/HKUDS/LightRAG/main/lightrag/operate.py `
    -OutFile work/upstream_lightrag/operate.py       # 299,930 bytes
```

| 事实 | 位置 |
|---|---|
| `only_need_context=True` 时，**在答案合成提示词渲染之前**就返回 context | `operate.py:4791`、`:7010`（注释在 `:6937`："only_need_context will return before this prompt is sent"） |
| **但关键词抽取在返回之前就已经调用过 LLM**：`extract_keywords_only` | `operate.py:5112` |
| 它把 `PROMPTS["keywords_extraction"]` 发给 `llm_model_func`，并要求 `response_format={"type":"json_object"}` | `:5157`（prompt）、`:5178`（`result = await use_model_func(kw_prompt, ...)`） |
| 查询主流程里先抽关键词、再建上下文 | `:5001`（`hl_keywords, ll_keywords = await extract_keywords_only(...)`）→ `:4770`（`_build_query_context`） |
| 答案合成那一步（`only_need_context` 时被跳过） | `:4907`、`:7066` |

## 三、对计划的直接后果（三条，都已写进裁决）

1. **`llm_model_func` 是检索路径的必要参数，不是可选装饰。** 它是 LightRAG 构造器的
   必要实参，检索时会用它抽关键词。所以：
   * 计划里 C3"只用检索端"的**措辞**不字面为真——准确说法是"**只取检索管线，丢弃答案合成**"；
   * C11"LightRAG 的 `llm_model_func` 改成 DeepSeek"**不是空操作**，正是用户 U10 要求的
     "沿用别家方案处的内部 LLM 用 DeepSeek"。
2. **E3（=0）的写法必须改**：关键词是模型生成的自由文本，会进入检索。按
   `PLAN_V4_LOOP2_DISPOSITION.md` 的 B.4(3)，下游只接受两类输入——
   `retrieve(...) -> Sequence[Case]` 的返回值，与**经闭集过滤后的关键词表**；
   闭集外的一切模型输出在进入下游前丢弃并计数。
3. **多了一个噪声源**：关键词抽取是 LLM 调用，会让"同一查询两次检索结果不同"。
   这正是 `B.1` 的"有效轮"必须写"成对 ＋ 降级计数＝0 ＋ 单一生产者"的原因之一；
   建议 P7 落地时把**关键词抽取的调用次数与输入输出也纳入 trace**（可判定、可复算）。

## 四、未核验（如实挂账）

* 上游 `lightrag.py`（主类）与 `kg/` 目录**没有逐行读**——本次结论只需要检索路径，
  上面点的行号都在 `operate.py` 里。
* **没有真的装上 `lightrag-hku` 跑过一次**（P7 才装）。上表的行号取自
  `main` 分支的 `operate.py`；P7 落地时必须按**实际 pin 的版本**复核这三处行号，
  并把版本号写进 `INDEX_MANIFEST.json` 的第一格（索引指纹已含该格）。
* 上游论文（Guo et al., 2024, arXiv:2410.05779）**没有读正文**；本文件只针对仓库实现。

---

## 五、**实跑 spike**（2026-10-05）：LightRAG 在本机**装得上、跑得通、全是本地的**

这是 U5（"真接入 LightRAG"）可行性的一次决定性验证——不是读文档推断，是真跑。

### 5.1 环境与命令

```powershell
python -m venv --system-site-packages work/_venv_lr      # 关键：让它看见系统的 torch
work\_venv_lr\Scripts\python.exe -m pip install --no-cache-dir lightrag-hku
$env:HF_ENDPOINT = "https://hf-mirror.com"               # 关键：见 5.3
work\_venv_lr\Scripts\python.exe work/_spike_lightrag.py
```

实测：venv 里 `lightrag 1.5.7` ＋ `torch 2.5.1+cu121`（`cuda True`）**并存**；
`lightrag-hku` 的依赖里**没有 torch**（清单见 `work/_pip_lightrag.log`），
所以"用 `--system-site-packages` 复用系统 torch"是可行而且省掉 2.5 GB 下载的做法。

### 5.2 结果（`work/_spike_lightrag.py` 的输出，逐字）

```json
{"torch": "2.5.1+cu121", "cuda": true, "lightrag": "1.5.7",
 "constructed": true, "init_s": 0.2,
 "insert": "ok", "query": "ok",
 "context_chars": 424, "elapsed_s": 8.0}
```

`query` 走的是 `QueryParam(mode="naive", only_need_context=True)`，拿回 **424 字符**的
真实检索上下文（"Document Chunks …"）。全程**没有云端 embedding、没有 API key**——
embedding 是我们注入的本地函数（`BAAI/bge-small-zh-v1.5`，GPU）。

### 5.3 踩到的两个坑（都是**必须写进实现**的硬要求）

1. **`embedding_func` 要 `EmbeddingFunc` 实例，不是裸函数。**
   传裸函数会报 `AttributeError: 'function' object has no attribute 'func'`
   （上游 `lightrag.py:1403` 读 `.func`）。正确写法：
   `EmbeddingFunc(embedding_dim=512, max_token_size=512, func=embed)`。
2. **必须设 `HF_ENDPOINT=https://hf-mirror.com`**，而且要在 **import transformers 之前**。
   不设的时候 `from_pretrained` 打 `huggingface.co`（本机**不可达**，实测超时
   `WinError 10060`），整条 LightRAG 管线随之崩：日志里能看到
   `IndexFlushError: NanoVectorDBStorage[chunks] index flush failed`、
   `Merging stage failed … unknown_source`、`Embedding func: Error in decorated function`。
   ⇒ **sidecar 启动脚本里这行环境变量是部署要求，不是可选项。**

### 5.4 顺带看到的一条（尚未处置）

`WARNING: Rerank is enabled but no rerank model is configured. Please set up a rerank
model or set enable_rerank=False in query parameters.` ⇒ 上游 1.5.7 的查询默认**想重排**。
计划 §3.3 里"重排用 DeepSeek"这条要么真的配上一个 rerank 实现，要么显式关掉——
**不能让它停在"启用了但没配"的警告状态**。

### 5.5 未核验

* 这次只插了 **1 篇文档**、跑的是 `naive` 模式；`local`/`global`/`hybrid` 三模式
  **没有逐个验**——但它们共用同一条 embedding 路径，风险已经落到 5.3 那两条上。
* **没有建 L3 的正式索引**（那要等 P6 的案例层）；本 spike 只验"能装、能跑、能检索"。
* 上游对 `llm_model_func`（此处是占位桩）在 `hybrid` 模式下关键词抽取的真实行为，
  仍以第二节的逐行定位为准；**没有在 spike 里跑通 hybrid**。
