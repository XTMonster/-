# C4：入库索引「未佐证槽位」的**记账口径机器固化**（P8-T1）

**run-id**：`_v15_stage8/c4_ledger`
**卡**：`执行文档v1.5/TECH_SOLUTIONS.md` §三 **C4**（✅ 本版直接做）
**卡定义**：`执行文档v1.5/dispatch_graph.json` 的 `P8-T1`
**日期**：2026-10-07
**性质**：口径校验器（诊断工具，**不是门**）＋ 它的单测。判据本身一个字未动。

---

## 1. 要守的是什么

`tools/knowledge/attestation.py` 量的是「**这条边的每个槽位，能不能在它自己的来源卡
正文里找到依据**」。它的读数一旦被下游转述，有三种已经反复出现过的歪法：

| # | 歪法 | 正确口径 |
|---|---|---|
| ① | 把 `unattested` 说成「**编造**」 | 它是**下界**：卡可以**蕴含**一个取值而不写出它（"把画面倒过来看"蕴含"检验平衡"）⇒ 一律写「**未被来源佐证**」 |
| ② | 只报一个分母 | 必须**并列**：可检分母 **1593**（`attested + unattested`）→ **0.2078**；全量分母 **1938** → **0.1708** |
| ③ | `not-checkable` 悄悄上涨 | 钉住上界 **≤ 345**（这一桶是"词表自己就是桶名"，如 `intensity:mid` / `avg_shot_len:>8s`） |

## 2. 交付物

| 文件 | 作用 |
|---|---|
| `tools/knowledge/attestation_ledger.py` | 校验器：读 `attestation.py --json` 的产物，逐条验不变量，违规即非零退出 |
| `tests/test_attestation_ledger.py` | 12 条单测：正常/违规各分支 ＋ 仓库实测报告 ＋ **现算一遍**（挡住"报告是手改的"） |
| `docs/evidence/_v15_stage8/c4_ledger/attestation_report.json` | 本次现算的实测报告（判据真源：`attestation.py`） |
| `docs/evidence/_v15_stage8/c4_ledger/ledger.json` | 校验器的机器可读判决 |
| `docs/evidence/_v15_stage8/c4_ledger/ledger.stdout.txt` / `pytest.stdout.txt` | 逐字输出留档（UTF-8） |

校验器**不重算**判据（那是 `attestation.py` 的事），它只对**报告本身**做口径校验：
三桶齐全且相加等于全量槽位、`checkable_slots` 等于 `attested + unattested`、
可检槽位与上界对得上钉住值、两个分母的计算值都出现、以及**措辞**（同句内没有否定词
才算违规——所以「未被佐证 ≠ 编造」这种正确写法不会被误伤）。

## 3. 实测（命令与真实输出）

```
python tools/knowledge/attestation.py --json docs/evidence/_v15_stage8/c4_ledger/attestation_report.json
python tools/knowledge/attestation_ledger.py --report docs/evidence/_v15_stage8/c4_ledger/attestation_report.json --json docs/evidence/_v15_stage8/c4_ledger/ledger.json
```

`ledger.stdout.txt` 逐字（退出码 **0**）：

```
attestation 记账口径校验：pass
  判据版本 : attest/v1｜边数 : 638
  三桶     : attested 331 / unattested 1262 / not-checkable 345（上界 345）
  可检分母 : 1593 -> share 0.2078
  全量分母 : 1938 -> share 0.1708
  措辞     : `unattested` ＝ 未被来源佐证（下界），**不是**『编造』
```

```
python -m pytest tests/test_attestation_ledger.py -q
-> ............                                                             [100%]
```

## 4. 两个分母的并列读数（**本卡的承重墙**）

| 分母 | 值 | 来源 | share |
|---|---|---|---|
| 可检槽位（`attested + unattested`） | **1593** | `attest/v1` 现算 | **0.2078** |
| 全量槽位（含 `not-checkable`） | **1938** | 331+1262+345 | **0.1708** |

同一批数换分母就换说法 ⇒ 凡引用这两个读数处必须**同时**给出分母。

## 5. 未验证 / 边界（如实记）

1. **钉住值是「这一代」的**：`PINNED` 里的 638 / 1593 / 1938 / 345 是 2026-10-07
   入库索引（`attest/v1`）的实测值。**索引换代**会让校验器红——这是故意的（换代必须按
   `docs/knowledge/REGEN_LOG_TEMPLATE.md` 显式登记），不是 bug。
2. **措辞检查是句子级的**：它挡"这些槽位是编造出来的"这类断言，挡不住更绕的改写
   （例如把 `unattested` 换个名字报出去）。**这是防回退的下界，不是自然语言理解的替代品。**
3. **本卡没有、也不该**改 `attestation.py` 的判据：3 个桶的分界、`surface` 的匹配口径
   一字未动（`git status` 里 `tools/knowledge/attestation.py` 未被改动）。
4. 本卡没有触碰索引、夹具、`fixtures/**`（C4 只是记账纪律，**不是**数据修订）。
