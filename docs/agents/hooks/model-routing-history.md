## 模型分工契约（Codex hooks 注入，效力等同 AGENTS.md）

### 1. 路由总则

| 工作类型 | 交给谁 | 交付物 |
| --- | --- | --- |
| **想法生成**（方案、设计、取舍、备选路线、缺口清单） | **子 agent 联合会诊**：DeepSeek × **GLM-5.3** 各出一份，再逐条对拍（用户 2026-10-06 当天先说"提出方案类用 gpt6A"、**当天晚些时候改判**为 "不用 gpt6A 了，改用 glm5.3 吧，不然太耗时间了"——以改判为准） | 只出"想什么/为什么"，不落代码 |
| **质量审核**（对抗审查、缺口复核、独立验算、验收判词） | **子 agent 联合会诊**（同上，四栏记账） | 每条 finding 必须带 `文件:行号` / 命令 / 输出 |
| **难题攻关**（卡住不动、反复失败的缺陷、架构死结、"给我一个方案"） | **子 agent 联合会诊**，**方案以 GLM-5.3 侧为主**（用户 2026-10-06 当天先说"难题攻关和会诊 gpt6A 吧"、**当天晚些时候改判**为"不用 gpt6A 了，改用 glm5.3 吧"——以改判为准） | 方案 + 依据 + 可执行步骤；**执行仍回主线 DeepSeek** |
| **人工裁决**（用户/主线之外的独立判词：验收异议、门⑦ 人审那一层、与评委不同族的复核）——**它的裁决代替用户决定** | **GLM-5.3**（`--partner glm`；写计划用 `plan_writer --provider glm`，已是默认）。用户 2026-10-06："gpt6A **只能用于人工裁决和执行计划书写**"。Kimi K3 那条**降为回退** | 判词 + 理由 + 可证伪的下一步；`reviewed_by` 如实写 `third-party` |
| **写执行计划**（起草 + 默认 5 轮自我精炼） | **GLM-5.3**（同上；用户 2026-10-06 改判后："中转站有可以使用 gpt6A，我希望用于写执行计划"）。GLM-5.3 那条保留作对拍／回退 | 计划五节 ＋ 每轮 usage 留证（`plan.round{r}.usage.json`） |
| **执行任务**（改代码、跑测试、构建、导出、提交） | **主线 DeepSeek** | 真实产物 + 测试结果 |

### 1b. **通道改判（2026-10-06，用户原话）**

> 「**不用 gpt6A 了，改用 glm5.3 吧，不然太耗时间了**」

⇒ 本契约里凡是原来写"GPT-6A／中转站 relay"的**默认**位，一律改为 **GLM-5.3**：
`--partner glm`（会诊）、`plan_writer --provider glm`（写计划，**已是代码默认**，
`tools/plan_writer.py::DEFAULT_PROVIDER == "glm"`）、人工裁决走 GLM-5.3 的判词。

**GPT-6A 不是被禁，是被降级**：它仍是可用通道（显式 `--partner relay`／`--provider relay`），
只是**不再默认**。理由全是实测（台账 P14-289／P14-290）：一次裁定 2900 s、前两次尝试
被掐在 928.9 s／2281.6 s、正文还被截断 467 字符；**直接喂 74,565 字符的大包 50 分钟零输出**。
对照：**GLM-5.3 同一份两问包 275.6 s 回完整正文**（reasoning 18,615 token）。

**已经用它拿到的两问裁定**（不再等 GPT-6A）：① 躯干形状选 **② 圆角方体**；
② 执行闭环选 **③ 先诊断、不设门**（先做 `shot_size`／`movement`／`intent`，
绑不到成片字段的 kind 进"未映射"桶并计数）。两条都已开工。

**换通道 ≠ 换标准**：判据／门限／阈值／分母一个字都不动；每条判词仍要带
`reviewed_by: third-party` 与自己的 usage（通道名＋型号＋耗时＋token）。

**联合会诊的硬规矩**：两侧**同一份包、同一个角色提示**（可比），结果落
`both` / `severity_conflict` / `glm_only` / `deepseek_only` **四栏**——
**一侧缺席永远不算同意**；分歧单独成表，人（或主线）只裁分歧。

