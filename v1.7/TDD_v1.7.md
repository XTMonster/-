# BlockDirector v1.7 技术设计文档（TDD）—— 前端界面、像素小助手 与 参考包交付闭环

| 项 | 值 |
|---|---|
| 版本 | v1.7.5（2026-10-10 **细节完善版配套修正**：§4.1 UIConfig 改为向既有类追加（config.py:334 实读已存在）、§14.1 SDL 升 **1.7**（sdl.py:25 实测 1.6 已占）、§4.4 SkippedFinding 归属 contracts/audit.py＋rules_disabled 模块级注入、§6.1/§11 校验器改 pytest 包装、§7/§12.2/§13.2/§13.3 行号全部复数刷新；执行侧细节见《改进计划》v1.7.5 与附录 X3 勘误表。v1.7.4：双执行者版。v1.7.3：严格自审 4 硬伤＋10 歧义。v1.7.2：M1–M5 并入。v1.7.1：首轮自审 7 项） |
| 日期 | 2026-10-08 |
| 配套 | `PRD_v1.7.md`（需求/判据）、`技术方案_v1.7.md`（选型论证）、`改进计划_v1.7_deepseek.md`（执行卡）、`调研依据_痛点调研与功能评估.md`（R-痛点） |
| 地位 | **接口单一真源**。改进计划卡片一律引用本文件章节号；代码与本文件冲突时以本文件为准并回改代码 |

---

## 1. 模块划分与依赖方向

```
web/                        纯静态前端（零构建，sidecar 直接服务）
  index.html  app.js  pixel.css  assets/assistant/*.png  frames.json

tools/sidecar_server.py     新增 UI 路由（§7），仍不引入新 pip 依赖
block_director/
  contracts/
    assistant.py            状态→clip 映射单一真源（§3，字符串键）
    rule_catalog.py         规则元信息目录（§7 rules 端点的数据源）
    ui_events.py            UIEvent DTO（§2.1）
    script_polish.py        PolishResult＋polish 的 schema/prompt 模板（§9，双通道共用）
    target_models.py        规格表 loader（§12.1）
    config.py               新增键（§4.1）
  layer7_ui/
    assistant_sprite.py     视口精灵（bpy/gpu，仅绘制）(§6.3)
    panel_assistant.py      面板：token 展示、开 Web 页按钮、精灵开关
  layer5_orchestrator/
    ui_bridge.py            driver → sidecar 事件推送（纯 urllib）(§2.2)
    script_polish.py        Stage P 状态机侧（§9）
  layer3_engine/rule_checker.py  哨兵短路（§4.4）＋ continuity_snapshot（§12.2）＋ R020–R025（§13.3）
  layer8_delivery/
    export_sandbox.py       导出沙箱（§13.1）
    package.py              reference_pack 生成（§12.2）
    target_advisor.py       规格对齐与切片建议（§12.3，纯函数）
  cinema/camera_narration.py     运镜文字化器（§13.2，纯函数）
overlay/geometry.py         路径着色/帧刻度几何（§10）
```

依赖红线不变：`contracts/`、`utils/`、`overlay/geometry.py`、`cinema/camera_narration.py`
**永不 import bpy**；`ui_bridge` 只许用 stdlib `urllib`。

## 2. 运行状态事件流（plugin → sidecar → web）

### 2.1 `contracts/ui_events.py::UIEvent`

```python
@dataclass
class UIEvent:
    seq: int                 # 单调递增，Web 端用 since=seq 增量拉
    ts: float                # time.time()
    kind: str                # state_change | shot_progress | llm_call | audit | chat | error
    state: str = ""          # DriverState.value，kind=state_change 时必填
    shot_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
```

约束：`payload` 里**禁止**出现 api_key、prompt 全文（trace 已有自己的落盘通道，UI 事件只带摘要）。

### 2.2 `layer5_orchestrator/ui_bridge.py`

- `UIBridge(url, token, enabled)`：driver 每次状态迁移、每镜完成、每次 LLM 调用各发一条；
- 发送失败/超时（≤0.5 s）**静默吞掉并计数**（`dropped_events`）——R-UI-2；
- 推送在后台线程，绝不阻塞状态机（对齐 CALLING_LLM 的既有后台线程模式）。

## 3. 小助手状态映射（单一真源 `contracts/assistant.py`）

**键用字符串**（`DriverState.value`），不用枚举本体：`DriverState` 定义在
`layer5_orchestrator/states.py`，而 contracts 不许反向 import layer5。
`DriverState` 是 `StrEnum`，字符串键与枚举成员**相等且同 hash**。

