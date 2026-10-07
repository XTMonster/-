# C1 判官替换与"思考拉满"的实测（用户 2026-10-07 指令）

**触发（用户原话）**：「接入这个 qwen3.8max0902，**代替 glm**」＋「**新模型思考强度拉到最大**」。
**性质**：这是**用户明示授权**的通道/判官替换，不是自行降级。本文件把"换成了什么、
拉满有没有真的生效"用**实测**记下来。

---

## 1. 接的是哪条通道 / 哪个模型

```
base   https://llm.goaichat.top/v1     （备用：https://model.kimitk.top/v1）
model  qwen3.8-max-0902                （`/v1/models` 实测存在；两个 base 都可列出 18 个模型）
key    只从环境变量 GLM_API_KEY 读，绝不入库
```

**接入方式＝纯环境变量，零代码改动**（工具本来就是 env-driven）：

```powershell
$env:GLM_API_KEY          = "<key>"
$env:GLM_BASE_URL         = "https://llm.goaichat.top/v1"
$env:GLM_MODEL            = "qwen3.8-max-0902"
$env:GLM_REASONING_EFFORT = "max"        # ← 见 §2
$env:BD_CONSULT_LEVEL     = "max"        # work/_run_grounding_batches.py 的思考档位
```

**UA 实测**：默认 urllib UA 与浏览器 UA **都能通**（不像 `linkai.pics` 那样会被 1010 挡）。

## 2. "思考拉满"到底该调哪个键（**先量再说话**）

`work/_probe_qwen_thinking.py`（同一通道、同一问题、每档 **3 次采样**）：

| 设置 | `reasoning_tokens`（3 次） | 判读 |
|---|---|---|
| `thinking.level=low` | 23 / 61 / 38 | 基线噪声带 |
| `thinking.level=high` | 51 / 52 / 187 | 与 low 无本质区别 |
| `thinking.level=max` | 42 / 53 / 41 | **并不比 high 想得多** |
| `reasoning_effort=high` | 59 / 48 / 58 | —— |
| **`reasoning_effort=max`** | **305 / 46 / 229** | **真正把思考拉满的是这一项** |

⇒ 与 `model-routing.md` 记的 relay 行为一致（`thinking={"type":…,"level":…}` 会被忽略、
`reasoning_effort` 才生效）。所以"拉到最大"＝**加 `reasoning_effort: max`**。

**为此给 `tools/glm_consult.py` 开了一条 opt-in 缝**：`GLM_REASONING_EFFORT` 非空时
把 `reasoning_effort` 原样带进 payload，并写进 usage（读数为证）；**不设时 payload 逐字不变**，
智谱 GLM 路径不受影响。守门：`tests/test_glm_consult.py::test_reasoning_effort_is_opt_in_and_off_by_default`
（默认**不许**出现这个键；设了就必须出现且进 usage）。

## 3. 换判官后的实际读数（`reasoning_effort=max` ＋ `thinking.max`）

| 批 | 模型 | 档位 | effort | 耗时 | finish | reasoning_tokens |
|---|---|---|---|---|---|---|
| batch1 | qwen3.8-max-0902 | max | **max** | 67.4 s | stop | **5059** |
| batch2 | qwen3.8-max-0902 | max | **max** | 184.8 s | stop | **12059** |
| … | | | | | | （逐批写进 `batch<n>/三分类.usage.json`） |

对照：早前同一模型只用 `thinking=high` 时 reasoning 是**几十**个 token
（batch1 13.4 s）；现在**四到五位数量级**——"拉满"是**实测到**的，不是照抄一个参数名。

## 4. 口径与留档（**不许混判**）

* 早先的 2 批是 **GLM-5.3** 判的，已被**移动**（不是删除）到
  `_superseded/glm-5.3-judge-<stamp>/batch{1,12}/`；
* 第一次用新模型但只开了 `thinking=high` 的那批，移动到
  `_superseded/qwen-high-<stamp>/batch1..8/`；
* **正式样本**＝**全部 12 批、同一判官（qwen3.8-max-0902 ＋ `reasoning_effort=max`）**，
  这样分母里不会混着两把尺。

> 注：`work/_run_grounding_batches.py` 里的档位从硬编码 `high` 改成读
> `BD_CONSULT_LEVEL`（默认仍是 `high`，**不许**为省时间调低——那是静默降级）。
