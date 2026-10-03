# `20261003-motion-layer-state` — 构图分低下去的真因：角色被瞬移到世界原点

这一份是 `20261003_chunked_long4/long5` 那份"跑完 ≠ 拍对"账目的**定向探针**，
回答 README 里悬着的那一问："是评分模型的口径问题，还是求解器摆位的问题？"
答案是**都不是**——是一处**动作层状态**的缺陷。

## 探针（命令原样可跑）

```
blender --background --factory-startup --python work/_composition_probe.py -- \
    --project docs/evidence/20261003_chunked_long5/project --limit 0 \
    --out work/_composition_probe.json

blender --background --factory-startup --python work/_blocker_probe.py -- \
    --project docs/evidence/20261003_chunked_long5/project \
    --out work/_blocker_probe.json
```

两份探针都把结果**自己写进文件**（`--out`）：PowerShell 的 `2>&1 | Out-File`
会按 cp936 解码 Blender 的 UTF-8 输出，中文经它一转就成乱码（这是现场踩到的）。

## 归因链（每一步都是量出来的）

1. **构图分低不是"评分模型刻薄"**：`composition_before.json` 里六项均值
   一眼可见 `occlusion` 只有 **0.423**（权重 0.25，最大的一项）。
2. **遮挡不是道具/墙/群众**：`blockers_before.json` 把 85 条主体-机位视线全做了
   `scene.ray_cast`，35 条被挡，**挡的全部是另一个角色**——
   `BD_Char_伊恩_Body` 18 次、`BD_Char_米迦尔_Body` 17 次。
3. **两个角色都在世界原点**：同一份探针打印角色根节点，两个 root 都是
   `[0.0, 0.0, 0.0]`（而 `SceneSpec.cast` 的 `initial_location` 是 ∓0.9）。
4. **根因在纯计算层**：`block_director/motion/model.py::compose` 的
   `layer_state[layer] = composed` 是**整份替换**本帧算出的通道集合。
   `turn_body` 只写 `root.rotation_z` ⇒ base 层的 `root.location` 从层状态里消失；
   此后 `sit`/`stand`/`walk_to` 冻结接管时 `frozen_base` 抓到的基线里没有摆位，
   `baseline = base.get(channel, _zero_like(value))` 取到 **0** ⇒ 角色瞬移到原点。
   最小复现（纯 Python，不用 Blender）：

   ```python
   base = {'root.location': (0.75, 0.0, 0.0), 'root.rotation_z': 0.0}
   compose([ActionRequest('turn_body', 1, 10, {'angle_deg': 90}, 'c', 'a1'),
            ActionRequest('sit', 20, 30, {'drop': 0.2}, 'c', 'a2')],
           base_pose=base)[20]['root.location']     # 旧代码：(0.0, 0.0, 0.0)
   ```

   修法：`layer_state[layer] = {**current, **composed}`——**未被本帧任何动作写入
   的通道原样带过**。落地见 `3ea5230`（P14-53）。

## 效果（同一份 `long5` 工程，重建后逐镜复评）

| 指标 | 修前 | 修后 |
|---|---|---|
| 构图分中位 | **51.4** | **68.0** |
| 构图门通过（≥70） | 9 / 64 | **26 / 64** |
| `occlusion` 均值 | **0.423** | **0.984** |
| 遮挡失败的镜数 | **42 / 64** | **1 / 64** |

逐项均值（`amount` 只列有变动的）：

| 分项 | 权重 | 修前 | 修后 |
|---|---|---|---|
| occlusion | 0.25 | 0.423 | **0.984** |
| balance | 0.15 | 0.642 | 0.733 |
| framing | 0.10 | 0.600 | 0.649 |
| headroom | 0.15 | 0.638 | 0.632 |
| lead_room | 0.20 | 0.627 | **0.532** |
| rule_of_thirds | 0.15 | 0.222 | **0.195** |

**如实记两条**：

* `lead_room` 与 `rule_of_thirds` **没有回升、反而略降**。把它们当成"修坏了"
  是错的：修前角色在原点，"恰好"落在某些镜头的构图友好区；修后角色回到
  真实的 ∓0.9 摆位，求解器**按真实摆位摆的机位**才第一次被量到。
* 于是 `rule_of_thirds`（均值 0.195，权重 0.15）与 `lead_room`（0.532，权重 0.20）
  就是**剩下那 51.4→68.0 之后的主要缺口**，也就是上一份 README 说的
  "求解器与构图模型是否对得上"——**这一条仍然悬着**，且它不是契约缺陷，
  是设计决策（谁改：让求解器遵守三分线，还是让评分模型接受居中主体）。

## 场景层的守门用例（这一份的另一半交付物）

`tools/blender_tests/test_layer2_project.py::t_a_base_action_keeps_the_placement`
新增一条**场景层不变量**："一个只写单通道的同层动作，不得把角色的摆位抹掉"。

**为什么非加不可**：长跑链上的重建检查只对拍**镜数 / 帧数 / 相机名 / 焦距**
（`t_save_load_rebuild_keeps_the_timeline`），而这处缺陷前后两边**完全一致**
（同一个确定性 bug，建两次都是原点），**对拍永远绿**。新判据换了个不变量：
角色坐下的位置必须**等于他被摆下的位置**（`SceneSpec.cast[].initial_location`）。

成对复验（`git worktree add work/verify_prefix e7182da`，把新用例拷进旧代码）：

```
旧代码：failed ['a_base_action_keeps_the_placement']
        placed  {"char_002": [0.0, 0.0]}   期望 [0.9, 0.0]
新代码：5/5 passed，placed {"char_002": [0.9, 0.0]}
```

纯层的两条用例在 `tests/test_motion_model.py`
（`test_a_base_action_does_not_erase_the_placement_for_a_later_one`、
`test_a_later_walk_keeps_the_placement_after_an_earlier_turn`）。

## 未验证 / 仍悬着的

* 这一跑是**从 `long5` 的 `project.bdproj` 重建**后复评的（不花 LLM 调用、
  可复算）。**真实模型重跑**（sidecar）没做——修复只动纯计算层，重建与真跑
  共用 `build_scene`，但"真跑一次构图门通过率"仍应以接下来的真跑为准。
* `rule_of_thirds` / `lead_room` 的对齐属**设计决策**，本份不改权重、不改阈值
  （那会是把指标做绿，不是把镜头拍对）。