```python
CLIP_BY_STATE: Dict[str, str] = {
    "IDLE": "sleep",
    "UNDERSTANDING": "read",
    "PLANNING": "think",
    "CALLING_LLM": "think_wait",
    "EXECUTING_TOOL": "build",
    "BUILDING": "build",
    "EDITING": "think",
    "AWAIT_HUMAN": "ask",
    "REVIEWING": "inspect",
    "CHECKING": "inspect",
    "REPAIRING": "fix",
    "FINISHING": "pack",
    "DONE": "celebrate",
    "ERROR": "dizzy",
    "CANCELLED": "sit",
    # 卡 E1 追加："POLISHING": "read",
}

def clip_for_state(state: str) -> str:
    """未知态回落 "sit"，永不抛异常（UI 是附属品）。"""
```

契约测试 `tests/test_assistant_contract.py`：
- `set(CLIP_BY_STATE) == {s.value for s in DriverState}`（测试侧 import 枚举对拍，PRD A-A-1）；
- 每个 clip 值在 `web/assets/assistant/frames.json` 中存在；
- clip 名合法字符 `[a-z_]+`；未知态回落 `"sit"`。

## 4. 配置契约变更（`contracts/config.py`）

### 4.1 新增键（全部带默认值，旧配置零 error 加载）

| 键 | 类型/默认 | 校验 |
|---|---|---|
| `llm.thinking_level` | `str = "off"` | ∈ {off, low, medium, high}，否则 **CFG_170** warning 并回落 off |
| `audit.rules_disabled` | `List[str] = []` | 元素须匹配 `^R\d{3}$`，非法元素 **CFG_171** warning（不 error） |
| `ui.enabled` | `bool = True` | False 时 ui_bridge 不发事件、不注册精灵 |
| `ui.viewport_sprite` | `bool = True` | 视口精灵开关（**扁平键，钉死**） |
| `ui.web_auto_open` | `bool = False` | run 开始时是否自动开浏览器（默认不开） |
| `script_polish.enabled` | `bool = False` | False 时链路零行为差（PRD A-U3-1） |
| `script_polish.max_suggestions` | `int = 20` | 1–100 |
| `delivery.target_model` | `str = "seedance_2.5"` | 值须 ∈ `specs/target_models.yaml`，未知值 **CFG_172** warning 回落（消费者 §12.3） |
| `guard.scale_drift` | `float = 0.05` | ∈ (0,1)，**CFG_173**；R020 阈值（**待实测校准**） |
| `guard.cam_accel_max` | `float = 8.0` | **单位 m/s²**，>0，**CFG_174**；R023 阈值（**待实测校准**） |
| `guard.compound_motion_max` | `int = 2` | ≥1，**CFG_175**；R021 单镜复合运动上限（R-痛点 P4） |
| `guard.prompt_conflict_check` | `bool = False` | R025 总开关，**默认关**；开需用户显式（CFG_176 备号，本节不产生校验码亦可） |

**错误码避让（实证）**：`CFG_021–023` 已被占用（2026-10-10 复数：CFG_023 在
config.py:498；:500 注释原文"TDD 草拟的 CFG_021–023 已被占用，顺延到 215–217"），
`CFG_215–217` 属 v1.6 guard 段。**v1.7 用 17x 段**：CFG_170–176（按上表分配）。

**v1.7.5 修正（实证）**：`UIConfig` **已存在**（config.py:334，含
`show_axis/show_composition/show_safe_area/show_labels` 四个 overlay 开关）且已挂
`AppConfig.ui:` 节（:452）——`ui.enabled`/`ui.viewport_sprite`/`ui.web_auto_open`
三键**追加进既有 `UIConfig`**，不新建第二个 Ui 类（同名节双 dataclass 会撞车）；
只有 `ScriptPolishConfig` 是新建 `@dataclass`（挂 `script_polish:` 节）。
guard 键进既有 `GuardConfig` 节（注意 `scale_drift` 与既有 `size_drift`(:364)
命名相近、语义不同，注释写清区别）。`CONFIG_VERSION` 升 `"1.4.0"`；
`tools/gen_specs.py` 重跑，`specs/config.default.yaml` 同步（铁律：不手改）。

### 4.2 思考强度映射（集中在 sidecar 一处，插件不感知）

`tools/sidecar_server.py` 新增 `_apply_thinking(body, level, provider)`：

