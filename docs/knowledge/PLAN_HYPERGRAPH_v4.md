<!-- 由 tools/plan_writer.py 产出：草案 → 2 轮自我精炼；模型 glm-5.3；取证见 plan.refinements.json -->
<!-- {"created_at": "2026-10-05T07:13:48", "model": "glm-5.3", "rounds_requested": 2, "rounds_ok": 3, "contract_sha256": "c2a9dd225a4f7778353e6427f594a51e0ffa1510502496778f6739be29c9c161", "final_sha256": "219c402a5fd6cdd13b3c036c8f676f8692c9e2d9cffe2f12b41fad6f791270c7", "draft_sha256": "2c395d8cca3a7247aa7f9f7ccdca7aa6f6134e153cff00e08e1effad7afb906c"} -->
# 自我精炼报告（第 2／2 轮，终轮）

## 任务 1：契约自查核验（核验对象＝第 3 稿）

**第 1 轮改动落稿核验**：C1–C20 逐项对照第 3 稿正文，**全部落稿**（抽查：C1→§4.1 在稿；C2/C3→§6 命令列＋全路径在稿；C4→R5 双字段判据在稿；C5→R10 子串断言在稿；C10→§8“三路由 E1 全 <0.10”在稿；C13→P6 DoD ④＋§3.2 挂点＋§8 风险行在稿；C18→§2.8 十四条在稿；C19→§5.8"1152＋1152"在稿）。

**勘误（第 1 轮报告自报计数与表内实标不符）**：第 1 轮报告自称“对抗性 9 处／负例 8 处”；第 3 稿 §6 表内实标＝**对抗性 8 处、负例 6 处**。系报告元数据计数笔误，计划本体无恙，契约门槛（对抗性 ≥1）仍满足。

| # | 契约条款 | 第 3 稿状态 | 依据／残留问题 | 本轮处置 |
|---|---|---|---|---|
| 1 | U1…Un 逐字＋U→R 显式映射 | **已满足** | §2.2 十条逐字；§2.3 映射表双向覆盖（逐条复核：U1→R1,R2,R3 … U10→R5；R1–R13 每条可溯源 ≥1 条 U） | 保持 |
| 2 | 术语表＋无指代歧义＋无不可判定词 | **大体满足，残留 8 处** | ①台账／主线／对抗性审查／评委／冒烟／红线／基线／A/B 八个高频词未入术语表；②“评测集”已宣布为旧称却残留于 P6 标题与产物列；③“换血”与“总体更换”混用（S4）；④“其时机”（§0）／“其自述”（§2.8）／“该文件”（§2.8-2）／“取其…弃其…”（§3.5）／“断言之”（§3.3）／“同一适配器”的“同一”（§5.3）六处指代；⑤§5.2“前缀…后 insert”语序歧义；“更好/尽量/显著”类词第 1 轮已清零，本轮复扫无新增 | C2-01/02/11–16 |
| 3 | PRD／技术方案／TDD／执行顺序／出处五节齐全 | **已满足** | §2／§3／§6／§7／§3.5＋§4 | 保持 |
| 4 | 上游四档＋改造点＋差异＋许可＋上游可跟踪策略 | **基本满足，残留 1 处** | §4 四档表＋§4.1 跟踪策略在稿；LightRAG 仅版本 pin，缺“版本→上游 commit”解析义务（契约要求 GitHub 上游给 commit） | C2-09 |
| 5 | 待裁决 D1…Dn 单列＋选项＋代价 | **已满足** | D1–D9 各有选项/代价/建议；触发条件第 1 轮已量化 | 保持 |
| 6 | 判据一个字没动 | **已满足** | 0.70／4.0／`DEFAULT_PANEL`／E3=0／RK-13／门①–⑩／0.02／0.30／192／seed=20261005 逐项比对第 3 稿原文，全部原样 | 保持；本轮**零新增量值数字** |
| 7 | 每条 R 五要素（对象＋判据＋阈值＋分母＋命令） | **大体满足，残留 4 条** | R8 缺阈值/分母、R9 缺命令、R11 缺分母、R13 缺命令（其余 9 条合规） | C2-03/04/05/06 |
| 8 | 测试用例四要素（名称＋断言＋夹具＋命令） | **已满足** | §6 命令列（nodeid 尾段）＋表前统一模板 | 保持 |
| 9 | 对抗性用例 ≥1 | **已满足** | 表内实标对抗性 8 处（勘误见上） | 保持 |
| 10 | 阶段表 DoD／依赖／串并／产物／验收命令 | **满足，新发现 2 处阶段门矛盾** | ①`tests/knowledge/test_e1_report.py::test_wrapper_keeps_panel_untouched` 依赖 P1 冻结件 `tests/plan_v4/instruments.sha256.json`，而 P2 与 P1 并行 ⇒ P2 退出时全量 pytest 无法全绿，且与 `tests/plan_v4/test_instruments_frozen.py::test_e1_panel_sha256` 断言完全重复；②`tests/plan_v4/test_freeze.py` 四用例中两个断言 P1 产物，若于 P0 全部落盘则 P0 退出必红，与“每阶段退出全量 pytest 全绿”矛盾 | C2-07/08 |
| 11 | 出处可核对、无出处标自研 | **形式满足／内容无法核验** | §3.5 形式合规；外部断言（上游 sha256/行号/四读数/引文）本轮仍无法重验 | 维持 §2.8 挂账 |
| 12 | 看不到的写“未核验” | **已满足** | §2.8 十四条＋复核时点 | 扩展（C2-09/10 → 新增 §2.8-15、扩展 §2.8-9） |

## 任务 2–4：本轮改动清单（补缺口＋消歧＋改了什么、为什么）

| # | 位置 | 第 3 稿问题 | 类别 | 处置 | 为什么 |
|---|---|---|---|---|---|
| C2-01 | §7 P6 标题＋产物列 | “冻结评测集”——“评测集”已定为旧称（§1 heldout 条）仍现于 P6 | 旧称残留 | 改“冻结 heldout” | 一词一义 |
| C2-02 | §1 | 台账／主线／对抗性审查／评委／冒烟／红线／基线／A/B 八个高频词未定义 | 术语缺口 | 逐条入表 | 一词一义 |
| C2-03 | §2.4 R8 | 五要素缺“阈值／分母” | 判据五要素缺口 | 补：缺失小节数＝0；分母＝已完成阶段数 | 契约 §0-3 |
| C2-04 | §2.4 R9 | 缺“命令” | 同上 | 补 `python -m pytest tests/plan_v4/test_instruments_frozen.py -q` | 同上 |
| C2-05 | §2.4 R11 | 缺“分母” | 同上 | 补：分母＝指纹不匹配场景的查询数 | 同上 |
| C2-06 | §2.4 R13 | 缺“命令” | 同上 | 补 `python -m pytest tests/knowledge/test_e1_report.py::test_paired_runs_and_noise_floor -q` | 同上 |
| C2-07 | §6＋§7 P2 | `test_wrapper_keeps_panel_untouched` 依赖 P1 冻结件而 P2 与 P1 并行（阶段门矛盾）＋与 `test_e1_panel_sha256` 断言重复 | 逻辑冲突＋冗余 | 删该行；冻结断言统一由 `tests/plan_v4/test_instruments_frozen.py` 承担（P1 起进全量门）；P2 DoD 加⑥ | 阶段可达性；一处一断言 |
| C2-08 | §6 纪律段＋§6 表标记列 | `test_freeze.py` 四用例与 `test_instruments_frozen.py` 若全部于 P0 落盘，P0 退出全量 pytest 必红 | 阶段门矛盾 | 新增“用例落盘规则”（P0 落 2 个、P1 落 2 个＋instruments 先红后绿、P2 落 e1_report 且不依赖冻结件）；表内标“（P0/P1 落盘）” | 消除与“每阶段退出全绿”的自相矛盾 |
| C2-09 | §3.5／§4／§4.1／§7 P7／§2.8 | LightRAG 出处只 pin 版本，无版本→上游 commit 解析义务 | 出处缺口 | P7 DoD 加⑥（UPSTREAM_LIGHTRAG.md 记版本＋commit/tag＋许可）；§4/§4.1 同步；新增 §2.8-15 挂账 | 契约 §2：GitHub 上游给 commit |
| C2-10 | §2.8-9＋§2.1-5 | 四次 E1 读数的实验条件（两次读数间索引是否重建、heldout 是否同一文件）未列复核，“同一份索引”含义悬空 | 未核验挂账缺口 | §2.8-9 扩展复核范围＋§2.1-5 括注 | 红线：不猜 |
| C2-11 | §0／§2.8 引言／§2.8-2 | “其时机”“其自述”“该文件”三处指代 | 指代 | “总体更换的时机”“第 2 稿自述”“以 `work/_plan/review.loop1.md` 为准” | 指代消解 |
| C2-12 | §3.5 第 1 行 | “取其…弃其…”两处“其” | 指代 | 写全名 HyperGraphRAG | 同上 |
| C2-13 | §3.3 修改 3 | “测试断言之” | 指代 | “测试断言旧字段全部保留” | 同上 |
| C2-14 | §2.5 S4 | “换血期间”——“换血”未入表且与“总体更换”混用 | 同义混用 | “总体更换期间” | 一词一义 |
| C2-15 | §5.2 | “每条 Case 文档前缀 `[CASE <case_id>]` 后 `LightRAG.insert`”语序歧义 | 歧义 | “每条 Case 的文档文本＝前缀＋Case 内容，交给 `LightRAG.insert`” | 消歧 |
| C2-16 | §5.3 | “经同一适配器”的“同一”未指明参照 | 指代 | “经 `block_director/knowledge/lightrag_adapter.py`（与插件运行期为同一适配器）” | 同上 |
| C2-17 | 版本行 | 稿次／精炼轮次信息过期（仍标第 3 稿） | 留痕 | 升第 4 稿，注明经第 2 轮精炼 | 留痕准确 |

## 红线自查（本轮）

- **判据／门限／阈值零改动**：0.70、4.0、`DEFAULT_PANEL=("deepseek-chat","glm-5.3")`、E3=0、RK-13、门①–⑩、0.02、0.30、192 行、seed=20261005 全部原样带入第 4 稿；第 1 轮引入的 0.05／0.10（诊断阈值）原样沿用。
- **零新增量值数字**：本轮唯一“删除物”＝§6 一行重复用例（其断言在 `tests/plan_v4/test_instruments_frozen.py` 原样保留且从 P1 起进全量门——判据冻结反而更严）；新增的"⑥"均为 DoD 序号，非量值。
- **未编造**：未新增任何文件／行号／commit／出处断言；C2-09 规定的是 P7 的解析**义务**，commit 具体值未知且挂 §2.8-15 待安装日解析，不预写。
- **未核验维持挂账**：§2.8 原十四条原样，本轮扩展第 9 条、追加第 15 条（按引用稳定性追加于表尾，不改动既有编号）。

终轮结论：第 4 稿为循环 2 草案终稿，交付主线核对 U→R 映射与出处后，进入循环 2 对抗性审查。

---

# 超图建模 RAG 完全重建 ＋ LightRAG 真接入 —— 执行计划 v4

| 项 | 内容 |
|---|---|
| 版本 | v4 第 4 稿（三循环之循环 2 的草案终稿；第 3 稿经第 2 轮工具级自我精炼修订而成；精炼轮不替代对抗性审查） |
| 日期 | 2026-10-05 |
| 状态 | **未定稿**。循环 1（草案→审查→修订）与循环 2（审查→37 条 finding→处置表）已完成；**循环 3 未做**（见下方"循环进度"）。按用户裁决，三循环收口前不得进入执行。 |
| 取代 | `docs/knowledge/PLAN_HYPERGRAPH_v3.md`（该文件的 S0/S1a 已完成并被本计划继承；该文件的 S2 起被本计划 P 系列取代） |
| 研究目标 | 白模预演强耦合：行为／动作／情绪／意图 × 镜头语言 × 构图 × 震动打击感 |

