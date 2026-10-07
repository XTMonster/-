# 换代登记 · 2026-10-07：卡↔槽位绑定清洗（用户裁决「换吧」）

**性质**：**已获用户明示批准的换代**（R-8 要求的显式登记）。
**触发**：用户 2026-10-07 对两个 ⚖️ 项同时答复「**换吧**」：
① `P5-T2`（要不要换代）② `C2`（9 条边选「**换卡**」而不是删边）。
**方法**：沿用 `build_hypergraph.py --replace-cards`（工具自带、且其 docstring 里
就有同形先例：v6 把概念名词写进动作槽位、横跨 329 张卡，用的就是这条清洗路径）。

---

## §1 换代原因（实测证据，不是拍脑袋）

1. **C1 三分类（90 槽位分层样本，已完成）**：
   `corrupt = 67/90 = 0.7444` → `corrupt-dominated`；四个分层**一致**（0.65–0.80）
   ⇒ 按裁定口径（≥33% 且模式一致）「**暂缓重抽**」被证伪。
   证据：`docs/evidence/20261007-grounding-sample90/三分类汇总.json`
2. **C2 机械判据（9 边 / 15 槽位）**：旧尺子 `topic_mismatch 14 / matches 1`，
   新尺子 `topic_mismatch 6 / topic 或域与 kind 相符 2 / topic 未知 6 / 正文里真的有 1`。
   每条都带 `candidate_cards`（正文里真的写了该取值的**候选卡**）。
   证据：`docs/evidence/_v15_stage8/c2_edge_surgery/edges.json`
3. **C3**：`topic` 是**来源级**标签、对卡级判定零分辨率 ⇒ 判「挂错卡」必须回到**卡正文**
   （机械预读的 88/90 不能当判决）。

## §2 影响面（要动什么、不动什么）

| 项 | 内容 |
|---|---|
| **动** | `knowledge/hypergraph.{nodes,edges}.jsonl`（重建）、`hypergraph.manifest.json`、`work/hypergraph.atoms.jsonl`（原子边） |
| **不动** | **判据／阈值／门限**（R-5）；**held-out 夹具**与第三方层（门⑦ 的输入，字节不动）；`hypergraph.py` 的槽位闭集 |
| **目标卡集** | **277 张**（`work/_rotation_replace_cards.txt`）：C2 的 65 张错卡 ＋ 21 张候选卡 ∪ C1 的 194 张来源卡 |
| **重抽量** | 覆盖 **180 / 708 chunk**（25%）——其余 528 chunk 走**原子边缓存**，逐字节不变 |
| **抽取模型** | **`qwen3.8-max-0902`**（用户 2026-10-07 指示"派发给 qwen3.8max0902，让他完成所有任务"）；`reasoning_effort = max`（用户："新模型思考强度拉到最大"） |

## §3 前后指纹（**前指纹＝实测**，后指纹待重建后填）

```
schema_fingerprint            1a90c089bb8f4f7fbd61a145a2088d6c2628ecbbd4dba47f63396fbf34fadaf3
manifest_fingerprint(前)      c796a5a87018631db54da88406a4bd352741ed346fa1e9b06293c85ef46fed67
hypergraph.nodes.jsonl   sha 789c0625ad6c6f65…    hypergraph.edges.jsonl  sha 0597326a9d300137…
hypergraph.manifest.json sha d0613eb498f91371…    work/hypergraph.atoms.jsonl sha 5cd8cf67680a3ff9…
corpus(fetched.jsonl)    sha 46401b5627df74e9…    vocab.json sha a295f3ef5a1e24a7…
```

**前指纹的完整备份**：`work/_pre_rotation_20261007-154410/`（6 份产物，可回滚/对拍）。
> `work/` 是 `.gitignore` 掉的草稿区 ⇒ 备份**不进库**；索引本体在 `knowledge/`（进库）。

## §4 最小重跑集（换代后必须重跑的）

| # | 门／读数 | 命令 |
|---|---|---|
| 1 | 门①–⑩（含门⑦ 两代口径） | `python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab fixtures/knowledge_holdout.vocab.json --cards fixtures/knowledge_holdout.cards.json …` |
| 2 | Q1–Q7（held-out） | `python tools/holdout_score.py --holdout fixtures/knowledge_holdout.jsonl --json <out>` |
| 3 | Q0 / E1–E3 | `python tools/knowledge/quality.py …` ＋ `python tools/knowledge/hard_gates.py …` |
| 4 | 全链 | `powershell -File tools/run_tests.ps1`（含 pytest ＋ 31 支探针） |
| 5 | **C1 复测（同口径）** | 重跑 90 槽位三分类，看 `corrupt_share` 是否下降（**判据不变**） |

