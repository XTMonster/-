# S2 立法：裁决记录（v1）

状态：**开工前的立法裁决**。S2 的原文「移植上游抽取层」按现文不可执行（见
`S2_UPSTREAM_PREMISE.md`）；这份记录把**前提的独立复核**、**两侧判词**与
**可执行的下一步**放在一处，供裁决与后续记账。

## 1. 前提：我自己把引用逐条复核过（证实，不是转述）

复核命令（只读，可重跑）：`work/upstream/` 是 gitignore 的草稿区，
`docs/knowledge/S2_UPSTREAM_PREMISE.md` §0 记了抓取命令与三份文件的 sha256。

| 前提里的断言 | 复核结果 |
|---|---|
| `prompt.py:18-21` 让模型切"完整知识片段"，记录形如 `("hyper-relation"{sep}<一句话>{sep}<完整度>)` | **证实**：`:18` `Divide the text into several complete knowledge segments`、`:19` `knowledge_segment: A sentence…`、`:20` `completeness_score: A score from 0 to 10`、`:21` 给了那条格式 |
| `operate.py:119-131` 把**那句话**当超边 | **证实**：`:122` `knowledge_fragment = clean_str(record_attributes[1])`、`:128` `hyper_relation="<hyperedge>"+knowledge_fragment`；`:125` 权重取最后一个字段 |
| 实体**按记录流先后**挂到"最近的那句话"（位置分组，不是语义角色） | **证实**：`:92` 要求 `now_hyper_relation != ""`；`:103-110` 直接 `hyper_relation = now_hyper_relation`；`:364` 每读到一条 hyper-relation 就刷新它 |
| `entity_type` 是**开放字符串** | **证实**：`:98` `entity_type = clean_str(record_attributes[2].upper())` |
| 合并键是**节点名字符串相等** | **证实**：`operate.py:134-164` `_merge_hyperedges_then_upsert` 以 `hyperedge_name` 取值／并集 |
| `prompt.py` 里**没有** hyperrelation 专用提示词 | **证实**：全部 `PROMPTS` 键枚举后只有 `entity_extraction`／`entity_extraction_examples`／`keywords_extraction(_examples)`／`rag_response`／`naive_rag_response`／`summarize_entity_descriptions`／`entiti_continue_extraction`／`entiti_if_loop_extraction`／`similarity_check`／`fail_response` ＋ 分隔常量 |
| 「照用上游表示是降级」：R011／Q6b／Q7／E3 全依赖 role 与闭集 kind | **证实（抽样）**：`tools/knowledge/quality.py:601` 的 E3 硬门逐字是 `[m for m in edge.members if str(m.role) == "forbid"]`；自由文本片段上没有 `role`，该门的分母只能是 0 |
| 本仓 v18 是**一趟**原子事实 ＋ 成员级 `quote`，没有"先分段再归属" | **证实**：`tools/kb_fetch/build_hypergraph.py` 的 `SYSTEM_PROMPT` 规则 0b／1／6b 是"一批卡 → 一条调用 → 直接吐 members ＋ 每条成员的 quote"，全篇没有"先切片段、再把片段里的耦合归到片段上"这一趟 |

**结论**：`S2_UPSTREAM_PREMISE.md` 的每一条指称都站得住；S2 按现文确实无法求值。

## 2. 两侧判词（联合会诊，四栏记账）

* 包：`work/_q_s2.md`（问题）＋ `work/_s2_brief.md`（事实摘要）＋ 三份源码行段。
  逐份 sha256 见 `work/_panel_s2b/bundle.manifest.json`；两侧 usage：
  `deepseek-chat` 2,434 in / 3,592 out；**`glm-5.3`（level=low，max_tokens=65536）
  2,420 in / 51,436 out，其中 reasoning 44,052，elapsed 576.2 s，`finish_reason=stop`**。
* 归属：`reviewed_by: llm-panel`（不是 human）。
* **第一次提问作废，如实记**：以 `--max-tokens 32768` 发问时 **GLM 侧
  `finish_reason=length`、正文为空**（32,768 个 completion token 全烧在 reasoning 上，
  实测 32,631）——按契约"一侧缺席不算同意、空正文不许读成同意"，压小 bundle
  （16,656 → 4,236 字符）并把上限提到 65,536 后重问。**这一条同时是对
  `tools/kb_fetch/llm.py::GLMClient` 档位纪律的又一次实测**。

