# 双模型复核**判否决、但暂时留在 oracle 里**的条目（2026-10-03）

## 为什么会有这个文件

`tools/holdout_review_llm.py` 的既定行为是"两个模型**一致否决**的条目从 held-out
里剔除"（提高口径质量）。2026-10-03 复核判据升到 `review/v2` 之后，177 条
`needs_human` 里有 **2 条**被一致否决，剔除本身是对的——但它们各自是**某一张卡的
唯一一条条目**，剔掉会让门⑥（来源覆盖）当场变红：

```
gate_6_sources: missing_cards = ['gen_cine_0087', 'gen_prod_0030'] → fail
```

正确的处置是**给这两张卡重新派生一条合规条目**，而不是"把坏的留着"或"把卡挪出
分母"。重派生要走 GLM 通道（`tools/holdout_pool.py --provider glm --only-cards @…`，
这是本来就是为这种缺口写的支路），**但此刻 GLM 的余额已耗尽**：

```
glm 调用失败：HTTP 429: {"error":{"code":"1113","message":"余额不足或无可用资源包,请充值。"}}
```

## 现状（如实记账，不是收尾）

| id | 卡 | q | 面板一致否决的理由 |
|---|---|---|---|
| `hq_1126` | `gen_prod_0030` | `光线=低调；强度=high；禁光线=正面光` | A：知识卡讲恒流灯开路，与光线/低调/强度完全无关，边对不上 q；B：期望与知识卡内容完全无关，属幻觉 |
| `hq_1196` | `gen_cine_0087` | `光线=暖光；强度=mid；禁光线=正面光` | A：卡片讲染色前禁过放映机，与光线/强度/禁光线完全无关；B：卡讲放映机禁忌，期望写光线 |

两条**目前留在** `fixtures/knowledge_holdout.jsonl` 里，且**不带 `review` 记录**
（它们不是"复核过"，是"复核过并且判否决，但因为覆盖约束暂时不能删"）。因此
门⑦ 的计数是 **169/177**（要求 ≥120），门⑥ 的 `missing_cards` 回到 0。

## 下一轮要做的（一条命令）

```bash
python tools/holdout_pool.py --provider glm --only-cards @work/_gap_cards.txt \
    --out work/_gap_pool.jsonl --report work/_gap_pool.json \
    --partial work/_gap_partial.jsonl --progress work/_gap_progress.json
```

（`work/_gap_cards.txt` 就是那两张卡的 id，已经落盘。）拿到新条目之后：

1. 用 `tools/holdout_review_llm.py --resume` 判新条目；
2. 把 `hq_1126` / `hq_1196` 换成新条目（这两条的卡不变，所以门⑥ 的覆盖不受影响）；
3. 重跑 `tools/check_holdout.py … --reviewer-classes human,llm-panel` 与
   `powershell -File tools\run_tests.ps1`。

**没有**把这两张卡挪出 `card_scope.json` 的分母——那会把"没覆盖"改成"不用覆盖"，
是改验收标准。

## 2026-10-03 17:5x 的第二次复核（`deepseek-chat` ＋ **`glm-5.3`**，43 条）

GLM 充值到账后，对"意图轴落地 + 第二轮独立标注"新增的 41 条重跑了双模型面板
（`work/holdout_panel_v3.json`，判据指纹仍是 `review/v2` 的
`7d95fbc44af177a772b2e10fea903ea7bacb106edaaca92b1b604fe76cc861e0`，与既有 169 条**同一份**）。
结果：**37 条一致接受 / 4 条分歧 / 2 条一致否决**。

* 一致否决的 2 条，**还是** `hq_1126` 与 `hq_1196`（上面那份表里的两条）——
  换了第二族模型（`glm-5.3` 取代 `glm-4.7`）之后结论不变。它们的处置仍然卡在
  同一条上：**要先把替换条目派生出来**，而这一步现在**可以做**了（GLM 有额度），
  只是本轮把额度优先给了 Q5 的 176 条独立标注（见 `Q5_DECISION_v1.md`）。
* 4 条分歧（待人类裁决）：`hq_0970`、`hq_1057`、`hq_1882`、`hq_1948`。
  其中 **`hq_1057` 恰好在 Q5 的实读数里占了 31 对中的 8 对**——它是不是"卡里真有
  那几个运镜期望"直接决定 Q5 那个 0.7419 的可信度。这条分歧因此**优先**。
* 复核记录**已并回** `fixtures/knowledge_holdout.jsonl`（41 条，逐字带上
  `review.source{models,prompt_sha256}`）。门⑦ 现在是 **210/120**（needs 212），
  门①–⑩ 仍全 pass（证据 `docs/evidence/20261003-182957/`）。