## §5 pin 处置（**不许 repin 洗白**）

* 已入库运行把 `pins.index`（索引指纹）钉进 `run_manifest.json`；
* 换代后这些 pin **会失配** ⇒ 一律**如实标「异代」**，**不** `repin()`（它会拒）；
* 实测：带 `holdout` pin 的运行 **22 份**（`docs/evidence/_v15_stage8/c5_superseded/superseded_audit.json`），
  其中 21 份的**夹具** pin 仍是现行代字节（夹具未动），**只有索引那一格换代**；
* 需要哪一份运行继续被引用，就**重跑那一份**（成本＝一次真实运行）。

## §6 完成定义

□ 前指纹＋备份 □ 重抽（277 卡 / 180 chunk，qwen3.8-max-0902＋effort=max）
□ 后指纹 □ 最小重跑集逐项落证 □ pin 标异代（不 repin）
□ C1 同口径复测 □ 如实报告（**含任何回退**）

---

## §7 第二轮（`rebind/v2`）：把门⑥ 的 11 张孤儿卡修掉，顺手修掉一处"库里的索引不是构建器产物"

**触发**：`rebind/v1` 落地后门⑥ 判红——`edge_backed_without_entry = 11`
（`rebind/v1` 把 11 张**本来零边**的卡追加进了 `sources[]`，它们于是成了"可断言卡"，
而 held-out 里没有它们的条目）。qwen3.8-max-0902 两角色会诊（`work/_qwen_orphan_fix/`）
一致裁定：根因是"重绑扩大了可断言面"，正解是**收窄候选池**（不改判据、不动冻结夹具）。

### §7.1 改了什么（只有一处规则 ＋ 一处接线 ＋ 一处记账）

| 文件 | 改动 |
|---|---|
| `tools/kb_fetch/rebind.py` | `REBIND_VERSION = "rebind/v2"`；新增 `edge_backed_cards()`；`candidate_cards(..., pool=)` / `rebind_edges(..., candidate_pool=)`——候选只从"重绑输入边里已经出现过的卡"里取 |
| `tools/kb_fetch/build_hypergraph.py` | `_apply_rebind()` 先算池再接线，并对拍**保范围不变量**（重绑后 `edge_backed` 只许多出来零张，否则当场 `AssertionError`）；`merge.rebind` 进 manifest（真源在 manifest 里，能审） |
| `tests/test_rebind.py` | 新增 4 条：池的边界（池外一字不许进／空池 ≠ 不设限）、`edge_backed_cards()`、`v1` 对照（不设池必须复现旧行为）、池内照旧重绑 |
| `tests/test_sidecar_retrieve.py` | sidecar 新增 opt-in `--reasoning-effort`（用户"思考强度拉到最大"）：不发时请求体一个字节不变，`openai` 才透传、`ollama` 不透传 |

**顺手修掉的既存缺陷（`v1` 的可推导性问题）**：`v1` 落库的那份索引是从**影子脚本**
（`work/_shadow_rebuild.py`，候选次序＝`attestation.load_cards()` 的字典序）promote 回来的，
而构建器的 `_apply_rebind` 用的是 `build_hypergraph.load_cards()` 的次序——两处次序在个别边上
给出**不同的候选**（实测 `hg:1bb82beaeb5d` 等：影子挑 `axis_cross_cost`，构建器挑 `cine_establishing`）。
也就是说 `work/_verify_rebind_reproduces.py` 那句"能逐字节复现"只证明了**影子那一侧**自洽，
并没有证明"库里的索引 == 构建器产物"。`rebind/v2` 起索引一律**由构建器路径重建**
（`python tools/kb_fetch/build_hypergraph.py --rematch`，不调模型），所以这条等式是**构造性**的。

### §7.2 后指纹（v2）与实测账

```
manifest_fingerprint(v2)      e5213e1b64781c24103eecae15a4921b5766f75c4709672fa48997de692cdf89
cache_key.rebind_version      rebind/v2
hypergraph.edges.jsonl   sha ad88f44e478b4f2c…（551,641 B）   （v1 是 58a4e8b2…／553,672 B）
manifest.merge.rebind         {"edges_touched": 560, "sources_added": 2867, "members_without_candidate": 210,
                              "candidate_pool": 2262, "edge_backed_before": 2262, "edge_backed_after": 2262}
```

