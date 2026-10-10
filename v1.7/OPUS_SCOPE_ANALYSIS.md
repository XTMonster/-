# v1.7 Opus 5.5 分工范围分析 (2026-10-10)

## 执行目标
Opus 5.5 执行 v1.7 计划中的 **21 张卡**（共 39 卡，DeepSeek 18 卡）。

## 卡号清单与文件覆盖面

### 阶段 A：契约层（1 卡）
- **A6【Opus】**：分工声明契约 (plan schema + SDL 升版 + 迁移)
  - 改：`contracts/plan.py`, `contracts/sdl.py`, `layer2_sdl/sdl_migrate.py`, `layer5_orchestrator/planner.py`
  - 测：`tests/test_responsibility_contract.py`
  - 产：golden 重生成

### 阶段 B：sidecar（1 卡，有红线）
- **B7【Opus，红线】**：聊天端点 + 捷径 + 检索注入 + 持久化
  - 改：`tools/sidecar_server.py`（互斥表：B1→B6 后）
  - 测：`tests/test_sidecar_chat.py`
  - 复核：DeepSeek 必审（不泄漏 key/prompt）

### 阶段 C：Web 前端（6 卡，零构建）
- **C1–C6【全 Opus，串行】**：
  - C1：骨架 + token 处理 + api() helper + 轮询器
  - C2：设置页手风琴（读-改-写纪律，POST JSON 往返）
  - C3：占位帧管线 + Web 精灵组件
  - C4：聊天页气泡 + 状态卡
  - C5：知识库统计·试检索 + 规则列表·开关
  - C6：轨迹俯视画布（可裁剪，最后）
  - 改：`web/` 新建（`index.html`, `app.js`, `pixel.css`, `settings.js`, `chat.js`, `knowledge.js`, `rules.js`, `trajectory.js`, `polish.js`, `assistant.js`）
  - 工具：`tools/gen_placeholder_sprites.py`, `tools/check_assistant_assets.py`

### 阶段 D：Blender 侧（3 卡）
- **D1【Opus】**：ui_bridge 事件推送（DriverEvent → UIEvent）
  - 改：新建 `layer5_orchestrator/ui_bridge.py`，`driver.py` 加 observer 挂接点
  - 测：`tests/test_ui_bridge.py`
  
- **D2【Opus】**：面板按钮 + assistant 面板
  - 改：`panel_main.py`（两按钮），新建 `panel_assistant.py`，`registration.py`
  
- **D3【Opus】**：视口精灵动画（精灵轮询绘制）
  - 改：新建 `layer7_ui/assistant_sprite.py`
  - 工具：sprite 路径解析 + frames.json 加载

### 阶段 E：Stage P 剧本优化（3 卡，E2 有红线）
- **E1【Opus】**：契约与状态机（POLISHING 态 + PolishResult dataclass）
  - 改：新建 `contracts/script_polish.py`，`states.py` 加态，`contracts/assistant.py` 加行
  - 测：`tests/test_script_polish_contract.py`
  
- **E2【Opus，红线】**：双通道 polish + 采纳门
  - 改：新建 `layer5_orchestrator/script_polish.py`，`driver.py` 状态分支，`contracts/enums.py` 加错误码，`tools/sidecar_server.py` 两端点
  - 复核：DeepSeek 必审（不重试、模板唯一真源）
  
- **E3【Opus】**：Web 剧本优化页（diff 双栏 + 建议清单 + 采纳确认）

### 阶段 F：规则开关（1 卡，有红线）
- **F1【Opus，红线】**：哨兵短路 + skipped 留痕
  - 改：`contracts/audit.py` 加 SkippedFinding，`rule_checker.py` 加 configure_rules_disabled
  - 复核：DeepSeek 必审（24→22 调用点零改、空列表零形状差）

### 阶段 G：轨迹几何（1 卡）
- **G2【Opus】**：draw_overlay 消费（路径绘制 + 刻度）
  - 改：`draw_overlay.py`（≤40 行）
  - 依赖 G1（DeepSeek 的 path_ticks/colored_paths 纯函数）

