# 25 条审查清单：**当前代码树**逐条复核（2026-10-01 19:20）

角色视角：**测试与验收 ＋ 文档与可维护性**。这份文件回答用户那句
"为什么常驻审查的 agent 没有拦截到"——把当初那 25 条**在今天的树上**逐条重验，
区分「已修（带证据）」「仍是真缺陷」「本来就不是缺陷（旧结论过期）」。
**不照抄旧结论**：每条都现场跑了判据。

标记：✅ 已修 ／ ❌ 仍红 ／ ⚠️ 部分 ／ ⬜ 待裁决 ／ 🕓 由在途的 oracle 重标决定。

| # | 条目 | 今天的结论 | 证据（现场实测） |
|---|---|---|---|
| 1 | 门⑥ 的 fixture 与实际语料脱节（97 幽灵 id、143 张不在 fixture） | ✅ | `fixtures/knowledge_holdout.cards.json` 与运行时集合**完全相等**：2113/2113，`fixture_only 0 / runtime_only 0` |
| 2 | 门③ 词表：3 个零使用 ＋ 3 个词表外取值 | ✅ | 现在 **0 个词表外取值**（`fixtures/knowledge_holdout.vocab.json` 与索引不动点逐值相同；`test_shipped_vocab_matches_the_fixpoint` 通过） |
| 3 | 门⑨ 可达性 53.6% 不可达 | ✅ | 最近一次门口径：`gate_9_reachability: pass（short 0）` |
| 4 | 门⑩ `must` 2142/4675 | 🕓 | 旧 oracle × 新索引 = 1053 未解析（`work/gates_now.json`）；**这就是 `glm_v12` 在修的东西**，不是实现缺陷 |
| 5 | 门⑦ 人审 0/120 | ⚠️ | 机制已改：门⑦ 可接受 `llm-panel`，但**记录必须可佐证**（我 19:06 加的 `review_class()`：两个互异模型 id ＋ 面板提示指纹）；链里也已补 `--reviewer-classes human,llm-panel`（`7e24cbe`）。**仍需跑一次复核** |
| 6 | RK-13 = measured + false | ❌（如实） | 唯一失败的 RK，根因是门③⑥⑦⑩；`docs/evidence/20261001-190425/rks.json` |
| 7 | Q1/Q2/Q4/Q6b 全在线下 | 🕓 | `tools/knowledge/quality.py` 实测 Q1/Q2/Q4/Q6b fail、Q0/Q3/Q6a/Q7 pass；**旧 oracle × 新索引**，重标后才可判 |
| 8 | "4239 条 oracle 只是机械 lane 产物" | ✅ | 现行 oracle 是池通道 ＋ GLM（`annotator.family=zhipu`），门⑧ pass；机械通道的产物（`family=rule`）已被门⑧ 显式拒绝（`NON_MODEL_ANNOTATOR_FAMILIES`） |
| 9 | 追认候选池标注 | ✅ | 用户已追认；`docs/knowledge/ORACLE_DECISION_v15.md` |
| 10 | L3 `SEQUENCE_FLOOR = 7` 无解 | ✅ | **我按用户"改门限吧"落地**（`9d2bc62`）：门限改为"产出 == 语料里显式枚举的条数，且 ≥1"，漏抽即红 |
| 11 | 门⑩ 期望关系 / `forbid` 宿主范围 | ✅ | 池通道在 `exact`（最严）下 0 未解析；`forbid` 宿主由 `hypergraph._forbid_hosts()` 机械派生，实测分布在 **8 个边类型** |
| 12 | `AXIS_RULE` 可区分槽位 | ⬜ | 门④ 已过（`min(30, 可断言对数)` 口径）；"更细的槽位"仍属检索质量议题，未做 |
| 13 | 人审 ≥120 / Q5/Q7/E3 最终裁定 | ⚠️ | 机器复核通道可用（记录不可改写）；**人审仍未做**，门⑦ 靠 `llm-panel` 记录（已加佐证要求） |
| 14 | 冻结词表比 schema/引擎窄 | ✅ | 词表仍 22 个 kind（含 `weak` 之外的 qualifier），但**每个值都能凑出 ≥3 个 `(卡,查询)` 对**；词表外取值的边 = **0 组**（旧索引上是 38 条边/6 张卡） |
| 15 | 别名未归一（固定/static、handheld/手持、过肩/OTS） | ✅ | 索引里 `movement` 只有 `固定` ＋ `handheld` 两种规范写法，`static`/`手持` 不出现；`camera_angle` 只有 `过肩`（无 `OTS`） |
| 16 | `action` 值域被话题名词污染（35 个取值里 16 个不是动作） | ✅ | `action_lexicon.json` ＋ `build_nodes` 只从受控表与判定通过的词取值；索引里 action 取值 20 个，**全是可见行为**（`31f0a94`，258 条污染边退出索引） |
| 17 | `forbid` 只长在 `EMOTION_PACK` 上 | ✅ | 现在 **49 条带 forbid 的边分布在 8 个边类型**（EMOTION 28 / LIGHT 7 / STAGING 5 / AXIS 3 / PERFORMANCE 2 / TRANSITION 2 / INTENT 1 / SHOT_PATTERN 1），forbid 成员跨 10 个 kind |
| 18 | 缺三类边 ＋ 两个孤儿节点 | ✅ | `DIALOGUE_PACK 27` / `MUSIC_PACK 7` / `PROP_PACK 30` 存在；`NODE_TYPES` 里已无 `character`/`object`。**残留**：qualifier `applies_to_genre` 在节点表里但**没有任何边使用**（1 个孤儿 qualifier，非节点） |
| 19 | 132 张手写策展卡不入索引 | ✅ | **766/766 条边都带 `source_span`**；手写卡出现在边的 `sources` 里（2086/2113 张卡至少被一条边引用） |
| 20 | `cases.jsonl` 仍是旧世代（53 篇 `repo://`） | ✅ | 我重算入库（`9d2bc62`）：810 条、**0 条 `repo://`**、9 个域全覆盖、501,796 B（过 512 KB 单文件门）、`build_cases --check` 退出 0 |
| 21 | E2（经验采纳率）结构性恒为 0 | ✅ | `d3436bd`：`retriever.provenance()` → 驱动逐镜 ── `movements[].source ∈ {theory,lesson,experience,case}`；GUI 通路的知识检索器也补上了（此前 `driver.knowledge` 恒为 None） |
| 22 | 4 处引用已删除的 `qwen3-vl:30b` | ⚠️ | `tools/probe_local_model.py` 已是 `--model` 必填（实测 `--help`）；`fixtures/local_*.config.yaml` 是**标注为历史记录**的注释。**仍存**：`改进执行文档v1.4.md` §4.4 的实证命令仍写 `--model qwen3-vl:30b`（规格文档的 R-版本记录，未擅改） |
| 23 | LightRAG 真实索引缺失 / 降级口径未收口 | ⚠️→✅(生产侧) | 仓库确无 `lightrag` 依赖与索引；**我修掉了"回落没有生产者"**（`dec627a`）：无 client 时惰性装配进程内 `CaseIndex`，trace 如实报 `hybrid` / `lightrag_adapter_unavailable` / `cases_requested_backend=lightrag`（以前误报 `off`）。"接上真 LightRAG"仍是外部依赖 |
| 24 | `depth`/`full_concat` 声明了却只给警告 | ✅ | **旧结论过期**：`export_depth`（EEVEE 硬校验 CFG_102）与 `full_concat`（VSE 拼接）都已实现，`test_delivery_extras.py` 有 5 个探针；`AGENTS.md` 里那句自相矛盾的状态行已改 |
| 25 | 环境残留（`.scratch` 41 项、ollama 18.49 GB） | ❌ | `.scratch` 现在 **278 个**未跟踪文件（各 lane 的诊断脚本）；`%USERPROFILE%\.ollama\models\blobs` 两个大文件**仍在**：`sha256-0373edb0…` 19,595,386,752 B ＋ `sha256-b1da6f96…-partial` 18,999,095,296 B ≈ **38.6 GB**。删除是工作区外的破坏性操作，**必须由你手工执行** |
| 26 | 两条标注 lane 同时在跑 | ✅ | 旧 `glm_v11` 已在换索引时终止（其产物作废，我在 19:0x 确认过），现在只有 `glm_v12` + 一个来源发现器 |
| 27 | 热文件被持续改写 | ⚠️（过程） | 属实：今天索引/词表/oracle 换过三代。**代价具体化**：我这条 lane 的 `glm_v11` 因索引换代作废（20/65 批）。建议的纪律：**换索引前先确认没有 oracle lane 在跑**（现在这条纪律没有机器检查——见下节） |

## 我这一轮**没做**、但值得做的事（留给下一轮）

1. **给"换索引"加一道机器检查**（#27 的机制化）：改 `knowledge/hypergraph.*` 或
   `fixtures/knowledge_holdout.vocab.json` 之前，先断言没有 oracle lane 在跑
   （例如把 `work/glm_pool/*.progress.json` 的 mtime 与索引 mtime 比对），
   否则"重标两小时、结果作废"会再发生一次。**这条我没有实现**（它是流程工具，
   不属于我这条 lane 已交付的范围，且会碰到你正在用的脚本）。
2. `applies_to_genre` 孤儿 qualifier：要么在某条边型上给它一个槽位，要么从节点表删掉。
3. `.scratch/` 归位：把散落的 278 个诊断脚本按 `docs/agents/issue-tracker.md` 的
   `<feature-slug>/` 收进子目录（我自己的 `.scratch/g6_*.py`、`verify_index_invariants.py`
   等可以随时归位，只要你说一声）。
4. 规格 §4.4 里已停用的本地模型命令（#22）——规格文档带 R-版本变更记录，我按纪律没擅改。
