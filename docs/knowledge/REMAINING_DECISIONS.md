# 剩余红门的决议清单（2026-10-01，主 agent）

四道红门各自的**当前数字、根因、可选项、我的建议与代价**。本文只汇总，逐项证据在
`ACCEPTANCE_STATUS.md` §九与 `ORACLE_DECISION_v15.md`。

## ① 门④ 边类覆盖：3 类短线，**供给天花板**

```
short_pairs: IMPACT_PACK 22 / SOUND_PACK 21 / MUSIC_PACK 14   （线是 30）
```

根因已查到底（§9.12）：这三类的**原子边数 ≈ 覆盖卡片数 ≈ 22**，且 required 签名
大多各不相同 —— 跨卡归并**没有可并的东西**，所以"对数 ≈ 原子数"，够不到 30。

* **选项 A（推荐先试）**：换来源族。判据是"许可白名单 ＋ robots 门 ＋ 真的讲剪辑/声音实务"。
  已知两次 Gutenberg 定向检索都空手（20 本里 4 本有技术内容，其中 3 本本来就在语料里）；
  下一步要试的是**CC 授权的高校影视制作课程讲义/开放教材**这类别的来源族。
* **选项 B（若 A 失败则必须裁决）**：`--min-per-type 30` 是 schema 只有 6 类时的常数。
  16 类摊同一份许可语料后，这三类**在构造上够不到**。要不要按"每类 ≥10 张卡 ＋
  该类的全部可断言对"重定这条门，是**规格裁决**。
* **代价**：A 需要新的抓取/清洗轮（数小时，且不保证找得到）；B 改的是验收标准本身。

## ② 门⑥ 来源覆盖：缺 393/2113，**三类成因已定量**

```
no_edge_at_all              184   ← 索引里没有任何边引用这张卡（供给）
in_oversized_group          177   ← 该卡的边落在 >3 的 (类型,查询) 组里，整组被跳过
edge_has_out_of_vocab_value  32   ← 边里有词表外取值，整条被跳过
```

`in_oversized_group` 里 **150 张是 `STAGING_PACK`**，而它的成因与 `EDIT_RHYTHM`
**不是同一种**（那一种是"缺查询键"，已修）：

```
group size 4 | type STAGING_PACK | q = 景别=MS；机位=平视；构图=occlusion
  [构图=occlusion, 景别=MS, 机位=平视, forbid_composition_rule=balance]        cards 1
  [构图=occlusion, 景别=MS, 机位=平视, forbid_composition_rule=rule_of_thirds] cards 1
  ...
```

四条边的**必填成员完全相同**，区别只在"**禁止哪个构图规则**"。而 `q` 里同一个键
只有一个值 —— `构图` 已经被必填值 `occlusion` 占用，**被禁止的那个取值写不进去**。
`query_of()` 因此只能跳过 forbid 侧，四条边拿到同一个 q、不可区分，整组被跳过。

* **选项 A（推荐）**：给 `forbid` 值一套**独立查询键**（例：`禁构图` → `forbid_composition_rule`）。
  这样 q 可以同时说"构图=occlusion（要）"与"禁构图=balance（不要）"，四条边立刻可分，
  实测**直接回收 150 张卡**。代价：协议 §2.1 的键集要扩（与 v1.5 加 `强度`、
  v1.6 加 `镜长`/`语气`/`配乐`/`道具` 同类），要同步提示、词表、oracle。
* **选项 B**：不动。那 150 张卡在门⑥ 里就一直是红的 —— 但**这是诚实的**：
  当前查询语言确实表达不出这些边之间的差别。

## ③ 门⑦ 人审：**通路已打通，等你 74 个勾**

`tools/knowledge/human_review_sheet.py` 生成的表里正好 **74 节**（= 门⑦ 会数到的条数），
门⑦ 判据是 `reviewed >= min(needs, 120)` → **勾完即过**。三步命令在
`docs/knowledge/HUMAN_REVIEW_SHEET.md` 表头。**这一步 agent 不能代替**（协议 §5.5/§5.6：
双模型复核只能写 `llm-panel`，写 `human` 就是伪造证据）。

