# 会诊包（实际送进模型的逐字内容）

## system（角色：领域讲解）

```text
你是这个项目的外部顾问，当次扮演的角色是：**领域讲解**。

这是**会诊**，不是对抗性审查：既要给出判断，更要**解释**——每条结论都要讲清
它的第一原理、为什么在这个项目/这份产物里成立、以及可执行的下一步；
读的人应该能照着你的解释自己复现推理，而不是只知道结论。

硬规矩：
* 只依据 bundle 里**真实出现**的文字与数字说话；引用要逐字照抄（中文就照抄中文）。
* 不发明文件路径、行号、函数名、数字。看不到就写进 `not_checked`。
* 一条精确的结论胜过三条含糊的。
* `severity`：`blocker`（结论/实现是错的）、`major`（真缺陷，有绕法）、`minor`（文档/观感）。
* 只输出**一个 JSON 对象**，不要任何额外说明：
  {"summary": "<一段话>",
    "role": "领域讲解",
    "teaching": "<把这件事讲清楚：第一原理 → 在本项目里为什么成立 → 该怎么做>",
    "findings": [{"id": "F1", "severity": "blocker|major|minor",
                   "title": "<短标题>", "claim": "<结论是什么>",
                   "explanation": "<为什么：原理与在本项目里的落点，讲给能读代码的人>",
                   "where": "<bundle 里的原句/数字>",
                   "why_it_matters": "<后果>",
                   "suggested_check": "<用什么实验/命令可以定案>",
                   "step_by_step": ["<可执行的第 1 步>", "<第 2 步>"],
                   "confidence": "high|medium|low"}],
    "not_checked": ["<bundle 没让你判断的东西>"]}

把工艺与原理**讲清楚**：这个问题的第一原理是什么、真实片场怎么做、为什么在这个项目里成立；按『先原理、再落到这个代码库、最后给可执行步骤』的顺序解释，允许指出我们漏掉的信息。
```

## system（角色：实现顾问）

```text
你是这个项目的外部顾问，当次扮演的角色是：**实现顾问**。

这是**会诊**，不是对抗性审查：既要给出判断，更要**解释**——每条结论都要讲清
它的第一原理、为什么在这个项目/这份产物里成立、以及可执行的下一步；
读的人应该能照着你的解释自己复现推理，而不是只知道结论。

硬规矩：
* 只依据 bundle 里**真实出现**的文字与数字说话；引用要逐字照抄（中文就照抄中文）。
* 不发明文件路径、行号、函数名、数字。看不到就写进 `not_checked`。
* 一条精确的结论胜过三条含糊的。
* `severity`：`blocker`（结论/实现是错的）、`major`（真缺陷，有绕法）、`minor`（文档/观感）。
* 只输出**一个 JSON 对象**，不要任何额外说明：
  {"summary": "<一段话>",
    "role": "实现顾问",
    "teaching": "<把这件事讲清楚：第一原理 → 在本项目里为什么成立 → 该怎么做>",
    "findings": [{"id": "F1", "severity": "blocker|major|minor",
                   "title": "<短标题>", "claim": "<结论是什么>",
                   "explanation": "<为什么：原理与在本项目里的落点，讲给能读代码的人>",
                   "where": "<bundle 里的原句/数字>",
                   "why_it_matters": "<后果>",
                   "suggested_check": "<用什么实验/命令可以定案>",
                   "step_by_step": ["<可执行的第 1 步>", "<第 2 步>"],
                   "confidence": "high|medium|low"}],
    "not_checked": ["<bundle 没让你判断的东西>"]}

只谈**怎么落地**：给出改哪个文件/函数、改成什么形状、哪些既有测试会红、该怎么测；每一步都要说明**为什么**要这样改，以及不这样改会怎样。
```

## user（所有角色共用；角色 领域讲解 的包逐字如下）

