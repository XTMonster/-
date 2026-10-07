# 基线读数（执行文档 v1.5 / P0-T1）

**run-id**：20261007-050254-baseline
**采集时刻**：2026-10-07 05:02（Asia/Shanghai）
**目的**：建立本版开始前的事实基线；后续所有"不回退"对照都以它为准。

---

## 1. C 盘余量（清单 F1）

```
Get-PSDrive C -> Used 508976222208 / Free 26850304000  (≈ 26.8 GB 可用)
```

**与文档出入**：`执行文档v1.5/README.md` 的"环境约束（2026-10-07 实测）"写
"C 盘仅剩约 2.7 GB"，本次实测为 **≈26.8 GB 可用**（高于 2 GB 停手线）。
结论：**不触发"低于 2 GB 停手"**；但仍遵守"不装新包、并发 pytest ≤ 2"。

## 2. 全量 pytest

命令：`python -m pytest`（pyproject `addopts = "-q"`；pytest 9.1.1 在 `-q` 下
不打印汇总行，故以默认 verbosity 重跑取汇总）

```
2492 passed, 1 skipped in 175.56s (0:02:55)
```

（`-q` 与默认 verbosity 两次运行均 **exit 0**，无 failed / error。）
1 skipped 为条件守卫（非被绕过判据）——见状态块既有说明。

**基线即红项**：无（0 failed / 0 error）。

## 3. tools/run_tests.ps1

命令：`powershell -ExecutionPolicy Bypass -File tools/run_tests.ps1`
（完整链路：spec/golden --check → pytest → Blender 契约冒烟 → headless
`--offline --build --preset fhd16x9 --export` 长剧本 61 镜 → rebuild →
28 支 Blender 探针 → RK 证据钩子）

读数与结论：见本目录 `run_tests.md`（链路较慢，另行落盘）。

**已知设计性红**：链路末段 `RK-13`（= E1 ≥ 0.70，A1 已结案）**按设计报红并
`exit 1`**；这不是本版引入，也不允许调判据转绿（R-5 / A1）。

## 4. golden 链路

```
python tools/gen_golden.py --check  -> [OK] Golden 夹具与 fixtures/mock_llm_responses/plan_simple.json 一致
python tools/gen_specs.py   --check  -> [OK] specs/config.default.yaml 与代码一致
```

**此刻为绿**。

## 5. HEAD 与工作树

```
git log --oneline -1 -> f6530c6 docs(P14-319): 出处缺口的 90 槽位分层抽检…
```

工作树未提交改动（P0-T2 逐条归属见 `worktree_inventory.md`）：

```
 M docs/evidence/20261007-grounding-sample90/README.md
 M docs/evidence/20261007-grounding-sample90/batch1/bundle.manifest.json
 M docs/evidence/20261007-grounding-sample90/batch1/bundle.md
 M docs/evidence/20261007-grounding-sample90/sample90.json
 M docs/evidence/20261007-grounding-sample90/sample_grounding90.py
 M tests/test_glm_consult.py
 M tools/glm_consult.py
?? docs/evidence/20261007-grounding-probe/
?? docs/evidence/20261007-grounding-sample90/_superseded/
?? docs/evidence/20261007-grounding-sample90/batch12/
?? docs/evidence/20261007-grounding-sample90/make_grounding_batches.py
?? docs/evidence/20261007-grounding-sample90/questions/
?? docs/evidence/20261007-wrong-card-correction/
?? docs/knowledge/OPEN_ITEMS_20261007.md
?? docs/research_src/
?? tools/knowledge/grounding_classify.py
?? 执行文档v1.5/
```

---

## 异常项

- 无"基线即红"的 pytest 失败项。
- `20261007-045808-baseline/` 是**另一条已中断的并行车道**留下的半成品
  （`run_tests.txt` 停在 `[2/32] ... 66%`），**不作为本版基线**；本基线以
  本目录为准。
