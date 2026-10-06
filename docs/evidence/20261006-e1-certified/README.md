# E1 此前是"**量不到**"，不是"量到了、很低"——把链喂的**同一次测量**换成可认证版

日期 2026-10-06 19:3x。这是**同一类洞的第三个实例**：链喂给指标的输入，指标**没法认证**。
前两个是 `20261002_real` 的 E1 与 SS84 的 Q5；本目录收口的是 **E1 自己那一份**。

## 一、事实：那份打分文件"什么都对，只差一个字段"

链上一直喂 `docs/evidence/20261006-e1-craft/reviews.jsonl`。逐条核过：

| 检查 | 结果 |
|---|---|
| `cases_digest` 与**当前**索引是否一致 | ✅ 逐字相同（`937a04e052e67548…`）——**不是**过期语料 |
| `cases_fingerprint` / `panel` / `prompt_sha256` / `reviewed_by` | ✅ 齐（`deepseek-chat` ＋ `glm-5.3`） |
| **每一行的 `judge_batch`** | ❌ **全为 0（缺失）** |

原因很清楚：那份文件产出于 `--judge-batch`（P14-205）**存在之前**，那时的面板不写这枚自述字段。
而 `quality.e1_relevance` 的规矩是"**没有判分语境就不能认证**"⇒ 它记
`not_measured` ＋ `stale_evidence: true`，把当时的分数 0.1354 一并报出来（**不判过**）。

**后果**：RK-13 那条红线的措辞是"**我们量不到**"，而不是"**量到了、远低于 0.70**"。
对一条要"能可信地判成败"的红线（用户 2026-10-06 的原话），这两句话不是一回事。

## 二、修法：**同一次测量**的认证版（不是换尺子）

先验证"同一次"：那份文件的 64 条查询与 **long21 project 的 64 条查询逐字相同（连顺序都同）**，
所以可以在**同一份索引、同一批查询、同两位评委、同一个 C=3 产品口径**下重跑一遍，
把语境标记写出来：

```powershell
python tools/knowledge/e1_panel.py `
  --project docs/evidence/20261006-long21/project/project.bdproj `
  --cases-dir knowledge --top-k 3 --judge-batch 3 --workers 6 `
  --out docs/evidence/20261006-e1-certified/reviews.jsonl
```

读数（`reviews.jsonl`，sha256 前 12 `663e1aeaaf39`、192 行 / 64 查询）：

| | 链之前喂的那份（craft） | 本目录（认证版） |
|---|---|---|
| `judge_batch` | **0（缺失）** | **3**（产品口径） |
| `e1_relevance` 的 `status` | **`not_measured`** | **`fail`** |
| `stale_evidence` | **true** | 无 |
| 值 | 0.1354（按两位评委口径重算） | **0.1771（34/192）** |

⇒ **红线仍然是红的**（0.1771 ≪ 0.70），但现在是**量到的红**。

**判据一个字没动**：相关阈值 **4.0**、分母＝**面板行数**、线 **0.70**、C＝**3** 全部原样；
改的只是"喂进去的那份**能不能被认证**"。

## 三、守门（含反例）

`tests/test_chain_evidence_is_measured.py::test_the_chain_feeds_e1_a_review_file_the_metric_can_certify`
——链上只允许一处 `--e1-reviews`，且**它的每一行都必须带产品口径的 `judge_batch`**。

**反例**（`negcontrol_e1_certify.py` 拿改前的文件跑同一套判据，逐字输出见 `negcontrol.out.txt`）：

```
OLD: {'file': 'docs/evidence/20261006-e1-craft/reviews.jsonl',   'rows': 192, 'contexts': [0], 'guard_fails': True}
NEW: {'file': 'docs/evidence/20261006-e1-certified/reviews.jsonl','rows': 192, 'contexts': [3], 'guard_fails': False}
```

⇒ 这条守门**本来就会红在旧文件上**。

## 四、未验证 / 边界（如实挂）

* **标签是新的**（重跑了两位评委），所以 0.1771 与旧那份的 0.1823／0.1354 **不是同一次判分**，
  不能相减当"变化"。**只有一次**这一版（没有重复跑、没有置信区间）。
* **样本量仍远低于下界**：192 < §4.1b 的 E1 下界 **1200**（`sample_shortfall: 1008`），
  这个缺口由 `quality.py` 原样报出来，**判据与状态未因此改变**。
* **192 行里有 9 行只有一位评委**（`judge_incomplete_rows: 9`，按 P14-249 口径**不算相关**、
  但**留在分母**）。这也是这版读数比旧版"宽松口径"低的原因之一。
* 这份证书**不能**把红线翻绿，也**不能**替代用户对 A／C 的裁决（GPT-6A 的 `a_metric` 第 2 条
  说得很清楚：结算方式的改动要验收方显式批准）。它只做一件事：**让"量到了没有"这一步不再含糊**。