### 2.1 四栏

| 栏 | 条数 | 内容 |
|---|---|---|
| `both`（两侧都提） | 0 | — |
| `severity_conflict` | 0 | — |
| `glm_only` | 8 | A 立法／两趟差异是待验证假设／取值域不许猜／负例落法／**我的摘要证据不足**／`hypergraph.py` 注释已成假／A 的验收不许押评委臂／completeness→confidence 对齐 |
| `deepseek_only` | 6 | 上游无槽位 ⇒ 谓词无指称／"翻译"按 ADR-0014 属自研／取值域必须由 S2 定义／负例要机器可判／completeness 要归一化并留原值／两趟差异要写进文档 |

**两侧的实质结论一致：走 A**（GLM 逐字"立法选 A"；DeepSeek 侧把"照现文不可行"
与"必须自研"写成 blocker）。**没有分歧需要人裁**——分歧只在颗粒度：
GLM 给了落地形状，DeepSeek 复述了约束。按《模型分工契约》，**方案以 GLM-5.3 侧为主**。

### 2.2 判词的逐条**证实 / 证伪**（在仓库里做，不是转述）

| # | 判词 | 复核 |
|---|---|---|
| ① | 应立法为 **A**（自实现两趟 ＋ completeness 置信度；上游仅算法参考） | **采纳**（两侧一致，且 §1 的引用逐条证实） |
| ② | 两趟 vs v18 一趟的差异有三项（提取单元／决策分解／溯源粒度），"提高召回"是**假设** | **证实其形状、纠正其表述**：三项差异在 §1 末行证实；"提高召回"确实**未被实测**——改为由 pilot 的双臂**成员级**召回对照定案，不作结论 |
| ③ | `seq_phase`／`carry_shots` 取值域"不许猜，唯一权威来源＝计划 v3 的 S4 节" | **部分证伪**：`rg -n "seq_phase|carry_shots"` 全仓只有**解释性注释**（`hypergraph.py:270`：`seq_phase`＝这一镜在段落推进里的位置；`carry_shots`＝效果还要带几镜）与"延后"标记，`PLAN_HYPERGRAPH_v3.md` 的 S4 行只讲阈值 T 与衰减，**没有枚举**。⇒ 不是"誊录"，是 **S2 必须定义并写明推导依据**。这条纠正必须记，否则落地时会去找一份不存在的清单 |
| ④ | "无时序语义 ⇒ 缺 `seq_phase`"落成 `TEMPORAL_EDGE_TYPES` 伴生常量 ＋ 四例测试 | **采纳**：内容属性确实不可直接机判；且它点出的边界（**时序型边缺 `seq_phase` 不算违例**，那正是 `0<r<1` 允许的缺失）与 v3 的谓词 ③ 不冲突 |
| ⑤ | 我的摘要"本仓 v18 是一趟原子事实"**证据不足**（包内没有 v18 提示词原文） | **证实（对包而言）**：包里的确没放 `SYSTEM_PROMPT`。**但结论本身成立**——我在仓库里逐条读过（§1 末行）；处置＝把 v18 原文的位置与差异表写进 S2 文档（见 §3 的 A1） |
| ⑥ | `hypergraph.py` 的注释"值的生产者是 S2 的上游抽取层"已成**假**，须同 commit 改掉；并把惰性键的可见性哲学延伸到**取值域** | **证实并已落地**：见 §3 的 P14-106 |
| ⑦ | A 的验收不许押评委臂（E1 两臂分不开、评委噪声 6%） | **证实**：见 `20261006-e1-baselines/`（Δ 0.0078 < 极差 0.0365；每 16 行翻 1 行）。⇒ 验收只许用机器可判量 |
| ⑧ | completeness→confidence：冻结单调映射 ＋ 显式缺失态，**禁止上游的 1.0 回退**；先查 `confidence` 规格 | **证实规格**：`block_director/knowledge/hypergraph.py:512` `confidence: float = 0.7`、`:513` `confidence_max: float = 0.7`，且 `:1298` 它是**排序权重**（`SCORE_WEIGHTS["confidence"]`）——所以映射表必须冻结 ＋ round-trip 钉住，否则它会**悄悄改排序**。上游 `operate.py:125` 的 `else 1.0` 回退正是不许照抄的那一处 |

