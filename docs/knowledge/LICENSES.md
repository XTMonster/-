# 知识语料的许可与归属（P14-1 · 执行文档 v1.4 §2.3c）

本文件逐条声明 `knowledge/` 下语料的来源、许可与归属，供审计。
机器可判的许可门在 `tools/kb_fetch/validate_licenses.py`，白名单为
`CC0 / CC-BY / CC-BY-SA / PublicDomain / OwnWork / ExplicitPermission`；
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

## 三、自撰笔记（`mode: manual`，`license: OwnWork`）

`knowledge/source_notes/*.md` 由本项目自撰，版权归本项目作者，许可记为 `OwnWork`。

**URL 约定**：因为来源就在本仓库里，`url` 用 `repo://<仓库相对路径>` 表示
（例如 `repo://knowledge/source_notes/anime_language.md`）。它不是网络地址，
而是可被任何人打开、复算 sha256 的稳定标识——`fetch.py` 因此不需要网络就能取到正文，
并且 `sha256` 可以直接对文件内容重算验证。

| 文件 | 主题 | 域 |
|---|---|---|
| `camera_angle_and_lens.md` | 机位高度、角度与焦距 | 摄影 |
| `lighting_and_color.md` | 布光体系与色彩情绪 | 摄影（K5: lighting / color） |
| `editing_rhythm.md` | 剪辑节奏与动作连贯 | 剪辑（K5: editing） |
| `storyboard_practice.md` | 分镜表与镜头清单 | 分镜（K5: storyboard） |
| `anime_language.md` | 日式动画镜头语言 | 动画（K5: anime） |
| `blocking_and_performance.md` | 场面调度与表演节拍 | 调度 / 表演 |
| `axis_continuity.md` | 轴线与银幕方向 | 轴线理论 |
| `production_pipeline.md` | 预演交付与制片流程 | 制片 |

## 四、引用块与"改写"的机器判定

`tools/kb_fetch/import_cards.py::gate()` 对每条入库条目执行：

1. `source_ref` 六字段（`url/title/author/license/retrieved_at/sha256`）全非空；
2. 许可在白名单内；
3. `quote` 句数 ≤2（CJK `。！？` ＋ ASCII `.!?`）且 ≤120 字；
4. `title` / `content` 非空，`domain` 属于九域。

任一条不过 → 该条进 `cards_rejected`，并在报告里留原因。
