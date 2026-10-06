# 验收链全量跑（32/32 步）：**除 RK-13 外全绿**；链子按裁决**非零退出并逐字说明**

日期 2026-10-06 13:32。命令（冻结树，`git status` 只有本目录这一处未跟踪）：

```powershell
$env:BLENDER_EXE='D:\Blender 5.2\blender.exe'
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_tests.ps1
```

## 结果

| 项 | 结果 |
|---|---|
| **32 步** | **全部跑完**（`[n/32]` 从 1 到 32）；无步骤因自身失败中断 |
| Blender 契约 smoke | `SMOKE_OK 1.3.0 3.13.13 0` |
| headless 全链（plan→scene→delivery） | `state=DONE`、355 步、146 次 LLM 调用、19 次工具、64 镜、4584 帧、`built: true` |
| **门①–⑩** | **`held-out coverage gates: all passed`** |
| 裁决者口径（D12） | `accepted-class reviewed 210 = llm-panel 210 + third-party 0 + human-only 0` |
| E1 | **not passing**（如实报） |
| E2 | `not_measured`（如实报） |
| **链子退出** | **`FAILED: RK-13 -- the knowledge-stack red line is not met (E1 >= 0.70 / R3).` ＋ `This run is NOT green.`（非零退出）** |

⇒ **这正是第三方裁决要求的行为**（`docs/evidence/20261006-adjudication-kimi/`）：
红线未达 ⇒ 链子**不许**打印 "All checks passed"、**不许** `exit 0`；
而且它明说"验收状态必须逐字带着这条"。

## 与 2026-10-05 那次长跑的区别

| | 20261005-213820 | **本次 20261006-133244** |
|---|---|---|
| 门①–⑩ | 全 pass（canonical） | **全 pass** |
| RK-13 | failed，但链子**仍 exit 0** | **failed ⇒ 非零退出 + NOT green** |
| 裁决者类别 | `human,llm-panel` | `human,llm-panel,third-party`（用户 2026-10-06 授权） |

## 这一批之后仍未收口的（就这两件，都是用户侧）

1. **RK-13 那条红线本身**：`docs/evidence/20261006-deep-pool-refuted/` 已把它判成
   **"当前测量协议下不可达"**（可达上界约 0.46–0.47，最好重排器已拿到约 93%）。
   ⇒ 要改就**只能改测量协议**（判据级，须用户拍板）；不改就**如实红着**。
2. **门⑦ 的 human 一格**：`human-only` 仍是 0（第三方已授权代裁并经 GPT-6A 重跑 212 条，
   但**夹具暂时不换**——见 `docs/evidence/20261006-adjudication-gpt6a/` 的 oracle-pin 耦合说明）。