### 阶段 I：导出层（2 卡，I1 有红线）
- **I1【Opus，红线】**：导出沙箱（9+ 项场景设置备份还原）
  - 改：新建 `layer8_delivery/export_sandbox.py`，`export_director.py` 包裹行，`tools/check_assertions.py` 静态规则
  - 复核：DeepSeek 必审（不吞异常、不改参数本身）
  
- **I3【Opus】**：导出包生成器（README + prompt_templates + shot_cards + continuity + responsibility）
  - 改：新建 `layer8_delivery/package.py`，新建 `specs/prompt_templates/`，`rule_checker.py` 追加公开包装，`export_director.py` 调用 narrate() + 采样路径，`delivery/manifest.py` 加 `paths` 键

### 阶段 J：校验扩展（2 卡，全 warning）
- **J3【Opus】**：分工声明消费 + R024（动画白名单冲突检测）
  - 改：`planner.py` 只改 PLAN_SYSTEM_PROMPT，`driver.py` 接入，`shot_builder.py` 三层 skip 逻辑，`rule_checker.py` 追加规则，`export_director.py` 跳过镜渲染
  
- **J4【Opus】**：R025 提示词-白模矛盾检测（默认关）
  - 改：`rule_checker.py` 产实测数据进 shot_audit，`review.py` payload 追加字段，`driver.py` REVIEWING 接入

### 阶段 H：收尾（1 卡）
- **H3【Opus】**：端到端冒烟 + 证据汇总

## 与 v1.6 G2 的交集检查

### ✅ **无文件交集**
v1.6 G2 的红项都在"轴判据、摆位线、构图门"等已落地的代码里（driver.py、rule_checker.py、shot_builder.py）。
v1.7 Opus 的工作主要是：
- **新建**：contracts/script_polish.py, ui_bridge.py, export_sandbox.py, layer8_delivery/package.py, web/* (整个目录)
- **追加**（不改既有逻辑）：contracts/plan.py 新字段, rule_checker.py 新规则检测, driver.py observer 挂接点
- **改 sidecar/panel**：B7/D1–D3 是新功能，不涉及 v1.6 的渲染逻辑

### ✅ **互斥表保证无冲突**
- layer5_orchestrator/driver.py：D1（observer）→ E2（polish 分支）→ I4(DS)→ J3→ J4
- rule_checker.py：F1 → I3 → J1→ J2→ J3→ J4
- contracts/audit.py：F1 独占（J 阶段只改 rule_checker，不碰它）

### ✅ **golden 重生成安全**
A6 的 golden 重生成只增 `responsibility: null` 一个键（既有字段逐字节不变）。
与 v1.6 G2 的 golden（shot_audit/axis 等）**并行存在**，无冲突。

## 预估工作量估算
- **前端（C 阶段）**：6 卡 × 3–4 h/卡 ≈ 20 h
- **sidecar（B7）**：1 h
- **Blender 侧（D）**：4 h（panel 简单，sprite 贵在帧序列化）
- **导出层（I）**：6 h（sandbox 2h + package 4h）
- **契约 + Stage P + 规则**（A/E/F/J）：8 h（工程化多，代码量小）
- **收尾 + 测试全跑**：3 h

**总计 ≈ 45 h**（假设 DeepSeek 并行做 18 卡不卡 Opus）

## 待确认的裁决项（PROGRESS.md 语义裁决项 §1）
- `skip_white_model` 三层操作化是否正确（角色级/镜头级/交付级语义）

## 红线卡复核清单（Opus 完成后 DeepSeek 必复核）
1. **B7**：注入无泄漏 + 白名单空
2. **E2**：不重试 + 模板唯一 + 未采纳恒原稿
3. **F1**：调用点零改 + 空列表零形状差
4. **I1**：不吞异常 + 不改参数
