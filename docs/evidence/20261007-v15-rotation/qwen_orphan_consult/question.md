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
