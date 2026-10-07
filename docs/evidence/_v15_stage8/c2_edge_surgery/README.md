# C2：「9 边 / 15 槽位」局部手术**备料**（P8-T4）⚖️

**run-id**：`_v15_stage8/c2_edge_surgery`
**卡**：`执行文档v1.5/TECH_SOLUTIONS.md` §三 **C2**（⚖️ 须裁决：删边＝换代）
**卡定义**：`执行文档v1.5/dispatch_graph.json` 的 `P8-T4`
**日期**：2026-10-07
**纪律**：**索引 `knowledge/hypergraph.edges.jsonl` 与所有夹具一个字节都没动**。
本卡只出"换卡 / 删边"两案与换代影响面，**不拍板**。

---

## 1. 裁决原文与两把尺子

裁决（`docs/evidence/20261007-grounding-ruling/README.md` §二）：

> 判不了的边 **9 条**；这些边的成员判定 `topic_mismatch 14` / `topic_matches 1`
> ⇒ 落在**删边**那一支。

那句话出自 `work/_probe_wrong_card.py`。`../20261007-wrong-card-correction/README.md`
已证明它**读的是一份残缺的卡索引**（只读 `*.yaml` ⇒ 132 张手写卡读不到；
而手写卡**根本没有 `topic` 字段**）。本卡把两把尺子**并排重跑**在**同一批 9 条边**上
（`edge_surgery.py`；逐槽位判词与入库的 `work/_wrong_card_full.json` **逐条一致**，
脚本会自证）：

| 尺子 | 卡索引 | 卡级"主题"取哪个字段 | 空值怎么办 |
|---|---|---|---|
| **旧**（`_probe_wrong_card.py`） | 只有 `*.yaml`（2221 张生成卡的文字块） | 只读 `topic` | 空串**也进集合** ⇒ `['']` 为真 ⇒ 记成"不符" |
| **新**（`_probe_wrong_card_full.py`） | 生成卡 `.jsonl` ＋ **132 张手写卡** | 手写卡用 `domain` 顶替 | 全空 ⇒ `topic_unknown`（"不知道"≠"不符"） |

**同一批 15 个槽位的判词（实测）**：

| 判词 | 旧尺子 | 新尺子 |
|---|---|---|
| `topic_mismatch`（主题**不符**） | **14** | **6** |
| `topic_matches` / `topic_or_domain_matches_kind` | **1** | **2** |
| `topic_unknown`（来源卡**没有**主题字段） | 0（被并进 mismatch） | **6** |
| `in_card_text`（取值就写在来源卡正文里） | 0 | **1** |
| 合计 | 15 | 15 |

⇒ 旧尺子的"14 条不符"里，**6 条其实是"不知道"、1 条是正命中**
（`hg:d090d7ce0096` 的 `composition_rule:headroom` —— 来源卡里有手写卡
`comp_headroom`，`title=头顶留白`、`keywords=['头顶留白','headroom','留白']`）。
**"删 9 条边"的机械依据不成立。**

## 2. 逐槽位清单（15 条，两把尺子并列）

| # | edge_id | type | kind | value | 旧尺子 | 新尺子 | 来源卡数 | 含手写卡 | 全库"正文写了这个值"的候选 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `hg:3f26bdf8d230` | SHOT_PATTERN | headroom_policy | cinematic | mismatch | mismatch | 1 | `cine_height` | **0** |
| 2 | `hg:400a2bfcda8e` | STAGING_PACK | composition_rule | lead_room | mismatch | mismatch | 23 | `block_crowd_flow` | **0** |
| 3 | `hg:400a2bfcda8e` | STAGING_PACK | camera_angle | 平视 | mismatch | mismatch | 23 | `block_crowd_flow` | 10 |
| 4 | `hg:5b8b86de2d87` | STAGING_PACK | composition_rule | lead_room | mismatch | **相符**（域 `composition` ⊂ kind） | 29 | `comp_diagonal`,`comp_eye_trace` | **0** |
| 5 | `hg:5b8b86de2d87` | STAGING_PACK | camera_angle | 平视 | matches | **相符** | 29 | 同上 | 10 |
| 6 | `hg:6d201c4c47a3` | SHOT_PATTERN | headroom_policy | cinematic | mismatch | mismatch | 1 | — | **0** |
| 7 | `hg:904424ad8c64` | STAGING_PACK | composition_rule | lead_room | mismatch | **unknown** | 2 | — | **0** |
| 8 | `hg:904424ad8c64` | STAGING_PACK | camera_angle | 高机位 | mismatch | **unknown** | 2 | — | 7 |
| 9 | `hg:d090d7ce0096` | STAGING_PACK | composition_rule | headroom | mismatch | **in_card_text** | 4 | `comp_headroom` | 1（`comp_headroom`） |
| 10 | `hg:d090d7ce0096` | STAGING_PACK | camera_angle | 平视 | mismatch | mismatch | 4 | `comp_headroom` | 10 |
| 11 | `hg:d28d18bfdde4` | STAGING_PACK | composition_rule | lead_room | mismatch | **unknown** | 2 | — | **0** |
| 12 | `hg:d28d18bfdde4` | STAGING_PACK | camera_angle | 低机位 | mismatch | **unknown** | 2 | — | 4 |
| 13 | `hg:e2ea1c270f9b` | SHOT_PATTERN | headroom_policy | cinematic | mismatch | mismatch | 2 | — | **0** |
| 14 | `hg:e3ee2d0b5f4c` | STAGING_PACK | composition_rule | balance | mismatch | **unknown** | 1 | — | 1（`comp_balance`） |
| 15 | `hg:e3ee2d0b5f4c` | STAGING_PACK | camera_angle | 低机位 | mismatch | **unknown** | 1 | — | 4 |