| level | OpenAI 兼容（o 系/gpt-5） | DeepSeek | 百炼 qwen | 本地 Ollama |
|---|---|---|---|---|
| off | 不带 reasoning 字段 | `chat.completions`（非 reasoner） | `enable_thinking=false` | `think=false` |
| low | `reasoning_effort="low"` | reasoner + 小 `max_tokens` 下限提示 | thinking budget 小 | `think=true` |
| medium | `"medium"` | reasoner 默认 | 中 | `think=true` |
| high | `"high"` | reasoner 默认 + 超时提醒 ≥600 s | 大 | `think=true` + num_ctx 提示 |

硬约束（证据：`docs/evidence/20261007-v15-bailian/` 实测）：
- 百炼思考模式**拒收** `tool_choice=required` → level≠off 且 provider=bailian 时自动降级为 auto，并在响应 trace 记 `tool_choice_downgraded: true`；
- 映射只准改请求体，**不改判据、不改预算键**；provider 不在四行内时原样透传。

### 4.3 key 存储（R-UI-1 的落地）

- Web 设置页 key 走独立端点 `/v1/ui/secret`（§7）；
- 落盘 `%APPDATA%/BlockDirector/secrets.json`（POSIX `~/.config/blockdirector/secrets.json`），0600，`{"<provider>": "<key>"}`；
- 读取优先级：环境变量 > secrets.json > 配置文件 `llm.api_key`（兼容旧行为）；
- 掩码：长度 <8 全 `*`；否则前 3 字符 + `…****`；HTTP 响应/trace/审计一律掩码；
- 配置文件写盘时 `llm.api_key` 恒写 `""`（证据：`fixtures/local_*.config.yaml` 就在仓里）。

### 4.4 规则开关：哨兵方案（**v1.7.3 二次修正分流点**）

实证链（全部实读，行号 2026-10-10 复数）：
- `_error/_warning` 直推调用点 **22 处**（分布 rule_checker.py 全文；旧写 24 已漂移），
  `_finding`(:56) 返回 None 会把 None 直接塞进 `findings` 列表（:619 起）——None 方案不可行；
- `finish()`（:633，`check_shot` 内嵌闭包）**只负责还原帧号**，不组装 findings——
  v1.7.1 写的"finish() 分流"不可行；
- findings 的收口是 `AuditResult.from_findings(findings, target=shot_id)`
  （:658 与 :972 两处，外加 `layer5_orchestrator/review.py:91` 的 LLM 审核路径——
  分流做在类方法里，三处自动全覆盖）——**真正的单点在这里**。

钉死方案：

```python
# contracts/audit.py —— v1.7.5 修正归属：SkippedFinding 是 DTO，定义在 contracts
# （audit.py 不许 import layer3，依赖方向红线）；rule_checker.py import 它。
@dataclass
class SkippedFinding:
    rule: str
    skipped: bool = True

# rule_checker.py：rules_disabled 不 import 插件侧 settings 单例（会成环且不可测），
# 改模块级注入 configure_rules_disabled()，由审核入口在 check 前同步。
def _finding(severity, rule, code, message, ...):
    if rule in _RULES_DISABLED:
        return SkippedFinding(rule=rule)
    ...                        # 原逻辑一行不动
```

- 24 个调用点零改动（列表里多的是同形 dataclass）；
- **分流点在 `AuditResult.from_findings`**（**实证定位：`contracts/audit.py:147`**，
  类定义在 :116）：入列含 `SkippedFinding` 时分离到 `result.skipped[]`，真 Finding
  进 `result.findings`；`finish()` 不动；
- 只此一处消费 `rules_disabled`；阈值常量不暴露到 UI（PRD §3.6 红线）。

## 5. 聊天后端

- `POST /v1/ui/chat`：body `{session_id, message}` → sidecar 走 `call_upstream`；
  system 注入：插件用法摘要 + 试检索结果（与 `/v1/retrieve` 同一 retrieve 函数）；
- 会话持久化 `runs/<run-id>/chat.jsonl`（无 run 时 `runs/_idle/chat.jsonl`），append-only；
- 状态问答捷径：消息**包含**（`re.search`，非锚定）`状态|进度|跑到哪` 时不调模型，
  直接从事件缓冲答（v1.7.3 修正：`^(状态|…)` 锚定写法匹配不到"现在跑到哪了"）；
- 写操作白名单：v1.7 为空。任何"帮我改/重新生成"语义回固定文案＋引导到面板按钮。

## 6. 精灵资产管线

### 6.1 帧表 `web/assets/assistant/frames.json`