---

## 循环进度（用户裁决 U6：三循环收口前不许开工）

| 循环 | 草案 | 对抗性审查 | 修订 |
|---|---|---|---|
| **1** | `work/_plan_rebuild_cycle1/CYCLE1_plan.md`（GLM-5.3 起草 ＋ 2 轮自我精炼） | `work/_critique_v4_1.md`（主线 DeepSeek 核对：13 条事实纠正＋blocker） | 本文（循环 2 草案） |
| **2** | 本文 | [`PLAN_V4_REVIEW_LOOP2.md`](PLAN_V4_REVIEW_LOOP2.md)：DeepSeek × GLM-5.3 双侧、角色＝红队反方 ＋ 测试与验收，**37 条 finding**（GLM 18 / DeepSeek 19，四栏记账 `both=0`） | [`PLAN_V4_LOOP2_DISPOSITION.md`](PLAN_V4_LOOP2_DISPOSITION.md)：GLM-5.3 实现顾问档逐条处置（**采纳 28／部分采纳 9／不采纳 0**）＋ 8 段可直接粘贴的修订正文 ＋ 5 条新裁决项 R1–R5 |
| **3** | **未做**（本轮到此为止，如实挂账） | 未做 | 未做 |

**循环 2 的五条新裁决项**（`PLAN_V4_LOOP2_DISPOSITION.md` 末尾，均属"本计划无权改"）：
R1 C6 噪声带的数值与验收地位；R2 C8 的 0.30 护栏是否随基线校准；R3 红线 0.70 在"不可达信号"下的处置 ＋ 试点判据签署；
R4 192 行评测集在换总体后的对照迁移；R5 检索契约既有字段语义变更。

**本轮同时实测到的、影响读数纪律的三件事**（证据在 `docs/evidence/20261006-e1-baselines/` 与 `ACCEPTANCE_STATUS.md`）：
① E1 的分子是两位 LLM 评委 1–5 分均值 ≥ 4.0 的行数，**不是检索命中**；
② 同一份索引、同一 192 行、同一配置下，同臂重复能差 7 行（lexical 37→44），两臂大小关系会翻转；
③ DeepSeek **没有** embeddings 端点（`/v1/embeddings`、`/embeddings`、`/beta/embeddings` 皆 404、`GET /models` 405），
智谱 `embedding-3/2` 对本 key 返回 1113 ⇒ 沿用别家方案处的 LLM 用 DeepSeek（用户裁决），
但 **embedding 是显式例外**，路线由 D3 裁决。

### 主线核对补记（2026-10-05，晚于本文起草；**冲突以本节为准**）

1. **§2.1-6 / §3.4 / D3 关于"本地 embedding"的措辞过旧，已被实测推翻。**
   主线在 sidecar 的解释器（系统 Python 3.10.11）里实测：

   ```
   torch 2.5.1+cu121   cuda True   NVIDIA GeForce RTX 4070 Ti SUPER (16376 MiB)
   transformers 5.15.0   numpy 2.2.6   networkx 3.4.2
   onnxruntime → ModuleNotFoundError（未安装）
   ```

   并且 `BAAI/bge-small-zh-v1.5` 已在 **CUDA** 上完成一次真实编码（`device_used: cuda`、`dim: 512`、`ok: true`），
   下载来源是 `hf-mirror.com`（`huggingface.co` 超时）。证据：`work/_facts_embed.md`、`work/_probe_embed.py`。
   ⇒ **embedding 不是"只有两条路"，而是"本地这条路已经跑通"**；D3 的选项应改成
   ①**本地 torch ＋ CUDA（已实测可用，无需新账号、无需新资源包，首选）**／
   ②智谱 `embedding-3`（需用户开通资源包）／③`onnxruntime`（需新装，只在 ① 不可用时考虑）。
   **DeepSeek 仍然没有 embedding 端点**（上面③条不变）。
2. 循环 2 的处置（`PLAN_V4_LOOP2_DISPOSITION.md`）里 B.3 要求"探测要存档"——本文的
   `work/_facts_embed.md` 与 `work/_probe_embed.py` 就是那条存档，请一并迁入 `docs/evidence/`。
3. **旧前提不再成立**：ADR-0014 里那句"本机能否跑轻量本地 embedding 未验证"现在可以销账为
   **已验证（可跑，且是 GPU）**。
| 精炼红线自查 | 本轮（第 2 轮）精炼零改动判据/门限/阈值（§0 全表逐项原样）；零新增量值数字（第 1 轮引入的 0.05／0.10＝诊断阈值（非判据）、1152×2＝费用披露拆分，均沿用） |

---

## 0. 红线零改动声明

本计划对以下判据**零改动**（阈值、判据、运行入口、分母构造机制均不动）：

1. 机器门①–⑩（载体：`python -m pytest` 全绿）；
2. E1：红线目标 top-1 ≥ 0.70；逐行判分＝两位 LLM 评委 1–5 分均值 ≥ 4.0（`tools/knowledge/e1_panel.py:50` `DEFAULT_PANEL=("deepseek-chat","glm-5.3")`、`:52 RELEVANT=4.0`，零改动；该行号与内容属循环 1 主线核对结论，P1 冻结 sha256 时以实测为准——§2.8-4）；
3. E3：经验越权率 = 0；
4. RK-13（既有红线判据编号，运行入口零改动）。

任何涉上述判据的变动只能以“待裁决”单列、经用户明示批准后另立提交执行；本计划正文不含任何对上述判据的改写。测量**总体**从 v3pop（旧知识产物＋既有 192 行 heldout，`cases_fingerprint=48df4a53c2c95637…` 完整值未核验，§2.8-8）换为 v4pop（新知识产物＋新冻结 heldout `knowledge_v4/eval/heldout_v4.jsonl`）属**总体更换**而非判据改动，总体更换的时机与后果由 D5 裁决。基线 `python -m pytest -q` 在每个阶段退出时必须全绿。

---

## 1. 术语表

| 术语 | 定义 |
|---|---|
| 白模预演 | 以素模（无材质白模）在 Blender 中排布镜头与动作的预演流程；本仓研究对象 |
| 强耦合 | 白模预演中 行为／动作／情绪／意图 × 镜头语言 × 构图 × 震动打击感 的联动问题 |
| 知识产物 | `knowledge/` 下的五件产物：`hypergraph.edges.jsonl`／`hypergraph.nodes.jsonl`／`hypergraph.vocab.json`／`hypergraph.manifest.json`／`hypergraph.rejects.jsonl`（旧称 `knowledge/hypergraph.jsonl` **不存在**，为讹传） |
| L1/L2 | 卡与槽位超边层（现状：2221 卡＋638 槽位超边，83.6% 素材来自 1900–1920 公有领域旧书；统计口径复核见 §2.8-10） |
| L3 / 案例（Case） | 案例层（现状 1143 条）；检索契约的返回单元 |
| 槽位超边 | 带 type／qualifier 闭集与槽位成员的超边；数据形状由 `block_director/knowledge/hypergraph.py` 定义 |
| 闭集 | `NODE_TYPES`(18)／`QUALIFIER_KINDS`(12)／`EDGE_TYPES`(16) 三张枚举表及其 `schema_fingerprint`（S0 已入缓存指纹） |
| 路由（route） | 检索实现可选项：`lexical`／`hybrid`／`lightrag`；由 `block_director/knowledge/cases.py:88` 的工厂 `(index_dir) -> adapter` 构造（行号复核见 §2.8-5） |
| 检索契约 | `retrieve(query, *, top_k, cases) -> Sequence[Case]` |
| heldout | 从 cases 冻结采样出的评测查询行集合；v3pop 的既有 heldout＝192 行（`cases_fingerprint=48df4a53c2c95637…`）；v4pop 的 heldout＝`knowledge_v4/eval/heldout_v4.jsonl`（192 行，seed=20261005）。“评测集”为旧称，正文不再使用 |
| panel（评委组） | E1 逐行判分的两位 LLM 评委集合＝`tools/knowledge/e1_panel.py` 的 `DEFAULT_PANEL=("deepseek-chat","glm-5.3")`；零改动（§0） |
| 评委 | panel 的单个成员（`deepseek-chat` 或 `glm-5.3`），对每行 heldout 检索结果打 1–5 分；“评委组”即 panel |
| 影子路径 | `knowledge_v4/`：新总体在指针切换（P10）前的构建落点 |
| 指针切换 | P10 的一次性目录搬移，默认知识产物由旧总体换为新总体 |
| 总体（population） | 知识产物＋heldout 的整体；v3pop＝旧、v4pop＝新；**跨总体 E1 读数不可比**（D5） |
| A/B | 同总体、同 heldout、≥2 次运行的成对比较（受 R13 约束）；“A/B 期间”＝P9 双报告阶段 |
| E1 | 检索质量判据：每条 heldout 行取 top-1 检索结果，panel 两位评委 1–5 分均值 ≥ 4.0 记 1；读数＝记 1 行数／heldout 行数（v3pop 分母＝192；v4pop 分母＝192） |
| E3 | 经验越权率；红线 = 0 |
| 机器门①–⑩ | `python -m pytest` 承载的机器门链 |
| 台账 | 持留的记录文件：E1/E3 历史读数记录、`work/corpus_v4/spend.jsonl` 花费记录等；具体文件以各命令 `--out` 参数或既有记录路径为准 |
| 两趟抽取 | 先分段、再把成员归属到段的抽取结构（上游算法参考，见 §3.5） |
| 完整度分（completeness_score） | 上游 0–10 分；本仓映射为边记录的 `confidence` 字段 |
| sidecar | 独立系统 Python 3.10.11 进程；`lightrag`／`onnxruntime` 只允许住在这里 |
| 插件进程 | Blender 5.2 Python 3.13.13（numpy 2.3.4）；零运行时依赖（本计划维持） |
| index_fingerprint | `INDEX_MANIFEST.json` 四元组的 sha256；比对失败即 fail closed |
| 对抗性用例 | 证明“做错会被抓住”的测试（如：闭集外边必须落 rejects） |
| 对抗性审查 | 计划三循环（R6）中的审查环节，产出 `work/_plan/review.loop{k}.md`；与“对抗性用例”（测试概念）是两个不同术语 |
| 负例 | 判据的反向断言（如：ΔE1 < 0.02 必须被标 inconclusive） |
| 冒烟 | 服务最小连通性验证：P7 的 `/health` 与 `/query` 各一次成功调用 |
| 诊断阈值（非判据） | 计划级触发规则中的数字，只用于触发“重裁决／不切指针／回退诊断／inconclusive 标记”，不是验收判据、不进 §0 红线表、数值调整＝计划修订（走循环审查）而非判据改动。本计划的诊断阈值：0.02（R13 噪声底）、0.30（D9 rejects 上限）、0.05（D3 重裁触发）、0.10（D5 放行下限）。与判据阈值（0.70／4.0／0）严格区分 |
| 红线 | 本计划中不可违背的判据或规则的统称，具体所指由上下文点名（如 §0 判据红线、§6 测试纪律“删测试／跳测试／放宽断言＝红线违规”） |
| 基线（baseline） | 对照用的既有读数或提交：“P0 基线提交”＝P0 收口时的 HEAD；`baseline_v4`＝指针切换后的成对重定标读数（标签 `population=v4pop`） |
| 主线 | 执行本计划的 DeepSeek 会话，负责证据核对、裁决执行与提交；计划起草与对抗性审查由 GLM-5.3 承担（用户既有分工裁决） |
| 术语统一 | 正文统一“镜头”；代码标识符（如 qualifier `carry_shots`）不属术语混用；“分镜”为旧称不用 |

---

## 2. PRD（要什么）

### 2.1 背景与现状（引用真源）

