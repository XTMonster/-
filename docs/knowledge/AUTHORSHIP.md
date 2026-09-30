# 素材署名：现状、影响与移除计划（2026-10-01）

**用户裁决**：理论不要自己写，要别人写的——专业的事情交给专业的人做。
这份文件把该裁决变成**可执行计划**：机器门在 `tools/knowledge/authorship_report.py`
（生成卡必须全部来自 `http(s)` 他人著作；`repo://` 出现即判失败）。

## 一、现状（实测）

```
1601 张生成卡 = 930 他人著作（全部 Project Gutenberg，1900–1920）＋ 671 自撰（本项目 23 篇笔记）
＋ 132 张手写策展卡（block_director/knowledge/cards_*.py，本项目的实现规则）
```

自撰占生成卡 **42%**，逐域：`axis_theory` 外部来源 **0 张**、anime 56/263、
cinematography 74/157、editing 55/127、storyboard 143/204、blocking 82/144、
production 67/113、composition 169/196、performance 284/308。

## 二、今天直接删会怎样（`work/_diag_removal_impact.py` 实测）

| 域 | 他人著作 | 自撰（拟删） | 删后占比 | K3 判定（每域 ≥60 且占比 ≥5%） |
|---|---|---|---|---|
| anime | 56 | 207 | 6.0% | **掉线（56 < 60）** |
| axis_theory | **0** | 89 | 0.0% | **掉线** |
| editing | 55 | 72 | 5.9% | **掉线（55 < 60）** |
| blocking | 82 | 62 | 8.8% | OK |
| cinematography | 74 | 83 | 8.0% | OK |
| composition | 169 | 27 | 18.2% | OK |
| performance | 284 | 24 | 30.5% | OK |
| production | 67 | 46 | 7.2% | OK |
| storyboard | 143 | 61 | 15.4% | OK |

另外：**529/4539 条** held-out 条目的 `from_card` 会变成幽灵卡（门⑥ 会如实判红），
`fixtures/knowledge_holdout.cards.json` 必须重生成，`work/glm_v1*/` 里那些卡的填写结果全部作废。

**结论：不能先删。顺序必须是"先补足他人来源，再删自撰"。**

## 三、执行顺序（每步都要能独立验收）

### 3.0 补齐三域的具体条目（已按管线自己的门验证过）

并行 lane 已把 `sources.yaml` 的自撰条目全部删掉，并补了 38 条他人来源
（36 条 Gutenberg ＋ 2 条 MIT OCW `CC-BY-NC-SA`），覆盖 8 个域——
**但 `anime` 一条没补、`axis_theory` 只补了 1 条**，而这两个域正是删后跌破 K3 的。
按 Gutenberg 官方目录（`cache/epub/feeds/pg_catalog.csv`，对镜像开放；检索页
`/ebooks/search` 被它自己的 robots 禁止，所以不用）筛出并逐本验证：

| 域 | 来源 | 体量 | 许可 |
|---|---|---|---|
| `axis_theory` | `https://www.gutenberg.org/cache/epub/53117/pg53117.txt`（*Motion Picture Directing: The Facts and Theories of the Newest Art*） | 229,677 字符 | PublicDomain |
| `axis_theory` | `https://www.gutenberg.org/cache/epub/13029/pg13029.txt`（*The Art of the Moving Picture*，Vachel Lindsay） | 365,279 字符 | PublicDomain |
| `anime` | **提高既有来源 `pg73455`（*Animated cartoons*）的 `chunk_budget`：20 → 40** | 1914 年那本，现有 56 张卡 | PublicDomain |

说明：Gutenberg 目录里**只有一本**真正讲动画的技术书（`Animated cartoons`，已收录；
其余命中"animat/cartoon"的要么是素描册、要么是科幻小说）。所以 `anime` 域靠
**把这本书的收录量提上去**（≥60 卡即可过 K3），而不是去找不存在的第二本。
更现代的动画理论若要补，只能走 arXiv/开放期刊，而 arXiv 的 PDF 抓取在本机
**时通时断**（同一条 URL 单发 7.1 秒成功、连发时大量 `WinError 10060`），
所以它只能作为"有则加、无则如实上报"的补充通道。

1. **补现代他人来源**（进行中）：arXiv 官方 API ＋ MIT OCW 讲义 PDF，按九域配额
   （每域 ≥3 条）；边界条件：三域至少要补到 `anime ≥60`、`axis_theory ≥60`、
   `editing ≥60`（含删后仍满足占比 ≥5%）。
   ```powershell
   python -m tools.kb_fetch.fetch          # 抓取（robots/scheme 门照旧）
   python -m tools.kb_fetch.extract_text   # 纯文本/HTML/PDF 三种介质
   python -m tools.kb_fetch.dedupe
   python -m tools.kb_fetch.validate_licenses
   python -m tools.kb_fetch.chunk
   python -m tools.kb_fetch.annotate --provider deepseek --incremental --workers 6
   python -m tools.kb_fetch.import_cards
   python -m tools.kb_fetch.build_hypergraph --provider deepseek --concurrency 6
   python -m tools.kb_fetch.vocabulary
   ```
2. **确认三域补足**：`python tools/knowledge/authorship_report.py --json ...` 看
   `per_domain`；同时 `tools/kb_fetch/import_cards.py` 的 K3 必须仍然 pass。
3. **移除自撰来源**：从 `knowledge/sources.yaml` 删掉 `mode: manual` 的 23 条
   （`repo://knowledge/source_notes/*.md`），**文件本体不删**（它们是设计文档，
   留在仓库里但**不再进语料**），然后重跑第 1 步的完整链。
4. **重生成 oracle 宇宙**：`python tools/holdout_merge.py --inputs "work/glm_v*/partial*.jsonl"`
   会自动丢掉幽灵卡；再对新增卡补一轮填写。
5. **验收**：`authorship_report` 必须 `passed: true`；`check_holdout` 的门①–⑪
   与 `run_tests.ps1`（31 项）全绿；`docs/knowledge/ACCEPTANCE_STATUS.md` 按新数字刷新。

## 四、手写策展卡（132 张）怎么算

它们是**本项目的实现规则**，不是理论素材：例如 `cine_shot_size` 对应
`block_director/cinema/framing.py::SHOT_FRAME`，`axis_180` 对应轴线控制器的
`R012`。处理方式：

* **保留在索引里**（它们是产品自己的硬约束，检索时有用），
* 但 `authorship_report` **单独计数**、不进"他人著作"分母，也不冒充理论；
* 若将来要求"语料里不许有任何本项目自己产出的东西"，再整体移出——那时
  九域每域仍要从外部来源补足 60 张，代价已经在第二节量化过了。