```json
{
  "base_size": 48,
  "fps": 12,
  "palette": {"cyan": "#2EC4E6", "purple": "#3B1D5A", "yellow": "#F6C90E",
              "white": "#F2F2F0", "orange": "#E8791A"},
  "clips": {
    "sleep":  {"file": "sleep.png",  "frames": 6, "loop": true},
    "think":  {"file": "think.png",  "frames": 8, "loop": true}
  }
}
```

- 每 clip 一张横向精灵表 PNG（宽 = 48×frames，高 = 48）；
- 校验器 `tools/check_assistant_assets.py`（纯 stdlib：PNG 尺寸读 IHDR 固定字节即可，
  生成用 stdlib `zlib` 压缩写 PNG——两端都不引 PIL）：尺寸整除、帧数 ≥2、
  clip 名 ∈ 映射值域、文件存在；**校验器 import `contracts/assistant.py`**；
  **v1.7.5 修正挂接方式**：run_tests.ps1 的 `$checks` 探针清单每条都在 Blender 里跑，
  纯 stdlib 校验器不走探针——照 `tests/test_assertion_hygiene.py:18` 先例用
  importlib 包成 `tests/test_assistant_assets.py` 进 pytest，不占探针名额；
- 占位帧：`tools/gen_placeholder_sprites.py` 程序生成，管线验收不依赖美术。

### 6.2 Web 渲染

CSS `image-rendering: pixelated`＋`steps(frames)` 逐帧跳；Pointer Events 拖拽；
`position: fixed` 右下角默认；位置存 localStorage。

### 6.3 Blender 视口精灵 `layer7_ui/assistant_sprite.py`

- 启动预载全部 clip 图集为 `gpu` 贴图；modal timer 0.1 s 换帧；draw 回调只 blit
  （<1 ms，回调内不读盘不解码）；
- `--background` 下 draw_handler 不触发（既有纪律），测试断言注册与帧表加载；
- 资产路径两级解析：插件根相对 `web/assets/assistant/` + `BD_ASSISTANT_ASSETS`
  环境变量覆盖（打包分发见 PRD 风险 Q6）。

## 7. sidecar 新增路由

**鉴权分层（钉死）**：
- `/v1/ui/*` **全部**过 `_authorised`（Bearer token）；浏览器 `fetch` 由 JS 统一带头；
- 静态资源（`/`、`/static/*`）**免鉴权**：浏览器原生资源加载（`<script src>`/`<link>`）
  无法带 Authorization 头；静态文件非敏感；**敏感数据一律不许走静态路径**；
- token 经 `?token=` 进页面后，前端立即 `sessionStorage` 转存并 `history.replaceState`
  抹掉 query。

**配置文件路径解析**：sidecar 新增 `--config` 启动参数；缺省解析与
`AppConfig.load(None)` 的默认路径**完全一致**（执行时以该函数实读为准，不许猜路径）。

**YAML 处理（v1.7.3 钉死）**：sidecar 的 YAML 读写一律复用
`contracts/config.py::parse_yaml` / `dump_yaml`（:759–767 实读存在，PyYAML 由
Blender/仓库环境提供）——**不许 import 第二份 YAML 解析器，也不许新写迷你解析器**。

