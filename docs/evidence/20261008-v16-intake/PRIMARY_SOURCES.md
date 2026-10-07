# v1.6 主源核验：API、原理与适用边界

日期：2026-10-08（本机 `Get-Date`：2026-10-08 04:48:09 +08:00）。

唯一角色：原理与官方资料核验。

范围：只读项目与主源、写本文；没有修改实现、没有运行 Blender、没有引入依赖、没有复制上游实现。

## 结论

1. **A7 的修复路线有依据，但“采样点合格”不能推出“成片全帧合格”。** 官方插值 API 没有多对象防碰撞承诺；动态标签原论文将不交叠和时间连贯性分开讨论，并明确某些配置没有连续可行解。A7 必须以实际字形投影的全帧复验闭环，不能以固定迭代次数、自动手柄或“加密过了”代替验收。[S1–S5、S10；本地 L1–L4]
2. **投影不等于可见性证明。** `world_to_camera_view` 给出点的 NDC 与视轴深度；它不替调用者求值对象、不判断遮挡、不证明九点射线代表全部像素。相机与被测对象均需与当前帧一致；部分跨近裁切面的盒与完全在相机后方的盒不能混为一谈。[S1–S3、S6；工程推论]
3. **节奏词必须落到实测时间轮廓。** `BEZIER` 是插值种类，不是 `slow_start`/`slow_end` 的同义词。曲线落地应测位移比例、端点、连续性，而不能只检查枚举字符串。[S4–S5；TDD §4.4]
4. **逐对象发光材质路线可行，但颜色与恢复都要补足契约。** 共享网格的 DATA 材质槽可能同时影响多个对象；sRGB 色表与线性发光值有转换关系；世界、材质槽 link、色彩设置、帧与相机均应纳入恢复测试。现有深度 pass 是参考，不是“复制其 try/finally 即可完备”的证明。[S7–S9、S13、S15；本地 L5]
5. **F2 不是给内存检查点加一个开关。** 现有管理器没有磁盘提交协议；原子替换一个 JSON 也不等于场景文件、状态和交付物的整体事务。需要明确同代快照、终态、交付提交点和崩溃窗口，并以杀进程测试证明跳过已完成镜。[S14–S16；本地 L6；工程推论]
6. **RGB 元素 ID/layout 视频不是 VACE 的二值编辑 mask。** 两者都可作为交付控制信息，但不能宣称同一个文件可以不经适配直接替代两类输入。VACE 原论文初版是 2025-03-10，非规格所写的 2025-08。[S11–S12]

本文只提出验证与实现约束，不修改任何验收阈值；不把未验证项记成通过。

## 全量盘点与来源方式

本轮完整阅读：

- `CONTEXT.md`
- `docs/v1.6/PRD_v1.6.md`
- `docs/v1.6/技术方案_v1.6.md`
- `docs/v1.6/TDD_v1.6.md`
- `docs/v1.6/改进计划_v1.6_deepseek.md`

先固定六组技术主题，再统一核验主源：标签全帧投影/自适应采样与二维松弛；视锥/可见性；轴线连续性；节奏插值；遮罩颜色管理与状态恢复；断点续跑。没有把二手调研报告中的结论直接升级为主源事实。

`web.run` 的搜索和打开调用没有返回可用正文/可引用条目。直接 HTTP 访问 Blender 文档域得到 Cloudflare 的 “Just a moment” 挑战页，因此改为读取 **Blender 官方 GitHub 源码与 API 示例**，并读取作者存档论文、arXiv 原文、Python/W3C 官方文档；这只是访问路径变化，来源标准未降低。前期一次协作消息误提 HTTP 402，已立即更正；**402 不在本报告证据内**。

Blender 主源以 `v5.0.0` 标签固定；另对读取当时 main 的提交
`ea0e364e908ba344a9102ba1b8027ac3d4cbdaa8` 核对 `world_to_camera_view`，核心行为一致。
GitHub API 给出的该提交时间为 `2026-10-07T20:48:49Z`。**这不是本机 Blender 版本识别结果**；运行时版本、构建哈希与能力须由主线环境探针确认。

### 本地核验命令与证据定位

下列行号是本报告审查时的工作树快照；并行开发可能使行号后移。

