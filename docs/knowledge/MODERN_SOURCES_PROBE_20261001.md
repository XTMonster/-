# 现代／动漫来源可达性：**逐站实测**（2026-10-01 晚，第二轮）

这份文件是**实测记录**，不是计划。它回答用户 2026-10-01 的三条要求：
「补充现代知识教材、理论体系」「再补一些动漫设计理论（不是角色设计，是动漫视频
制作）」「围绕动漫电影展开」。判据一律是**仓库自己的门**：`tools/kb_fetch/fetch.py`
的 `robots_allows()` / `crawl_delay()`（取不到 `robots.txt` 一律拒收），
不是"我以为它允许"。

## 一、方法

```python
from tools.kb_fetch import fetch
fetch.robots_allows(url, timeout)   # -> (allowed, reason)
fetch.crawl_delay(url, timeout)     # -> 秒
```

**关键区分（上一版文档混掉的一点）**：

| `reason` | 含义 |
|---|---|
| 空 | robots 允许 |
| `robots_disallow:<rule>` | 站点**明确禁止**这个路径（真拒绝） |
| `robots_unavailable:URLError` | **本机连不上**那个域名（DNS 被污染／不可达），**不是站点拒绝** |

实测 DNS：`en.wikipedia.org → 199.16.158.8`、`archive.org → 162.125.32.15`
（都不是这些站点的真实地址）→ 属**本机网络层**不可达，换成别的网络有可能可用；
`journals.illinois.edu` 干脆 `gaierror`（无解析）。

## 二、实测结果（2026-10-01 18:45–19:05）

| 站点 | 判定 | Crawl-delay | 结论 |
|---|---|---|---|
| `arxiv.org/pdf/...`、`/abs/...`、`/list/...` | **ALLOW** | **15.0 s** | 可用；`/search` 与 `export.arxiv.org` 被 `robots_disallow` |
| `ocw.mit.edu`（含 `/sitemap.xml`、`/courses/…`） | **ALLOW** | 0 | 可用；sitemap 实测列出 **2587 个课程 URL** |
| `necsus-ejms.org`（NECSUS，**CC-BY**） | **ALLOW** | 0 | 可用；category 页可枚举文章 |
| `framescinemajournal.com` | **ALLOW** | 0 | 已在用（3 篇） |
| `sensesofcinema.com` | **ALLOW** | 0 | 可用；索引页抽出 131 条文章链接 |
| `pressbooks.pub` | **ALLOW** | 0 | 上一版文档记的"被拒"**不成立**（当时是网络抖动） |
| `courses.lumenlearning.com` | **ALLOW** | 0 | 可用（具体课程路径要另找） |
| `cinergie.unibo.it` | **ALLOW** | 0 | 可用（电影/动画期刊） |
| `mediaindustriesjournal.org` | **ALLOW** | 0 | 可用（制片/产业研究） |
| `doaj.org` | DENY | — | `robots_disallow:/search` |
| `milnepublishing.geneseo.edu`、`oercommons.org`、`saylor.org`、`film-philosophy.com`、`bfi.org.uk`、`nofilmschool.com`、`premiumbeat.com`、`ejumpcut.org`、`journal.animationstudies.org`、`media-studies.ca` | DENY | — | 取不到 `robots.txt`（HTTPError） |
| `en.wikipedia.org`、`archive.org`、`open.umn.edu`、`journals.illinois.edu`、`thefilmstage.com`、`sagepub.com` | DENY | — | **本机网络层不可达**（DNS 污染/无解析），非站点拒绝 |

## 三、动漫（anime）专题：**在可达集合里找不到**

用户点名的缺口是"动漫视频制作理论"。实测三处：

* `necsus-ejms.org` 的 features + audiovisual 两个分类页共 176 条链接，
  命中 `anime|animat|manga|cartoon|cel|toon|otaku|sakuga` 的只有 **1 条**
  （《The Environmental Footprint of Animated Realism…》——数字动画纪录片，不是动漫制作）；
* `framescinemajournal.com/issue/` 目录页 **404**，首页 32 条链接里 0 条；
* 专门做动漫研究的开放期刊（`journals.illinois.edu` 的 *Journal of Anime and Manga
  Studies*、`journal.animationstudies.org`）**本机不可达**。

也就是说：**动漫域的现状（1 篇来源：Lutz《Animated cartoons》1926，141 张卡）
不是"忘了抓"，是可达来源里确实没有第二个**。要么换网络/换环境（DNS 可达性
是环境问题），要么由用户提供/授权具体书目。

## 四、因此值得做的一件事（下一轮的**可选**工作项）

在**可达**集合里，能补的是"现代电影/媒介理论"而不是动漫：

* `arxiv.org`：`2408.17424 = CinePreGen: Camera Controllable Video Previsualization
  via Engine-powered Diffusion`（实测 `/abs/` 可取；正是"分镜/运镜预演"的同题论文）；
  15 s 节流意味着一次只能拿一本，适合小批量、高价值的挑选；
* `ocw.mit.edu`：sitemap 可枚举 2587 门课，其中电影/媒介课（`21L.011`、`CMS.*`、
  `4.341` 等）可逐课取讲义 PDF；许可 `CC-BY-NC-SA` 已在白名单；
* `necsus-ejms.org`：**CC-BY**，文章级可枚举，主题覆盖剪辑/空间/声音/媒介考古；
* `sensesofcinema.com`：开放获取影评与研究长文（含剪辑节奏专题）。

**代价（必须如实说）**：任何语料扩充都会**换掉索引**，而 held-out oracle 的每条
期望都指向索引里的具体边——所以扩充之后必须**重跑整个 oracle**（GLM 池通道实测
约 2.3 小时／65 批）。因此本轮的顺序是：先把当前索引的验收链跑完并留档，
再决定要不要为一个"补现代理论、但补不了动漫"的扩充再付一次 oracle 的钱。
