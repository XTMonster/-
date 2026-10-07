# 裁决项：C6「16 条 `amended` 的 `fix` 文本落地」——**卡与现状不符，升级给用户**

**run-id**：_v15_stage8/c6_layer_fix
**卡**：`执行文档v1.5/TECH_SOLUTIONS.md` §三 **C6**（分档写的是"✅ 可执行（机械）"）
**性质**：⚖️ **须用户裁决**。执行方**只备料**：索引、夹具、层文件**一个字节都没动**。
**纪律**：R-5（判据不动）、R-8（换代必须显式登记）、A1（E1/RK-13 已结案、判据冻结）。

---

## 1. 卡文要求（逐字）

> **C6（16 条 amended 的 fix 文本未生效）——✅ 可执行（机械）**
> 方案：层是输入工件，把 16 条 fix 文本应用到对应层文件，重跑该层校验；前后 diff 落证据。

## 2. 实测：这条"机械动作"其实是**换代**

```
python -c "...读 fixtures/knowledge_holdout.third_party.jsonl..."
-> rows 212：accepted 194 / rejected 2 / amended 16；16 条 amended **全部**带非空 fix
```

**"层"是被 pin 的 gate 输入**——层自己带的 manifest 逐字写着：

> `"note": "**这一层是 gate 的输入之一**：pin 它 = pin 这一代；旧夹具的字节不动。"`

而它与 oracle 夹具的 sha256（前 16 位）与门⑦ gen2 登记里的 pin **逐字符一致**：

```
fixtures/knowledge_holdout.third_party.jsonl  eda380e4c4dd54f5   （登记：third_party: eda380e4…）
fixtures/knowledge_holdout.jsonl              e3e6bac24d9efcfe   （登记：holdout:     e3e6bac2…）
```

⇒ 按 `tools/check_holdout.py` 的 `--third-party` 机制与门⑦ 那次裁决
（pin 绑"运行↔输入"，gate 输入一旦含增量层即是那一代），**改层的字节 = 换一代**：
已入库运行的 `run_manifest.json.pins.third_party` 会**失配**
（`tests/test_run_generation_registry.py` 会当场红），必须走 A6 登记 + 最小重跑。
**口径更正**：台账/清单里写的"23 份运行 pin"**实测是 22 份**
（`docs/evidence/_v15_stage8/c5_superseded/superseded_audit.json`：
`runs_with_holdout_pin = 22`）——**以 22 为准，不凑数**。

**第二条不符**：16 条 `fix` 是**散文建议**，不是可机械套用的补丁。逐条原文见
`amended16.json`（同目录），例如：

| entry_id | fix（原文） |
|---|---|
| `hq_1809` | 把 `expect_movements` 改为空列表 `[]` |
| `hq_1819` | 把 `expect_movements` 改为空列表 |
| `hq_1869` | `expect_movements` 改为 `["tilt_up"]` |
| `hq_1881` | 把 `q` 里人给的 must/top1 的 movement 统一改为 `crane_arc_up` |
| `hq_1882` | 把 `q／must／top1` 的 `crane_arc_up` 全改为 `crane_arc_down`（其余保留） |

它们要改的是 **oracle 夹具**（`knowledge_holdout.jsonl`）里的 `expect_movements` / `q`，
也就是 **E1 与门①–⑩ 的判分输入**。而 A1 已把 E1/RK-13 **结案为"现行判据下不可达"**，
门⑦ 的整套机制（层 + 代登记）存在的**全部意义**正是"**旧夹具的字节不动**"。

## 3. 两条路线与代价（供裁决）

| 路线 | 做法 | 代价 | 风险 |
|---|---|---|---|
| **A（推荐：换代 gen3，只动层）** | 把 16 条 fix **结构化**落进**层**（例如给该条记录加 `fix_applied: {...}` 与 `applied_at`，或直接改 `verdict` 为 accepted 并附实证），**夹具 oracle 仍一字不动**；随后按 A6：登记 gen3 → 更新 `pins.third_party` → 最小重跑（门⑦ + Q1/Q2/Q4/Q6b 同口径 + 一次链） | 换代登记 + 一轮最小重跑（链约 30 min） | 中：23 份历史运行需如实标"异代"，不许 repin 洗白 |
| **B（不换代，写明"fix 不生效"）** | 维持现状：层只提供 `verdict`，`fix` 保持"**记录而不生效**"（报告里 `fixes_applied: false` 如实写） | 零风险 | —— |
| **C（把 fix 套进 oracle 夹具）** | 直接改 `knowledge_holdout.jsonl` | **判据面**：等于改 E1/门①–⑩ 的判分输入 | ⛔ **不建议**：与 A1 结案、门⑦ 设计、R-8 同时冲突 |

## 4. A6 预填登记表（只在用户选 A 时使用）

| 字段 | 值 |
|---|---|
| 换代原因 | C6：把层里 16 条 `amended` 的 `fix` 结构化落地（**只改层，不改 oracle 夹具**） |
| 前指纹 | `third_party = eda380e4c4dd54f5…`（实测，与 gen2 登记一致） |
| 后指纹 | **待生成**（本卡未执行） |
| 影响面 | 已入库运行的 `pins.third_party` 失配（实测 22 份带 `holdout` pin）；门⑦ 需在新代下重跑 |
| 最小重跑集 | 门⑦（`check_holdout --third-party <新层> --generations <登记表>`）＋ Q1/Q2/Q4/Q6b 同口径 ＋ 一次全链 |
| pin 处置 | 旧运行**如实标"异代"**，**不 repin 洗白**（`repin()` 会拒） |

## 5. 本卡为什么**没有**按卡文动手（如实记）

卡文把 C6 分到"✅ 可执行（机械）"，但实测它同时满足两条"必须停手"的条件：
①**要改的是被 pin 的 gate 输入**（R-8：换代必须显式登记）；
②`fix` 是散文、且其中数条要改的是 **oracle 夹具**（A1 已结案冻结的判分输入）。
按注入契约"差异属于判据/门槛的一律升级给用户"，**停手备料**是唯一正确动作。

## 6. 证据指针

- `fixtures/knowledge_holdout.third_party.jsonl`（212 行；16 条 amended）
- `fixtures/knowledge_holdout.third_party.manifest.json`（`pin 它 = pin 这一代`）
- `tools/check_holdout.py`（`apply_third_party_layer`；`fixes_applied=False`）
- `tests/test_run_generation_registry.py`（每份运行必须解析到已登记代）
- `docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md:2172-2174`（台账自己写明"16 条 fix **没有**拿去改夹具"）
- 本目录 `amended16.json`（16 条原文，UTF-8 可读）