| ID | 证据位置 | 实际读数 |
|---|---|---|
| L1 | `block_director/layer3_engine/label_baking.py:109` | `_glyph_half_extents` 用字号、字符数与 0.95 宽度系数估算字框 |
| L2 | `tools/blender_tests/test_label_layout.py:122` | `_screen_box` 投影对象自己的 `bound_box`；与 L1 不是同一几何量 |
| L3 | `block_director/layer3_engine/label_baking.py:162`、`:176`、`:183` | `separate_labels` 只向上推；每轮先建立 boxes，再逐对改位置，后续配对仍消费该轮旧盒 |
| L4 | `tools/blender_tests/test_label_layout.py:405`、`label_baking.py:433` | 原 RK-2 探针每镜检查五帧；写关键帧函数本身没有显式指定插值/手柄 |
| L5 | `block_director/layer8_delivery/depth_pass.py:108`、`:121`、`:131` | 快照后先改材质/世界/图像设置，随后才进入 `try`；快照没有色彩管理与当前帧 |
| L6 | `block_director/layer3_engine/checkpoint_manager.py:171` | `CheckpointManager` 是命名检查点**内存栈**；没有磁盘序列化/原子提交入口 |
| L7 | `block_director/layer3_engine/checkpoint_manager.py:65`、`:105` | 曲线快照包含帧、值、interpolation；恢复键时未逐键设置记录的 value，也未记录手柄/相机 data 动画 |

复核命令：

```powershell
rg -n 'def _glyph_half_extents|def separate_labels|boxes =|def _screen_box|def _write|def t_rk2_overlap' block_director/layer3_engine/label_baking.py tools/blender_tests/test_label_layout.py
rg -n 'previous =|view_layer.material_override|try:|finally:|frame_current|view_transform' block_director/layer8_delivery/depth_pass.py
Get-Content -LiteralPath block_director/layer3_engine/checkpoint_manager.py -Raw
```

L7 是 F2 的需复验风险，不在本文内修复，也不据此宣称所有现有回滚路径已经失败。

## 1. A7：全帧标签与自适应松弛

| 主源结论 / 工程推论 | 落地意义 | 依据 |
|---|---|---|
| NDC 左下为 `(0,0)`，右上为 `(1,1)`；可超出区间；返回 z 是沿视轴的深度，不是欧氏距离 | 使用既有投影函数，不再用简化视场角公式替代离轴实际像素测量 | S1 |
| 函数直接读取传入相机的 `matrix_world`/camera data；不自行 `evaluated_get` | 切帧后取得同一 depsgraph 下的相机、标签与锚点状态；不能只求值角色而保留旧相机 | S1–S3 |
| `bound_box` 是局部盒，需要世界变换后投影；字体 em 大小不等于可见字形的实际盒 | L1 与 L2 的口径差应单独统计；先证明修复前重叠发生在哪些帧，不把所有红归因于插值 | S2、S7；L1–L2 |
| interpolation 管当前键至下一键区间；AUTO_CLAMPED 约束单条曲线的转向 | 没有“两个物体的投影盒不碰撞”的保证；甚至世界坐标分量均无超调也不能推出运动相机下的投影不重叠 | S4–S5；后一半是工程推论 |
| 原论文把盒不相交作为硬约束，锚点距离、场景遮挡、时间连贯性作为目标；贪心布局不是普遍最优解 | 二维推开可参考其约束分离原则；不应承诺 `SEPARATE_ITERATIONS=16` 必然收敛 | S10 §3–4；L3 |
| 原论文展示某些场景没有连续标签轨迹，插值只是让跳变不突兀 | 固定字号、锚点跟随、最大位移同时约束时可能不可行；必须记录不可行帧，不准隐藏标签、缩字号或改阈值消红 | S10 时间连贯性讨论；项目既有约束 |

自审后的建议顺序（工程建议，不是移植算法）：

