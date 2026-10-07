# `20261007-v15-relay-502` — 新通道（中继 `qwen3.8-max-0902` ＋ `reasoning_effort=max`）做**引擎真跑**不稳定

**结论**：中继通道在**计划调用**（stage A，长提示 ＋ 工具调用）上连续返回 **502**，
两次尝试、共 **6 次计划调用全部失败**，两次运行都以
`分镜计划生成失败（已达最大尝试次数）` 收场。同一通道在**会诊/标注**那类调用上
当天是好的（`work/_qwen_orphan_fix/`、`docs/evidence/_v15_stage8/c1_recap/v2_judge/`
共 14 次成功调用）。⇒ **问题出在"长提示 ＋ 工具调用"这一形状上，不是 key 或模型名**。

## 实测

| 尝试 | 目录 | 上游 | 档位 | 计划调用 | 结果 |
|---|---|---|---|---|---|
| 1 | `audit_attempt1.jsonl` | `https://llm.goaichat.top/v1` | `reasoning_effort=max` | 2 次（112.2 s / 94.0 s）→ **502** | `run_failed`，镜头 0 |
| 2 | `audit_attempt2.jsonl` | 同上 | 同上 | 4 次 → **502** | `run_failed`，镜头 0 |

`attempt1` 的 `understand` 调用是**成功**的（121.2 s、4083 prompt ＋ 4707 completion），
所以通道本身可用；失败集中在计划那一步（提示里带整份分镜表 ＋ 工具 schema）。

## 这对"思考强度拉到最大"意味着什么（如实记，不替用户决定）

用户 2026-10-07 的指令是"新模型思考强度拉到最大"。实测：

* **分析/标注通道**：`reasoning_effort=max` 可用，且确实把 reasoning token
  从 42 拉到 305（`work/_probe_qwen_thinking.py`）——本轮的会诊与 C1 复判都跑在这个档位上；
* **引擎真跑**：这个档位下计划调用 6/6 失败。**没有**试过降档跑真跑
  （那需要用户明示——降档是改变用户明示的口径），所以引擎那一侧的真跑一律走
  DeepSeek 上游（与 `20261003_real_ds` / `20261003_real_long` 同一条理由：
  那一跑量的是**引擎行为**，不是哪个模型更会拍片）。

## 复算

```
python - <<'PY'
import json,pathlib
rows=[json.loads(l) for l in pathlib.Path('docs/evidence/20261007-v15-relay-502/audit_attempt1.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
print([r['message'] for r in rows if r['kind']=='llm_error'])
PY
```
