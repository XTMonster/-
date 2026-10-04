# S2 前提复核：上游"抽取层"里**没有槽位超边** —— 按现文不可执行，需裁决

状态：**发现于动手做 S2 之前**（`PLAN_HYPERGRAPH_v3.md` §1 的 S2 行）。
日期 2026-10-05。**没有改动任何执行路径**（本批只落这份账）。

## 0. 复现（只读、可重跑；产物落在 gitignore 的 `work/upstream/`）

```powershell
$c='d587cdf8c3fe2be7719557f845324cb3a321f5e2'
$base="https://raw.githubusercontent.com/LHRLAB/HyperGraphRAG/$c"
Invoke-WebRequest "$base/LICENSE"                 -OutFile work/upstream/LICENSE
Invoke-WebRequest "$base/hypergraphrag/prompt.py"  -OutFile work/upstream/prompt.py
Invoke-WebRequest "$base/hypergraphrag/operate.py" -OutFile work/upstream/operate.py
```

| 文件 | 字节 | 行 | sha256 |
|---|---|---|---|
| `LICENSE` | 1,067 | — | `b54ba7ea027e607f865b42c7d617a4cbe03344e2a7e8f64b4fab3e8bf58a339e` |
| `prompt.py` | 28,929 | 351 | `2730b18d849641d9dedafad2374034bd5ed90d403402a1991ea0596e869b085e` |
| `operate.py` | 38,126 | 1,124 | `1302a1599fc3b98b9c1bbcbccf9553a093a048985fb36855c3d5e0a4a3da4160` |

（与 `work/upstream_files.json` 记的行数 351 / 1,124 一致 ⇒ 抓到的是同一个 revision。）

## 1. 计划 v3 的 ①b 写了什么

> **只取** `LHRLAB/HyperGraphRAG@d587cdf8c3fe`（MIT）的**抽取层**
> （`prompt.py` ＋ `operate.py::_handle_single_hyperrelation_extraction`），放**构建期**。

## 2. 实测：那一层产出的是**自由文本片段**，不是槽位超边

1. **提示词**（`prompt.py:13` `PROMPTS["entity_extraction"]`）只有一个两趟结构，
   第 1 步逐字是（`:18-21`）：
   > `1. Divide the text into several complete knowledge segments. For each knowledge segment, extract the following information:`
   > `-- knowledge_segment: A sentence that describes the context of the knowledge segment.`
   > `-- completeness_score: A score from 0 to 10 indicating the completeness of the knowledge segment.`
   > `Format each knowledge segment as ("hyper-relation"{tuple_delimiter}<knowledge_segment>{tuple_delimiter}<completeness_score>)`

   ⇒ "hyper-relation" 的载荷是**一句话**加一个 0–10 分。**没有类型、没有角色、没有槽位。**

2. **解析**（`operate.py:119-131`）：`record_attributes[1]` 就是那句话，
   `hyper_relation = "<hyperedge>" + 句子`，权重取最后一个字段。
3. **成员怎么挂上去**（`operate.py:92` ＋ `:103-110`）：`_handle_single_entity_extraction`
   要求 `now_hyper_relation != ""`，而 `:364` 把最近一条 hyper-relation 记进
   `now_hyper_relation` ⇒ 实体是**按记录流里的先后**挂到"最近的那句话"上的
   （**位置分组**），不是 allow/forbid/qualifier 那种**语义角色**。
   实体的 `entity_type`（`:98`）是模型给的**开放字符串**（大写化），不是闭集。
4. **合并**（`operate.py:134-164` `_merge_hyperedges_then_upsert`）：按**节点名（＝那句话）字符串相等**合并，
   权重相加、来源取并集。
5. `prompt.py` 的全部 PROMPTS 键（脚本枚举）：`entity_extraction`、
   `entity_extraction_examples`、`keywords_extraction`、`keywords_extraction_examples`、
   `rag_response`、`naive_rag_response`、`summarize_entity_descriptions`、
   `entiti_continue_extraction`、`entiti_if_loop_extraction`、若干分隔符常量。
   **没有** hyperrelation 专用提示词——那条记录是 `entity_extraction` 的第 1 步顺带产出的。

## 3. 与本仓数据模型的差距（逐字段）

本仓的真源是 `block_director/knowledge/hypergraph.py` 的
`HyperEdge(type, members[(role, kind, node_id)], source_kind, hardness, weight, confidence, source_span)`。

| 本仓有 | 上游有吗 |
|---|---|
| `type`（16 类闭集） | **无**（只有"自由文本片段"） |
| `role ∈ {allow, forbid, qualifier}` | **无** |
| `kind`（节点 18 类 ＋ qualifier 12 类闭集） | **无**（`entity_type` 是开放字符串） |
| 成员级依据（`source_span` / `member_quotes`） | **无**（只有 chunk 级的 `source_id`） |
| `source_kind` / `hardness`（理论 vs 经验、硬 vs 软） | **无** |
| 合并键 `(type, frozenset(members), source_kind, hardness)` | **字符串相等**（那句话本身） |
| 9 条校验门（成员 ∈ 闭集、禁忌必须有宿主、自相矛盾拒收…） | **无**（`len>=3` 即收） |