1. 用测试侧已有 `_screen_box/_overlap` 对每个输出整数帧建立外生基线，分别列出原采样帧和插值帧；相机按该镜与当前帧选择。
2. 以实际字形局部盒建立求解量，并保持描边与填充的几何/尺度约束；全帧验收仍用测试侧独立投影，不能读求解器自己报告的“已无重叠”。
3. 标签按稳定 ID 排序；每次移动后重算相关盒，二维选择最小可行修正；同时维持锚点距离上限、字号区间、画框边界。
4. 用相对屏幕速度或实测违规定位待加密区间；加密到整数帧是性能策略，不是新的通过标准。
5. 完成关键帧写入后重新逐帧求值和测量；输出每帧最坏交叠、超阈帧、相关标签对。若加密或布局仍不可解，明确失败，不能把迭代终止当成功。
6. 增反例：两个端点均不交叠而中间相交；移动/变焦相机；多人同侧拥挤；长中文与混排标签；镜头切点；约束导致的移动；确定性重跑。

**保证边界**：整数全帧验收只证明视频被采样的整数时刻。若成片启用运动模糊、快门内子帧积分或额外时域处理，还需按渲染条件复验；本文没有测试这些条件，不扩大声称。

## 2. 视锥、裁切与可见性

| 核验结论 | 对 B2/B3/B4 的要求 | 依据 |
|---|---|---|
| `frame_set` 立即更新所有对象与 view layers；求值示例要求用 evaluated ID 获取动画/约束/修改器后的状态 | 采样应保存并在异常路径恢复当前帧/相机；不能改变用户工作现场 | S2–S3；恢复要求为工程推论 |
| 投影函数的透视路径在 z=0 特判，并不裁切跨相机平面的包围盒 | 区分“所有角点后方”“部分角点后方”“近裁切面穿越”；混合深度盒不能直接 min/max 当可信完整包围盒 | S1；工程推论 |
| `Scene.ray_cast` 在求值几何的**世界空间**工作；`Object.ray_cast` 的坐标契约不同 | 相机位置、射线方向、目标距离必须同世界系；命中物体需按角色所有几何的归属判断 | S3、S6 |
| scene 射线接口把命中对象转换为 original ID 返回 | 不应仅因返回对象不是 evaluated wrapper 就认成“另一个遮挡物” | S3 源码 |
| 九个包围盒表面点不是人体实际像素的均匀采样；角点还可能在空处 | `visible_ratio` 应注明“射线采样比例”；九点全未见不构成严格的全表面/全像素不可见证明 | S3 的点射线能力边界；数学推论 |
| 包围盒可能比实际轮廓大 | 裁切率是保守盒度量；不得称为精确像素裁切率，需遵守 PRD 的 confidence 区分 | S7 + PRD 风险表；工程推论 |

需要在落地前明确的规格歧义：TDD 规定“九点全零 → `subject_not_visible` error/high”，但没有为其提供完整遮挡证明。建议保留原阈值，增加真实主体采样/遮挡反例与证据口径，提交主线裁定；**本文不擅自改成 warning、不跳过该判据**。

100 帧 `<5 s` 是项目验收目标，不是 Blender 官方性能保证。必须记录场景规模、硬件、Blender 构建、采样帧数以及实耗；不得从 API 文档推断已经满足。

## 3. 轴线连续性与跳切

原论文 *The Virtual Cinematographer: A Paradigm for Automatic Real-Time Camera Control and Directing* 的作者是 **Li-wei He、Michael F. Cohen、David H. Salesin**，并非本地二手调研段落归给的 Christianson 等人。该文 §2.2 明确“不跨兴趣线”、跨切换需在主体大小/视角/数量上有明显变化；以分层有限状态机编码电影习语。[S17，作者稿 PDF 第 2–4 页]

工程边界（推论，S17 不提供以下实现的正确性证明）：

- `left_to_right` 应按稳定角色身份比较同一叙事关系对；前后镜可见角色集合不同，不能用 tuple 不相等直接报越轴，也不能因缺对象就清掉记忆。
- 单人反打可能没有同屏角色对，朝向符号可作证据，但不等价于完整的世界轴线判定。
- 两个角色发生走位互换，与相机跨轴可能产生同样屏幕次序结果，需有事件/桥接上下文。
- `abs(facing_projection)<0.1` 与 30°/10% 是本项目设计值；本轮原论文没有为这些精确数值提供普适阈值证明，不把“有论文”写成“阈值经论文证实”。
- “中性镜”要对应被跟踪的关系对和明确桥接帧；一个无关人物正对镜头不应自动解锁全片其他人物的换侧。
- 第一次可比较镜头、暂时出画、遮挡、组内新增角色、镜内连续换侧、单镜头末帧到次镜首帧均需反例测试。