1. **仓库状态**：HEAD `5aff340`（2026-10-05 06:38，`python -m pytest` 全绿；P0 收口时以 `git log` 复核记 PROGRESS——§2.8-1）。S0（schema 闭集进缓存指纹）＝提交 `824005b`；S1a（`seq_phase`／`carry_shots` 两个惰性 qualifier＋trace 可观测面）＝提交 `5aff340`。**两步已入库，本计划继承、不重做。** 状态真源＝`AGENTS.md` 状态块与 `docs/knowledge/ACCEPTANCE_STATUS.md`（两处当前状态段的逐字摘录于 P0 收口与 P11 终态更新时进行——§2.8-3）。
2. **构建机制现状**：`tools/kb_fetch/build_hypergraph.py`（`PROMPT_VERSION="extract/v18"` :182、`CACHE_KEY_FIELDS` 八分量 :250、`fingerprint_components()` :275、`rekey_manifest()` :314；行号复核见 §2.8-5）；闭集校验在 `block_director/knowledge/hypergraph.py`。
3. **素材老旧（本次换代动因）**：L1/L2 共 2221 卡，83.6% 素材来自 1900–1920 公有领域旧书；“震动打击感”等现代维度在旧素材中无覆盖。
4. **上游前提复核（推翻上一稿 §3.2）**：`docs/knowledge/S2_UPSTREAM_PREMISE.md` 逐行核过 `LHRLAB/HyperGraphRAG@d587cdf8c3fe` 的 `prompt.py`（351 行，sha256 `2730b18d…`）与 `operate.py`（1,124 行，sha256 `1302a159…`）：上游“超边”载荷＝一句话＋0–10 完整度分（`prompt.py:18-21`），无 type/role/kind/槽位；成员按记录流挂“最近那条句子”（`operate.py:364`＋`:92`）；`entity_type` 开放字符串；合并键＝节点名字符串相等（`:134-164`）。⇒ **“移植上游抽取层”不成立**；按 ADR-0014 判例，“把上游数据模型翻译成本仓槽位模型”属自研。LICENSE（sha256 `b54ba7ea…`）为 MIT。（sha256 与行号以 S2_UPSTREAM_PREMISE.md 留证为准——§2.8-6）
5. **E1 机制与噪声底**：分子＝panel 均值 ≥ 4.0 的行数（非检索命中）。同一份索引、同一 192 行上四次实测：hybrid 台账 35/192=0.1823／重跑 39/192=0.2031；lexical 台账 41/192=0.2135／重跑 37/192=0.1927 ⇒ **大小关系会翻转，任何 |ΔE1| < 0.02 不作结论**（四读数、台账位置与实验条件复核见 §2.8-9）。
6. **embedding 实测**：智谱 `embedding-3`/`embedding-2` → 1113「无可用资源包」；`GET /api/paas/v4/models` 200 但 11 个全是对话模型；DeepSeek 同 key `POST /chat/completions` → 200，而 `/v1/embeddings`、`/embeddings`、`/beta/embeddings` 全 404、`GET /models` → 405 ⇒ **DeepSeek 无 embedding 端点**（三条实测于 D3 裁决前复测留证——§2.8-11）。
7. **适配器真契约**：`retrieve(query, *, top_k, cases) -> Sequence[Case]`，工厂 `(index_dir) -> adapter`（`block_director/knowledge/cases.py:88`；§2.8-5）。

### 2.2 用户原话（逐字）

- U1「重新开始吧。这次github上成熟的超图建模rag，按需求自己魔改。如果不需要构建新的知识库那就不构建，如果需要构建那就重新构建知识库，之前的构建的知识库素材有点问题，用了过于老旧的素材。」
- U2「自研的成熟度太低了，我不放心」
- U3「重新规划执行计划」
- U4「不是完全重新构建超图建模rag么？我要的是完全重新构建」
- U5「以及light rag」
- U6「开始之前你先用glm5.3写执行计划，然后对抗性审查，一共循环三遍再开始」
- U7「记住我是个人使用学习，不用担心版权问题，我研究白模预演的强耦合性怎么解决」
- U8「要说明白细节，执行计划，任务进度，解决需求等问题」
- U9「embedding 改成用其他 ai 模型」→ 追问后「用 deepseek 吧，比较便宜」
- U10「凡是遇到用其他模型的，一律改成 DeepSeek」（用户随后澄清适用范围：“这部分只针对用别人的方案”）

### 2.3 U→R 映射

| 用户原话 | 派生需求 |
|---|---|
| U1 | R1, R2, R3 |
| U2 | R1, R4 |
| U3 | R9, R13 |
| U4 | R1, R3, R10 |
| U5 | R4, R11, R12 |
| U6 | R6 |
| U7 | R7 |
| U8 | R8, R13 |
| U9 | R5 |
| U10 | R5 |

（双向覆盖核对：每条 U 派生 ≥1 条 R；R1–R13 每条溯源 ≥1 条 U。）

### 2.4 可验收需求 R1–R13

每条按「对象＋判据＋阈值＋分母＋命令」书写。

**R1（抽取实现换代；←U1,U2,U4）** 措辞按事实 §2.1-4 修正：**“移植上游抽取层”不成立；本轮是“上游算法参考＋自研槽位实现”（ADR-0014）**。新建 `tools/kb_fetch/extract_segmented.py`，实现两趟“分段→归属”，`PROMPT_VERSION` 升为 `"extract/v19-seg"`，抽取 LLM＝DeepSeek。
判据：对象＝`knowledge_v4/hypergraph.edges.jsonl`；闭集违例数＝0（违例全在 `hypergraph.rejects.jsonl`）；分母＝主产物边数；命令 `python -m pytest tests/kb_fetch/test_extract_segmented.py -q`。

**R2（语料换代；←U1）** 新语料 year ≥ cutoff（D1 裁决值），每条带 `source_ref`（url/title/author/license）＋year。
判据：对象＝`work/corpus_v4/MANIFEST.json`；year < cutoff 的条目数＝0；分母＝清单条数；命令 `python -m pytest tests/kb_fetch/test_ingest_corpus.py -q`；被排除旧素材全记 `work/corpus_v4/excluded.jsonl`。

**R3（影子路径；←U1,U4）** 新产物落 `knowledge_v4/`；指针切换前旧 `knowledge/` 五件产物逐字节不动。
判据：对象＝`knowledge/` 五件产物 sha256；P5 前后清单 diff＝空；分母＝五件产物；命令 `python tools/kb_fetch/sha256_dir.py knowledge --out work/knowledge.sha256.p5.before/after`＋文件比对。

**R4（LightRAG 真接入；←U2,U5）** `block_director/knowledge/lightrag_adapter.py` 以工厂契约接入路由表；sidecar 承载 lightrag 运行时；插件进程零新增依赖。
判据：对象＝插件进程 import 集；新增依赖数＝0；分母＝`block_director/**/*.py` 全部 import；命令 `python -m pytest tests/knowledge/test_lightrag_adapter.py tests/knowledge/test_no_new_plugin_deps.py -q`。`lightrag_adapter_unavailable` 降级路径保留为运行期回落，不再是唯一状态。

**R5（模型通道规则与 embedding 显式例外；←U9,U10）** 沿用／魔改别家方案处的内部 LLM 一律 DeepSeek（`https://api.deepseek.com`，key＝环境变量 `DEEPSEEK_API_KEY`）：①`tools/kb_fetch/extract_segmented.py` 的 `DeepSeekClient` 驱动抽取；②LightRAG `llm_model_func`。**embedding 为显式例外**：DeepSeek 无 embedding 端点（实测 404/405，§2.1-6），路线由 D3 裁决（智谱 `embedding-3` 或本地 ONNX），本计划不默认任一。E1 评委 `DEFAULT_PANEL` 属本仓自有测量仪器，不因 U10 改动；是否改动由 D4 裁决（改动即判据级变动，历史读数不可比）。计划起草／对抗审查仍用 GLM-5.3（用户既有裁决）。
判据：对象＝`knowledge_v4/lightrag/INDEX_MANIFEST.json`；`llm_model == "deepseek-chat"` 且 `embedding_route` 等于 D3 裁决值（字段相等断言）；分母＝2 个字段；命令 `python -m pytest tests/lightrag/test_client.py::test_manifest_records_llm_and_embedding_route -q`。

**R6（计划三循环门；←U6）** 循环 k 的定义＝（草案 k → 对抗性审查 k → 修订 k），k＝1..3。循环 1 已完成（循环 1 的审查产出即本稿输入）；本稿＝循环 2 草案（本稿内部含工具级自我精炼轮，精炼轮留证＝`plan.round*.md`，不替代对抗性审查）。循环 2 的审查与修订、循环 3 的草案／审查／修订全部完成，且用户明示“开始执行”后，方可进入 P1。
判据：对象＝`work/_plan/`；`review.loop1.md`、`review.loop2.md`、`review.loop3.md` 三份＋`plan.md` 共 4 个文件存在（存在断言）；分母＝4 个文件；命令 `python -m pytest tests/plan_v4/test_freeze.py::test_plan_loops_complete -q`。

**R7（理论外部来源；←U7）** 新总体只收外部来源（本仓自撰策展卡不入新总体，处置由 D2 裁决）；每条产物可回溯 `source_ref`；语料覆盖四维（行为／动作／情绪／意图、镜头语言、构图、震动打击感），每维专门来源数 ≥ 1（记入 `docs/knowledge/CORPUS_v4.md`）。版权不设门但出处必留。
判据：对象＝`docs/knowledge/CORPUS_v4.md`；缺四字段＋year 的源数＝0，四维专门来源数各 ≥ 1；分母＝清单条数＋四维；命令 `python -m pytest tests/plan_v4/test_freeze.py::test_corpus_list_frozen -q`。

**R8（进度可追踪；←U8）** `docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md` 按阶段更新：每个阶段小节含 DoD 勾选＋验收命令输出摘要＋日期＋引用的裁决号。
判据：对象＝`docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md`；缺失小节数＝0（每个已完成阶段各有对应小节）；分母＝已完成阶段数；命令 `python -c "import pathlib;assert 'P0' in pathlib.Path('docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md').read_text(encoding='utf-8')"`（`'P0'` 逐阶段替换为该阶段编号，各阶段类推）。

**R9（红线零改动；←U3）** 见 §0。机制化保证：`tests/plan_v4/test_instruments_frozen.py` 断言 `tools/knowledge/e1_panel.py` 与 `block_director/knowledge/hypergraph.py` 的 sha256 等于 P1 冻结值 `tests/plan_v4/instruments.sha256.json`（该文件改动必须走用户批准的独立提交）。
判据：对象＝`tools/knowledge/e1_panel.py` 与 `block_director/knowledge/hypergraph.py`；sha256 与冻结值不等数＝0；分母＝2 个文件；命令 `python -m pytest tests/plan_v4/test_instruments_frozen.py -q`。

**R10（保留物边界；←U4，答 Q1）** 见 §3.1：保留物逐项列名＋理由；这些保留不构成“自研 RAG 未换代”。留证机制：P0 收口时 `work/_plan/plan.md` 的 sha256 记入 `docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md`；§3.1 两表（重建物 5 行、保留物 3 行）随计划一并冻结。
判据：对象＝`work/_plan/plan.md`；含子串“重建物”与“保留物”（计数各 ≥ 1）；分母＝2 个子串；命令 `python -m pytest tests/plan_v4/test_freeze.py::test_plan_contains_boundary_tables -q`。

**R11（指纹与 fail-closed；←U5）** `INDEX_MANIFEST.json` 绑四元组（corpus digest＝`cases.jsonl` 的 sha256；lightrag 版本＝`pip freeze` 片段；embedding 路由＋模型标识；构建参数 mode=hybrid 等）→ `index_fingerprint`。指纹不匹配 ⇒ 路由不可用＋回落＋trace `fallback_reason=index_fingerprint_mismatch`，绝不用脏索引出数。
判据：对象＝lightrag 路由在指纹不匹配场景的出数行为；脏索引起数＝0；分母＝指纹不匹配场景的查询数；命令 `python -m pytest tests/lightrag/test_client.py::test_manifest_mismatch_fails_closed -q`。

