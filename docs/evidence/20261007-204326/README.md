# `20261007-204326` — `rebind/v2` 换代后的**完整链**读数（35/35 步全部跑到）

这一份是 `tools/run_tests.ps1` 在知识索引换代（`rebind/v1 → rebind/v2`，
登记 `docs/knowledge/REGEN_LOG_20261007_rotation.md` §7）之后的一次**完整**运行。
链上没有中途停（上一轮因为 pytest 里那条"长剧本触顶"的红在 step 2 就停了）。

## 链上读数

| 项 | 值 |
|---|---|
| 链规模 | **35/35**（探针 31 支 ＋ spec/golden 漂移、pytest、契约冒烟、headless 四步） |
| Blender 探针 | 31 支全 `OK` |
| `python -m pytest` | **2808 passed / 1 skipped / 0 failed**（那 1 条 skip 是 `tests/test_build_ledger.py:68` 的条件守卫，**不是被绕过的判据**） |
| 门①–⑩ | `holdout_gates.json`：**`overall: pass`**（`generation: gen2`） |
| Q1 | **0.9975**（线 0.70）；`not passing: E1`、`not measured: E2` |
| attestation（诊断） | **0.8682** 的可检槽位能在这条边自己的来源卡正文里找到取值；**451/638** 条边完全被佐证（换代前 0.2078 / 151 条） |
| Q6b 注入上限 | plan 1799/2000、shot 795/800（读真实 prompt） |
| 红线 | **唯一红 = `RK-13`**（E1 ≥ 0.70）——`rks.json` 的 `failed_checks` 就是 `["RK-13"]`，与换代前同一条已结案红线 |

## 这一份**不能**证明的事

* **不能证明 E1 达标**：它照样是红（0.18 量级），这里只证明"链跑完了、判据没动"。
* **不能当 oracle 换代的证据**：夹具（held-out / 第三方层）这一轮**一个字节都没动**
  （`config.fingerprint.json` 与换代前同代）。