* **保范围**：`edge_backed` 2262 → 2262（`v1` 是 2262 → 2273）；
  `v2` 与 HEAD 的"有边卡"集合**逐张相同**（新增 0、丢失 0）。
* **门⑥** 回到 `edge_backed 2262 / excluded 91 / edge_backed_without_entry 0`；
  `python tools/kb_fetch/card_scope_audit.py` 重新落 `knowledge/card_scope.json`。
* **代价（如实记）**：1,063 个可重绑槽位里 **11 个**掉回"零候选"（全是
  `composition_rule:lead_room`，唯一候选只有手写卡 `comp_lead_room`），
  零候选总数 199 → **210**。90 条 C1 样本**一条都不在其中**（`work/_measure_restricted_rebind.py`）。
* **可推导性**：`--rematch` 连跑两次 → `hypergraph.edges.jsonl` 逐字节相同。

### §7.3 最小重跑集（第二轮）

| # | 读数 | 结果 |
|---|---|---|
| 1 | 门①–⑩ | **全 pass**（`overall: pass`，generation gen2） |
| 2 | Q1–Q7 | Q1 **0.9975**、Q2 1.0、Q3 0.0、Q4 1.0、Q6a/Q6b/Q7 1.0 —— 与换代前同值 |
| 3 | C1 同口径复测 | 90 槽位三分类（判官 `qwen3.8-max-0902`，`reasoning_effort=max`）见 §7.4 |
| 4 | 全链 | 见 §7.5 |

### §7.4 C1 同口径复测（`rebind/v2` 落库那一份）

判官、模板、90 条样本、批大小全部与真实那一次逐字相同，只有来源卡换成**现行 v2 索引**
的 `sources`（90 条里有 **20 条**的来源卡与影子版不同）。产物：
`docs/evidence/_v15_stage8/c1_recap/v2_judge/`，组题脚本 `work/_v2_rejudge_prep.py`。

（读数见该目录的 `三分类汇总.json` 与 `../shadow_comparison.md` 的对照栏。）

### §7.5 pin 处置（第二轮，**仍不 repin**）

`v1` 让 22 份已入库运行的索引 pin 失配；`v2` 再换一次（`00ea933e…` → `e5213e1b…`）。
按 §5 的纪律：**一律如实标异代**，需要继续被引用的运行**重跑**。第二轮跑出来的新证据：

| 目录 | 用途 |
|---|---|
| `docs/evidence/20261007-v15-6shot-ds/` | 6 镜真实运行（sidecar→DeepSeek），同代、零原因零警告 |
| `docs/evidence/20261007-v15-long/` | 61+ 镜长剧本真实运行（同上游），链上 Q5/E2 与长路径证据 |
| `docs/evidence/20261007-v15-6shot-bailian/` | 6 镜真实运行（sidecar→**阿里云百炼** `qwen3.8-max-0902`），同代、零原因零警告 |

---

## §8 第三轮：零候选槽位的**裁决**（qwen3.8-max-0902 代替人工）＋ 一次**没有落地**的剪枝

**触发**：用户 2026-10-07 "用拍板的问题 2 的那个 qwen3.8max0902 解决，**代替人工裁决**"
——即把"老账"里那 199 个零候选槽位（含 `axis_side` 一族）的"删边/裁决"交给判官。

### §8.1 裁决（已出，`reviewed_by: "third-party"`）

* 判官：`qwen3.8-max-0902`（**阿里云百炼**，DashScope OpenAI 兼容口），`reasoning_effort=max`，
  **流式**；18 批、每批 ≤12 条，逐条判完 **199/199**（不是抽样）。
* 判词：`keep` **177** / `wrong_card` **20** / `wrong_value` **2**；逐条理由在 `rows[].why`。
* 记录：`docs/evidence/20261007-v15-zerocand-verdict/verdict.json`（＋每批 `裁决.json`
  与 `.usage.json`）；组题/汇总脚本在 `work/_zerocand_*.py`。

### §8.2 规则写好了，但**没有打开**：冻结的 oracle 挡着

`tools/kb_fetch/rebind.py` 新增 `PRUNE_VERSION = "prune/v1"` ＋ `prune_members()`
（判成 `wrong_card`/`wrong_value` 的成员从它所属的边上摘掉；边被摘空就整条删），
并接进构建器——但记录里 **`apply: false`**（缺省也是 false），所以索引**没有动**。