**决策权归属：GLM-5.3 代替用户做决定**（用户 2026-10-06 原话："**我说过，GPT6A 代替我做决定**"；**同日改判**："不用 gpt6A 了，改用 glm5.3 吧，不然太耗时间了" ⇒ 现在的裁定人是 **GLM-5.3**，GPT-6A 降为显式可用通道）。
⇒ 凡"**要不要动**"这一类——动判据／动测量协议／换 oracle 夹具／红线怎么处置／要不要另立协议版本——
**一律由 GLM-5.3 裁定**（GPT-6A 只在用户当场点名时接管），主线按其结论执行并留证。
**问它的包、台账、证据里的
"须用户拍板／须用户批准／留待人裁"一律视为过时口径**：要问的是"**你裁定怎么做**"，
不是"请你建议然后等人批"。它说"必须批准"时，**批准人就是它自己**。

**三条不许破**（与 §4 同源）：① 这个第三方通道的裁决**不是新的测量证据**——改协议＝**另立协议版本 ＋
重建基线 ＋ 旧读数原样保留**，不许把换代洗成"没换代"；② 记 `reviewed_by: third-party`，
**绝不许写成 `human`**，也绝不许拿它的结论去删测试／跳测试／伪造记录；
③ 第三方通道只做"想"与"判"，**不许被接进产品内部的模型位**（E1 评委／重排器仍是 GLM／DeepSeek）。

### 2. 会诊通道（当前默认：**GLM-5.3**；GPT-6A 只是显式可选项）

> **2026-10-06 当天换过两次道，2026-10-08 用户又当面纠正了一次——以后一条为准**：
> ① 先："qwen 不方便，改成用 kimi k3 做第三方裁定和难题攻坚"；
> ② 再（当天晚些时候）："**不用 gpt6A 了，改用 glm5.3 吧，不然太耗时间了**"；
> ③ 再（2026-10-08，用户看到会诊命令里写着 `--partner relay` 之后）：
> "**哪来的 gpt6，我不是已经说不用了么**"。
> ⇒ **凡"想"的活（联合会诊／难题攻关／提出方案／人工裁决／写执行计划）默认走 GLM-5.3**；
> **凡"做"的活（改代码／跑测试／构建／导出／提交）走主线 DeepSeek**；
> **GPT-6A（中转站 relay）只在用户当场点名时用**——它不是"默认的回退通道"，是**显式可选项**。
> Kimi K3 另因**余额挂起**（§2b 有原始回包）不可用。

本机 Codex 的模型目录（`~/.codex/models.json`）里只有 `deepseek-flash` / `deepseek-v4-pro`，
**GLM-5.3 不是可被 spawn 的 agent 模型**。因此"用 GLM-5.3"= **判词经 GLM-5.3 通道产出**：

* **联合会诊（首选）**：`python tools/panel_consult.py --roles <角色…> --question <q.md>
  --source <文件:起-止> --context <产物> --out <目录>` —— DeepSeek 与**第二侧**
  各答一遍再对拍；**默认 `--partner glm --level low`（GLM-5.3）**；
  **只有用户当场点名**才写 `--partner relay`（中转站 GPT-6A）；
  产出 `<role>.{glm,deepseek}.json` 与 `panel.{json,md}`
  （文件名的 `glm` 是**历史槽位名**，实际通道看 `panel.json` 的 `partner{channel,model}`），
  判词记 `reviewed_by: "llm-panel"`。主线程本身就是 DeepSeek 时，用
  `--main-answer <我的判词.json>` 当 DeepSeek 侧入口（不必再走 API）。
* 单侧会诊 / 讲解：`python tools/glm_consult.py --roles <角色…> --question <q.md>
  --source <文件:起-止> --context <产物> --out <目录>`
  —— **不给源码就拒绝调用**；先写 `bundle.manifest.json` / `bundle.md` 再联网；
  每个角色同时落 `<role>.usage.json`（模型、档位、耗时、token）。
* 直接调用：`tools/kb_fetch/llm.py::GLMClient`，`model_id` **必须**是 `glm-5.3`。
* **型号纪律**：GLM 一律用 `glm-5.3`。`glm-4.x` / `embedding-*` 报 `1113` 只表示
  **该型号没有资源包**（智谱按模型分别计费），**不代表账户没钱**；判额度必须逐模型探。
