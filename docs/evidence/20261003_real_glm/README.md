# `20261003_real_glm` — 一次**云端 GLM** 真实运行的证据（§4.4 步骤 2）

这份目录是 P14-5 里**唯一**能判 Q5 / E2 的那类证据：一次真实模型运行
（`glm-4.7`，经 `tools/sidecar_server.py` 走 `open.bigmodel.cn`），
剧本 `fixtures/shotlist_market.md`，6 镜 / 792 帧 / 33.0 s。

## 1. 这一跑是什么

| 项 | 值 |
|---|---|
| `run_id` | `5a18272e4a1d` |
| 终态 | `DONE`（`success: true`） |
| 步骤 / LLM 调用 / 工具调用 | 97 / **50** / 72（预算硬顶 120） |
| 镜数 / 总帧 | 6 / 792（33.0 s @24fps） |
| 修复 / 审计 / 未过审计 | 11 / 22 / 20 |
| 检索调用（`retrieval_call`） | **7**（1 次 plan scope ＋ 6 次逐镜） |
| 知识后端 | `hypergraph`（2353 张卡、`lanes=2`、案例层 `hybrid`、未降级） |
| 索引代际 | `hypergraph_fingerprint = c796a5a87018631db54da88406a4bd352741ed346fa1e9b06293c85ef46fed67` |
| 案例层代际 | `cases_index_fingerprint = 69791dbacabd3fd77e5132dea277664972a227d222b7be0c6c6841c5a7a6649e` |
| 墙钟 | 876 s |

交付产物在 `export/`（17 个文件：6 段 mp4 ＋ 6 张首帧 ＋ `blockout_full.mp4`
＋ `shots.json` ＋ `prompts.md` ＋ `README.md` ＋ `script_compliance.json`），
工程在 `project/project.bdproj`。**mp4 与 `first_frames/` 不入库**（`.gitignore`
与 `offline_run1` 同一条政策：可由命令逐字节重建）。

## 2. 证据清单（sha256 的**单一真源**是 `run_manifest.json`）

| 文件 | 是什么 | 谁读它 |
|---|---|---|
| `audit_log.jsonl` | 这 338 条事件的分片（**逐字节**从本机累积日志里按 `run_id` 挑行） | Q5 的 join 键（`retrieval_call.data.query`）、RK-18 的独立计数 |
| `llm_trace.jsonl` | 50 次调用的 prompt/response 分片 | §11.3 的 trace、Q6b 的"读实际 prompt"通道 |
| `knowledge_trace.json` | 这一跑最后一次检索的 trace（含六元 provenance） | 索引代际的旁证 |
| `export/shots.json` | 交付清单（顶层带 `knowledge` 块） | `quality.run_evidence_is_stale` 读它判代际；E2 读 `movements[].source` |
| `run_manifest.json` | 四个 sha256 ＋ 时间跨度 | `tools/extract_run_evidence.py --check` |

复算（在任何机器上，只要仓库这一份是当前代）：

```
python tools/extract_run_evidence.py --run-id 5a18272e4a1d --out docs/evidence/20261003_real_glm --check
python tools/knowledge/quality.py --cases knowledge/cases.jsonl \
    --shots docs/evidence/20261003_real_glm/export/shots.json \
    --audit-log docs/evidence/20261003_real_glm/audit_log.jsonl \
    --e1-reviews docs/evidence/20261003-e1-zh/reviews.jsonl --out work/_q5.json
```

## 3. 这一跑量出来的 Q5：**分母 0，判失败**（不是"测不了"）

`quality.py` 现在按 §4.1b 硬规则 2 只读**真实发出**的逐镜查询
（`audit_log.jsonl` 的 `retrieval_call.data.query`）：

```
shot_001 景别=MCU
shot_002 景别=CU；运镜=dolly_in；对白=dialogue
shot_003 景别=MCU；对白=dialogue
shot_004 景别=CU；对白=dialogue
shot_005 景别=MS；运镜=follow_subject
shot_006 景别=MCU；对白=dialogue
```

与 held-out 里那 70 条带 `expect_movements` 的 `q` 按"键值对集合相等"
匹配：**相等的 0 条、连子集也只有 0 条** ⇒ 分母为 0 ⇒ 按 §4.1b 硬规则 1
**判失败**（`Q5 = fail`）。夹具侧是达标的（70 ≥ 30），所以失败落在运行侧。

## 4. 顺带量出来的真缺陷：**"从 shots.json 重推"与"真实发出"是两回事**

同一跑 6 镜的**重推串**（`shot_constraint_query()` 打在收尾后的 `shots.json`
上）与发出串逐一对比——**6 镜全部不同**（`quality` 的 `drift` 字段）：

```
shot_001 发出 景别=MCU
         重推 景别=MCU；镜头=50mm；运镜=dolly_in；特效=smoke；特效=glow
shot_002 发出 景别=CU；运镜=dolly_in；对白=dialogue
         重推 景别=CU；镜头=85mm；运镜=dolly_in；对白=dialogue
```

根因是**时序**：逐镜检索发生在这一镜 editor 调用**之前**（那时 `camera`
还没被 `setup_camera`/`reframe` 与取景求解器写进去，`vfx`/`actions` 也还是
模型原样），而 `shots.json` 是**收尾时**的快照。所以"重推串"量的是另一次
运行——这正是 §4.1b 硬规则 2（禁止自证）不允许拿实现自报的汇总字段当判据
通道的原因。旧通道（重推）在这一跑上会报出"子集命中 4 条"的假数字，新通道
（audit）如实报 0。

## 5. 这一跑**不能**证明的事（照实记）

* **不证明 Q5 达标**：分母 0 就是失败。要让它有分母，夹具里那批 `q` 的键集
  必须能被真实计划的形状命中（见 `docs/knowledge/ACCEPTANCE_STATUS.md` 的
  待裁决清单）——那是标注/契约层面的决定，不是本文件能改的。
* **不证明计划质量**：这一跑 `audit_pass_rate = 0/5`、20/22 次审计未过、
  33 条 `loop_warning`、50 次 LLM 调用（上一跑 30 次）。模型这次很吃力
  （`react_invalid` 30 条）。Q5 只量"发出的查询能不能与人工期望对上"，
  与构图门（RK-10，P16）不是同一件事。
* **不覆盖 GUI 手工交互**：它是 headless 的 sidecar 通路。
