# 知识语料的许可与归属（P14-1 · 执行文档 v1.4 §2.3c）

本文件逐条声明 `knowledge/` 下语料的来源、许可与归属，供审计。
机器可判的许可门在 `tools/kb_fetch/validate_licenses.py`，白名单为
`CC0 / CC-BY / CC-BY-SA / PublicDomain / OwnWork / ExplicitPermission /
PersonalStudy`；
不在白名单内的一律进 `work/license_rejects.jsonl`，**不入库**。

## 一、入库规则（写死的口径）

1. **改写而非转载**：入库的是「知识（规则 / 条件→取舍 / 术语定义）＋ 短引用（≤2 句、≤120 字）＋ 出处」，
   不是原文长段落。引用块以 `quote:` 字段与正文分离，超限或非逐字即拒收。
2. **原文快照不入库**：抓取缓存与原文只存在于 `work/`（已被 `.gitignore` 忽略），
   仓库里只保留 `source_ref.sha256` 供校验；重新抓取即可复现。
3. **绝不抓取**：整部剧本、整部字幕、付费墙内容、需登录内容、`robots.txt` 禁止的路径。
   `fetch.py` 会先读 `robots.txt`，取不到就拒收。
4. **限速**：同一域两次请求之间至少间隔 `--rate` 秒（默认 1.0），并携带固定的
   `User-Agent`。

## 二、公有领域文本（`mode: http`）

下列文本取自 Project Gutenberg（公有领域，`license: PublicDomain`）。
逐条的 `url` 即纯文本地址，`sha256` 在抓取时写入 `source_ref`。

| 标题 | 作者 | 用途（域） |
|---|---|---|
| Practical Cinematography and Its Applications | Frederick Arthur Ambrose Talbot | 摄影 / 机位 |
| Photography at home | John A. Tennant | 摄影 |
| Bromide Printing and Enlarging | John A. Tennant | 摄影（洗印） |
| Pictorial Composition and the Critical Judgment of Pictures | Henry Rankin Poore | 构图 |
| Lectures on Painting, Delivered to the Students of the Royal Academy | Edward Armitage | 构图 |
| The Theory and Practice of Perspective | G. A. Storey | 构图 / 透视 |
| The Use of a Box of Colours | Harry Willson | 构图 / 色彩 |
| Light and Colour Theories | Joseph W. Lovibond | 光线 / 色彩 |
| Tinting and toning of Eastman positive motion picture film | Eastman Kodak Company | 色彩 |
| The Photoplay: A Psychological Study | Hugo Münsterberg | 剪辑 / 观众心理 |
| Writing the Photoplay | J. Berg Esenwein | 分镜 / 剧本 |
| How to write photoplays | Embrie Zuver | 分镜 / 剧本 |
| The photodrama: the philosophy of its principles | Henry Albert Phillips | 分镜 |
| Animated cartoons — How they are made | Edwin George Lutz | 动画 |
| How to Produce Amateur Plays: A Practical Manual | Barrett H. Clark | 调度 |
| Dramatic Technique | George Pierce Baker | 表演 / 剧本 |
| Heroines of the Modern Stage | Forrest Izard | 表演 |
| Motion Picture Operation, Stage Electrics and Illusions | Henry Charles Horstmann | 制片 / 灯光 |

> Project Gutenberg 的文本在美国属公有领域；本仓库只保留改写后的知识与 ≤2 句短引用，
> 并保留书名、作者与 URL，符合"知识＋短引用＋出处"的入库纪律。

## 三、自撰笔记（**已退出语料，仅作设计文档**）

**2026-10-01 用户裁决**：「理论不要自己写，要别人写的——专业的事情交给专业的人做」。
因此 `knowledge/source_notes/*.md`（27 篇）**不再进语料**：
`knowledge/sources.yaml` 里 `mode: manual` 的条数为 **0**，
`knowledge/cards_generated/*.jsonl` 里 `repo://` 的条数为 **0**。

文件本身留在仓库里，身份从"知识来源"降为"设计文档"：它们记录了每条规则当初的
引擎落点与取舍理由（`docs/adr/0007`…`0013` 引用它们）。判据是机器门
`tools/knowledge/authorship_report.py`（退出码 0 = 生成卡全部来自他人著作），
由 `tools/run_tests.ps1` 写进 `docs/evidence/<run-id>/authorship.json`。

> 仍然**允许** `mode: manual` ＋ `repo://` 这条管线能力本身（`fetch.py` 有它、有测试），
> 只是**当前语料不再用它**——`repo://` 依然被当作"本项目自撰"，一旦出现在生成卡里
> 就判失败。

