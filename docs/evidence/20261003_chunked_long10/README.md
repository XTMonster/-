# long10：轴侧修复之后的第一次真跑（64 镜，DeepSeek sidecar）

**结论**：`43892a3`（单人镜头也待在已确立轴侧）之后跑的第一趟真模型 64 镜，
**R001 由 64 条降到 3 条**，逐镜终审通过 5 → **15**、构图分中位 52.65 → **71.55**、
构图门 20 → **37**。R001 与构图是这一轮**唯一改过的引擎路径**（轴侧镜像），
其余项（R008/R009/R004 归零、R003/R019 减半）**主要来自模型这一趟写得好**，
单跑对比含模型方差，不能全算在引擎账上——引擎账在
`docs/evidence/20261003-axis-single-shot/`（同一份工程前后对拍：越轴 20 → 0）。

## 运行

```
blender --background --factory-startup --python tools/run_headless.py -- \
  --sidecar --script fixtures/script_long_61.md --build --preset fhd16x9 \
  --out docs/evidence/20261003_chunked_long10 \
  --save docs/evidence/20261003_chunked_long10/project \
  --export --export-dir docs/evidence/20261003_chunked_long10 \
  --wall 7200 --llm-timeout 300 --max-llm-calls 0
```

`run_id = 1b398374ac8b`，`state = DONE`，64 镜 / 4584 帧 / `built=true`，
交付 133 个文件（`export/` 13.7 MB 视频按 .gitignore 不入库），
`llm_calls = 314`、`tool_calls = 200`、`react_rounds = 2`、起草 64/64 成功。
落盘的 `project.bdproj` 校验仍报 **1 条 S3**（`shot_043` 里伊恩两个动作窗口
1–24 与 20–44 重叠）——那是**模型自己排的重叠**，如实记（见下"同镜重叠"）。

## 与 long9 的逐项对比（都是各跑的**终审轮**）

| 指标 | long9（`925ef79` 前后） | **long10（`43892a3`）** |
|---|---|---|
| 终审逐镜通过 | 5 / 64 | **15 / 64** |
| 构图分中位 | 52.65 | **71.55** |
| 构图门（≥70） | 20 / 64 | **37 / 64** |
| R001 越轴 | 64 | **3** |
| R003 动作重叠 | 233 | 173 |
| COMPOSITION 低分 | 181 | 126 |
| R019 视线/构图相关告警 | 86 | 35 |
| R012 | 35 | 25 |
| R010 30° 规则 | 11 | 10 |
| R005 在画 | 129 | **2** |
| R008 地面/悬空 | 131 | **0** |
| R009 机位距离 | 64 | **0** |
| R004 视锥 | 63 | **0** |

复算命令（只读审计日志，不跑 Blender）：

```
python work/_axis_audit.py docs/evidence/20261003_chunked_long10/audit_log.jsonl
```

## 这一趟真正证明的事

1. **轴侧修复在真模型路径上生效**：`BLOCKDIRECTOR_RESULT.build.results[].warnings`
   里有 **23 镜**带镜像说明（"落在已确立轴线的另一侧，已关于轴线镜像…"，
   23 条去重后；`build.warnings` 里另有同样的 23 条汇总副本），逐镜 R001 由 64 → 3。
   复算：`work/_run_long10.log` 里的 `BLOCKDIRECTOR_RESULT` 一行 ——
   `python -c "…raw_decode…"` 或直接 `Select-String 已关于轴线镜像`。
   剩下那 3 条里终审只留 1 镜（`shot_001`）——它是**轴线建立之前**的第一镜
   （单人中景建立场景，机位在轴线确立前就摆好了），属"还没确立轴线时不该管"
   的边界，已记进 `ACCEPTANCE_STATUS.md` §五十九 的未决项。
2. **逐镜通过率仍然低**（15/64）：主因换成了 **COMPOSITION 126 条**（三分线交点 /
   视线留白两个分项），其次是 **同镜动作重叠 R003 173 条**（模型自己排的窗口打架，
   落盘的 SDL 校验也抓到同样的 S3）。这两条是下一层，**不是轴侧问题的残留**。
3. **单跑波动**：19/64（long6）、0/64（long8）、5/64（long9）、15/64（long10），
   同一个引擎。要把"逐镜通过率"当验收线，得先定"跑几次、取什么统计量"
   （§五十七 已记，属规格裁决）。

## 产物

* `audit_log.jsonl`（2076 事件，`sha256 1fcc6e35…`）、`llm_trace.jsonl`（314 条）、
  `knowledge_trace.json`、`run_manifest.json`（含 holdout/index/cases 指纹）。
* `export/`：`shots.json`（64 镜机位/焦距/帧区间）、`prompts.md`（每镜提示词）、
  `script_compliance.json`、逐镜 mp4 与 `blockout_full.mp4`（不入库）。
* `project/project.bdproj`：可直接 `tools/rebuild_project.py` 重建复评。