**R12（E3 全路由覆盖；←U5）** 三路由（lexical/hybrid/lightrag）经同一 E3 既有检查器读数。
判据：对象＝E3 读数；经验越权数＝0；分母＝检查条数；命令 `python tools/knowledge/e3_report.py --index-dir knowledge_v4 --routes lexical,hybrid,lightrag --out work/e3_v4pop.json`（检查器入口与查询集来源于 P9 首跑前盘点——§2.8-13）。

**R13（E1 成对判读与噪声底；←U3,U8）** 任何 E1 比较必须成对（同总体、同 heldout、≥2 次）；|ΔE1| < 0.02（诊断阈值）⇒ 报告标 `inconclusive`。判据机制化在 `tools/knowledge/e1_report.py`；负例：构造 Δ=0.01 的假读数，断言报告标 inconclusive（`tests/knowledge/test_e1_report.py::test_paired_runs_and_noise_floor`）。
判据：对象＝`tools/knowledge/e1_report.py` 产出的成对比较报告；|ΔE1| < 0.02 的比较对漏标 `inconclusive` 数＝0；分母＝报告中的比较对数；命令 `python -m pytest tests/knowledge/test_e1_report.py::test_paired_runs_and_noise_floor -q`。

### 2.5 用户故事与验收（Given/When/Then）

**S1 研究者**：作为白模强耦合研究者，我要在新总体上把三路由 E1/E3 成对测出，以便在噪声底之上选默认路由。Given `knowledge_v4/eval/heldout_v4.jsonl` 已冻结且 sidecar 服务健康；When `python tools/knowledge/e1_report.py --index-dir knowledge_v4 --heldout knowledge_v4/eval/heldout_v4.jsonl --routes lexical,hybrid,lightrag --runs 2 --out work/e1_v4pop_ab.json`；Then 报告含 6 个 E1 读数（3 路由 × 2 次）＋成对差值＋inconclusive 标记，且 `work/e3_v4pop.json` 三路由经验越权数全 0。

**S2 插件用户**：作为 Blender 插件用户，我要插件进程零新增依赖地用上 LightRAG 检索。Given 服务健康且 `BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG=1`；When 发起检索；Then 返回 `Sequence[Case]`、trace 含 `route=lightrag`＋`index_fingerprint`；Given 服务不可达；Then 回落既有默认路由且 trace 记 `fallback_reason=lightrag_adapter_unavailable`。

**S3 知识维护者**：作为知识产物维护者，我要新语料全部现代且可溯源。Given `docs/knowledge/CORPUS_v4.md` 冻结；When 运行 ingest；Then `excluded.jsonl` 记录全部 year < cutoff 条目、主 manifest 含 0 条旧素材、每条含 `source_ref` 四字段。

**S4 判据守护者**：作为判据守护者，我要总体更换期间仪器零漂移。Given 本计划执行全程；When 任何阶段退出；Then `python -m pytest -q` 全绿，且 `tools/knowledge/e1_panel.py`／`block_director/knowledge/hypergraph.py` 的 sha256 等于冻结值（除非 D9 扩集被批准）。

### 2.6 非目标

1. 不改任何红线判据（§0 全表）与其运行入口。
2. 不在插件进程新增任何运行时依赖（`lightrag`／`onnxruntime`／`torch` 一律不进插件；torch 不进任何进程）。
3. 不使用 LightRAG 的生成端（answer synthesis）；只用其检索端。
4. 不引入边到边（edge-of-edge）一等表示（继承 v3 不确定项 1，留求解侧）。
5. 不自动扩闭集（扩集仅经 D9 裁决；构建期“标记不降权”原则保持，不动 `TYPE_PRIORITY`）。
6. 不删除任何历史台账／旧产物（归档不删除）。
7. 不做服务化部署加固、鉴权、多用户（个人学习；sidecar 仅绑 `127.0.0.1`）。
8. 不重做 S0／S1a（`824005b`／`5aff340` 已入库）。
9. 本轮不追求 E1 达到 0.70（0.70 是既有红线目标，非本轮验收）；本轮验收＝“换代后的 RAG 在新总体上被完整测量”。
10. v3 不确定项 3（基线单次读数）由 P2 成对复验关闭；不确定项 2（年代敏感）由 D1 的 year cutoff＋`source_ref` 关闭。

### 2.7 已知约束

1. 插件进程＝Blender 5.2 Python 3.13.13（numpy 2.3.4，装不了 torch，零运行时依赖）。
2. sidecar＝系统 Python 3.10.11，`pip` 可达 PyPI。
3. DeepSeek 无 embedding 端点（实测 404/405）。
4. 智谱 embedding 当前 1113 无资源包。
5. 上游 HyperGraphRAG 抽取层与槽位闭集 schema 不兼容（§2.1-4）。
6. E1 噪声底：|ΔE1| < 0.02 不作结论（§2.1-5）。
7. 个人学习用途，版权不设门，`source_ref` 必留；理论须外部来源。
8. Windows／PowerShell，仓库 `E:\白模预演codex`。

### 2.8 未核验清单（本轮精炼无法重验，按复核时点挂账）

以下断言沿用第 2 稿（第 2 稿自述为“循环 1 主线核对”），本轮**未重验、不猜**；各条在标注时点由主线复核并记入 `docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md`（或对应留证文档）：

1. （P0）HEAD＝`5aff340`（2026-10-05 06:38，pytest 全绿）、`824005b`＝S0、`5aff340`＝S1a——以 `git log`／`git status` 复核。
2. （P0）循环 1 证据（`work/_plan/review.loop1.md` 等）的存在性与内容；“答 Q1…Q5”所指标记的原文以 `work/_plan/review.loop1.md` 为准。
3. （P0／P11）`AGENTS.md` 状态块与 `docs/knowledge/ACCEPTANCE_STATUS.md` 当前状态段的逐字内容——摘录时复核。
4. （P1）`tools/knowledge/e1_panel.py:50` `DEFAULT_PANEL`／`:52 RELEVANT=4.0` 的行号与常量——冻结 sha256 时以实测为准。
5. （P1）`block_director/knowledge/cases.py:88` 工厂签名；`tools/kb_fetch/build_hypergraph.py` 的 ：182/:250/:275/:314 行号。
6. （P1）上游 `LHRLAB/HyperGraphRAG@d587cdf8c3fe` 三份 sha256（`prompt.py` `2730b18d…`／`operate.py` `1302a159…`／LICENSE `b54ba7ea…`）及所引行号（:18-21/:92/:134-164/:364）——以 `docs/knowledge/S2_UPSTREAM_PREMISE.md` 留证为准。
7. （P1）LightRAG 论文引文（arXiv:2410.05779 作者名单）与 HyperGraphRAG 论文级引文（如需正式化）——对 arXiv 原页复核后修正。
8. （P2）既有 192 行 heldout 的仓库路径与 `cases_fingerprint=48df4a53c2c95637…` 完整值——`e1_report` 缺省值与 P6 对照用。
9. （P2）E1 四次读数（hybrid 35/192、39/192；lexical 41/192、37/192）、台账文件位置、以及四次读数的实验条件（各路由两次读数之间索引是否重建、heldout 是否为同一份文件——§2.1-5“同一份索引、同一 192 行”的确切含义）——以台账原件复核。
10. （P3）“83.6% 素材来自 1900–1920 旧书”的统计口径与命令——记入 `docs/knowledge/ADJUDICATIONS_v4.md`。
11. （D3 裁决前）§2.1-6 三条 API 实测结论（智谱 1113、DeepSeek embeddings 404/405）——复测一次留证。
12. （P6）lexical/hybrid 路由对 `knowledge_v4` 的索引构建入口（既有工具 file:line，或“无既有工具”结论）。
13. （P9）E3 既有检查器的入口（file:line）与其查询集来源（heldout 还是自带集合）。
14. （P9／P11）长跑证据链与既有探针清单的入口命令——以 `docs/knowledge/ACCEPTANCE_STATUS.md` 记载为准原样执行。
15. （P7）`lightrag-hku` 安装版本与上游 commit/tag 的对应关系（自 PyPI 元数据或 `HKUDS/LightRAG` 仓库 tag 解析），连同许可证声明记入 `docs/knowledge/UPSTREAM_LIGHTRAG.md`——安装日解析留证（本计划不预写具体 commit 值）。

---

## 3. 技术方案（怎么做）

### 3.1 「完全重建」的边界（答 Q1）

**重建物（被评测的 RAG 本体，全部换代）：**

| # | 重建对象 | 旧 | 新 |
|---|---|---|---|
| 1 | 语料 | 83.6% 来自 1900–1920 旧书 | 新语料，year ≥ cutoff，四维覆盖（D1） |
| 2 | 抽取实现 | `extract/v18` 单趟 | `extract/v19-seg` 两趟“分段→归属”（上游算法参考＋自研，DeepSeek 驱动） |
| 3 | 检索实现 | lexical／hybrid | 新增 `lightrag` 路由（真接入）；A/B 后按 D8 定默认路由 |
| 4 | 缓存键 | 八分量 | 追加 `corpus_digest` 分量＋`PROMPT_VERSION` 升版（继承 S0 的闭集分量） |
| 5 | 产物总体 | `knowledge/`（v3pop） | `knowledge_v4/` 影子构建 → P10 一次性指针切换（D7 归档） |

**保留物（三类，逐项理由；这些保留 ≠ “自研 RAG 没换”）：**

| # | 保留物 | 理由 |
|---|---|---|
| 1 | 判据执行环境：`tools/knowledge/e1_panel.py`（`DEFAULT_PANEL`/`RELEVANT`）、E3 既有检查器、门①–⑩、heldout 冻结机制、`python -m pytest` 链 | 该组保留物＝**测量仪器**，不是被测的 RAG。换了仪器 ⇒ 新旧读数不可比，A/B 失去意义；且 E1/E3 是红线判据（§0）。lexical/hybrid 两条路由保留为**对照组**（A/B 基线），删除 lexical/hybrid＝删除比较本身 |
| 2 | 表示层：`block_director/knowledge/hypergraph.py` 闭集（18/12/16）＋S0/S1a 机制 | 槽位闭集是白模强耦合研究的**载体**，也是 E3=0 的检查对象；`LHRLAB/HyperGraphRAG` 的超边载荷（一句话＋0–10 完整度分）无 type/role/槽位等价物（§2.1-4），“换成上游表示”＝放弃研究课题本身 |
| 3 | 契约接口：`retrieve(query, *, top_k, cases) -> Sequence[Case]` 与工厂 `(index_dir) -> adapter`（`block_director/knowledge/cases.py:88`） | 该组保留物＝仪器与被测件的接口；接口签名零改动（两签名照录），LightRAG 才能作为**被测实现**接进来 |

### 3.2 架构与数据流

```
构建期（sidecar Python 3.10.11，批量 LLM＝DeepSeek，花费台账 work/corpus_v4/spend.jsonl）：
docs/knowledge/CORPUS_v4.md
  → tools/kb_fetch/ingest_corpus.py ─→ work/corpus_v4/（MANIFEST.json＋excluded.jsonl）
  → tools/kb_fetch/extract_segmented.py（DeepSeekClient；两趟：分段→归属）
  → tools/kb_fetch/build_hypergraph.py --target-dir knowledge_v4 --extractor segmented
       ─→ knowledge_v4/hypergraph.{edges,nodes,vocab,manifest,rejects}（闭集校验：validate_edge）
  → tools/kb_fetch/build_cases_v4.py ─→ knowledge_v4/cases.jsonl
  → （lexical/hybrid 路由在 knowledge_v4 上的索引构建入口：P6 盘点确认——既有工具 file:line 或 P6 新增步骤，§2.8-12）
  → tools/lightrag_service/build_index.py（lightrag＋DeepSeek llm_model_func＋D3 embedding）
       ─→ knowledge_v4/lightrag/（storage/ gitignore；INDEX_MANIFEST.json 入库）

评测期（sidecar；测量＝运行行为，走同一 HTTP 适配器，不走旁路）：
knowledge_v4/eval/heldout_v4.jsonl（192 行，seed=20261005，sha256 冻结）
  → tools/knowledge/e1_report.py → tools/knowledge/e1_panel.py（零改动）→ 台账
  → tools/knowledge/e3_report.py → E3 既有检查器（零改动）→ 台账

运行期：
Blender 插件进程（block_director；stdlib urllib；零新增依赖）
  —HTTP 127.0.0.1:8765→ tools/lightrag_service/serve.py（持 lightrag 运行时＋embedding 路由）
  → 命中回解 case_id → lightrag_adapter 映射 → Sequence[Case] → 既有下游（trace 加法字段）
服务不可达/指纹不匹配 → 回落既有默认路由（hybrid）＋trace fallback_reason
```

