# `action` 值域：从"标签垃圾桶"到可见行为闭集（审计 #16 关闭）

这份文件记一次**索引级**修复的完整证据链。它回答三个问题：缺陷长什么样、
怎么修、修完以后哪些数字变了、代价是什么。

## 一、缺陷

`action` 是 `ACTION_BEAT`／`PERFORMANCE_PACK` 的**必填**槽位
（`block_director/knowledge/hypergraph.py::REQUIRED_MEMBERS`）。旧实现
（`tools/kb_fetch/vocabulary.py` 第 4 步）为了"让必填槽位有的可填"，把
performance／blocking 域卡片里**长度 ≤6 的 tag 全部**铺成 `action:` 节点——
而 tag 是卡片生成模型写的**话题词**。

抽查一张卡就看得出来：`gen_block_0048` 的 tag 决定了它会得到
`ACTION_BEAT:action=协作,beat_type=coverage,intensity=low` ——
"协作"不是任何演员能在镜头前做出来的动作。

实测（修复前，索引 837 条边）：

```
action 节点            343 个，其中只有 7 个来自受控表
带"非动作 action"的边   258 / 837（30.8%）
  ACTION_BEAT          131 条（占该类型的 69%）
  PERFORMANCE_PACK     127 条
取值榜                动作×41、反应×27、出场×24、克制×15、准备×14、
                      人物塑造×12、入场调度×10、动作设计×10 …
```

关键点：**抽取提示早就写了规则 8b**（"`action` 只能是看得见的身体行为，
卡里没有就别写这类边"），但**节点表把话题词当成了合法取值**，模型自然照抄。
所以修的地方不是提示，是词表。

## 二、修法（审计 `AUDIT_TRIAGE.md` #16 的选项 3 → 1）

1. **候选集与旧规则同源**：`tools/kb_fetch/action_lexicon.py::candidates()`
   用的就是旧规则会铺成节点的那些 tag（339 个）。
2. **判据由抽取族模型逐词执行**：判据写死在 `SYSTEM` 里
   （"演员／角色在镜头前看得见、能表演出来的身体行为"），由 DeepSeek 对
   每个候选给出 `accept` ＋ **不超过 20 字的理由**。
3. **结果钉进仓库**：`knowledge/action_lexicon.json`，带 `_provenance`
   （模型、判据、提示 sha256）。增量合并**只判新词**——这条不是洁癖：
   同一条判据重跑，第二次就把 `肢体语言`／`情绪姿态` 从 rejected 翻成
   accepted。词表是索引的输入，抖动会让语料/索引无法复现。这两个词由人工
   复核钉成 rejected，理由写在 `_provenance.human_review` 里。
4. **代码层再钉一遍类别词**：`动作`／`运动`／`行为`／`表演`／`动作组` 是
   "自身就是类别词"的取值，查询写成 `动作=动作` 没有任何信息量，
   `VACUOUS_ACTION_WORDS` 无条件拒绝。
5. **`vocabulary.build_nodes` 只收两份来源**：受控表 `ACTIONS` ＋ 判定通过的
   词。**读不到词表文件时只回落受控表**，绝不回落到那条 tag 规则。
6. **闭到索引的环**：抽取器提出、但节点表没有的行为（实测 3 个：
   `奔跑`／`拿起`／`颤抖`）交给同一条判据复核，通过的进词表、然后只重抽
   涉及的那 3 张卡 —— "抽取器提议 → 判据复核 → 进词表"是闭环的。

## 三、结果

全量重抽（`--replace-cards <2113>`）＋ 一轮 `--only-missing` 补边之后：

| 量 | 修复前 | 修复后 |
|---|---|---|
| 超边 | 837 | **766** |
| 原子边 | 2948（v8 2748 ＋ v10 200） | **2836（全部 v10）** |
| `action` 取值 | 35 个，其中 16 个不是动作 | **20 个，全部是行为** |
| 带非动作取值 `action` 的边 | 258 | **0** |
| `ACTION_BEAT` / `PERFORMANCE_PACK` | 190 / 160 | 107 / 103 |
| 必填槽位填不满而被拒的原子边 | 2（旧口径不查回读的边） | **71**（如实记账） |
| `forbid` 成员 | 28 | **49**（v10 纪律现在覆盖全部卡） |
| 池能覆盖的卡（门⑥ 的分母侧） | 2041 / 2113 | **2058 / 2113** |

最后一行是这次修复最反直觉的地方：**清掉 258 条污染边之后覆盖率反而上升**。
原因是原来那些卡里，有相当一部分**只有**一条污染边（238 张卡属于
"被污染边掩护着"）；词表修好以后，全量重抽 + 定向补边让它们拿到了
**语义正确**的边。实测口径见 `work/gap_cards5.txt` 与
`docs/knowledge/ACCEPTANCE_STATUS.md` 的新一轮快照。

## 四、代价与残余

* **`ACTION_BEAT` 少了 84 条**：这是审计 #16 明写的代价（"必填槽位填不满 →
  整条边丢弃"）。规则 8b 认为"卡里没有可见行为就不该写这类边"，
  所以这不是召回丢失，是**把不成立的边去掉**。
* **仍有 27 张卡在索引里一条边都没有**（`gen_cine_0004` 之类的胶片染色工艺、
  `gen_comp_0254` 之类的绘画技法、`gen_prod_0014` 的电气布线）：它们的知识
  不是"视频制作"层面的，与 16 类边的 schema 天然不匹配。
  这是**语料 ↔ schema 的适配缺口**，不是实现缺陷。
* **`action` 词表是一个召回上限**：模型只能从表里挑。要扩表就走第 6 条的闭环
  （抽取器提议 → 判据复核 → 进词表），不要退回 tag 规则。

## 五、可复现命令

```powershell
# 1. 词表：候选 → 判据 → 钉进仓库（需要 DEEPSEEK_API_KEY）
python -m tools.kb_fetch.action_lexicon --provider deepseek --model deepseek-chat
# 增量补词（@文件，中文不要走命令行）
python -m tools.kb_fetch.action_lexicon --extra "@work/action_extra.txt"

# 2. 节点表 + 抽取词表
python -m tools.kb_fetch.vocabulary

# 3. 重抽（全量清洗 / 只补没有原子边的卡）
python -m tools.kb_fetch.build_hypergraph --provider deepseek --replace-cards work/all_cards.txt --concurrency 16
python -m tools.kb_fetch.build_hypergraph --provider deepseek --only-missing --concurrency 12

# 4. 冻结词表 + 可断言对（索引换代后**必须**重跑，门③/门④ 的分母跟着变）
python -m tools.knowledge.holdout_vocab --cards fixtures/knowledge_holdout.cards.json --out fixtures/knowledge_holdout.vocab.json
python -m tools.holdout_pool --mechanical --assertable-out fixtures/knowledge_holdout.assertable.json --out work/pool_mech.jsonl
```

对抗性用例：`tests/test_action_lexicon.py`（候选集同源、污染词被拒、
入库节点必须来自词表、词表缺文件时回落受控表、增量合并不重判已钉住的词）。
