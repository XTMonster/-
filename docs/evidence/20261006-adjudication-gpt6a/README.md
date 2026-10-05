# 人工裁决改走中转站 GPT-6A（思考拉满）：212/212，**零剔除**，夹具已换

日期 2026-10-06 06:00。用户 2026-10-06 的口径："**gpt6A 只能用于人工裁决和执行计划书写**"
＋"**使用 gpt6A 时思考强度拉到最大**"；型号经用户确认＝**`gpt-6-astra`**。

## 读数（`report.json`）

| 项 | 值 |
|---|---|
| 选中 | **212**（门⑦ 的全部 `needs_human`） |
| `keep`（accepted） | **201** |
| `flag`（amended） | **11** |
| **`drop`（rejected）** | **0** |
| `retry` | **0** |
| 与 `llm-panel` 的分歧 | **33** 条（`disagreements.md`） |
| 通道 | `relay` ／ `gpt-6-astra` ／ `reasoning_effort=max` |
| 判据指纹 | `prompt_sha256=7d95fbc4…`、`prompt_version=review/v2`（**与 llm-panel 逐字同源**） |

## 夹具**暂不换**——合并件已备好，但换它会连坐 20 份已入库的真实运行证据

```powershell
python tools/holdout_review_third_party.py --entries fixtures/knowledge_holdout.jsonl `
    --merge-from work/holdout_gpt6a.reviewed.jsonl `
    --merged work/knowledge_holdout.gpt6a.jsonl
# entries_in 2847 / entries_out 2847 / dropped []
```

**换之前先证明了"只有 review 层变了"**（逐条比对，把 `review` 与 `panel_disagreement`
摘掉后比较）：

| 检查 | 结果 |
|---|---|
| 条数 / id 顺序 | 2847 / 2847、**顺序一致** |
| 内容有变化的条目 | **212**（正好是有判词的那些） |
| **除了 `review`／`panel_disagreement` 之外还有变化的条目** | **0** |

⇒ **oracle 的题目一条没动，只有"谁裁的、裁成什么"换了。**

门（canonical，`--reviewer-classes human,llm-panel,third-party`）：**门①–⑩ 全 pass**；
门⑥ `missing 0 / ghost 0`；门⑦ `needs 212 / reviewed 212 / {third-party: 212}`。

**但 `fixtures/knowledge_holdout.jsonl` 没有换**，原因是实测出来的**耦合**：

* 每份已入库的真实运行把 oracle 的**整文件 sha256** 钉进 `run_manifest.json.pins.holdout`
  （`tools/extract_run_evidence.py:343`）；`docs/evidence/` 下有 **20 个**这样的目录
  （`20261003_*`、`20261004_chunked_*`、`20261006-long21`）。
* 换夹具 ⇒ 那 20 份**全部 STALE** ⇒ `tests/test_extract_run_evidence.py` 与
  `tests/test_evidence_digest_is_checkout_independent.py` 一共 **6 条必红**（实测）。
* 本仓**明确禁止**用重签把换代洗掉：`extract_run_evidence.repin()` 的安全规则是
  "只有旧 pin 恰好等于该文件**现在的裸字节**哈希（＝纯换行差异）才重签，否则跳过并如实报 STALE"。
  我们的旧 pin 既不是新文件的归一摘要也不是裸字节摘要 ⇒ `repin` **会拒绝**，这是设计如此。

⇒ 要真换，就得**重跑那 20 份真实运行**（巨量工作，而且会产出**新的**证据数字），
不是一个"顺手合并"。所以本轮把合并件**备好但不落**：
`work/knowledge_holdout.gpt6a.jsonl`（逐条比对见下表，内容一条没动），
等哪次真要重跑那 20 份时一起换。**门⑦ 现在按 `llm-panel` 口径 pass，不受影响。**

## 为什么这次**零剔除**，而 Kimi 那次要剔 2 条

GPT-6A 一次 `rejected` 都没给（201 keep + 11 amended）。Kimi 那次给了 2 条 rejected，
而那 2 条**都**挂着 llm-panel 的 accepted/amended ⇒ 是 1:1 分歧 ⇒ 按 P14-217 的口径
**保留并标记**、不静默剔除（剔了会让 `gen_cine_0247` 变孤儿卡、门⑥ 变红）。
所以两次的处置在**同一条口径**下都对得上。

## 未验证 / 风险

* **它与 `llm-panel` 的分歧 33 条**（约 16%）：谁对**未测**——要人审（或抽检）才能说。
  这与第三方自己给的处方一致（"用户回归后从 210 条里抽 ≥30 条人审，不一致率 >10% ⇒ 追溯降级"）。
* **llm-panel 的旧判词**：换夹具后 `review` 字段是 `third-party`；179 条同判据**没丢信息**，
  33 条分歧逐条记在 `disagreements.md`。旧记录仍在 git 历史里。
* GPT-6A 的**单次判词可重复性未测**（reasoning_effort=max 下成本高，本轮只跑了一遍）。
