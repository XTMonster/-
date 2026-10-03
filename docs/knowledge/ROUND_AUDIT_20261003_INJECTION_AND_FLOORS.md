# 轮次审计（2026-10-03）：两条 §4.1b 判据**没有执行者**，以及 Q5 的真正缺口

审计角色：**验收口径与测量完整性**（只读审计；不改判据、不改门限、不重标 oracle）。
测量时的树：`HEAD 0d39739` ＋ 同批 `意图轴`（`ShotPlan.intent_type` → `意图=`）的
在途改动。全部数字都用仓库自己的工具复算过，命令与输出在每节里。

---

## 0. 复现的现状（不是照抄文档）

```text
python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab ... \
    --assertable ... --reviewer-classes human,llm-panel --exclude-cards knowledge/card_scope.json
  -> overall: pass（gate_1…gate_10 全 pass）
python tools/holdout_score.py --holdout fixtures/knowledge_holdout.jsonl --json <tmp>
  -> exit 0（Q1 0.9975 / Q2 1.0 / Q3 0.0 / Q4 1.0 / Q6a 1.0 / Q6b 1.0 / Q7 1.0）
python tools/knowledge/quality.py --run-id recon2 --cases knowledge/cases.jsonl \
    --e1-reviews docs/evidence/20261003-e1-zh/reviews.jsonl \
    --shots docs/evidence/20261003_real_long/export/shots.json \
    --audit-log docs/evidence/20261003_real_long/audit_log.jsonl
  -> Q0–Q4、Q6a/Q6b、Q7、Q4_pre、E3、E3_cases、K1–K4 全 pass
     Q5 fail（fixture_items 70 / fixture_plan_shaped 70 / run_denominator 0）
     E1 fail 3/18 = 0.1667（sample_floor 1200、差 1182、sample_floor_met false）
     E2 not_measured（诊断量，不设门）
python tools/knowledge/hard_gates.py --report <tmp>
  -> not passing: Q5,E1; not measured: E2
python -m pytest -q -> 全绿（在**干净的** HEAD 0d39739 上实测；在途的意图轴改动
                          落盘于 15:09–15:11，晚于那一次跑，见 §5 的会话说明）
```

## 1. 发现 A：意图轴**不足以**解锁 Q5——它的合格池里 70/70 都带 `镜头=`

Q5 的运行侧只 join **带 `expect_movements` 的条目**
（`tools/knowledge/quality.py:258-265`：`values = entry.get("expect_movements")`，
为空就 `continue`）。所以"意图轴让 176 条 oracle 可 join"这句话**不能**推出 Q5 转绿。

实测（`fixtures/knowledge_holdout.jsonl`，2847 条）：

```text
q 里出现 镜头= 的条目                 247 / 2847
q 的键集 ⊆ 引擎运行期可表达键空间      176 / 2847   ← 全部是 {意图, 景别, 运镜}
  …其中带 expect_movements 的          0 / 70      ← Q5 的**合格池**一条都不在里面
```

而真实发出的查询里 `镜头=` **结构性缺席**（`docs/evidence/20261003_real_long/audit_log.jsonl`：
65 条 `retrieval_call`，`镜头=` 0 条；`景别=`/`运镜=` 各 65 条）。stage A 的计划 schema
没有 `camera`（`block_director/layer5_orchestrator/planner.py::_SHOT_ITEM_SCHEMA`，
`additionalProperties: false`），v1.2 §7.2 的分镜计划 schema 也没有焦段
（`BlockDirector_执行文档_v1.2.md:878-898` 的 JSON 例）——焦段只在 B1 草案的
`camera.lens`（`BlockDirector_执行文档_v1.2.md:872`）里，那是**逐镜检索之后**。

**风险提示**：`tools/knowledge/quality.py:75-85` 的 `PLAN_QUERY_KEYS` 现在含 `镜头`，
于是 Q5 报告里的 `fixture_plan_shaped` 是 **70**（静态键集意义上的"形状合格"）。
那是**上界**，不是可达性：运行期根本没有 `镜头=`。报告里必须同时看
`run_denominator`（现在 0）。用 `fixture_plan_shaped` 单独下结论会把"形状合格"
读成"可 join"。