```text
# 项目现状（自动注入；这是**事实**，不是问题的一部分，别把它当结论）
- 仓库：E:\白模预演codex
- HEAD：f6530c6 docs(P14-319): 出处缺口的 90 槽位分层抽检——样本(闭环三 kind 30 + 三 pack 各 20，互不重叠可复现)＋机械预读(topic_mismatch 88/90)＋12 批三分类作业已起
- 最近提交（`git log --oneline -5`）：
    f6530c6 docs(P14-319): 出处缺口的 90 槽位分层抽检——样本(闭环三 kind 30 + 三 pack 各 20，互不重叠可复现)＋机械预读(topic_mismatch 88/90)＋12 批三分类作业已起
    013d516 docs(P14-318): 出处缺口的裁定——转入修复但只做局部手术(先修闭环那几条边、不按体量排 pack)；机械判据：9 条边/15 槽位里 topic_mismatch 14；并写清删边=索引换代(23 份运行 pin 全失配)
    7a73ef7 docs(P14-317): 把更新后的全扫产物(23 次运行，含两次真跑)一并入库——上一条提交只带了 README 与台账
    6e1bf52 feat(P14-317): 第二次真跑(两栏都落地)——movement 真的在比了(空 294->0，matched 268)、生效边 1->30；另修工具里 for...else 误用导致的 no_match 假计数
    fd499c9 feat(P14-316): declared.camera_move 落字段——movement 一族从 没得比 变成 能比(空 294/300 -> 0，matched 267)
- 未提交改动（`git status --porcelain`）：
    M AGENTS.md
     M CONTEXT.md
     M block_director/cinema/anchor.py
     M block_director/cinema/station.py
     M block_director/contracts/audit.py
     M block_director/contracts/config.py
     M block_director/contracts/messages.py
     M block_director/contracts/plan.py
     M block_director/contracts/sdl.py
     M block_director/delivery/manifest.py
     M block_director/knowledge/client.py
     M block_director/knowledge/hypergraph.py
     M block_director/knowledge/retriever.py
     M block_director/layer2_sdl/sdl_builder.py
     M block_director/layer2_sdl/sdl_migrate.py
     M block_director/layer3_engine/scene_executor.py
     M block_director/layer3_engine/shot_auditor.py
     M block_director/layer3_engine/shot_builder.py
     M block_director/layer5_orchestrator/driver.py
     M block_director/layer5_orchestrator/editor.py
     M block_director/layer5_orchestrator/headless_runner.py
     M block_director/layer5_orchestrator/modal_operator.py
     M block_director/layer5_orchestrator/planner.py
     M block_director/layer5_orchestrator/scene_contract.py
     M block_director/layer7_ui/panel_shots.py
     M block_director/motion/model.py
     M docs/evidence/2026
…[现状摘要已按 --status-chars 截断；完整文本的字数与 sha256 记在 bundle.manifest.json]

# 本次要审的问题

# 问题：一次"换卡"换代后，门⑥ 红了（11 张卡变成"有边却没有 held-out 条目"）

## 背景（都是实测读数，不是推测）

BlockDirector 的知识索引有三层：2353 张卡（`knowledge/cards_generated/*.jsonl` ＋
`block_director/knowledge/corpus.py::HANDWRITTEN_CARDS` 里的 132 张手写策展卡）→
超图边（`knowledge/hypergraph.edges.jsonl`，638 条，`edge.members[]` 是 `[角色, kind, 节点]`
三元组、`edge.sources[]` 是"谁为这些成员担保"的卡 id）→ held-out 冻结夹具
（`fixtures/knowledge_holdout.jsonl`，每条有 `from_card`）。

**已获用户明示批准的换代**（`docs/knowledge/REGEN_LOG_20261007_rotation.md`）只做了一件事：
机械重绑（`tools/kb_fetch/rebind.py`，代号「换卡」）。它把"未被来源佐证"的成员
（`tools/knowledge/attestation.py::label_for`：取值的 surface 在**这条边自己的**来源卡正文里找不到）
**追加**候选卡（正文里真的写了该 surface 的卡，每成员最多 3 张，**union-add、不删原来源**）。

实测对拍 HEAD 与现行索引（`work/_audit_rebind_diff.py` 的输出就是下面这些数）：

```
edges old/new 638 638
pre-rebind edge-backed cards 2262
distinct added sources 263 total added 2937
distinct removed 0 total removed 0
edges differing beyond sources: 0
changed edges: 560
added sources NOT in pre-rebind edge-backed set: 11
{cine_move_index:36, cine_move_pan_right:14, gen_cine_0378:10, gen_cine_0377:4,
 cine_move_track_left:5, cine_move_pan_left:3, gen_block_0005:3, gen_block_0297:3,
 gen_block_0086:2, cine_move_tilt_down:2, comp_lead_room:11}
```

## 红在哪

`tools/kb_fetch/card_scope_audit.py::audit` 算的门⑥ 分母 = **可断言卡**（判据原文在模块
`CRITERION`，`scope/v3`）：`excluded ⟺ 全语料抽取对该卡零条边（sources 不含该 id）`；
它同时算一个"诚实计数" `edge_backed_without_entry` = 有边、但 held-out 里没有条目的卡。

```
HEAD : catalogue 2353, edge_backed 2262, excluded 91, edge_backed_without_entry 0
现行 : catalogue 2353, edge_backed 2273, excluded 80, edge_backed_without_entry 11
```

也就是说：重绑把 11 张**本来零边**的卡（6 张手写策展卡 ＋ 5 张生成卡）变成了"有边的卡"，
而它们在 held-out 里没有条目 ⇒ 门⑥ 判红（`overall: fail`）。

注意：`work/_verify_rebind_reproduces.py` 已证明"现行索引 = 换代前备份 ＋ 写下来的那条确定性规则"
（逐字节复现，`reproduces_promoted_index: true`），所以这不是手工编辑，是一条规则的副作用。

## 我自己想到的三条候选（请你判断，也可以给第四条）

- **A（收窄候选池）**：重绑的候选只从"**重绑前就已经有边**的卡"里选（对现行状态，
  这个集合 2262 与"held-out 里有条目的卡"等价）。理由：重绑的职责是修**担保关系**，
  不是**扩大可断言面**；后者会让 11 张卡凭空欠一条 held-out 条目，而 held-out 是冻结仪器。
  代价：93/2937 条追加来源（11 张卡贡献的那些）不再产生 ⇒ 可能有槽位从"可重绑"掉回"零候选"。
- **B（给这 11 张卡补 held-out 条目）**：保持候选池不变，扩 held-out 夹具覆盖这 11 张。
  代价：held-out 是**冻结仪器**（门①–⑩、Q1–Q7、第三方层、generations 都钉着它的 sha256），
  扩条目＝夹具换代，且需要重新标注这 11 张的 `must` 条目。
- **C（不动索引，改判据）**：把门⑥ 的分母/口径改成允许"有边没条目"。**我认定这条违规**
  （R-5：判据/门限一个字不许动），列出来只是要你确认它确实不该选。

## 连带 fallout（同一次换代的第二组问题）

换代让索引指纹 `c796a5a8…` → `00ea933ed11c…`（9 格缓存键里第 9 格是 `rebind_version`），
于是**已入库的真实运行证据**（`docs/evidence/20261003_real_glm`、`20261003_real_ds`、
`20261003_real_long`、`20261006-long21`）被如实判成"另一代索引跑的"。现行 pytest 里
7 条用例要求这些证据**同代**：

```
FAILED tests/test_extract_run_evidence.py::test_the_landed_real_run_evidence_is_fresh
FAILED tests/test_extract_run_evidence.py::test_the_second_landed_run_is_fresh_and_has_no_contract_warning
FAILED tests/test_extract_run_evidence.py::test_the_long_real_run_is_fresh_and_stayed_within_the_ceiling
FAILED tests/test_evidence_digest_is_checkout_independent.py::test_a_landed_run_still_checks_out_after_an_lf_checkout[20261003_real_glm]
FAILED tests/test_evidence_digest_is_checkout_independent.py::test_a_landed_run_still_checks_out_after_an_lf_checkout[20261003_real_ds]
FAILED tests/test_evidence_digest_is_checkout_independent.py::test_a_landed_run_still_checks_out_after_an_lf_checkout[20261003_real_long]
FAILED tests/test_q5_audit_channel.py::test_the_committed_real_run_drift_is_reproducible
（断言原文：`['索引指纹不符（证据 c796a5a87018… vs 现行 00ea933ed11c…）：这份运行不是这一代索引跑的']`）
```

`tools/extract_run_evidence.py::check()` 的第 396 行就是那条判据；`REGEN_LOG` §5 写的是
"换代后 pin **一律如实标异代**，**不许 repin 洗白**；需要哪一份运行继续被引用，就**重跑那一份**"。
但仓库里还有一条既有先例：`tests/test_q5_audit_channel.py::test_the_committed_real_run_drift_is_reproducible`
的注释（2026-10-06）说"**证据跟着最近一次真跑走**，判据一个字不动"——它是把这条用例换到
最近一次真跑上，而不是重跑旧的。

## 请你回答（按这个顺序，每条都要可证伪）

1. **根因判定对不对**：门⑥ 红是因为"重绑扩大了可断言面"，还是我在别处把话说错了？
   给出你认为的根因，以及你据以判断的**文件:行号**。
2. **A / B / 其它**：在不改任何判据/门限/阈值（R-5）、不删测试不放宽断言的前提下，
   哪一个才是"知识没有被削、也没有把噪声洗绿"的正解？如果你有第四条形状，请写出来。
   若选 A，请说清"候选池"到底该定义成什么（重绑前有边的卡？held-out 里有条目的卡？
   还是别的可观测量），以及为什么这个定义不是"静默降级"。
3. **选 A 会不会静默削弱修复效果**：重绑的验收读数是 **C1 同口径复判**（90 槽位三分类，
   判官 `qwen3.8-max-0902`，`corrupt = 67/90 → 37/90`），不是 `attestation` 本身
   （后者与候选判据同源、会构造性满足）。收窄候选池之后，这条读数要**怎么重测**才算数？
   如果你认为收窄会让 `corrupt_share` 回升，请说出可证伪的检查方法。
4. **那 7 条"异代"用例的处置**：在 R-8（换代须知登记、不 repin）与"证据跟着最近一次真跑走"
   这两条之间，正确的落法是什么？是"重跑那 4 份运行"、"把用例指向新一代的真跑"、
   还是别的？请给出与仓库既有机制（`resolve_generation` / `fixtures/knowledge_holdout.generations.json`
   / `--check` 的 reasons）一致的落法，并说清**哪些断言一个字都不能动**。
5. **缺口与风险**：这套改法还会在哪一步翻车？列 3 条，并给每条一个"如果 X 就说明我错了"的判据。


## 源码：tools/kb_fetch/rebind.py（第 1–86 行，逐字，带行号）

```
    1| """卡↔槽位绑定的**机械重绑**（user 2026-10-07 批准，代号「换卡」）。
    2| 
    3| 问题（实测）：1,262 个"未被来源佐证"的槽位里 **84.2%** 的取值**确实写在别的卡正文里**
    4| ——错的是**担保关系**（这条边引用了不写这个取值的卡），不是知识本身。
    5| qwen3.8-max-0902 三角色会诊一致指出：把这种事交给"同一抽取器再抽一遍"是**重新掷骰子**
    6| （条件分布不变 ⇒ 分布不变），真正确定性的修法是**机械重绑**。
    7| 
    8| 规则（**确定性、可复现**，与影子实验逐字同一条）：
    9| 
   10| 1. 对每个**未被佐证**的成员（`attestation.label_for` 的口径：取值的 surface 在这条边
   11|    **自己的来源卡**正文里找不到）；
   12| 2. 在**全库**（`cards_generated/*.jsonl` ＋ `HANDWRITTEN_CARDS`，按加载顺序）里找
   13|    **正文真的写了**该 surface 的卡；
   14| 3. 取前 `PER_MEMBER_CANDIDATES`（3）张，**追加**进这条边的 `sources[]`（**不删原来源**，
   15|    所以边的出处没有被抹掉，改动可回滚）；
   16| 4. 只在**确实找不到**候选时才留原样（那种情况重绑也修不了，属另一类问题）。
   17| 
   18| **它不是判据**：不改 `attestation` 的口径、不改任何门限；它只决定"哪几张卡为这条成员担保"。
   19| 效果以 **C1 同口径复判** 为准（实测 `corrupt 67/90 → 37/90`），不是以 attestation 为准
   20| ——后者与候选判据同源，会**构造性**满足。
   21| """
   22| 
   23| from __future__ import annotations
   24| 
   25| from typing import Any, Dict, List, Sequence, Tuple
   26| 
   27| #: 规则版本。它**进 `CACHE_KEY_FIELDS`**：改了重绑规则必须让索引指纹跟着变，
   28| #: 否则同一条缓存键会同时指向"重绑前"和"重绑后"两份不同的索引。
   29| REBIND_VERSION = "rebind/v1"
   30| 
   31| #: 每个成员最多追加几张候选卡。
   32| PER_MEMBER_CANDIDATES = 3
   33| 
   34| 
   35| def candidate_cards(forms: Sequence[str], blobs: Dict[str, str],
   36|                     limit: int = PER_MEMBER_CANDIDATES) -> List[str]:
   37|     """正文里真的写了这些 surface 之一的卡 id（按 `blobs` 的顺序，取前 `limit` 张）。"""
   38|     wanted = [form for form in forms if form]
   39|     if not wanted:
   40|         return []
   41|     found: List[str] = []
   42|     for card_id, blob in blobs.items():
   43|         if any(form in blob for form in wanted):
   44|             found.append(str(card_id))
   45|             if len(found) >= limit:
   46|                 break
   47|     return found
   48| 
   49| 
   50| def rebind_edges(edges: Sequence[dict], blobs: Dict[str, str],
   51|                  labels: Any, surfaces: Any) -> Tuple[List[dict], Dict[str, Any]]:
   52|     """按上面的规则重绑；返回 ``(新边表, 统计)``。纯函数、确定性。
   53| 
   54|     `labels` 是 ``(edge, member) -> "attested"|"unattested"|"not-checkable"`` 的判定函数，
   55|     `surfaces` 是 ``member_node_id -> [surface, ...]``——两者都由调用方注入，
   56|     这样本模块不依赖 `attestation`（避免与判据形成环形依赖）。
   57|     """
   58|     out: List[dict] = []
   59|     touched = added = 0
   60|     no_candidate = 0
   61|     for edge in edges:
   62|         record = dict(edge)
   63|         sources = list(record.get("sources") or [])
   64|         extra: List[str] = []
   65|         members_rebound: List[str] = []
   66|         for member in record.get("members") or []:
   67|             if labels(record, member) != "unattested":
   68|                 continue
   69|             key = str(member[2])
   70|             candidates = candidate_cards(surfaces(key), blobs)
   71|             if not candidates:
   72|                 no_candidate += 1
   73|                 continue
   74|             picked = [cid for cid in candidates
   75|                       if cid not in sources and cid not in extra]
   76|             if picked:
   77|                 extra.extend(picked)
   78|                 members_rebound.append(key)
   79|         if extra:
   80|             record["sources"] = sources + extra
   81|             touched += 1
   82|             added += len(extra)
   83|         out.append(record)
   84|     return out, {"rebind_version": REBIND_VERSION, "edges": len(out),
   85|                  "edges_touched": touched, "sources_added": added,
   86|                  "members_without_candidate": no_candidate}
```

## 源码：tools/kb_fetch/build_hypergraph.py（第 1612–1690 行，逐字，带行号）

```
 1612| def _apply_rebind(edges: Sequence[hg.HyperEdge], cards: Sequence[Dict],
 1613|                   node_index: Dict[str, Any]):
 1614|     """机械重绑的接线层：dict 形状交给 `rebind.rebind_edges`，再变回 `HyperEdge`。
 1615| 
 1616|     为什么参数化 `labels`/`surfaces`：`rebind.py` 不依赖 `attestation`（避免与判据成环），
 1617|     判据与 surface 一律由这里注入——**判据只有一个**（`attestation.label_for`）。
 1618|     """
 1619|     from tools.knowledge import attestation as att
 1620|     from tools.kb_fetch import rebind as _rebind
 1621| 
 1622|     card_map = {str(card.get("id")): card for card in cards}
 1623|     #: 手写卡也在语料里（它们本来就该为取值担保）。
 1624|     try:
 1625|         from block_director.knowledge.corpus import HANDWRITTEN_CARDS
 1626| 
 1627|         for card in HANDWRITTEN_CARDS:
 1628|             payload = card if isinstance(card, dict) else card.__dict__
 1629|             cid = str(payload.get("id") or "")
 1630|             if cid and cid not in card_map:
 1631|                 card_map[cid] = payload
 1632|     except Exception:  # noqa: BLE001 - 手写卡不可用时不放大改动面
 1633|         pass
 1634|     blobs = {cid: att.card_blob(card) for cid, card in card_map.items()}
 1635| 
 1636|     def labels(edge, member):
 1637|         own = "".join(" " + blobs[str(s)] for s in (edge.get("sources") or [])
 1638|                       if str(s) in blobs)
 1639|         return att.label_for(node_index.get(str(member[2])), own)
 1640| 
 1641|     def surfaces(node_id):
 1642|         node = node_index.get(str(node_id))
 1643|         return node_surfaces(node) if node is not None else []
 1644| 
 1645|     rebound, stats = _rebind.rebind_edges(
 1646|         [edge.to_dict() for edge in edges], blobs, labels, surfaces)
 1647|     return [hg.HyperEdge.from_dict(item) for item in rebound], stats
 1648| 
 1649| 
 1650| def _write_index(cards: Sequence[Dict], atoms: Sequence[hg.HyperEdge],
 1651|                  rejects: Sequence[Dict], batch_log: Sequence[Dict], *,
 1652|                  extractor: Dict[str, str], cache_key: Dict[str, str],
 1653|                  fingerprint: str, merged, merge_report: Dict,
 1654|                  units: Sequence[Dict] = (),
 1655|                  cache_enabled: bool = True) -> Dict:
 1656|     """第 1 段产物之后的公共收尾：归并 → 9 条门 → 落盘 → manifest。"""
 1657|     processed, total = chunk_counts(cards, batch_log, atoms)
 1658|     gate_rejects: List[Dict] = []
 1659|     node_index = nodes_from_vocab()
 1660|     unique, report = hg.build_index(merged, node_index,
 1661|                                     processed_chunks=processed, total_chunks=total,
 1662|                                     reject_sink=gate_rejects)
 1663|     #: **机械重绑（rebind/v1，user 2026-10-07 批准代号「换卡」）**：把"未被来源佐证"的
 1664|     #: 成员补上**正文真的写了**该取值的候选卡（union-add，不删原来源）。理由与实测见
 1665|     #: `tools/kb_fetch/rebind.py`：1,262 个未佐证槽位里 84.2% 是**绑错卡**而不是卡里没知识；
 1666|     #: 同一抽取器重抽是"重新掷骰子"（qwen3.8-max-0902 三角色会诊一致结论）。
 1667|     #: 效果以 **C1 同口径复判**为准（实测 corrupt 67/90 → 37/90），不以 attestation 为准。
 1668|     unique, rebind_report = _apply_rebind(unique, cards, node_index)
 1669|     merge_rejects = [{"phase": "merge", "reason": item["reason"],
 1670|                       "edge_ids": item["edge_ids"]}
 1671|                      for item in merge_report["dropped_groups"]]
 1672|     # `merge` 段里"这条索引到底有多少禁忌/最大 arity"必须描述**写出去的**那批边，
 1673|     # 不是去重校验之前的候选（否则 manifest 与 `hypergraph.edges.jsonl` 对不上，
 1674|     # 而 §4.1b 硬规则 2 禁止自报一个对不上的汇总）。候选口径另存 `before_dedupe`。
 1675|     merge_report = dict(merge_report)
 1676|     merge_report["before_dedupe"] = {
 1677|         "merged_edges": merge_report["merged_edges"],
 1678|         "forbid_members": merge_report["forbid_members"],
 1679|         "max_arity": merge_report["max_arity"],
 1680|     }
 1681|     merge_report["merged_edges"] = len(unique)
 1682|     merge_report["forbid_members"] = sum(len(edge.forbids) for edge in unique)
 1683|     merge_report["max_arity"] = max((len(edge.members) for edge in unique), default=0)
 1684|     repairs = sum(int((edge.extractor or {}).get("dropped_members", 0) or 0) for edge in unique)
 1685|     merge_report["dangling_members_dropped"] = repairs
 1686|     common.write_jsonl(EDGES, [edge.to_dict() for edge in unique])
 1687|     # 边级拒收 → 与 manifest.rejects 一一对应；原子级/归并级 → 另一个文件（工作区）。
 1688|     common.write_jsonl(REJECTS, gate_rejects)
 1689|     common.write_jsonl(ATOM_REJECTS, list(rejects) + merge_rejects)
 1690|     common.dump_json(REPORT, {**report.to_dict(), "merge": merge_report,
```

## 源码：tools/kb_fetch/build_hypergraph.py（第 245–320 行，逐字，带行号）

```
  245| #: 第七个是同一行里写的"＋ 校验门代码版本"，第八个是**词表/别名表**本身
  246| #: （§0.1b 的缓存指纹行；生产者 `vocabulary.lexicon_fingerprint()`）。
  247| #: 第八个为什么必须存在：别名表是**落地判据的输入**，改它就会改索引，而改的人
  248| #: 不会想起去换版本号——实测（`ACCEPTANCE_STATUS.md` §20.4）给 `EMOTIONS` 补一个
  249| #: 别名就让索引从 540 变 539 条边，前七个分量**一个都不动**。
  250| CACHE_KEY_FIELDS = ("corpus_sha256", "model", "prompt_version",
  251|                     "chunker_version", "decode", "schema_version",
  252|                     "validation_rules_version", "vocabulary_fingerprint",
  253|                     #: **第九格（2026-10-07 加）**：机械重绑（`rebind/v1`）的版本。
  254|                     #: 重绑**改的是边的内容**（`sources[]`），但**不改任何输入**——
  255|                     #: 没有这一格，"重绑前"与"重绑后"两份不同的索引会共用同一枚指纹
  256|                     #: （正是本模块 docstring 里点名要防的那个洞）。加它之后，
  257|                     #: 22 份已入库运行的 `pins.index` 会**如实**变成"异代"。
  258|                     "rebind_version")
  259| 
  260| 
  261| def corpus_digest(cards: Sequence[Dict]) -> str:
  262|     """语料指纹：卡片 id ＋ chunk ＋ 源文档 sha256 ＋ 正文 sha256，按字典序拼后取 sha256。
  263| 
  264|     只拿 id 列表去哈希是不够的：**同样的 id、改过的正文**必须让指纹变（否则缓存会
  265|     拿旧索引当新语料的产物）。源文档 sha256 与正文 sha256 同时计入，正是为此。
  266|     """
  267|     rows = []
  268|     for card in cards:
  269|         span = card.get("source_span") or {}
  270|         rows.append([
  271|             str(card.get("id", "")),
  272|             str(card.get("chunk_id") or span.get("chunk_id") or ""),
  273|             str((card.get("source_ref") or {}).get("sha256", "")),
  274|             common.sha256_text(str(card.get("content", ""))),
  275|         ])
  276|     rows.sort()
  277|     payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
  278|     return hashlib.sha256(payload.encode("utf-8")).hexdigest()
  279| 
  280| 
  281| def fingerprint_components(cards: Sequence[Dict], client, *,
  282|                            prompt_version: str = PROMPT_VERSION,
  283|                            validation_rules_version: str = VALIDATION_RULES_VERSION,
  284|                            decode: str = DECODE,
  285|                            chunker_version: str = "",
  286|                            schema_version: str = "",
  287|                            vocabulary_fingerprint: str = "") -> Dict[str, str]:
  288|     """把指纹的分量算出来（`cache_key` 的**唯一**生产者）。"""
  289|     return {
  290|         "corpus_sha256": corpus_digest(cards),
  291|         "model": f"{client.model_id}@{getattr(client, 'model_version', '')}",
  292|         "prompt_version": str(prompt_version),
  293|         "chunker_version": str(chunker_version or common.CHUNKER_VERSION),
  294|         "decode": str(decode),
  295|         #: **现算**，不从调用方/manifest 读回来——与第八格（词表指纹）同一纪律：
  296|         #: 往闭集里加一个 qualifier（`seq_phase`／`carry_shots` 那一类）必须**自动**
  297|         #: 让指纹变，否则断点续跑命中旧批次、新槽位从未被抽取而一切照绿。
  298|         "schema_version": str(schema_version or hg.schema_version_with_fingerprint()),
  299|         "validation_rules_version": str(validation_rules_version),
  300|         "vocabulary_fingerprint": str(vocabulary_fingerprint
  301|                                       or vocabulary.lexicon_fingerprint()),
  302|         #: 第九格：机械重绑的规则版本（`rebind/v1`）。语义见 `CACHE_KEY_FIELDS` 的注释。
  303|         "rebind_version": str(rebind.REBIND_VERSION),
  304|     }
  305| 
  306| 
  307| def fingerprint_of(components: Dict) -> str:
  308|     """缓存指纹：对**恰好 `CACHE_KEY_FIELDS` 这些**分量做规范化 JSON 哈希。
  309| 
  310|     键集不对就报错（不是忽略多余键）：这是"加了新分量却没进哈希"的机械防线。
  311|     """
  312|     keys = set(components)
  313|     expected = set(CACHE_KEY_FIELDS)
  314|     if keys != expected:
  315|         raise ValueError(f"缓存指纹的分量不匹配：多 {sorted(keys - expected)} / "
  316|                          f"少 {sorted(expected - keys)}")
  317|     payload = json.dumps({key: str(components[key]) for key in CACHE_KEY_FIELDS},
  318|                          ensure_ascii=False, sort_keys=True, separators=(",", ":"))
  319|     return hashlib.sha256(payload.encode("utf-8")).hexdigest()
  320| 
```

## 源码：tools/kb_fetch/card_scope_audit.py（第 210–243 行，逐字，带行号）

```
  210|     import random
  211| 
  212|     pool = sorted((set(cards) - set(wanted)) & set(covered))
  213|     random.Random(seed).shuffle(pool)
  214|     return pool[:count]
  215| 
  216| 
  217| def audit(cards: Dict[str, Dict], edge_counts: Dict[str, int], *,
  218|           covered: Sequence[str]) -> Dict:
  219|     """确定性判据。**不调模型、不读 oracle 内容**。"""
  220|     names = sorted(cards)
  221|     excluded = [ident for ident in names if int(edge_counts.get(ident, 0)) == 0]
  222|     edge_backed = [ident for ident in names
  223|                    if int(edge_counts.get(ident, 0)) > 0]
  224|     used = set(str(item) for item in covered)
  225|     gap = [ident for ident in edge_backed if ident not in used]
  226|     return {
  227|         "criterion": CRITERION, "criterion_version": CRITERION_VERSION,
  228|         "rule": "excluded ⟺ 全语料抽取对该卡零条边（sources 不含该 id）",
  229|         "catalogue": len(names), "edge_backed": len(edge_backed),
  230|         "excluded": excluded, "excluded_count": len(excluded),
  231|         #: 兼容旧读取方（`check_holdout --exclude-cards` 两个键都认）。
  232|         "out_of_scope": excluded, "out_of_scope_count": len(excluded),
  233|         #: 不变量：被剔的卡**不许**在索引里有边（否则就是剔掉了能断言的知识）。
  234|         "excluded_with_edges": sorted(
  235|             ident for ident in excluded if int(edge_counts.get(ident, 0)) > 0),
  236|         #: 诚实计数：被剔的卡里已有条目的（多出来的覆盖，不是损失）。
  237|         "excluded_with_entries": sorted(ident for ident in excluded if ident in used),
  238|         #: 门⑥ 真正在测的东西：可断言卡里还缺条目的（**必须补标注**）。
  239|         "edge_backed_without_entry": gap, "edge_backed_without_entry_count": len(gap),
  240|         "edges_per_card": {ident: int(edge_counts.get(ident, 0)) for ident in names},
  241|     }
  242| 
  243| 
```

## 源码：tools/knowledge/attestation.py（第 78–90 行，逐字，带行号）

```
   78| def card_blob(card: dict) -> str:
   79|     return " ".join([str(card.get("title", "")), str(card.get("content", "")),
   80|                      " ".join(map(str, card.get("keywords") or [])),
   81|                      " ".join(map(str, card.get("tags") or []))])
   82| 
   83| 
   84| def label_for(node, blob: str) -> str:
   85|     """一个槽位在这条边的来源正文里算不算"有依据"（见模块 docstring 的口径）。"""
   86|     forms = node_surfaces(node) if node is not None else []
   87|     if not forms:
   88|         return NOT_CHECKABLE
   89|     return ATTESTED if any(form in blob for form in forms) else UNATTESTED
   90| 
```

## 源码：tools/extract_run_evidence.py（第 362–407 行，逐字，带行号）

```
  362| def check(*, out_dir: Path, holdout: Path, index_manifest: Path,
  363|           with_warnings: bool = False):
  364|     """复算分片与 pins；返回**不能用的理由**（空列表 = 证据齐且同代）。
  365| 
  366|     ``with_warnings=True`` 时返回 ``(reasons, warnings)``：`warnings` 是**不影响
  367|     同代性**但必须如实记账的契约对拍（当前只有 `retrieval_calls` 一条，见
  368|     :func:`retrieval_cross_checks`）。默认仍只返回 reasons，改动对既有调用点透明。
  369|     """
  370|     out_dir = Path(out_dir)
  371|     manifest_path = out_dir / MANIFEST_NAME
  372|     if not manifest_path.is_file():
  373|         reasons = [f"缺 {manifest_path}：这份证据没有来源说明"]
  374|         return (reasons, []) if with_warnings else reasons
  375|     manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
  376|     reasons: List[str] = []
  377|     for name, item in (manifest.get("artifacts") or {}).items():
  378|         target = out_dir / str(item.get("path") or name)
  379|         if not target.is_file():
  380|             reasons.append(f"缺分片 {name}（{target}）")
  381|             continue
  382|         if item.get("sha256") and sha256_file(target) != item["sha256"]:
  383|             reasons.append(f"{name} 的 sha256 与 manifest 不符：分片被改过或重放过")
  384|     pins = manifest.get("pins") or {}
  385|     pinned_holdout = ((pins.get("holdout") or {}).get("sha256") or "")
  386|     if not pinned_holdout:
  387|         reasons.append("manifest 没钉 held-out 的 sha256")
  388|     elif pinned_holdout != sha256_file(Path(holdout)):
  389|         reasons.append("held-out oracle 已换代：这份运行证据不是当前那一份 oracle 的")
  390|     from block_director.knowledge.hypergraph import (
  391|         manifest_fingerprint as hypergraph_fp,
  392|     )
  393| 
  394|     pinned_index = ((pins.get("index") or {}).get("fingerprint") or "")
  395|     live_index = hypergraph_fp(Path(index_manifest).parent)
  396|     if not pinned_index or pinned_index != live_index:
  397|         reasons.append(f"索引指纹不符（证据 {pinned_index[:12]}… vs 现行 "
  398|                        f"{live_index[:12]}…）：这份运行不是这一代索引跑的")
  399|     #: 换代登记：**每份运行都要解析到已登记代**（裁决给的最小跳）。历史运行 pin 的
  400|     #: 只是夹具 ⇒ 落在 gen1；新运行 pin 了夹具＋第三方层 ⇒ 落在 gen2。
  401|     #: 解析不到（例如 pin 了没登记过的输入）就如实报，**不猜**。
  402|     generation, why = resolve_generation(pins, ROOT / GENERATIONS_NAME)
  403|     if generation is None:
  404|         reasons.append("这份运行没有对应的已登记代：" + why)
  405|     if not with_warnings:
  406|         return reasons
  407|     return reasons, retrieval_cross_checks(out_dir)
```

## 源码：docs/knowledge/REGEN_LOG_20261007_rotation.md（第 1–69 行，逐字，带行号）

```
    1| # 换代登记 · 2026-10-07：卡↔槽位绑定清洗（用户裁决「换吧」）
    2| 
    3| **性质**：**已获用户明示批准的换代**（R-8 要求的显式登记）。
    4| **触发**：用户 2026-10-07 对两个 ⚖️ 项同时答复「**换吧**」：
    5| ① `P5-T2`（要不要换代）② `C2`（9 条边选「**换卡**」而不是删边）。
    6| **方法**：沿用 `build_hypergraph.py --replace-cards`（工具自带、且其 docstring 里
    7| 就有同形先例：v6 把概念名词写进动作槽位、横跨 329 张卡，用的就是这条清洗路径）。
    8| 
    9| ---
   10| 
   11| ## §1 换代原因（实测证据，不是拍脑袋）
   12| 
   13| 1. **C1 三分类（90 槽位分层样本，已完成）**：
   14|    `corrupt = 67/90 = 0.7444` → `corrupt-dominated`；四个分层**一致**（0.65–0.80）
   15|    ⇒ 按裁定口径（≥33% 且模式一致）「**暂缓重抽**」被证伪。
   16|    证据：`docs/evidence/20261007-grounding-sample90/三分类汇总.json`
   17| 2. **C2 机械判据（9 边 / 15 槽位）**：旧尺子 `topic_mismatch 14 / matches 1`，
   18|    新尺子 `topic_mismatch 6 / topic 或域与 kind 相符 2 / topic 未知 6 / 正文里真的有 1`。
   19|    每条都带 `candidate_cards`（正文里真的写了该取值的**候选卡**）。
   20|    证据：`docs/evidence/_v15_stage8/c2_edge_surgery/edges.json`
   21| 3. **C3**：`topic` 是**来源级**标签、对卡级判定零分辨率 ⇒ 判「挂错卡」必须回到**卡正文**
   22|    （机械预读的 88/90 不能当判决）。
   23| 
   24| ## §2 影响面（要动什么、不动什么）
   25| 
   26| | 项 | 内容 |
   27| |---|---|
   28| | **动** | `knowledge/hypergraph.{nodes,edges}.jsonl`（重建）、`hypergraph.manifest.json`、`work/hypergraph.atoms.jsonl`（原子边） |
   29| | **不动** | **判据／阈值／门限**（R-5）；**held-out 夹具**与第三方层（门⑦ 的输入，字节不动）；`hypergraph.py` 的槽位闭集 |
   30| | **目标卡集** | **277 张**（`work/_rotation_replace_cards.txt`）：C2 的 65 张错卡 ＋ 21 张候选卡 ∪ C1 的 194 张来源卡 |
   31| | **重抽量** | 覆盖 **180 / 708 chunk**（25%）——其余 528 chunk 走**原子边缓存**，逐字节不变 |
   32| | **抽取模型** | **`qwen3.8-max-0902`**（用户 2026-10-07 指示"派发给 qwen3.8max0902，让他完成所有任务"）；`reasoning_effort = max`（用户："新模型思考强度拉到最大"） |
   33| 
   34| ## §3 前后指纹（**前指纹＝实测**，后指纹待重建后填）
   35| 
   36| ```
   37| schema_fingerprint            1a90c089bb8f4f7fbd61a145a2088d6c2628ecbbd4dba47f63396fbf34fadaf3
   38| manifest_fingerprint(前)      c796a5a87018631db54da88406a4bd352741ed346fa1e9b06293c85ef46fed67
   39| hypergraph.nodes.jsonl   sha 789c0625ad6c6f65…    hypergraph.edges.jsonl  sha 0597326a9d300137…
   40| hypergraph.manifest.json sha d0613eb498f91371…    work/hypergraph.atoms.jsonl sha 5cd8cf67680a3ff9…
   41| corpus(fetched.jsonl)    sha 46401b5627df74e9…    vocab.json sha a295f3ef5a1e24a7…
   42| ```
   43| 
   44| **前指纹的完整备份**：`work/_pre_rotation_20261007-154410/`（6 份产物，可回滚/对拍）。
   45| > `work/` 是 `.gitignore` 掉的草稿区 ⇒ 备份**不进库**；索引本体在 `knowledge/`（进库）。
   46| 
   47| ## §4 最小重跑集（换代后必须重跑的）
   48| 
   49| | # | 门／读数 | 命令 |
   50| |---|---|---|
   51| | 1 | 门①–⑩（含门⑦ 两代口径） | `python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab fixtures/knowledge_holdout.vocab.json --cards fixtures/knowledge_holdout.cards.json …` |
   52| | 2 | Q1–Q7（held-out） | `python tools/holdout_score.py --holdout fixtures/knowledge_holdout.jsonl --json <out>` |
   53| | 3 | Q0 / E1–E3 | `python tools/knowledge/quality.py …` ＋ `python tools/knowledge/hard_gates.py …` |
   54| | 4 | 全链 | `powershell -File tools/run_tests.ps1`（含 pytest ＋ 31 支探针） |
   55| | 5 | **C1 复测（同口径）** | 重跑 90 槽位三分类，看 `corrupt_share` 是否下降（**判据不变**） |
   56| 
   57| ## §5 pin 处置（**不许 repin 洗白**）
   58| 
   59| * 已入库运行把 `pins.index`（索引指纹）钉进 `run_manifest.json`；
   60| * 换代后这些 pin **会失配** ⇒ 一律**如实标「异代」**，**不** `repin()`（它会拒）；
   61| * 实测：带 `holdout` pin 的运行 **22 份**（`docs/evidence/_v15_stage8/c5_superseded/superseded_audit.json`），
   62|   其中 21 份的**夹具** pin 仍是现行代字节（夹具未动），**只有索引那一格换代**；
   63| * 需要哪一份运行继续被引用，就**重跑那一份**（成本＝一次真实运行）。
   64| 
   65| ## §6 完成定义
   66| 
   67| □ 前指纹＋备份 □ 重抽（277 卡 / 180 chunk，qwen3.8-max-0902＋effort=max）
   68| □ 后指纹 □ 最小重跑集逐项落证 □ pin 标异代（不 repin）
   69| □ C1 同口径复测 □ 如实报告（**含任何回退**）
```

## 产物：E:\白模预演codex\work\_ctx_orphan_fix.json

```
{
  "gate_six_criterion_source": "tools/kb_fetch/card_scope_audit.py:32-39 (CRITERION / scope/v3)",
  "gate_six_numbers": {
    "HEAD": {"catalogue": 2353, "edge_backed": 2262, "excluded": 91,
             "edge_backed_without_entry_count": 0},
    "LIVE": {"catalogue": 2353, "edge_backed": 2273, "excluded": 80,
             "edge_backed_without_entry_count": 11}
  },
  "orphan_cards": ["cine_move_index", "cine_move_pan_left", "cine_move_pan_right",
                   "cine_move_tilt_down", "cine_move_track_left", "comp_lead_room",
                   "gen_block_0005", "gen_block_0086", "gen_block_0297",
                   "gen_cine_0377", "gen_cine_0378"],
  "orphan_added_source_refs": 93,
  "total_added_source_refs": 2937,
  "index_fingerprint_before": "c796a5a87018631db54da88406a4bd352741ed346fa1e9b06293c85ef46fed67",
  "index_fingerprint_after": "00ea933ed11c1fa24a553feef18217e31eaff5f2c5a881dba5aa50867c7ec97c",
  "cache_key_fields": ["corpus_sha256", "model", "prompt_version", "schema_version",
                       "node_types", "edge_types", "vocab", "generations",
                       "rebind_version"],
  "rebind_version": "rebind/v1",
  "per_member_candidates": 3,
  "c1_same_yardstick": {"judge": "qwen3.8-max-0902", "reasoning_effort": "max",
                        "sample_slots": 90, "corrupt_before": 67,
                        "corrupt_after_shadow": 37,
                        "evidence": "docs/evidence/_v15_stage8/c1_recap/shadow_judge/"},
  "failing_tests": [
    "tests/test_extract_run_evidence.py::test_the_landed_real_run_evidence_is_fresh",
    "tests/test_extract_run_evidence.py::test_the_second_landed_run_is_fresh_and_has_no_contract_warning",
    "tests/test_extract_run_evidence.py::test_the_long_real_run_is_fresh_and_stayed_within_the_ceiling",
    "tests/test_evidence_digest_is_checkout_independent.py::test_a_landed_run_still_checks_out_after_an_lf_checkout[20261003_real_glm]",
    "tests/test_evidence_digest_is_checkout_independent.py::test_a_landed_run_still_checks_out_after_an_lf_checkout[20261003_real_ds]",
    "tests/test_evidence_digest_is_checkout_independent.py::test_a_landed_run_still_checks_out_after_an_lf_checkout[20261003_real_long]",
    "tests/test_q5_audit_channel.py::test_the_committed_real_run_drift_is_reproducible"
  ],
  "hard_constraints": [
    "R-5: 判据/阈值/门限一个字不许动",
    "不许删除测试、跳过测试、放宽断言",
    "R-8: 索引换代必须显式登记 + 最小重跑集",
    "换代后已入库运行的 pin 一律如实标「异代」，不许 repin 洗白",
    "holdout 是冻结仪器（门①-⑩ / Q1-Q7 / 第三方层 / generations 都钉着它的 sha256）"
  ]
}

```
```
