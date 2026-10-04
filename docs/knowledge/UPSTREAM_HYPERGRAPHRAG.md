# 上游留档：HyperGraphRAG / LightRAG（**已读、未移植**）

这份文件是 ADR-0014 的证据附件：**读了什么、读到哪一层、为什么现在不移植**。
它是"许可与出处"的落点，不代表已经引入任何上游代码。

## 一、读过什么（只读，未拷贝任何代码进本仓库）

| 上游 | commit | 许可 | 读过的文件（行数） | 结论 |
|---|---|---|---|---|
| `LHRLAB/HyperGraphRAG` | `d587cdf8c3fe` | **MIT** | `hypergraphrag/prompt.py`(351)、`hypergraphrag/operate.py`(1,124)、`hypergraphrag/hypergraphrag.py`(550) | 值得移植的只有**不含 embedding 的那一层**；现在**缓议**（触发条件见 ADR-0014 附表） |
| `HKUDS/LightRAG` | `453dce83d6d0` | **MIT** | `lightrag/prompt.py`(901)、`lightrag/operate.py`(**7,127**) | 只看提示词层；检索层要 embedding，不碰 |

原始回包与文件清单：`work/upstream_files.json`、`work/graphrag_survey.json`、
`work/hypergraph_search.json`、`work/hypergraphrag_repo.json`、
`work/hypergraphrag_deps.json`（均在 gitignore 的草稿区）。

## 二、为什么"缓议"而不是"现在就移"

1. **移植的验收有一个静默失败模式**（联合会诊 GLM 侧的 blocker）：
   `tools/kb_fetch/build_hypergraph.py:182` 的 `PROMPT_VERSION = "extract/v18"` 与
   `:252` 的**八分量 `cache_key`**——换了提示词而**没 bump 版本分量**时，断点续跑会命中
   旧缓存，新提示词**从未执行**而 `pytest` 全绿。所以任何移植的**第一条验收必须是
   "manifest 指纹已变化"**，排在跑测试之前。
2. **归并/去重那层不是"漏掉的便宜移植面"**：本仓的归并窗口是"同 `domain` ＋ 一跳
   `related` 闭包 ＋ 每批 ≤8 张卡"（`build_hypergraph.py` 的批处理），与上游按实体名
   并点的语义不同源；改它必然 bump 第 7 个指纹分量，并连锁改动 E1 的代际钥匙。
3. **当前瓶颈不在这里**：红门是 `E1`（语料适配度）与 `RK-13`，不是"边抽得不够多"。
   按 hook 的表，魔改的优先级排在"语料／查询同层"之后。

## 三、将来真移植时的规矩（写在这里，动手时照着做）

1. **只移一段**（优先"一个文件／一段算法"），**不拉整库**；上游版本与 commit 写进本节。
2. **保留版权声明与许可证全文**（MIT）；在 `docs/knowledge/LICENSES.md` 记出处。
3. **第一条验收＝`cache_key` 指纹已变化**；随后跑全套 `pytest` ＋ `tools/run_tests.ps1`，
   **判据与阈值一字不动**；把与上游的差异落成差异清单。
4. **不许**把"把上游的数据模型翻译成本项目的槽位模型"记成"复用"——那层翻译是自研
   （ADR-0014 的判例）。
