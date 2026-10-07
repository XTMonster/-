# 执行文档 v1.5 —— 契约层与规则层落地证据

**run-id**：20261007-v15-contracts
**HEAD（起点）**：`f6530c6`
**纪律**：判据／阈值／门限一个字未动（红线 R-5）；证据落本目录（R-9）。

---

## 1. 本批完成的卡

| 卡 | 交付 | 落点 |
|---|---|---|
| **P1-T1** | OPEN_PROBLEMS 加"已被接管"抬头；两处悬空引用改指 | `docs/knowledge/OPEN_PROBLEMS.md`（顶部块）、`AGENTS.md:58`、`docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md:1325` |
| **P1-T2** | 台账四处编者注（P10 过期块 / 编号撞号 / 307 晚于 308 / 尾止 P14-318） | `docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md` |
| **P1-T3** | AGENTS.md 状态块读数刷新为实测 | `AGENTS.md`（P14 现状块） |
| **P2-T1** | `ShotBeat`/`LightSpec`/`CompositionSpec`/`RuleJustification` + `validate_beats` 等 | `block_director/contracts/beats.py`（新建）、`tests/test_beats.py` |
| **P2-T2** | `ShotPlan.beats/composition/rule_justifications`、`Plan.environment` | `block_director/contracts/plan.py`、`tests/test_plan_v15_fields.py` |
| **P2-T3** | SDL 升 1.5（`SDLAnchor`、环境 anchors/light、镜头三字段）+ 1.4→1.5 迁移 | `contracts/sdl.py`、`layer2_sdl/sdl_migrate.py`、`layer2_sdl/sdl_builder.py`、`tests/test_sdl_15.py` |
| **P2-T4** | emit_plan 增 `environment`；emit_shot_draft 增 `beats`/`composition`/`rule_justifications` + 解析期校验 + 合并 | `layer5_orchestrator/planner.py`、`editor.py`、`driver.py`、`tests/test_draft_v15_schema.py` |
| **P2-T5** | `rag.rule_top_k`(5, 3–8) 与 `vlm_review{enabled,max_shots}`；`gen_specs` 同步 | `contracts/config.py`、`specs/config.default.yaml`、`tests/test_config_vlm_review.py` |
| **P3-T1** | 拍点表 → actions 的确定性编译与合并 | `layer5_orchestrator/beat_compiler.py`（新建）、`tests/test_beat_compiler.py` |
| **P4-T1/T2** | 规则包（强度标 / 条数预算 / 冲突并陈 / 自由度声明） | `knowledge/rulepack.py`（新建）、`tests/test_rulepack.py`；接线 `knowledge/client.py`、`knowledge/retriever.py`、`layer5_orchestrator/headless_runner.py` |
| **P4-T3** | forbid 反查补挂（守门激活）＋ trace 两键 | `knowledge/hypergraph.py`、`knowledge/client.py`、`tests/test_forbid_guard_backfill.py` |

## 2. 治理事件：冻结仪器换代（第二十八次）

**背景**：`block_director/knowledge/hypergraph.py` 在 `tests/plan_v4_instruments.sha256.json`
里是**冻结仪器**（第二十七次冻结起）。P4-T3 要求在检索装配期做 forbid 补挂，
必然改动 `Hypergraph.retrieve` 与 `RetrievalTrace`。

**处置**（按该文件自带的规矩：有意改动 → 单独显式重新冻结并写明理由）：

```
HEAD  sha256 = c353217361fa62e2f72df435598da18c25c5b78b8e04039ff02073818b3c2d73  (== 冻结值)
WORK  sha256 = 91802481f96e9afecae63c690f64242af833caba79be7c18dd1e7bd6647f7127
```

**被守的三样一个字未动**（证据：diff 全部落在 `:962` 之后）：

```
git diff -U0 -- block_director/knowledge/hypergraph.py | Select-String '^@@'
@@ -962,0 +963,10 @@ class RetrievalTrace:
@@ -978,0 +989,2 @@ class RetrievalTrace:
@@ -1324,0 +1337,60 @@ class Hypergraph:
@@ -1371,0 +1444,8 @@ class Hypergraph:
@@ -1372,0 +1453,3 @@ class Hypergraph:
```