## 4. 为什么这就足以叫停"按现文执行 S2"

1. **S2 的两条谓词在槽位上定义，此处无法求值**（不是"难"，是**没有指称**）：
   * 填充率 `0 < r < 1`＝"必填槽位有多少被填上"——自由文本片段**没有槽位**；
   * 负例＝"一条**没有时序语义的边**必须**缺** `seq_phase`"——没有成员，也就无所谓"缺哪个键"。
2. **"片段 → 槽位超边"那层翻译，ADR-0014 已判定是自研**：
   "不许把『把上游的数据模型翻译成本项目的槽位模型』记成『复用』——那层翻译是自研"。
   照现文执行会把账记错（把自研记成移植）。
3. **反过来"照用"上游的表示是降级**：把句子当边、实体当成员之后，
   R011（禁忌必须进注入）／Q6b（n 元约束完整率）／Q7（禁忌拦截率）／E3（经验不得越权）
   全部依赖 `role` 与闭集 `kind`，在自由文本表示上**一条都判不了**。

## 5. 真正可复用／可借鉴的部分（如实分栏，不与上面混账）

* **可原样复用**（小、MIT、确定性、不含任何表示假设）：
  记录协议的那一小段——`<|>` / `##` / `<|COMPLETE|>` 三个分隔常量、
  `split_string_by_multi_markers` / `clean_str` / `is_float_regex`，
  以及 `operate.py:350` 的外层 `"(...)"` 剥离。
  **注意**：本仓已有自己的记录解析（`tools/kb_fetch/build_hypergraph.py` 的两段式），
  复用这一段的**唯一**收益是"多一套解析器"——所以它本身不构成做 S2 的理由。
* **可借鉴的**算法**（但必须按本仓 schema 自己实现，记账写"算法参考"）**：
  ① **先分段、再归属**的两趟结构：先切"完整知识片段"，再把该片段里的耦合归到片段上
  （本仓 v18 是一趟原子事实 ＋ 成员级 `quote`——**这一趟结构本仓确实没有**）；
  ② `completeness_score`（0–10）作为一个可用的**置信度输入**（与 `confidence` 对齐）；
  ③ "每条记录自带分数"的做法。
* **不可复用**：表示层本身（自由文本片段 ＋ 开放 `entity_type`）、合并键、以及任何
  "超边"语义。

## 6. 请裁决（三选一，后果都写清）

| 选项 | 内容 | 后果 |
|---|---|---|
| **A. 改 S2 的立法** | S2 从"移植上游抽取层"改为**"按本仓 schema 自实现：分段→归属两趟 ＋ completeness 置信度"**，上游只作**算法参考**（ADR-0014 的判例要求这样记账） | 谓词仍可用现文的填充率/负例（因为输出仍是本仓的槽位超边）；但**换了立法**，S2 的 ΔE1 对照臂要重述；`PROMPT_VERSION` 需要换代（`extract/v18` → `v19`） |
| **B. 先做影子语料，S2 押后** | 执行计划 §2 本来就把"S3 的证据生成"提到 S2 之前：先把现代语料在**影子路径**上建出来当**冻结评测集**，再决定 S2 的立法 | S2 的 ΔE1 从此有**同代**可比基线（现在没有）；代价是先花一轮语料工程 |
| **C. 放弃 S2** | 承认上游这一层对"白模预演的强耦合"没有可移植的信息，力气全放到 **S4（时序求解层）** 与 **S3（素材换代）** | 省一轮；但放弃的是"先分段再归属"这个本仓确实没有的结构 |

**我倾向 A 或 B，不倾向 C**：`completeness_score` 与"先分段再归属"是真的新东西，
且红队那句"两个 qualifier 是**标签不是约束**"打的是**求解侧**（S4），不是"分段"这一层。
但 A 是**改立法**，按纪律**不由我单方决定**。

## 7. 未验证（如实挂账）

* 我**没有跑任何试点抽取**：S2 的填充率与负例在现文下无法求值（§4），
  所以在裁决前**不产出读数**，也不写"跑了但没效果"这种含糊话。
* 上游**论文正文（NeurIPS 2025）没有读**；本结论只针对**仓库实现**
  （`d587cdf8c3fe` 的三个文件）。如果论文里另有槽位化实现而仓库没放出来，
  结论要按新证据修正。
* 上游 `hypergraphrag.py`（550 行）与 `kg/` 目录**没有逐行读**——结论不需要它们
  （抽取与合并都落在上面点名的两处），但这条如实记着，免得读者以为"全读过"。
