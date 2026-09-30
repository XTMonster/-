# 标注通道实测台账（v1.5，2026-09-30）

这一页只记**实测到的事实**与由此产生的配置决定，供 RK-13 的数据来源审计用。
所有数字都出自本机脚本（`work/` 下的 raw 探针），不是推测。

## 1. 换族关系（协议 §5.1 第 1 条）

| 通道 | family | 与抽取器（deepseek）的关系 | independence |
|---|---|---|---|
| 本地 `qwen3-vl:30b` | qwen | 异族 | strong |
| 智谱 `glm-4.7 / 4.6 / 4.5` | zhipu | 异族 | strong |
| `deepseek-chat`（**未用于标注**） | deepseek | 同族 | weak（会触发 ≥30% 人审且 RK-13 降级） |

`tools/check_holdout.py` 的门⑧（`gate_8_independence`）会对产出文件逐条核对
`annotator.family`，实测当前产出 **pass**。

## 2. GLM 的思考档：`max` 在本任务上**跑不完**（这是默认档不取 `max` 的原因）

同一份标注 prompt、同一批 3 张卡、`max_tokens=32768`：

| 模型 / 档位 | 单次耗时 | completion_tokens | reasoning_tokens | finish_reason | 正文 |
|---|---|---|---|---|---|
| `glm-5.3-flash` + `{"type":"enabled","level":"max"}` | **742 s** | 32768（烧光） | **32306** | `length` | **0 字符** |
| `glm-4.6` + `{"type":"enabled"}` | 280 s | 10791 | 9483 | **stop** | **3607 字符**（合法 JSON） |
| `glm-4.7` + `{"type":"enabled"}`（12 卡/批） | 291 s | 11627 | 6912 | **stop** | 13916 字符 |

结论：`level=max` 的思考**没有上界**，会把整个预算吃在 `reasoning_content` 上、
正文一个字都不吐 ⇒ 每次调用都判失败。默认档因此取"**能跑完的最高档**"
（`{"type":"enabled"}`），`max|high|low|disabled` 仍可显式指定。

配套修复（都在 `tools/kb_fetch/llm.py`，有单测）：

- 读超时 300 s → **1800 s**（思考档单次必然 > 5 分钟，300 s 会把每次调用打死）；
- `glm-5.3` 那类"始终思考、不允许关闭"的模型对 `disabled` 回 **400 code=1210**，
  客户端自动退回 `max` 档重试；
- `429`（`1302` 速率 / `1305` 模型忙）一律长退避：`20 s × attempt`。

## 3. 账号侧的两道硬墙

1. **并发上限 ≈ 3 个思考档请求/模型**：实开 8 个并行分片时，只有 3 个分片能持续出货，
   另 5 个一直在 `429`。**跨模型可以绕过**：把其余分片换到 `glm-4.5` 后立刻开始产出
   （实测 `glm-4.6` 3 片 ＋ `glm-4.5` 3 片同时跑，各自都在出货）。
2. **付费档需要余额**：`glm-4.6 / 4.5 / 4-plus` 在余额不足时回 `429 code=1113`；
   `glm-4-flash` 免费可用但**实测不可用**（6 张卡只给 4 条、必填槽位缺失、
   通过率 **0**）。

## 4. 本地通道：磁盘事故与现状

- `ollama pull qwen2.5:32b` 把 **C: 写满到 0 字节**，Ollama 因此丢了全部模型清单
  （`ollama list` 当时为空）。
- 用残留 blob 重建的 `qwen3-vl:30b` **内容已损坏**：让它自我介绍返回
  `"-(!32-&)/!(3()"%!*334(...` 这类乱码，标注调用直接
  `HTTP 500: prediction aborted, token repeat limit reached`。
  ⇒ 本地标注通道在重新拉取前不可用。
- 抢救方式**不删数据**：把无人引用的 3 个 blob（≈49 GB）**移动**到
  `work/ollama_leftover_*.bin`，C: 恢复可用空间；需要时可以原样搬回
  `C:\Users\小皮\.ollama\models\blobs\`。

## 5. 因此产生的长跑配置（可复现）

```powershell
$env:GLM_API_KEY = "<只从环境变量读，绝不进仓库>"
$env:GLM_THINKING = "enabled"     # 能跑完的最高档；max 实测不出正文
$env:GLM_MAX_TOKENS = "32768"     # 16384 会截断思考
python -u tools/holdout_fill.py --provider glm --model glm-4.6 `
  --batch 12 --window 12 --rounds 400 --min-entries 300 `
  --cards work/glm_max/shard0.jsonl --out work/glm_max/out0.jsonl `
  --progress work/glm_max/progress0.json --partial work/glm_max/partial0.jsonl `
  --report work/glm_max/report0.json
```

每张条目都记 `annotator.{model_id,family,model_version,prompt_sha256,decode}`——
换模型/换思考档/换提示词都不会"悄悄混进同一个标注者"。
