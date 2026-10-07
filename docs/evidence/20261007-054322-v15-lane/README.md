# v1.5 车道记录（P1-T3 / P2-T1 / P3-T1 / P4-T1·T2·T3）

**run-id**：20261007-054322-v15-lane
**HEAD**：`f6530c6`（+ 本轮未提交改动）
**执行者**：子 agent `/root/audit_spec`

本目录只记**这一条车道**做掉的卡与实测读数。全程遵守红线 R-1…R-11；
**未做任何 git commit**。

---

## 1. 完成的卡

| 卡 | 落点 | 新增测试 |
|---|---|---|
| **P1-T3** AGENTS.md 状态块读数刷新 | `AGENTS.md` 的 `最新，以这行为准` 块改写为 2026-10-07 实测；旧 2026-10-05 段降级为「历史，只作存档」 | `tests/test_agents_status_is_current.py`（3 条，全绿） |
| **P2-T1** 拍点与三个规格类 | `block_director/contracts/beats.py`（新）；`block_director/motion/model.py` 增 `enter_from`/`exit_frame`/`place_prop`/`pick_up`/`hand_to` 的 `LAYER_OF`/`ACTION_PARAMS`/`expand()` 分支与 `FORBIDDEN_PAIRS` 条目 | `tests/test_beats.py`（17 条） |
| **P3-T1** 拍点 → actions 编译器 | `block_director/layer5_orchestrator/beat_compiler.py`（新） | `tests/test_beat_compiler.py`（20 条） |
| **P4-T1/T2** 规则包 | `block_director/knowledge/rulepack.py`（新）；接线 `knowledge/client.py::render_edge_block`、`knowledge/retriever.py::edge_columns`+`_hypergraph_block`、`layer5_orchestrator/headless_runner.py`（`rule_top_k`） | `tests/test_rulepack.py`（14 条） |
| **P4-T3** forbid 反查补挂 | `knowledge/hypergraph.py`（`RetrievalTrace.forbid_backfilled`/`forbid_members_seen` + `_forbid_guard_edges` + 注入排序）；`knowledge/client.py` 的 `retrieval_call` 事件同步两键 | `tests/test_forbid_guard_backfill.py`（6 条） |

## 2. 实测读数（命令 + 输出）

```
python -m pytest            -> 2636 passed, 1 skipped in 174.83s   (EXIT=0)
python -m pytest tests/test_beats.py tests/test_beat_compiler.py \
    tests/test_rulepack.py tests/test_forbid_guard_backfill.py \
    tests/test_agents_status_is_current.py -q -> 60 passed          (EXIT=0)
python -m pytest tests/ -k "plan or sdl or beats or rulepack or beat_compiler
    or editor or planner or knowledge or motion or driver or scene or forbid
    or hypergraph or config or golden or fixtures or openapi or contract
    or lighting or staging or framing or composition" -q -> 972 passed (EXIT=0)
```

基线（本版开始前，`docs/evidence/20261007-050254-baseline/`）：**2492 passed /
1 skipped**。⇒ 本车道**无新增失败**。

## 3. 卡文与仓库现状的两处出入（如实记录，未自行改设计）

1. **卡 P2-T2 第 5 步**"`specs/openapi.yaml` 同步（新字段 optional）"：
   `specs/openapi.yaml` **没有 Plan/ShotPlan/SDL 的 schema**（`tests/test_openapi_matches_contracts.py`
   的 `SCHEMA_TO_MODEL` 只列 sidecar 线协议 DTO）。该步在当前仓库**不适用**，
   **未新造 schema**（新造会变成第二真源）。
2. **卡 P4-T5 的光线种子**：卡文要求"先核对 `VALUE_DOMAINS["lighting"]` 的闭集"，
   而 `hypergraph.VALUE_DOMAINS` 里**没有 `lighting` 键**（`lighting` 是
   `NODE_TYPES` 里的**自由值**节点，没有闭集可核）。按卡的纪律"取值不在闭集内
   就不写"，`光线=` 种子在本版**不会**发出 ⇒ **FR-3 的检索侧通路是惰性的**。
   这是**待裁决项**（要么给 `lighting` 定闭集、要么改成"按索引节点表核值"），
   未自行拍板。

## 4. 已知未接线（交给主线/别的车道）

* `layer5_orchestrator/beat_compiler.py::compile_beats` **还没有被任何生产代码调用**
  （`rg "compile_beats" --glob "!tests"` 零命中）。TDD §6 第 5 步要求
  "合并回 ShotPlan → beat_compiler 编译出 actions"，这一步**未落地**：
  当前 `editor.merge_draft` 只把 `beats` 落到 `ShotPlan.beats`，
  而 `shot_builder.action_requests` 只读 `shot.actions` ⇒ **拍点表目前不产生任何动作**。
  接线位置应在 `driver`/builder 拿得到锚点坐标与角色当前位置的那一刻
  （`shot_builder.action_requests` 已经有 `cast` 与 `live_from`）。
* `knowledge/retriever.py` 的 `rule_top_k` 只在 `headless_runner` 接线；
  面板/其它构造点仍走 `default_retriever` 的缺省 5（与配置缺省一致，行为无差）。

## 5. 未验证 / 剩余风险

* 未跑 `tools/run_tests.ps1`（阶段门 G1…G7 由主线集中跑；本节只记 pytest 读数）。
* 未做端到端真跑（真实模型）——`forbid_members_seen > 0` 的**运行侧**验收
  （G4）需要三份冻结工程同代重建，不在本车道。
* 本车道写入时，仓库里另有并行车道在改 `driver.py`/`editor.py`/`scene_executor.py`
  等共享文件；本车道**刻意回避**了这些文件（除 `headless_runner.py` 的一行接线），
  以免互相覆盖。