### 3.3 改动清单（file:function＋签名）

**新增：**

1. `tools/kb_fetch/extract_segmented.py`
   - `segment_corpus(records: Iterable[CorpusRecord]) -> list[Segment]`（`Segment = dataclass(text: str, source_ref: SourceRef, span: tuple[int, int])`）
   - `attribute_members(segments: list[Segment], llm: LLMClient) -> Iterator[EdgeDraft]`（`EdgeDraft = dataclass(edge_type: str, members: list[str], qualifiers: dict, confidence: int, segment_span: tuple[int, int], source_ref: SourceRef)`）
   - `class DeepSeekClient: def complete(self, prompt: str, *, max_tokens: int = 2048) -> str`（读环境变量 `DEEPSEEK_API_KEY`，base_url `https://api.deepseek.com`，模型 `deepseek-chat`；每次调用追加 `work/corpus_v4/spend.jsonl`）
2. `tools/kb_fetch/ingest_corpus.py`：`load_source_list(path) -> list[SourceRef]`；`download_all(sources, out_dir) -> CorpusManifest`；CLI `--list docs/knowledge/CORPUS_v4.md --out work/corpus_v4/`
3. `tools/kb_fetch/build_cases_v4.py`：`build_cases(corpus_dir, edges_path, out_path) -> None`（Case 形状与检索契约兼容；生成期 LLM 一律 `DeepSeekClient`）
4. `tools/knowledge/freeze_eval.py`：`sample_heldout(cases, size, seed) -> HeldoutSet`；CLI `--cases --size --seed --out`；同时写 `heldout_v4.SHA256`
5. `tools/knowledge/e1_report.py`：`run_route(route, index_dir, heldout, runs) -> RouteReport`；CLI `--index-dir --heldout --routes --runs --out`（`--heldout` 缺省＝既有 192 行 heldout 的仓库路径；该路径于 P2 前由主线核对后写死为缺省值——§2.8-8）；内部调用 `tools/knowledge/e1_panel.py` 既有入口（实际调用点 file:line 于 P2 写入 PROGRESS；`DEFAULT_PANEL`/`RELEVANT` 零改动）
6. `tools/knowledge/e3_report.py`：同构 CLI；调用 E3 既有检查器（调用点 file:line 与查询集来源于 P9 首跑前写入 PROGRESS——§2.8-13）
7. `tools/lightrag_service/build_index.py`：`build_index(cases_path, out_dir, embedding_route) -> IndexManifest`；每条 Case 文档文本＝前缀 `[CASE <case_id>]`＋Case 内容，交给 `LightRAG.insert`；注入 `llm_model_func`＝DeepSeek、`embedding_func`＝D3 路由
8. `tools/lightrag_service/serve.py`：`make_server(index_dir, port) -> ThreadingHTTPServer`（仅绑 `127.0.0.1`）；`GET /health` → `{"status","index_fingerprint","lightrag_version","embedding_route"}`；`POST /query` `{"query","top_k"}` → `{"hits":[{"case_id","score"}]}`（查询 `mode="hybrid"`）
9. `tools/lightrag_service/client.py`：`health(base_url) -> dict`；`query(base_url, query, top_k) -> list[tuple[str, float]]`；CLI 子命令 `health`／`query`（stdlib `urllib.request`）
10. `tools/lightrag_service/requirements.txt`：sidecar 依赖 pin（含 `lightrag-hku`；安装日 `pip freeze` 快照记入 INDEX_MANIFEST）
11. `block_director/knowledge/lightrag_adapter.py`：`make_lightrag_adapter(index_dir) -> adapter`，符合 `block_director/knowledge/cases.py:88` 工厂契约；`retrieve(query, *, top_k, cases) -> Sequence[Case]`；服务地址＝环境变量 `BLOCK_DIRECTOR_LIGHTRAG_URL`（默认 `http://127.0.0.1:8765`）
12. `tools/kb_fetch/sha256_dir.py`：`hash_dir(dir) -> dict[str, str]`；CLI `--out`
13. 测试文件：见 §6
14. 文档：本计划、`docs/knowledge/ADJUDICATIONS_v4.md`、`docs/knowledge/UPSTREAM_LIGHTRAG.md`、`docs/knowledge/CORPUS_v4.md`、`docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md`、`tests/plan_v4/instruments.sha256.json`

**修改（全部为加法，默认行为不变）：**

1. `tools/kb_fetch/build_hypergraph.py`：`:182` 附近新增常量 `PROMPT_VERSION_SEGMENTED = "extract/v19-seg"`（保留 `extract/v18` 常量与旧路径行为）；`CACHE_KEY_FIELDS`（:250）追加 `corpus_digest` 分量（S0 闭集分量保留）；`main()` 新增 `--target-dir/--corpus/--extractor` 参数（不传＝旧行为，保基线）；`fingerprint_components()`（:275）与 `rekey_manifest()`（:314）原样复用
2. `block_director/knowledge/cases.py`：路由注册表新增 `lightrag` 行，受环境变量 `BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG=1` 门控；工厂签名与既有路由零改动
3. trace 面（commit `5aff340` 引入处）：新增加法字段 `route`／`index_fingerprint`／`fallback_reason`（旧字段全部保留；测试断言旧字段保留）
4. `docs/knowledge/ACCEPTANCE_STATUS.md`／`AGENTS.md` 状态块：只追加 v4 状态段

**设计约束（P10 门可达性）**：`tools/`、`block_director/`、`tests/` 下的新增代码**不得硬编码 `knowledge_v4` 字面量**（目录路径一律经 CLI 参数或测试夹具注入）；`docs/` 不在此约束内（P10 的 `git grep` 范围＝`tools block_director tests`）。

**零改动（点名）：** `tools/knowledge/e1_panel.py`、E3 既有检查器、门①–⑩、`block_director/knowledge/hypergraph.py`（闭集／`validate_edge`／`schema_fingerprint`）、两个契约签名、`knowledge/` 现有五件产物（直至 P10）。破坏性改动：无；P10 为数据级搬移（git 历史＋归档件保回退）。

### 3.4 依赖与许可

| 依赖 | 层 | 许可 | 体积 | 进程 |
|---|---|---|---|---|
| `lightrag-hku`（pin 版本） | 检索运行时（只用检索端；默认文件存储＋NanoVectorDB，numpy 向量检索，无需 torch） | MIT（HKUDS/LightRAG） | 安装日实测记 INDEX_MANIFEST | sidecar＋构建期 |
| `onnxruntime`（仅 D3=②时） | 嵌入推理 | MIT | 同上 | sidecar |
| bge 系 ONNX 权重（仅 D3=②时；候选出自 FlagOpen/FlagEmbedding） | 嵌入模型 | MIT | 同上 | sidecar 数据 |
| DeepSeek API | 抽取／LightRAG 内部 LLM | 商用 API（无包体） | — | 构建期＋sidecar |
| 智谱 `embedding-3`（仅 D3=①时） | 嵌入 | 商用 API | — | sidecar |

插件进程新增依赖＝**0**（`tests/knowledge/test_no_new_plugin_deps.py` 机制化断言）。

### 3.5 出处清单

| 设计 | 出处 |
|---|---|
| 两趟“分段→归属”抽取结构 | `LHRLAB/HyperGraphRAG@d587cdf8c3fe`，`operate.py:364`＋`:92`（成员归属最近句的反例结构：本仓取 HyperGraphRAG「先分段再归属」的形状，弃 HyperGraphRAG「挂最近句」的归属规则）；算法参考，零拷贝 |
| `completeness_score` → `confidence`；每记录带分 | 同上 `prompt.py:18-21` |
| LightRAG 检索范式（实体/关系图＋向量混合检索，local/global/hybrid 模式） | `HKUDS/LightRAG`（MIT）；Guo, Z., Xia, L., Yu, Y., Wu, Y., Huang, X., Huang, C. (2024). *LightRAG: Simple and Fast Retrieval-Augmented Generation*. arXiv:2410.05779（引文复核见 §2.8-7）；安装版本→上游 commit/tag 对应关系记 `docs/knowledge/UPSTREAM_LIGHTRAG.md`（§2.8-15） |
| bge 嵌入权重（D3=②候选） | `FlagOpen/FlagEmbedding`（MIT） |
| DeepSeek OpenAI 兼容端点 | DeepSeek API 官方文档（`https://api-docs.deepseek.com`）；本仓实测见 §2.1-6 |
| 槽位超边 schema 翻译层、影子路径＋一次性指针切换、`[CASE <id>]` 前缀映射层、四元组指纹 fail-closed、花费台账、E1 噪声底双报告 | **无出处（自研）**；其中噪声底的实证依据＝本仓四次读数大小关系翻转（§2.1-5） |
| “数据模型翻译层＝自研”的记账规则 | 本仓 ADR-0014 判例 |

---

## 4. 上游复用四档判定（答 Q2）

| 需求 | 上游现状 | 四档判定 | 改成什么形状 | 改造点 | 上游 commit | 许可与差异 |
|---|---|---|---|---|---|---|
| R1（抽取算法结构） | `LHRLAB/HyperGraphRAG`：超边载荷＝一句话＋0–10 完整度（`prompt.py:18-21`）；成员挂最近句（`operate.py:364`＋`:92`）；`entity_type` 开放串；节点名等值合并（`:134-164`） | **③ 改上游也满足不了**：槽位闭集＋qualifier 体系下，满足 R1 需重写其数据模型 ⇒ 按 ADR-0014 判例，翻译层＝自研；故**零拷贝，只记算法参考** | 三条算法参考（两趟分段→归属；completeness→confidence；每记录带分）落 `tools/kb_fetch/extract_segmented.py`（自研实现，docstring 记上游行号出处） | 无上游代码改造点（零拷贝） | `d587cdf8c3fe`（LICENSE sha256 `b54ba7ea…`） | MIT；零代码引入 ⇒ 无衍生义务；`docs/knowledge/S2_UPSTREAM_PREMISE.md` 追加“算法参考清单”节 |
| R4（LightRAG 检索运行时） | `HKUDS/LightRAG`：PyPI 包 `lightrag-hku`；`llm_model_func`/`embedding_func` 为文档化注入点；默认文件存储＋NanoVectorDB（无需 torch） | **① 原生满足**（依赖级接入＋注入 DeepSeek 与 D3 embedding，无需改上游源码） | sidecar 依赖；只用检索端（`mode="hybrid"`），不用生成端；`[CASE <id>]` 映射层＝自研 | 注入配置在 `tools/lightrag_service/build_index.py::build_index` 与 `serve.py::make_server`；上游源码零改 | 安装日 pin（记 `requirements.txt`＋INDEX_MANIFEST；版本→上游 commit/tag 对应关系记 `docs/knowledge/UPSTREAM_LIGHTRAG.md`——§2.8-15） | MIT；依赖级使用不 vendor ⇒ `docs/knowledge/UPSTREAM_LIGHTRAG.md` 记依赖声明与版本；未拷代码，不触发文件级版权保留义务 |
| R5（embedding，备选①） | 智谱 `embedding-3`：API 存在，本 key 1113 无资源包 | **①**（开通资源包即原生可用） | `embedding_route=zhipu_api` | 无 | n/a（服务端） | 商用 API；D3 裁决 |
| R5（embedding，备选②） | `FlagOpen/FlagEmbedding` bge 系权重（MIT）＋ `onnxruntime`（MIT，本机已证可装） | **①** | `embedding_route=onnx_local:<model>`，仅 sidecar | 无 | 模型与 runtime 版本＋权重 sha256 记 INDEX_MANIFEST | MIT；需用户显式批准（D3） |
| R5（DeepSeek 作为 LLM） | `https://api.deepseek.com` OpenAI 兼容 chat（实测 200） | **①** | `DeepSeekClient`＋lightrag `llm_model_func` | 无 | n/a | 商用 API；U10 适用范围（§2.2-U10 澄清） |
| R5（DeepSeek 作为 embedding） | `/v1/embeddings`、`/embeddings`、`/beta/embeddings` 全 404；`GET /models` 405 | **④ 只有改我们的需求才能用**（物理无端点）⇒ **按弃用处理**：embedding 不用 DeepSeek；显式例外写入 R5，路线由 D3 裁决 | — | — | — | — |

