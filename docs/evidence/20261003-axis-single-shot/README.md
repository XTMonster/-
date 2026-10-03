# P14-58：单人镜头也待在已确立的轴侧（R001 20/64 → 0/64）

**结论**：`docs/evidence/20261003_chunked_long9/` 那份真跑审计里的 **61 条 R001
（180° 轴线）错误、命中 21/64 镜，全部是单人镜头**——同一跑里两人镜头一条都没有。
根因不是"模型乱摆"，而是**契约错配**：`camera.side` 相对**被摄主体朝向**解析，
两人相对而立时两个角色朝向相反，于是同一个 `front_right` 落在**世界轴线的两侧**；
R001 的判据却是世界轴侧。修法（`43892a3`）把单人镜头也纳入"已确立轴侧"的约束，
用**关于轴线镜像**保住模型要的偏角。同一份工程重建复评：

| 指标 | 改前（`925ef79`） | 改后（`43892a3`） |
|---|---|---|
| R001 越轴镜数 | **20 / 64** | **0 / 64** |
| 构图分中位 | 57.8 | 64.7 |
| 构图门（≥70） | 17 / 64 | 19 / 64 |

（真跑审计里的 61 条含**重审轮次**，与"同一份工程重建一次"的 20 不是同一个量；
两个数都记，不互相冒充。）

## 怎么来的（全部可复算，零 LLM）

1. **取证**：`python work/_axis_audit.py docs/evidence/20261003_chunked_long9/audit_log.jsonl`
   —— 逐镜打印 `camera.side` 与 R001 文案；所有 R001 命中的镜头 `characters` 都是
   单人（21 镜）。
2. **成对重建**：

   ```
   # 旧代码（改动前的冻结提交）
   git worktree add work/verify_axis 925ef79
   Copy-Item work/_axis_rebuild_probe.py work/verify_axis/work/
   cd work/verify_axis
   blender --background --factory-startup --python work/_axis_rebuild_probe.py -- `
       --project <repo>/docs/evidence/20261003_chunked_long9/project --out <repo>/work/_axis_before.json
   # 新代码
   blender --background --factory-startup --python work/_axis_rebuild_probe.py -- `
       --project docs/evidence/20261003_chunked_long9/project --out work/_axis_after.json
   ```

   两次都读**同一份** `long9/project`（`project.bdproj`），只换代码：
   `axis_before.json` / `axis_after.json` 是原始产物（含逐镜 `r001`、`composition`、
   机位坐标）。`established_side` 两次都是 −1，可比。
3. **守门用例**（换的不变量，不是"某个数等于某个数"）：

   ```
   blender --background --factory-startup --python tools/blender_tests/test_phase3_audit.py
     旧代码：failed ["a_dialogue_line_survives_reverse_singles"]
     新代码：6/6 passed（established_side=-1；五镜 sides 全为 -1；3 条镜像说明）
   python -m pytest tests/test_axis_side_single_shot.py -q
     旧代码：6 failed（含 18 个参数化用例），新代码：全过
   ```

## 修的是什么（一句话）

`cinema/station._honour_the_established_side` —— 单人镜头的机位方向落在已确立轴线的
**另一侧**时，把它**关于轴线镜像**一次（保持与轴线的夹角，只翻侧别）。两个边界都钉住：

* **只在不改变前/后关系时**才镜像 —— 否则"正面机位"会被悄悄换成背拍（那是换了一镜，
  不是修轴侧）；
* 真的无法同时满足的请求**原样返回**并留一条说明，交给 R001 如实报错，
  **不在解算器里把冲突吞掉**；
* 每次镜像都进这一镜的取景警告（`solution.warnings`），审计日志里看得到。

## 未验证 / 边界

1. **还没跑真模型（LLM）**：这里的"改前/改后"全部是**同一份工程重建**（零 LLM），
   量的是引擎摆位；"真跑的逐镜通过率"要下一次 64 镜真跑才有数。
2. **端到端指标单跑波动大**（§五十七 记过：19/64、0/64、5/64），所以本文件不拿
   真跑通过率当证据，只拿"同一份工程前后对拍"。
3. r001 的**构图连带效应**已经量到（中位 +6.9、门 +2 镜），但它是摆位改变的自然
   结果，不是单独优化过的目标。
