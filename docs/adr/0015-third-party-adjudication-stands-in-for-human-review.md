# ADR-0015 第三方裁定代替用户做人工审核判断（**通道已换代，见文末"更新"**）

> **2026-10-06 更新（读这一条再看下文）**：本 ADR 的**决定没有变**（第三方裁定代替人审、
> 记录如实写 `reviewed_by: "third-party"`、绝不冒充 `human`、门⑦ 要不要认它由
> `--reviewer-classes` 显式点名）——**变的是"第三方走哪条通道"**：
> qwen → **Kimi K3**（本 ADR 当时）→ **中转站 GPT-6A `gpt-6-astra`**（现行）。
> 下文凡是写"Kimi K3"的地方，**通道**应读作 **GPT-6A**；见文末「通道换代」一节。

状态：Accepted（2026-10-06）。触发：用户 2026-10-06 两条指示
「qwen 不方便，改成用 kimi k3 做第三方裁定和难题攻坚」与
「**这个裁定是指代替我做人工审核判断**」。

## 背景

门⑦（`tools/check_holdout.py::gate_human_review`）要 `needs_human` 条目有裁决记录。
本仓此前有三种裁决者，各有各的缺口：

| 裁决者类别 | 产出方 | 缺口 |
|---|---|---|
| `human` | `tools/holdout_review.py`（人去填 `EDGE_REVIEW_SAMPLE.md`） | 用户长期不在家 ⇒ **`human 0/212`**，这一格一直空着 |
| `llm-panel` | `tools/holdout_review_llm.py`（`deepseek-chat` ＋ `glm-5.3`，双模型） | 这两个模型**同时是 E1 的评委** ⇒ 拿它当"人工审核"有同族自证的味道 |
| `third-party` | 本 ADR 新增（`tools/holdout_review_third_party.py`，**Kimi K3**） | — |

## 决定

1. **第三方通道由 qwen 换成 Kimi K3。** qwen 账号 2026-10-06 掉出 good standing
   （每次调用 `HTTP 400 Access denied ... good standing`，见
   `docs/evidence/20261006-qwen-account/`），第三方裁定与难题攻坚因此不可用。
   Kimi（`api.moonshot.cn/v1`，型号 `kimi-k3`）既不是抽取器（deepseek）、
   也不是标注器（zhipu）、也与两位评委（deepseek-chat / glm-5.3）**不同族**。
2. **Kimi 的裁定承担"人审那一层"**，但记录**如实写 `reviewed_by: "third-party"`**，
   **绝不冒充 `human`**；每条记录带 `source{model, prompt_sha256, prompt_version,
   authorized_by}`，授权出处逐条可追。
3. 门⑦ **要不要把它算进"已裁"由显式的 `--reviewer-classes` 决定**——
   默认仍是协议原样 `("human",)`；验收链要显式点名 `third-party` 才计数。
   报告里 `reviewed_by_class` 永远把"谁裁的"分开写。

## 判据没有被放宽

* 门①–⑩ 的阈值、E1 的 4.0、分母、"接受哪些类别由 `--reviewer-classes` 决定"——
  一个字没动（`tests/plan_v4_instruments.sha256.json` 第十二次重新冻结，理由写在该文件）。
* `third-party` 记录**必须自带 `source.model` 与 `source.prompt_sha256`**，
  缺一就不算一条裁决记录（`review_class()` 会具名拒收）——与 `llm-panel`
  那条"必须带双模型 id ＋ 面板提示指纹"是同一套可佐证性纪律。
* **判据文本一字不改**：`tools/holdout_review_third_party.py` 直接复用
  `holdout_review_llm.SYSTEM`（`review/v2`）与 `entry_prompt()`／`_judge()`，
  所以它与 llm-panel 的判决**逐字可比**，对拍表只列分歧。

## 代价与风险（如实记）

* **它仍然不是人。** 用户授权它"代替我做人工审核判断"，这句话在法律/流程意义上
  是**用户对自己那部分裁量权的委派**，不是"机器冒充人"。任何报告都不得把它写成
  `human`，也不得把 `third-party ≥ 120` 读成"人审通过"。
* **同族性只剩一半保证**：Kimi 与两位评委不同族，所以"评委偏好自己人"这条路被堵住；
  但它与评委**同属大模型**，系统性的共同盲区（例如对"可达性"判据的共同误读）**未验证**。
* 一次性判词没有重复跑 ⇒ 它自身的**稳定性未测**（Kimi K3 只接受 `temperature=1`，
  逐次调用本就不保证逐字节复现）。

## 落地物

* `tools/kb_fetch/llm.py::KimiClient`（＋ `make_client("kimi"/"moonshot")`），
  守门 `tests/test_llm_kimi.py`。
* `tools/holdout_review_third_party.py`，守门 `tests/test_holdout_review_third_party.py`。
* `tools/check_holdout.py::review_class()` 认 `third-party`（第十二次重新冻结）。
* `~/.codex/hooks/model-routing.md`：第三方裁定／难题攻坚改走 Kimi K3
  （想法生成／质量审核仍走 GLM-5.3）。

---

## 通道换代（2026-10-06，追加；**决定未变**）

上面那条"走 Kimi K3"**已经过时**，两次换道都发生在同一天：

1. **Kimi 被额度挂起**：`docs/evidence/20261006-kimi-quota/` 记着
   `429 exceeded_current_quota_error`；同批把"发货代重排 85% 降级"的具名根因也定到它身上。
2. **改用中转站 GPT-6A**：用户 2026-10-06 原话"**难题攻关和会诊 gpt6A 吧**"＋
   "**提出方案类用 gpt6A，执行交给 DeepSeek**"；落地型号 **`gpt-6-astra`**
   （用户确认"就是这个了"），**`reasoning_effort=max`**，走 `linkai.pics`（Cloudflare 后面，
   必须浏览器 UA ＋ 流式，否则 524）。

**由此定下的现行口径**（与 `~/.codex/hooks/model-routing.md` 一致）：

| 工作类型 | 现行通道 |
|---|---|
| 人工裁决／写执行计划／难题攻关／会诊／提出方案 | **中转站 GPT-6A（`gpt-6-astra`，思考拉满）** |
| 改代码／跑测试／构建／导出／提交 | 主线 DeepSeek |
| 对拍与回退 | GLM-5.3（`--partner glm`）／Kimi（额度问题，仍不可用） |

**并且（用户 2026-10-06 原话"**我说过，GPT6A 代替我做决定**"）**：
凡是"**要不要动**"这一类——动判据／动测量协议／换 oracle 夹具／红线怎么处置／要不要另立协议版本——
**由 GPT-6A 裁定**，主线按其结论执行并留证；证据与台账里旧的"须用户拍板／须用户批准"
**视为过时口径**。

**这一节只改"通道与授权"的事实陈述**：本 ADR 的三条决定（不冒充 `human`、记录必须自带
`source{model, prompt_sha256, authorized_by}`、门⑦ 认哪些类别由 `--reviewer-classes` 显式点名）
**一个字没动**；门①–⑩ 的阈值、E1 的 4.0 与分母也一个字没动。

**落地物（现行）**：`tools/relay_consult.py::consult`（单次尝试已有"无数据上限"，
见 `docs/evidence/20261006-gpt6a-silent-hang/`）；第三方裁定的记录格式与守门仍用
`tools/holdout_review_third_party.py` 与 `tests/test_holdout_review_third_party.py`，
只是 `--provider relay --model gpt-6-astra`。