注：若用户另指定第三家超图 RAG 上游，须先做 S2 式前提复核（逐行核上游源码＋sha256 留证）再入本表；本计划不预置第三候选。

### 4.1 上游可跟踪策略与衍生许可

| 上游 | 使用方式 | 跟踪策略 | 衍生许可义务 |
|---|---|---|---|
| `LHRLAB/HyperGraphRAG@d587cdf8c3fe` | 零拷贝：只取三条算法参考（§3.5），不改不装其代码 | 不跟踪上游演进；`docs/knowledge/S2_UPSTREAM_PREMISE.md` 已留 commit＋文件 sha256（§2.8-6 复核）作为参考快照 | 无（未拷贝、未分发其源码） |
| `HKUDS/LightRAG`（PyPI `lightrag-hku`） | 依赖级：pip 安装，源码零修改；经文档化注入点 `llm_model_func`/`embedding_func` 注入 | ①`tools/lightrag_service/requirements.txt` pin 精确版本；②`INDEX_MANIFEST.json` 记安装日版本（`pip freeze` 片段）；③升级＝显式改 pin＋重建索引（`index_fingerprint` 含版本 ⇒ 旧索引 fail closed）；④安装日解析版本→上游 commit/tag 对应关系并记入 `docs/knowledge/UPSTREAM_LIGHTRAG.md`（§2.8-15）；**不 fork、不维护 patch** | MIT；依赖级使用（不分发其源码）不触发文件级版权保留义务；`docs/knowledge/UPSTREAM_LIGHTRAG.md` 记依赖声明＋许可证名＋版本 |
| `FlagOpen/FlagEmbedding`（仅 D3=②） | 权重文件＋`onnxruntime` 推理（仅 sidecar） | 权重 sha256＋runtime 版本记 `INDEX_MANIFEST.json` | MIT；同上，记声明即可 |

通用规则：**GPL/AGPL 依赖禁止引入任何进程**（本项目硬约束）；**若未来需要修改上游源码**（当前判定为不需要）：改走 §4 四档判定重审，采用 fork＋patch 分支＋定期 rebase 的跟踪策略，并保留上游 LICENSE 全文与差异清单——该变动须新设待裁决项，不经裁决不得实施。

---

## 5. LightRAG 真接入设计（答 Q3）

1. **进程拓扑**：lightrag 运行时住 sidecar（Python 3.10.11）；插件进程经 stdlib `urllib.request` 访问 `http://127.0.0.1:8765`（仅本机绑定）；插件进程永不接触 embedding（查询文本发到服务端，向量化在 sidecar 完成）。
2. **索引位置与构建**：构建期 `tools/lightrag_service/build_index.py` 以 `knowledge_v4/cases.jsonl` 为语料：每条 Case 的文档文本＝前缀 `[CASE <case_id>]`＋Case 内容，交给 `LightRAG.insert`；存储＝lightrag 默认文件后端，落 `knowledge_v4/lightrag/storage/`（gitignore）；`INDEX_MANIFEST.json` 入库。
3. **谁查**：①插件运行期：`block_director/knowledge/lightrag_adapter.py` → HTTP；②评测期（P9）：`tools/knowledge/e1_report.py` 经 `block_director/knowledge/lightrag_adapter.py`（与插件运行期为同一适配器）→同一 HTTP 服务取数（测量＝运行行为，不走旁路实现）。
4. **embedding 路线**：D3 两备选（智谱 `embedding-3` 或本地 ONNX）；DeepSeek 物理不可用（§2.1-6），为 U9/U10 的显式例外。
5. **缓存失效钥匙**：`INDEX_MANIFEST.json` 四元组（corpus digest＝`cases.jsonl` sha256；lightrag 版本＝`pip freeze` 片段；embedding 路由＋模型标识；构建参数 mode=hybrid 等）→ `index_fingerprint`。适配器在会话首查时比对本地 manifest 与 `/health` 返回的指纹；不一致 ⇒ fail closed：路由标不可用、回落既有默认路由、trace `fallback_reason=index_fingerprint_mismatch`（对抗性用例覆盖）。
6. **E3 仍 = 0 的三条不变量**：①只用检索端，不调用 LightRAG 生成端 ⇒ 无未经 Case 契约约束的自由文本进入下游；②适配器输出必须是 `cases` 参数的子序列（未知 id 丢弃＋trace `unknown_id_dropped`）；③E3 既有检查器零改动，经同一入口覆盖全部三路由。
7. **降级路径语义**：`lightrag_adapter_unavailable` 保留为运行期回落状态（服务不可达），不再是 lightrag 的唯一状态；门控环境变量 `BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG=1` 开启注册。
8. **费用披露**：P9 面板调用量＝路由数 × runs × 192 行 × 2 评委＝3×2×192×2＝2304 次（DeepSeek 评委 1152 次＋GLM-5.3 评委 1152 次；沿用既有判据通道，不属 D6 管辖，在此披露）；LightRAG 构建期实体/关系抽取的 DeepSeek 消耗**纳入** D6 花费台账。

---

## 6. TDD 用例清单（答 Q4 之一）

纪律：每阶段**先写用例、跑出真实红输出**（存 `work/_plan/tdd/<阶段>_red.txt`），实现至绿，重构后全量 `python -m pytest -q` 仍绿；删测试／跳测试／放宽断言＝红线违规。夹具一律录制（无网络），`test_no_live_network` 类用例以 monkeypatch socket 断言之。**命令模板＝`python -m pytest <文件列><命令列> -q`**（命令列给出 `::用例名` nodeid 尾段）。

**用例落盘规则**：用例随所属阶段落盘——`tests/plan_v4/test_freeze.py` 中 `test_plan_loops_complete`／`test_plan_contains_boundary_tables` 于 P0 落盘，`test_adjudications_complete`／`test_corpus_list_frozen` 于 P1 落盘；`tests/plan_v4/test_instruments_frozen.py` 于 P1 落盘（TDD：先红——冻结件缺失——再冻结 sha256 至绿）；`tests/knowledge/test_e1_report.py` 于 P2 落盘且不依赖 P1 冻结件。落盘规则保证各阶段退出时全量 `python -m pytest -q` 可达全绿。判据冻结断言（`e1_panel.py`／`hypergraph.py` 的 sha256）统一由 `tests/plan_v4/test_instruments_frozen.py` 承担，不在其他测试文件重复（第 3 稿中 `tests/knowledge/test_e1_report.py::test_wrapper_keeps_panel_untouched` 与 `tests/plan_v4/test_instruments_frozen.py::test_e1_panel_sha256` 断言重复，本轮合并删除前者）。