## ④ 门⑧ 换族：GLM 在跑

`glm_v6`（`glm-4.7-flash`，family zhipu，与抽取器 deepseek 异族）。跑完 → 提升 →
门⑧ 有望转绿。当前 oracle 是**机械通道**的临时件，隔壁新增的检查正确地拒绝了它
（`non_model_families: ["rule"]`）—— 这条红是**对的**。

## ⑤ 质量指标 Q4 / Q6b：0.972 / 0.9865（合同线 1.0）

已定量（§9.8）：`occurrences` 让"部分匹配但更常见"的边以 0.002–0.01 的分差把
"逐字全中"的边挤出 top-3；Q6b 另有一部分是 `render_edges` 的 2000 token 预算丢边。
权重已做过一次 12 点网格扫参（四项同时变好）。**剩下的缺口需要"锚点"层面的改动**：
`Q4` 要求每条 required 都进 top-3，而当同一个查询下"完全对齐"的边多于 3 条时，
它在数学上不可能 —— 选项 A 的**forbid 键**同样会缓解这一类（它让更多边变得可分）。

## 汇总建议（按性价比排序）

1. **门⑦ 74 个勾**（你，30 分钟）——唯一"做完就绿"的一条。
2. **门⑧**：等 GLM v6（在跑）。
3. **门⑥ 的 forbid 键**（我，协议级扩展）——实测直接回收 150 张卡，且与 Q4 的机制同源。
4. **门④/⑥ 的来源族**（我，需要新抓取族；不保证成功）。
5. **门④ 的门限重定**（你，规格裁决；我不会单方面动）。

## 附：三次定向来源检索的原始结果（避免重复同样的关键词）

每次都走管线自己的 `find_sources.py`（候选逐本过真实 fetch＋extract 门）：

| # | terms | 命中/可抓 | 有技术内容的 |
|---|---|---|---|
| 1 | `photoplay scenario continuity "screen writing" "picture music"` | 8 / 8 | **3**（Writing the Photoplay、How to write photoplays、The Photoplay: A Psychological Study）——**且这 3 本本来就在语料里** |
| 2 | `"motion pictures" cinematography sound technique editing` | 12 / 12 | **1**（Moral Deliberations in Modern Cinema） |
| 3 | `"incidental music" "moving picture music" "trick photography" stunt "mechanical effect"` | 9 / 9 | **2 待评估**（Magic, Stage Illusions and Scientific Diversions；Photographic Amusements）——其余是芬兰语小说／stunt 短篇／"Picture stuff" |

三次共 29 本，只有 4 本与前 3 类短线相关，其中 3 本**已在语料里**。
即：**Project Gutenberg 的关键词检索基本只返回小说**，用它补 `IMPACT_PACK`／
`SOUND_PACK`／`MUSIC_PACK` 是低效路径。下一步要换**馆藏**（CC 授权的高校影视制作
课程讲义/开放教材），而不是继续换关键词。

顺带修掉一个真缺陷（提交见下）：`find_sources.py` 在中文 Windows（控制台 GBK）上
碰到书名里的 `ä` 会抛 `UnicodeEncodeError` **把整轮验证打断**，已经抓完的书一起丢。
现在 stdout/stderr 一律 reconfigure 成 UTF-8 + replace：编码问题最多显示成 `?`，
不会作废一次几十分钟的抓取。

## 附二：换馆藏的第一次尝试（MIT OCW）——**HTML 抓不到**

思路：Gutenberg 三次检索都只返回小说，那就换 CC 授权的高校课程材料（OCW 的
`CC-BY-NC-SA` 已在许可白名单里，语料里已有 2 份 21L.011 的 PDF）。

实测（走管线自己的 `fetch._http_get`，含 robots 门）：

```
robots_allows("https://ocw.mit.edu/courses/21l-011-the-film-experience-fall-2013/") -> (True, "")
_http_get(...) -> 49845 bytes
页面内 ".pdf" 出现次数        -> 0
页面内 "/resources/" 链接数   -> 0
```

