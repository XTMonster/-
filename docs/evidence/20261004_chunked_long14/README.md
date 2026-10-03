# long14：轴侧状态机顺序化之后的第一次**真跑**（64 镜，DeepSeek sidecar）

**结论**：`state=DONE`、**建了场景**、交付 **133** 个文件、终审**逐镜通过 29/64**
（错误按规则：COMPOSITION 24、R001 13、R003 6、R011 1），构图分中位 **77.3**、
构图门（≥70）通过 **40** 镜。这是 long9…long14 里**最好的一次真跑**，但**跑与跑之间
方差很大**（模型每跑写不同草案），所以它**不能**单独当作 §七十四 那个修的证明——
那条修的证据是结构性的（构建器表 ＝ 真机位表，见 `docs/evidence/20261004-r001-v21/`）。

## 这一趟是什么

| 项 | 值 |
|---|---|
| `run_id` | `9ab4a7ed14d5` |
| 剧本 | `fixtures/script_long_61.md`（64 镜 / 4584 帧） |
| 通道 | sidecar `127.0.0.1:8765` → DeepSeek `deepseek-chat`（本机在跑的实例） |
| 结果 | `DONE`、`built=true`、`export.ok=true`、**133** 个交付文件 |
| LLM | **291** 次调用（上限 512）、1 266 113 token、LLM 墙上时间 **471.9 s** |
| 工具 | 200 次；审计 **195** 次，其中 **141** 次当轮没过（走修复） |

复算：

```
python work/_axis_audit.py docs/evidence/20261004_chunked_long14/runs/runs/audit_log.jsonl
blender --background --factory-startup --python work/_reaudit_probe.py -- \
    --project docs/evidence/20261004_chunked_long14/project --out work/_reaidit_long14.json
  → {"shots": 64, "passed": 24, "rules": {"COMPOSITION": 29, "R001": 13,
     "R003": 6, "R011": 1}, "composition_median": 74.15}
```

**跑时 29 / 复评 24** 的差不是规则变了，而是复评走的是"重建工程 → 逐镜审核"：
真跑里那些**修复回合改过的机位**不在 `project.bdproj` 里（工程存的是 SDL 计划），
所以重建出来的机位更"原始"。两个数都要看，别只挑大的那个。

## 顺带一条**负对照**：`docs/evidence/20261004_chunked_long13/`

那是同一条命令**漏了 `--build`** 的一趟：没建场景，工厂默认的 `Cube` 留在场景里，
`--export` 被安全闸拦下并如实报错——

```
BLOCKDIRECTOR_EXPORT {"ok": false, "aborted": true, "files": 0,
  "reason": "导出中止：以下对象会出现在参考视频中：Cube"}
```

留着它，是因为这正是 §15 要的行为：**导出宁可中止，也不把辅助物泄进参考视频**。
（两趟的 `run_id` 不同：long13 `167dc323ae27` / long14 `9ab4a7ed14d5`。）

## 仍未做

* `project.bdproj` 的落盘校验**报了 7 条**（S3 动作重叠 6、S6 对白装不下 1）——
  `save_run_project` 如实带回结论、文件照写（这是 §14 的口径，不是新缺陷）；
* R001 那 13 条错误与 63 条 warning（"轴线被走位重建、但有合法桥接"）说明
  `_axis_rebuild` 的**参照系**仍待换（§74.4）；
* COMPOSITION 24 条低分仍在：口径裁决（三分线**交点** vs 三分**线**）没拍板，
  谁都不许靠调 `PASS_SCORE` 变绿。