| 文件 | 用例 | 断言（判据＋阈值＋分母） | 夹具 | 标记 | 命令 |
|---|---|---|---|---|---|
| `tests/kb_fetch/test_ingest_corpus.py` | `test_source_list_requires_all_fields` | 缺 url/title/author/license/year 任一字段的源，`load_source_list` 报错数＝1；分母＝字段数 | 内联清单 | 负例 | `::test_source_list_requires_all_fields` |
| `tests/kb_fetch/test_ingest_corpus.py` | `test_year_cutoff_excludes_old` | year=1912 的条目进 `excluded.jsonl` 计数＝1，主 manifest 计数＝0；分母＝清单条数 | 含 1912 条目的清单 | **对抗性** | `::test_year_cutoff_excludes_old` |
| `tests/kb_fetch/test_ingest_corpus.py` | `test_manifest_digest_stable` | 同清单两次 ingest 的 corpus digest 相同（相等断言） | 固定清单 | — | `::test_manifest_digest_stable` |
| `tests/kb_fetch/test_extract_segmented.py` | `test_members_localize_within_attributed_segment` | ∀ EdgeDraft：每个成员字符串可在 `segment_span` 指向的 Segment.text 中定位；违例数＝0；分母＝EdgeDraft 数 | 录制 LLM 夹具 | 两趟结构不变量 | `::test_members_localize_within_attributed_segment` |
| `tests/kb_fetch/test_extract_segmented.py` | `test_completeness_to_confidence` | 录制夹具 completeness=7 ⇒ `confidence=7`（相等断言） | 录制 | — | `::test_completeness_to_confidence` |
| `tests/kb_fetch/test_extract_segmented.py` | `test_every_record_carries_score` | 缺 `confidence` 的 EdgeDraft 数＝0；分母＝EdgeDraft 数 | 录制 | 负例 | `::test_every_record_carries_score` |
| `tests/kb_fetch/test_extract_segmented.py` | `test_schema_violation_routed_to_rejects` | 闭集外 `edge_type` 的边：主产物违例数＝0、rejects 计数≥1；分母＝产出记录数 | 录制（含违例边） | **对抗性** | `::test_schema_violation_routed_to_rejects` |
| `tests/kb_fetch/test_extract_segmented.py` | `test_no_live_network` | monkeypatch `socket.socket` 抛异常后，本文件全部用例仍绿（绿数＝用例数） | 录制 | 边界 | `::test_no_live_network` |
| `tests/kb_fetch/test_extract_segmented.py` | `test_deepseek_client_reads_env_key` | `DEEPSEEK_API_KEY` 缺失 ⇒ 构造期报错、请求数＝0 | 环境变量清理 | 负例 | `::test_deepseek_client_reads_env_key` |
| `tests/kb_fetch/test_build_v4.py` | `test_build_writes_shadow_dir_only` | 以临时目录跑 build 后，`knowledge/` 真目录五件产物 sha256 变化数＝0；分母＝5 | 临时目录 | **对抗性** | `::test_build_writes_shadow_dir_only` |
| `tests/kb_fetch/test_build_v4.py` | `test_cache_key_includes_corpus_digest` | 两个不同 corpus digest ⇒ 缓存键不同数＝2；分母＝2 | 内联 | — | `::test_cache_key_includes_corpus_digest` |
| `tests/kb_fetch/test_build_v4.py` | `test_prompt_version_bumped` | 新路径 `PROMPT_VERSION == "extract/v19-seg"`（相等断言）；旧常量 `"extract/v18"` 仍存在 | 常量 | — | `::test_prompt_version_bumped` |
| `tests/kb_fetch/test_build_v4.py` | `test_spend_cap_aborts` | spend 台账触 D6 顶 ⇒ build 退出码 ≠ 0（断言非零） | 假台账 | 负例 | `::test_spend_cap_aborts` |
| `tests/knowledge/test_freeze_eval.py` | `test_heldout_size_and_seed` | size=192、seed 固定 ⇒ 两次采样逐字节相同；行数＝192 | 固定 cases | — | `::test_heldout_size_and_seed` |
| `tests/knowledge/test_freeze_eval.py` | `test_heldout_frozen_sha256` | `heldout_v4.SHA256` 与文件实测不匹配 ⇒ 用例红（断言相等） | 冻结件 | **对抗性** | `::test_heldout_frozen_sha256` |
| `tests/lightrag/test_client.py` | `test_health_parses_fingerprint` | `/health` JSON 解析出 `index_fingerprint`（非空断言） | 进程内假服务器 | — | `::test_health_parses_fingerprint` |
| `tests/lightrag/test_client.py` | `test_service_500_falls_back` | 假服务器返回 500 ⇒ 适配器回落既有默认路由＋trace `fallback_reason=lightrag_adapter_unavailable`（字段相等断言） | 假服务器 | **对抗性** | `::test_service_500_falls_back` |
| `tests/lightrag/test_client.py` | `test_unknown_case_id_dropped` | 服务返回不在 `cases` 池的 id ⇒ 丢弃数＝1、`unknown_id_dropped` 记录数＝1、输出仍是 `cases` 子序列（断言⊆） | 假服务器＋3 条 Case | **对抗性**（E3 不变量） | `::test_unknown_case_id_dropped` |
| `tests/lightrag/test_client.py` | `test_manifest_mismatch_fails_closed` | 篡改 manifest 的 corpus digest ⇒ 路由不可用＋`fallback_reason=index_fingerprint_mismatch`、出数＝0 | 假服务器＋篡改 manifest | **对抗性** | `::test_manifest_mismatch_fails_closed` |
| `tests/lightrag/test_client.py` | `test_manifest_records_llm_and_embedding_route` | `INDEX_MANIFEST.json` 的 `llm_model=="deepseek-chat"` 且 `embedding_route`==D3 裁决值（字段相等断言）；分母＝2 个字段 | 假 manifest（临时文件） | R5 机制化 | `::test_manifest_records_llm_and_embedding_route` |
| `tests/knowledge/test_lightrag_adapter.py` | `test_factory_contract` | `make_lightrag_adapter(index_dir)` 返回可调用且签名匹配 `(query, *, top_k, cases)` | 假服务器 | 契约 | `::test_factory_contract` |
| `tests/knowledge/test_lightrag_adapter.py` | `test_route_flag_gated` | 环境变量未设 ⇒ 路由表含 `lightrag` 数＝0；设为 1 ⇒ ＝1 | 注册表 | 负例 | `::test_route_flag_gated` |
| `tests/knowledge/test_lightrag_adapter.py` | `test_trace_fields` | 命中后 trace 含 `route`/`index_fingerprint`，且 S1a 旧字段全在（旧字段缺失数＝0） | 假服务器 | 兼容 | `::test_trace_fields` |
| `tests/knowledge/test_no_new_plugin_deps.py` | `test_plugin_import_whitelist` | `block_director/**/*.py` 的 import 中出现 `lightrag\|onnxruntime\|torch` 的次数＝0；分母＝全部 import | AST 扫描 | **对抗性**（进程边界） | `::test_plugin_import_whitelist` |
| `tests/knowledge/test_e1_report.py` | `test_paired_runs_and_noise_floor` | 构造 Δ=0.01 的两读数 ⇒ 报告标 `inconclusive`（标记存在断言） | 假读数 | 负例（噪声底机制化） | `::test_paired_runs_and_noise_floor` |
| `tests/plan_v4/test_freeze.py` | `test_plan_loops_complete` | `work/_plan/review.loop1..3.md` 三份＋`plan.md` 存在（4 个文件存在断言） | 文件系统 | P0 DoD（P0 落盘） | `::test_plan_loops_complete` |
| `tests/plan_v4/test_freeze.py` | `test_plan_contains_boundary_tables` | `work/_plan/plan.md` 含子串“重建物”与“保留物”（计数各 ≥1）；分母＝2 个子串 | `work/_plan/plan.md` | R10 机制化（P0 落盘） | `::test_plan_contains_boundary_tables` |
| `tests/plan_v4/test_freeze.py` | `test_adjudications_complete` | `docs/knowledge/ADJUDICATIONS_v4.md` 含 D1–D9 各“已裁决＋日期”（计数＝9） | 文档 | P1 DoD（P1 落盘） | `::test_adjudications_complete` |
| `tests/plan_v4/test_freeze.py` | `test_corpus_list_frozen` | `docs/knowledge/CORPUS_v4.md` 每条源四字段＋year 齐全、四维各≥1 源（违例数＝0） | 文档 | P1 DoD（P1 落盘） | `::test_corpus_list_frozen` |
| `tests/plan_v4/test_instruments_frozen.py` | `test_e1_panel_sha256` | `tools/knowledge/e1_panel.py` sha256 等于冻结值（相等断言；D9 扩集被批准时须以独立提交更新冻结值） | 冻结文件 | 红线（P1 落盘） | `::test_e1_panel_sha256` |
| `tests/plan_v4/test_instruments_frozen.py` | `test_hypergraph_sha256` | `block_director/knowledge/hypergraph.py` sha256 等于冻结值（相等断言；同上例外） | 冻结文件 | 红线（P1 落盘） | `::test_hypergraph_sha256` |

---

## 7. 阶段表 P0–P11（答 Q4 之二）

通用规则：每阶段先落本阶段用例（红）→ 实现（绿）→ 全量 `python -m pytest -q` 绿 → 更新 `docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md`；失败先定位修复，不许跳阶段。

| 阶段 | DoD（可判定） | 依赖 | 串/并 | 产物 | 验收命令（写死） | 回滚动作 |
|---|---|---|---|---|---|---|
| **P0 计划三循环收口** | ①`work/_plan/` 内循环 1–3 的草案、审查（`review.loop1..3.md`）、修订证据齐；②用户明示“开始执行”；③`work/_plan/plan.md` 的 sha256 记入 PROGRESS（R10 留证）；④§2.8-1/2/3 复核完成并记 PROGRESS | — | 串行首步 | 计划 v4 终稿 | `python -m pytest tests/plan_v4/test_freeze.py::test_plan_loops_complete tests/plan_v4/test_freeze.py::test_plan_contains_boundary_tables -q` | n/a（文档态；不满足则不进入执行） |
| **P1 裁决与冻结** | ①`docs/knowledge/ADJUDICATIONS_v4.md` 含 D1–D9 各“已裁决＋日期＋选项”；②`docs/knowledge/CORPUS_v4.md` 冻结（每源 url/title/author/license/year；四维各≥1 源；sha256 记入 ADJUDICATIONS_v4）；③`tests/plan_v4/instruments.sha256.json` 冻结 `e1_panel.py` 与 `hypergraph.py` 的 sha256；④§2.8-4/5/6/7 复核完成 | P0 | 串行 | 三份冻结文档＋冻结哈希 | `python -m pytest tests/plan_v4/test_freeze.py tests/plan_v4/test_instruments_frozen.py -q` | n/a（裁决修订须留痕） |
| **P2 基线成对复验（v3pop，只读）** | ①`tools/knowledge/e1_report.py` 实现（先红后绿）；②`work/e1_baseline_paired_v3pop.json` 含 lexical/hybrid × 各 2 次共 4 读数＋与台账差异记录；③PROGRESS 记 `e1_panel.py` 实际调用点 file:line；④`knowledge/` 前后 sha256 相等；⑤§2.8-8/9 复核完成；⑥`tests/knowledge/test_e1_report.py` 全部用例不依赖 P1 冻结件（判据冻结断言统一由 `tests/plan_v4/test_instruments_frozen.py` 承担——§6 落盘规则） | P0（与 P1 并行受限：`e1_report` 不依赖裁决） | 与 P1/P3 并行 | 基线双读数 JSON | `python tools/kb_fetch/sha256_dir.py knowledge --out work/knowledge.sha256.p2.before`；`python tools/knowledge/e1_report.py --index-dir knowledge --routes lexical,hybrid --runs 2 --out work/e1_baseline_paired_v3pop.json`（`--heldout` 缺省＝既有 192 行 heldout 路径，P2 前写死——§2.8-8）；`python tools/kb_fetch/sha256_dir.py knowledge --out work/knowledge.sha256.p2.after`；`python -m pytest tests/knowledge/test_e1_report.py -q` | 无（只读测量） |
| **P3 新语料入库** | `work/corpus_v4/MANIFEST.json` 全量条目含四字段＋year≥cutoff；`excluded.jsonl` 记录全部被排除旧素材；corpus digest 入 MANIFEST；§2.8-10 复核完成 | P1 | 与 P2/P4 并行 | 语料目录 | `python tools/kb_fetch/ingest_corpus.py --list docs/knowledge/CORPUS_v4.md --out work/corpus_v4/`；`python -m pytest tests/kb_fetch/test_ingest_corpus.py -q` | `Remove-Item -Recurse -Force work/corpus_v4` |
| **P4 抽取实现重建（TDD）** | `tests/kb_fetch/test_extract_segmented.py` 全绿（红输出存档）；全量 pytest 绿；模块仅 stdlib＋录制夹具 | P1 | 与 P2/P3 并行 | 抽取模块 | `python -m pytest tests/kb_fetch/test_extract_segmented.py -q`；`python -m pytest -q` | `git revert <P4 提交>` |
| **P5 L1/L2 影子构建** | ①`knowledge_v4/` 五件产物生成；②主产物闭集违例数＝0（违例全在 rejects）；③manifest 记 `PROMPT_VERSION=="extract/v19-seg"`＋corpus digest；④spend ≤ D6 顶；⑤`knowledge/` sha256 前后相等；⑥rejects 率 ≤ 0.30（超即停，提请 D9） | P3＋P4 | 串行 | 新 L1/L2 | `python tools/kb_fetch/sha256_dir.py knowledge --out work/knowledge.sha256.p5.before`；`python tools/kb_fetch/build_hypergraph.py --target-dir knowledge_v4 --corpus work/corpus_v4 --extractor segmented`；`python tools/kb_fetch/sha256_dir.py knowledge --out work/knowledge.sha256.p5.after`；`python -m pytest tests/kb_fetch/test_build_v4.py -q`；`python -c "e=sum(1 for _ in open('knowledge_v4/hypergraph.edges.jsonl',encoding='utf-8'));r=sum(1 for _ in open('knowledge_v4/hypergraph.rejects.jsonl',encoding='utf-8'));assert e>0 and r/(r+e)<=0.30, r/(r+e)"` | `Remove-Item -Recurse -Force knowledge_v4`（旧目录未动已由 sha256 证） |
| **P6 L3 案例与冻结 heldout** | ①PROGRESS 记案例构造机制盘点（既有工具 file:line 或“无既有工具”结论）；②`knowledge_v4/cases.jsonl` 生成且 Case 形状过契约断言；③`knowledge_v4/eval/heldout_v4.jsonl` 192 行、seed=20261005、sha256 冻结；④PROGRESS 记 lexical/hybrid 路由对 `knowledge_v4` 的索引构建入口盘点（既有工具 file:line 或“无既有工具，P6 新增构建步骤”结论＋落地） | P5 | 串行 | 新 L3＋冻结 heldout＋（如需）lexical/hybrid 索引 | `python tools/kb_fetch/build_cases_v4.py --corpus work/corpus_v4 --edges knowledge_v4/hypergraph.edges.jsonl --out knowledge_v4/cases.jsonl`；`python tools/knowledge/freeze_eval.py --cases knowledge_v4/cases.jsonl --size 192 --seed 20261005 --out knowledge_v4/eval/heldout_v4.jsonl`；`python -m pytest tests/knowledge/test_freeze_eval.py -q` | `Remove-Item -Recurse -Force knowledge_v4/cases.jsonl knowledge_v4/eval` |
| **P7 LightRAG 索引与 sidecar 服务** | ①sidecar 依赖安装并 pin；②索引建于 `knowledge_v4/lightrag/`；③`INDEX_MANIFEST.json` 四元组齐（含 `llm_model=="deepseek-chat"`＋D3 embedding 路由）；④`/health`、`/query` 冒烟通过；⑤`tests/lightrag` 全绿（假服务器）；⑥`docs/knowledge/UPSTREAM_LIGHTRAG.md` 记录 `lightrag-hku` 安装版本、对应上游 commit/tag、许可证声明（§2.8-15） | P6＋D3/D6 裁决 | 测试开发可与 P8 并行 | 索引＋服务 | `python -m pip install -r tools/lightrag_service/requirements.txt`；`python tools/lightrag_service/build_index.py --cases knowledge_v4/cases.jsonl --out knowledge_v4/lightrag --embedding <D3 裁决值>`；（另开终端）`python tools/lightrag_service/serve.py --port 8765 --index-dir knowledge_v4/lightrag`；`python tools/lightrag_service/client.py health --base-url http://127.0.0.1:8765`；`python tools/lightrag_service/client.py query --base-url http://127.0.0.1:8765 --query "追击场景的手持镜头与情绪递进" --top-k 5`；`python -m pytest tests/lightrag -q` | 停服务；`Remove-Item -Recurse -Force knowledge_v4/lightrag` |
| **P8 插件侧适配器** | ①契约测试绿；②门控默认关（未设环境变量时路由表不含 `lightrag`）；③插件 import 白名单测试绿；④全量 pytest 绿 | P7（契约稳定） | 测试开发可与 P7 并行 | 适配器＋注册行＋trace 加法字段 | `python -m pytest tests/knowledge/test_lightrag_adapter.py tests/knowledge/test_no_new_plugin_deps.py -q`；`python -m pytest -q` | 不设 `BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG` ⇒ 行为与 P8 前完全一致（feature-flag 回退） |
| **P9 A/B 双报告（v4pop）** | ①`work/e1_v4pop_ab.json` 含 3 路由 × 2 次读数＋成对差值＋inconclusive 标记；②`work/e3_v4pop.json` 三路由经验越权数全 0；③PROGRESS 记 E3 检查器调用点 file:line＋查询集来源＋结果表 | P7＋P8（服务运行中） | 串行 | 双报告 JSON | `python tools/knowledge/e1_report.py --index-dir knowledge_v4 --heldout knowledge_v4/eval/heldout_v4.jsonl --routes lexical,hybrid,lightrag --runs 2 --out work/e1_v4pop_ab.json`；`python tools/knowledge/e3_report.py --index-dir knowledge_v4 --routes lexical,hybrid,lightrag --out work/e3_v4pop.json` | 无（只读测量） |
| **P10 指针切换与归档（需 D5/D7/D8 裁决落定后放行）** | ①单提交完成归档＋切换；②`git grep -n "knowledge_v4" -- tools block_director tests` 命中数＝0（前提＝§3.3 设计约束）；③全量 pytest 绿；④`git diff <P0 基线提交>..HEAD -- tools/knowledge/e1_panel.py block_director/knowledge/hypergraph.py` 输出为空（D9 扩集被批准时例外且须单独提交）；⑤切换后 baseline_v4 成对读数入台账（标签 `population=v4pop`） | P9＋D5/D7/D8 | 串行 | 切换提交＋`knowledge/_archive_v3/` | `git mv knowledge/hypergraph.edges.jsonl knowledge/_archive_v3/`（五件产物逐一）；`git mv knowledge_v4/hypergraph.edges.jsonl knowledge/`（`git ls-files knowledge_v4` 清单逐一）；`Move-Item knowledge_v4/lightrag knowledge/lightrag`；`python -m pytest -q`；`python tools/knowledge/e1_report.py --index-dir knowledge --heldout knowledge/eval/heldout_v4.jsonl --routes <D8 默认路由> --runs 2 --out work/e1_baseline_v4.json` | `git revert <切换提交>`＋`Move-Item knowledge/lightrag knowledge_v4/lightrag`（归档未删，全量回退） |
| **P11 长跑与收尾** | ①长跑证据链按既有入口原样完成；②RK-13 原样通过；③既有探针清单按 `docs/knowledge/ACCEPTANCE_STATUS.md` 记载的入口原样通过；④`AGENTS.md`／`docs/knowledge/ACCEPTANCE_STATUS.md`／PROGRESS 终态更新（只追加）；⑤门①–⑩全绿 | P10 | 串行 | 终态文档＋台账 | `python -m pytest -q`；长跑与探针既有入口按 `docs/knowledge/ACCEPTANCE_STATUS.md` 记载命令原样执行（零改动；§2.8-14） | n/a（文档态） |

