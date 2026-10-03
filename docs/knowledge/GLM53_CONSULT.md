# 常驻外部顾问：GLM 5.3（智谱）多角度会诊

**用途**：遇到难处随时把**冻结的产物**交给外部模型族（智谱）按**不同角色**看一遍，
再把它的每一条断言在仓库里**证实或证伪**。它不是"权威"，是"换一双眼睛"——
这一轮三处真缺陷（单人镜头的轴侧、修复回合点不动草案工具、动作窗口重叠）
都是换角度才看见的。

## 怎么用

```
$env:GLM_API_KEY = "<key>"        # 只从环境变量读，绝不入库
python tools/glm_consult.py --roles 规格一致性,红队反方 \
    --question work/_q.md \
    --source block_director/cinema/axis.py:160-240 \
    --context docs/evidence/<run>/README.md \
    --out work/_consult/
```

* **必须先给源码**（用户 2026-10-04 的追问："会诊 AI 有先看目前落实的情况与源码么？
  了解项目才能提出想法"）。`--source <文件[:起-止]>` 把源码**逐字带行号**放进包；
  **一份都不给时工具直接拒绝调用**，除非显式 `--question-only`（承认这次确实没有源码）。
  行段是必要的：整文件动辄 5k token，实测必然空正文。
* **现状自动注入**：每一份包都带 HEAD、最近提交、`git status --porcelain`、
  `AGENTS.md` 的状态块、验收台账末尾——现状不再靠提问的人转述（转述会掺进提问者的
  结论）。用 `--status-chars N` 控字数（默认 2000，0 = 不截断），截断会在包里留痕。
* **取证**：每次调用先写 `<out>/bundle.manifest.json`（HEAD/未提交清单/每个输入文件的
  sha256 与字数/`source_seen`/每份包的 system 与 user 指纹）与 `<out>/bundle.md`
  （**实际送进模型**的逐字内容），**再联网**。于是"它到底看到了什么"可对拍，
  失败的那次也留得下。这些都是 `tests/test_glm_consult.py` 的判据。
* 每个角色写两份：`<role>.json`（模型原始 JSON）与 `<role>.usage.json`
  （模型回显、`usage`、耗时、`finish_reason`、逐档尝试）——后者是"确实调了
  glm-5.3、用的哪一档"的证据。
* **失败也留证**：一次会诊没拿到正文（含上面那条"对端断连"）时写
   `<role>.failed.json`（`role` / `requested_model` / 逐档 `attempts`），
   然后才退出。断连是记一条 `finish_reason: "transport_error"` 的失败记录，
   **不是**抛 traceback 走人——否则"哪一档、跑了多久"全丢。
* `--dry-run` 只拼提示词、不联网（`tests/test_glm_consult.py` 用这条）。
* 角色表（`tools/glm_consult.py::ROLES`，互不重复）：
  `规格一致性` / `接口与契约` / `测试与验收` / `性能与鲁棒` / **`领域讲解`** /
  **`实现顾问`** / `红队反方` / `领域专家`。后两个加粗的是**解释型**角色（用户
  2026-10-04 裁决："会诊不是对抗性审查，而且需要他们解释"）：输出必须带
  `teaching`，每条 finding 必须带 `explanation` 与 `step_by_step`。

## 实测的运行包线（2026-10-04，本机，**照这个用**）

| prompt 规模 | 档位 | 结果 |
|---|---|---|
| 42 token | `max` | 14.5 s，正文 33 字符，`stop` ✓ |
| ~1.7k token（`CONTEXT.md`） | `max` | ~25 min，正文正常，`stop` ✓ |
| ~1.7k token（`CONTEXT.md`） | `high` | **363.6 s**，completion 16174、reasoning 14232，`stop` ✓ |
| ~1.7k token | `max` ＋ `max_tokens=8192` | 217 s，**正文为空**（reasoning 8147、`length`）✗ |
| ~10k token（4 份产物） | `high` | >30 min 后**对端断连** ✗ |
| ~15k token（README ＋ 40k 字尾） | `high` | ~25 min 后**对端断连** ✗ |
| ~2.6k token（Q5 出路一节全文） | `high` | **902.2 s** 后对端断连 ✗ |
| ~2.6k token（同一份） | `low` | **903.0 s** 后对端断连 ✗（⇒ 15 分钟是硬切，与档位无关） |
| **1179 token**（同一节的摘录） | `low` | **819.2 s**，正文正常，`stop` ✓（completion 27013、reasoning 23941） |
| **1641 token**（`axis.py` 摘录 ＋ 三个小问） | `low` | **404.2 s**，正文正常但撞 `max_tokens`（reasoning 32355、`length`）✓ |
| **2289 token**（同一份但现状摘要给到 1200 字） | `low` | **387.2 s**，**正文为空**（reasoning 32702、`length`）✗ |
| **≈1.6k token**（拆小后：现状压到 400 字 ＋ 两段各 18/30 行） | `low` | **383.6 s**，正文正常（`length`，关键判词已读到）✓ |

**同一小时的补充观测（很关键）**：上面那次 363.6 s 的成功之后，我在同一小时里
并发发起过 3 次大调用，随后的 4 次调用——10k / 15k / 2.4k（`high`）/ 2.4k（`low`）
——**分别被对端断连或 15 分钟读超时**。也就是说：**同一账号不要并发多个大调用**，
被掐过之后一段时间里连小 bundle 也会变慢。遇到这种情况：等几分钟、**只发一个**、
bundle 压到最小、先用 `--level low` 拿结果（要更深再单独补一次 `max`）。

⇒ **把 bundle 压到 ~2k token 以内、一次只问一件事**；大 bundle 先拆成几次，
或降到 `--level low`。`level=max` 只在"只有一个问题、愿意等半小时"时用。
空正文会自动降档（`max → high → low`）并逐档记进 usage——那是正常行为，不是失败。
上面那三行（2.6k 两连败 → 1179 token 成功）的**原始回包与失败记录**在
`docs/evidence/20261004-q5-glm-consult/`：`glm_redteam.json`（成功那次）、
`glm_redteam.usage.json`（1179/27013/819.2 s）、`attempt_transport_error.json`
（断连那次的 `finish_reason: transport_error`）。那份 README 还逐条写了
5 条 findings 的**判词**（证实/证伪），其中一条把 GLM 提的"第四条出路"算掉了。
（2026-10-04 补测：`stream: true` 也救不了——对端在思考阶段**一个字节都不发**，
~10k token 的 bundle 静默到 ~12 分钟才开始吐 delta，中途掐断时只留下半截
`reasoning_content`。所以正解还是**把 bundle 压小**，不是换传输方式。）

## 纪律（比工具本身重要）

1. **模型的话不是事实**：每条 finding 都要在仓库里找到 `文件:行号` 或最小复现；
   没被证实的单独列进"未证实/已证伪"。
2. **不许拿它当验收**：它可以在质量门、判据、口径上提意见，
   但"改判据/调阈值"仍然走仓库自己的流程（ADR ＋ 测试）。
3. **不许把它当成"多跑一次就多一份证据"**：同一份 bundle 重复问只会得到
   措辞不同的同一批结论；要的是**不同角色**与**不同产物**。
4. 报告里必须带 `usage`（本次实测：`high` 档 1.7k token ≈ 6 分钟、16k completion
   token）——不然无法判断这次"会诊"值不值。
5. **没看源码的会诊不算会诊**：只能问通用原理时才用 `--question-only`，并且要在
   报告里写明"这次没有源码，结论不可当判据"。工具已经把它做成结构性约束——
   不给源码就跑不起来，跑了就在 manifest 里留下 `source_seen`。
