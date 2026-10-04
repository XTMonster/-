# Codex Hooks：工作契约注入 + 红线守卫

这套 hooks 把"审查先行 / 并行 / 不许降级 / 不许跳测试 / 持续执行"的流程规则，
变成每轮对话都会注入的上下文，并机械拦截"删测试、跳测试、破坏性 git 操作"。

## 文件

| 文件 | 作用 |
| --- | --- |
| `../hooks.json` | 钩子注册（SessionStart / UserPromptSubmit / SubagentStart / PreToolUse） |
| `workflow-contract.md` | 每轮注入的强制工作契约（中文，直接改这个文件即可调整规则） |
| `model-routing.md` | 模型分工＋**联合会诊**契约：想法 / 难题 / 质量审核 → 子 agent 的 DeepSeek × GLM-5.3 双份判词；执行 → 主线 DeepSeek |
| `session-start.md` | 仅会话开始时追加的"开工清单" |
| `subagent-protocol.md` | 子代理（并行审查）角色分工协议 |
| `inject-context.ps1` | 按事件读取上面的 md，输出 `hookSpecificOutput.additionalContext` |
| `guard-pretool.ps1` | PreToolUse 守卫：命中红线则输出 `decision:block` 并给出理由 |
| `selftest.ps1` | 自检：用 hooks.json 里的真实命令行跑 70 项断言 |

## 行为

- **SessionStart / UserPromptSubmit**：把 `workflow-contract.md` 作为 `additionalContext`
  注入模型上下文（会话开始再加一份开工清单）。压缩（compact）后由下一条 prompt 重新注入。
- **模型分工与联合会诊（三类事件都注入，子代理同样看到）**：`model-routing.md` 规定
  ① 想法生成 / **难题攻关** / 质量审核走**子 agent 联合会诊**——同一份包、同一个角色提示，
  DeepSeek 与 **GLM-5.3** 各出一份判词，结果按
  `both` / `severity_conflict` / `glm_only` / `deepseek_only` **四栏**记账，
  **一侧缺席不算同意**；工具是 `tools/panel_consult.py`（判词记 `reviewed_by: "llm-panel"`）。
  ② 执行（改码 / 测试 / 构建 / 导出 / 提交）只在**主线 DeepSeek** 上做。
  注意：本机 `~/.codex/models.json` 里只有 `deepseek-flash` / `deepseek-v4-pro`，
  GLM-5.3 **不是可被 spawn 的 agent 模型**，所以"用 GLM-5.3"落地为**判词经它的通道产出**。
- **SubagentStart**：给每个子代理注入并行审查协议（先声明不重复的角色视角）。
- **PreToolUse**：拦截
  - 删除 / 移动测试文件（`rm`、`Remove-Item`、`git rm`、apply_patch 删除 `tests/` 等）；
  - 跳过测试（`--deselect`、`--ignore`、`--skip`、`-k "not ..."`、`xit(`、`mark.skip`）；
  - 破坏性 git（`reset --hard`、`checkout --`、`restore`、`clean -f`、`stash drop/clear`、
    `push --force`、`branch -D`、`commit --no-verify`）。
  命中时工具调用被拒绝，模型会看到理由并被要求先征求你的明确同意。

> **改 `.ps1` 的铁律：保持 ASCII-only。** 实测（2026-10-04）：在 `inject-context.ps1`
> 的注释里写中文，Windows PowerShell 5.1 会把 BOM-less UTF-8 当 ANSI(GBK) 读，
> **吞掉紧跟其后的那一行赋值**——症状是"新契约明明在文件里，就是注入不进去"。
> 中文只放 `.md`（脚本用 `ReadAllText(..., UTF8)` 显式读）。

## 自检

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\hooks\selftest.ps1"
```

## 信任

Codex 要求先信任钩子才会运行。信任状态写在 `~/.codex/config.toml`：

```toml
[hooks.state."C:\\Users\\<你>\\.codex\\hooks.json:pre_tool_use:0:0"]
enabled = true
trusted_hash = "sha256:..."
```

- 改 `hooks.json`（命令、超时、事件）会让 `trusted_hash` 失效，Codex 会重新要求确认。
- 只改 `.ps1` / `.md` 内容不会失效（hash 只覆盖钩子定义）。
- 查看当前状态：Codex 设置里的 Hooks 面板，或 `codex app-server` 的 `hooks/list`。
- 单次跳过信任（危险）：`codex exec --dangerously-bypass-hook-trust ...`

## 关闭 / 移除

- 临时关闭：在 Codex 的 Hooks 设置里把对应钩子设为 disabled，或在
  `~/.codex/config.toml` 的对应 `[hooks.state."..."]` 下写 `enabled = false`。
- 完全移除：删除 `~/.codex/hooks.json`（以及 `~/.codex/hooks/` 目录），
  并清掉 `config.toml` 里的 `[hooks.state."..."]` 小节。
