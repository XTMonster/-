# `20261007-v15-rotation` — `rebind/v2` 换代的门/评分读数（**不是一次完整链**）

这一份是 2026-10-07 知识索引换代（`rebind/v1` → `rebind/v2`，登记见
`docs/knowledge/REGEN_LOG_20261007_rotation.md` §7）后的**门与评分**读数。

## 读数

| 项 | 命令 | 结果 |
|---|---|---|
| 门①–⑩ | `python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab fixtures/knowledge_holdout.vocab.json --cards fixtures/knowledge_holdout.cards.json --assertable fixtures/knowledge_holdout.assertable.json --reviewer-classes human,llm-panel,third-party --exclude-cards knowledge/card_scope.json --third-party fixtures/knowledge_holdout.third_party.jsonl --generations fixtures/knowledge_holdout.generations.json --out …` | `holdout_gates.json`：**`overall: pass`**（generation gen2） |
| Q1–Q7 | `python tools/holdout_score.py --holdout fixtures/knowledge_holdout.jsonl --json …` | `holdout_score.json`：Q1 **0.9975**、Q2 1.0、Q3 0.0、Q4 1.0、Q6a/Q6b/Q7 1.0，`passed: true` |
| 门⑥ 的分母 | `python tools/kb_fetch/card_scope_audit.py` | `edge_backed 2262 / excluded 91 / edge_backed_without_entry **0**`（v1 时是 2273 / 80 / **11**） |
| 索引指纹 | — | `e5213e1b64781c24103eecae15a4921b5766f75c4709672fa48997de692cdf89`（v1 是 `00ea933e…`） |
| 确定性 | `build_hypergraph.py --rematch` 连跑两次 | `hypergraph.edges.jsonl` 逐字节相同 |

## 完整的链读数在别处

这一份只放**门与评分**。完整链（探针 31 支 ＋ 4 步固定 = **35/35 步全部跑到**）的
读数在 **`docs/evidence/20261007-204326/`**：`not passing: E1`（已结案的 RK-13），
其余全绿，`pytest` 2808 passed / 1 skipped / 0 failed。

（过程里曾经有一版"链停在 step 2"的记录：那时 `pytest` 里那条
`test_the_long_real_run_is_fresh_and_stayed_within_the_ceiling` 红着，因为 64 镜真跑
吃满了写死的 2 M token 上限。用户 2026-10-07 "你看着来"之后，上限改成随场景缩放、
长剧本那一跑重做了一版（2.76 M / 3.864 M，未触顶），那条红随之消失。）

判据、阈值、门限**一个字都没有改**；红的就是当前代码的真实读数。

## 派发前的会诊（用户裁决："先让 qwen3.8-max-0902 分析现在遇到的问题再执行"）

`qwen_orphan_consult/`：问题与证据包（`question.md` / `context.json`）、
两个角色（**领域讲解 / 实现顾问**）的判词与 usage、以及**联网前就写好**的
`bundle.manifest.json`（每份输入的 sha256、逐角色的 system/user 指纹、`source_seen`）
⇒ "它到底看到了什么"可对拍。判官/通道：中继 `qwen3.8-max-0902`，
`reasoning_effort=max`（两角色分别 183 s / 338 s，`finish_reason=stop`）。

两侧一致结论（也是最终落地的形状）：

1. 根因＝"重绑**扩大了可断言面**"（不是判据坏、不是夹具坏）；
2. 正解＝**收窄候选池**（`rebind/v2`），不补 held-out、不改门⑥ 的分母；
3. 必须用 **C1 同口径复判**验收，并**逐槽位**对比——不能只看门⑥ 绿；
4. 换代后旧运行的 pin **一律如实标异代**、不 repin；被引用的运行**重跑**一份。

两侧的分歧只在一处（候选池定义）：实现顾问主张"用 held-out 的 `from_card` 覆盖集"，
领域讲解主张"用**重绑前就有边**的卡"——后者被采纳，理由是**前者会让门⑥ 与仪器成环**
（"有边卡必须在 held-out 里"这条判据会**自己解锁自己**，正是 `MIN_EXPRESSIBLE_SHARE`
那条注释在防的形状）。两者在当时的索引上**逐张相同**（2262），所以落地读数不受影响。
