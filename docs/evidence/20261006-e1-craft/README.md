# L3 定版 1,143 条（craft 来源扩容）：E1 0.1823（同代查询）／0.1990（long19 查询）

结论先行：把**唯一成体系讲镜头工艺**的来源（StudioBinder）从 157 条扩到约 900 条，
其余来源钉回发货份额，L3 从 500 条变成 **1,143 条案例 / 1,012 条线索**。
E1 在同一份索引上有**两个查询集**的读数（见 §2）：long19 的 64 条查询上 **0.1990**，
**同代**（新真跑 long21 自己的 64 条查询）上 **0.1823**——链上用的是后者，
因为它与 Q5／审计通道**同一代**。上一版（500 条）在 long19 查询上是 **0.1441**。
判据、门限（0.70）、oracle、`SCORE_WEIGHTS` 一个字没动；E1 仍 `fail`、`RK-13` 仍 `failed`。

## 1. 为什么动的是这一家

§八十九 把 E1 的根因拆成两半（检索面 / 语料面）；§九十一 的 D 臂证明
"**无差别**加深**已有**来源"是回退（覆盖 59.9% 而 E1 0.0920 → 0.0469）。
来源普查（`docs/evidence/20261005-craft-source-arm/README.md`）显示：

| host | 段数 | 发货 500 条里占 | 定位 |
|---|---|---|---|
| www.gutenberg.org | 41,805 | 105 | 1900 年代实务书（稀释项） |
| journal.animationstudies.org | 15,582 | 161 | 同行评审影评（稀释项） |
| **www.studiobinder.com** | **1,752** | **157** | **讲"怎么拍"** |
| bfi / skwigly / frames / ocw | 约 1,900 | 77 | 逐片评论与讲义 |

E 臂只抬 craft 一家（`case_budget: 40`），其余钉回发货份额（古书/摄影/影评 → 2 或 1）。
另查过 MIT OCW 的 574 份候选 PDF：真正讲"怎么做"的只有约 42k 字（几十条案例），
低于噪声底，所以那一批不做实验、不收录（其中 `Designed_Video_for_Learning.pdf`
还挂在斯坦福域名下，许可不在课程范围内）。

## 2. 读数（同片、同 64 条逐镜查询、同跨族面板 deepseek-chat × glm-5.3）

| 索引 | 案例 | 线索 | 覆盖 | E1 |
|---|---|---|---|---|
| 上一版发货（§九十一） | 500 | 363 | 72.6% | 0.1441（83/576，3 次，**long19 查询**） |
| E 臂候选（并集，已测） | 1,322 | 1,191 | 90.1% | 0.2031（39/192，**long19 查询**） |
| **发货（本节）· long19 查询** | **1,143** | **1,012** | **88.5%** | **0.1990（38/191）** |
| **发货（本节）· long21 查询（链上用的）** | **1,143** | **1,012** | **88.5%** | **0.1823（35/192）** |

候选与发货**不是同一份**（候选是"发货 500 ∪ 新候选"的并集，发货是从新
`licensed.jsonl` 重建），所以没有拿候选的 0.2031 冒充发货读数。`reviews.jsonl`
是**发货索引 × long21 查询**那一次（35/192）；`reviews.long19.jsonl` 是同一份索引
× long19 查询（38/191；分母 191 是因为有一条两侧都没给出数字分数）。

**读数怎么读才诚实**：`0.1441 → 0.1990` 是**同一套 long19 查询**上的前后对照
（同一个分母口径），craft 扩库的贡献看这一对；`0.1823` 是**同代**读数
（long21 自己的查询 + 同一份索引），与 Q5／审计通道同一代，链上用它。
两套查询不同，**不能**拿 0.1823 与 0.1441 直接相减当增益。

**尚未完成的一步（如实记）**：语料管线这次重跑让上一版 500 条里的 **77 条**换了段号
（活站点内容漂移，`old ∩ new = 423/500`），所以"0.1441 → 0.1990"里**混着漂移**。
同语料、旧预算的**对照臂**（`work/control_index`，810 条候选）正在注线索，
跑完才有"craft 扩容的净贡献"。

## 3. 机制

只换来源、不加深度：E 臂与 D 臂的差别就在这一点——D 是把同一批来源挖得更深
（带工艺信息的比例低），E 是换到**本来就讲拍法**的来源（线索产出率约 53%，
而古书深层只有约 20%）。

覆盖门同时被满足：`1,012 / 1,140 = 88.8%`（门要求 ≥50%）；来源痕迹门
（每条 `sources.yaml` 来源都要在卡片 ∪ 案例里留痕）也过——发货 500 条被
`--require-clue-keep` 整批保护，没有任何来源失去痕迹。

## 4. 复算

```powershell
# 预算已写进 sources.yaml（仓库里的输入）：
#   studiobinder -> case_budget: 40 ；古书/摄影/影评 -> 2 ；Animation Studies/BFI -> 1
python -m tools.kb_fetch.fetch          # 幂等，321 源全部命中缓存
python -m tools.kb_fetch.extract_text
python -m tools.kb_fetch.dedupe
python -m tools.kb_fetch.validate_licenses
python -m tools.kb_fetch.build_cases --max-cases 4000 `
    --require-clue knowledge/cases/search_zh.part-000.jsonl `
    --require-clue-keep knowledge/cases.protect_shipped.jsonl --out-dir knowledge
python tools/knowledge/e1_panel.py `
    --project docs/evidence/20261004_chunked_long19/project/project.bdproj `
    --cases-dir knowledge --out docs/evidence/20261006-e1-craft/reviews.jsonl --top-k 3
```

线索由 `glm-5.3` 生成（`prompt_sha256 = 36069623…`，与 manifest 的
`clue_attached.prompt_sha256` 一致；缺失或混代会由 `read_search_zh` 整份拒用）。
