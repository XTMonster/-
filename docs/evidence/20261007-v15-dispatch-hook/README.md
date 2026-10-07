# 自动派发 hook：派发前分析（目标 × 耦合性）＋ 禁止子 agent 派子 agent

**run-id**：20261007-v15-dispatch-hook
**触发**：用户 2026-10-07 两条指令——①「写一个自动派发子 agent 的 hooks」；
②「**不允许子 agent 派出子 agent，写入 hooks 中**」；③「让 hooks 先做一次
派发前的分析，以及每个子 agent 的目标与耦合性评估，再规划决定要不要派出子
agent，派出多少」。
**纪律**：只加"派发决策"机制，**判据/阈值/门限一个字未动**（R-5）；派发权只在主线。

---

## 1. 交付物

| 文件（仓库镜像） | 安装位 | 作用 |
|---|---|---|
| `tools/hooks/dispatch-board.ps1` | `~/.codex/hooks/` | 派发板：**派发前分析 ＋ 批次决定**（ASCII-only） |
| `tools/hooks/dispatch-board.md` | 同上 | 中文模板（脚本只做占位符替换） |
| `tools/hooks/dispatch-board.selftest.ps1` | 同上 | 自检 **25/25** |
| `tools/hooks/guard-pretool.ps1` | 同上 | PreToolUse 守卫：**拒绝子 agent 派发** |
| `tools/hooks/selftest.ps1` | 同上 | hooks 总自检 **133 checks / 0 failures** |
| `执行文档v1.5/dispatch_graph.json` | 仓库 | 27 卡 ＋ 8 门的机器可读 DAG |
| `tests/test_dispatch_graph.py` | 仓库 | DAG 结构守卫（ID 唯一／依赖存在／无环／并发上限／阶段门） |

## 2. 派发前分析：每张卡的"目标 × 耦合性"

板子对**每一张卡**先算四个量，再给批次决定：

* `goal`：卡的目标（来自图）；
* `coupling`：**写集与多少张别的卡共享**（两两比对，目录项以 `/` 结尾按前缀算）；
* `deps_depth`：依赖链深度；
* `frozen_instruments`：是否触碰**冻结仪器**——清单从
  `tests/plan_v4_instruments.sha256.json` **实时**读，不手抄。

实测输出（本仓库真实图，节选）：

```
- P4-T3 | state=done | goal: forbid 反查补挂（守门激活）
    coupling=1 cards share files | deps_depth=0 | frozen_instruments=block_director/knowledge/hypergraph.py | files: ...
    verdict: already done
- P7-T2 | state=pending | goal: 文档同步与提交
    coupling=2 cards share files | deps_depth=1 | frozen_instruments= none | files: ...
    verdict: HOLD (mode:user)
```

**批次决定**（机械、可复核）：

```
- DISPATCH 0 agent(s). Every remaining card is blocked by one of: dependency,
  write-set coupling with an in-flight card, mode=serial (same-file double write),
  mode=user (needs the user), mode=gate (stage gate), or the parallelism cap.
- Falling back to SERIAL execution is the correct move; do not raise the cap or
  ignore coupling to look parallel.
```

每次分析的机器可读快照落 `docs/evidence/_v15_dispatch/last_board.json`
（`dispatch_now` ＋ 逐卡 `state/mode/coupling/deps_depth/frozen/reason/files`），
事后可复核"当时为什么这么派"。

## 3. 禁止子 agent 派子 agent（硬拦截，不是提示词）

**判别依据**（真实 payload 对照）：PreToolUse 事件里**子 agent 带
`agent_id`/`agent_type`，root 线程两者都没有**（实测 4 条子 agent 事件有、2 条 root 事件无）。

**抓到的坑**：hook 收到的工具名是 `collaborationspawn_agent`——
命名空间**拼接、无分隔符**（同类还有 `collaborationlist_agents`、
`collaborationinterrupt_agent`）。第一版正则按"分隔符"写，**没拦住**（探针实测通过）；
改成 `(collaboration)?(spawn_agent|followup_task|...)` 后才生效。

**规则**：子 agent 调 `spawn_agent` / `followup_task` → `permissionDecision: deny`；
`interrupt_agent` / `list_agents` 仍放行；root 线程不受影响；每次拒绝写一行
`DENY {ts,tool,agent_id,blocked[]}` 到 `hooks/guard.log`。

**自检**（`selftest.ps1` 新增 8 条）：子 agent × {`spawn_agent`、`followup_task`、
`collaboration.spawn_agent`、`collaborationspawn_agent`、`collaborationfollowup_task`}
全部 deny；子 agent × {`Bash`、`apply_patch`、`collaborationinterrupt_agent`、
`collaborationlist_agents`} 全部放行；root × {`spawn_agent`、`followup_task`} 放行。

## 4. 自检读数（本批）

```
powershell -File hooks\selftest.ps1              -> checks: 133  failures: 0   HOOK SELFTEST PASS
powershell -File hooks\dispatch-board.selftest.ps1 -> passed 25 / failed 0
python -m pytest tests\test_dispatch_graph.py    -> 4 passed
```

## 5. 本轮的派发决定（如实记）

派发板给出 **done 25/27｜在飞 0｜可派发 0**：剩下 P5-T2（换代，须用户点头）与
P7-T2（提交口径，须用户确认）都是 `mode:user`，**不派**。
另外 P4-T3 被分析标出**触碰冻结仪器** `block_director/knowledge/hypergraph.py`
——这正是它触发"第二十八次显式重新冻结"的原因（见
`docs/evidence/20261007-v15-contracts/README.md` §2）。

> 教训（已写进 `dispatch-board.md`）：**派发权只在主线**。本批曾出现子 agent
> 自派孙子去抢同一批文件、把派发板的 `inflight` marker 改乱（把两张卡标成在飞而
> 实际没人做）。
