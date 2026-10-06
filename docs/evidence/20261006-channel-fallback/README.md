# 通道可用性实测：GPT-6A 能出正文但慢且脆；GLM-5.3 同一份包 5 分钟就回来了

日期 2026-10-06 21:27–22:20。起因是用户 2026-10-06 的两句话：
「**直接喂大包**」（拒绝自适应分块）与「**如果现在还是用不了 gpt6A，就改用 glm5.3 吧**」。
本节只回答一件事：**这两个通道各自到了哪一步**。判据/门限/阈值**一个字没动**。

## 一、四条实测（都不是推断）

| # | 通道 | 包 | 结果 | 原件 |
|---|---|---|---|---|
| ① | 中转站 `gpt-6-astra`（`reasoning_effort=max`） | RK-13 裁定包 | **成功**：正文 467 字符，但**在"研究重排器的 0.44"处被截断**（第 2/3 问没答）；总 `elapsed_s=2900.0`（48 分钟），`attempts` 显示前两次被掐（**928.9 s** SSL 握手超时、**2281.6 s** HTTP 524） | `work/_gpt6a_adjudicate.log`、`docs/evidence/20261006-rk13-ruling/README.md` |
| ② | 中转站 `gpt-6-astra` | **直接大包** 74,565 字符（`work/_q_big_feed.md`） | **50 分钟零输出**：最后一次尝试的 TCP 连接自 21:59:24 起，25 s 采样 **读字节 0 / CPU 0**（进程仍在，即"卡在 socket 读上"）；产物文件始终不存在 | `work/_big_feed.log`（0 字节）、pid 56348 |
| ③ | 智谱 `glm-5.3`（`--level max`） | 两问包 942 字符（＋现状摘要 2,068 字符） | **失败**：`{"level":"max","error":"TimeoutError: The read operation timed out","elapsed_s":900.1,"finish_reason":"transport_error"}`，**`attempts` 里只有 max 一档**（没去试 high） | `work/_glm53_decide23/规格一致性.failed.json` |
| ④ | 智谱 `glm-5.3`（`--level max`） | **同一份包、同一组参数**，重跑 | **成功**：`elapsed_s=275.6`、`completion_tokens=21068`（其中 **reasoning 18615**）、`finish_reason=stop`，正文完整（含 `summary`／`teaching`／2 条 findings／`not_checked` 8 项） | `glm53.answer.json`、`glm53.usage.json`（本目录） |

**要读准的两件事**：

1. **③ 与 ④ 是同一份包、同一组参数、同一天** ⇒ 900.1 s 零字节那条**不是"`max` 档不可用"的确定性性质，
   而是通道抖动**。所以对它正确的处置是**重试/降档**，不是"换模型"。
2. **"直接喂大包"这条路的实测是负面的**：74,565 字符的包给出去 50 分钟，
   **一个字节都没回来**，而进程既不烧 CPU 也不收数据。
   注意这**不是** `attempt_timeout=900` 按时生效——那条上限**这次没有在 900 s 处掐断**
   （连接从 21:59:24 一直挂到采样时刻），与 `docs/evidence/20261006-gpt6a-silent-hang/` 设计的行为不一致，
   **根因未查**（见"未验证"）。

## 二、这次实测倒逼出的两处修复（判据没动）

落库提交 **`5f26314`**（`fix(P14-288)`）。

### 2.1 `tools/glm_consult.py`：传输失败**要**降档，不再和 429 混为一谈

旧代码 `if "429" in error or error: break` 把"有错误"一律当成"换档无益"。
于是 ③ 那种**零字节超时**会把整次调用打死，**根本不去试 `high`**——
而"降一档、想得少一点、更快"恰恰就是这种失败的解药（同一账号 `high` 档在 1.7k 包上实测 363.6 s 出正文）。

新判据收在 `why_not_step_down()` 一处：**同模型换档换不来额度 ⇒ 只有额度类才停手**。

* 停手（并留 `step_down_refused` 说明为什么）：`429`／`1113`／`余额`／`资源包`／`quota`／`rate limit`／`insufficient`／`suspended`
* 继续降级（并留 `stepped_down_to`）：超时、`RemoteDisconnected`、空正文

### 2.2 `tools/panel_consult.py`：relay（GPT-6A）三次全废 → **自动改走 GLM-5.3**