| 方法/路径 | 功能 | 请求体 → 响应 |
|---|---|---|
| `POST /v1/ui/events` | 插件推事件（§2） | `UIEvent` → `{accepted: true}`；环形缓冲 2,000 条（重启清空是设计内） |
| `GET /v1/ui/events?since=N` | Web 增量拉事件 | → `{events: [...], latest_seq: N}`（轮询 ≥1.5 s） |
| `GET /v1/ui/config` | 读配置（key 掩码） | → `AppConfig.to_plain()` ＋ `api_key` 掩码（§4.3） |
| `PUT /v1/ui/config` | 写配置（不含 key） | 全量 YAML（parse_yaml 解析）→ 校验 → 写盘 → `{issues: [...]}`；error 级 Issue 拒写；写盘前强制 `llm.api_key=""` |
| `PUT /v1/ui/secret` | 写 key | `{provider, api_key}` → secrets.json（§4.3）→ `{saved: true}`，不回 key |
| `POST /v1/ui/chat` | 聊天（§5） | `{session_id, message}` → `{reply, sources: [...]}` |
| `GET /v1/ui/knowledge/stats` | 知识统计 | 实读 `knowledge/*.jsonl` 行数 → `{cards, edges, cases}`（缺则 0，只数行） |
| `GET /v1/ui/state_map` | 状态→clip 映射 | → `CLIP_BY_STATE`（**从 contracts import**） |
| `GET /v1/ui/rules` | 规则元信息 | → `contracts/rule_catalog.py` 的 `[{id, severity, summary}]` ＋ 当前 `rules_disabled` |
| `GET /v1/ui/shots?run=<id>` | 镜头数据（轨迹页） | 只读 `<runs-dir>/<run>/export/shots.json`（`export_dir = out_dir / "export"` 实证在 `export_director.py:173`，2026-10-10 复数；sidecar 加 `--runs-dir` 缺省 `<仓根>/runs`，run id 白名单 `^[A-Za-z0-9._-]+$`，越界 400） |
| `POST /v1/ui/script/polish` | Stage P（Web 触发，§9） | `{script}` → `{suggestions[], rewritten}`，**由 sidecar 直接调 `call_upstream`** |
| `POST /v1/ui/script/polish/accept` | 采纳改写稿 | `{run_id}` → 写回该 run polish 记录 `accepted=true` |
| `GET /v1/ui/target_models` | 目标模型规格表 | → `specs/target_models.yaml` 全量 ＋ 当前 `delivery.target_model`（§12.1） |
| `GET /` 、`/static/*` | 静态文件 | `web/` 白名单；`..` → 400；content-type：.html/.js/.css/.png/.json/.txt |

`contracts/rule_catalog.py`：规则元信息单一真源（id/severity/summary），
供 sidecar 与前端消费；`rule_checker.py` 不 import 它。
**对拍口径（v1.7.3 钉死）**：契约测试用正则 `R\d{3}` 静态扫描 `rule_checker.py`
全文得到的规则 id 集合 == catalog 的 id 集合（不依赖运行时产 finding，静态可判）。

全部新端点进 `specs/openapi.yaml` 同一 PR。

## 8. Blender 面板改动（最小化）

- `panel_main.py` 加一行："Web 界面"按钮（`webbrowser.open(...?token=…)`）＋ token 复制；
- 新 `panel_assistant.py`：精灵开关（绑 `ui.viewport_sprite`）、`driver.state` 只读显示；
- 现有 6 面板**不动布局**。

## 9. Stage P 剧本优化（**v1.7.3 钉死双通道执行者**）

```python
# contracts/script_polish.py —— schema/prompt 模板的单一真源
@dataclass
class PolishResult:
    suggestions: List[str]
    rewritten: str
    accepted: bool = False
```

- **两个触发通道，共用一个真源**：
  - run 内：`driver` 的 POLISHING 状态用插件自己的 transport 发起调用
    （strict schema：`{suggestions: string[], rewritten: string}`）；
  - Web 触发（`/v1/ui/script/polish`）：**由 sidecar 直接 `call_upstream`**
    ——polish 是纯文本→文本调用，无需 bpy；sidecar 本来就 owns provider specifics。
    **两边的 schema/prompt 模板都从 `contracts/script_polish.py` import**，
    不许出现第二份模板字符串；
- 状态机插入：UNDERSTANDING →（`script_polish.enabled` 且有 builder）→ POLISHING → PLANNING；
  `DriverState` 新增 `POLISHING = "POLISHING"`，映射表加 `"POLISHING": "read"`；
- 一次调用，失败一次即回落原剧本＋`E_POLISH_001`（**不重试**）；
- 采纳前 PLANNING 输入恒为原剧本；采纳经 `/v1/ui/script/polish/accept` 写回；
- 审计 `polish_result`；`project.bdproj` 存 PolishResult。

## 10. 轨迹几何增强（`overlay/geometry.py`，纯函数）

```python
def path_ticks(points: List[Vec3], interval_frames: int = 12) -> List[Vec3]:
    """沿折线按帧间隔取刻度点（匀速参数化）。"""

def colored_paths(paths: Dict[str, List[Vec3]], colors: Dict[str, str]) -> List[ColoredPolyline]:
    """按角色 color 字段分组着色；未知角色回落调色板循环。"""
```

- 配色真源是角色既有 `color` 字段（证据：`panel_cast.py`）；
- `draw_overlay.py` 只消费新几何函数；帧未变时用缓存，回调内不重算。

## 11. 测试清单（全部进 `python -m pytest`）