* **包线纪律**：`glm-5.3` 是"始终思考"模型，单次调用是分钟级（实测 1.7k 输入、`high` 档 363.6 s），
  bundle 压到 ~2k token、一次只问一件事；批量超过十来次要分批或后台跑。

### 2b. "Kimi K3" 的落地通道（**已降为回退；当前不可用**）

> **2026-10-06 实测：账号被挂起**——`HTTP 429`，原话
> `Your account org-… <ak-…> is suspended due to insufficient balance, please recharge
> your account or check your plan and billing details`（`exceeded_current_quota_error`）。
> 所以**任何活都别默认走它**；余额恢复后才可作为对拍/回退。
> 证据：`docs/evidence/20261006-kimi-quota/`（含发货代重排 85% 降级的具名根因）。

* **客户端**：`tools/kb_fetch/llm.py::KimiClient`（`family="kimi"`，`make_client("kimi")`／
  `make_client("moonshot")`）。端点 `KIMI_BASE_URL`（默认 `https://api.moonshot.cn/v1`）、
  型号 `KIMI_MODEL`（默认 **`kimi-k3`**）、超时 `KIMI_TIMEOUT`（默认 900 s）；
  密钥只从 **`KIMI_API_KEY`** 读，**绝不写进仓库**。
* **一条硬约束（别踩）**：`kimi-k3` **只接受 `temperature=1`**——传 0 会
  `HTTP 400 invalid temperature: only 1 is allowed`。客户端**显式**盖成 1 并把这个决定
  写进 `decode_tag`；**不许**写成"传 0 被拒再重试"，也不许因此判"模型不可用"。
* **调用形状**：OpenAI 兼容 `/chat/completions`；响应把 **思考**放 `reasoning_content`、
  **正文**放 `content`，所以 `max_tokens` 要留够（思考会吃预算）；**正文为空 = 具名失败**，
  不许当"模型没意见"。实测一次小调用 5.3 s、`completion_tokens` 158（其中思考 124）。
* **能用它的既有缝**：`tools/knowledge/e1_panel.py --cases-rerank llm
  --rerank-llm-provider kimi --rerank-llm-model kimi-k3 --rerank-llm-prompt order|select|score`。
* **纪律**：Kimi 的判词同样**不是验收**——不改判据 / 门限 / 阈值，也不用"再跑一次"充当新证据；
  与 GLM 侧一样，判词要带 `usage`（模型、耗时、token）。

### 2c. 写执行计划 / 人工裁决的落地通道（**默认 GLM-5.3**；GPT-6A 点名才用）

> **用途边界（三轮指示合并，以 2026-10-08 用户当场纠正的**那一条**为准）**：
> ① 先划的是"GPT-6A 只能用于人工裁决和执行计划书写"；② 随后用户加过一句"难题攻关和会诊 gpt6A 吧"；
> ③ **2026-10-08 用户看到会诊命令里的 `--partner relay` 之后明确纠正："哪来的 gpt6，我不是已经说不用了么"**。
> ⇒ 现在的口径是：**凡"想"的活默认走 GLM-5.3**（人工裁决／执行计划书写／难题攻关／联合会诊／提出方案），
> **GPT-6A 只在用户当场点名时**才启用（`--partner relay`／`--provider relay`）；
> **凡"做"的活走主线 DeepSeek**（改代码、跑测试、构建、导出、提交）。
> **仍然不许**把它接到**产品内部的模型位**上——尤其**不要**拿它当 E1 的评委或重排器
> （那两处按用户更早的规则只许 glm／DeepSeek）。

* **客户端**：`tools/kb_fetch/llm.py::RelayClient`（`family="relay"`，`make_client("linkai")`
  ／`make_client("relay")`）；起草入口 `tools/plan_writer.py --provider relay`
  （模型函数 `tools/relay_consult.py::consult`）。端点 `LINKAI_BASE_URL`
  （默认 `https://linkai.pics/v1`）、型号 `LINKAI_MODEL`（默认 **`gpt-6-astra`**）、
  超时 `LINKAI_TIMEOUT`（默认 900 s）；密钥只从 **`LINKAI_API_KEY`** 读，**绝不写进仓库**。
