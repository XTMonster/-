# E1 的根因：**检索键的词表与查询的词表错配**（L3 案例层）

> 结论先行：链上唯一红项 `E1 = 17/192 = 0.0885`（线 0.70）**不是"案例不够多"一个原因**，
> 而是两个互相独立的原因叠在一起——
> ① **检索面**：中文线索（检索键）用的词与产品查询用的词对不上，
>    查询里点名的 309 处工艺词有 **153 处（49.5%）在整个线索库里一次都不存在**；
> ② **语料面**：就算把这条 810 条的语料**完美排序**，E1 的上界也只有 **0.25**。
>    （口径说明：这个上界是**条件于当前检索的召回池**的——它量的是"从 top-8 池子里
>    挑最好的 3 条"能到多少；池子之外是否还有相关材料，属于检索面那一半，
>    不在这个数里。要更强的说法必须先把召回面拉满再量。）
> 判据、门限（0.70）、oracle、`SCORE_WEIGHTS`、`E1_SAMPLE_FLOOR` **一个字没动**。

## 1. 这次量了什么（全部零 LLM 或已录档，可复算）

样本：`docs/evidence/20261004_chunked_long19/project/project.bdproj` 的 **64 条逐镜查询**
（与链上 `--e1-reviews` 用的是同一批）。索引：`knowledge/`（810 条案例 / 739 条中文线索）。

| 量 | 值 | 怎么得到 |
|---|---|---|
| 查询点名的工艺词总数 | **309** | `docs/evidence/20261004-e1-vocab/e1_vocab_probe.py` |
| 其中在**整库线索**里一次都不出现的 | **153（49.5%）** | 同上（`vocab_baseline.json`） |
| 缺失最多的词 | `固定机位` 31、`景深` 23、`浅景深` 19、`越轴` 15、`逆光` 15、`侧光` 11、`留白` 11、`中远景` 8、`硬光` 5 | 同上 |
| 线索里的高频词 | `调度` 54 条线索 / 只有 1 条查询用 | 同上 |
| **召回面放宽 2.7 倍**后的 E1（top-8，跨族面板 512 条） | **48/512 = 0.0938**（top-3 是 0.0885） | `panel_top8.summary.json` ＋ `top8.jsonl` |
| top-8 里**一条 ≥4 都没有**的查询 | **26 / 64** | `top8.jsonl` |
| **完美排序**（用面板分重排 top-8）下 E1@3 的上界 | **0.25** | 同上 |

### 1.1 那 26 条"空查询"再拆一刀

| 类别 | 条数 | 含义 |
|---|---|---|
| 库里**有**这条查询点名的题材页，但 top-8 没召到 | **14** | **检索面**问题（词表错配的直接后果） |
| 库里**根本没有**查询点名的题材页 | **12** | **语料面**问题 |
| 召到了同题材页、但面板仍给 <4 | **0** | ——"召到同题材页"在这一批里就等价于"判 ≥4" |

## 2. 为什么"改排序"到不了 0.70

E1 是**精确率**：分母是返回的 `cases[]`，分子是其中判 ≥4 的条数，线 0.70
⇒ 平均每 3 条返回里要有 **2.1 条**真的能用。上表的 0.25 就是这台机器在这份语料上的
**物理上限**——任何重排、任何 IDF 调参都越不过它，因为池子里压根没有那么多相关材料。

## 3. 复算命令

```powershell
# 词表错配（零 LLM、确定性）
python docs/evidence/20261004-e1-vocab/e1_vocab_probe.py `
    --cases-dir knowledge `
    --project docs/evidence/20261004_chunked_long19/project/project.bdproj --json

# top-8 的面板读数（跨族 deepseek-chat + glm-5.3；会花 128 次调用）
$env:GLM_API_KEY = "<key>"       # 只从环境变量读，绝不入库
python tools/knowledge/e1_panel.py `
    --project docs/evidence/20261004_chunked_long19/project/project.bdproj `
    --out work/e1_diag/top8.jsonl --top-k 8 --workers 8 --json
```

## 4. 与既有台账的关系（没有翻案，只是补上分母）

* `ACCEPTANCE_STATUS.md` §八十七 记的是"**语料适配度**是下一层"。这一轮的读数同意
  "语料面是必需条件"，但补上一条**同样必需**的检索面条件（词表错配），并给出两者的
  可分离证据（1.1 的 14 / 12）。
* `ACCEPTANCE_STATUS.md` §五十二（P14-45）判"查询形状的线索**未提升**"。当时的读数是
  **6 条查询 × top-3 = 54 条**、两臂都 8/54；而这一次给出的是**机制层**的原因：
  那一版提示词虽然换了"形状"，但它的词表仍是**手写的一小串**（特写/中景/全景、推镜/
  拉镜/摇镜/跟拍/升降、低角度/俯拍、侧光/逆光、构图/留白…），**真源表**
  （`tools/kb_fetch/vocabulary.py` 的 `SHOT_SIZE_NAMES` / `MOVEMENT_ZH` / `LIGHTING` /
  `CAMERA_ANGLES` / `COMPOSITION_RULES_ZH` / `AXIS_TOPICS`）里的 `中远景`/`固定机位`/
  `顺光`/`暗调`/`骑轴`… 一个都没进去——所以"换了形状"没有解决"词表对不上"。

## 5. 下一步（两个杠杆，按依赖顺序）

1. **检索面**：把 `QUERY_SIDE_WORDS_EXTRA` ＋ `tools/kb_fetch/vocabulary.py` 的同一份词表
   注入 `tools/kb_fetch/case_search_zh.py::SYSTEM`（已落地，守门
   `tests/test_case_search_zh.py::test_the_craft_word_list_is_derived_from_the_query_side_vocabulary`），
   用同一模型重生成线索，再测 E1。**语料一个字节不动**，所以这一臂的差就是"词表"的差。
2. **语料面**：`work/cases_v2/`（`--max-cases 3804 --per-source 40`）已经把供给放进来，
   但它 **2.34 MB 单文件超了 §2.3c 的 512 KB 单文件体积门**（`size_gate.passed=false`）
   ——要落地必须先做**分片**（每片 ≤512 KB、总量 ≤20 MB，与卡片层同口径，
   `knowledge/cards_generated/` 本来就是多文件）。

**这一份证据只做诊断**：不改判据、不改门限、不改 oracle，也不把 `fail` 说成
`not_measured`。