槽位闭集（`NODE_TYPES`/`QUALIFIER_KINDS`/`EDGE_TYPES`）、`validate_edge()`、
`schema_fingerprint()` 的实现与取值全部原样；复算：

```
python -c "from block_director.knowledge import hypergraph as h; print(h.schema_fingerprint())"
1a90c089bb8f4f7fbd61a145a2088d6c2628ecbbd4dba47f63396fbf34fadaf3
```

⇒ 写入 `tests/plan_v4_instruments.sha256.json` 的 `_reason_28`，并更新该文件的
哈希与 `_frozen_at`（第二十八次）。**这是一次有意的、非判据的仪器换代**，
已按要求单独留痕，供用户复核。

## 3. 阶段门 G2 读数（契约层升级后）

```
python tools/gen_specs.py --check   -> [OK] specs/config.default.yaml 与代码一致
python tools/gen_golden.py --check  -> [OK] Golden 夹具与 plan_simple.json 一致
python -m pytest                    -> 2609 passed, 1 skipped   (exit 0)
```

1.4 兼容：`tests/test_sdl_15.py::test_migrated_14_project_validates_clean` 与
`test_migrated_14_to_15_only_fills_defaults` 全绿（旧字段逐字节不变、新字段缺省）。

## 4. golden 夹具重生成（红线 R-11）

`fixtures/tool_transcript_simple.jsonl` / `expected_sdl_simple.json` /
`expected_sdl_long.json` 随 Plan 字段与 SDL 1.5 **重生成**。重生成前的结构 diff：

```
ADDED: data/plan/environment, data/plan/shots[]/beats, .../composition,
       .../rule_justifications, data/shots[]/{beats,composition,rule_justifications}
REMOVED: （无）
version: 1.4 -> 1.5
environment.anchors = []   environment.light = {}
```

⇒ **只有版本号与新增可选字段**，无删除、无改名，符合 R-11。

## 5. 卡与代码现状不符（如实记）

1. **P3-T2 的"白名单"**：卡文要求把 `BD_Anchor_` 前缀接进导出审计 helper 白名单；
   实测 `collection_router.audit_renderable_objects()` 对 `EMPTY` 类型直接跳过
   （`block_director/layer3_engine/collection_router.py:180` 附近），且锚点经
   `mark_as_guide` 后 `hide_render=True` ⇒ 不会被判泄漏。**不改白名单**。
2. **P2-T2 的 openapi 同步**：`specs/openapi.yaml` 只覆盖 sidecar 线协议
   （`ChatRequest`/`RetrieveResponse`/`HyperEdge`/`Case` 等 DTO），**不含 Plan/SDL**；
   `tests/test_openapi_matches_contracts.py` 的映射表里也没有 Plan。
   ⇒ 本卡无 openapi 改动可做（不是漏做）。
3. **P1-T2 的 `P14-295`**：卡文写"P14-295 两节撞号"，实测撞号的是
   `P14-292`×2 与 `P14-293`×2，295 只有 `:1801` 一节；且字面 `"P10 待处置"`
   在台账里**不存在**。两处按"不重编号、不臆造"处理，并在编者注中如实记录。
4. **P4-T3 的落点**：TDD §5.6 写"在 `knowledge/retriever.py` 装配阶段"，
   但真实运行里超图由 sidecar 侧执行 ⇒ 补挂必须在 `Hypergraph.retrieve`
   （服务端也在用同一份实现），否则只修了本地路径、服务端仍无守门能力。
   因此落点选 `hypergraph.py`，并触发上面的第二十八次显式重新冻结。

## 6. P3-T1 的**生产消费者**（拍点真的生效了）

`compile_beats` / `merge_with_actions` 一开始**只有测试在调用**——拍点表进了
计划也**不产生任何动作**（静默空操作）。本批在 `layer3_engine/shot_builder.py::build_scene`
里把它接上（构建期、拿到已解算锚点与"这一镜开始时人在哪"之后做一次），
结果直接喂给既有 `action_requests`，下游零改动。