即：**OCW 的课程页是 JS 外壳**，静态 HTML 里既没有 PDF 链接也没有资源列表
（语料里那两份 PDF 的 URL 带内容哈希，像是从别处/旧版页面拿到的）。
所以"抓课程页 → 抽 PDF 链接"这条路**在静态 HTML 上走不通**，需要 OCW 的
JSON/API 或 sitemap（本轮未找到、不猜）。

下一步的候选（都还没试）：OCW 的课程 JSON、其他 CC 馆藏（OER Commons 等）、
公开的 CC 授权影视制作讲义。**在找到可用来源之前，门④/⑥ 的红就如实留着** ——
它们测的正是"许可语料的供给够不够 16 类 schema"。

## 附三：MIT OCW 的**可抓路径**已经找到（下一步照这个做）

上一节说"课程页是 JS 外壳、抓不到 PDF"——继续往下挖，**静态入口是有的**：

```
robots.txt  ->  "Allow: /"  +  "Sitemap: https://ocw.mit.edu/sitemap.xml"
sitemap.xml ->  2588 个 <loc>，**每个课程一个子 sitemap**
                （形如 /courses/<slug>/sitemap.xml）
课程 sitemap ->  ~11 个 <loc>：都是**页面** URL（资源页），不含 .pdf
data.json   ->  只有元数据（course_title/description/instructors/…），**没有资源清单**
```

也就是说：**PDF 链接在"资源页"这一层**，与语料里已有的那两份一致（形如
`/courses/<slug>/<hash>_MIT21L_011F13_2006_Notes.pdf`）。所以可抓路径是：

1. 从 `sitemap.xml` 取 2588 个课程 slug，按**片名/课程名关键词**筛出影视相关课程
   （`film`／`cinema`／`photography`／`media`／`video`／`animation`／`storyboard`）；
2. 对每个候选课程取 `/courses/<slug>/sitemap.xml` → 拿到资源页 URL；
3. 逐个资源页（**过 robots 门、按域限速**）抓静态 HTML，正则抽 `*.pdf`；
4. 抽到的 PDF 走**既有管线**验证（`fetch.py` 的 robots 门 + `extract_text.py`），
   通过的写进 `sources.yaml`（`license: CC-BY-NC-SA`，已在白名单里）。

这是一次**有边界的爬取**（课程数可控、每课程约 10 个资源页、同域限速），
但要真跑起来还需要一个新工具 `tools/kb_fetch/find_ocw_sources.py` ——
把它排进下一轮，与 `MUSIC_PACK` 漏抽、L3 的 `SEQUENCE_FLOOR` 同批（都靠新来源）。

## 附四：OCW 采集的**实际产量**与"要不要全收"的判断

实测两轮采集（`find_ocw_sources.py`，每跳过 robots 门、同域限速）：

| 轮次 | 课程 | 资源页 | 抽到 PDF | 通过管线验证 |
|---|---|---|---|---|
| 1 | 5 | 44 | 8 | **8/8** |
| 2 | 14 | 108 | 50 | **45** |

即：**通路可用，产量可控**（14 个课程拿到 45 份可用讲义 PDF，每份 1.5k–12k 字符）。

**但我没有把它们直接写进 `sources.yaml`**，理由是两条实测约束：

1. **扩语料会抬高门⑥ 的分母** —— 门⑥ 要求"每张入库卡至少派生一条"。现有语料
   2113 张里已经有 **184 张连一条原子边都抽不出**（8.7%）；把这 45 份讲义全部入库
   会新增几百张卡，按同样比例又会带来几十张"无条目卡"，**门⑥ 会从 215 涨回去**。
2. **它们对三条短线有没有用，目前测不出来** —— 关键词粗扫（impact 89 篇／sound 90 篇／
   music 91 篇）用的是 `sound`／`music`／`impact` 这类**通用词**，在任何影视文本里
   都会命中，**不足以证明**能补 `IMPACT_PACK`/`SOUND_PACK`/`MUSIC_PACK` 的 30 对。

