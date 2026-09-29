# BlockDirector — 领域上下文

> 单上下文布局（见 `docs/agents/domain.md`）：术语表、边界与目录地图都在这
> 一份文件里；架构决策记录在 `docs/adr/`。

## 一句话

**BlockDirector 是一个 Blender 插件**：把**中文分镜剧本**变成**白模预演参考
视频**（每镜 mp4 ＋ 合片 ＋ 首帧 PNG ＋ `shots.json` ＋ `prompts.md`），供
AI 视频生成当参考。

## 核心术语

| 术语 | 含义 |
|---|---|
| **声明（declared）** | 剧本原文里**显式写出**的东西：镜号、机号、拍摄手法、技巧、台词、时长、角色、地点、灯光、音效。解析结果是 `ParsedScript.declared_shots`（`layer1_input/shotlist.py`）。 |
| **规划（planned）** | LLM 产出、经 schema 校验后的 `Plan`（`contracts/plan.py`）。优先级是 **声明 > brief > draft**：剧本写死的字段由驱动器钉在计划上，模型只能补它没写的东西。 |
| **契约（SceneContract）** | 把一镜的语义（情绪 / 意图 / 关系 / 动作 / 台词 / 特效）**收敛成可执行描述**的中间层（`layer5_orchestrator/scene_contract.py`）。它回答"谁看谁、谁在说话、哪里没落实"，是 R013/R019/F2 的共同上游。 |
| **oracle** | **不受被测实现自身通道影响**的判定来源。渲染、网格几何、实际发出的 prompt、人工标注的 held-out、`audit_log.jsonl` 的逐次事件都算；"读被测实现自己写出的汇总字段就等于通过"**不算**。 |
| **降级（degraded）** | 运行没能按正常路径完成，但仍有产物。**不是成功**：`snapshot()["degraded_reason"]` 里必须写明原因（例如预算触顶走 `_degrade_to_finish`）。 |

## 目录地图

| 目录 | 职责 | 允许 import bpy？ |
|---|---|---|
| `block_director/contracts/` | 契约层：配置、枚举、计划、SDL、错误码、线协议 DTO。**单一真源**，`specs/*.yaml` 与它同步。 | **否** |
| `block_director/utils/` | 工具：AABB、几何、日志、路径、线程护栏。 | **否** |
| `block_director/cinema/` | 纯取景/构图/轴线/排片/运动学：`framing.py`、`composition.py`、`anchor.py`（角色竖直锚点）、`schedule.py`、`camera_motion.py`。 | **否** |
| `block_director/motion/` | 动作库与分层合成、§9.7 冲突仲裁、错开策略。 | **否** |
| `block_director/layer1_input/` | 剧本解析：格式检测、分镜表、对白计时、共指消解。 | **否** |
| `block_director/knowledge/` | Light RAG 卡片（BM25 兜底）与（P14 起）超图/案例层。 | **否** |
| `block_director/layer2_sdl/` | SDL 组装、校验、迁移。 | **否** |
| `block_director/layer3_engine/` | 唯一"动手改场景"的层：角色工厂、取景落地、动作烘焙、标签烘焙、规则校验、事务、检查点。 | 是 |
| `block_director/layer5_orchestrator/` | 状态机、阶段 S/A/B1/B4/B5、预算、合规、SceneContract、GUI 与 headless 两个入口。 | 部分（`modal_operator.py` 用 bpy；`driver.py` 等不得用） |
| `block_director/layer6_audit/` | 审计日志与 LLM trace。 | **否** |
| `block_director/layer7_ui/` | 面板与视图叠加。 | 是（`run_settings.py` 例外，它刻意保持无 bpy 以便纯层单测） |
| `block_director/layer8_delivery/` | 导出：逐镜渲染、首帧、合片、深度、相机轨迹。 | 是 |
| `block_director/layer9_persistence/` | 工程保存/加载/重放。 | 部分（`replay.py` 无 bpy） |
| `block_director/delivery/` | 交付物内容：`manifest.py`（`shots.json`）、`prompts.py`、`depth.py`。 | **否** |

## 硬边界（改代码前先看这条）

**纯层清单**：`contracts/`、`utils/`、`cinema/`、`motion/`、`layer1_input/`、
`knowledge/`、`delivery/`、`layer6_audit/`、`layer7_ui/run_settings.py`
**不得 import bpy**——它们是纯层，pytest 直接跑。`layer3_engine/__init__.py`
会拉起 bpy 链路，所以纯模块**不要**放进去（`cinema/anchor.py` 就是为此单独
存在的）。

**主线程**：任何触碰 bpy 的入口都要过 `utils/threading_guard.py` 的
`@main_thread_only`。

**契约同步**：`contracts/` 与 `specs/openapi.yaml` / `specs/config.default.yaml`
必须同步——改配置默认值先跑 `python tools/gen_specs.py`。

**字段纪律**：交付物字段的**生产者**与**消费者**都要写清楚；没有生产者的
字段按"死字段"处理（v1.4 §3.5）。