`relay_caller()` 现在在 relay 侧重试耗尽后自动改走 GLM-5.3（守 `max→high→low` 阶梯），
并把 **`fallback_from`（通道、型号、原始错误）** 写进判词 usage。两条纪律照旧：

* `except (Exception, SystemExit)` —— 本仓通道用 `SystemExit` 报"缺 key／没正文"，只接 `Exception` 会让回退形同虚设；
* **没给回退型号时不许吞失败**：`fallback_model` 为空就原样抛出（"一侧缺席永远不算同意"）。

## 三、验证

```
python -m pytest -o addopts="" -q tests/test_glm_consult.py tests/test_panel_consult.py tests/test_plan_writer.py
52 passed in 20.32s
```

新增 5 条守门（**只增不改**；既有的 `test_a_transport_error_is_not_retried_through_the_ladder`
仍绿——它喂的是 `429`，属于"停手"那一类）：

| 守门 | 钉的是什么 |
|---|---|
| `test_a_zero_byte_timeout_does_step_down_the_ladder` | `transport_error` 必须降到 `high`，并在 `attempts[0]` 留 `stepped_down_to` |
| `test_the_step_down_rule_separates_quota_from_transport` | 分类器本身：429/1113/余额 → 停手；超时/断连/空串 → 降级 |
| `test_a_quota_failure_says_why_it_did_not_step_down` | 停手也要留因（`step_down_refused`），且**不写** `stepped_down_to` |
| `test_the_relay_channel_hands_over_to_glm_when_gpt6a_dies` | relay 全废 → GLM-5.3 接手，`fallback_from` 逐字留证 |
| `test_without_a_fallback_model_a_relay_failure_still_surfaces` | 没配回退通道时**失败照旧上报**，不许静默 |

## 四、顺带落地的一件事：那两问**有 GLM-5.3 的裁定了**

④ 的成功不只是"通道可用"的证据——它同时给出了 `work/_q_gpt6a_decide23.md` 那两个问题的**完整裁定**：

* **问题一（躯干形状）→ ② 圆角方体**。理由：`§7` 本身就把它列为"唯一一项待拍板"（规范两可），
  `max_delta=0.0` 只证明**同外接盒**、不证明形状等价 ⇒ 尺寸常量**不需要动**，
  要动的只有构造调用本身 ＋ 一个**新增的圆角半径常量**；风险点是"身体构造**之外**若还有代码直接引用圆柱半径"会静默错位。
* **问题二（知识→成片的执行闭环）→ ③ 先诊断、不设门**。理由：`R001–R019` **没有一条**要求校验超边约束的执行，
  现在设门＝用实现反向发明规范；且 66 条全来自 `axis_side` 这一条**绑不到成片字段**的边
  ⇒ 第一步只做 `shot_size` ＋ `movement` 两个 kind，**未映射的 kind 默认"不适用"并单独计数**，数字稳定后再谈设门。

**口径**：GPT-6A 侧对**这两问**至今**没有**给出正文（pid 40360 从 21:46:54 起、30 分钟以上零输出）。
按用户 2026-10-06 的指示（"如果现在还是用不了 gpt6A，就改用 glm5.3"），**这一格归 GLM-5.3**。
本节只记录裁定与理由，**尚未据此改代码**（换形要连带查"圆柱半径的外部引用"，落在下一批）。

## 五、未验证 / 边界（如实挂）

* **`attempt_timeout` 这次为什么没在 900 s 处掐断**（② 里连接挂了一个多小时）**根因未查**——
  与 `docs/evidence/20261006-gpt6a-silent-hang/` 的实测行为不一致；
* `HTTP 524` 那次为什么耗时 **2281.6 s**（而非 Cloudflare 文档里的约 100 s）**未查**（沿用 `…-rk13-ruling` 的挂账）；
* **大包直喂（②）至今没有终局**：进程仍在，既没成功也没报错；
  本节只报"50 分钟零输出"这个事实，不代表"永远不行"；
* **GLM 侧只重跑了一次**（n=1 vs n=1）：③ 与 ④ 的差别**有实测支持**，但**抖动频率没量**
  ——"多久失败一次"需要多次重复才能说（成本是每次 5–15 分钟）；
* 本节的 ② 由主线观察所得；③④ 由主线发起、主线读表。**没有一个数字来自未跑的推断**。
