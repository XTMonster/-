# Codex Hooks：工作契约注入 + 红线守卫

这套 hooks 把"审查先行 / 并行 / 不许降级 / 不许跳测试 / 持续执行"的流程规则，
变成每轮对话都会注入的上下文，并机械拦截"删测试、跳测试、破坏性 git 操作"。

## 文件

| 文件 | 作用 |
| --- | --- |
| `../hooks.json` | 钩子注册（SessionStart / UserPromptSubmit / SubagentStart / PreToolUse） |
| `workflow-contract.md` | 每轮注入的强制工作契约（中文，直接改这个文件即可调整规则） |
| `model-routing.md` | 模型分工＋**联合会诊**契约：想法 / 难题 / 质量审核 → 子 agent 的 DeepSeek × GLM-5.3 双份判词；执行 → 主线 DeepSeek |
| `consult-trigger.md` | 「自动会诊触发」模板：按提示词判定 `hard` / `review` / `idea` 并拼出要跑的命令 |
| `github-reuse.md` | 「GitHub 复用检查」：设计 / 规划 / 执行文档 / 程序设计类请求**先找现成方案再用**（候选清单＋许可证门＋决定留证） |
| `classify-prompt.md` | **语义分类器**的系统提示：把这一轮请求判成 `design` / `idea` / `review` / `hard`（hook 里调一次 DeepSeek，~1 s） |
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
- **两条按提示词自动触发的契约**（判定在 `inject-context.ps1` 里，**不需要人工点名**）：
  * **判定方式＝关键词 ∪ 语义（2026-10-05 升级）**：关键词表（快、确定性、离线）＋
    一次 **DeepSeek 语义分类**（`classify-prompt.md` 作系统提示、JSON 模式、`max_tokens=256`、
    **8 s 硬超时**，实测往返 ~1 s）。两条路**取并集**：语义能补关键词看不见的说法
    （例：「帮我搞个能替代现有检索层的东西」→ `design`+`idea`），关键词能兜住语义分类失败。
    **fail-open**：缺 key／超时／解析失败一律退回关键词，并在注入块里写明
    `source=keyword (semantic unavailable: …)`；判决与耗时逐轮记进 `hooks/classify.log`
    （**只记长度不记正文**）。`CODEX_CLASSIFY_STUB`（内联 JSON 或文件路径）可替换这次调用，
    所以 selftest **全程离线**、确定性。
  * **自动会诊**：`hard`（难题/为什么/诊断/根因…）／`review`（审查/复核/验收/对抗…）／
    `idea`（方案/取舍/架构/设计/规划/执行文档…）——命中即注入 `consult-trigger.md`，
    拼好 `panel_consult.py` 命令与从提示词里抽出的 `--source`。
  * **GitHub 复用检查**：设计 / 规划 / 执行文档 / 程序设计类（设计、规划、计划、执行文档、
    架构、程序、实现、重构、选型、框架、依赖、复用、现成、开源、第三方、轮子，
    以及 **魔改 / 移植 / 改造 / 二次开发 / fork / vendor / patch**）——命中即注入
    `github-reuse.md`：**先到 GitHub 全量检索有没有可用方案，有就用**；出候选清单
    （≥3 条，含最近提交与许可证）、许可证门（GPL/AGPL/无证不得引入），并作为
    `--context` 喂给同轮的联合会诊。
    候选表的最后两列就是 `①能否直接用 ｜ ②魔改后能否用`——**调研与判定是同一个动作**
    （看到一个候选就**当场**过一遍下面的本项目约束表），**决定从这两列直接读出**。
    **决定是四选一**：① 直接采用 ② **魔改后采用**（fork／局部改造／**移植其中一段**）
    ③ 弃用 ④ 自研。选了 ② 必须逐条回答：**改造点**（`文件:函数`）、**改造量级**
    （改造量≈自研就要如实记）、**上游可跟踪**（fork ＋ rebase／维护 patch）、**依赖代价**
    （只用一个文件就移植那一段，别拉整库）、**衍生许可**（MIT/BSD/ISC 保留声明与许可证全文；
    Apache-2.0 另加 NOTICE 并标明改动；MPL-2.0 改动文件同许可公开；**GPL/AGPL 不得引入**；
    **无许可证／NOASSERTION 既不能复制也不能改**）、**魔改后的验收**（跑本仓库全套测试，
    判据与阈值一字不动，并留 patch／差异清单）。
    **魔改与否必须对着本项目当前的实际情况判**（§4b）：先读 `AGENTS.md` 状态块、
    `ACCEPTANCE_STATUS.md`、`pyproject.toml`，再逐条过"Blender 自带 Python 装不了第三方包／
    零运行时依赖／确定性与可重放／判据不许动／许可门／自研规模与数据模型已定／本机资源与
    可用模型／当前真实瓶颈"这八条，每条写"不适用／代价／直接出局"；落笔格式固定为
    `候选 | 能否直接用 | 魔改点与量级 | 撞了哪条本项目约束 | 结论 | 证据`。
    验收判据＝本仓库现有的链（门①–⑩ ＋ pytest ＋ 探针清单），**降级一律不算**。
  * 两类**互相独立**：一个设计类请求会**同时**拿到"复用检查"与"联合会诊"两块。
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