| # | 测试 | 对应验收 |
|---|---|---|
| T1 | 状态映射与 `DriverState` 对拍（卡 E1 后 15 态）＋未知态回落 sit | A-A-1 |
| T2 | 帧表校验器：缺文件/帧数 1/非法名各一条负例 | A-A-3 |
| T3 | 新配置键默认值往返幂等；CFG_170/171（卡 A2）与 CFG_172（卡 A5）分别触发 | A-U1-1 |
| T4 | key 掩码边界（空/7/8/20）＋ PUT secret 响应全文无明文 | A-U1-2 |
| T5 | 哨兵开关：关 R009 后 findings 无 R009、`skipped[]` 留痕、24 调用点零改动；空列表与 HEAD 逐字节对拍；**分流点在 `from_findings`** | A-U6-1/2 |
| T6 | UIEvent 往返；payload 禁 key/prompt 静态检查（`check_assertions.py` 加规则） | §2.1 |
| T7 | ui_bridge 断连静默：offline 链无异常且 `dropped_events>0` | R-UI-2 |
| T8 | Stage P：enabled=false golden 逐字节一致；未采纳输入原剧本；失败回落 E_POLISH_001；**双通道同 schema**（sidecar 与 driver 产出同构） | A-U3-1/2 |
| T9 | 端点契约：401/404/目录穿越 400；`/v1/ui/*` 全鉴权、静态免鉴权各一例 | §7 |
| T10 | path_ticks/colored_paths 纯函数（手算期望值） | A-U4-1 |
| T11 | 思考强度 16 格快照＋百炼降级留痕 | §4.2 |
| T12 | 静态服务：白名单与 content-type | §7 |
| T13 | state_map/rules/shots：state_map 与 `CLIP_BY_STATE` 一致；catalog 与 rule_checker 静态扫描集合对拍；shots 越界 400 | §7 |
| T14 | 规格表：三模型字段完整/区间合法/缺文件结构化 error | A-E3-2 |
| T15 | 导出沙箱：改设置＋抛异常，退出后 ≥9 项逐一还原；既有导出 golden 零漂移 | A-E2-1/2 |
| T16 | 运镜文字化器：推进/横移/环绕/多主体四夹具手算对拍；静止镜出"固定机位" | A-E1-2 |
| T17 | reference_pack：golden 工程文件清单＋模板字段对拍；模板 ≤5 句；`camera_narration` 进 shots.json | A-E1-1/3 |
| T18 | 切片建议：45 s 单镜对 seedance_2.5 → 恰好 1 条超限 warning＋切点在镜界；规格不一致只告警 | A-E3-1/3 |
| T19 | R020–R023：构造夹具各命中一次；三份冻结工程误报计数落证据目录（不判红） | A-V1/V2 |
| T20 | 分工声明：v1.4 SDL 迁移补 null 零 error；skip 镜无白模主体；未声明镜零行为差；R024 恰好 1 条 | A-S1 |
| T21 | R025：文字/实测矛盾样本 → 恰好 1 条；`enabled=false` 零行为差 | A-V3 |

`tools/run_tests.ps1` 探针清单按实测新增（v1.7 预期 +2：I1 的 `test_export_sandbox.py`
与 D3 的 `test_assistant_sprite.py`，均为 Blender 探针；纯 stdlib 的
`check_assistant_assets.py` 走 pytest 包装不占名额），链规模对拍按实测数同步。

## 12. 交付线：目标模型与导出包（R-痛点 M1/M2）

### 12.1 规格表 `specs/target_models.yaml`（数据文件，不许硬编码进 py）

```yaml
# 数字来源：R-痛点 §2 P7（每条注 src；无来源的数字不许进表）
seedance_2.5:
  label: "Seedance 2.5"
  max_segment_s: 30          # src: R-痛点 P7
  max_video_refs: 10         # src: R-痛点 P7
  max_ref_total_s: 30        # src: R-痛点 P7
  ref_recommend_s: [5, 10]   # src: R-痛点 P7
  aspect_range: [0.4, 2.5]   # src: R-痛点 P7
kling:
  label: "Kling"
  segment_choices_s: [5, 10] # src: R-痛点 P7
  extend_total_cap_s: 180    # src: R-痛点 P7
  degrade_after_s: 30        # src: R-痛点 P7（质量退化注记）
hailuo_h3:
  label: "Hailuo H3"
  segment_range_s: [4, 15]   # src: R-痛点 P7
  max_ref_files: {image: 9, video: 3, audio: 3}  # src: R-痛点 P7
```

`contracts/target_models.py`：`load_table(path=None) -> Dict[str, ModelSpec]`；
缺文件/缺键/区间非法 → 抛结构化 `TargetModelError`（不静默回落）；
YAML 解析复用 `contracts/config.py::parse_yaml`（§7 同一纪律）。

