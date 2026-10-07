# C1 第二半：90 槽位三分类——**已完成**（2026-10-07 03:4x 未完成 → 15:xx 用新通道跑完）

> ## ✅ **结论（先说结论）**
>
> **12 批全部完成（90/90 条），单一判官 `qwen3.8-max-0902`（思考拉满）。**
> `三分类汇总.json` 判：**后两类 = 67/90 = 0.7444** → 分支 **`corrupt-dominated`**
> ⇒ 按裁定口径（"**≥33% 且模式一致** ⇒ 暂缓重抽被证伪、应启动换代"）
> **「暂缓重抽」被证伪**。
>
> **四个分层一致**（不是某一层拉高平均）：`closed_loop_kind` 24/30=0.80、
> `PERFORMANCE_PACK` 13/20=0.65、`SHOT_PATTERN` 14/20=0.70、`STAGING_PACK` 16/20=0.80。
>
> **分 kind**：`headroom_policy` 13/13=1.00、`shot_size` 16/17=0.94、`camera_angle` 20/23=0.87、
> `emotion` 6/10=0.60、`action` 4/7=0.57、`composition_rule` 5/11=0.45、`movement` 3/9=0.33。
>
> **判官替换与"思考拉满"的实测**见同目录 [judge_switch.md](judge_switch.md)
> （用户指令："接入这个 qwen3.8max0902，代替 glm"＋"新模型思考强度拉到最大"）。
> 汇总产物：`docs/evidence/20261007-grounding-sample90/三分类汇总.json`（12 批逐份 sha256 取证）。
>
> **本结论对 ⚖️ 项的意义**：它把 `P5-T2`（要不要换代）与 `C2`（9 条边的换卡/删边）
> 从"要不要动"推进到"**语料侧确实需要重抽/重挂**"——但**换代仍须用户点头**（R-8）。

**run-id**：_v15_stage8/c1_recap
**卡**：`执行文档v1.5/TECH_SOLUTIONS.md` §三 **C1**（收口动作第 2 步："等 12 批三分类作业跑完后汇总"）
**状态**：**已完成**（下面是当时"缺凭据"的现场记录，保留存档）。

---

## 1. 实测：12 批作业只完成 2 批

```
docs/evidence/20261007-grounding-sample90/questions/   -> 12 个问题文件（batch1…batch12）
docs/evidence/20261007-grounding-sample90/batch*/三分类.json -> 只有 batch1、batch12
```

| 批 | 状态 |
|---|---|
| `batch1` | ✅ 有判词（8 条；`--plain` 修复后跑出的那一版） |
| `batch12` | ✅ 有判词（2 条） |
| `batch2` | 只有 `bundle.manifest.json` / `bundle.md`（问题已装包，**无判词**） |
| `batch3…batch11` | 只有问题文件，**未装包未判** |

**已判总量：10 / 90 条槽位（11.1%）**。

## 2. 已判部分的读数（**只作参考，不是结论**）

```
python -c "...汇总 batch*/三分类.json..."
batch1  n=8  {wrong_card:7, hidden:1}
batch12 n=2  {hidden:1, wrong_card:1}
TOTAL   n=10 {wrong_card:8, hidden:2, wrong_value:0}
```

按 C1 的分水岭口径（"**后两类**"= `wrong_card` + `wrong_value`，两类都腐蚀下游）：
已判的 10 条里后两类 = **8/10 = 0.80**。

> ⚠️ **这不能拿来下结论**：C1 的规则是拿**全部 90 条**的分母判"≥33% ⇒ 暂缓重抽被证伪 / ≤10% ⇒ 修数据被证伪"。
> 现在 8/9 的样本还没判，且已判的 10 条**集中在前两批**（不是随机子集），
> 拿它算比例等于**用 11% 的样本替 100% 发声** —— 这正是本仓反复记为事故的形态。**不预判**。

## 3. 为什么没跑完（具名根因，不是"懒"）

1. **通道缺失**：这些批次走 GLM 通道（`tools/knowledge/grounding_classify.py` + `tools/glm_consult.py --plain`），
   而本机环境里 **`GLM_API_KEY` 未设置**（实测 `python -c "import os; print(bool(os.environ.get('GLM_API_KEY')))" -> False`）。
   按仓库纪律"GLM 类调用串行、不可用即跳过并记录"，**不许**用别的通道冒充 GLM 判词。
2. **提交口径仍待用户确认**：C1 第 1 步（把在跑改动入库）在 `TECH_SOLUTIONS` 里写明"**先经用户确认提交信息口径**"
   —— 这一条同时是 F5，属 `P7-T2` 的用户裁决项。

### 3.1 **验证性阻塞**（不是猜，是跑出来的）

```powershell
$env:PYTHONIOENCODING="utf-8"; python work/_run_grounding_batches.py
[batch 1] 已有产物，跳过
[batch 2] start 08:49:43
[batch 2] FAILED(code='缺少 GLM_API_KEY（只从环境变量读，绝不入库）'): 缺少 GLM_API_KEY（只从环境变量读，绝不入库）
[batch 2] rc=3 用时 0s
…（batch 3…12 同形）
```

⇒ **驱动本身是好的**：它逐批找到了 `work/_q_grounding_batch<n>.md`、跳过已有的 batch1、
对缺产物的批次逐批调用——**唯一缺的是环境变量**。所以这条阻塞的准确表述是
**"一到凭据就能跑"**，而不是"实现没做完"。

> **没有**用 `--dry-run`（那是占位形状，会把假判词灌进分母）、**没有**换 DeepSeek 冒充 GLM
> （那会让前 2 批与后 10 批**混判**，破坏这份测量的口径）。

## 4. 一旦拿到 GLM key，怎么跑完（可执行步骤，已核实脚本都在）

```powershell
# 逐批（串行；每题实测 30–170 s，12 批约 20–60 min）
python tools/knowledge/grounding_classify.py --batch <n> `
    --questions docs/evidence/20261007-grounding-sample90/questions/batch<n>.md `
    --out docs/evidence/20261007-grounding-sample90/batch<n>/
```

跑完后再按 C1 的分水岭汇总（分母＝90），并把结论与前两类占比一起落证。

## 5. 证据指针

- `docs/evidence/20261007-grounding-sample90/`（12 个问题文件、batch1/batch12 判词、`_superseded/` 的失败重跑）
- `tools/knowledge/grounding_classify.py`、`docs/evidence/20261007-grounding-sample90/make_grounding_batches.py`
- `执行文档v1.5/TECH_SOLUTIONS.md` §三 C1（分水岭口径与收口动作）
