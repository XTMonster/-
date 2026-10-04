# long15：真跑样例请求了**超图**——Q5 第一次**有分母**

**一句话**：`fixtures/*.config.yaml` 把 `rag.backend` 写死成 `bm25`，而 v1.4 §2.3 与
出厂默认要的是**超图**。`bm25` 走插件进程里的内置卡片检索、**不发 `/v1/retrieve`**，
于是 ① L1/L2 的 `forbid` 那栏从来没进过提示词、② 审计里一条 `retrieval_call` 都没有
（long14 六十四镜实测 `retrieval_calls: 0`）⇒ §4.1b 的 **Q5 结构性没有分母**、
E2 结构性恒为 0。改掉后端之后这两条**第一次量出了真数**。

## 现场（long14 vs long15，同一条命令、同一份剧本）

| | long14（`bm25`） | **long15（`hypergraph`）** |
|---|---|---|
| `knowledge.backend` | `bm25` | **`hypergraph`** |
| `retrieval_calls` | **0** | **68**（上限 `(2+64)×2 = 132`） |
| 审计 `retrieval_call` 事件 | **0** | **68**（5 次整场预取 ＋ 63 次逐镜） |
| 逐镜查询长什么样 | 不发 | `景别=LS；意图=揭示；运镜=固定` |
| **Q5** | `not_measured`（分母 0、`channel: absent`） | **`fail` 3/9 = 0.3333**（线 0.80，`channel: audit`，64 个逐镜事件） |
| **E2**（诊断，不设门） | 恒 0 | **4/64 = 0.0625**（有 4 镜的运镜取自经验/案例层） |

Q5 的那 9 对是"发出的串与 held-out 的 `q` **键值对集合完全相等**"的那些镜头——
54 条恒真的旧标注不算进来。3/9 意味着**同值的 9 次里只有 3 次真的采纳了那条边**：
判据一个字没动，读数第一次是真的。

## 这一趟本身

`run_id d4eccc5efc7b`、`state=DONE`、`built=true`、交付 **133** 个文件、
LLM **272** 次调用（上限 512）、LLM 墙上时间 478.8 s、工具 200 次、审计 179 次。
终审**逐镜通过 29/64**；错误 COMPOSITION 25、R001 25、R003 6、R011 1；构图分中位
**74.3**、构图门 **39** 镜。R001 的 warning 从 long14 的 63 条降到 **31** 条。

> 别拿 long14 ↔ long15 的逐镜通过互比"哪个修更值"：**长跑方差很大**（模型每跑写不同
> 草案），这两趟的 R001（13 → 25）和构图门（40 → 39）反向动就是它的表现。这一页的
> 结论只关于**知识栈有没有真的接上**——那是 0 与 68 的差别，不是 29 与 29 的差别。

## 复算

```
python tools/extract_run_evidence.py --run-id d4eccc5efc7b \
    --out docs/evidence/20261004_chunked_long15 \
    --audit-log .../runs/runs/audit_log.jsonl --llm-trace ... --shots .../shots.json
python tools/knowledge/quality.py --run-id d4eccc5efc7b --json \
    --cases knowledge/cases.jsonl --e1-reviews docs/evidence/20261003-e1-zh/reviews.jsonl \
    --shots docs/evidence/20261004_chunked_long15/export/export/shots.json \
    --audit-log docs/evidence/20261004_chunked_long15/audit_log.jsonl \
    --out <report>.json      # → Q5: fail 3/9 = 0.3333
```

守门：`tests/test_real_run_sample_configs.py`（两条真跑样例必须请求 `hypergraph`，
且与 `AppConfig().rag.backend` 一致——样例与出厂默认不许各说一套）。

## 仍未解决（如实记）

* **Q5 现在是 fail，不是 not_measured**：这是进步（量得到）也是坏消息（只有 33%）。
  运行侧分母 **9** 偏小，根因是 join 要求**逐字相等**——`q` 点名了被量的字段
  （`运镜=`）本身就让大多数条目不可比，`docs/knowledge/Q5_DECISION_v1.md` 的出路②
  仍待裁决；
* **E1 = 3/18 = 0.1667**（线 0.7），且判分样本 18 < §4.1b 下界 1200（差 1182 条）；
* `project.bdproj` 落盘校验报 7 条（S3 动作重叠 6、S6 对白装不下 1）——`save_run_project`
  如实带回结论、文件照写；
* `cases_backend` 实际走的 `hybrid`（LightRAG 不可用时的**允许**降级），
  但 `cases_degraded=false`——这一处口径值得下一轮单独核。
