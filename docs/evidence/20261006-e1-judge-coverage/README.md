# E1 的**测量失真**：只有一位评委给分的行，被当成了"相关"

日期 2026-10-06。本目录是**缺陷证据 ＋ 修复记录**，判据/阈值一个字没动。

## 一、缺陷

E1 的冻结定义（`tests/plan_v4_instruments.sha256.json` 里 `e1_panel.py` 的 guards 原文）是
**"两位 LLM 评委各打 1-5 分、取均值 >= 4.0 记相关"**。

而实际实现是：某位评委那一批调用失败时，

* `tools/knowledge/e1_panel.py::_score_one` 在行里留 `scores: [x, None]`（**失败不许记成低分**，
  这条本身是对的，`tests/test_e1_panel.py::test_a_broken_judge_is_recorded_as_missing_not_as_a_low_score`
  就是为它写的）；
* 但它接着 `score = sum(numbers)/len(numbers)`——**只按答上来的那一位**取均值，
  于是这一行**照样被判"相关"、照样进分子**（`e1_panel.py:566-577`）；
* `tools/knowledge/quality.py::e1_relevance` 读的是行的 `score`（`quality.py:840-844`），
  于是**链上真正报出的那个 E1** 也照收。

⇒ 一位评委的一次基础设施失败，被算成了"两位评委都判它相关"。

## 二、偏差有多大（复算）

```powershell
python docs/evidence/20261006-e1-judge-coverage/probe_judge_coverage.py `
    docs/evidence/20261006-e1-craft/reviews.jsonl `
    docs/evidence/20261006-c3-ceiling/reviews.current.batch3.top20.jsonl `
    docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top50.jsonl `
    docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl
```

逐字输出见 `probe.out.txt`。四份证据的偏差**方向完全一致**：

| 打分文件 | sha256(前 12) | 行数 | 只有一位评委 | 现在报的 E1 | 按定义重算 |
|---|---|---|---|---|---|
| **`20261006-e1-craft/reviews.jsonl`**（**链上真正消费的那份**，`run_tests.ps1:677`） | `82d62ebcc485` | 192 | **17（8.9%）** | **0.1823** | **0.1354** |
| `20261006-c3-ceiling/reviews.current.batch3.top20.jsonl` | `442b3d587fe6` | 1,152 | 37（3.2%） | 0.1267 | 0.1163 |
| `20261006-c3-deep-pool/reviews.current.batch3.top50.jsonl` | `c5c112823898` | 3,072 | 92（3.0%） | 0.0908 | 0.0837 |
| `20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl` | `4b30f55fea1d` | 7,679 | 172（2.2%） | 0.0611 | 0.0548 |

**每一份都是"现在报的数偏高"**——所以修它不是"换尺翻绿"，是把尺子收紧。

## 三、修复（两处，都只收紧方向）

1. `e1_panel._score_one` 每行新增自述字段 **`judge_incomplete`**；`e1_panel.summarise` 新增
   **`judge_incomplete_rows`**，并把这类行**排除出 `good`**。
2. `quality.e1_relevance` 同样把这类行排除出分子，并把条数写进 payload 与 note
   （`judge_incomplete_rows` / `judge_incomplete_examples`）。

**分母不动**——这是本修复最关键的一条：E1 的分母是"交给导演的那 3 条"／面板条目数，
**由检索决定**，不是"我们侥幸判成了几条"。所以判不出的行**留在分母里、只是绝不算相关**。

> 本目录的探针同时算了另一种口径（`E1_two_judge_only`，把这类行**从分母里剔掉**）：
> 链上那份会变成 **0.1486**（比 0.1354 高）。它**没有被采用**，因为"把判不了的行从分母里
> 拿掉"会让分母变小、比率变好看——那正是 §4.1b 硬规则 1（比率型判据必须带分母下界）
> 要防的那件事。

## 四、顺带补上的一个**冻结洞**

链上真正报出的那个 E1 是 `tools/knowledge/quality.py` 算的，而它**不在**
`tests/plan_v4_instruments.sha256.json` 的冻结清单里（清单里只有 `e1_panel.py`、
`e1_baseline_summary.py`、`check_holdout.py`、`e1_report.py`、`hypergraph.py`）。
⇒ **E1 这个数的产出方此前可以被静默改掉**，而"改了要红"的守门覆盖不到它。
本次把它**新增进冻结清单**（第十九次冻结，理由写在 `_reason_19`）。
这与本仓库已记的两个前例是同一个形状：S0 的 `QUALIFIER_KINDS` 洞、
S1a 的 `tools/sidecar_server.py` 手抄字面量洞。

## 五、守门测试（红 → 绿）

* `tests/test_knowledge_quality.py::test_e1_never_counts_a_row_that_only_one_judge_scored`
  （先红：实测 `assert 2 == 1`，旧实现把单评委那行算进分子）
* `tests/test_e1_panel.py::test_a_single_judge_row_stays_in_the_denominator_but_is_never_relevant`
* `tests/test_e1_panel.py::test_a_broken_judge_is_recorded_as_missing_not_as_a_low_score`
  （**加强**，不是放宽：新增"这一行必须被标记"的断言；原来那条"失败侧不是 1 分"原样保留）
* `tests/test_plan_v4_instruments_frozen.py`（先红：`e1_panel.py` 哈希不符 ⇒ 重新冻结后绿）

## 六、未验证 / 不主张

* **没有重跑面板**：修复改的是"怎么汇总已有的分"，不是"重新判分"。
  四位评委的原始分数一条没动，`scores` 数组逐字保留。
* **没有让 E1 变成 `measured`**：链上那份仍因缺 `judge_batch` 记 `not_measured`
  （这是**另一件事**，见 `docs/knowledge/DECISION_BRIEF_RK13.md`）。本文只证明
  "现在报出来的那个值偏高 0.0469（0.1823→0.1354）"。
* 历史台账里引用的 `e1_panel.summarise` 读数（例如 0.4583／0.4740 这类**可达上界**）
  同样含这一点偏差、**未逐条重算**；它们的口径是"oracle 三元组的行被两位评委判过"，
  单评委行占比不同，偏差方向一致但幅度需要各自复算。
