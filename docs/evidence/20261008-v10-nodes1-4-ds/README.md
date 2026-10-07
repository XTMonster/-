# `20261008-v10-nodes1-4-ds` — 前四节点的白模预演**成片**（DeepSeek 引擎，3.6 分钟）

用户 2026-10-08 在 qwen 那条跑到 98 分钟仍未出片之后裁决："**用deepseek吧**"。
这一份是同一份剧本、同一条**插件路径**、只换引擎通道的那一跑：**DONE ＋ 交付包 ok**。

## 1. 交付包（用户要的"前四个节点的白模预演视频"）

```
work/_plugin_v10_nodes1_4_ds/exports/bfd80dba4a99/export/
  blockout_full.mp4            3,271,985 B   ← 13 镜连成一条（VSE 内拼接，无外部 ffmpeg）
  blockout_shot_001..013.mp4   89 KB–486 KB  ← 逐镜参考视频
  first_frames/shot_001..013.png              ← 图生视频输入图（刻意不带标签）
  shots.json / prompts.md / script_compliance.json / README.md
```

## 2. 同一份剧本：**qwen vs DeepSeek**（这是这一跑最值钱的对照）

| 项 | qwen3.8-max-0902@百炼（`20261008-v10-nodes1-4-run`） | **DeepSeek**（本份） |
|---|---|---|
| 终态 | 98 min 时仍在 `shot_004`，**撞 120 min 墙前被用户叫停** | **DONE** |
| 墙钟 | 98+ min（其中 45 min 是 3 次 900 s 超时白等） | **3.6 min**（LLM 合计 188.5 s） |
| LLM 调用 | 29 次（到 shot_004 为止） | **69 次**（13 起草 ＋ 23 修复 ＋ 27 ReAct ＋ 4 审核 ＋ plan/understand） |
| 单次调用 | 中位 117 s，最长 900 s（超时） | 中位 **1.5–5.1 s**，最长 14.0 s（plan） |
| token | 未统计完（同一调用 1–10 分钟） | **428,373**（prompt 389,044 ＋ completion 39,329）= 上限 2 M 的 21% |
| 交付 | **无** | **13 段 mp4 ＋ 连播 ＋ 首帧 ＋ 三个 json/md** |

⇒ 结论：**慢的根因是通道（思考档 × 长尾超时），不是这条插件链**——同一份输入、同一条
代码路径、只换上游，墙钟差 **27 倍**（98+ min 未完成 vs 3.6 min 完成）。

## 3. 这一跑的质量读数（**不能只看"跑完了"**）

* **声明侧完全对齐**：`script_compliance.ok = true`，声明 13 镜 / 69.0 s ＝ 计划 13 镜 / 69.0 s；
  13 条 `E_SCRIPT_001` 里 **全是 warning**（0 error），逐镜帧数差 `frames_delta = 0`。
* **质量门不达标的多**：`audits 44 / failed_audits 36`（`audit_pass_rate 6/12`）、`repairs 23`、
  **9/13 镜 `degraded = true`**、`drafts_failed 9`。也就是说：**片子出来了，但大部分镜头是"带已知问题降级交付"的**。
* 新配置生效确认：`knowledge.top_k = 15`、`token_limit = 50000`、`plan_token_limit = 60000`、
  `retrieval_calls = 14`、`degraded = false`（即上一轮定的检索宽度确实在用）。

## 4. 这一跑新暴露的缺陷（都带现场证据）

### ① 环境锚点解析不出坐标（6 条）—— **中**

```
unresolved_anchor: 码头市场拱廊顶棚: relation='覆盖全场上方，蓝绿色铸钢雕花铁艺框架' 解析不出坐标
unresolved_anchor: 拱廊立柱与围栏／干鱼串与彩旗串／糖果摊位／远处海面与海雾／地面薄水洼 …
```

`SceneBrief.space` 里的自然语言关系落不到坐标 ⇒ 这些环境元素**没进场景**，后面的"动作引用"
自然全落空（见 ②）。修法：给 `space` 加一条"可解析关系"的闭集（方位＋距离类），解析不出就
**报 finding 而不是静默跳**（现在只有一条 warning）。