* **一条硬约束（别踩）**：这个域名在 **Cloudflare** 后面，裸 urllib 的默认 UA 会被
  `HTTP 403 error code: 1010`（"banned your access based on your browser's signature"）挡掉。
  `RelayClient` 已强制发浏览器 UA；**不要**绕过它自己写 HTTP。
* **型号＝`gpt-6-astra`（用户 2026-10-06 亲口确认："就是这个了"）**。经过：用户说的
  "gpt6A"在 `/v1/models` 里没有同名字面量（实测列出 `codex-auto-review`／`gpt-5.5`／
  `gpt-5.6-{luna,sol,terra}`／`gpt-6-astra`／`gpt-6-luna`／`gpt-6-sol`／`gpt-6.1-sol`），
  主线按"唯一以 A 起名的 `gpt-6*`"取了它，用户确认。⇒ 默认就是它；
  **要换仍可设 `LINKAI_MODEL`**，不用改代码。
* **没有档位**：中转站没有 GLM 那套 `max→high→low`；`--level` 在它上面只被记账、不被使用。
  所以"档位阶梯"那套取证在 relay 通道上**不适用**（`relay_consult` 会如实写 `levels_ignored`）。

* **⚠️ 实测包线（2026-10-06，`docs/evidence/20261006-channel-fallback/`）：它能出正文，但"大包直喂"不行。**
  ① 出正文的实例：RK-13 裁定**成功**，但正文在 467 字符处**被截断**（两个问题没答），
  总 `elapsed_s=2900.0`＝48 分钟，前两次尝试分别被掐在 **928.9 s**／**2281.6 s**；
  ② **直接喂 74,565 字符的包**：**50 分钟零输出**（25 s 采样读字节 0／CPU 0，进程卡在 socket 读上），
  且 `attempt_timeout=900` **这次没有按时掐断**（根因未查）。
  ⇒ **别把整份项目快照丢给它**；要它读全，走 `tools/relay_adaptive.py` 分块，
  或者把包压到"一件事 + 必要证据"。**大包不是"多给时间就行"**——这条实测推翻了那个假设。

* **通道级自动回退（已落库 `5f26314`＋`97824bb`）**：用户 2026-10-06
  "**如果现在还是用不了 gpt6A，就改用 glm5.3 吧**"。落地形状：
  `tools/panel_consult.py::relay_caller()` 在 relay 侧**三次重试全废**后**自动改走 GLM-5.3**
  （守 `max→high→low` 档位阶梯），并把 `fallback_from`（通道、型号、原始错误）写进判词 usage；
  **没配 `fallback_model` 时失败照旧上报**（"一侧缺席永远不算同意"）。
  ⇒ 以后开联合会诊**不需要**人工盯着换通道；通道抖一下不再把整次会诊打死。
  **换通道不是换标准**：判据/门限/口径一个字都不动。

* **GLM 侧同一时刻的实测（同一天、同一份包）**：`--level max` **一次 900.1 s 零字节超时**
  （`attempts` 里只有 max 一档），**同一份包同一组参数重跑 275.6 s 就成功**
  （`completion_tokens=21068`，其中 reasoning **18615**）。
  ⇒ **那是抖动、不是"`max` 档不可用"**；正确的处置是**重试／降档**。
  已被 `tools/glm_consult.py::why_not_step_down()` 固化：
  **传输类（超时、`RemoteDisconnected`、空正文）继续降档**（留 `stepped_down_to`），
  **只有额度类停手**（`429`／`1113`／余额／资源包／quota／rate limit／insufficient／suspended，
  留 `step_down_refused` 说明为什么没降）。旧实现把两者混为一谈，
  于是"逐档降级"这个设计**在最需要它的失败上没有生效**。
* **长生成不再受限（2026-10-06 实测并已修）**：`linkai.pics` 在 **Cloudflare** 后面，
  **524 是边缘等不到源站的默认超时（约 100 s）**——非流式时，31 KB 与 10 KB 的包都**三次全 524**
  （127/257/389 s，证据 `docs/evidence/20261006-gpt6a-envelope/`）。
  **解法是流式**：同一条问题改成 `stream:true` ⇒ **HTTP 200 ＋ `text/event-stream`、132.7 s 拿到完整正文**
  （证据 `docs/evidence/20261006-linkai-streaming/`）。`RelayClient` 的 `chat()`／`chat_json()`
  **已默认走流式**（挂了才退回非流式）。
  ⇒ 用户 2026-10-06 说的"**gpt6A 生成很慢，要给很多时间**"**已经满足**：给它多少时间都行。
  仍然**不许**为绕超时去调低 `reasoning_effort`（那是静默降级）。
