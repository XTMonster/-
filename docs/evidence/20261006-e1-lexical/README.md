# L3 零依赖适配器（候选，**默认关闭**）：E1 0.1823 → **0.2135**

> 状态：**候选**。它在**同一份发货索引、同一批 long21 查询、同一个跨族面板**上量到
> E1 **41/192 ＝ 0.2135**（现行 BM25 路径是 35/192 ＝ 0.1823）。
> **产品默认路径没有改**（sidecar 仍走 `cases_backend=hybrid`）——是否启用等拍板。

## 1. 它是什么（对应 ADR-0014 的 ② 魔改第一块）

`block_director/knowledge/lexical_adapter.py`：挂在**已经声明好的**适配器接缝上
（`cases.register_lightrag_adapter`，`block_director/knowledge/cases.py:88`），
契约是 `retrieve(query, *, top_k, cases)`。三段：

1. **精确层**：查询点名的**取值**（`景别=MS` 的 `MS`、`运镜=固定` 的 `固定`；
   `禁<键>=值` 的取值同样进召回面）在案例文本/中文线索里出现者排前；
2. **词法层**：仓库自带的 Okapi BM25（与 `rank_bm25` 同算法同参数，`bm25.py`）
   对"中文线索 ＋ 作者原文摘录"打分；
3. **重排层（可选、注入式）**：`rerank(query, cases) -> [case_id, …]`，
   sidecar 可以注入一个 `glm-5.3` 的重排器；**抛错或返回空时退回词法序**并具名记账。

**零依赖**：只 import 标准库与仓库自己的模块（守门
`tests/test_lexical_adapter.py::test_the_adapter_pulls_no_new_dependency` 用 AST 判）。
这正是联合会诊两侧给的路线——`键=值` 查询要的是**谓词匹配**，不必解 embedding。

## 2. 读数（同索引、同查询、同面板）

| 检索路径 | 线索 | 判分 | 相关（≥4） | E1 |
|---|---|---|---|---|
| `hybrid`（产品现行 BM25） | 1,012 | 192 | 35 | 0.1823 |
| **`lexical`（本适配器）** | 1,012 | 192 | **41** | **0.2135** |

命令（两臂只差 `--adapter`）：

```powershell
python tools/knowledge/e1_panel.py `
    --project docs/evidence/20261006-long21/project/project.bdproj `
    --cases-dir knowledge --out <out> --top-k 3 --workers 3 [--adapter lexical]
```

每行现在自带 **`retrieval_path`**（`hybrid` / `lexical`）——一份证据里两条路的读数
不会混账（守门 `tests/test_e1_panel.py::test_every_scored_row_says_which_retrieval_path_produced_it`）。
（`reviews.hybrid.jsonl` 是本适配器落地**之前**跑的那一次，所以它的行里还没有这一格——
它的路径由生成它的命令断言：当时没有 `--adapter`，即产品现行的 `hybrid`。）

## 3. 边界（不许含糊）

* **每臂只跑了 1 次**。同一臂的重复散布约 ±0.008（见
  `docs/evidence/20261004-e1-vocabfix/noise_floor.json`），+0.031 ≈ 4 倍噪声；
  **要启用应先补 2 次重复**。
* **E1 仍 fail**（0.2135 对 0.70 线），`RK-13` 仍 failed；判据、门限、oracle 一个字没动。
* **启用会改产品行为**（检索路径），因此需要：① 重复测量；② 一次**新真跑**让
  Q5／审计证据与新的检索路径同代（现在那份 long21 证据跑在 `hybrid` 上）。
  这两条没做之前，它只作为**候选**留档。
