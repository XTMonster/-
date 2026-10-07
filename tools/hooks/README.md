# 自动派发 hook（dispatch-board）

这套文件把 `执行文档v1.5/dispatch_graph.json`（机器可读的任务卡 DAG）变成
**每轮自动注入的"派发板"**：Codex 每收到一条用户消息时，hook 会算出
**现在能安全并行派发哪些任务卡**，并把 `spawn_agent` 指令直接写进上下文。

## 文件

| 文件 | 作用 |
|---|---|
| `dispatch-board.ps1` | hook 本体（**ASCII-only**，PS 5.1 安全）。`-DryRun`/`-Status` 看板；`-Claim/-Mark/-Unclaim <卡号>` 维护状态；默认按 hook 事件输出 `additionalContext` |
| `dispatch-board.md` | 派发板的中文模板（`.ps1` 只做占位符替换，中文全留在 `.md`） |
| `dispatch-config.json` | 工作区定位（`workspace`） |
| `dispatch-board.selftest.ps1` | 自检（16 项，全离线）：ASCII-only、DAG 规则、并发上限、冲突/依赖原因码、状态往返 |

## 安装

把这四个文件复制到 `%USERPROFILE%\.codex\hooks\`，并在
`%USERPROFILE%\.codex\hooks.json` 的 `SessionStart` 与 `UserPromptSubmit`
各加一个 group：

```json
{
  "type": "command",
  "command": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\\Users\\<你>\\.codex\\hooks\\dispatch-board.ps1",
  "timeout": 20,
  "statusMessage": "生成自动派发板"
}
```

> 改 `hooks.json` 会让 `trusted_hash` 失效，Codex 会重新要求确认信任。

## 派发规则（四条硬边界，越界就不派）

1. **依赖全完成**（`depends_on` ⊆ done）；
2. **写集与在飞卡不相交**（`files` 逐个比对；目录项以 `/` 结尾按前缀算）；
3. **`mode=auto`**——`serial`（同文件双写／语义依赖）、`user`（⚖️ 须用户裁决）、
   `gate`（阶段门）都**不派**，交给主线串行执行；
4. **并发未到 `max_parallel`**。

不满足就给原因码 `depends:<ID>` / `conflict:<ID>` / `mode:serial|user|gate` / `cap`。
**宁慢不乱**：只要并行会伤质量（同文件、绕过门、未裁决），就退回串行。

## 派发前分析（每张卡：目标 × 耦合性）

板子不只是"列出能派的卡"，它先做一次**派发前分析**，再给批次决定：

* 每张卡一行的 `goal`（目标）、`coupling`（**写集被多少张别的卡共享**）、
  `deps_depth`（依赖链长度）、`frozen_instruments`（**实时**对照
  `tests/plan_v4_instruments.sha256.json`——触碰冻结仪器的卡要额外小心）；
* 然后给出 `本轮决定`：`DISPATCH N agent(s): <卡号>`，或者
  `DISPATCH 0` + 逐条原因；**耦合度越高越不许同时派**；
* 每次分析的机器可读快照落 `docs/evidence/_v15_dispatch/last_board.json`
  （`dispatch_now` / 逐卡 `state,coupling,deps_depth,frozen,reason,files`），
  以便事后复核"这次到底为什么这么派"。

## 子 agent 不得再派子 agent（hook 硬拦截，不是提示词）

`guard-pretool.ps1` 会**拒绝**子 agent 的派发调用：

* 判别：PreToolUse 事件里**子 agent 带 `agent_id`/`agent_type`，root 线程两者都没有**；
* 拦截：子 agent 调 `spawn_agent` / `followup_task`（真实写法是
  `collaborationspawn_agent` 这种**拼接无分隔符**的名字）→ `permissionDecision: deny`；
  `interrupt_agent` / `list_agents` 仍放行；root 线程不受影响；
* 留痕：每次拒绝写一行 `DENY {ts,tool,agent_id,blocked[]}` 到 `hooks/guard.log`。

背景（2026-10-07 实测）：子 agent 自派孙子后会**抢同一批文件**、把派发板 marker
改乱（曾把两张卡标成在飞而实际没人做）、并越界做别的卡。**派发权只在主线。**

## 状态

进度写在 `docs/evidence/_v15_dispatch/`：

```
docs/evidence/_v15_dispatch/done/<ID>.done        # 该卡完成
docs/evidence/_v15_dispatch/inflight/<ID>.claim   # 该卡在飞
```

## 自检

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\hooks\dispatch-board.selftest.ps1
```

## 与执行计划同步

`dispatch_graph.json` 与 `EXECUTION_PLAN.md` 的附录 A/B 同源；**改计划必须同步
改图**。`tests/test_dispatch_graph.py` 守住图的结构（ID 唯一、依赖存在、无环、
`max_parallel` 合理、阶段门存在）。