### 12.2 导出包布局与生成（FR-E1）

```
<export_dir>/reference_pack/
  README.md                 # 包用法
  prompt_<target>.txt       # 分工提示词：specs/prompt_templates/<target>.txt 渲染
  shot_cards.md             # 逐镜镜头卡：含 camera_narration（§13.2）
  continuity.json           # {shot_id: {left:[], right:[], facing:{}, note}}
  responsibility.md         # 分工声明汇总（§14，未声明镜标"未声明"）
```

- 模板引擎 = stdlib `string.Template`；模板 ≤5 句正向指令（R-痛点 P1）；
- **continuity 数据源（v1.7.5 复数行号）**：`_pair_screen_order`（rule_checker.py:116）
  是 **bpy 绑定的私有函数**（内部用 `bpy.context.scene` + `world_to_camera_view`，
  且只算当前帧）——不许跨层 import 私有函数。钉死：在 `rule_checker.py` 新增
  **公开包装** `continuity_snapshot(shot_id, context) -> Dict`，内部 frame_set 到
  该镜首帧、调 `_pair_screen_order`、还原帧（复用 `finish()`（:633 闭包）的还原模式）；
  `package.py` 只调这个公开函数；
- **`camera_narration` 的调用点（v1.7.3 钉死）**：`export_director.py` 组装
  `shots.json` 时逐镜调用 `camera_narration.narrate()` 写入新键（导出时场景仍在内存，
  证据：AGENTS.md"run_headless --export 场景仍在内存时导出"）；`package.py` 的
  镜头卡从 `shots.json` 读，不重复计算；
- `shots.json` 只增不改（P15 对拍测试同步更新）。

### 12.3 适配器 `layer8_delivery/target_advisor.py`（纯函数）

**v1.7.4 修正**：`cinema/schedule.py` 实读只有函数（`shot_ranges(plan)` :16、
`total_frames(plan)` :27），**没有 `Schedule`/`ShotSpan` 类**——签名一律用
`contracts/plan.py::Plan` 与既有函数的真实返回类型，不许新造类型：

```python
def check_specs(config: AppConfig, plan: Plan) -> List[Issue]:
    """帧率/宽高比与目标规格不一致 → warning。只告警，不改任何设置。
    帧数口径用 cinema/schedule.py::shot_ranges(plan) 与 total_frames(plan)。"""

def suggest_slices(plan: Plan, target: ModelSpec) -> List[SliceAdvice]:
    """总时长超 max_segment_s → 建议切点：优先镜头切换处（shot_ranges 的边界），
    其次运镜静止段（复用 §13.2 的 MOVE_EPS）。只建议不执行。"""
```

结果写审计 `target_advice` 事件；切片建议在导出 README 与 Web 状态卡各展示一次。

## 13. 交付线：导出沙箱与新规则（R-痛点 M3/M4）

### 13.1 导出沙箱 `layer8_delivery/export_sandbox.py`（FR-E2）

```python
@contextmanager
def export_sandbox(scene, *, camera, fps: int):
    """备份 → 锁定 → 还原。finally 逐项还原，异常不吞。"""
```

备份清单（≥9 项，对照 R-痛点 P11）：`filepath` / `image_settings.file_format` /
`ffmpeg.format` / `ffmpeg.codec` / `ffmpeg.constant_rate_factor` /
`resolution_percentage` / `frame_rate` / `image_settings.color_depth` /
`image_settings.color_mode`（alpha）。**相机语义（v1.7.6 收窄）**：`scene.camera`
列备份清单第 10 项，进入时设首帧基准相机、退出还原；**不拦截**导出中途的相机
切换（实读：renderer/export_director 均无 `scene.camera` 赋值，逐镜切换靠
cut markers）。帧率 = fps。
守门：`tools/check_assertions.py` 新增静态规则——`layer5_orchestrator/` 与
`contracts/` 下出现 `scene.render.` 直写即失败。

### 13.2 运镜文字化器 `cinema/camera_narration.py`（纯函数，无 bpy）

```python
def narrate(camera_samples: List[Vec3], subject_anchor: Vec3,
            subject_facing: float) -> str:
    """"从主体的左前方推进到正前方"式描述；总位移 < MOVE_EPS → "固定机位"
    （但 |首末 lens 差| ≥ LENS_EPS=2.0mm → "变焦"句式，判定先于静止）。"""
```

