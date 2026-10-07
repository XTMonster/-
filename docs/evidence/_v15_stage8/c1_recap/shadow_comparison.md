# 影子复判对照：机械重绑 vs 现状（C1 同口径，同一判官）

**目的**：qwen3.8-max-0902 三侧会诊一致要求"**先影子再动手**"，且红队点名
"**门①–⑩ 全绿不构成'绑定修好'的证据**，唯一成功读数是 C1 同法重判"。
本文件就是那条读数。

**方法（两次**完全同口径**）**：

| 项 | 真实那次 | 影子那次 |
|---|---|---|
| 样本 | 90 槽位（同一批，同 `edge_id`+`kind:取值`） | **同一批 90 条**，只把 `sources` 换成影子版 |
| 题包模板 | `make_grounding_batches.py` 的 HEADER/逐卡展示 | 同一模板（`work/_q_grounding_shadow_batch*.md`） |
| 判官 | `qwen3.8-max-0902` ＋ `thinking.level=max` ＋ **`reasoning_effort=max`** | **同上** |
| 批数 | 12（每批 8） | 12（每批 8） |
| 汇总器 | `tools/knowledge/grounding_classify.py` | **同一工具**（`--sample-dir …/shadow_judge`） |

## 结果

```
真实索引： total=90  corrupt=67 (0.7444)  {"hidden": 23, "wrong_card": 66, "wrong_value": 1}
影子索引： total=90  corrupt=37 (0.4111)  {"hidden": 53, "wrong_card": 37, "wrong_value": 0}
```

**判读**：

1. **机械重绑真的修好了主题级错配**：`wrong_card` **66 → 37**、`hidden` **23 → 53**
   ⇒ 30 条从"挂错卡"变成"卡讲对了只是没写出该词"。这不是自证——判官看的是**卡正文**，
   而重绑换的正是"给判官看哪几张卡"。
2. **但它不是万能药**：仍有 **37/90** 判 `wrong_card`（`corrupt_share` 仍在
   `corrupt-dominated` 那一支）。这些是"候选卡只是**提过这个词**、主题仍不是它"的情形——
   正好印证红队那句"门全绿 ≠ 绑定修好"。
3. **对照的诚实边界**：影子只做了 union-add（不删原来源卡）；两次判官**同一模型同一档**，
   所以差异只能归因于 `sources` 的变化，不是判官漂移。

> **这一条第 3 款在 2026-10-07 晚些时候被自己的第三次复判证伪了，原文保留不动**：
> 落库那一版（`rebind/v2`，候选池收窄到"重绑前就有边"的卡）用**同一判官、同一模板、
> 同一批 90 条**再判一次，得到 `corrupt=43 (0.4778)`，与影子版 `37 (0.4111)` 相差 6 行——
> 但**逐行比较有 16 行翻转，而且有来回**（11 行 `hidden→wrong_card`、5 行 `wrong_card→hidden`）。
> 判官**不是**逐字可复现的，所以"两次读数之差只能归因于 `sources`"这句话不成立：
> 小于那次翻转幅度的差值（这里 6 行）**分不出发是真实代价还是判官漂移**。

## 第三次复判（`rebind/v2`，真正落库那一份）

```
真实索引（重绑前）： total=90  corrupt=67 (0.7444)  {"hidden": 23, "wrong_card": 66, "wrong_value": 1}
影子（rebind/v1，全池）： total=90  corrupt=37 (0.4111)  {"hidden": 53, "wrong_card": 37, "wrong_value": 0}
落库（rebind/v2，保范围）： total=90  corrupt=43 (0.4778)  {"hidden": 47, "wrong_card": 43, "wrong_value": 0}
```

产物：`docs/evidence/_v15_stage8/c1_recap/v2_judge/`（组题 `work/_v2_rejudge_prep.py`，
90 条里有 **20 条**的来源卡与影子版不同）。判读：

1. 主结论不变：**主题级错配的修复保住了大约七成**（0.7444 → 0.4778）。
2. 收窄候选池的**可判定代价**在别处、而且很窄：11 个槽位（全是
   `composition_rule:lead_room`，唯一候选只有手写卡 `comp_lead_room`）掉回"零候选"，
   零候选总数 199 → 210；门⑥ 因此从"11 张孤儿卡"回到 `edge_backed_without_entry = 0`。
3. 单次读数差 6 行**不作为证据**（见上面那条证伪）。

## 产物

| 项 | 路径 |
|---|---|
| 影子索引 | `work/_shadow_index/hypergraph.edges.jsonl`（**只在 work/，未进库**） |
| 影子样本 | `work/_grounding_shadow_sample90.json` / `…/shadow_judge/sample90.json` |
| 影子题包 | `work/_q_grounding_shadow_batch{1..12}.md` |
| 影子判词 | `docs/evidence/_v15_stage8/c1_recap/shadow_judge/batch{1..12}/三分类.json`（逐批 usage 同目录） |
| 影子汇总 | `docs/evidence/_v15_stage8/c1_recap/shadow_judge/三分类汇总.json` |
| 脚本 | `work/_shadow_recheck.py`（候选）／`_shadow_rebuild.py`（影子索引）／`_shadow_rejudge_prep.py`（题包）／`_run_grounding_batches.py`（批跑） |

## 结论与下一步

* **够格 promote**：读数改善幅度大（0.7444 → 0.4111）且方向与机制解释一致；
  用户已批准"**换卡**"这一动作 ⇒ 把影子（去掉临时字段）落成新索引，并按 A6 登记换代。
* **仍未解决**：① 剩 37/90 的主题级错配；② **199 个零候选槽位**（`axis_side` 一族 10/11）
  只能**语义裁决或删边** —— 这是**新的裁决点**，不自行决定。