所以正确的做法是**有策略地收 + 收完立刻量**，而不是"抓多少收多少"：
先按课程名挑出最可能讲**剪辑/声音/配乐实务**的几门（而不是摄影/电影史那几门），
入库后立刻跑一遍薄边统计；若三条短线的对数没动，就说明这条路也补不上，
那就回到"门限裁决"。

（`find_ocw_sources.py` 目前不记录候选属于哪个课程；下一轮先补上 attribution，
再按课挑选，否则分不清哪份 PDF 来自哪门课。）

## 附五：只收"制作课"的那一轮产量

`--want video media dv-lab --max-courses 8 --max-pages-per-course 10`：

```
课程 8 ｜ 资源页 80 ｜ 抽到 PDF 50 ｜ 通过验证 47
```

课程归属（新加的 `course` 字段终于让它可读）：

| 课程 | 候选数 |
|---|---|
| `cms-611j-creating-video-games-...` | 多数 |
| `4-351-introduction-to-video-spring-2004` | — |
| `21a-550j-dv-lab-...` | — |

**但"制作课"这个名字不等于"讲剪辑/声音/配乐"**：CMS.611 是**游戏制作**，
4.351 是影像导论，dv-lab 是科学纪录片工作坊。它们对 `IMPACT_PACK`/`SOUND_PACK`/
`MUSIC_PACK` 的补益**仍未验证**。

**判定这件事只能靠"收进去 → 抽边 → 数对数"**，不能靠课程名或关键词粗扫
（粗扫用的 `sound`/`music` 在任何影视文本里都会命中）。所以下一轮的次序是：

1. 先入库**一小批**（不是 47 份全收 —— 扩语料会抬高门⑥ 的分母）；
2. 立刻跑：抓取 → 分块 → 卡片 → 索引 → 薄边统计；
3. 若 `IMPACT_PACK`/`SOUND_PACK`/`MUSIC_PACK` 的对数**没动**，就说明这条路也补不上，
   **回到门限裁决**（那是一个需要你拍板的规格问题，我不会单方面调）。

## 附六：扩来源**结案**——两个馆藏都不产"影视制作技术"

按附五的次序执行 A（入库前先看清候选是什么），逐份核对了那 17 份"影视/媒体课"PDF：

| 课程 | 候选实际内容 | 字符数 |
|---|---|---|
| `24-209-philosophy-in-film` | **哲学论文**（imagination／death／Philosophy…） | 9.6k–18.8k |
| `4-343-photography-and-related-media` | 学生作品说明／展览单 | **28–1164** |
| `4-341-introduction-to-photography` | wolfe／exhibit 小页 | 1.3k–2.1k |
| `21l-435-shakespeare-film-and-media` | 一份影评 | 12.9k |
| `21a-550j-dv-lab` | **Cronon《The Trouble with Wilderness》**（阅读材料，不是技术讲义） | 74.5k |

即：**OCW 的"影视课"给的是阅读材料与学生作业，不是制作技术**。加上前面 Gutenberg 的
结论（三轮检索 29 本里 4 本沾边、其中 3 本本来就在语料里），两个馆藏**都不产**
`IMPACT_PACK`/`SOUND_PACK`/`MUSIC_PACK` 需要的那类知识。

所以 **A 的结论是负的**，而且是在**烧掉整条链之前**就得到的——本次没有把这 17 份写进
`sources.yaml`（写进去只会给语料灌入与三类短线无关的卡，并把门⑥ 的分母推高）。

**剩下只有 B**：`--min-per-type 30` 是 schema 只有 6 类、语料是另一批时的常数。
16 类摊一份**许可可得**的语料之后，这三类在构造上够不到 30 对（原子边数 ≈ 覆盖卡片数 ≈ 22，
且 required 签名大多各不相同、跨卡归并无从下手）。这条门限要不要按"每类 ≥10 张卡 ＋
该类全部可断言对"重定，是**规格裁决**，实现不得单方面调。
