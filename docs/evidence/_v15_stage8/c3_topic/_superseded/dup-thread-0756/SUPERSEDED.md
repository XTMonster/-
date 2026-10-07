# 这一套 C3 产物已被 `../../../c3_topic/` 的正本取代（**不是删除，是挪位**）

**挪位人**：主线（阶段 8 收口），2026-10-07 08:1x。
**理由**：`_v15_stage8/c3_topic/` 在 07:56–07:59 之间**同时**收到两套 C3 产物
——本目录这一套（07:56，一条并行线程写的 `diagnose_topic.py` ＋ `README.md` ＋
`topic_accuracy.json` ＋ `topic_inventory.json`）与正本那一套（`p8t2_c3` 写的
`topic_field_audit.*` ＋ `README_topic_field_audit.md`）。
同一张卡（P8-T2）留两套会让同一份证据被数两遍，而**两套的承重结论同向**：

| | 本目录（旧线程） | 正本（`p8t2_c3`） |
|---|---|---|
| `topic` 的分辨率 | 576 个 `chunk_id` / 108 个来源各自只有 1 个 `topic` | 同（逐卡判读 82 张：faithful 54 / partial 7 / mislabeled 21） |
| 机械预读 88 的拆解 | **65 mismatch / 23 unknown / 2 ok** | **55 mismatch / 33 unknown / 2 ok** |

唯一差异是**口径**：一行"既多来源、又部分来源没有 `topic`"时，旧线程记
`mismatch`（65）、正本记 `unknown`（23→33），正好 **10 行在两个桶之间搬家**
（55+10=65、23+10=33；正本的口径见 `README_topic_field_audit.md` 第 5 节的
逐项对账）。两套都**没有**判据改动。

**为什么保留而不是删**：仓库纪律是"挪位而不是清除"（与
`docs/evidence/20261007-grounding-sample90/_superseded/` 同款），删掉会让
"当时到底算过什么"无法回查。**正本是 `../../` 那一套**；本目录只作历史。

**没有被动过的东西**：`knowledge/`（索引、卡片、夹具）、`tools/kb_fetch/`、
任何判据/阈值/门限。
