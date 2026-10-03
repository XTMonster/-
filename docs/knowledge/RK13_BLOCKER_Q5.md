# RK-13 的最后一道**结构性**阻塞：Q5（2026-10-03 定稿）

## 一句话

把 E1 修好之后，**RK-13 仍然红**——而且不是实现问题、不是标注问题、不是门限问题：
**Q5 的运行侧分母在当前契约下可证恒为 0**（64 条真实发出查询、10 倍样本，结论不变）。
所以要让 RK-13 转绿，只能动**规格**或动**引擎契约**，两者都需要你点头。

## 证据链（都在库里，可复算）

| 环节 | 事实 | 证据 |
|---|---|---|
| Q5 是 RK-13 的判据之一 | §4.1 的 RK-13 写死 `Q5 ≥ 80%`；`Q5` 现在是 `hard_gates.HARD_IDS` 的成员 | `tools/knowledge/hard_gates.py` |
| join 键 = 真实发出的契约串 | §4.1b：`SceneContract` 查询串与本条 `q` 的键值对集合**相等**；硬规则 2 只允许读 audit 逐次事件 | `docs/knowledge/ACCEPTANCE_STATUS.md` §三十五 |
| 发出的串只有 `景别/运镜/对白` | 64 镜长剧本那跑，发出串形如 `景别=MS；运镜=固定`；焦段**不存在** | `docs/evidence/20261003_real_long/audit_log.jsonl` |
| 焦段为什么不存在 | stage A 的计划 schema 是 `additionalProperties: false` 且**没有 `camera`** ⇒ 检索那一刻计划里不可能有 lens | `block_director/layer5_orchestrator/planner.py::_SHOT_ITEM_SCHEMA` |
| 夹具那 70 条的 `q` 带 `镜头=` | 所以两边**永远不可能相等** | `fixtures/knowledge_holdout.jsonl`（`expect_movements` 那 70 条） |
| 实测：6 条与 64 条都是 0 | 6 镜那一跑：相等 0、子集 0；64 镜那一跑：同样 0 | `docs/evidence/20261003_real_ds/`、`20261003_real_long/` 的 `knowledge_quality.json` |
| 结构性证明 | 门⑨ 要求 `q` 覆盖 `must[0]`/`top1` 的必填可查槽位；按门⑨ 的真实口径重算，能把必填槽位塞进发出串的**只有 `AXIS_RULE`**，而索引里**不带 `axis_topic` 的 `AXIS_RULE` 是 0 条** | `ACCEPTANCE_STATUS.md` §三十八 + `tools/check_holdout.py::gate_9_reachability` |

## 三条出路（各自要动什么、代价是什么）

1. **动引擎契约（推荐给"提高质量"）**：让逐镜检索时的契约串带上**检索前已知**的更多信息。
   - 已经做掉的一半：**剧本声明的拍摄手法**（`ShotPlan.declared_camera_move`，§四十）。
   - 仍然做不到的一半：**焦段**——分镜表不声明焦段，stage A 的 schema 也不允许模型早给相机。
   - 若要走通，得改契约（例如"分镜表声明焦段"或"检索前先解算机位再检索"），
     两者都会改**检索预算**（§2.4 的 `retrieval_calls ≤ (2+N)×lanes`）与 prompt 时序。
2. **动规格**：把 §4.1b 的 Q5 行改成"join 空间 = 引擎在检索前能产出的键空间"，
   并据此重标夹具。⚠️ 注意：按 §三十八 的证明，**即便改了**，能塞进那个空间的边类
   只有 `AXIS_RULE`（且实例为 0 条）——所以只改这一句**不解决问题**，还得同时决定
   "Q5 到底该量什么"。
3. **把 Q5 从 RK-13 的判据里摘出来**（降级为诊断量，如实记录、不参与总判），
   理由写清楚：它的 join 空间在当前契约下不可达。代价：RK-13 少一条判据——
   这是**改验收标准**，必须你明确点头；本仓库在没得到授权前一直保持第 3 条的
   "如实记 fail"状态。

## 现在的状态（没动任何判据）

```
门①–⑩ 全 pass、K1–K4 pass、32/32 探针
not passing: Q5, E1      ← 只有这两条
Q5  fail（分母 0，按 §4.1b 硬规则 1；夹具侧 70 ≥ 30 达标）
E1  fail 0.1667（3/18；判分样本 18 < §4.1b 下界 1200，报告里已如实标出）
```

**只要 E1 修好而 Q5 不动，RK-13 就永远红**——这就是这份文件存在的理由。
