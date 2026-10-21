# BlockDirector 逐镜质量闭环：一手文献与仓库证据

日期：2026-10-21

范围：粗排/细排质量闭环、best-so-far 与回滚、程序测量、RAG 溯源、VLM 审查、
失败交付分类。

结论用途：为 `.scratch/blockout-quality-closed-loop/spec.md` 及其 tickets 提供依据。

## 1. 方法与边界

本轮按以下顺序取证：

1. 全量检查质量链相关模块、调用点、测试、配置、ADR 与真实运行证据；
2. 对论文标题、作者、时间与摘要回到 arXiv 原始页面或 DOI 出版页核验；
3. 把“文献直接支持的结论”与“针对本项目的工程判断”分开书写；
4. 不把论文结论外推成未经本项目实测的视觉艺术真值。

一手文献只能支持方法学方向，不能直接证明“80 分严格大于”“三帧足以判定电影构图”
或某个具体循环一定能收敛。这些是本项目已作出的产品/验收决策，必须由可执行测试、
真实模型运行和产物审计证明。

## 2. 文献结论

### 2.1 无梯度搜索可以逐次试探，但收敛性需要本项目自己的停止条件

Hooke 与 Jeeves 的 *Direct Search Solution of Numerical and Statistical Problems*
发表于 *Journal of the ACM* 8(2), 212–229, 1961，DOI
[10.1145/321062.321069](https://doi.org/10.1145/321062.321069)。论文研究不使用解析
梯度的直接搜索：逐次试探、比较并调整方向。

文献支持：

- 当目标函数只能通过程序测量得到时，可以采用“提议—测量—比较”的直接搜索；
- 搜索过程需要明确的方向、比较和停止规则。

文献不直接支持：

- 本项目的构图评分是平滑目标函数；
- 固定 50 轮、连续三轮无新高或重复状态检测一定最优；
- 低分版本应恢复哪一份世界状态。

工程判断：把每一镜视作一次受约束的状态搜索，显式保存 best-so-far，在低分、
平局、重复状态和预算耗尽时恢复最佳物理状态。停止条件必须由本仓库测试钉住，
不能从论文推导出一个“已证明正确”的阈值。

### 2.2 外部反馈比纯自我反思更可靠

Madaan 等，*Self-Refine: Iterative Refinement with Self-Feedback*，arXiv
[2303.17651](https://arxiv.org/abs/2303.17651)，2023-03-30。摘要报告：单模型生成初稿、
给出反馈并迭代改写，在七类任务上可优于单次生成。

Shinn 等，*Reflexion: Language Agents with Verbal Reinforcement Learning*，arXiv
[2303.11366](https://arxiv.org/abs/2303.11366)，2023-03-20。摘要强调语言 agent 可从外部
环境反馈形成反思并存入 episodic memory，在后续试次中改善决策。

Gou 等，*CRITIC: Large Language Models Can Self-Correct with Tool-Interactive
Critiquing*，arXiv [2305.11738](https://arxiv.org/abs/2305.11738)，2023-05-19。摘要明确：
模型通过工具交叉检查输出，再依据验证反馈修正；外部反馈是持续自我改进的关键。

Huang 等，*Large Language Models Cannot Self-Correct Reasoning Yet*，arXiv
[2310.01798](https://arxiv.org/abs/2310.01798)，2023-10-03。摘要指出：没有外部反馈时，
模型在推理任务上难以自我纠错，部分情况下自我修正后性能反而下降。

综合支持：

- 迭代反馈可以产生改进机会；
- 外部测量、工具验证和反馈记忆能补足纯语言自我判断；
- “模型说更好”不能代替外部验证。

综合不支持：

- 任意迭代都会单调改进；
- 反馈越多越好；
- 同模型自评足以决定最终交付。

工程判断：每一轮必须重新测量，不能用“已提出修改”当作“已改善”。只有通过程序
测量和完整门禁且优于当前 best 的版本才替换 best；无新高、平局或低分版本必须回滚
到最佳世界状态。

### 2.3 LLM/VLM 可作评审信号，不能独自充当硬门

Zheng 等，*Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*，arXiv
[2306.05685](https://arxiv.org/abs/2306.05685)，2023-06-09。摘要报告强 LLM judge 可与
人类偏好达到较高一致度，同时明确列位置偏差、冗长偏差、自我增强偏差和有限推理能力。

Chen 等，*MLLM-as-a-Judge: Assessing Multimodal LLM-as-a-Judge with Vision-Language
Benchmark*，arXiv [2402.04788](https://arxiv.org/abs/2402.04788)，2024-02-07。摘要报告：
多模态模型在 Pair Comparison 上较接近人类，但 Scoring Evaluation 与 Batch Ranking
与人类偏好有显著差异，并存在偏差、幻觉回答与判断不一致。

工程判断：

- VLM 的逐镜问题清单和相对比较有诊断价值；
- VLM 的绝对分数不能代替程序测量或唯一决定 hard gate；
- VLM 必须看到真实首/中/末帧，并同时收到可复算的程序测量事实；
- VLM 问题应转成 correction candidate，执行后重新测量；未执行、被拒绝、已解决和
  仍存在的问题都要有 disposition；
- 程序测量与 VLM 判断冲突时保留双方证据，硬事实优先，不能由模型改写数值。

### 2.4 RAG 需要检索质量评估、注入溯源与知识边界

Lewis 等，*Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*，arXiv
[2005.11401](https://arxiv.org/abs/2005.11401)，2020-05-22。摘要指出：显式非参数记忆可
改善知识密集任务，同时把 provenance 和知识更新列为开放问题。

Asai 等，*Self-RAG: Learning to Retrieve, Generate, and Critique through
Self-Reflection*，arXiv [2310.11511](https://arxiv.org/abs/2310.11511)，2023-10-17。摘要
指出：无论是否需要都固定注入固定数量段落会降低模型的可塑性，甚至产生无用回答；
系统应按需检索并反思段落相关性。

Yan 等，*Corrective Retrieval Augmented Generation*，arXiv
[2401.15884](https://arxiv.org/abs/2401.15884)，2024-01-29。摘要指出 RAG 高度依赖检索
文档相关性；需要评估检索质量，并在检索结果不佳时采取纠正动作。

Es 等，*Ragas: Automated Evaluation of Retrieval Augmented Generation*，arXiv
[2309.15217](https://arxiv.org/abs/2309.15217)，2023-09-26。摘要把 RAG 评估拆成检索
相关性、生成器是否忠实使用上下文、生成质量三个维度。

工程判断：

- 每次真实发生的检索都必须有 query、scope、shot、命中 id、实际注入 token、dropped
  内容和 backend/degraded 状态；
- provenance 只能引用真正进入提示词的条目，不能把“召回了但被预算丢弃”写成“采纳”；
- 空命中、零注入和降级也要留证，否则无法解释质量为何没有改善；
- plan、editor、粗排处方、细修、React 等每个实际消费知识的阶段都要同源记账。

### 2.5 推理必须与外部动作交错，事实性需要验证

Yao 等，*ReAct: Synergizing Reasoning and Acting in Language Models*，arXiv
[2210.03629](https://arxiv.org/abs/2210.03629)，2022-10-06。摘要报告推理轨迹与外部动作
交错可帮助跟踪和更新计划、访问知识库或环境，并减少纯思维链中的幻觉和错误传播。

Huang 等，*A Survey on Hallucination in Large Language Models*，arXiv
[2311.05232](https://arxiv.org/abs/2311.05232)，2023-11-09。摘要把“看似合理但事实错误”
与事实性区分，并讨论检测、基准和缓解方法，也指出 RAG 仍有限制。

工程判断：agent 的“我改好了”必须落成实际工具调用和新的测量结果。完成本轮闭环的
最小证据链是：

`观察 -> 提议 -> 应用 -> 重测 -> 比较 -> 保留/回滚 -> 记录 disposition`

只保存建议文本、只发生 LLM 调用或只记录一次构建结果，都不构成质量闭环。

## 3. 仓库证据

### 3.1 细排不是逐镜闭环

`block_director/layer5_orchestrator/detail_pipeline.py` 当前只执行一次：

1. 从冻结基准派生细排镜表；
2. 重建场景并应用一次 beats；
3. 刷新构图；
4. 逐镜 review；
5. 序列 review；
6. final gate。

没有逐镜 propose/apply/remeasure/compare/retain 循环，也没有保存每镜 best。文件头仍称
构图为 warning，而实际 `detail_review` 已把构图不足算作失败，文档与行为不一致。

`tests/test_detail_pipeline.py` 只 mock 构建、构图刷新和序列审查边界，证明的是 gate
接线，不是闭环收敛、回滚或 shot isolation。

### 3.2 粗排循环缺少最佳物理状态

`block_director/cinema/coarse_loop.py` 每轮记录“修改前”的 report，但没有：

- 最佳 reference / manifest / world snapshot；
- 低分或平局后的物理恢复；
- 连续 N 轮无新高早停；
- 重复状态指纹与周期振荡检测；
- 阻塞时与最佳版本的明确关联。

`docs/evidence/20261020-market-real-final16/coarse/coarse_pipeline_report.json`
已有跑满 50 轮仍未过门、shot_002/003 反复修改的实测记录。

### 3.3 driver 与 UI 仍是两套质量引擎

UI 的完整流程直接调用专用粗排/细排管线；driver 则另有计划级三态回溯、逐镜 React
best/no-gain/revert 与恢复能力。两套路径的评分、循环、停止条件、证据与最终身份没有
统一契约。

这会造成同一场景经 UI、driver、headless 三个入口得到不同质量结论，且无法从产品层面
回答“最终采用哪一版、为什么、是否可恢复”。

### 3.4 ShotVersion 证据不足

`block_director/layer5_orchestrator/shot_versioning.py` 当前版本只保存：

- plan；
- build summary；
- audit summary；
- adversarial summary；
- reason 与 created_at。

缺少 reference/manifest slice、runtime world snapshot、首/中/末帧、完整分数与 gates、
RAG provenance、VLM review、correction proposal/disposition、best 标记和交付身份。

已有 `contracts/backtrack.py`、`contracts/world_state.py` 与
`layer3_engine/world_state.py` 提供三态裁定、世界状态采集和恢复基础，但尚未汇入统一
证据版本库。

### 3.5 构图门仍有多个数值真源

正确语义已在 `block_director/cinema/composition.py` 定为：

```python
PASS_SCORE = 80.0
score > PASS_SCORE
```

仍然分散定义的消费者/文案至少包括：

- `block_director/cinema/coarse_revision.py`；
- `block_director/cinema/prescription.py`；
- `block_director/layer5_orchestrator/driver.py` 的粗排计划评分；
- `block_director/delivery/failures.py` 的数字与 README 文案；
- `tests/test_coarse_loop_soft_composition.py` 的测试 helper。

`delivery/failures.py` 的 README 还写成“≥ 80”，与“80.0 必须失败”矛盾。
`docs/adr/0012-composition-gate-and-assertion-hygiene.md` 仍保留旧 `>= 70.0` 口径，
已被 2026-10-18 用户裁决取代。

边界必须固定为：

| 分数 | 结果 |
|---:|---|
| 79.99 | fail |
| 80.00 | fail |
| 80.01 | pass |

### 3.6 真实运行证据暴露质量与账实问题

`docs/evidence/20261021-final16b-detail-render-r5/detail_review.json` 的七镜构图为
70.0、73.7、77.7、77.7、80.0、77.4、77.7，全部 `ok=false`。其中 shot_005=80.0
却记录 `composition_warning=false`，说明该证据来自旧实现，不能充当当前代码终验。

`docs/evidence/20261021-deepseek-real-run/`：

- 四镜 best 分为 58.8、43.3、74.3、20.0；
- no-gain 分别为 3、4、3、3；
- 失败清单与 diagnostic 视频已产出；
- 但同运行的 `coarse_pipeline_report.json` 记录 `coarse_status=approved`、
  `phase=BASELINE_FROZEN`、`rounds=[]`，而 `blockout_report.json` 四镜构图是
  77.7、20.0、77.4、20.0。

这是“低分仍冻结”的严重账实矛盾，必须由当前代码真实模型复跑和端到端守恒测试排除。

### 3.7 RAG 注入真实发生但审计断账

`docs/evidence/20261021-deepseek-real-run/knowledge_trace.json` 同时写着：

- requested backend = hypergraph；
- actual backend = bm25；
- degraded = true；
- retrieval_calls = 0；
- shot_scope / plan_scope 为空。

同运行的 `audit_log.jsonl` 没有 `retrieval_call`，`vlm_review_round` 与 `guard_verdict`
也为 0。但 `llm_trace.jsonl` 中 plan prompt 与四个 editor prompt 确有“参考资料”知识块。

根因在 `block_director/knowledge/retriever.py`：BM25 的 `block_for_plan()` 与
`block_for_shot()` 直接调用 `self.block()`；只有 hypergraph/client 路径通过
`KnowledgeClient` 增计数并写 `retrieval_call`。知识确实注入，审计却称没有检索，
provenance 因此结构性不可信。

### 3.8 视觉审查能力存在但主链未消费

仓库已有：

- `contracts/vlm_review.py` 的首/中/末帧请求、结构化 issue、score/history/disposition；
- `layer3_engine/shot_auditor.py` 的取帧与 VLM 记录；
- `layer5_orchestrator/correction_candidates.py` 的几何告警与 VLM issue 合并；
- `layer5_orchestrator/repair.py` 的候选注入。

真实四镜运行的 `blockout_report.visual_states` 有 12 个预览帧，但全部
`reviewed=false`，审计也没有任何 `vlm_review_round`。因此当前产物既不能证明 VLM
参与过审查，也不能证明 correction candidate 被处理与复测。

## 4. 由证据形成的质量契约

以下不是文献原句，而是本项目的工程决策：

1. 只允许一个 `QualityContract` 定义分数、硬门、空镜豁免、比较和 delivery class。
2. 程序测量是硬事实；agent/VLM 只产生语义问题和动作候选。
3. 每镜每一版保存完整、可重放、可物理恢复的证据。
4. 粗排与细排都使用 `observe -> propose -> apply -> remeasure -> compare -> retain
   best/rollback`。
5. 未过门的 best 可用于 diagnostic，不得进入 final 或 passed 集合。
6. RAG 只对真正注入的内容写 provenance；空命中和降级也必须留证。
7. 视觉审查必须带真实帧与程序读数；跳过不是通过。
8. 局部修改必须使受影响 shot 的序列审查与 final 身份失效并重审。
9. driver、UI、headless 只能共享同一个质量引擎和交付契约。
10. 终验必须用当前代码和真实模型重跑，不以 mock、旧证据或单测代替。

## 5. 参考文献

1. Hooke, R., Jeeves, T. A. *Direct Search Solution of Numerical and Statistical
   Problems*. JACM 8(2), 212–229, 1961.
   [DOI](https://doi.org/10.1145/321062.321069)
2. Zheng et al. *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*.
   [arXiv:2306.05685](https://arxiv.org/abs/2306.05685)
3. Chen et al. *MLLM-as-a-Judge*. [arXiv:2402.04788](https://arxiv.org/abs/2402.04788)
4. Madaan et al. *Self-Refine*.
   [arXiv:2303.17651](https://arxiv.org/abs/2303.17651)
5. Gou et al. *CRITIC*. [arXiv:2305.11738](https://arxiv.org/abs/2305.11738)
6. Shinn et al. *Reflexion*. [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)
7. Huang et al. *Large Language Models Cannot Self-Correct Reasoning Yet*.
   [arXiv:2310.01798](https://arxiv.org/abs/2310.01798)
8. Lewis et al. *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*.
   [arXiv:2005.11401](https://arxiv.org/abs/2005.11401)
9. Asai et al. *Self-RAG*. [arXiv:2310.11511](https://arxiv.org/abs/2310.11511)
10. Yan et al. *Corrective Retrieval Augmented Generation*.
    [arXiv:2401.15884](https://arxiv.org/abs/2401.15884)
11. Es et al. *Ragas*. [arXiv:2309.15217](https://arxiv.org/abs/2309.15217)
12. Yao et al. *ReAct*. [arXiv:2210.03629](https://arxiv.org/abs/2210.03629)
13. Huang et al. *A Survey on Hallucination in Large Language Models*.
    [arXiv:2311.05232](https://arxiv.org/abs/2311.05232)

## 6. 残余风险

- 80 分是产品硬门，不是艺术质量的完备度量；程序尺仍可能漏判表演、空间因果和镜头
  间节奏。
- VLM 的绝对分数不可靠，必须通过问题清单、程序事实、相对版本和复测共同使用。
- 单目白模帧无法证明灯光、材质、最终镜头语言；这些仍需要后续镜头空间尺和人工复核。
- 多镜循环的计算预算、Blender 状态隔离与可恢复性必须由真实 e2e 验证，不能只靠
  pure-Python mock。