**"候选"一栏的读法**：它是"**全库任何一张卡的正文里出现了这个取值**"（`edge_surgery.py`
的 `candidate_cards`），**不是**"这条边该挂到它身上"。列 0 表示**库里根本没有卡写过这个取值**。

### 2.1 三条 `headroom_policy: cinematic` 的特别说明

第 1/6/13 行的取值 `cinematic` 在**全库 2353 张卡里一个字都没出现过** ⇒ 这类槽位
按构造**永远不可能**被"正文回查"判成有依据。它不是"挂错了卡"，而是**取值本身是闭集桶名**
（与 `tools/knowledge/attestation.py` 里 `not-checkable` 的成因同类：
`intensity:mid`、`avg_shot_len:>8s`）。**换卡救不了它，删边也不证明什么。**

## 3. 逐条两案（**只备料**）

| edge_id | 换卡案 | 删边案 |
|---|---|---|
| `hg:3f26bdf8d230` | **无具名候选**（`cinematic` 全库无卡写过）⇒ 该案当前不可选；要么改值域（＝改判据，须裁决），要么承认它是 `not-checkable` 型槽位 | 删这条边会动 `SHOT_PATTERN` 的 83 条中的 1 条；索引换代 ⇒ 见 §4 |
| `hg:400a2bfcda8e` | `camera_angle:平视` 有 10 张候选（`cine_eye_level`／`gen_cine_0205`…）；但本边的 `composition_rule:lead_room` **无候选** ⇒ 换卡只能换一半，且会把来源从 23 张收窄到具名少数几张（**改的是边的溯源**，须裁决） | 23 张来源卡的 `STAGING_PACK` 边消失一条 |
| `hg:5b8b86de2d87` | 新尺子下**两个槽位都"相符"**（域 `composition` ⊂ `composition_rule`、`camera_angle` 直接命中）⇒ **不必换卡** | **不应删** |
| `hg:6d201c4c47a3` | 同 `hg:3f26bdf8d230`（`cinematic` 无候选） | 同左 |
| `hg:904424ad8c64` | `camera_angle:高机位` 有 7 张候选；`composition_rule:lead_room` 无候选 | 同左 |
| `hg:d090d7ce0096` | **不需要换**：`composition_rule:headroom` 已判 `in_card_text`（`comp_headroom`）⇒ 该槽位本来就是对的 | **不应删** |
| `hg:d28d18bfdde4` | `camera_angle:低机位` 有 4 张候选；`lead_room` 无候选 | 同左 |
| `hg:e2ea1c270f9b` | 同 `cinematic` 型（无候选） | 同左 |
| `hg:e3ee2d0b5f4c` | `composition_rule:balance` 有 `comp_balance`（**具名、正命中**）；`camera_angle:低机位` 有 4 张候选 ⇒ 这是**唯一一条两个槽位都有具名候选**的边 | 同左 |

**换卡案的共同代价（无论哪条）**：

1. **改的是边的溯源**（`sources`），不是排版——它决定"这条规则凭什么成立"；
2. 换完必须重跑 `tools/knowledge/attestation.py`（支持率会变），并**重签索引指纹**；
3. 换卡是**语义决定**，机械候选只给"哪些卡写过这个词"，**不给"谁才是这条规则的正当出处"**——
   后者正是 90 槽位三分类（C1，当前被 GLM 通道阻塞）要回答的。

## 4. 换代影响面（**实测 22 份，不是 23**）

删边会改 `knowledge/hypergraph.edges.jsonl` ⇒ `knowledge/hypergraph.manifest.json` 的
`fingerprint` 变 ⇒ 已入库运行的 `pins.index.fingerprint` 全部失配。

```
python -c "...rglob('run_manifest.json')..."
-> 全仓 run_manifest.json 共 22 份，**每一份都 pins.index**
-> 22 份的指纹**全部等于** 当前 c796a5a87018631db54da88406a4bd352741ed346fa1e9b06293c85ef46fed67
```

| 项 | 值 |
|---|---|
| 会失配的运行份数 | **22** |
| 当前索引指纹 | `c796a5a8…f46fed67`（`knowledge/hypergraph.manifest.json`） |
| 当前 schema 指纹 | `1a90c089bb8f4f7fbd61a145a2088d6c2628ecbbd4dba47f63396fbf34fadaf3`（`hypergraph.schema_fingerprint()`） |

