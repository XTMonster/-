# P9：v4 总体上的**三臂双重复**读数（D8 的判定证据）

日期 2026-10-05。产物：`e1_v4pop_ab.json`（`tools/knowledge/e1_report.py` 出）＋
`e3_v4pop.json`（`tools/knowledge/e3_report.py` 出）＋ 6 份逐行录档 ＋ 6 份轮记录。

## 1. 结论先说

| 臂 | rep1 | rep2 | mean | 同臂极差 |
|---|---|---|---|---|
| `hybrid`（产品现行 BM25） | 0.192708（37/192） | 0.192708（37/192） | **0.192708** | 0.000000 |
| `lexical`（零依赖适配器） | 0.197917（38/192） | 0.182292（35/192） | **0.190105** | 0.015625 |
| `lightrag`（真索引，`hybrid` 模式，本地嵌入） | 0.026042（5/192） | 0.026042（5/192） | **0.026042** | 0.000000 |

* 噪声带 R ＝ 参与比较各臂**同臂极差的最大值** ＝ **0.015625**；
* **hybrid ↔ lexical：Δ = −0.002603 ＜ R ⇒ `inconclusive`**（与 v3pop 那份已入库基线的
  结论一致："BM25 与词法适配器之间的差别没有量到"）；
* **hybrid ↔ lightrag：Δ = −0.166666 ＞ R ⇒ `separated`**；
  **lexical ↔ lightrag：Δ = −0.164063 ＞ R ⇒ `separated`**。

⇒ 按计划 v4 的 D8（"ΔE1 ≥ R 且 E3=0 ⇒ lightrag 默认"），**LightRAG 不满足成为默认路由的
条件**：它在本总体、本查询集、本面板下**显著更差**（低一个数量级）。产品默认路由保持
`hybrid`（BM25）不变——`BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG` 仍然默认关。

## 2. 为什么这次的读数**可信**（三道以前会漏掉的关口都过了）

1. **每轮真的是那条路由答的**：`all_rounds_used_the_route = true`——6 轮的
   `cases_degrade_reason` 全为空（没有退回 BM25 的降级），`lightrag` 两轮
   `queries_with_rows = 64/64`（没有"适配器返回空、整条查询悄悄没有行"的静默空）。
   对照：修这条之前的 lightrag 臂量到的是**客户端 10 秒超时**（`work/_sidecar4.err`
   5773 行 `bound to a different event loop` ＋ 客户端超时），而不是检索质量。
2. **代际同一**：6 轮的身份字段 diff **不一致字段数＝0**；`seed=20261005`、`rows=64`、
   `corpus_manifest_digest=a162c41c…`（案例层 manifest——它的内容里钉着
   `corpus_fingerprint` 与 `cards_sha256`，所以 L1/L2 那一代也被传递性地钉住了）；
   `cases_fingerprint=4b1b44bb…`、`cases_digest=d916cd78…` 逐轮一致。
3. **终态全 valid**：`terminal_states = {"valid": 6}`（V2 的封闭枚举：两个作废码
   `invalid_parse_fault` / `invalid_empty_intersection` 各为 0）。

## 3. 怎么复跑（命令逐字）

```powershell
# ① 两条进程内臂（每路由 2 轮，写逐行录档 ＋ V1 轮记录；不带报告）
python tools/knowledge/e1_report.py --index-dir work/knowledge_v4_cases `
    --heldout work/eval_sets/heldout_v4_long21.jsonl --routes hybrid,lexical --runs 2 `
    --rounds-only --out work/e1_v4pop_ab.json

# ② 第三臂：sidecar（真索引）＋ 读超时放开 ＋ **预热须验 200**，再写同一份证据目录
$env:BLOCK_DIRECTOR_LIGHTRAG_TIMEOUT = '180'
powershell -NoProfile -File work\_run_p9_lightrag.ps1 `
    -Index work/lightrag_v4_clues_local -Port 8811 -AbOut work/e1_v4pop_ab.json -Runs 2

# ③ 汇总（三臂 × 2 轮：判词走 paired_report，噪声带以下算 inconclusive）
python tools/knowledge/e1_report.py --index-dir work/knowledge_v4_cases `
    --heldout work/eval_sets/heldout_v4_long21.jsonl --routes hybrid,lexical,lightrag `
    --runs 2 --reuse `
    --lightrag-fingerprint c1cd106e558af216274f170676de99a0f00ab3ca9ba7ee48e9c10d88b6ca8596 `
    --out work/e1_v4pop_ab.json

# ④ E3（三路由经验越权数）
python tools/knowledge/e3_report.py --index-dir work/knowledge_v4_cases `
    --routes hybrid,lexical,lightrag --runs 2 `
    --reviews-dir work/e1_v4pop_ab.json.reviews --out work/e3_v4pop.json
```

索引（第三臂的服务侧）：`work/lightrag_v4_clues_local`，
指纹 `c1cd106e558af216…`，783 篇文档、`clues=542`、`clue_state=""`。

## 4. E3（P9②）

`e3_v4pop.json`：`status = pass`；层一级 `quality.e3_cases` **0/783**；
6 轮的召回里 `constraint_fields` 与 `constraint_clues` **全为 0**（三路由经验越权数全 0 ✓）。

## 5. 如实挂着的折扣与未核验

* **评委覆盖不齐**：hybrid/lexical 各轮有 **7–14 行**只有一位评委回了分
  （`all_rounds_complete=false`）；lightrag 两轮是 **192/192** 两位齐。
  按 V1 的"一侧缺席永远不算同意"，严格说 hybrid/lexical 那四轮不是**完整**轮——
  但两臂的 Δ（0.0026）远小于噪声带（0.0156），这条折扣不改变上面的结论。
* **`lightrag` 只测了 `hybrid` 检索模式**（P9 的第三条臂）。`naive`/`local`/`global` 三档
  与**云端嵌入**那一代的对照另行入库（D3），本文不替它们下结论。
* **`hypergraph_manifest_digest` 记 `missing`**：超图 manifest 不在案例层目录里。
  本批的语料身份由 `corpus_manifest_digest` 钉住（见 §2.2），这条缺口是**记录面**的，
  不是可比性面的。
* 这一跑**不改任何判据**：阈值 4.0、两位评委取均值、分母 ＝ 面板行数、
  噪声带由同臂极差推出——与 `tools/plan_v4_instruments.sha256.json` 冻的那五件仪器一致。