* **思考强度拉到最大（用户 2026-10-06："并且使用 gpt6A 时思考强度拉到最大"）**：
  开关是 OpenAI 兼容的 **`reasoning_effort`**，默认 **`max`**（`LINKAI_REASONING_EFFORT` 可改）。
  实测（`work/_probe_linkai_thinking.py`，同一问题、同一 `max_tokens=2048`）：
  裸调用 reasoning **40** token → `high` **137** → **`max` 1034**（墙钟 11.1 s → 37.7 s）。
  **踩过的坑**：`thinking={"type":"enabled","level":"max"}`（45）与
  `extra_body.reasoning_effort`（35）**都被忽略**——写了等于没写，是**静默降级**。
  谁要再试新拼法，先用那个探针量 `reasoning_tokens` 再说话。
* **纪律**：写的计划**不是验收**——判据/门限/阈值一个字不许动；每轮 usage 必须留证。

### 3. 子 agent 的义务（想法 / 审核两种角色）

1. 开工先声明**唯一角色视角**（与并行其他 agent 不重复），只从该视角给结论。
2. **先全量审计**：相关文件、产物、文献一次读全再表态；不许按需搜索。
3. 判词**经联合会诊**产出并留证：两侧同一份包、同一个角色提示；`--source` 逐字带行号，
   两侧各自落 `usage`（模型、档位、耗时、token）；分歧写进 `panel.md` 的独立栏。
4. 只给可验证证据：`文件:行号`、命令、真实输出；拿不到就写"未验证"。
5. **GLM 的判词不是验收**：不改判据 / 门限 / 阈值，也不用"再跑一次"充当新证据。
6. 交付格式：角色 → 结论 → 证据 → 缺口与风险 → 可执行到文件与行的建议动作。
7. **遇到难题就开联合会诊**：先按维度和现象把问题拆开（自己查全、给出最小复现），
   再带着**源码与产物**跑
   `python tools/panel_consult.py --roles 领域讲解,实现顾问 --question <q.md>
   --source <文件:起-止> --context <产物> --out <目录>`；
  **以 GLM-5.3 侧为主**取出方案（`--partner glm --level low`，默认；GPT-6A 只在用户当场点名时用），
  与 DeepSeek 侧对拍（分歧必须点明），
   落成"可执行步骤 + 验收判据"后**交回主线执行**；两侧的方案都要在仓库里证实或证伪。

### 4. 主线的义务（执行）

* 写代码 / 跑测试 / 构建 / 导出 / 提交**只在 DeepSeek 上做**；GLM／GPT-6A（点名才用）／Kimi 通道
  只用来取判词与方案，**不用来执行**（用户 2026-10-06："执行交给 DeepSeek"）。
* 执行前应先拿到"想法 + 审核"两类的结论；执行后按仓库流程补对抗性测试并如实报告。
* 汇报时把两类证据分开写：**第三方通道（默认 GLM-5.3；GPT-6A 仅在用户点名时）的判词**（含 usage 与通道名）
  与 **DeepSeek 的执行结果**（含测试输出）。

### 4b. **修复阶梯**（用户 2026-10-06："同一个问题，第一次修复问题 DeepSeek 自己想办法修复，
### 如果修复不了，第二次尝试修复时使用 GLM-5.3 进行，第三次修复加入 GPT-6A。自动判断修复次数然后触发。"）

**怎么用**：在提问里带一个**稳定的问题键**——`repair-key: <slug>`（同一个问题每次都用**同一个**
slug）。hook 会**自动读改写 `~/.codex/hooks/.repair-ladder.json`** 并把当前级数注入上下文：

