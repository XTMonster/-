# P14 验收度量可信化 · 执行方案（/root lane）

依据：`改进执行文档v1.4.md` §2.3（检索四步／校验门／Q6b 前置①）、
§4.1（RK-13 的 Q0–Q7 分子/分母/k）、§4.1b（两条硬规则 ＋ 分母下界表 ＋
held-out 覆盖门）、§B.5（对抗性测试）、协议 `fixtures/knowledge_holdout.protocol.md`。

## 0. 全量审查后的现状（都是本轮实测，不是引用旧文档）

基线：`python -m pytest -q` **全绿**（1070+ 项）；`git log` 头三笔 =
`985c423 / 845f622 / 4fd18a8`。

| 实测项 | 命令 | 结果 |
|---|---|---|
| held-out 规模 | `fixtures/knowledge_holdout.jsonl` | **4539 条 / 5043 条 `must`** |
| 覆盖门 | `python tools/check_holdout.py …` | ①–⑥、⑤b、⑧ pass；**⑦（人审）fail** |
| 质量指标 | `python tools/holdout_score.py` | Q1 0.117（线 0.70）／Q2 0.221（线 0.90）／Q3 0.018 pass／**Q4 恒真**／Q6a pass／Q6b 0.717（线 1.0）／Q7 pass |
| `must` → 索引边的可解析率 | `work/p14_resolve_probe.py` | **1323 / 5043 = 26.2%**；最近邻差 1 个 `kind=取值` 的 1632 条、差 2 个 1053 条 |
| Q2 的**天花板** | `work/p14_ceiling_probe.py` | `must` 能进候选集的 query 只有 1277/4539 → **ceiling_Q2 = 0.2813** |
| 目标边在候选集里的排名 | 同上 | `rank_of_must` 中位数 = **1**（排序基本没问题） |
| 违反标注规则 0（`q` 覆盖不到自己的 `must`）的条目 | `work/p14_reach_probe.py` | **1183 条 / 1247 条 must spec**（4031 条用旧 prompt sha `82b341…`，508 条用 `14fcba3c…`） |

**结论**：Q1/Q2/Q6b 现在量到的低值，主因不是检索排序，而是
**oracle 与索引不同构**（`must` 指向索引里不存在的边 ⇒ 这些条目从分母里被静默丢掉）。
而 `tools/holdout_score.py` 的 **Q4 是 `_metric("Q4", required_total, required_total, 1.0)`**，
即**分子恒等于分母**——按 §4.1b 硬规则 2（禁止自证）与规格 §4.1 line 831
（`Q4 = 命中的 required_hyperedge_ids 数 / Σ_q |required(q)|`）都是错的。

## 1. 本 lane 的落点（与并行 lane 不重叠）

并行 lane：`modern_sources`（语料增长／`kb_fetch`）、`modern_notes_visual`
（held-out 重标 · prompt `holdout/v10`）。**本 lane 只做"度量与门"，不碰语料与 oracle 生成。**

| 阶段 | 落点 | 动作 |
|---|---|---|
| **A** | `tools/holdout_score.py` | ① Q4 改成规格口径 `Σ_q|required(q) ∩ top-k(q)| / Σ_q|required(q)|`（k=3），保留分母下界；② 把"`must` 解析不到索引边"从**静默丢弃**改成**计入报告并判失败**（§2.3 Q6b 前置①："若某 query 的 required 边在归并后确实不存在，则索引构建失败"）；③ 新增 `tests/test_holdout_score.py` 对抗用例（把 required 边挤出 top-k → Q4 必须红；不可解析的 must → `passed` 必须假） |
| **B** | `tools/check_holdout.py` | 新增**构建期覆盖门⑨**（`∀must/never/top1: ∃ 索引边 满足 norm_key 相等`），由 `--nodes/--edges` 驱动；索引缺失 → `not_measured`（硬规则 1：不得判通过）；报告不可解析条目与示例。对抗用例：自造一对值 → 门⑨ 必须红；与索引一致 → 绿 |
| **C** | `tools/check_holdout.py` 门② | 把标注规则 0 变成**机器检查**：`must` 里每个**有查询键**的槽位必须逐字出现在 `q` 里（这正是"协议写了、机器没查"的那条）。对抗用例：`must` 有 `lens=50mm` 而 `q` 不写 `镜头=50mm` → 必须红 |
| **D** | `docs/evidence/<run-id>/`、`AGENTS.md`、`.scratch/v1.5/` | 落全量复跑证据；如实写"Q1/Q2 未达标 + 人审⑦ 未完成"，**不粉饰** |

## 2. 自我审核（先于动手，逐条反驳自己）

| # | 可能的反对 | 处置 |
|---|---|---|
| 1 | "Q4 改成真实口径＝改判据" | 不是。规格 §4.1 line 831 白纸黑字写着"命中的 `required_hyperedge_ids` 数 / `Σ_q |required(q)|`"，现状是**实现偏离规格**。修的是实现，不是线（线仍是 100%，分母下界仍是 1200）。 |
| 2 | "把不可解析的 must 判失败＝新加严" | 规格 §2.3 Q6b 前置① line 850-854 明写"若某 query 的 required 边在归并后确实不存在，则**索引构建失败**（不留给 P14-4 去发现）"。现状是**静默丢掉**，等于把分母做小——正是硬规则 1/2 要堵的洞。 |
| 3 | "门⑨／规则 0 会让现有 4539 条 fixture 直接变红" | 是，而且**本来就该红**：1323/5043 才解析得上、1183 条查询够不着自己的 must。这正是并行 lane 正在用 `holdout/v10` 重标的原因。门变红不会让任何既有测试变绿，只会把真实缺陷暴露出来。 |
| 4 | "会不会打红既有断言？" | 已逐条核对：`tests/test_check_holdout.py` 的 `valid_records()` 用 `q_for()` 从 spec 派生 `q`，天然满足规则 0；门⑨ 需要给它一个合成索引（测试夹具改造，属"测试过时"类，提交里说明）。`tests/test_holdout_score.py` 里 Q4 只被断言"分母 > 0"，改成真实口径后仍成立。 |
| 5 | "门⑨ 需要索引 → `check_holdout.py` 不再是纯 stdlib" | 它**已经** import `block_director.knowledge.hypergraph`（取 schema 单一真源），且设计上就要"机械验证"。索引缺失时按 `not_measured` 退出（2），不会假装通过。 |
| 6 | "排序要不要一起调？" | **不动**。全量实测 `rank_of_must` 中位数 = 1；在候选集内排序不是瓶颈。动权重只会掩盖 oracle 缺陷（且规格 §2.3 第 3 步写死了默认权重，现状的 `SCORE_WEIGHTS` 已被前一轮改成非规格值，属另一条待收口的口径——记进报告，不在本 lane 擅自改回）。 |
| 7 | "长任务会不会被本 lane 打断？" | 不会：本 lane 只改 `tools/holdout_score.py`、`tools/check_holdout.py`、`tests/`、文档。语料与生成脚本（`tools/kb_fetch/*`）不动。 |

## 3. 明确不做（红线）

- 不降 Q1/Q2/Q4/Q6b/Q7 的任何线，不动 §4.1b 的分母下界。
- 不删测试、不 `--deselect`、不 `-k "not …"`、不 `try/except` 吞错。
- 不把人审门⑦写成通过（agent 不可替代），一律 `not_measured`/`fail` 并单独报告。
- 不为了变绿去改 oracle 或索引。
