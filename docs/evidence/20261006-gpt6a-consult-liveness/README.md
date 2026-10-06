# GPT-6A 会诊通道：本轮"是否还在跑"的取证，以及问题包**换代**

日期 2026-10-06 18:2x。本目录只记**三件可复算的事**，不记任何读数结论：
① 通道探针（证明中转站本身没坏）；② 长跑任务的存活取证（证明它没崩、没自旋）；
③ 问题包**换代**——原来那份"全面评审"包喂的是**过期前提**，换掉后重发。

## 一、通道健康探针

```powershell
$env:LINKAI_API_KEY = (Get-ItemProperty 'HKCU:\Environment' -Name LINKAI_API_KEY).LINKAI_API_KEY
python -u work/_gpt6a_ask.py --question work/_q_probe.md --max-tokens 128 --timeout 600 --out work/_probe_answer.md
```

输出（逐字）：

```json
{"channel": "relay", "usage": {"model": "gpt-6-astra", "requested_model": "gpt-6-astra",
 "max_tokens": 128, "elapsed_s": 2.8, "usage": {"prompt_tokens": 70, "completion_tokens": 7},
 "finish_reason": "stop", "levels_ignored": ["max"], "channel": "linkai-relay", "attempts": []}, "chars": 8}
```

正文 `PROBE_OK`。⇒ **通道是通的**（70 prompt token → 2.8 s）。
顺带记一笔：`levels_ignored=["max"]`——relay 通道不认 `levels` 参数，
档位只由环境变量 `LINKAI_REASONING_EFFORT` 决定（默认 `max`），与既有口径一致。

## 二、长跑任务（pid 53944）的存活取证

`Get-CimInstance Win32_Process` + `Get-NetTCPConnection` + 每 30 s 采一次
`ReadTransferCount`/`WriteTransferCount`/`KernelModeTime+UserModeTime`：

| 检查 | 读数 |
|---|---|
| 进程 | 在（pid 53944，17:19:49 起，`--timeout 5400`） |
| 连接 | `Established` → `104.21.78.23:443`（Cloudflare 边缘，中转站） |
| 采样窗口 18:21:13 → 18:23:44（2.5 min） | `dRead=0`、`dWrite=0`、`dCpu=0 ms`（每个采样点全 0） |
| 生涯累计 | `read=1,557,855 B`（≈1.5 MB，是 Python 自己的导入/启动读）、`cpu≈0.08 s` |

⇒ **它在阻塞读网络**：没在自旋（0 CPU）、没崩（进程在）、连接没被断（Established）。

**局限（必须写清）**：这条流**没有 keepalive 帧**，所以"本机 0 字节"**无法**区分
「远端还在生成」与「远端已经哑了」。本目录**不主张**它一定在思考——
只主张它**没死**、且通道对**小包**是通的（见上）。

## 三、问题包**换代**（本轮真正的价值）

旧包 `work/_q_gpt6a_full_head.md` 在"③ 三条已查到底的结论"里写着：

> （正在跑的最后一步：把 oracle-3 **一条一呼**地判，直接看"逐条独立盲评"能不能把它救回来。）

**这一步已经跑完，而且是负结果**：`docs/evidence/20261006-oracle-alone/`（15:43）——
oracle-3 逐条单独盲评 E1 只有 **0.1458**（28/192），比三元组的 0.4583 **更差**。
⇒ 喂旧包等于让 GPT-6A 去论证一条**已被实测排除**的路线。
（旁证：它 13:55 那份 `work/_gpt6a_rk13_answer.md` 给的就是"**选 B：修判分协议**"，
而 **B 正是被这份证据推翻的那条**。）

换代后把三件事实写进包：
1. **B（逐条独立盲评）已被实测排除**（0.1458）；
2. 因果由"批次效应"改为"**案例 × 呈现方式**"的**共同属性**；
3. 候选收口只剩 **A（如实红着）** 与 **C（把"呈现方式"写进度量定义）**。

`packs/` 下是**逐字原件**：

| 文件 | sha256(前 12) | 字节 |
|---|---|---|
| `packs/full_head.md`（换代后的全面评审包） | `adbe760c055b` | 5,309 |
| `packs/a_metric.md`（度量本身可信吗） | `168161b30163` | 1,774 |
| `packs/b_closeout.md`（两件未收口怎么收） | `3d72ec0c9e15` | 1,822 |
| `packs/c_arch.md`（架构该改哪、漏了什么） | `0d0e770dc57d` | 1,339 |

## 四、本轮发出去的五个问题

全部 `--provider relay` / `gpt-6-astra` / `reasoning_effort=max`（默认），**都在跑**：

| pid | 问题包 | 输出 | 超时 | 备注 |
|---|---|---|---|---|
| 53944 | `full_head`（**旧包**） | `_gpt6a_full_answer.md` | 5,400 s | 17:19:49 起，**约 18:49 会超时退出**；旧前提，只当交叉对照 |
| 34188 | `full_head`（换代） | `_gpt6a_full_answer_b.md` | 21,600 s | 主件 |
| 51160 | `a_metric` | `_gpt6a_a_metric_answer.md` | 21,600 s | 拆小包，先出结论 |
| 48568 | `b_closeout`（换代） | `_gpt6a_b_closeout_answer.md` | 21,600 s | 拆小包 |
| 38420 | `c_arch` | `_gpt6a_c_arch_answer.md` | 21,600 s | 拆小包 |

启动脚本 `work/_run_gpt6a_aspects.ps1`（在 gitignore 的 `work/` 下）。

## 五、未验证 / 本目录不主张的东西

* **一条答案都还没拿到**。本目录只证明"任务在跑 ＋ 包是对的"，**不等于**通道能在这个包大小上出结果。
* 长跑那份的**上一代**（17.5 KB）跑 64 分钟无输出已被掐掉；1.2 KB 这份已跑 65 分钟无输出
  ⇒ "包越大越慢"的规律**方向一致**，但**具体阈值未标定**。
* GPT-6A 的判词**一条都不是事实**；落地前必须由主线逐条证实/证伪（按《模型分工契约》§3.4）。
