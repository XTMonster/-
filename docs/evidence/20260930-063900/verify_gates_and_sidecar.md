# 独立对抗性验收：门有没有牙齿 ＋ sidecar 能力位两态

执行者：`/root`（非实现者）。目的：把"实现者自报的绿"与"真的能翻红"分开。
日期：2026-09-30 06:39（本机，Windows PowerShell，Blender 5.2，Ollama 0.34.3）。

## 1. sidecar 的能力位是两态的（真起 HTTP，不是看代码）

```powershell
python tools/sidecar_server.py --port 8799 --knowledge-dir <空目录>
# -> {"sidecar": "listening", ... "capabilities": ["llm", "bm25"]}
curl.exe -s http://127.0.0.1:8799/health
# -> {"status": "ok", "version": "1.3.0", "capabilities": ["llm", "bm25"]}
curl.exe -s -X POST http://127.0.0.1:8799/v1/retrieve -d '{"query":"emotion=荒诞","top_k":3}'
# -> cards 有 3 条（BM25 兜底）；"edges": [], "cases": [];
#    trace.backend="bm25", cases_degraded=true, cases_degraded_reason="cases_index_missing"

python tools/sidecar_server.py --port 8798 --knowledge-dir knowledge
# -> "capabilities": ["llm", "bm25", "hypergraph"]
```

结论：索引缺失时不宣告 `hypergraph`（不是"宣告了却回空数组"）；案例通道缺失时
`cases_degraded=true` ＋ 具名原因，`cases[]` 为空且不报错。

## 2. 超图通道确实能出边（用协议规定的中文键）

```powershell
curl.exe -s -X POST http://127.0.0.1:8798/v1/retrieve -d '{"query":"景别=MS","top_k":3}'    # selected 3
curl.exe -s -X POST http://127.0.0.1:8798/v1/retrieve -d '{"query":"情绪=荒诞","top_k":3}'  # selected 3
```

同进程复核：`parse_query("景别=MS") -> {"shot_size": ["MS"]}`，
`seeds=[applies_to_shot_size:MS, shot_size:MS]`，`selected=3`。
用英文键（`shot_size=MS`）会解析成空查询——`q` 的键集是冻结的中文那一套（协议 §2.1）。
这不是缺陷，但它意味着任何用英文键造出来的 held-out 都会把 Q4 打成 0，
所以生成器 prompt 必须把中文键印给模型。

## 3. 覆盖门有没有牙齿（单点破坏 -> 必须翻红）

方法：拿一条真实产出的条目（来自 `holdout_fill` 的 partial），每次只破坏一处，用
`tools/check_holdout.py --pilot --vocab fixtures/knowledge_holdout.vocab.json --cards <与条目同源的卡片集>`
跑。`--pilot` 把门限降到 1（协议内的试点模式），只用来观察"这一门会不会翻红"，
不作为验收结论。

| 破坏 | gate_1_total | gate_2_format | gate_5_forbid | gate_5b | gate_6_sources | gate_7_human | gate_3 |
|---|---|---|---|---|---|---|---|
| 基线（未复核） | pass | pass | pass | pass | pass | fail | fail（样本只 1 条） |
| must 用词表外取值 | pass | fail | fail | fail | pass | not_measured | fail |
| review.reviewed_by=agent | pass | pass | pass | pass | pass | fail | fail |
| review.reviewed_by=human | pass | pass | pass | pass | pass | pass | fail |
| must 有 forbid_* 但 q 里没有同值 | pass | pass | fail | pass | pass | fail | fail |
| top1 不在 must 里 | pass | fail | fail | fail | pass | not_measured | fail |
| 不传 --vocab / --cards | pass | pass | pass | pass | — | fail | not_measured |

结论：

* 门② 会翻红（格式与 `top1` 一致性）；门⑤ 按 Q7 冲突的机械定义翻红（`q` 与该条
  `must` 的 `forbid_<kind>=<value>` 必须同 kind 同值）；门⑥ 在卡集与条目同源时 pass；
  门⑦ 只认 `review.reviewed_by="human"`，写成 `agent` 一律 fail。
* 缺 `--vocab`/`--cards` 时门③/⑥ 是 `not_measured`，不是 pass（§4.1b 硬规则 1）。

## 4. 本地标注器：思考税实测（本轮最贵的一条）

`qwen3-vl:30b`（`bd-annotator:8k` = 同样模板 + `PARAMETER num_ctx 8192`），
`num_predict=2048`、`num_ctx=8192`，同一份 holdout prompt：

| 变体 | sec | eval_count | content_len | thinking_len | done_reason |
|---|---|---|---|---|---|
| 基线（thinking 默认） | 26.3 | 2048 | 0 | 3674 | length |
| user 末尾 /no_think | 26.3 | 2048 | 0 | 3418 | length |
| system 末尾 /no_think | 26.6 | 2048 | 0 | 3928 | length |
| think: false | 26.3 | 2048 | 0 | 3548 | length |
| 1 张卡 + 精简词表 | 26.6 | 2048 | 0 | 3375 | length |
| num_predict=6144（同基线） | 81.7 | 6144 | 0 | 16000 字符 | length |
| assistant 预填（JSON 数组开头） | 4.7 | 355 | 962 | 0 | stop |

结论：官方三条关闭开关在本机确实全部无效（与 §6 的记录一致）；但 assistant 预填可以
让同一个模型直接续写答案，思考税归零。预填不会被回显（Ollama 只回续写：head 是
换行加 `"from_card"` 那一行、tail 是 `]}`），所以解析时要先按原文试、失败再把预填
贴回去，两次都失败才算调用失败。

端到端验证：`holdout_fill.py --batch 1 --rounds 0` 得到 entries=1、rejects=1、
format_ok=true、q7_conflicts=1、needs_human=1（此前恒为 entries=0、rejects=2）。
