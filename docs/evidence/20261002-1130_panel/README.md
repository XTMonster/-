# 证据：门⑥ 的"面板旁证不可复现"（2026-10-02）

## 结论

`knowledge/card_scope.json` 的分母**不是**由模型判读决定的——判据是确定性的索引证据
（`tools/kb_fetch/card_scope_audit.py` 的 `scope/v3`：全语料抽取对该卡零条边 ⇒ 不进分母）。
这份目录是那条设计决定的**直接证据**：把同一批卡、同一个提示、`temperature=0`、
同一对模型连跑两遍，模型给出的类别会变。

## 命令（可复现）

两份产物是**同一条命令跑两遍**得到的，只有输出文件名不同：

```
python tools/kb_fetch/card_scope_audit.py \
    --out work/_scope_runpair_baseline.json \
    --panel-only @<21 张卡的名单> \
    --panel-out docs/evidence/20261002-1130_panel/panel_run_a.json \
    --control 0 --edge-control 0
```

名单（21 张，就是门⑥ 当时缺卡的那一批）：

```
gen_anime_0309 gen_anime_0406 gen_axis_0300 gen_axis_0308 gen_block_0030
gen_block_0048 gen_block_0339 gen_cine_0073 gen_cine_0199 gen_cine_0247
gen_story_0020 gen_story_0033 gen_story_0064 gen_story_0065 gen_story_0066
gen_story_0068 gen_story_0107 gen_story_0110 gen_story_0111 gen_story_0113
perf_conflict
```

## 两次运行的对拍

| | 值与上一次**相同** | 值变了 |
|---|---|---|
| `deepseek-chat` | 21 | 0 |
| `glm-4.7-flash` | 11 | **10** |

10 次翻转**全部是同向的**：GLM 把 `not_expressible` 翻成 `shot_language`。

| 卡片 | 第一次（run a）GLM | 第二次（run b）GLM | DeepSeek（两次相同） |
|---|---|---|---|
| `gen_story_0020` | `not_expressible` | `shot_language` | `manuscript_format` |
| `gen_story_0033` | `not_expressible` | `shot_language` | `casting` |
| `gen_story_0064` | `not_expressible` | `shot_language` | `manuscript_format` |
| `gen_story_0065` | `not_expressible` | `shot_language` | `manuscript_format` |
| `gen_story_0066` | `not_expressible` | `shot_language` | `shot_language` |
| `gen_story_0068` | `not_expressible` | `shot_language` | `manuscript_format` |
| `gen_story_0107` | `not_expressible` | `shot_language` | `manuscript_format` |
| `gen_story_0110` | `not_expressible` | `shot_language` | `manuscript_format` |
| `gen_story_0111` | `not_expressible` | `shot_language` | `manuscript_format` |
| `gen_story_0113` | `not_expressible` | `shot_language` | `shot_language` |

## 这对判据意味着什么

如果按"两名审查员都判范围外才剔"来缩小分母，这 10 张卡会**随抽取批次的不同在分母里
进进出出**——同一个索引、同一份 oracle、同一份实现，门⑥ 的分子分母会变，验收结论
也跟着变。这不是"严格一点/宽松一点"的问题，是判据不可复现。

所以 `scope/v3` 把判据换成确定性信号（索引对该卡零条边），并且给分母补了下界
（`tools/check_holdout.py::MIN_EXPRESSIBLE_SHARE = 0.95`，实测 2083/2113 = 98.6%）：
没有下界，"零条边的卡不进分母"这条规则能自己把自己解开（把抽取关掉 ⇒ 分母空 ⇒ 门绿）。

## 未验证 / 风险

* 两次运行之间，`knowledge/hypergraph.*` **确实被另一个 lane 改过**
  （落地 `allow` 落体判据）。这对拍**不**依赖索引：面板只看卡片正文，不看索引；
  两次的 `models`、提示、卡名单逐字相同（见两份 JSON 的 `models` 与 `controls`）。
* 只跑了 2 遍、21 张卡。翻转率是这 21 张上的实测值，不是对全语料的无偏估计。
* GLM 用的是 `GLM_THINKING=disabled`（该模型开思考时单批要数分钟，跑不动两遍）。
  开思考是否更稳定，本目录**没有**测。
