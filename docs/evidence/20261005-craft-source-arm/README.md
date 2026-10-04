# E 臂：**只对 craft 来源**扩容（来源普查 ＋ 变量隔离）

> 状态：**进行中**。这份先记"查到了什么、为什么这么设计"，E1 读数等面板跑完再补
> （届时与发货的 0.1441 并排）。**没出数字之前不主张任何结论。**

## 1. 来源普查（为什么不去加 OCW 那一批）

`tools/kb_fetch/find_ocw_sources.py`（走 MIT OCW 的 sitemap ＋ 资源页，每一个 PDF 都
过仓库自己的 robots/抽取门）实测：

* 2,587 门课里**影视相关 40 门**，候选 PDF **574** 份（`work/ocw_candidates.json`）；
* 但按"讲**怎么做**"筛，真正对题的只有 `mas-845`（cinematic storytelling 的 6 份
  客座讲义，合计约 42k 字）与 `es-333` 的 1 份——后者还挂在
  `aaalab.stanford.edu`（**不是** OCW 那门课的许可范围）⇒ **不收**；
* 剩下的多是影史/摄影/游戏开发。按实测产出率（深层候选约 20% 带工艺信息），
  42k 字只够**几十条**案例——**低于 E1 的噪声底**（同一臂重复散布约 ±0.008，
  见 `docs/evidence/20261004-e1-vocabfix/noise_floor.json`）。

⇒ 结论：**这批不值得开一次实验**（花 1 小时 LLM 也测不出信号）。真正有体量的
对题来源在**已经收进来的**那一家。

## 2. 供给普查（按 host 数，`work/licensed.jsonl`）

| host | 来源数 | 被钉成 `case_budget: 1` | 约有多少段 | 发货 500 条里占 |
|---|---|---|---|---|
| www.gutenberg.org | 54 | 0 | **41,805** | 105（1900 年代实务书） |
| journal.animationstudies.org | 161 | **161** | 15,582 | 161（同行评审影评） |
| **www.studiobinder.com** | 50 | 6 | **1,752** | **157**（**讲怎么拍**的博客） |
| www.bfi.org.uk | 35 | 35 | 800 | 35（逐片评论） |
| www.skwigly.co.uk | 16 | 0 | 416 | 34 |
| framescinemajournal.com | 3 | 0 | 360 | 7 |
| ocw.mit.edu | 2 | 0 | 352 | 1 |

**要点**：StudioBinder 是语料里唯一**成体系讲镜头工艺**的来源，而它只进了 157 条
（1,752 段里的 9%）。影评/古书那两项合计 4.3 万段，是**稀释项**（D 臂实测：
无差别扩库让覆盖升到 59.9% 而 E1 从 0.0920 掉到 0.0469）。

## 3. E 臂的设计：**只动 craft 一家**

```powershell
# 候选语料（work/ 里；发货索引不动）
python work/_build_armE.py            # 只有 studiobinder 的预算抬到 40，其余钉回发货水平
python work/_build_armE_union.py      # 并上发货的 500 条（否则会混进"丢了 74 条"这个变量）
python -m tools.kb_fetch.case_search_zh --cases work/armE_index --out work/armE_index/cases ...
python -m tools.kb_fetch.build_cases --max-cases ... --require-clue <上面的线索> \
    --require-clue-keep work/protect_shipped500.jsonl --out-dir <候选索引>
```

* **候选 1,659 条** = 发货 500 ∪ 新增 1,159（`per_host`：studiobinder 1,236 /
  animationstudies 161 / gutenberg 108 / bfi 35 / skwigly 32 / frames 6 / ocw 4
  —— 除 studiobinder 外**都钉回发货水平**，所以变量只有一家）；
* **线索闸门**再筛一遍：新增里没有中文检索键的（多半是古书/影评的深层段）
  直接不进索引 ⇒ 最终索引 ≈ 500 ＋ craft 里能查到的那些；
* 判据、门限（0.70）、oracle、`SCORE_WEIGHTS` **一个字不动**。

## 4. 为什么值得试这一臂

* §八十九 把 E1 的根因拆成两半：检索面（词表，已修，+0.05 量级）与语料面。
* §九十一 的 D 臂证明"**无差别**加深**已有**来源"是回退——但那一次的变量是
  "更深的段"，不是"更对题的来源"。
* E 臂是**唯一还没被排除**的组合：**换来源**（对题）而**不加深度**（不摊薄）。
  它若也不动，则"当前来源族撑不起 0.70"就有了实验证据，可以拿去谈线或谈语料采购。
