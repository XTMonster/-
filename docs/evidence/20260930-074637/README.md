# 全量验收证据（run-id `20260930-074637`）

`tools/run_tests.ps1` 在 commit `56a660d` 的代码上跑完 **31/31 全绿**，
本目录是它的收尾产物。

| 文件 | 说明 |
|---|---|
| `rks.json` | 19 条 RK 的聚合判定：**18 条已量、0 条失败**，唯一 `not_measured` 的是 **RK-13**（held-out 长跑尚未跑完） |
| `config.fingerprint.json` | 这次运行用的配置指纹（证据目录自描述，S13） |
| `knowledge_quality.json` | `python tools/knowledge/quality.py --run-id 20260930-074637` 的输出：**Q0 / E3 / E3_cases 全部 pass**，Q1–Q7 与 E1/E2 是 `not_measured`（helt-out 未完成 ／ 必须人工打分 ／ 需要一次真实运行），退出码 2 = 有证据缺失，**不是通过** |

同一次运行的其它事实：

* `python -m pytest` → **1261 passed**；
* L3 案例语料 `knowledge/cases.jsonl` → **733 篇**（`narrative=654 /
  sequence_pattern=7 / lesson=72`），`rejects/raw = 0.24%`，
  单文件 443 936 B < 512 KB；
* 与上一份证据（`20260930-063042`）相比，本轮**多修了三条真实缺陷**：
  软边的 `forbid` 被降级进"经验建议"栏、计划阶段的契约串没有生产者、
  以及 PowerShell 用 ANSI 解码探针的 UTF-8 标记导致 **RK-6/RK-8 静默变
  `not_measured`**（见 `.scratch/v1.4/plan.md` 与相关提交）。

仍未收口（如实记录）：`cast-panel` 与 `llm-trace` 两个探针的 `BD_TEST_RESULT`
负载仍解析不出来（转义层级不一致／残留乱码字节），证据留在
`work/probe_parse_fail-*.txt`；两者都**不承载任何 RK**，不影响验收判定。