本轮只核验连续性原则，不修改 R001/E_AXIS_001 语义或 error 级别。

## 4. 节奏与插值

| 命题 | 核验结果 | 依据 |
|---|---|---|
| `LINEAR`/`BEZIER` 是可用插值类型，作用于当前键至下一键区间 | 已核 | S4–S5 |
| 设置 `BEZIER` 就能保证 `ease_in`/`ease_out` 数值判据 | **不成立**；还取决于手柄、采样键与时间分布 | S4–S5；工程推论 |
| 改写关键帧插值后纯轨迹求解函数可以不改 | 架构上可行，但位置/看向/焦距及跟随路径的时间采样必须同步；不能仅给位置改变节奏而焦距还线性推进 | TDD §4.4 + S4；工程推论 |
| ASL 2–4 / 4–8 / 8–12 秒是通用科学阈值 | **未证实**；规格来源主要为二手资料，本轮没有获得支持这些精确带宽的原始统计研究 | 规格来源盘点 |

规格内部的命名风险：PRD FR-B3 文字写 “ease_out 起步 / ease_in 落地”，而 TDD §4.4 明确 `ease_in=slow_start`、`ease_out=slow_end`。任务卡钉死 TDD，执行时需按 TDD 做数值测试，并把文案冲突留痕；不能因英文通常含义不同而暗改表。

验证应直接测 `Δposition/Δframe` 与累计位移：起始 20%、末尾 20%、突发前 15%；校验短镜头取整、零位移、反向路径、所有 24 运镜 × 5 曲线及 lens/look-at 同步。节奏读数仍为 info，不转为创作通过门。

## 5. 遮罩、颜色与状态恢复

### 5.1 能做什么

- View-layer `material_override` 的确是全层材质覆盖。简单给它一份固定颜色材质不能得到逐元素颜色；逐对象槽方案符合本项目已选路线。[S8]
- 但“全层只能一份材质”不等于“任何共享材质都不可能区分对象”：后者是过强推论，可能使用对象输入。本轮不改选型，仍按 E2 明确的逐对象槽实现。[S8；逻辑边界]
- `MaterialSlot.link` 区分 OBJECT 与 DATA；DATA 槽共享时，对一个对象的材质编辑可能改变其他实例的外观。快照应记录槽数量、每槽 link 与 material、必要的数据关联，不能只记录一份 materials 列表。[S7；工程推论]

### 5.2 颜色即 ID 的前提

Blender 官方 OCIO 配置把 scene-linear 设为 Linear Rec.709，把字节图像默认空间设为 sRGB；Standard 视图与 sRGB 显示空间组合，Raw 使用 Non-Color。W3C 列出了 sRGB 编码与线性光值的互逆转换。[S9、S13]

因此要先明确 `elements.json.color_hex` 的语义（建议明确为 sRGB 编码字节），再将其转换到材质输入所需的线性值，控制输出变换。不能把十六进制 `#808080` 的 `128/255` 直接视为在所有视图变换下都输出同一灰阶的发光值。[S9、S13；工程推论]

需要锁定并在 finally 恢复：view transform、look、exposure、gamma、dither、颜色管理输出覆盖、引擎、透明背景、世界、相机、帧范围/当前帧、图像格式/位深/路径、逐槽材质和 link、辅助件可见性。这里只列风险面，运行时支持哪些属性必须在目标 Blender 构建里确认，禁止猜属性或 `try/except: pass`。[S7–S9、S15；工程建议]

纯色主体内部像素与抗锯齿轮廓应分开测：轮廓混色不能当作新的元素 ID，也不能要求所有边缘像素等于色表后偷偷增容差。需固定既有验收对颜色的口径并记录编码/边缘语义；**本文没有运行像素实验，也没有宣布颜色已经对拍**。

### 5.3 恢复与失败