### ② 环境节拍被当成"角色动作"，然后被整条丢掉 —— **高（这一跑 shot_001 的 10 条警告全是它）**

```
shot_001: 动作引用了不在场的角色 干鱼串与彩旗串，已跳过   ×2
shot_001: 动作引用了不在场的角色 地面薄水洼，已跳过        ×2
shot_001: 动作引用了不在场的角色 远处海面与海雾，已跳过    ×2
```

模型把"海风吹动干鱼串"这类**环境节拍**塞进了 `character_action`。修法：工具层拒绝
非在场主体的动作并**回一条可执行的错误**（"环境节拍请用 `create_vfx`／氛围字段"），
而不是先接受、后跳过——现在是"计划里写着、片子里没有"。

### ③ 占位 id 漏进产物与画面 —— **高**

`shot_010` 的 `characters = ["char_a", "char_b"]`（剧本写的是米迦尔），
而且 `axis_pair` 从 shot_010 起一直是 `["char_a","char_b"]`；
`label_report` 里**白模画面上真的渲染出了 `char_a` / `char_b` 这两个标签**。
R015 只报了 warning（"身份错位"）。修法：计划落地时把 id 归一成角色名，
归一失败就**判 error**（这已经不只是"错位"，是把内部 id 印到成片上了）。

### ④ 同层动作大量重叠，靠 `§9.7 串行` 事后错开 —— **中**

shot_007 4 条、shot_008 3 条、shot_010 **6 条**（"已把 36–53 后移到 73–90"）。
事后错开会改变节奏（尤其动画的蓄-发-收三段），应该**在计划期就报给模型**。

### ⑤ 声明景别被改写（R015 ×3） —— **中**

镜5 声明 CU → 计划 MS；镜8 声明 MCU → MS；镜10 声明 MCU → MS。
声明是硬约束，这里只有 warning，且没有"破例理由"。修法同 v1.5 的既有纪律：
要么照做，要么**显式声明破例**（`declared_breaks`）。

### ⑥ `request_self_review` 无人承接 —— **中**（qwen 那一跑也撞到，`self_review_requested 19` 次）

DeepSeek 这一跑模型请了 **19 次**自审，交付包里**没有任何"需要人看"的标记**
（`shots.json` 里没有 `needs_review` 字段）——后台跑的时候这一步等于没发生。

## 5. 复现（两条命令）

```powershell
powershell -File work/_start_sidecar_deepseek.ps1            # -> 127.0.0.1:8782（DeepSeek）
powershell -File work/_run_plugin.ps1 `
    -Script 'fixtures\shotlist_market_v10_nodes1_4.txt' `
    -SidecarUrl 'http://127.0.0.1:8782' -Model 'deepseek-chat' -Preset 'hd16x9' `
    -OutDir 'E:\白模预演codex\work\_plugin_v10_nodes1_4_ds' `
    -LogStem 'run_nodes1_4_ds' -LlmTimeout 300
```

（`--llm-timeout 300` 与台账里 DeepSeek 那条长跑同口径；qwen 那条需要 900 s，见缺陷清单 ①。）

## 6. 未验证 / 未做

* **成片没做人工观感验收**：本节所有结论都是产物字段与审计读数，**没有人逐镜看过画面**
  （9/13 镜带 degraded，值不值得看、差到什么程度，需要人眼）。
* `unresolved_anchor` 六条与"环境节拍被当成角色动作"的**因果关系**（是不是前者导致后者）只是推断。
* qwen 那条**没有产出**，所以"qwen 的成片质量 vs DeepSeek"这个对比**无从谈起**——
  能比的只有"耗时/能否跑完"。要真比质量，得让 qwen 在 240 min 墙钟下重跑一次（用户可点名）。
* 会诊第二侧现已接好 `--partner qwen`（commit `08a4348`），但那一跑的判词**未返回**，
  本目录不留空位、不冒充有判词。
