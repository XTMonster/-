# 证据 · P6-T2 多样性度量（三份冻结工程）

**run-id**：`20261007-p6t2-diversity`
**卡**：`执行文档v1.5/EXECUTION_PLAN.md` → P6-T2（多样性度量与 Best-of-N 骨架）
**HEAD**：`f6530c6` ＋ 本版未提交改动
**执行者**：主线（DeepSeek）
**纪律**：红 R-5（判据一个字没动）、R-9（读数落盘，实测/未验证分开写）。

---

## 1. 卡里那条验收命令的实测读数

```
python tools/diversity_score.py \
  docs/evidence/20261003_chunked_long9/export/shots.json \
  docs/evidence/20261004_chunked_long11/export/shots.json \
  docs/evidence/20261004_chunked_long12/export/shots.json
```

产物：本目录 `diversity_three_runs.json`（机器可读）与 `diversity_three_runs.txt`
（逐字节相同）。**实测**读数：

| 维度 | 读数 | 可测？ |
|---|---|---|
| 景别序列编辑距离 | `sum 2` ／ 3 对 ／ 归一化 **0.0104** | ✅ |
| 运镜分布卡方 | `statistic 6.6628`，`dof 14`，**8 种运镜** | ✅ |
| 机位侧向符号翻转率 | `flipped 0 / 64`，`rate 0.0` | ❌ **结构上量不出来** |

`measurable` 一栏（本次新增）：`{"shot_type": true, "movement": true,
"axis": false}` —— 第三栏的 0 **不是**"机位永远待在同一侧"的证据：这三份
成片（2026-10-03／10-04）早于 `shots[].axis{side_sign}` 字段落盘（P14-313），
64 镜里一个符号都没有。读账必须区分"量了，是 0"与"根本没得量"。

## 2. 这一轮查出并修掉的**真缺陷**（P6-T2 自带的脚本）

`tools/diversity_score.py::movement_histogram` 原来只认**计划**的形状
（`shot.camera.movements[].type`），而 `shots.json`（`delivery/manifest.py`）
把运镜放在**镜头级**、键是 `kind`。于是拿卡里指定的三份 `shots.json` 跑，
运镜那一栏恒为 `kinds = 0` —— **结构性量不出来，却和"三次生成运镜完全一样"
读起来一模一样**。

修法：两种形状都读（`shot.movements[].kind` ‖ `shot.camera.movements[].type`），
并给报告加 `measurable{}` 一栏把"没得量"显式标出来。修前／修后的同一命令
对照（同一批输入、同一天）：

| | 修前 | 修后 |
|---|---|---|
| `movement_chi_square` | `statistic 0.0`，`kinds 0` | `statistic 6.6628`，`kinds 8` |

回归用例：`tests/test_best_of_n.py::test_movement_histogram_also_reads_the_shots_json_shape`
与 `::test_report_flags_dimensions_it_structurally_cannot_measure`。

## 3. **未验证**的部分（不许拿上面的读数顶）

PRD §6 的那条验收指标是"**同一剧本 3 次生成**的分镜差异度可测量且 >0"。
本次的读数用的是**三份不同剧本的冻结成片**（卡 P6-T2 自己指定的输入），
因此：

* 0.0104 的归一化编辑距离说的是"这三部片子的景别结构几乎同构"——
  对"规则把 AI 逼成查表"是个**值得盯的信号**，但**不是** PRD 那条指标的读数；
* 真正的"同剧本 3 次生成"需要 **3 次真实模型运行**（离线替身是确定性的，
  三次必然逐字节相同 ⇒ 该口径下恒为 0，量了也没意义）。截至本目录写入时
  未跑，**标未验证**。可复核的命令（跑完把三份 `shots.json` 喂给同一脚本）：

```
# 同一剧本跑三次（真实模型），各产出一份 export/shots.json
python tools/run_export.py --script <同一剧本> --out <runA>
python tools/run_export.py --script <同一剧本> --out <runB>
python tools/run_export.py --script <同一剧本> --out <runC>
python tools/diversity_score.py <runA>/export/shots.json \
    <runB>/export/shots.json <runC>/export/shots.json
```

## 4. 另外两项验收（都不是靠上面的命令顶的）

* **`gen_specs` 幂等无 diff**：`python tools/gen_specs.py --check` → 绿
  （`tests/test_best_of_n.py::test_gen_specs_is_in_sync_and_idempotent` 钉住）。
* **默认 1 时零行为差**：`orchestration.draft_candidates` 缺省 1，
  `driver._draft_candidates` 只收 1 个候选 ⇒ `rank_drafts` 的 `alternates`
  为空 ⇒ `shots.json` 里 `alternates` 是空表（键在，值空——P15 §3.3 的固定列），
  且 `draft_received` 事件**一个字节都不多**（`candidates` 只在 `wanted > 1`
  时才写，见 `driver.py:1240-1246`）。用例：
  `tests/test_best_of_n.py::test_draft_candidates_defaults_to_one`、
  `::test_rank_keeps_every_candidate_and_is_stable`、
  `::test_manifest_alternates_defaults_to_empty`。
