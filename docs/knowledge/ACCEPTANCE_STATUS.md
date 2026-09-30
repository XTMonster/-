# RK-13 / P14 验收现状（逐项对账 · 2026-10-01）

这份文件是**完成度审计**，不是计划：每一项都给出当前真实数字、证据文件、
以及"要让它变绿还缺什么"。数字取自最近一次全量验收
`docs/evidence/20261001-022303/`（`tools/run_tests.ps1` 31/31 通过，
RK-13 如实记为 measured + failed），索引为重建后的 **683 条边 / 1733 张卡**。

## 一、语料门（K1–K5，`knowledge/cards_generated/import_report.json`）

| 门 | 要求 | 当前 | 判定 |
|---|---|---|---|
| K1 `source_ref` 六字段完整 | = 1.0 | 1.0 | **pass** |
| K2 许可合规率 | = 1.0 | 1.0 | **pass** |
| K3 九域每域 ≥60 张且占比 ≥5% | — | 最少域 106 张（axis_theory），总 1733 | **pass** |
| K4 去重有效率 | ≥0.60 | 1.0 | **pass** |
| K5 主题配额（lighting/color/camera_angle/editing/anime/storyboard） | 诊断量 | 92 / 56 / 131 / 127 / 263 / 204 | **pass** |
| 体积门（单文件 ≤512 KB、总量 ≤20 MB） | 硬门 | 3.22 MB，最大文件 <512 KB | **pass** |

## 二、held-out 覆盖门（`tools/check_holdout.py`）

| 门 | 当前 | 判定 | 让它变绿需要 |
|---|---|---|---|
| ① 总量 ≥1200 | 4539 条 | **pass** | — |
| ② 逐条格式 | 全部合规 | **pass** | — |
| ③ 种子覆盖 | 词表有值没被任何 `q` 用到 | **fail** | 填充分片跑完后合并（`tools/holdout_merge.py`） |
| ④ 边类覆盖（13 类各 ≥30 对 / ≥10 卡） | 通过 | **pass** | — |
| ⑤ 禁忌冲突 ≥60 | 487 | **pass** | — |
| ⑤b 每个 forbid 成员 ≥1 条冲突用例 | 通过 | **pass** | — |
| ⑥ 来源覆盖（每张卡 ≥1 条、无幽灵卡） | 缺 **687** 张卡、29 条幽灵卡（把在跑的 v11/v12 分片并进来后降到 571） | **fail** | 同上：合并 v11/v12 分片；幽灵卡是 29 张被重标替换的 cinematography 卡，合并时会被门丢掉 |
| ⑦ 人审 ≥120 | 需要 789 条，已审 0 | **fail（只能人做）** | 表格已备好：`docs/knowledge/EDGE_REVIEW_SAMPLE.md` |
| ⑧ 换族独立性 | 抽取 deepseek / 标注 zhipu | **pass** | — |
| ⑨ 可达性（`q` 能检出自己的 `must`） | **2449/4539 条够不着（54.0%）** | **fail** | 需重标。这个数从 970 涨到 2449 不是新缺陷：v1.5 给 `intensity` 补了查询键（`强度`），把"说不出强度"的弱查询**暴露**了出来——而它换来的是索引派生 Q1/Q2 0.6164/0.8653 → **0.7189/0.9165**（双双过线）。标注提示从 schema 渲染，下一轮标注会自动带上该键（见 ORACLE_ALIGNMENT.md §6.1） |
| ⑩ 索引可解析 | `must` 1846/5043 解析 | **fail** | **规格裁决**：见 §四 |

运行方式（三种口径都能量）：

```powershell
python tools/check_holdout.py fixtures/knowledge_holdout.jsonl `
  --vocab fixtures/knowledge_holdout.vocab.json `
  --cards fixtures/knowledge_holdout.cards.json `
  --expectation-relation exact   # 或 subset / card_edge
