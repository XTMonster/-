# P14-64：机位瞄的是"这一镜人在哪"——构图门 20 → 32（同一份 `long9` 工程重建）

**结论**：`place_shot_camera` 一直用 `CastMember.initial_location`（剧本开始时的
站位）摆机位，而角色在**前面的镜头里已经走动过**。`work/_anchor_probe.py` 在同一份
`long9` 工程上量到 **52 镜**的机位与"该镜首帧的实际位置"差 > 1 m，最远 **7.7 m**。
改成"先烘焙动作、再按该镜首帧角色的实际位置与朝向摆机位"之后：

| 指标（同一份 `docs/evidence/20261003_chunked_long9/project` 重建，零 LLM） | 改前 `a938482` | 改后 |
|---|---|---|
| 构图分中位 | 63.8 | **70.0** |
| 构图门（≥70） | 20 / 64 | **32 / 64** |
| 逐镜构图变化 | — | **29 镜升 / 12 镜降** |
| 机位移动 > 1 m 的镜头 | — | **52 / 64**（这是修复本身） |
| R001 越轴 | 0 | 2（角色真的走动了，轴侧判据随之变化；已记） |

最极端的两条：`shot_059` 机位 (0.9, −2.9) → **(25.6, −27.7)**，构图 20.0 → **78.0**；
`shot_063` 构图 20.0 → **87.4**。改前它们都是"主体在画外"的 20 分。

## 一起修掉的契约错配：`target_position` 写在**顶层**时被整条丢掉

草案 schema（`editor.EMIT_SHOT_DRAFT_PARAMETERS`）把 `target_position` 声明成动作项的
**顶层**字段，而 `action_requests` 原来只读 `params.target_position` ⇒ 模型按 schema
写的目的地被丢掉、只剩一句"`walk_to` 缺少 target_position，已跳过"
（`long10`/`long11` 各 **10 处**）。现在两个合法位置都认（优先 `params`）。
这一条与"机位锚点"是同一个病的两面：**都是"读的是计划里的旧地址，而不是当时的实际
状态"**。

## 怎么复算

```
# 改前（a938482）
git worktree add work/verify_anchor a938482
Copy-Item tools/blender_tests/test_phase3_audit.py work/verify_anchor/tools/blender_tests/ -Force
cd work/verify_anchor
blender --background --factory-startup --python tools/blender_tests/test_phase3_audit.py
  → failed ["the_camera_aims_where_the_character_is_now"]

# 改后
blender --background --factory-startup --python tools/blender_tests/test_phase3_audit.py
  → 7/7 passed
blender --background --factory-startup --python work/_axis_rebuild_probe.py -- \
    --project docs/evidence/20261003_chunked_long9/project --out work/_anchor_fix.json
```

`composition_before.json` / `composition_after.json` 是原始产物（逐镜构图分、六分项、
机位坐标）。

## 顺带量到的下一步（**不是**本轮改的）

角色现在**真的会走**了（walk_to 不再被跳过），于是暴露出计划侧的新问题：
LLM 写的 `walk_to` 目的地会**累积**到 25–30 m 之外（`shot_059` 伊恩走到
(26.5, −24.9)）。镜头是跟住了，但"剧本上的走位"已经跑出场景很远。
这是**计划面**的下一件事（要么在提示词里给出场景边界/站位预算，要么在解析期
拒绝超出房间的目的地并回灌原因），与本轮的锚点修复是两件事。

## 未验证

1. **还没有用新树跑真模型**：这里的 63.8 → 70.0 是"同一份工程重建"的引擎账；
   真跑的逐镜通过率要下一趟 64 镜才有。
2. `shot_014` / `shot_020` 的 R001 由 0 变 2：角色位置变了，轴侧判据随之变化，
   需要下一次真跑确认它是不是"模型让角色走过了轴线"。
