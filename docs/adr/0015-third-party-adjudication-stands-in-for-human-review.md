# ADR-0015 第三方裁定（Kimi K3）代替用户做人工审核判断；第三方通道由 qwen 换成 kimi

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