```

## 三、质量指标（Q0–Q7 / E1–E3，`docs/evidence/20261001-022303/knowledge_quality.json`）

| 指标 | 线 | 当前 | 判定 | 说明 |
|---|---|---|---|---|
| Q0 构建恒等式与拒收率 | rejects ≤5% 且 processed=total | 满足 | **pass** | 683 条边，rejects 0 |
| Q1 top-1 命中 | ≥0.70 | **0.2483** | fail | 独立 oracle 口径，上限受种子可达性压制约 0.38；**索引派生查询下已达 0.7555**（`ranking_quality.py`） |
| Q2 top-3 命中 | ≥0.90 | **0.3582** | fail | 同上；索引派生查询下 **0.9488** |
| Q3 负样本误命中 | ≤0.10 | 0.0194 | **pass** | — |
| Q4 required 边 top-3 检出 | = 1.0 | **0.8243** | fail | 分母只含**能在索引里解析**的 required 边（1846 条）；`required_unresolved` 3197 另计 |
| Q6a 契约往返 | = 1.0 | 1.0 | **pass** | — |
| Q6b 成员完整率 | = 1.0 | **0.8666** | fail | 未解析的边不进分母，故与 Q4 同源 |
| Q7 禁忌拦截 | = 1.0（冲突查询 ≥60） | 1.0（**616**） | **pass** | 排序重标定后分母从 487 涨到 616（安全层覆盖更广），见 FORBID_COVERAGE.md |
| Q5 运镜命中 | ≥0.80 | not_measured | — | 需真实计划镜头（人评） |
| E1 经验引用相关性 | ≥0.70 | not_measured | — | 需人评 |
| E2 经验采纳率 | 诊断量（不设门） | **0.0（0/64）** | measured | 用 `docs/evidence/offline_run2/export/shots.json` 实测得到；**这条 0 是结构性的**：`block_director/delivery/manifest.py::_movements_payload` 只写 `declared`/`planned` 两种来源，注释自己写着"P14 之后 `theory`/`experience`/`lesson`/`case` 由知识 trace 填"——而那一步没做。于是"这条运镜是不是知识层给的"无从追溯，E2 恒为 0（不是因为知识层没被用，而是**没人记账**） |
| E3 经验越权率 | = 0 | 0（类型级保证） | **pass** | `Case` 结构上没有 forbid 字段 |

## 四、要把 RK-13 判绿，必须先行裁决的三件事

1. **门⑩ 的期望关系**（`docs/knowledge/ORACLE_ALIGNMENT.md`）：
   `exact` 天花板 39.6% / `subset` 43.5% / `card_edge` 94.1%。
   开关已实现（`--expectation-relation`），**默认仍是规格字面的 `exact`**。
2. **`forbid` 的宿主范围**（`docs/knowledge/FORBID_COVERAGE.md`）：
   现状 278 条禁令只有 16 条进索引（5.8%）；提案是"边里有这个槽位就能禁"。
3. **门⑨/门⑥ 的残差**：970 条 `q` 够不着自己的 `must`、571 张卡没有条目
   ——前者靠重标（v11/v12 正在做），后者靠合并分片。v11/v12 跑完前，
   这两项**不可能**变绿，不是实现缺陷。

## 五、这一轮（P14 知识 lane）已经把什么做实的

### 4.1 两处"要接但没接"的地方（本轮实测确认）

* **`movements[].source` 的知识层来源没人写**（见上表 E2 行）：`delivery/manifest.py`
  只写 `declared`/`planned`。要 E2 有意义，需要在产出 `shots.json` 时把该镜注入过的
  知识来源（`theory`/`experience`/`lesson`/`case`）落到每条运镜上——这需要驱动层保留
  **逐镜**的知识归属（现在 `knowledge_trace.json` 是**整轮**一份）。
* **`intensity` 这类必填槽位缺查询键**曾经把排序压在 0.62——已修（见 §四 之后的
  `ORACLE_ALIGNMENT.md §6.1`），但它同时把门⑨ 的弱查询暴露到 54%，需要一轮重标。

* 语料 1075 → **1733 卡**（新增现代理论 11 篇 + 动漫制作/剧场版 7 篇，全部走同一套机器门）；
* 索引 387 → **683 条边**，其中：手写策展卡**首次进索引**（`curated/<id>`）、
  抽取器改为**按耦合写边**（extract/v5）、被整轮漏掉的卡用 `--only-missing` 补边；
* 卡级覆盖：oracle 涉及的 1075 张卡里，无边的从 **268 张降到 86 张**；
* 消费侧：超图后端下八条真实查询**每条取到 8 条边、注入 194–699 字符、零降级**
  （`tools/knowledge/retrieval_smoke.py` + `tests/test_retrieval_smoke.py`）；
* 一切改动都带对抗性测试，`python -m pytest` 与 `run_tests.ps1`（31/31）全绿。
