# Q5 的 join 可达性（P14-9，2026-10-02 09:55）

`§4.1b` 的 Q5 是两步判：① 夹具里带 `expect_movements` 的条目 **≥ 30**；
② 真实运行里与本条 `q` **键值对集合相等**的计划镜头数 **≥ 1** 才算进分母。
本轮把两步都做成了可执行的东西，并量出了**这一步现在到底够不够得着**。

## 1. 运行侧现在真的能算了（新实现）

`tools/knowledge/quality.py`：`plan_query_of_shot()` ＋ `q5_run_join()`，接进
`build_report()` 的 `--shots`。逐镜查询串**不重写**，一律交给同一个生产者
`layer5_orchestrator/scene_contract.py::shot_constraint_query`——只是把
`shots.json` 的字段折成它吃的形状（`camera.lens` / `movements[].kind` /
`action_types[]` / `dialogue_ids[]`）。

一个真实运行（`docs/evidence/market4/export/shots.json`，6 镜）反推出的契约串：

```
shot_001 景别=MCU；镜头=50mm
shot_002 景别=CU；镜头=85mm；运镜=dolly_in；对白=dialogue
shot_003 景别=MCU；镜头=50mm；对白=dialogue
shot_004 景别=CU；镜头=85mm；对白=dialogue
shot_005 景别=MS；镜头=50mm；运镜=follow_subject；动作=turn_body；动作=stand
shot_006 景别=MCU；镜头=50mm；对白=dialogue
```

对着这批串做 join：**相等判据命中 1 条**（`shot_001` ←→ 入库的
`景别=MCU；镜头=50mm`，`hq_2449`）；放宽成子集也只有 5 条。
也就是说 **join 机制本身是通的**，之前"0 命中"不是实现问题。

## 2. 但分母只有 1：三条结构性限制

### 2.1 只有 `SHOT_PATTERN` 是计划形状的（106/2953）

`q` 的键必须**全部**落在 `shot_constraint_query()` 会产出的六个键
（`景别/镜头/运镜/动作/特效/对白`）里。逐条核对入库 oracle：

```
plan-shaped entries: 106 / 2953        （全部是 景别×镜头）
distinct queries:    15
  MS+50mm 23 / CU+85mm 19 / MS+35mm 16 / CU+50mm 15 / LS+35mm 6 / MCU+50mm 6 / …
```

原因是索引的边里只有 `SHOT_PATTERN` 的**可查询成员**全部落在这六个键内
（`shot_size + lens`；`headroom_policy` 没有查询键）。其余 15 类边都至少带一个
计划永远不产出的键（`情绪`/`意图`/`节奏`/`音效`/`机位`/`轴线`/`构图`…），
所以它们的 `q` 在**构造上**不可能与计划镜头相等。

### 2.2 计划期的查询与 build 后的契约串**不是同一个串**

同一个运行里，`audit_log.jsonl` 的 `retrieval_call` 记的是**计划期真正发出去的**
查询：

```
景别=MCU
景别=CU；运镜=dolly_in；对白=dialogue
景别=MCU；对白=dialogue
景别=CU；对白=dialogue
景别=MS；运镜=follow_subject
```

**一条都没有 `镜头`**——因为计划里 `shot.camera` 常为空，焦距是取景求解器后补的。
所以"§4.1b 的 `SceneContract` 查询串"到底指哪一条，会直接决定 Q5 是 1 还是 0：

| 基准串 | 来源 | 与 106 条相等命中 |
|---|---|---|
| 计划期契约串（**驱动检索的那一条**） | `audit_log.retrieval_call.query` | **0** |
| build 后契约串（含求解器补的焦距） | `shots.json` 反推（本轮实现） | **1** |

> **更正（2026-10-02 10:05 自查）**：`retrieval_call` 的 `shot_id` **已经在代码里
> 接好了** —— `editor.py:244-250` 传 `shot_id=`，`retriever._edges_from_client` →
> `KnowledgeClient.retrieve_or_none` 一路带下去，并有具名用例
> `tests/test_knowledge_client.py::test_retrieval_call_events_carry_the_shot_they_belong_to`。
> market4 那份证据里是 `null`，因为它**早于**该修复。**这不是待修的缺陷。**
> 运行侧仍从 `shots.json` 反推，是因为那是 **build 后**的产物（含求解器补的焦距），
> 与计划期的检索串**不是同一个串**。

### 2.3 那 106 条的来源卡大多不讲运镜（够不到 30）

106 条里来源卡正文出现运镜语汇的只有 **23 张**。跑一次独立标注（换族 GLM，
`tools/holdout_expect_movements.py`，判据＝"这句作者话里有没有说镜头怎么动"）
实测（`work/q5_expect_movements.jsonl`，跑满 106 条之前的中途快照 **n=38**）：
**只有 7 条**拿到非空 `expect_movements`（5 条 `固定`、1 条
`track_left/track_right`、1 条 `dolly_in/crane_arc_up`），约 **18%**。
按这个比例，106 条最多产出 ~19 条非空条目——**§4.1b 第一步的 30 条在这批语料上够不到**。
（中途快照另有 n=19 → 3 条 ＝16%，比例稳定。）

## 3. 结论与建议动作

**结论**：Q5 的 join 机制是通的（已实现、有对抗性用例），但**样本供给不够**：
计划形状的条目只有 106 条、其中讲运镜的 ~17 条，且"计划期串 vs build 后串"
的口径没定死。这不是实现缺陷，是**索引/语料/口径**三处的缺口。

**建议（按代价从小到大）**：

1. **把 `SHOT_PATTERN` 的 `movement` 可选成员抽出来**。schema 里它本来就有
   （`OPTIONAL_MEMBERS["SHOT_PATTERN"] += allow/movement`），但索引里一条都没有。
   让抽取器在"景别×镜头"的边上显式找运镜耦合，`q` 变成
   `景别×镜头×运镜`——**仍然是计划形状**（`运镜` 是计划键），而这类卡本身就在讲
   运镜，`expect_movements` 天然有依据，30 条下界当即可达。
2. **定死 Q5 的基准串**：要么在计划 schema/提示里要求**每一镜给出 `camera.lens`**
   （现在常缺，计划期串因此没有 `镜头`），要么在 §4.1b 里写明基准是 build 后的
   `ShotContract`。两者都要用户点头（改的是验收口径，不是代码）。
3. ~~`retrieval_call` 事件补 `shot_id`~~ —— **已核销：不是缺陷**。代码里已经接好
   （`editor.py:244-250` → `retriever._edges_from_client` → `KnowledgeClient`，
   用例 `tests/test_knowledge_client.py:91`）；market4 那份 `null` 是**修复前**的
   证据。运行侧用 `shots.json` 反推是**故意的**：它要的是 build 后的契约串。

## 4. 本轮落地的代码与用例

| 文件 | 内容 |
|---|---|
| `tools/knowledge/quality.py` | `PLAN_QUERY_KEYS`、`_normalise_query_pairs()`、`_ShotView`、`plan_query_of_shot()`、`q5_run_join()`；`q5_movement_hit()` 接上运行侧 |
| `tools/holdout_expect_movements.py` | 换族 GLM 给**计划形状**条目补 `expect_movements`（判据落在卡正文，quote 必须带运镜语汇，宁缺勿猜） |
| `tests/test_q5_run_join.py` | 生产者同源、锁死＝`固定`、别名归一、子集只作诊断、分母为 0 记 `not_measured`、入库条目确实是计划形状 |