---

## 8. 风险与回退

| 风险 | 触发条件 | 观测方式 | 回退动作 |
|---|---|---|---|
| 智谱 embedding 资源包未开通（D3=①时） | `tools/lightrag_service/build_index.py` 阶段复现 1113 | 构建日志 | 改 D3=② 重建索引；`index_fingerprint` 含 embedding 路由 ⇒ 旧索引不被误用 |
| D3=② 技术性失败（模型加载／推理错误） | P7 构建或冒烟报错 | 构建日志／`/health` | 提请重裁 D3（改 ①） |
| 嵌入质量系统性缺陷（D3 诊断触发） | P9 双报告 ΔE1(lightrag − hybrid) ≤ −0.05 且 lightrag 各次运行 trace 无 `fallback_reason`（诊断阈值，非判据；D3） | `work/e1_v4pop_ab.json` | 提请重裁 D3；不据此切指针 |
| DeepSeek 花费超限 | `spend.jsonl` 触 D6 顶 | 每次调用追加台账；build 循环每 50 调用查顶 | 非零退出；缓存键含 corpus digest ⇒ 续跑不重复计费 |
| v4pop 组内 E1 全面过低 | P9 双报告三路由 E1 读数全部 < 0.10（D5 建议放行下限，诊断阈值）；**跨总体比较因不可比（术语表“总体”）不作为触发条件** | `work/e1_v4pop_ab.json` | 不切指针（D5）；`knowledge_v4` 保持影子；回 P3/P4 诊断语料与抽取 |
| lightrag A/B 无差异 | P9 双报告 \|ΔE1(lightrag − hybrid)\| < 0.02（R13 噪声底） | `work/e1_v4pop_ab.json` | 默认路由维持 hybrid（D8 规则 (a)）；lightrag 保留为可用路由 |
| 闭集外候选暴涨 | rejects 率 > 0.30（D9） | P5 的 assert 命令 | 停并提请 D9 裁决；不许静默扩闭集 |
| sidecar 端口冲突／服务未启动 | `/health` 不通 | 适配器 trace | 按设计回落既有默认路由＋`fallback_reason=lightrag_adapter_unavailable`（既定行为，非故障） |
| lightrag 上游版本漂移 | pip 解析出新版本 | `requirements.txt` 已 pin＋INDEX_MANIFEST 记版本 | 重装 pin 版本；指纹含版本 ⇒ 脏索引 fail closed |
| 案例构造无既有工具可复用 | P6 盘点结论＝“无” | PROGRESS 盘点小节 | `build_cases_v4.py` 以同一 Case 形状从新语料生成（规则：每案例绑定 source_ref＋四维标注），并把“首次固化”记入 PROGRESS |
| lexical/hybrid 路由对 `knowledge_v4` 无既有索引构建入口 | P6 盘点结论＝“无既有工具” | PROGRESS 盘点小节 | P6 新增构建步骤（输出格式与 `knowledge/` 既有索引一致，入口 file:line 记 PROGRESS） |

---

## 9. 待裁决 D1–D9（答 Q5）

**D1 新语料来源与书单**
选项：(a) cutoff=1980，四维各≥1 专门源，清单由主线起草、用户逐条批准；(b) cutoff=2000 更严；(c) 用户自备书单。
代价：(a) 需一次清单批准；(b) 部分经典镜头语言理论源取舍风险；(c) 用户时间成本。
建议：**(a)**。每源四字段＋year 必填；清单冻结于 `docs/knowledge/CORPUS_v4.md`（sha256 记入 ADJUDICATIONS_v4）。

**D2 旧卡处置（含本仓自撰策展卡）**
选项：(a) 全部旧 L1/L2（含 `block_director/knowledge/cards_*.py` 自撰策展卡）归档进 `knowledge/_archive_v3/`，新总体只收外部来源；(b) 纯引用卡经出处审计后带入；(c) 全带入。
代价：(a) 干净、符合“理论须他人写”；(b) 2221 卡逐卡出处审计的人工成本；(c) 违背用户既有裁决。
建议：**(a)**；归档件仍可 grep／查询，不损失学习价值。

**D3 embedding 路线**
选项：(a) `zhipu_api:embedding-3`；(b) `onnx_local:<model>`（FlagEmbedding bge 系，仅 sidecar）。
代价：(a) 需用户开通资源包（当前 1113）、外部依赖、按量计费；(b) 磁盘与首次配置（体积安装日实测记 manifest）、需用户显式批准。
建议：**(b)**（无资源包阻塞、本地可复现、零边际成本）。
重裁触发（诊断阈值，非判据，用户可调）：①技术性失败＝P7 构建或冒烟报错；②读数触发＝P9 双报告 ΔE1(lightrag − hybrid) ≤ −0.05 且 lightrag 各次运行 trace 无 `fallback_reason`（同总体、同 heldout 内的合法比较；排除服务故障）。命中任一 ⇒ 提请用户重裁 D3。

**D4 E1 评委是否换 DeepSeek**
选项：(a) 保持 `("deepseek-chat","glm-5.3")`；(b) 换双 `deepseek-chat`；(c) 其他组合。
代价：(a) 零，历史可比；(b)(c) 判据级改动：全部历史读数不可比、须重跑全部基线，且 (b) 两评委同模型削弱独立性。
建议：**(a)**。U10 经用户澄清不适用本仓自有测量仪器（§2.2-U10）。

**D5 E1 与长跑证据的重定标时机**
选项：(a) 双报告至 P10；切换放行附加条件（诊断阈值，建议值 0.10，用户可调）：P9 双报告中**至少一路由 E1 读数 ≥ 0.10**（组内绝对下限；跨总体比较因不可比不参与放行判断）；切换后成对重定标为 baseline_v4；v3pop 读数永久标 `population=v3pop`；(b) P6 后立即弃旧报告。
代价：(a) 过渡期双份台账工作；(b) A/B 期间无旧对照，切换收益／风险无据。
建议：**(a)**。

**D6 抽取 LLM 预算上限**
机制（不裁）：`spend.jsonl` 逐调用记账（覆盖 P5 抽取、P6 案例生成、P7 lightrag 构建）；触顶非零退出。
选项：(a) 硬顶＝输入 2,000 万 token＋输出 200 万 token（与价格解耦）；(b) 按人民币金额设顶（价格变动需重算）；(c) 只警告不停。
代价：(a) 最稳；(b) 依赖单价；(c) 有超支风险。
建议：**(a)**，数值用户可调。

**D7 旧产物归档方式**
选项：(a) 单提交 `git mv` 入 `knowledge/_archive_v3/`；gitignored 的 `work/` 级旧缓存原地保留不删；(b) 工作区删除靠 git 历史；(c) 双目录并存不切。
代价：(a) 可 grep、可一键 revert；(b) 归档可见性差；(c) 与指针切换矛盾。
建议：**(a)**。

**D8 默认路由规则**
选项：(a) 规则制：paired ΔE1(lightrag − hybrid) ≥ +0.02 且 E3=0 ⇒ lightrag 默认；否则 hybrid 默认、lightrag 可用；(b) lightrag 无条件默认；(c) 永远 hybrid。
代价：(a) 数据说话、需 P9 完整跑完；(b) 若 ΔE1(lightrag − hybrid) < +0.02，默认路由无实证收益（甚至为负）；(c) lightrag 沦为摆设，与 U5 意图不符。
建议：**(a)**。

**D9 闭集扩展权限**
选项：(a) rejects 率 > 0.30 即停；扩集经裁决、单独提交、重算 `schema_fingerprint`、相关读数标不可比；(b) 构建期自动扩闭集。
代价：(a) 构建可能中断待裁；(b) 闭集失控、S0 指纹机制被绕过、E3 检查对象漂移——违背红线精神。
建议：**(a)**，阈值 0.30 首轮使用、可调（诊断阈值，非判据）。