- **多主体钉死**：调用方传 `subject_anchor` = 该镜全部主体的**首帧位置质心**
  （质心计算在调用方，本函数只吃一个锚点，不做主体选择）；
- **方位钉死**：相对锚点＋朝向的**八方位**（前/前左/左/后左/后/后右/右/前右），
  距离带（近/远）独立输出；方位角阈值与 `MOVE_EPS` 为模块常量（非用户调节项）；
- **相机采样数据源（实证）**：`cinema/camera_motion.py::movement_samples`
  （2026-10-10 复数在 :299；旧写 :282 是 `movement_curve`——已漂移。返回
  `[{frame, position, look_at, lens}]`，:308 注释实证）即每镜相机位置采样的
  既有产物，直接复用其结果，不重新采样；
- 运动动词表对齐 `contracts/enums.py::MOVEMENT_TYPES`（import，不抄）。

### 13.3 新规则 R020–R025（全部 warning 级，红线 R-V）

| 规则 | 检测（**v1.7.3 操作化定义，无歧义**） | 数据源/阈值 | 证据 |
|---|---|---|---|
| R020 | 同一角色 id 跨镜包围盒世界高度：与**首出场镜基线**比对，相对差 > `guard.scale_drift` → 每角色每镜至多 1 条告警（rule_checker 无场级入口，实读只有 `check_shot` :607，操作化见《改进计划》J1）。**收窄说明**："角色 vs 门/桌等参照物"无尺寸真源（仓内无标定尺寸库），**不做**，列入移交事项 | `_character_aabb`（:496，2026-10-10 复数） | R-痛点 P5 |
| R021 | 单镜内：相机相邻采样段**航向角差 > 30°**（模块常量，对齐 R010 的 30° 词汇）记 1 次方向突变；突变数 + 该镜主体运动条目数（plan 的 movement 列表实读）≥ `guard.compound_motion_max` → "建议拆镜头" | camera_motion 采样＋plan | P4 |
| R022 | 相机 up 向量逐帧符号序列出现翻转 → 告警 | 逐帧 up | P10 |
| R023 | 相机加速度（采样位置二阶差分 × fps²，**单位 m/s²**）> `guard.cam_accel_max` → 告警 | 数值微分 | P10 |
| R024 | 声明 vs 实测：①声明 `skip_white_model` 但场景建了该镜白模主体；②声明移交 prompt 的角色出现**白名单外动画通道**——白名单 = root 的 `location`/`rotation_euler`＋契约允许的 `body_tilt` 键表；其余 data_path（含形态键/pose 骨骼通道）即命中 | `shot.responsibility`（§14）＋动画通道实读 | P6/P16 |
| R025 | 提示词文本 vs 实测方位矛盾（校验层只产实测方位；文本判断归 LLM 裁决层，接入点 = driver 的 REVIEWING 阶段（Purpose.REVIEW 调用处）；**默认关**） | §13.2 输出 | P14 |

六条全部进 `contracts/rule_catalog.py`（静态扫描对拍强制同步）；
可被 `rules_disabled` 关闭；阈值键注释"待实测校准"。

## 14. 分工声明契约（R-痛点 M5）

### 14.1 plan schema 扩展

```python
@dataclass
class Responsibility:
    white_model: List[str] = field(default_factory=list)  # 白模管：位置/机位/节奏…
    prompt: List[str] = field(default_factory=list)       # 移交提示词：动作细节/表情…
    ref_image: List[str] = field(default_factory=list)    # 移交参考图：外观/风格…
    skip_white_model: bool = False                        # 本镜跳过白模（P16）
```

- `shot.responsibility: Optional[Responsibility] = None`；**None = 未声明**
  （≠ 全空），未声明镜全链零行为差；
- **SDL 升 1.7**（v1.7.5 修正：`contracts/sdl.py:25` 实测 `SDL_VERSION="1.6"`、
  `sdl_migrate.py:22` 的 `KNOWN_VERSIONS` 已含 `"1.5"`——1.5/1.6 均被占用）：
  `KNOWN_VERSIONS` 追加 `"1.7"`，迁移 = 旧文件每镜补 `responsibility: null`
  （照 1.2→…→1.6 既有迁移模式；坏数据只报 finding）；
- `skip_white_model=true` 的执行语义：`scene_executor` 跳过该镜白模主体构建、
  `shots.json` 标 `skip_white_model: true`、reference_pack 给"直出提示词＋参考图"指引；
- Stage P 建议清单模板加"分工建议"维度——建议只是建议，采纳权在人工门（§9）。
