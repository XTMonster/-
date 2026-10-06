# 链上的 **Q6b 读数通道读的是上一代真跑**——半边指标因此**永远量不到**

日期 2026-10-06 19:0x。这是 **SS84 那条的同形洞**：SS84 把链上 **Q5** 的输入
从 bm25 时代的长跑换成了当前代真跑，**而同一个文件里 Q6b 的那一行没跟着换**。

## 一、事实

`tools/run_tests.ps1` 里两处喂真跑：

| 位置 | 2026-10-06 之前 | 说明 |
|---|---|---|
| knowledge 块（`quality.py` 的 `--shots`/`--audit-log`） | `$knowledgeRun = 'docs/evidence/20261006-long21'` | **当前代**（链自己的注释：*"the chain now feeds the newest committed REAL run that has the hypergraph channel"*） |
| **Q6b 读数通道**（`injection_audit.py`） | **写死** `docs/evidence/20261003_real_long` | **bm25 时代**（SS84 的原话：`/v1/retrieve` 从没被调用过，逐镜查询是**旧形状**） |

后果不是"数字难看"，是**半边指标永远量不到**：

| 读数（同一份 `injection_audit.py`） | 喂 `20261003_real_long`（旧） | 喂 `20261006-long21`（当前代） |
|---|---|---|
| `token_caps` | pass（plan 775/2000、shot 785/800） | pass（plan **778**/2000、shot **788**/800） |
| `required_edges_dropped_by_budget` | **`not_measured`**（join 不上 oracle） | **pass：167 个镜头 join 上、167 条 required 边、丢 0 条** |
| `complete` | **false** | **true** |

两份原件都在本目录：`injection_audit.20261003_real_long.json`（链上旧产物，取自
`docs/evidence/20261006-133244/`）与 `injection_audit.long21.json`（同一命令喂当前代）。

## 二、修法（一个真源，而不是换一个日期）

**不是**把写死的路径从 `20261003_real_long` 改成 `20261006-long21`——那只是把"下次再漏"
推迟一遍。改法是把 Q6b 那一行也接到**同一个 `$knowledgeRun`**：

```powershell
$knowledgeRun = 'docs/evidence/20261006-long21'
$knowledgeRunId = (Get-Content (Join-Path $knowledgeRun 'run_manifest.json') -Raw | ConvertFrom-Json).run_id
python tools/knowledge/injection_audit.py --llm-trace (Join-Path $knowledgeRun 'llm_trace.jsonl') ...
```

并且**把定义上移到 Q6b 之前**——PowerShell **自上而下执行**，定义留在下面会让这一行拿到
空路径（这是改动里唯一的陷阱，已用同形状的脚本在 **Windows PowerShell 5.1** 下实跑验证：
`run_id=5c7b92d738c0`、`exit=0`、`status pass / complete true`）。
原位置只留一行注释指向上面，避免**两处定义**。

## 三、守门（先有反例，才叫守门）

`tests/test_chain_evidence_is_measured.py::test_q6b_reads_the_same_real_run_as_the_rest_of_the_knowledge_block`
钉三件事：① 链上只允许**一处**调用 `injection_audit.py`；② 那一处必须走 `$knowledgeRun`
（**不许再出现 `docs/evidence/<8位日期>` 这样的写死路径**）；③ `$knowledgeRun` 只许**一处**定义，
且必须在该调用**之前**。

**反例（negative control）**：`negcontrol_q6b.py` 拿 `git show HEAD:tools/run_tests.ps1`
（改前的文件）跑同一套判据，逐字输出见 `negcontrol.out.txt`：

```
OLD: {'calls': 1, 'uses_knowledgeRun': False, 'has_dated_path': True, 'definitions': 1, 'def_before_call': False, 'guard_fails': True}
NEW: {'calls': 1, 'uses_knowledgeRun': True,  'has_dated_path': False, 'definitions': 1, 'def_before_call': True,  'guard_fails': False}
```

⇒ 这条守门**本来就会红**在旧文件上（三处违规），不是写给已经正确的代码看的。

## 四、未验证 / 边界

* **判据一个字没动**：Q6b 的两个 token 上限（`rag.plan_prefetch_tokens` 2000 /
  `rag.max_tokens_per_call` 800）、分母规则、`not_measured` 的处置全部原样。改的只是
  "**读哪一跑**"。
* 只验证了**这一个**真跑（`20261006-long21`）与这一个旧跑；其余历史真跑没逐个重算。
* `20261006-long21` 是不是"最新"这件事**没有写进代码做断言**（链仍然是显式点名一跑）——
  这与本仓既有做法一致（`$knowledgeRun` 本来就是显式值），但也就意味着**换语料后仍需人记得换**；
  守门只能保证"**两处不会各读各的**"。
