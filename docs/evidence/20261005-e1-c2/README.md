# L3 索引定版：500 条（覆盖 72.6%）——E1 **0.1441**，四臂实测选出来的

> 结论先行：发货索引从"810 条案例 / 731 条线索（E1 ＝ 0.0920）"换成
> **"500 条案例 / 363 条线索（E1 ＝ 0.1441）"**，**判据、门限（0.70）、
> oracle 一个字没动**。选型不是靠推理，是靠**五个臂各跑跨族面板**选出来的；
> 其中"把语料加深"那一臂被实测**判成回退**（0.0469）。

## 1. 五个臂（同一部片子、同一批 64 条逐镜查询、同一面板 deepseek-chat ＋ glm-5.3）

| 臂 | 案例 | 线索 | 覆盖（守门 ≥50%） | 来源痕迹 | E1 | 重复 |
|---|---|---|---|---|---|---|
| A：发货原状（旧提示词线索） | 810 | 731 | 90.2% | ✓ | **0.0920**（53/576） | 3 次 |
| B：810 ＋ **词表同源**新线索 | 810 | 363 | **44.8% ✗** | ✓ | 0.1198（69/576） | 3 次 |
| C：只留有线索的案例 | 363 | 363 | 100% | **✗ 213 个来源失去痕迹** | 0.1597（92/576） | 3 次 |
| **C2（发货）**：只留有线索的案例＋**每条来源保一条最后痕迹** | **500** | **363** | **72.6%** | **✓** | **0.1441**（83/576） | 3 次 |
| D：把语料加深到 1,097 条 | 1,097 | 657 | 59.9% | ✓ | **0.0469**（9/192） | 1 次 |

* A 与 C2 的合并比较：**z ＝ 2.74**（p ≈ 0.006）——这次不是噪声。
* 噪声底（A/B 各 3 次）在 `docs/evidence/20261004-e1-vocabfix/noise_floor.json`：
  同一臂的重复散布约 ±0.008（A：0.0833–0.0990）。

## 2. D 臂为什么是**回退**（这一轮最有价值的一条）

`build_cases --require-clue …` 把"**先注线索、非空才入库**"落地之后，覆盖从
44.8% 升到 59.9%、`size_gate` 过、`test_source_traces` 过——**所有结构门全绿**，
而 **E1 从 0.0920 掉到 0.0469**。

道理在判据本身：`E1` 是**精确率**（分母是"返回的那几条"，top-3）。加进来的深层候选
没有把相关材料顶上去，反而把 top-3 里的位置**挤走**了。联合会诊里 DeepSeek 侧
一句判词说中了这件事：

> 覆盖门量的是行数占比，不是检索命中率——59.5% 可能是假覆盖。

**可复用的教训**：覆盖门（`len(lines) >= 0.5 * len(cases)`）只能证明"索引与线索
同代且不残缺"，**不能**用来推断"检索变好了"。任何"扩库"都必须用**同一批查询**
跑一次 E1 才准说话——这一轮就是靠这条路把 1,097 条那一版拦下来、换成 500 条。

## 3. C 为什么不能直接发货

C（只留有线索的案例）E1 最高（0.1597），但它让 **213 个来源**在
`sources.yaml` 里、而"卡片 ∪ 案例"里一条都没有——`tests/test_source_traces.py`
（反向门：清单里每条来源都要留痕）当场红。这些来源是**只喂 L3 的现代影评**
（Animation Studies 等），它们没有卡片，痕迹全靠案例。

修法不是往 `NAMED_EXCEPTIONS` 里塞例外，而是**给闸门加保护带**：每个这样的来源
保**一条**（字母序第一条）——这就是 C2 的 500 条。保护带必须**按 id**
（`--require-clue-keep`）：按下标（`--require-clue-after 810`）在
`--max-cases` 变了之后会换掉历史案例（实测 149 条，见 §90.2）。

## 4. 联合会诊（`reviewed_by: llm-panel`，四栏）

`panel_impl.md` 是 `work/_panel_batch/panel.md` 的原样副本：DeepSeek × GLM-5.3，
同一份包、同一个角色（实现顾问）。**这一轮 GLM 侧的正文是空的**
（`finish_reason=length`、`reasoning_tokens=31301`、`completion_tokens=32768`，
见 `panel_impl.glm.usage.json`），按契约记 **`unparsed` / `complete=false`**——
**一侧缺席不算同意**。DeepSeek 侧 5 条 findings 逐条在仓库里证过：

| DeepSeek 侧 finding | 仓库里的判词 |
|---|---|
| 覆盖门是行数占比、不是命中率；59.5% 可能是假覆盖 | **证实**（D 臂 E1 ＝ 0.0469，见 §2） |
| 闸门与写盘必须**同一份判据**（不然留下无键的悬空案例） | **证实并修掉**：`apply_clue_gate` 与 `attach_clues` 都走 `classify`，守门 `tests/test_cases_corpus.py::test_the_gate_and_the_writer_share_one_predicate` |
| 重签必须在最终集合确定之后 | **证实**（`attach_clues` 排在 `write_outputs` 之后） |
| manifest 要按过滤后集合重算 | **证实并修掉**（`recount()`；`_case_domains` 不进 manifest） |
| E1 提升未达 5% 显著，不能当"扩库即改善" | **证实**（D 臂回退；B 臂池化 z＝1.53） |

## 5. 复算

```powershell
# 发货索引（500 / 363）
python -m tools.kb_fetch.build_cases --max-cases 810 `
    --require-clue work/armB/cases/search_zh.part-000.jsonl `
    --require-clue-keep work/protect_traces.jsonl --out-dir knowledge

# E1（三次；本目录 reviews.jsonl 是三者的合并）
python tools/knowledge/e1_panel.py `
    --project docs/evidence/20261004_chunked_long19/project/project.bdproj `
    --cases-dir knowledge --out <out> --top-k 3 --workers 4
```

`work/protect_traces.py` 生成保护表（每个"没有卡片"的来源取字母序第一条案例）。
**词表同源**那一步（把查询侧真源词表注入线索提示词）在
`docs/evidence/20261004-e1-vocabfix/` 有独立的 A/B 与噪声底。
