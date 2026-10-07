# 阶段门 G3 —— 三份冻结工程重建对照（P3-T2 / P3-T3 / P3-T4 之后）

**run-id**：20261007-g3
**对照基准**：`git worktree` 固定在 **HEAD `f6530c6`**（本批改动之前）的同一份
重建探针 `work/_reaudit_probe.py`，同一批冻结工程、同一条命令。
**纪律**：判据／阈值／门限一个字未动（红线 R-5）；证据落本目录（R-9）。

## 1. 本阶段做了什么

| 卡 | 内容 | 落点 |
|---|---|---|
| P3-T2 | 场级摆位锚点求解（`relation → 坐标`）＋ Blender 侧 `BD_Anchor_*` empty 进 Guides | `block_director/cinema/staging.py`、`layer3_engine/scene_executor.py`、`tests/test_staging_anchors.py`、`tools/blender_tests/test_anchor_staging.py` |
| P3-T3 | 灯光语义 → 预设矩阵（`resolve_lighting`）＋ 道具交互动词 → 跟随关键帧 | `block_director/cinema/lighting.py`、`block_director/cinema/props.py`、`tools/blender_tests/test_prop_interaction.py` |
| P3-T4 | **构图声明消费**：`shot.composition` → 对准点横向偏移 | `block_director/cinema/station.py::aim_offset_for_composition`、`layer3_engine/shot_builder.py`、`tests/test_composition_consumption.py` |

P3-T2/T3 只在新字段（`environment.anchors` / `environment.light` / 道具交互动词）
被声明时才生效；三份冻结工程都是 v1.2 时代的产物，**一个都没声明**。
P3-T4 同理：空声明的分支**原样返回求解器默认值**（单测
`test_an_empty_declaration_returns_the_default_untouched` 钉住这条）。

## 2. 重建命令（逐字）

```
# 「之后」（当前工作树）
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261003_chunked_long9/project  --out docs/evidence/20261007-g3/long9.json
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261004_chunked_long11/project --out docs/evidence/20261007-g3/long11.json
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261004_chunked_long12/project --out docs/evidence/20261007-g3/long12.json

# 「之前」：同一个 worktree 的同一支探针（git worktree add --detach E:\bd_head_f6530c6 f6530c6）
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261003_chunked_long9/project  --out docs/evidence/20261007-g3/long9.json
...（long11 / long12 同）
```

`REAUDIT` 行是**同一条**（重建 → `BpyShotAuditor().audit()` 逐镜）。

## 3. 读数（before = `f6530c6` ／ after = 本批）

| 冻结工程 | 逐镜通过 | 构图分中位 | 构图门 ≥70 | R 系列计数 |
|---|---|---|---|---|
| `long9` | 29 → **29** | 79.6 → **79.6** | 39 → **39** | `COMPOSITION 25 / R001 11 / R003 1` 两版逐项相同 |
| `long11` | 8 → **8** | 64.3 → **64.3** | 24 → **24** | `COMPOSITION 40 / R001 40` 两版逐项相同 |
| `long12` | 24 → **24** | 72.4 → **72.4** | 34 → **34** | `COMPOSITION 30 / R001 7 / R003 7` 两版逐项相同 |

**逐镜逐字段比对（不是只看汇总）**：三份工程的
`(shot_id, passed, score, errors)` 四元组序列**完全相等**（`identical_rows=True`），
即"每一条审计结论都没变"，不只是总数凑巧相同。

```
long9  identical_rows= True
long11 identical_rows= True
long12 identical_rows= True
```

## 4. 构图声明的 bpy 侧守门（P3-T4 真的接上了）

`tools/blender_tests/test_phase3_audit.py::declared_composition_overrides_the_default_aim`
（同一几何四镜，只换 `composition`）：

```
{"ok": true, "default_offset_m": 0.347, "center_offset_m": 0.0,
 "left_third_offset_m": 0.347, "right_third_offset_m": 0.347,
 "left_and_right_opposite": true, "default_matches_a_declared_side": true,
 "default_delta": [0.0, 0.3474], "left_delta": [0.0, -0.3474], "right_delta": [0.0, 0.3474]}
```

⇒ 居中 = 对准点回到主体（0.0 m）；左/右三分 = 朝相反两侧各 1/6 幅宽；
**不声明的那一镜与左/右三分之一的位移逐分量相同**（缺省就是 §10.4 视线留白）。

## 5. 未验证 / 边界

* 三份冻结工程都**没有**声明 anchors / light / composition ⇒ 本节证明的是
  "**空路径不回归**"，不是"新声明在真实工程里有效"。新声明的有效性由
  上面的四镜守门用例与 P3-T2/T3 的探针用例各自证明。
* 逐镜读数只覆盖 `BpyShotAuditor` 的规则面；导出/渲染面（helper 泄漏审计、
  道具跟随是否真的进关键帧）由 `test_anchor_staging.py` /
  `test_prop_interaction.py` 两条 Blender 探针各自证明。