**要 Q5 有分母，只有两条**（都不属 agent 可自行决定的范围）：
1. **重标合格池**：把 `expect_movements` 标注改挂到落在运行期键空间里的条目上
   （`INTENT_PACK` 那 176 条是唯一候选）。属 oracle 变更 ＋ 需要换族标注通道
   （本机 `GLM_API_KEY` 未设置，见 §5）。
2. **改引擎契约**：让检索前就有焦段（剧本声明焦段或先解算再检索）——改检索预算
   `retrieval_calls ≤ (2+N)×lanes` 与 prompt 时序，属规格裁决。
   （"剧本声明的拍摄手法"这一半已由 §四十落地，可复用同一条管线。）

## 2. 发现 B：§4.1b 的 **Q3 下界**写着 `max(50, 0.25 × query 数)`，全仓没有执行者

* 规格：`改进执行文档v1.4.md:1450`；该表抬头写着"**不满足即该 RK/指标判失败**"
  （`改进执行文档v1.4.md:1442`）。
* 实现：`tools/holdout_score.py:424` 只算**误命中率**（`kind="max"`），
  `:439-446` 的下界块只覆盖 `Q1/Q2`（`MIN_QUERIES=1200`）与 `Q4`
  （`MIN_REQUIRED=200`）；`_metric`（`:241-256`）只处理 `denominator <= 0`。
* `rg -e '0\.25' tools/` 找不到任何负样本下界常量或判据。
* 现状不会因此变红：实测 `negative_pairs = 2767 ≥ max(50, 0.25 × 2847 = 712)`。
  但把 oracle 换成"负样本极少"的一代时，Q3 会以 3/4 条样本报 pass——那正是
  分母下界要防的形态。

## 3. 发现 C：§4.1b 的 **Q6b「读数通道」**（读真实 prompt）没有执行者

规格行：`改进执行文档v1.4.md:1454`——"**必须读实际发给模型的 prompt**
（`llm_trace.jsonl` 的 `prompt`），**不得**读 `knowledge_trace` 的自述；并断言注入
token **整场 ≤ `rag.plan_prefetch_tokens`（默认 2000）**、**每镜 ≤
`rag.max_tokens_per_call`（默认 800）**（是两个键，不是一个），
`required_edges_dropped_by_budget` 由 prompt 里实际缺失的 required 边独立计数"。

全仓 `rg -e llm_trace -e plan_prefetch_tokens -e required_edges_dropped`（排除 `docs/`、
`work/`、`.scratch/`）只命中：切片工具 `tools/extract_run_evidence.py`、面板
`block_director/layer7_ui/panel_debug.py`、Blender 探针 `tools/blender_tests/test_llm_trace.py`
与若干 pytest——**没有任何判据读真实 prompt 量这四件事**。Q6b 现在由
`tools/holdout_score.py:388` 用 `render_edges` 对**夹具自己的 `q`** 重渲染来判，
不是真实运行的那条 prompt。

**可行性已实测**（本轮原型，未入库）：知识块在 prompt 里是机械可定位的——
以 `参考资料…：` 那段为起点，其后**连续以 `【` 或 `[` 开头的段落**都是知识栏
（`【硬约束（禁/许）】`／`【经验建议（软）】`／`【参考案例（仅参考）】`／
`【卡片正文补充】` 及其条目），遇到第一段不是这两种开头的段落即结束。用
`block_director/knowledge/tokens.estimate_tokens` 计数，三份入库真实运行：

| 证据目录 | `purpose=plan` 的注入 token（上限 2000） | `purpose=editor`（每镜上限 800） |
|---|---|---|
| `docs/evidence/20261003_real_long/` | 1 条，**775** | 64 条，166–**784** |
| `docs/evidence/20261003_real_ds/` | 1 条，**614** | 6 条，226–**786** |
| `docs/evidence/20261003_real_glm/` | 1 条，**614** | 6 条，742–**787** |

