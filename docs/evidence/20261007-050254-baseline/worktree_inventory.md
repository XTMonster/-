# 在跑工作树清点（执行文档 v1.5 / P0-T2，不提交）

**run-id**：20261007-050254-baseline
**HEAD**：f6530c6（docs(P14-319)）
**对应**：OPEN_ITEMS §五 F5（工作树未提交）+ TECH_SOLUTIONS C1 收口第 1 步。
**纪律**：只清点、**不做任何 git commit**（提交口径须用户确认）。

---

## 逐文件归属与建议提交分组

| 文件 | 状态 | 改动摘要 | 归属 | 建议分组 |
|---|---|---|---|---|
| `tools/glm_consult.py` | M | `--plain` 机械标注包（+`plain_messages`/`bundle_manifest(mode=)`/指纹与渲染适配）；修 `bundle_manifest` 位置参数顺序（`repo` 必须在 `mode` 前） | C1：`glm_consult` 输出契约互斥修复 | 组① 工具修复 |
| `tests/test_glm_consult.py` | M | +80 行：`--plain` 与 manifest 取证测试 | 同上 | 组① 工具修复 |
| `tools/knowledge/grounding_classify.py` | ?? | 90 槽位三分类驱动（新增） | C1：出处三分类 | 组② 出处三分类 |
| `docs/evidence/20261007-grounding-probe/` | ?? | `--plain` 对照实测（带角色 vs 无 system） | 同上 | 组② 出处三分类 |
| `docs/evidence/20261007-grounding-sample90/`（含 `README.md`/`batch1/*`/`sample90.json`/`sample_grounding90.py` 的 M，及 `_superseded/`/`batch12/`/`questions/`/`make_grounding_batches.py` 的 ??） | M+?? | 90 槽位分层抽检产物；失败重跑进 `_superseded/`；12 批作业已起 | C1 | 组② 出处三分类 |
| `docs/evidence/20261007-wrong-card-correction/` | ?? | 错卡纠正在跑证据 | C2 前置 | 组② / 待定 |
| `docs/knowledge/OPEN_ITEMS_20261007.md` | ?? | 未完成项总表（本版输入材料） | 本版输入 | 组③ 本版文档 |
| `docs/research_src/` | ?? | 两份调研报告 PDF（输入材料） | 本版输入 | 组③ 本版文档 |
| `执行文档v1.5/` | ?? | 本执行包（PRD/TDD/TECH_SOLUTIONS/EXECUTION_PLAN/README） | 本版输入 | 组③ 本版文档 |
| `docs/evidence/20261007-050254-baseline/` | ?? | 本次 P0 基线产物 | 本版执行 | 组③ 本版文档 |

## 归属判断依据（命令与输出）

```
git diff --stat
 .../evidence/20261007-grounding-sample90/README.md          |   16 +-
 .../batch1/bundle.manifest.json                              |   38 +-
 .../20261007-grounding-sample90/batch1/bundle.md           |  151 +-
 .../20261007-grounding-sample90/sample90.json               | 1836 ++++++-
 .../20261007-grounding-sample90/sample_grounding90.py        |   30 +-
 tests/test_glm_consult.py                                    |   80 +
 tools/glm_consult.py                                         |   85 +-
```

`tools/glm_consult.py` diff 顶部注释自陈：`--plain` 是"标注类任务"专用，
因为 `SYSTEM_TEMPLATE` 的 JSON 对象契约与三分类问题的 JSON 数组契约**互斥**，
实测同一份 2 条问题：带角色 **170.4 s 回错形状**、去掉 system **32.9 s 回正确数组**。
`bundle_manifest` 的 `repo` 位置参数修复对应
`tests/test_glm_consult.py::test_manifest_is_written_before_any_call_and_outlives_a_failure`。

## 建议提交信息草稿（**须用户确认后**才执行）

- 组①：`fix(tools): glm_consult 增 --plain 机械标注包（输出契约互斥）＋ bundle_manifest 位置参数修复`
- 组②：`docs(P14-32x): 出处缺口 90 槽位三分类在跑产物与驱动脚本入库`
- 组③：`docs(v1.5): 执行文档 v1.5 执行包与输入材料（PRD/TDD/TECH_SOLUTIONS/EXECUTION_PLAN）＋ P0 基线`

## 结论

- 清单覆盖 `git status --porcelain` 全部条目（含本轮新增的
  `20261007-050254-baseline/`）。
- **未做任何提交**；分组口径待用户确认（P7-T2 会再走一次）。
- 注意：`执行文档v1.5/` 也在 `?? 执行文档v1.5/` 中（用户放置的输入包），
  **不属本轮执行产物**，只作输入。