理由（逐条实测，`work/_prune_greedy.py`）：

```
22 条判决**每一条**单独执行 ⇒ 门⑩ 判红（unresolved 2–67 条 spec）
基线（一条都不摘）        ⇒ 门⑩ pass
```

根因：门⑩ 的 spec 是按**边的成员形状**匹配的，而每个成员都是某条 spec 期望的形状的一部分
——所以"摘掉一个无卡佐证的成员"就等于**改掉 oracle 断言**。要执行必须换 **oracle 一代**
（夹具 sha256 进所有运行的 pin ⇒ 那些运行会一起失代，整条链与真跑都要重来）。
这是**换代决策**，按 R-8 要用户明示；记录里 `apply_blocked_by` 写清了这条。

### §8.3 顺带落地的两件事

| 事项 | 内容 |
|---|---|
| **长剧本 token 上限** | 用户"你看着来"⇒ `budget.tokens_per_call_allowance=7000` ＋ `max_tokens_ceiling=4000000`：账本上限＝`max(静态下限, min(静态帽, 本场调用额度 × 每次调用额度))`。小场景仍是 2 M（一个字节不变），64 镜 2 M → **3.864 M**（实测两次真跑 6,150 / 6,311 token/调用） |
| **百炼通道** | 见 `docs/evidence/20261007-v15-bailian/`：根因是**思考模式拒收 `tool_choice=required`**（`InternalError.Algo.InvalidParameter`），sidecar 把非 2xx 一律翻 502 ⇒ 0.7 s 失败；修法是 sidecar 新增 `--tool-choice-mode`（默认 `passthrough`）。另实测：百炼上**非流式大包会挂住**（26 分钟不返回）、**流式 1 s 回首 chunk**，所以 `glm_consult` 加了 `GLM_STREAM=1` 的 opt-in 流式通道 |

### §8.4 「再抽一次」这条路：**已穷尽**（2026-10-07，用户「做吧」）

§8.2 摆出的两条出路里，用户选了第一条"重新掷骰子"。掷完的结论：**这条也走不通**，
并且**两个取值的病根不是同一处**——逐条读数在
`docs/evidence/20261008-replace-cards/README.md` §6（＋ `reroll/` 下的两次 stdout、
缓存读数、卡正文 token 扫描，以及"每个取值有几条边支撑"的两把尺子）。

| 取值 | 卡正文里写没写过 | HEAD 索引里的载体 | 掷骰子后 | 判读 |
|---|---|---|---|---|
| `movement:dolly_zoom` | **写过**（`cine_move_dolly_zoom` 标题即「推拉变焦（眩晕镜头）」） | 1 条边 | **0 条边** | 词表别名漏了语料真实用词：`vocabulary.py::MOVEMENT_ZH` 收的是 `("移焦眩晕","希区柯克变焦","变焦推拉")`，而语料写的是 **`推拉变焦`**（顺序反着，四个字一个都没收）⇒ 抽取器只能猜，猜中是掷骰子 |
| `sfx:尖锐哨音` | **一个字都没写过**（2353 张卡里 `尖锐哨音/哨音/耳鸣` = 0/0/0） | 2 条边（源卡正文都没有这个词） | 1 条边（源卡 `gen_edit_0191`+`gen_story_0132`，同样没有） | **抽取器发明的**，每次重抽都会继续发明 ⇒ 掷骰子修不掉 |

另量到一件事：**这 52 张的重抽不可复现**——两次都从与 HEAD 逐字节相同的状态、同一条命令起步，
缓存 39 张命中、13 张每次真调用 ⇒ 一次 636 条边、一次 634 条边。⇒ 它只能当"这条路通不通"的
一次判断，**不能当验收手段**（同一份输入连跑两次，索引都不是同一个）。

**剩下的三选一（需用户拍板）**：① 就按现状结案（22 条判决只记不改）；② 只治词表那一档
——给 `dolly_zoom` 补上语料真实用词（`ACCEPTANCE_STATUS.md` §20.4 有先例：补一个别名
`安静` 就把一条正确的禁令边从"主体是编的"救回来），并把没有真载体的取值换代；③ 改抽取提示
（成员必须给正文原句或取值本身／同义词，现在 `gate/v2` 只对 `forbid` 成员查宿主）后整库重抽。
**三条都要改冻结输入（词表/夹具），按 R-8 一律要用户明示**；两条路都没动判据、门限、阈值。
