# P14-89：链上的 Q5 读的是**上一代**的真跑——换成本代的

## 缺陷（账与系统脱节）

`tools/run_tests.ps1` 的 knowledge 块把 `--shots` / `--audit-log` 指向
`docs/evidence/20261003_real_long/`——那是**唯一跑在 `rag.backend: bm25` 时代**的长跑
（§七十六 之前，真跑样例还没改）。那一代**不发 `/v1/retrieve`**，逐镜查询也不是现在
这个形状（没有意图轴＋声明运镜），所以 Q5 的运行侧**结构上**只能是 `0/0`：

| 链上喂的输入 | Q5 运行侧 | 状态 |
|---|---|---|
| `20261003_real_long`（旧代） | `run_numerator 0 / run_denominator 0`、`run_drift_shots` 57 | **fail**（§4.1b 硬规则 1：分母 0 即失败） |
| `20261004_chunked_long17`（本代，超图 67 次检索） | **9 / 12 = 0.75**（线 0.80） | **fail** |

**同一个工具、同一份 held-out oracle，只换输入**——系统实际做到 0.75，账上写的是 0/0。
这不是"数字好看"，是**账在量一个已经不存在的系统**：Q5 的分母从 0 变成 12，说明这一代
的逐镜查询第一次落进了标注的键形状里（这正是 §七十六 修 `bm25 → hypergraph` 的直接
后果）。E2 也一样：从"读不出来"变成 **3/64 = 0.0469**（诊断量，不设门）。

## 修法

* `--shots` / `--audit-log` 指向**本代**的长跑（`docs/evidence/20261004_chunked_long17/`，
  超图通道、64 镜全审、逐镜查询带意图轴）；
* 新增 `--audit-run-id`，其值**从那份 run 的 `run_manifest.json` 现读**
  （`$knowledgeRunId = (Get-Content ... | ConvertFrom-Json).run_id`）——新跑的审计事件
  带 `run_id`，镜像必须按"产出这份日志的那一跑"过滤；**绝不把 id 手抄进脚本**；
* `--shots` / `--audit-log` 仍写成**字面路径**（不是 `(Join-Path …)` 表达式）：
  `tests/test_chain_evidence_is_measured.py::test_the_quality_report_is_fed_the_real_run_and_the_audit_channel`
  会去 `ROOT / <那个 token>` 上验"文件存在且非空"，写成表达式它当场红——这条守卫在这次
  改动里**真的起作用了**（第一次改法就被它拦下）。

## 结果（`docs/evidence/20261004-125750/`）

| 指标 | 换前 | 换后 |
|---|---|---|
| Q5（运行侧） | 0 / 0（fail，分母 0） | **9 / 12 = 0.75（fail，线 0.80）** |
| E2（诊断） | 读不出来 | **3 / 64 = 0.0469** |
| E1 | 3 / 18 = 0.1667（fail） | 不变（要 GLM 额度扩样，§七十八） |

**验收口径一个字没改**：Q5 仍是 fail（0.75 < 0.80），E1 仍是 fail，硬门汇总裁决仍是
`not passing: Q5,E1`。变的只是"这条账量的是哪个系统"。

`tools/run_tests.ps1` **32/32**、`python -m pytest` **2006 passed / 1 skipped**。
