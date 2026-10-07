# `20261007-224409` — 22 条裁决"执行尝试 + 回滚"之后的**完整链**读数（35/35 步）

这一份是 `tools/run_tests.ps1` 在下面这串动作**之后**的一次完整运行：

1. 按用户 2026-10-07「跑吧」尝试执行那 22 条裁决（两条路都试过，见
   `docs/evidence/20261007-v15-oracle-gen3/README.md`）；
2. 两条路分别撞在 **门③（词表盲点）** 与 **门⑥（可断言卡无条目）** 上；
3. 因此**回滚**到已验证状态（索引 `e5213e1b…` / held-out `e3e6bac2…` / gen2），
   只留下"可复用的两件工具 + 实验读数"。

## 链上读数

| 项 | 值 |
|---|---|
| 链规模 | **35/35**（探针 31 支 ＋ spec/golden 漂移、pytest、契约冒烟、headless 四步） |
| `python -m pytest` | **2808 passed / 1 skipped / 0 failed** |
| 门①–⑩ | `holdout_gates.json`：**`overall: pass`**（`generation: gen2`） |
| attestation（诊断） | 0.8682；451/638 条边完全被自己的来源卡佐证 |
| 红线 | **唯一红 = `RK-13`**（E1 ≥ 0.70）——与换代前同一条已结案红线 |

## 这一份**不**证明的事

* 不证明那 22 条判决已经执行——它们**没有**（回滚了，理由见上面第 2 点）；
  判决本身仍如实挂在 `docs/evidence/20261007-v15-zerocand-verdict/verdict.json`（`apply: false`）。
* 不证明 E1 达标（它照旧红）。