Python `ExitStack` 官方说明注册清理回调以逆序执行，适合分阶段取得资源；`try/finally` 同样可实现恢复。[S15]

本地深度 pass 的首次临时赋值在 `try` 外，且未保存全部 E2 将修改的字段（L5）。E2 不应机械照抄而继承这些空窗。建议从第一项场景变更之前建立恢复保护，逐个注入“材质创建失败/设置失败/第 N 帧渲染失败”，比对完整快照并让原异常继续可见。清理失败也应留证，不能吞掉。

“Blender 5.x File Output 只能多层 EXR”不能从本轮源码审查推出普遍结论：v5.0.0 和检查时 main 的节点初始化使用 multi-layer 类型，但源码亦包含 individual file output 分支。项目已选 E2 路线不变；如要引用该限制，应限定到项目**实际测试过的构建与设置**，不能外推整个 5.x。[S18；未验证运行时枚举]

### 5.4 VACE 输入边界

原论文 §3.1 的 V2V 控制可表示为 RGB 视频，列出 depth/grayscale/pose/scribble/optical-flow/layout；§3.2 的编辑 mask 是二值，标识哪里编辑且与帧序列时空对齐。[S11]

交付中应清楚写：

- 元素纯色序列：稳定 ID/layout 控制信息。
- 某元素二值 mask：可由 ID 色表转换得到，供要求 binary editing mask 的接口使用。
- 角色参考图：身份参考输入。

**本轮不增加转换功能或下游依赖。** “下游可直接接受何种文件编码/调色板”仍需实际目标工作流对接验证，不能由 VACE 概念图替代。

## 6. 断点续跑与持久化

Python 官方 `os.replace` 说明覆盖目标与跨文件系统失败边界，并说明成功替换的原子语义；`fsync` 说明先 flush Python 缓冲再同步文件，Windows 对应 `_commit`。[S14] 这些原语不提供跨多个文件的一体提交，也不代表在任意断电时刻已达成磁盘/远端服务的事务一致性。[S14；能力边界推论]

建议 F2 的测试与状态契约覆盖：

1. **运行代际**：计划/剧本/配置/契约版本指纹、run_id、完成镜与当前阶段，避免把异代产物误作本代已完成。
2. **同盘提交**：临时文件与最终目标放同一目标目录/文件系统；写完整、flush、fsync，再 replace；失败保留上一份有效状态并报告。
3. **整体一致性**：场景或可重建 SDL、驱动状态、交付物哈希/帧数必须相互绑定；只有全部必需部分就绪后才能记录镜头终态。
4. **不重渲染**：resume 前验证既有交付物存在、字节完整、帧数正确；不能只看 `done=true` 或文件名。校验失败应报错，不静默重渲染用户已完成镜。
5. **调用边界**：已提交终态镜不得再发 LLM 请求。进程可能在收到远端回答而本地提交之前被杀，这属于“未提交镜”的崩溃窗口；没有远端幂等协议时，不能把本地文件原子写入宣称为全网络 exactly-once。
6. **故障注入**：B1 成功前后、审核终态写入前后、交付完成但 manifest 未提交、state 提交中、非法 JSON、缺失快照、异代配置、历史版本迁移。
7. **曲线完备**：先验证 L7 的关键帧值、手柄、相机 data.lens、可见性等能往返；F2 的继续执行不能依赖没有覆盖完整状态的快照。

这些是原子文件原理映射到本项目的工程建议，不是 Python 文档对 BlockDirector resume 的证明。只有主线 F2 的合成杀进程与实际产物检查通过才能关闭此项。

## 7. GitHub 复用候选四档

评级只回答本项目如何利用来源，不构成引入依赖授权。本轮四档都**没有复制代码或安装依赖**。

