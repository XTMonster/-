# 门⑦ 换代 gen1→gen2：**输入工件已具名、已 pin、夹具字节未动**（落地第一步）

日期 2026-10-06 23:5x。裁决原文：
`docs/evidence/20261006-gate7-disambiguation/规格一致性.json`（159.7 s，`finish_reason=stop`）——
**"pin 绑'运行↔输入'，gate 输入一旦含增量层即是 gen2，与旧夹具字节未动无关；
'逐位命中'只证未篡改，不证切题。增量层必须具名为被 pin 的独立输入工件并登记 gen1→gen2，
否则是无 pin 的影子输入。"**

## 一、这一步做了什么（只有三份工件 ＋ 一个可复算的生成器）

| 工件 | 内容 | sha256（前 32） |
|---|---|---|
| `fixtures/knowledge_holdout.third_party.jsonl` | **第三方代裁层**：212 行，每行 `{entry_id, verdict, reviewed_by, reason, fix, agreement, source}` | `eda380e4c4dd54f58354384bb0fbe8a5` |
| `fixtures/knowledge_holdout.third_party.manifest.json` | 这一轮的产出方自述（模型／提示指纹／跑的时间／计数） | `b1a99fe4483ea393603ce0334133ee7a` |
| `fixtures/knowledge_holdout.generations.json` | **换代登记**：gen1 → gen2，两代 pin 的 `holdout` **同一枚 sha256** | `0c2473014ca9336bed55719a5cee0ec8` |
| （生成器）`tools/knowledge/build_third_party_layer.py` | 从合并件抽出这一层；`--check` 重算比对，漂移即非零退出 | — |

**"夹具字节未动"是可验证的**：`fixtures/knowledge_holdout.jsonl` 的 sha256 =
`e3e6bac24d9efcfea8c5f1b5f1f7fd65…`，gen1 与 gen2 的 `inputs.holdout` **逐位相同**；
gen2 只是多了一个 `inputs.third_party`。

守门：`tests/test_third_party_layer.py`（4 条）——层能从源**逐位复算**、gen1/gen2 pin 同一份夹具、
计数如实、**绝不冒充 `human`**。

## 二、顺手纠正一个**口径错误**（很重要）

台账与上一轮判词里引的是"**keep 201 / flag 11 / drop 0**"。**这一轮的实物不是那样**：

```
work/holdout_third_party.json → counts: {"selected": 212, "keep": 194, "drop": 2, "flag": 16, "retry": 0}
```

⇒ **`drop` 不是 0，是 2**（194 accepted / 16 amended / 2 rejected）。
"`drop 0` ⇒ 标签零变化"这个前提**不成立**——那 2 条 rejected 是**实质改动**。
（早先那组 201/11/0 属于**另一轮**第三方代裁，不能与这一轮混用。）

**但这不改变裁决**：最终裁定取的是 **B 的原则**——"输入集合的同一性"定义"代"，
与"某个文件字节是否变动"无关。所以换代登记照做；受影响的只是"**层不是纯增量**"这一点，
已写进 `diff_note` 与下面的未验证清单。

## 三、**还没做**的三件（裁决点名了，按顺序来）

1. `tools/check_holdout.py` 加 `--third-party <层>`，让门⑦ **按代计数**（并事前锁定新的期望数）；
2. 那 **6 条**按"pin == 夹具 sha"断言的测试改成**按代断言**
   （裁定给的最小心跳：断言每份运行解析到**已登记代**、链头 pin 覆盖**旧夹具＋增量层**）；
3. **新开一次 gate 运行**——它是 gen2 的第一份证据，**不是**对 gen1 的"重跑一次"。

在 1–3 落地之前：`fixtures/knowledge_holdout.jsonl`、`tools/check_holdout.py`、
那 6 条测试、20 份历史 `run_manifest.json` 的 pin **全部原样**（一个字节没改）。

## 四、未验证 / 边界（如实挂）

1. **19 份 `superseded` 是否让 Q1/Q2/Q4/Q6b 失据**——裁定说 bundle 里没有判据原文、**不能定案**；
   实施时按"按份计数 ⇒ 标 `generation: 1`"处理，并把这条写进那一批的证据里。
2. 层里 **16 条 `amended`** 的 `fix` 文本**没有**被本轮拿去改夹具（那属于第 1 步之后的事）；
   ⇒ 现在这一层是"**输入工件**"，不是"已生效的标签变更"。
3. 生成器读的源 `work/knowledge_holdout.third_party.jsonl` 在 **gitignore 区**（可重建、未入库）
   ⇒ 复算路径是"**有那份源才能 `--check`**"；源本身不随库走。
