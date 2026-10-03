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
