# 第三方给 D13 的**可证伪触发器**：实测**没有触发** ⇒ D13 = A（P10 不切换）

日期 2026-10-06。第三方在带理由的裁决里把 `D13 = A`（P10 不切换、门①–⑩ 按现役代验收）
写成**可证伪的**：只有当 **v4 的 top-20 相关均值 ≥ 现役 ＋ 0.30**、且能回填 oracle 时，
才允许改判 B。这份目录就是那个触发器的读数。

## 命令（两个语料层各跑一次，同一批 64 条冻结查询、同一面板、同一 `--top-k 20`）

```powershell
python -m tools.knowledge.e1_panel --queries work/eval_sets/heldout_v4_long21.jsonl `
    --cases-dir knowledge --out work/ab_e1_candidates/current.top20.rep1.jsonl `
    --top-k 20 --workers 8 --adapter none
```

（v4 那一侧用 `--cases-dir work/knowledge_v4_cases`，即 `docs/evidence/20261006-e1-ceiling/`。）

## 读数（每查询在 top-20 里的相关行数；相关 ＝ 两位评委均值 ≥ 4.0）

| 语料层 | `cases_fingerprint` | 文件 | 相关行 | precision@20 | **均值 / 查询** | 中位数 | ≥3 相关 | 0 相关 |
|---|---|---|---|---|---|---|---|---|
| **现役代**（`knowledge/`） | `48df4a53…` | `reviews.current.top20.rep1.jsonl`（本目录，sha256 `08746037…`） | 219 | 0.1711 | **3.422** | 3.0 | 42 | 1 |
| v4（`work/knowledge_v4_cases`） | `4b1b44bb…` | `docs/evidence/20261006-e1-ceiling/…rep1.jsonl` | 178 | 0.1391 | **2.781** | 3.0 | 38 | 4 |
| v4（同一命令第 2 跑） | `4b1b44bb…` | `docs/evidence/20261006-e1-ceiling-noise/…rep2.jsonl` | 176 | 0.1375 | **2.750** | 2.5 | 32 | 5 |

复算入口：`python tools/knowledge/e1_ceiling_report.py --top-k 20 <上面三个文件>`

## 判定

触发器要求 **v4 ≥ 现役 ＋ 0.30**，实测是 **v4 比现役低 0.64（run A）～ 0.67（run B）**——
方向相反，量级差得远。

⇒ **触发器不响，D13 = A 维持原判**：P10 **不切换**，门①–⑩ 继续按现役代验收，
v4 只作影子对照。（第二个条件"能回填 oracle"因此无需再测。）

**顺带一个值得记账的事实**：v4 的**边**是现役的 7.8 倍（5,000 / 638），
但它的**案例层更小**（783 vs 1143），在这批查询上的 top-20 召回**反而更低**。
=> "边多"没有转化成"检索面更好"；这正是第三方把 D13 判成 A 的理由（可断言面薄一个量级），
现在有了直接读数。

**未验证**：现役代这一跑只有 1 次（它的重复跑没做）；上面的跨跑极差（每查询均值 0.67）
是从 v4 的两跑推的，现役侧的实际极差**未测**。这条不影响方向（差 0.64 远大于 0.67 的
噪声量级也只够抵掉一半），但**要引用精确差值时应当补重复跑**。