## 3. 已落地的第 0 步（P14-106）与后续阶段

### 3.1 已落地：判词 ⑥ 指出的**同形洞**（`hg/v2+e70870ea3034` → `hg/v2+1a90c089bb8f`）

S0 修的是"闭集没进缓存指纹"，这一批是**同一形状、深一层**：`VALUE_DOMAINS`
（门⑨ 的取值面）、`REQUIRED_MEMBERS`（必填缺一即拒收）、`OPTIONAL_MEMBERS`
（`forbid` 槽位白名单）**同样决定"收不收"**，却都不在第六格的载荷里。
后果与 S0 那次的现场一模一样：**S2 要做的第一件事（给 `seq_phase` 填取值域）
会静默命中旧批次**——模型从未被要求产出那些取值，而一切照绿。

* 改法：`schema_fingerprint()` 的载荷补上这三组（`None` 作为"**故意**不设枚举"的
  显式状态照原样序列化，与"这一格不存在"区分开）。**闭集本身一个字没动**
  （`QUALIFIER_KINDS` 仍是 12 个、`EDGE_TYPES` 仍是 16 个），所以指纹移动
  **只能**来自覆盖面变大。
* 守门（`tests/test_hypergraph_determinism.py`，4 条新用例）：三组**各自**都要有
  鉴别力（改任一组 ⇒ 指纹必须变，撤回必须复原）；并有一条**用途**证明——
  填 `seq_phase` 的取值域**当场**换代；`tests/test_qualifier_lazy_keys.py` 的
  代际字面量按"S1a 那代要有人签字"的约定同步更新（签字记在该用例的 docstring 里）。
* 记账：本条**不碰任何判据/门限/阈值**，只动缓存钥匙的覆盖面；发货索引仍**故意**
  没有重签（§98.3 的警示原样有效，等 S1a＋S2 同批的重建）。

### 3.2 后续阶段（A 的落地形状，占位——**未开工**）

| 阶段 | 产出 | 机器可判的验收 |
|---|---|---|
| **A1 差异入档** | S2 文档里放**指令级差异表**（提取单元／决策分解／溯源粒度）＋ v18 提示词原文位置 | 表里每一项都能被 `文件:行号` 指到；"v18 没有分段这一趟"由**在库里读到的原文**支撑（不再靠摘要） |
| **A2 冻结取值域** | `VALUE_DOMAINS["seq_phase"｜"carry_shots"]` 填上闭集 ＋ **推导依据**（上游 completeness 语义 ＋ S4 的消费契约），并把取值域**渲染进提示词** | 填上后 `schema_version_with_fingerprint()` **必须变**（P14-106 已把它变成硬事实）；提示词里出现取值域 ⇒ `PROMPT_VERSION` 换代 ⇒ `--check` 断言**旧 key 命中数 == 0** |
| **A3 两趟抽取** | pass1 只切"完整知识片段"＋打完整度、pass2 只做归属并保留**成员级 quote**；`segment_id` 进 trace | 负例：**非时序型边带 `seq_phase` 必须被拒**（`TEMPORAL_EDGE_TYPES` 之外的边）；正例：时序型边缺 `seq_phase` **不**算违例（`0<r<1`）；填充率 `0<r<1` 且 `r=0／1` 都判可疑 |
| **A4 对齐 confidence** | 冻结单调映射 `completeness(0–10) → [0,1]`，缺失落**显式 missing**，trace 保留原始分 | round-trip 用例；**禁止** `else 1.0` 回退（上游 `operate.py:125` 那一处）；映射改了要有人签字 |
| **A5 pilot 对照** | 在**同一冻结评测集**上做两趟 vs 一趟的双臂对照 | 只测**机器可判**量（成员级召回/精确、填充率、违例数）；**不**用 E1 评委臂当验收（判词 ⑦） |

**仍未裁决的**（这是留给人的，不是我单方能定）：A5 的"成员级召回/精确"金标从哪来、
以及 B（影子现代语料当冻结评测集）要不要**先**做——判词把它们压在 A5 之后，
但 A5 没有金标就落不了地。