| 档 | 候选 | 主源/许可证据 | 判断 |
|---|---|---|---|
| A：直接调用既有 API | Blender `world_to_camera_view`、depsgraph、ray_cast、材质槽 API | 官方 `blender/blender`；S1–S8 | 项目已运行在 Blender；调用公开 API，不复制其实现，不自造投影矩阵 |
| B：仅原则/算法参考 | `Phlya/adjustText` | README 是 Matplotlib 标签迭代布局；LICENSE 为 MIT，S19 | 可参考排斥/回拉与布局结束后重测原则；静态图布局不证明动态全帧约束，不引 Matplotlib/SciPy 栈 |
| B：仅原则/算法参考 | `ckjellson/textalloc` | README 的候选位置/避免相交、距离约束；LICENSE 为 MIT，S20 | 可参考候选成本与边界检查；其可只显示无冲突子集的功能不符合本项目“不得隐藏标签”的要求 |
| C：领域相关但不作为本轮实现依赖 | `ali-vilab/VACE` | 官方 README、LICENSE.txt 为 Apache-2.0，S12；模型许可另列 | 用于核验下游信号语义；本项目是 Blender 交付端，不引视频模型推理依赖 |
| D：不复制/复用资格未证实 | Blender 源码函数直接移植、论文中未取得明确许可的实现 | `object_utils.py` SPDX 为 GPL-2.0-or-later；论文公开可读不等于其软件可移植，S1、S10 | 本轮**仅原则参考，不引入 GPL 代码**；没有许可/适配/授权证据的上游实现不进入生产目录 |

MIT/Apache 的名称来自各上游许可证文件实读；没有据此作兼容性法律结论。后续真引入仍需固定提交、归属信息、许可证与依赖审查，本轮不做。

## 8. 主源登记

全部访问日期均为 **2026-10-08（Asia/Shanghai）**。以下 URL 是可复核来源标识；除注明外，直接 HTTP 返回 200 且已读取相关正文。Blender 标签源稳定，`master/main` 型候选仓库的结果只代表访问时状态。

| ID | 来源 / 已核范围 | 来源标识 |
|---|---|---|
| S1 | Blender 官方投影 API 实现与内嵌文档；另核 main 快照 | `https://raw.githubusercontent.com/blender/blender/v5.0.0/scripts/modules/bpy_extras/object_utils.py`；`https://raw.githubusercontent.com/blender/blender/ea0e364e908ba344a9102ba1b8027ac3d4cbdaa8/scripts/modules/bpy_extras/object_utils.py` |
| S2 | Blender 官方 evaluated ID API 示例，动画/约束/修改器求值 | `https://raw.githubusercontent.com/blender/blender/v5.0.0/doc/python_api/examples/bpy.types.Depsgraph.1.py` |
| S3 | Blender 官方 scene API 的 frame_set/ray_cast，含返回 original 对象 | `https://raw.githubusercontent.com/blender/blender/v5.0.0/source/blender/makesrna/intern/rna_scene_api.cc` |
| S4 | Blender 官方 Keyframe interpolation/easing 属性定义 | `https://raw.githubusercontent.com/blender/blender/v5.0.0/source/blender/makesrna/intern/rna_fcurve.cc` |
| S5 | Blender 官方插值/手柄枚举，AUTO_CLAMPED 的语义 | `https://raw.githubusercontent.com/blender/blender/v5.0.0/source/blender/makesrna/intern/rna_curve.cc` |
| S6 | Blender 官方 Object.ray_cast 与 Scene.ray_cast 空间契约对照 | `https://raw.githubusercontent.com/blender/blender/v5.0.0/source/blender/makesrna/intern/rna_object_api.cc` |
| S7 | Blender 官方 bound_box/material_slots/MaterialSlot.link 定义 | `https://raw.githubusercontent.com/blender/blender/v5.0.0/source/blender/makesrna/intern/rna_object.cc` |
| S8 | Blender 官方 ViewLayer material_override 定义 | `https://raw.githubusercontent.com/blender/blender/v5.0.0/source/blender/makesrna/intern/rna_scene.cc` |
| S9 | Blender 官方 OCIO 配置，scene_linear/default_byte/Standard/Raw | `https://raw.githubusercontent.com/blender/blender/v5.0.0/release/datafiles/colormanagement/config.ocio` |
| S10 | Stein & Décoret，2008，Dynamic Label Placement for Improved Interactive Exploration，作者 HAL 稿；全文 7 页读取，§3–4 重点核验 | `https://inria.hal.science/inria-00269370/document`；DOI `10.1145/1377980.1377986` |
| S11 | Jiang 等，VACE，arXiv v2 原文 §3.1/3.2 与提交历史 | `https://arxiv.org/html/2503.07598v2`；`https://arxiv.org/abs/2503.07598` |
| S12 | VACE 官方 README/源码许可证；模型许可须另看对应模型文件 | `https://raw.githubusercontent.com/ali-vilab/VACE/main/README.md`；`https://raw.githubusercontent.com/ali-vilab/VACE/main/LICENSE.txt` |
| S13 | W3C CSS Color 4，sRGB/linear-light 转换定义与示例 | `https://www.w3.org/TR/css-color-4/` |
| S14 | Python 官方 os.replace/os.fsync 文档，跨文件系统与缓冲边界 | `https://docs.python.org/3/library/os.html#os.replace`；`https://docs.python.org/3/library/os.html#os.fsync` |
| S15 | Python 官方 contextlib.ExitStack，逆序清理与异常路径 | `https://docs.python.org/3/library/contextlib.html#contextlib.ExitStack` |
| S16 | 本地 checkpoint_manager 完整源码；只作为项目事实，不作为外部算法权威 | `block_director/layer3_engine/checkpoint_manager.py` |
| S17 | He/Cohen/Salesin，1996，Virtual Cinematographer，作者上传稿的 Inria 存档；全文文本抽取，§2–3 重点读取 | `https://team.inria.fr/imagine/files/2019/11/The_Virtual_Cinematographer_A_Paradigm_for_Automat.pdf`；DOI `10.1145/237170.237259` |
| S18 | Blender 官方 File Output 节点初始化与多层/独立输出分支 | `https://raw.githubusercontent.com/blender/blender/v5.0.0/source/blender/nodes/composite/nodes/node_composite_file_output.cc`；main 固定提交同路径 |
| S19 | adjustText 官方 README 与 MIT LICENSE | `https://raw.githubusercontent.com/Phlya/adjustText/master/README.md`；`https://raw.githubusercontent.com/Phlya/adjustText/master/LICENSE` |
| S20 | textalloc 官方 README 与 MIT LICENSE | `https://raw.githubusercontent.com/ckjellson/textalloc/main/README.md`；`https://raw.githubusercontent.com/ckjellson/textalloc/main/LICENSE` |

