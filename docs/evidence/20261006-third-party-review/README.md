# 第三方裁定（Kimi K3）覆盖**全部 212 条 `needs_human`**——门⑦ 从此有了"人审口径"的实体

日期 2026-10-06 03:39。用户 2026-10-06 授权："**这个裁定是指代替我做人工审核判断**"
（ADR-0015）。判定器是 **Kimi K3**，判据**逐字复用** `holdout_review_llm.SYSTEM`（`review/v2`），
所以它与既有 `llm-panel` 的判决**逐字可比**。

## 读数（`report.json`）

| 项 | 值 |
|---|---|
| 选中 | **212**（= 门⑦ 的全部 `needs_human`，**不是只补空缺**） |
| `keep`（accepted） | **194** |
| `flag`（amended） | **16** |
| `drop`（rejected） | **2** |
| `retry`（判不出） | **0** |
| **与 `llm-panel` 的分歧** | **27** 条（清单 `disagreements.md`） |

记录形状（每条）：`reviewed_by: "third-party"` ＋ `source{model=kimi-k3, prompt_sha256,
prompt_version=review/v2, adjudicator_provider=kimi, authorized_by=user-2026-10-06:…}`。
**没有一条写成 `human`**——这是 ADR-0015 的红线。

## 它改变了什么（以及没改变什么）

* **改变**：门⑦ 此前只有两种口径（`human 0/212`、`llm-panel 210/212`）。现在多了第三种：
  **`third-party 212/212`**，而且它是**全量**（不是补齐），所以能与 `llm-panel` 逐条对拍。
  `tools/check_holdout.py::review_class()` 只在**显式点名**时才认它
  （`--reviewer-classes human,llm-panel,third-party`）；默认口径仍是协议原样 `("human",)`。
* **没改变**：判据 / 门限 / 阈值一个字没动；`human 0/212` 那笔账**仍然挂着**，
  不许读成"人审已通过"（第三方自己也这么判：D12 维持 C）。
* **风险（第三方自己点的）**：这 212 条判词与人审的**一致率未知**。用户回归后应抽
  **≥30 条**人审；不一致率 **>10%** ⇒ 这些 `third-party` 记录**追溯降级**、重审全部 212 条。

## 合并试算：门⑦ 过，但**甩出 1 张孤儿卡**（所以夹具还没换）

合并入口是本工具新增的**离线**模式（不联网）：

```powershell
python tools/holdout_review_third_party.py --entries fixtures/knowledge_holdout.jsonl `
    --merge-from work/holdout_third_party.reviewed.jsonl `
    --merged work/knowledge_holdout.third_party.jsonl
# -> entries_in 2847 / entries_out 2845 / dropped ["hq_0495","hq_1057"]
```

拿合并件跑 canonical 门（`--reviewer-classes human,llm-panel,third-party`）：

| 门 | 原夹具 | 合并件 |
|---|---|---|
| **⑦ 人审** | pass（`needs 212`／已裁 210，`llm-panel`） | **pass**（`needs 210`／已裁 **210**，`{third-party: 210}`） |
| **⑥ 来源覆盖** | pass（`missing 0`） | **fail**（`missing_cards ["gen_cine_0247"]`） |

**根因**：两条被判 `rejected` 的条目里，`hq_1057` 是卡 `gen_cine_0247` 的**唯一**一条
期望；剔掉它，那张卡就没有任何条目 ⇒ 门⑥ 的 `missing_cards` 记 1 条。
（`hq_0495` 覆盖的 `gen_story_0289` 另有 1 条，剔掉不伤覆盖。）

两条驳回**都站得住**（原文）：

* `hq_0495`：「卡讲相邻镜景别差异防跳切，期望却写短节奏/短镜长，与卡完全无关」；
* `hq_1057`：「卡主张持续运动、避免固定，`q`/`must`/`top1` 却取运镜=固定，与卡意相反
  且与 `expect_movements` 矛盾」。

⇒ **不能就这么换夹具**：按本仓纪律（不许为让某条过而弄坏另一条），
正确顺序是**先给 `gen_cine_0247` 补一条合格期望**（就是 `holdout_review_llm` 当初
"剔掉一条 ⇒ 支撑掉线 ⇒ 补跑一轮"的同一条路），再整体换。
本目录保留**合并件与门读数**作为证据；**`fixtures/knowledge_holdout.jsonl` 一个字没动**。

## 未做 / 未验证

* **孤儿卡的补条未做**（`gen_cine_0247`）。
* **夹具未换**：门⑦ 在原夹具上仍按 `llm-panel` 口径 pass；`third-party` 口径的
  pass 只在合并件上验证过。
* 未验证：Kimi K3 只接受 `temperature=1`，**单次判词的可重复性未测**（无重复跑）。
* 未验证：27 条分歧里有多少是 Kimi 对、有多少是 `llm-panel` 对——那要人审（或抽检）才能说。
