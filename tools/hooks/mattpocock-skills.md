# Matt Pocock Skills（项目默认技能集，自动触发）

本项目默认使用 **mattpocock/skills**（仓库克隆：`.scratch/mattpocock_skills_probe_20261012/`，
已通过 `scripts/link-skills.sh` 链入 `~/.agents/skills`）。这些技能**按描述自动触发**：
任务命中某技能的应用场景时，无需用户点名也要按该技能执行；执行前先完整读该技能的
`SKILL.md`，再按其中引用加载所需参考文件，不要只凭技能名猜测内容。

## 按任务类型自动触发的技能（model-invoked，命中即用）

| 任务类型 | 技能 |
| --- | --- |
| 测试驱动开发 / 先写测试 / 修 bug 先复现 | `$tdd` |
| 报 bug / 崩坏 / 变慢 / 诊断 | `$diagnosing-bugs` |
| 查资料 / 文献 / 文档事实 / 背景研究 | `$research` |
| 设计模块接口 / 深模块 / 找接缝 | `$codebase-design` |
| 讨论术语 / 写或改 CONTEXT.md / ADR | `$domain-modeling` |
| 审查分支 / PR / 变更 | `$code-review`（双轴：标准 + 规格；遵守本项目并行派发规则） |
| 合并冲突 | `$resolving-merge-conflicts` |
| 搭 pre-commit / Husky / lint-staged | `$setup-pre-commit` |
| 替换测试里的 `as` 断言为 shoehorn | `$migrate-to-shoehorn` |
| 建练习目录结构 | `$scaffold-exercises` |
| 用一次性原型验证设计 | `$prototype` |
| 写 PR 描述 | `$pr` |
| 走人工交互向导（凭据 / 迁移 / 外部面板） | `$wizard` |
| 给 git 加安全钩子（阻止 push / reset --hard 等） | `$git-guardrails-claude-code` |
| 压力测试想法 / 计划 / 决策 | `$grilling` |
| 写 / 改给 agent 看的文档（AGENTS.md / CLAUDE.md / 技能） | `$writing-for-agents` |

## 仅用户点名才触发的技能（user-invoked，禁止模型自动调用）

`$setup-matt-pocock-skills`、`$ask-matt`、`$triage`、`$to-spec`、`$to-tickets`、
`$wayfinder`、`$handoff`、`$retro`、`$teach`、`$implement`、`$implement-spec`、
`$improve-codebase-architecture`、`$to-questionnaire`、`$wait-what`、`$grill-me`、
`$grill-with-docs`、`$writing-*`（in-progress 系列）等：用户输入技能名或明确要求时才用，
不得因任务相似而自动触发。

## 项目侧配置（已就位，直接用）

- `AGENTS.md` 的 `## Agent skills` 一节：issue tracker / triage labels / domain docs 三小节。
- `docs/agents/issue-tracker.md`：issue 与规格存在 `.scratch/<feature-slug>/` 下的本地 markdown。
- `docs/agents/triage-labels.md`：五个规范标签 1:1 映射。
- `docs/agents/domain.md`：单一上下文，`CONTEXT.md` + `docs/adr/`。

## 纪律

1. 技能描述与项目 `AGENTS.md` / hooks 契约冲突时，以项目契约与用户裁决为准；
   技能只补充流程与质量标准，不降低或绕过验收判据、阈值、红线。
2. 自动触发以"任务真的命中技能场景"为准：命中就按技能执行，未命中不必强行套用。
3. 本项目 hooks 已硬性禁止子 agent 再派子 agent、禁止删测/跳测/破坏性 git；
   技能里的派生子代理类步骤（如 code-review 的双轴并行）须遵守这两条。
4. 技能更新：`git -C .scratch/mattpocock_skills_probe_20261012 pull` 后重跑
   `scripts/link-skills.sh`，保持 `~/.agents/skills` 与上游同步。