辅助主源：Blender `node_shader_emission.cc`（发光节点 Color/Strength 定义）、`animrig/intern/keyframing.cc`（关键帧设置入口会读取用户偏好）、`blenkernel/intern/camera.cc`（view frame 计算考虑 render resolution、pixel aspect、sensor fit）；这三项均在官方 v5.0.0 路径下 HTTP 200。没有复制其实现。

未作为结论依据的资料：Crossref 中 Kevin Mote 动态地图标签论文元数据仅用于盘点；未以其摘要宣称本项目运行复杂度。`docs.blender.org` 挑战页、若干请求超时、VACE 错误许可证路径 `/LICENSE` 的 404 均不作为内容证据；正确路径 `/LICENSE.txt` 已重新取得 200。

## 9. 尚未验证与交接

本报告是资料核验完成，不是 v1.6 开发完成，也不是功能验收通过。

- 未运行 Blender：A7 修复前全帧红分布、真实 glyph bbox、动态相机/约束采样行为、二维可行性、性能预算、像素颜色和异常恢复需主线探针。
- 未测实际目标 Blender 构建：官方 `v5.0.0` 与 main 的阅读不能替代项目记录的 5.2 运行时能力证明。
- 未证实精确 ASL 带宽、九点射线对全像素可见性的等价、0.1 朝向阈值的普适性；它们不能被表述为“官方/论文已证明”。
- 未验证下游 VACE 实际工作流的 codec/颜色/分辨率输入适配；仅核验理论接口区分。
- 未执行杀进程恢复、磁盘故障/断电、远端调用幂等；F2 必须用实际提交边界测试。
- 未引入任何 GitHub 依赖，未拷贝 GPL 源码，未改 AGENTS.md，未删除/跳过/弱化测试。

交接优先级：A7 先完成独立全帧基线与真实字框归因；B3 明确深度混合/射线身份/采样比例口径；D2 测实际时间轮廓；E2 同测 sRGB 颜色与故障恢复；F2 将内存回滚和跨进程续跑分开验收。
