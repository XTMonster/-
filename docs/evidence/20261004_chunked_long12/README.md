# long12：R003 **广播**被量出来——同一份工程，0/64 → 15/64

**结论**：这一趟真跑（`run_id 67d8e780a1ca`，DeepSeek sidecar，64 镜，`DONE`，
交付 133 个文件）记录了 **逐镜通过 0/64、R003 1003 条**。把**同一份**
`long12/project` 用当前规则重建复评，数字是 **15/64、R003 7 条**——差出来的
那部分不是模型写坏的，是**规则把一处重叠广播到了每一张含该角色的镜头审计里**：

```
全片真正的重叠只有 7 处（shot_035/038/044/047/054/055/056）
每条消息出现在 40–48 张镜头审计里（角色在那些镜里出场）
⇒ 312 条终审 R003、64/64 镜红、逐镜通过塌成 0/64
```

## 三跑对照（终审轮，同一份 `fixtures/script_long_61.md`）

| 指标 | long10 | long11 | **long12（跑时）** | **long12（规则收口后复评）** |
|---|---|---|---|---|
| 终审逐镜通过 | 15/64 | 35/64 | **0/64** | **15/64** |
| R003 动作重叠 | 173 | 13 | **1003（终审 312）** | **7** |
| R001 越轴 | 3 | 6 | 81（终审 28） | 27 |
| COMPOSITION 低分 | 126 | 131 | 128（终审 32） | 39 |
| 构图分中位 | 71.55 | 71.3 | 69.5 | 65.9 |

单跑方差照旧很大（模型每跑写不同的草案）：long12 这一跑的动作比 long11 密
（`motions` 137 vs 114、`keyframes` 7873 vs 5487），所以真实重叠更多（7 vs 3），
但**没有**多到 312 条那个量级。

## 复算

```
python work/_axis_audit.py docs/evidence/20261004_chunked_long12/runs/audit_log.jsonl   # 跑时数字
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261004_chunked_long12/project --out work/_reaidit_long12.json
  → {"shots": 64, "passed": 15, "rules": {"COMPOSITION": 39, "R001": 27, "R003": 7},
     "composition_median": 65.9}
```

`_reaudit_probe.py` 是"同一份产物、只换规则"的复评器：重建工程 → 逐镜跑驱动器
用的同一个 `BpyShotAuditor` → 落 JSON。守门用例
`tools/blender_tests/test_phase3_audit.py::r003_is_scoped_to_the_shot_being_audited`
（一镜有重叠、一镜干净：干净的镜头**不许**带 R003）。成对复验：
`worktree at 3c3e716` ＋ 新用例 → **fail**；新代码 → 9/9 pass。

## 仍未解决（如实记）

* R001 27 条 / COMPOSITION 39 条仍在——前者多数是"角色走位跨过轴线"（§六十五
  已让规则说清根因），后者仍等"轴线要不要跟着走位重估"与"走位边界"两条裁决；
* 这一趟的 `export/` 里 mp4 按 .gitignore 不入库，`shots.json` 等人在库里。
