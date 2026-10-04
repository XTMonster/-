# Codex hook 包（本仓库留档 ＋ **自动会诊触发**）

这一目录是 `~/.codex/hooks/` 的**版本化快照**：hook 装在那里（全局生效），
但它的行为直接决定这个项目怎么被推进，所以在这里留一份可审、可复原的副本。
`README-upstream.md` 是这套 hook 原本的说明；本文件说明**本轮新增的自动触发**。

## 装到哪儿

```powershell
Copy-Item docs/agents/hooks/*.ps1  $env:USERPROFILE\.codex\hooks\ -Force
Copy-Item docs/agents/hooks/*.md   $env:USERPROFILE\.codex\hooks\ -Force
powershell -NoProfile -ExecutionPolicy Bypass -File $env:USERPROFILE\.codex\hooks\selftest.ps1
```

`hooks.json`（同样在 `~/.codex/`）把四个事件接到两个脚本：`SessionStart` /
`UserPromptSubmit` / `SubagentStart` → `inject-context.ps1`；`PreToolUse` →
`guard-pretool.ps1`。**不要**把 `--no-verify`、`git checkout --`、删测试一类的动作
当成可绕过的——`guard-pretool.ps1` 会在动手前拦下（自检里每条都有 PASS）。

## 新增：**自动会诊触发**（`inject-context.ps1` ＋ `consult-trigger.md`）

原来的《模型分工契约》是**一段被动文本**：它说"想法/审核/难题要联合会诊"，
但要不要真的开，全靠模型自觉。现在 `inject-context.ps1` 会在每次
`UserPromptSubmit` / `SubagentStart` 时**读这次的请求**，命中关键词就注入一段
**可执行指令**（`consult-trigger.md` 的模板）：

| 判定 | 触发词（中/英，`\uXXXX` 转义写进脚本，文件保持纯 ASCII） | 建议角色 |
|---|---|---|
| `hard` | 难题 / 卡住 / 阻塞 / 为什么 / 诊断 / 排查 / 死结 / 根因 / 报错 / 崩溃 / 疑难 ／ stuck · blocker · root cause · diagnose | 领域讲解,红队反方,实现顾问 |
| `review` | 审查 / 审核 / 复核 / 验收 / 对抗 / 复算 / 校验 ／ review · audit · verify | 测试与验收,规格一致性 |
| `idea` | 方案 / 取舍 / 权衡 / 思路 / 架构 / 怎么做 ／ design · approach · tradeoff | 领域讲解,实现顾问 |

优先级 `hard > review > idea`（既是难题又是设计问题 → 按难题办）。注入的内容包含
**可直接粘贴的命令**、以及**从请求里自动抽出的 `--source` 候选**（最多 6 个，
匹配 `*.py|md|json|jsonl|ps1|yaml|toml`）。没有任何源码候选时会明确写
`--source <file:start-end>`，提醒"不给源码，工具会拒调用"。

三条纪律写在注入文本里，且**不是建议**：

1. 两侧同一份包、同一个角色提示；结果落 `both` / `severity_conflict` /
   `glm_only` / `deepseek_only` 四栏；
2. **一侧缺席（空正文 / 超时 / `unparsed`）永远不算同意**；
3. 判词不改判据/门限/阈值，落地与提交仍在主线（DeepSeek）做。

## 设计上踩过的两个坑（写在这里，免得下次再踩）

* **`.ps1` 必须纯 ASCII**：Windows PowerShell 5.1 把无 BOM 的 UTF-8 当 ANSI 读，
  中文字面量会把脚本**解析成语法错误**（实测：一个中文注释让整份脚本报
  `Unexpected token '}'`）。所以脚本里的中文一律写成 `\uXXXX` 正则转义，
  成句的中文放在 `.md` 里（脚本用 `System.Text.Encoding]::UTF8` 显式读）。
* **判定标记要挑"只有触发块才有"的串**：`panel_consult.py` 本身就在**每次都注入**的
  路由契约里，拿它当"触发了"的判据会**恒真**——自检当场抓到这个假阳性。
  现在判据用触发块独有的输出目录名 `--out work/_panel_*`。

## 自检

`selftest.ps1` 覆盖 82 项：原有 73 项（PreToolUse 拦截、注入契约、UTF-8 输出契约）
＋ 本轮 9 项（三类触发的桶与 `--source` 抽取、普通请求**不**触发、契约仍在）。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $env:USERPROFILE\.codex\hooks\selftest.ps1
# => checks: 82  failures: 0    HOOK SELFTEST PASS
```
