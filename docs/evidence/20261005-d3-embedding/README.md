# D3：嵌入路线的**同路由对照**（本地 bge-small-zh ↔ 智谱 embedding-3）

日期 2026-10-05。产物：`e1_d3_embedding.json` ＋ 4 份逐行录档 ＋ 4 份轮记录。
判词走 `tools/knowledge/e1_report.py` → `e1_baseline_summary.paired_report`（噪声带 ＝
各臂同臂极差的最大值）。

## 1. 结论先说

| 臂 | rep1 | rep2 | mean | 同臂极差 |
|---|---|---|---|---|
| `lightrag+local`（`BAAI/bge-small-zh-v1.5`，**512** 维，本地 GPU） | 0.026042（5/192） | 0.015625（3/192） | **0.020833** | 0.010417 |
| `lightrag+cloud`（智谱 **`embedding-3`**，**2048** 维，云端） | 0.119792（23/192） | 0.114583（22/192） | **0.117188** | 0.005209 |

**Δ(cloud − local) = +0.096355 ＞ 噪声带 0.010417 ⇒ `separated`**：
**云端的 `embedding-3` 把 LightRAG 这条路的 E1 提高了约 5.6 倍**（0.0208 → 0.1172）。
⇒ 用户买下的那个资源包**是有实质作用的**；而且既然两代索引**必须整体重建**
（指纹第三格 `<路由>:<模型>:<维度>`），这条读数就是"要不要为 lightrag 付这份钱"的依据。

## 2. 这条对照是怎么做到"只差嵌入器"的

* 两条臂**同一条路由**（`lightrag`）、**同一个案例层**、**同一批 64 条冻结查询**、
  **同一个面板**、**同为 `naive` 检索模式**（纯向量，不含图谱/LLM 关键词那一步）；
* 两代索引的入库文档**逐字相同**（都由 `--clues local` 并入同一份 542 条中文线索）；
* 环境（`--expected-fingerprint`）**都开了 fail closed**，且 `all_rounds_used_the_route = true`
  ——4 轮的 `cases_degrade_reason` 全空、`queries_with_rows = 64/64`，
  没有一次退回 BM25，也没有静默空。
* **如实记一处小混杂**：我拷抽取缓存时本地那代还在收尾，所以云端这代**重抽了 2 篇**
  （图谱规模：本地 6385 节点/6205 边、processed 781；云端 6386 节点/6243 边、processed 783）。
  差异 1 节点/38 边（≈0.6%），不改变上面那个量级的结论。

## 3. 与 D8 的关系（两个结论并存，别读混）

* **D3（这条）**：**嵌入器**层面，云端 `embedding-3` 显著优于本地 `bge-small-zh`。
  要用 lightrag，就用云端那一代。
* **D8（`docs/evidence/20261005-p9-v4pop/`）**：**路由**层面，即便换成云端嵌入器，
  LightRAG 仍**低于**两条 BM25 臂（0.117 vs hybrid 0.193／lexical 0.190），
  所以**默认路由仍是 `hybrid`**（`BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG` 默认关）。
  （P9 那份用的是本地嵌入那一代；这里给出的是云端那一代的读数，两条都要看。）

## 4. 复跑

```powershell
# 本地那一代
powershell -NoProfile -File work\_run_p9_lightrag.ps1 `
    -Index work/lightrag_v4_clues_local -Port 8813 -Mode naive `
    -Routes 'lightrag+local' -AbOut work/e1_d3_embedding.json -Runs 2
# 云端那一代（先按 §5 建索引）
powershell -NoProfile -File work\_run_p9_lightrag.ps1 `
    -Index work/lightrag_v4_clues_cloud -Port 8814 -Mode naive `
    -Routes 'lightrag+cloud' -AbOut work/e1_d3_embedding.json -Runs 2
# 汇总（同路由两个配置各算一个臂，靠 `<路由>+<标签>` 区分）
python tools/knowledge/e1_report.py --index-dir work/knowledge_v4_cases `
    --heldout work/eval_sets/heldout_v4_long21.jsonl `
    --routes 'lightrag+local,lightrag+cloud' --runs 2 --reuse `
    --reviews-dir work/e1_d3_embedding.json.reviews --out work/e1_d3_embedding.json
```

## 5. 未核验

* 云端那一代的**图谱**是在"缓存已老化"的情况下建的（重抽 2 篇，见 §2）——若要一个
  逐字节同图谱的对照，应在本地那代**完全收尾之后**再拷缓存重建一次；本读数不依赖它
  （差异 0.6%）。
* 只测了 `naive` 模式。`hybrid` 模式在云端嵌入器上的读数未测。
* 云端嵌入是**联网调用**（`open.bigmodel.cn`）：上线使用时它带来网络依赖与调用成本，
  这两项**不在本读数的射程内**（E1 只量相关性）。