| 第几次 | 参与方 |
|---|---|
| **1** | **主线 DeepSeek 自己修**（最小复现 → 定位 → 改 → 跑测试）——**不许**一上来就开会诊 |
| **2** | ＋ **GLM-5.3** 会诊（`--partner glm --level low`，守它的 ~2k token 包线） |
| **≥3** | ＋ **GLM-5.3 会诊**（`--partner glm --level high`；中转站 GPT-6A **只在用户当场点名时**才用） |

**复位**：修好后写 `repair-key: <slug> done`，hook 会把这个键的计数清掉（实测：1→2→3 会依次
勾选 `[x]`，写 `done` 后状态文件回到空）。

**三条不许破**：① 换级**是换脑子，不是换标准**（判据/门限/阈值一个字不许动）；
② 每一级都要留证（命令＋真实输出＋两侧 usage）；③ 三级都修不动就**如实报阻塞**，不许降级绕过。

### 5. Codex 客户端侧的 GPT-6A 接入（2026-10-08）

§2／§2b／§2c 讲的是**仓库侧工具**怎么调中转站；这一节讲**Codex 客户端本身**
（`codex` CLI 与桌面 App 跑在哪个模型上）怎么用上它。
用户 2026-10-08："帮我接入 gpt6A 到 codex 里，中转站那个"。

* **provider**：`~/.codex/config.toml` 的 `[model_providers.linkai]`
  （`base_url = "https://linkai.pics/v1"`、`wire_api = "responses"`、密钥走
  `experimental_bearer_token`）。0.154.0 **已删** `wire_api = "chat"`，所以只能走
  `/responses`——中转站这个口实测 200 `text/event-stream`。
  **不用 `env_key`**：桌面 App 的进程环境是启动时快照的，`setx` 之后不重启读不到，
  会白白多一个 `Missing environment variable` 失败面。
* **型号目录**：`~/.codex/models.json` 里加了 `gpt-6-astra`
  （`display_name = "GPT-6A Astra (中转站)"`、`context_window = 900000`），
  否则桌面选择器里根本看不见它。
* **CLI 用法（首选，不动默认）**：`codex --profile gpt6a`／`codex exec --profile gpt6a`／
  `codex review --profile gpt6a`；profile 单独成文件 `~/.codex/gpt6a.config.toml`
  （0.154.0 **拒收** config.toml 里的 `[profiles.*]`，写了直接报错退出）。
  该 profile 里 `model_reasoning_effort = "ultra"`——契约要求"用 gpt6A 时思考强度拉满"。
  （2026-10-08 用户指正：Codex 档位表 `minimal < medium < xhigh < max < ultra`，
  最高档是 `ultra` 不是 `max`，已实测生效；此前写的 `"max"` 差一档。）
* **桌面 App 用法（有代价）**：桌面端**没有**"每个模型绑一个 provider"的机制
  （`app.asar` 里 `modelProvider` 只对硬编码 id `codex_vscode_copilot` 非空，
  其余一律 `null` ⇒ 回落到 config 的 `model_provider`），
  所以**只把选择器切到 GPT-6A 不够**：它会拿着 `bailian` 去请求，实测
  `Unsupported model: 'gpt-6-astra'`，重试 5 次全废。桌面端真要用就得**翻全局默认**：
  `powershell -NoProfile -ExecutionPolicy Bypass -File $env:USERPROFILE\.codex\use-gpt6a.ps1`
  → 重启 Codex；用完 `use-default-model.ps1` 翻回来（按 `config.toml.pre-gpt6a`
  整文件快照还原，实测还原后与切换前**逐字节相同**）。
  **agent 不许自己去重启桌面 App**——它就跑在那个进程里。
* **纪律（不变）**：GPT-6A **不是默认**，默认仍是 config.toml 顶部那三行；
  用完必须还原；**不许**为了绕慢／绕超时而调低 `model_reasoning_effort`（那是静默降级）。
* **中转站模板里被这一版拒收的键**（实测 `codex exec --strict-config`）：
  `disable_response_storage`／`network_access`／`windows_wsl_setup_acknowledged`
  ⇒ **别照抄用户贴的模板**；同一份模板里的 `features.goals`／`review_model`／
  `model_providers.*.requires_openai_auth`／`model_reasoning_effort = "xhigh"` 这几个它认。
* 逐项验收与备份清单：`~/.codex/GPT6A_LINKAI_20261008.md`。
