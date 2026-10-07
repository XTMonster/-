# BlockDirector 执行文档 v1.5 —— 导览与执行纪律

**本包是什么**：一份可直接交给执行模型（DeepSeek v4.1 Flash）落地的改进套件，
含 PRD（要什么）、TDD（怎么设计）、TECH_SOLUTIONS（现存问题逐条怎么修）、
EXECUTION_PLAN（按什么顺序、分多少张任务卡执行）。

**命名说明**：目录名沿用执行文档系列序号（v1.0 → v1.2 → 改进计划 v1.3 →
改进文档 v1.4 → **本包 v1.5**）。注意：AGENTS.md 状态块里的
"v1.5（用户裁决 D6/D7）"是**超图 schema 的裁决轮次**，与本包同名不同义。
本包文内的"本版"一律指本执行包。

**本包不是什么**：不取代《BlockDirector_执行文档_v1.2.md》（权威规格）与
《改进执行文档v1.4.md》；本包是**叠加在 v1.4 与超图 hg/v2 已落地现状之上**
的下一轮改进。凡本包与 v1.2 冲突处，以本包为增量、v1.2 为底座。

## 文件清单（与本文件同目录）

| 文件 | 作用 | 谁读 |
|---|---|---|
| `README.md`（本文件） | 执行纪律、全局红线、使用方式 | 执行模型**每次会话开始必读** |
| `PRD.md` | 产品需求：定位、问题、需求、验收指标 | 执行模型通读一次即可 |
| `TDD.md` | 技术设计：契约 schema、数据流、四通道规则架构 | 执行契约/规则类任务卡前必读对应小节 |
| `TECH_SOLUTIONS.md` | OPEN_ITEMS_20261007 逐条技术方案（分"可执行/须裁决/不要动"三档） | 执行修复类任务卡前必读对应条目 |
| `EXECUTION_PLAN.md` | 7 阶段 27 张任务卡 + 并行分析（附录 B），每张自包含 | **一次只取一张卡执行** |

## 给执行模型（DeepSeek v4.1 Flash）的使用规则

本包按"执行模型上下文注意力有限"设计：

1. **一次只执行一张任务卡**。不要把整个 EXECUTION_PLAN 一次性读完再动手；
   每张卡自包含：目标、必读文件、步骤、验收命令、红线、完成定义。
2. **每张卡的"必读"按顺序读**，读完再动手；卡外文件非必要不读。
3. **每完成一张卡**：跑卡内验收命令 → 全绿才算完成 → 再取下一张。
   验收红时不许带红进入下一张。
4. **遇到卡与代码现状不符**（路径不存在、函数已改名）：停下来，把差异记进
   该卡的"执行记录"，**不许自行改设计**；差异属于判据/门槛的一律升级给用户。
5. **标"须用户点头 / 待裁决 / GATE / ⚖️"的事项只准备材料，不动手改**。
   裁决清单见 TECH_SOLUTIONS.md §裁决闸门。

### 交接提示词模板（用户把任务卡发给 DeepSeek 时，连同任务卡全文一起发）

```
你是 BlockDirector 仓库的执行模型。仓库根：E:\白模预演codex。
先读 docs/执行文档v1.5/README.md 的全局红线 R-1…R-10，然后只执行随附的任务卡
P?-T?（卡文见下）。不许做卡外的事；判据/阈值/门限不许动；cards[] 与代码现状
不符就停下来报告，不许自行改设计。完成后汇报：改动文件清单、验收命令输出的
末尾 5 行、与卡不符之处（如有）。
【任务卡 P?-T? 全文粘贴在这里】
```

## 全局红线（每张任务卡都适用，不再逐卡重复）

R-1. `block_director/contracts/` 与 `block_director/utils/` **永不 import bpy**。
R-2. 任何碰 bpy 的代码必须过 `block_director/utils/threading_guard.py`
     （`@main_thread_only`）。
R-3. `.ps1` 文件 **ASCII-only**（PowerShell 5.1 把无 BOM 的 UTF-8 当 ANSI 解析）；
     调 Blender 的 ps1 保持 `$ErrorActionPreference = 'Continue'`，
     显式检查 `$LASTEXITCODE`。
R-4. 改 `contracts/config.py` 的默认值/键后，必跑 `python tools/gen_specs.py`，
     保证 `specs/config.default.yaml` 与代码逐字节一致。
R-5. **判据/阈值/门限一个字不许动**。发现判据本身有问题 → 记录、停手、
     升级给用户裁决。历史上每一次"顺手改判据"都被记为事故。
R-6. 超边 schema 的单一真源是 `block_director/knowledge/hypergraph.py`
     （`NODE_TYPES`/`QUALIFIER_KINDS`/`EDGE_TYPES`/`VALUE_DOMAINS`/`QUERY_KEYS`），
     任何工具/脚本**导入它**，不许抄第二份。
R-7. 动作类型与参数键的单一真源是 `block_director/motion/model.py`
     （`ACTION_TYPES`/`ACTION_PARAMS`）；工具 schema 从它渲染，不手抄。
R-8. 删边/改索引/改夹具 = **换代**：必须先按 A6 流程显式登记＋最小重跑，
     不许把换代洗成"没换行"（`repin()` 会拒）。
R-9. 证据留痕：每轮执行的实测读数落 `docs/evidence/<run-id>/`，
     措辞区分"实测/推断/待核"，不许把推断写成结论。
R-10. GLM_API_KEY 只从环境变量读；中文角色名不走 PowerShell 5.1 命令行
      （ANSI/GBK 解码会炸），必须 Python 进程内传参。
R-11. golden 夹具（`fixtures/expected_*.json`）只允许通过
      `python tools/gen_golden.py` 重生成，且重生成前必须 diff 确认变化
      **只有新增的可选字段/版本号**，不许手改夹具。

## 环境约束（2026-10-07 实测）

- **C 盘仅剩约 2.7 GB**：不许 `pip install` 新包、不许下载模型；
  pytest 的 tmp 在 `%TEMP%`（C 盘），**并发 pytest 进程 ≤ 2**；
  大批量跑测试前先确认余量。
- `~/.cache/huggingface`（19.2 GB）**故意不删**（HF 只有镜像可达）。
- 回退通道现状：Kimi 余额挂起（429）；GPT-6A 仅显式回退（Cloudflare 524
  包线）；GLM-5.3 有抖动（900 s 超时 vs 275 s 成功，根因未查）——
  任何依赖外部评委的任务卡都要有"评委不可用就跳过并记录"的退路，
  GLM 类调用**串行**，不并发。

## 执行入口

从 `EXECUTION_PLAN.md` 的"阶段 0"第一张卡开始。阶段之间有**阶段门**：
全量 `python -m pytest` ＋ `tools/run_tests.ps1` 全绿、证据落盘后才进入下一阶段。
可并行的卡见 `EXECUTION_PLAN.md` 附录 B（多执行者或插空时用；单执行者按
附录 A 速查顺序即可）。