Blender 实测（`work/_probe_beat_wiring.py`，非注册探针）：

```
& "D:\Blender 5.2\blender.exe" --background --factory-startup --python work/_probe_beat_wiring.py
BD_BEAT_WIRING {"without_beats": {"keyframes": 342, "motors": 0, "anchor_objects": ["BD_Anchor_door"]},
                "with_beats":    {"keyframes": 618, "motors": 1, "anchor_objects": ["BD_Anchor_door"]},
                "beats_change_keyframe_count": true}
BD_BEAT_WIRING_OK
```

⇒ ①带拍点 ⇒ 动作数 0→1、关键帧 342→618；②`behind char_001` 的锚点真的落成
`BD_Anchor_door`（Guides 集合、`hide_render`）；③**空 beats 路径**仍是
`motors: 0`（既有行为，标签烘焙的 342 帧与走位无关）。

## 7. 自动派发 hook（用户 2026-10-07 要求）

新增 `tools/hooks/`（可版本化镜像）＋ 安装到 `~/.codex/hooks/`：

| 文件 | 作用 |
|---|---|
| `dispatch-board.ps1` | 读 `执行文档v1.5/dispatch_graph.json` ＋ `docs/evidence/_v15_dispatch/` 的 done/claim 标记，算出**现在能安全并行派发哪些任务卡**；`-Claim/-Mark/-Unclaim/-DryRun/-Status` |
| `dispatch-board.md` | 中文模板（`.ps1` 只做占位符替换 ⇒ 脚本保持 ASCII-only） |
| `dispatch-board.selftest.ps1` | 16 项 hermetic 自检（**16/16 通过**） |
| `dispatch_graph.json` | 27 张卡 ＋ 8 道门的机器可读 DAG（与 EXECUTION_PLAN 附录 A/B 同源） |
| `tests/test_dispatch_graph.py` | 图的结构守卫（ID 唯一／依赖存在／无环／并发上限／阶段门存在） |

**四条硬边界**（越界就不派）：依赖未满足 / 写集与在飞卡相交 / `mode≠auto`
（`serial` 同文件双写、`user` ⚖️ 须用户裁决、`gate` 阶段门）/ 并发到顶。
不满足就退回串行——**宁慢不乱**。

## 8. P5-T2 的前提被证伪（实测复核）

卡 P5-T2（FX-2）的前提是"**132 张手写策展卡不在索引里**（覆盖 2221/2353）"。
本批**独立复核**（命令与读数）：

```
python -c "import json; ref=set(); [ref.add(str(s.get('card_id') if isinstance(s,dict) else s))
    for l in open('knowledge/hypergraph.edges.jsonl',encoding='utf-8') if l.strip()
    for s in (json.loads(l).get('sources') or [])]; print(len(ref))"
-> 2262                      # 被 >=1 条边引用的卡
# knowledge/cards_generated/*.jsonl -> 2221 张生成卡
# block_director/knowledge/corpus.HANDWRITTEN_CARDS -> 132 张手写卡
-> 手写卡中零边者：16        # 116/132 已被引用
```

并且**该卡要求的动作已经在 HEAD 上做完**：`tools/kb_fetch/build_hypergraph.py::load_cards()`
（`:2001` 起，`git status` 未列为改动）会把 `HANDWRITTEN_CARDS` 逐张并入输入，
并合成如实出处（`chunk_id = curated/<id>`、`provenance = 权威文档`）。

⇒ ①`2221` 是 `K1_source_ref_complete` 的"**生成卡出处完整性**"分母，**不是**
索引覆盖数（`AGENTS.md:56` 曾把它当覆盖数，已改正）；②真正剩下的缺口是
**16 张手写卡零边（＋75 张生成卡零边）**，属"索引生成/抽取"问题，
与卡文写的"132 张没进管线"是两件事。完整分析见
`docs/evidence/20261007-v15-closeout/adjudication_p5t2_index_regen.md`。