结论：**上限今天真的在约束**（最高 787/800，余量只有 13 token），这条审计不是空转；
而 `required_edges_dropped_by_budget` 那半边的 join 数**是 0**（与 §1 同一个
入口形状问题），只能如实记 `not_measured`，不能记 pass。

## 4. 发现 D：E1 的 1200 样本下界"报了但不判"——这是口径二义，需裁决

* 规格把两个数写在同一格：`改进执行文档v1.4.md:1468` 的"返回的 `cases[]`
  总数 **≥ 1**（判分样本 ≥ 1200，R50）"，而表头（`:1442`）说"不满足即该
  RK/指标判失败"。
* 实现按"绑定 **≥1**"读：`tools/knowledge/quality.py:651-657` 报出
  `sample_floor/sample_shortfall/sample_floor_met`，但 `status` 只由
  `value >= 0.70` 决定；`tests/test_knowledge_quality.py:187` 明确钉住
  "判定不许因为样本量而改变"（4 条样本 0.75 记 pass）。
* 两种读法今天**都不改变**结论（E1 已经是 fail 0.1667）；差别在"将来小样本
  高命中率是否可能被读成 pass"。这一条不该由实现单方面挑一个读法。

## 5. 环境与阻塞（本轮实测）

```text
$env:GLM_API_KEY = <unset>      # 只有 DEEPSEEK_API_KEY（len 35）
$env:BLENDER_EXE = <unset>；默认候选里 D:\Blender 5.2\blender.exe 存在
```

没有非 DeepSeek 族通道 ⇒ **换族标注/复核**（Q5 的 `expect_movements` 重标、
gate⑦ 残件、E1 面板重打分、任何索引换代后的 oracle 重标）在本机跑不动。
`embedding-3` 不可用一事业已在 `AGENTS.md` 记录（E1 只能从语料/查询同层入手）。

## 6. 建议动作（按性价比，落到具体文件与行）

1. **先补两条没有执行者的判据**（不依赖任何 key，且对今天的账是零回归）：
   * Q3 下界：`tools/holdout_score.py` 增 `MIN_NEGATIVE_FLOOR = 50` /
     `NEGATIVE_FLOOR_SHARE = 0.25` ＋ 一个纯函数（`max(50, ceil(0.25×queries))`），
     在 `:439-446` 那个下界块里对 `negative_pairs` 执行；先红用例写进
     `tests/test_holdout_score.py`（该文件已有负样本用例 `:137`，扩它即可）。
   * Q6b 读数通道：新增 `tools/knowledge/injection_audit.py`（纯 Python、无 bpy），
     读 `--llm-trace`，按 §3 的定位规则取块、用 `tokens.estimate_tokens` 计数、
     上限从 `block_director/contracts/config.py` 的
     `rag.max_tokens_per_call`(800)/`rag.plan_prefetch_tokens`(2000) 取；
     token 部分判**硬**（今天三项全在限内：775/2000、最高 787/800），
     required 半边如实记 `not_measured` ＋ `joinable_calls=0`；产物按
     `knowledge_attestation.json` 的形状落 `docs/evidence/<run-id>/injection_audit.json`
     并在 `tools/run_tests.ps1` 的知识块里要求它存在（照 P14-30/31 的先例）。
     用例：正控（合规块 → pass）＋ 反控（把块加长到超限 → 必红）。
2. **Q5**：先把 §1 的两个数字写进报告（`fixture_plan_shaped` 是上界，
   `run_denominator` 才是判据），再请用户裁决"重标合格池"或"改引擎契约"。
   **不要**把意图轴当成 Q5 的修复。
3. **E1**：把 §4 的二义并进待裁决清单；语料一侧（现代、逐镜分析的 L3 来源）
   与换族重打分同批做，缺 `GLM_API_KEY` 时不要动 `knowledge/cases.jsonl`
   （会让现有 E1 证据变 stale，红得更多而不是更少）。
