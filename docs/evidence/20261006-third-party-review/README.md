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

## 未做 / 未验证

* **还没把这批判词并进 `fixtures/knowledge_holdout.jsonl`**：门⑦ 读的是**夹具里**的
  `review` 字段（`llm-panel` 那 210 条当初就是这么进去的）。本目录只是产物；
  **合并（含 2 条 `drop` 的剔除）是下一步**，合并后才谈得上"门⑦ 在 third-party 口径下 pass"。
* 未验证：Kimi K3 只接受 `temperature=1`，**单次判词的可重复性未测**（无重复跑）。
* 未验证：27 条分歧里有多少是 Kimi 对、有多少是 `llm-panel` 对——那要人审（或抽检）才能说。