**台账/清单里写的"23 份"与本卡实测的 22 份差 1**：`rg -l '"pins"' --glob '*.json'`
全仓只有 22 份（含 `work/` 也是 22）⇒ **以实测 22 为准**，本卡如实记录，不去"凑"23。

运行清单（逐份）：`20261003_chunked_long{,3,6,9,10}`、`20261003_intent`、
`20261003_real{,,_ds,_glm,_long}`、`20261004_chunked_long{11,12,14,…,20}`、
`20261006-long21`、`20261007-real-axis`、`20261007-real-closure`
（后两份多一个 `third_party` pin）。完整机器可读清单见 `edges.json` 的 `pins_impact.runs`。

## 5. A6 换代登记表（**预填，只在用户选"动手"时使用**）

| 字段 | 值 |
|---|---|
| 换代原因 | C2：处置 9 条闭环边（换卡或删边） |
| 触发卡 / 裁决 | `P8-T4`／`docs/evidence/20261007-grounding-ruling/README.md` §二 |
| 换代类型 | 加边 / 删边 / 改 `sources`（**三者都会被 `repin()` 判成换代**） |
| 是否需要用户点头 | **是**（涉判据与溯源） |
| §2 会变的产物 | `knowledge/hypergraph.edges.jsonl`（**会变**）；`nodes.jsonl`／`cases.*`／
`fixtures/knowledge_holdout*`（**未变**，除非改值域）；`hypergraph.manifest.json`（指纹必变） |
| §2 会失配的消费者 | **22 份** `run_manifest.json.pins.index`（清单见 §4）；
其中 `20261007-real-axis`／`20261007-real-closure` 另有 `pins.third_party`（不受影响） |
| §3 前指纹 · 索引 | `c796a5a87018631db54da88406a4bd352741ed346fa1e9b06293c85ef46fed67` |
| §3 前指纹 · schema | `1a90c089bb8f4f7fbd61a145a2088d6c2628ecbbd4dba47f63396fbf34fadaf3` |
| §3 后指纹 | **待生成**（本卡未执行） |
| §4 最小重跑集 | 门①–⑩＋Q0（`tools/knowledge/quality.py`）＋Q1/Q2/Q4/Q6b（`tools/holdout_score.py`）＋
`tools/knowledge/attestation.py`（支持率会变）＋ 一次 headless 链；**全量 pytest 永远是** |
| §5 pin 处置 | 22 份**原样保留**，标"异代"，**不 repin 洗白**（`repin()` 内容真变会进 `skipped`） |

## 6. 本卡的结论（**推荐动作，不是裁决**）

1. **机械依据已作废** ⇒ **不建议**按旧尺子的"14 条不符"去删边。
   （与 `013d516` 的结论一致，但**理由不同**：那条是"代价太大"，这条是"**判据不成立**"。）
2. **不建议现在就换卡**：9 条边里只有 4 个槽位有具名候选（`comp_headroom`／`comp_balance`
   ／`camera_angle` 的 7~10 张），而"机械候选"回答不了"谁才是正当出处"；
   其余槽位的取值（`cinematic`／`lead_room`）**全库无卡写过**，换卡解决不了。
3. **建议的下一步**：等 C1（90 槽位三分类）拿到真错率——它给的才是"挂错卡 vs 蕴含未写出"的
   判词；本卡的 `edges.json` 可以直接当它的输入侧对账表。
4. 三条 `headroom_policy: cinematic` 应单列给 **B3（适用域语义 / 值域）** 那一支：
   它们是**值域问题**，不是"挂错卡"。

## 7. 未验证 / 边界

1. "9 条边"来自**一次真实运行**（`docs/evidence/20261007-real-closure/`）注入日志的闭环诊断；
   换一份运行日志，"判不了"的边集合可能不同（`edge_surgery.py` 可复算，逐字可跑）。
2. 新尺子的"相符"用的是**双向子串包含**（`composition` ⊂ `composition_rule`）——
   **宽松**，不是语义等价。本卡照抄它是为了与入库读数对得上；这不构成"挂对了"的证明。
3. `candidate_cards` 只做**字面子串**搜索（中英文都算），不做同义/蕴含判断。
4. 本卡**未**触碰索引、夹具、`fixtures/**`、`tests/**`；`git status` 见 README 末尾。

### 7.1 未改动索引的现场证据

```
git status --porcelain -- knowledge fixtures docs/evidence/_v15_stage8/c2_edge_surgery
->  M fixtures/expected_sdl_long.json
    M fixtures/expected_sdl_simple.json
    M fixtures/expected_shots_long.json
    M fixtures/tool_transcript_simple.jsonl
    ?? docs/evidence/_v15_stage8/c2_edge_surgery/
```

* `knowledge/` **一行改动都没有**（索引与夹具的真源未被触碰）——这是本卡最关键的红线证据。
* 那 4 个 `fixtures/expected_*.json` 的 `M` 是**本卡之前**就存在的改动（阶段 2 的 golden
  重生成，见 `docs/evidence/20261007-v15-closeout/commit_grouping.md` 的分组），**不是**本卡产生的。