| 文件 | 主题 | 域 | 现状 |
|---|---|---|---|
| `camera_angle_and_lens.md` | 机位高度、角度与焦距 | 摄影 | 设计文档 |
| `lighting_and_color.md` | 布光体系与色彩情绪 | 摄影（K5: lighting / color） | 设计文档 |
| `editing_rhythm.md` | 剪辑节奏与动作连贯 | 剪辑（K5: editing） | 设计文档 |
| `storyboard_practice.md` | 分镜表与镜头清单 | 分镜（K5: storyboard） | 设计文档 |
| `anime_language.md` | 日式动画镜头语言 | 动画（K5: anime） | 设计文档 |
| `blocking_and_performance.md` | 场面调度与表演节拍 | 调度 / 表演 | 设计文档 |
| `axis_continuity.md` | 轴线与银幕方向 | 轴线理论 | 设计文档 |
| `production_pipeline.md` | 预演交付与制片流程 | 制片 | 设计文档 |

## 四、引用块与"改写"的机器判定

`tools/kb_fetch/import_cards.py::gate()` 对每条入库条目执行：

1. `source_ref` 六字段（`url/title/author/license/retrieved_at/sha256`）全非空；
2. 许可在白名单内；
3. `quote` 句数 ≤2（CJK `。！？` ＋ ASCII `.!?`）且 ≤120 字；
4. `title` / `content` 非空，`domain` 属于九域。

任一条不过 → 该条进 `cards_rejected`，并在报告里留原因。

## 五、现代理论语料（v1.5）

老语料的话题是 1900–1920 年的：机位、轴线、构图、剪辑的**原理**今天仍然
成立，但数字摄影、虚拟制片、声音设计、动作与打击感、现代分镜与演出实务
完全没有覆盖。第五节以下的材料就是补这一半。

### 5.1 自撰现代理论笔记（`license: OwnWork`）——**已退出语料**

下面这组笔记由本项目自撰，是 v1.5 为补现代理论而写的。按 2026-10-01 的用户裁决，
它们和第三节一起**退出语料、只作设计文档**；空出来的域由第五节以下的
**他人著作**（Project Gutenberg 公有领域实务书 ＋ MIT OCW 讲义）补，
K3 的门一个字不放宽。

| 文件 | 主题（域） |
|---|---|
| `modern_cinematography_digital.md` | 曝光/快门/感光度、传感器与景深、宽容度、LUT 与虚拟棚（摄影） |
| `modern_axis_and_continuity.md` | 三种轴线、越轴的四种安全手法、银幕方向与连续性（轴线） |
| `modern_composition_theory.md` | 视觉重量、引导线与视线、图底分离、留白数值、画幅（构图） |
| `modern_editing_theory.md` | 剪辑动机、动作剪辑点、声画错位、节奏分布、覆盖（剪辑） |
| `modern_sound_and_impact.md` | 声画关系、J/L-cut、空间感、低频、静默、音乐克制（剪辑） |
| `modern_performance_theory.md` | 目标/障碍/动作、节拍、潜台词、景别与表演尺度（表演） |
| `modern_blocking_and_staging.md` | 为镜头调度、纵深三平面、群体调度、单灯位约束（调度） |
| `modern_action_and_impact.md` | 准备/打击/恢复、打击感三要素、震动换算、速度斜坡（调度） |
| `modern_storyboard_and_previs.md` | 镜头清单契约、动态分镜、三档精度、覆盖与预算（分镜） |
| `modern_anime_and_2d_practice.md` | 演出、时间表与 1/2/3 格、冲击帧、口型经济、合成（动画） |
| `modern_production_pipeline.md` | 阶段划分、虚拟制片、VFX 拆分、数据交接、版本纪律（制片） |

### 5.2 现代教材/论文/讲义（`license: PersonalStudy`）

`PersonalStudy` 是 v1.5 新增的一档，专门给**受版权保护的现代教材、论文与
课程讲义**。它的含义是**作者本人（库的使用者）出于个人学习目的阅读与摘录**，
与"拿到授权"（`ExplicitPermission`）不是一回事，因此单独记名：

* **不对外分发**：本仓库不作为该部分材料的分发渠道；派生出的卡片只保留
  **改写后的知识＋≤2 句短引用＋出处**，不保留原文长段；
* **可一眼筛出**：需要对外发布、投稿或商用前，用
  `grep -c 'PersonalStudy' knowledge/cards_generated/*.jsonl` 即可定位全部条目；
* **逐条归属**：每一条的 `source_ref` 六字段（含 URL、作者、许可、抓取时间、
  sha256）随卡片入库，可回溯到原页面。
