# 真缺陷（2026-10-03 实测，**尚未修**）：逐镜检索的查询串丢掉了**剧本声明的拍摄手法**

## 现场

`docs/evidence/20261003_real_glm/audit_log.jsonl`（run `5a18272e4a1d`）里逐镜
真正发出的查询：

```
shot_001 景别=MCU
shot_002 景别=CU；运镜=dolly_in；对白=dialogue
shot_003 景别=MCU；对白=dialogue
shot_004 景别=CU；对白=dialogue
shot_005 景别=MS；运镜=follow_subject
shot_006 景别=MCU；对白=dialogue
```

而 `fixtures/shotlist_market.md` 第 1 镜写得很清楚：

```
镜号：1
拍摄手法：固定镜头
```

声明是 **`固定`**，计划最后排的是 **`dolly_in`**（模型改了）——但**发出的查询
里两个都没有**，只有 `景别=MCU`。

## 为什么

`block_director/layer5_orchestrator/editor.py:242` 的逐镜查询是
`shot_constraint_query(shot)`，`shot` 是**阶段 A 的计划对象**。阶段 A 只把分镜表
的声明**渲染成文本**喂给模型（`planner.py:158` 的 `render_declared_shots`），
**没有把它写进 `shot.camera`**；而这一镜的 `camera` 是 B1 之后由工具调用与取景
求解器补上的。所以逐镜检索发生的那一刻，`shot.camera` 还是空的 ⇒ 契约串里没有
`运镜=`。

## 代价（两条，都是真的）

1. **检索锚点少一半**：超图那一栏是靠契约串挂种子的；没有 `运镜=固定`，这一镜
   拿不到"固定镜头"那族边的**硬约束与禁忌**。`declared_constraint_query()`
   （计划期预取用）**恰好是**按声明拼的（`scene_contract.py:150-153`），逐镜这条
   路却没有复用它——同一份信息，一条路用了，另一条没用。
2. **Q5 的入口形状被它绑架**：`q` 必须能与**发出的**串相等才 join 得上。发出的
   串如果只有 `景别`，那夹具就只能写 `景别=X`（见 `ACCEPTANCE_STATUS.md` §三十八：
   门⑨ 的可达性规则让这条路结构性走不通）。把**声明**放进检索前的契约串，`q`
   的空间才会随之扩大，Q5 也才有"声明 vs 计划"的对照意义。

## 建议的修法（下一轮做；**这一步不需要模型额度**）

`editor.build_editor_payload` 里把**这一镜的声明**也喂给 `shot_constraint_query`：
声明的 `shot_type` / `camera_move` 是**检索前已知的输入**，不是结果，把它写进契约串
不违反 §4.1b 硬规则 2（那条禁的是"读实现自报的汇总字段"，声明来自剧本）。

* 判据：改完之后真实运行的发出串应当出现 `运镜=<声明值>`；
* 验收：`E1`/`Q1`/`Q2`/`Q4`/`Q6b` 与 `tools/knowledge/ranking_quality.py`
  四项**都不许变差**（照 `f146de4` 那次的扫参口径）；
* 落地后**必须重审 Q5 的条目形状**（见 `ACCEPTANCE_STATUS.md` §38.3 的选项 1），
  别让两轮结论打架；
* 回归点：`tests/test_editor_contract_query.py`（若无则新建）＋
  `tests/test_q5_audit_channel.py`。

**注意**：端到端验证需要一次**修复后的真实运行**，而它要模型额度——2026-10-03
本轮结束时 **GLM 余额已耗尽**（`429 code 1113`，DeepSeek 仍可用），所以这条
停在这里；代码改动本身可以先落地并用离线夹具回归。
