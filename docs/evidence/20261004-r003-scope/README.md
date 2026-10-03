# P14-67：R003 必须**按镜收口**——一处重叠不许污染 64 张审计

**结论**：`long12` 的真跑记录是 **0/64 逐镜通过、1003 条 R003**（终审 312 条、
64/64 镜红）。把**同一份** `long12/project` 用收口后的规则重建复评：

```
shots 64 → passed 15 → 规则直方图 {"COMPOSITION": 39, "R001": 27, "R003": 7}
```

也就是说：全片**真正的同角色动作重叠只有 7 处**（`shot_035/038/044/047/054/055/056`），
而当时每一条都被**广播**到 40–48 张镜头审计里。

## 根因（`rule_checker.check_shot` 的 R003 分支）

`_action_ranges(context)` 读的是**整份计划**的动作表，而审计只按**角色**过滤
（`character_id not in shot.characters`）——没有按**镜头**过滤。于是"米迦尔在
shot_044 的两段动作重叠"这条，会出现在**每一张有米迦尔的镜头**（48 张）的审计里。
后果有三层：

1. **逐镜通过率失去意义**：任何一处重叠让全片 64 镜变红（`long12` 0/64）；
2. **修复回路被同一句话灌满**：128 次修复调用里 39 次 `emit_shot_draft`，
   而模型看不到"这一镜到底哪两段重叠"；
3. **历史数字被污染**：`long8` 的 487 条、`long12` 的 1003 条里绝大部分是广播副本。

## 改法

重叠的**两个动作必然在同一镜里**（窗口已被 `cinema/schedule.action_frame_window`
夹进各自那一镜，跨镜重叠在构造上不可能），所以只保留"两端都属于当前镜"的配对：

```python
if shot_id and not any(label.startswith(f"{shot_id}#")
                       for label in (label_a, label_b)):
    continue
```

**判据一个字没动**：重叠仍然是 error、仍然用 `action_frame_window` 折算。

## 守门用例

`tools/blender_tests/test_phase3_audit.py::r003_is_scoped_to_the_shot_being_audited`
——`shot_001` 故意重叠、`shot_002` 干净；断言 `shot_001` 有 R003、`shot_002`
**没有** R003 且 `passed=True`。
成对复验：`git worktree add work/verify_scope 3c3e716` ＋ 新用例 → **fail**；
新代码 → 9/9 pass。

## 复算

```
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261004_chunked_long12/project \
    --out docs/evidence/20261004-r003-scope/reaudit_long12.json
```

`reaudit_long12.json` 是逐镜原始产物（`passed` / `score` / `errors`）。
