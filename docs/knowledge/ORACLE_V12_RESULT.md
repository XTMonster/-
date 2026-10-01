# v12 oracle 落地后的**实测状态**（2026-10-01 21:05）

角色：独立验证（不是驱动方）。数据来源：`fixtures/knowledge_holdout.jsonl`
（**2437 条**，`glm_v12` 合并产物，链上第一次换代成功的 oracle）×
当前索引（766 边 / `extract/v10`）。

## 一、门（`tools/check_holdout.py`，与验收链同一套参数）

| 门 | 状态 | 相对旧 oracle |
|---|---|---|
| ① 总量 2437 | **pass** | — |
| ② 逐条格式 | **pass** | — |
| ③ 种子覆盖 | fail（只剩 **4 个取值**：`action=退场`、`delivery=喊叫`、`scene_type=action\|dialogue`） | 旧版 13 个取值 ＋ 22 个词表外取值 |
| ④ 边类覆盖 | fail（**只剩 `SOUND_PACK`**：18 对 / 上限 19） | 旧版 3 类 |
| ⑤ / ⑤b 禁忌 | **pass** | — |
| ⑥ 来源覆盖 | fail（**247 张卡**：27 张索引里零原子边 ＋ 220 张有边但没条目） | 旧版 72 张，但旧版的"覆盖"是靠**指向已不存在的边**撑起来的 |
| ⑦ 人审 | fail（机制已就绪，**复核尚未跑**） | 同 |
| ⑧ 换族 | **pass** | — |
| ⑨ 可达性 | **pass** | 旧版 fail |
| ⑩ 索引可解析 | **pass**（`must` 全部可解析：**0 / 4497**） | 旧版 `must 1047/5203` 解析不到 |

## 二、质量指标（`tools/holdout_score.py` / `tools/knowledge/quality.py`）

| 指标 | 线 | 旧 oracle | **v12**（本轮排序修复前 → 后） |
|---|---|---|---|
| Q1 top-1 | ≥0.70 | 0.6437 | 0.7974 → **0.8728** ✅ |
| Q2 top-3 | ≥0.90 | 0.7646 | 0.9774 → **0.9955** ✅ |
| Q3 负样本误命中 | ≤0.10 | 0.0 | 0.0 ✅ |
| Q4 required 检出 | =1.0 | 0.9892 | 0.9786 → **0.9957**（缺 11 对）❌ |
| Q6a 契约往返 | =1.0 | 1.0 | 1.0 ✅ |
| Q6b 成员完整 | =1.0 | 0.9986 | 0.9958 → **0.9993**（缺 3 处）❌ |
| Q7 禁忌拦截 | =1.0 | 1.0 | 1.0 ✅ |
| Q4_pre 索引同构 | =1.0 | **fail**（1047 条解析不到） | **pass（0/4497）** ✅ |
| E3 经验越权 | =0 | pass（**空集通过**） | **fail**（L2 层 0 条 → 测不到东西）❌ |
| E1 / E2 | — | not_measured | not_measured |

## 三、这一轮把 Q4/Q6b 从 0.9786/0.9958 拉到 0.9957/0.9993 的两处**语义缺陷**

（提交 `1c14bda`，`block_director/knowledge/hypergraph.py`）

1. **契约串的禁用半被解析器整段丢掉**：`6c82511` 给 forbid 配了查询键 `禁<键>`
   （`禁运镜=固定`），标注通道照它写 `q`，而 `parse_query` 只查 `QUERY_KEYS`
   —— 于是"不要什么"这半从来没进过检索器。新增 `parse_query_full()` 返回
   `(正向, 禁用)`，`parse_query()` 公开行为不变（既有调用点零影响）；
   `RetrievalTrace.forbid_seeds` 如实记录这次禁了什么。
2. **被禁的取值能顶替正向种子**：`_edge_coverage` 把 **forbid 成员**也算进覆盖，
   于是"禁构图=rule_of_thirds 的边"能被查询 `构图=rule_of_thirds` 满足 ——
   问的是三分法，答的是"不要用三分法"。这正是主导缺口的机制：那条查询在 oracle
   里重复 **34 次**，required 边每次都被这种边挤出 top-3。修掉后它在真实索引里
   排到 **第 1**（0.7329 vs 0.6598）。

## 四、剩下的**三个查询**（Q4 缺 11 对 / Q6b 缺 3 处）与根因

| 查询 | 重复 | 机制 |
|---|---|---|
| `转场=cut；节奏=long；对白=transition` | 3 | **种子稀释**：`转场=cut` 展开成 **7 个种子**（cut/dissolve/fade/whip/beat_type:transition/scene_type:transition/pacing:long），带 `dissolve` 的边覆盖 6/7 而带 `cut` 的边覆盖 5/7 → 分母被别的种子稀释 |
| `情绪=讽刺；动作=表情；机位=平视` | 6 | 同上：`情绪=讽刺` 展开出 `emotion:冷漠` 等 5 个种子，`冷漠` 的边一样覆盖 4/5，再靠 occurrences 胜出 |
| `情绪=荒诞；强度=mid` | 2 | 同上（`mid` 与更常见的 `high/low` 边同分竞争） |

**这是已知的硬尾巴**：`seeds_for` 的 docstring 记录了同样的机制（4928 条 `must` 里
71.9% 是"部分匹配"），并记录了两次被**实测证伪并回退**的修法。要动它必须做一次
`Q1/Q2/Q4/Q6b` 的**多目标**权重扫参，不能单点改——本轮没有动它。

## 五、剩余红门各自的**可执行**下一步

| 项 | 动作 | 量级 |
|---|---|---|
| ③ 种子覆盖 | `python -m tools.knowledge.gap_report` → `--only-values @work/gaps/gap_values.txt` | 4 个取值 |
| ④ 边类覆盖 | 同上 → `--only-types SOUND_PACK` | **1 对** |
| ⑥ 来源覆盖 | 同上 → `--only-cards @work/gaps/gap_cards.txt` | 220 张有边的卡（另 27 张是结构下限） |
| ⑦ 人审 | `python -m tools.holdout_review_llm --limit 150 …`（记录必须带 `source`，见 `1e9d614`） | `needs_human` 条 |
| Q4/Q6b | 需要一次多目标权重扫参（`seeds_for` 的种子稀释） | 11 对 / 3 处 |
| E3 | L2 经验层为空：要么补"条件→取舍"型来源，要么把这条记为"当前测不到"（已由 `6d4c178` 判 fail，不再空集通过） | 语料工作 |

`--only-cards` 那一轮**不会**碰 27 张零原子边的卡：它们在 schema 范围内没有可建模的
知识（逐张理由见 `GATE6_STRUCTURAL_FLOOR.md`）。
