# 空间尺指标规范 v1.0

状态：指标参考（disclosed reference，经《空间尺多维评测扩展 SPEC v1.0》§4 指针引入）
范围：32 个新增指标的完整规格；现有 6 项指标只给真源指针。
本文件不承诺实现；实现细节以主 SPEC §1.1 真源映射为准。

## 通用字段与规则

每项指标统一给出 8 个字段：

- **粒度**：Frame（单帧）/ Shot（内容关键帧 + 动作关键帧）/ Sequence（相邻镜头集）。
- **输入**：该指标需要的证据，来源见主 SPEC §6。
- **测量值**：程序测量的原始值与归一化方式。
- **目标区间**：0..1 分数或 NDC 距离的通过区间；具体默认值以 `specs/config.default.yaml` 为真源。
- **严重度**：fatal / error / warning / note，定义见主 SPEC §5.3。
- **失败原因**：导致指标不通过的可复现几何/叙事条件。
- **修复方向**：可执行的工具方向与预期影响分量，不写不可验证的自由文本。
- **证据等级**：production（相机投影+场景状态）/ demo（人工输入，仅演示）。

硬门联动：指标命中硬门条件时引用主 SPEC §5.2 的 H1–H6 编号。
样例要求：每个新增指标至少一组 good/bad/ambiguous 样例，与主 SPEC §8、§11.1 一致。

## 现有六项指标（真源指针，不重写定义）

| 指标 | 真源 |
|---|---|
| `headroom` / `lead_room` / `rule_of_thirds` / `balance` / `occlusion` / `framing` | `block_director/cinema/composition.py` |

## 4.1 几何基础层（Frame，5 项）

### `edge_clearance`
- 粒度：Frame
- 输入：主体关键点（头、手、脚、道具）的投影包围盒与画面边缘
- 测量值：各关键点到最近边缘的 NDC 距离，取最小值
- 目标区间：[0.04, 0.20]；景别越小下限越低
- 严重度：关键点完全出画 fatal；贴近边缘 error；其余 warning
- 失败原因：主体贴边、景别过紧、道具伸出画面
- 修复方向：`move_character` / `reframe` / 调整 lens，把关键点拉回安全区
- 证据等级：production；联动 H1

### `depth_separation`
- 粒度：Frame
- 输入：前后主体深度值、投影重叠率、相对尺度
- 测量值：深度差 / 投影重叠面积的组合分
- 目标区间：0.60..1.00
- 严重度：主次深度不可辨 fatal；重叠但深度差小 error；其余 note
- 失败原因：前后景距离过近、机位角度使两层几乎重合
- 修复方向：`move_character` 拉开纵深、`move_camera` 改变机位角度
- 证据等级：production

### `silhouette_separation`
- 粒度：Frame
- 输入：主体轮廓与背景/他人轮廓的差分蒙版
- 测量值：轮廓重叠像素 / 主体轮廓像素
- 目标区间：重叠率 ≤ 0.25 且可分离轮廓存在
- 严重度：关键动作轮廓粘连 fatal；部分粘连 error；其余 note
- 失败原因：人物重叠、暗背景吞边、轮廓同色
- 修复方向：错开站位、增加边缘光或对比、调整机位
- 证据等级：production

### `screen_size`
- 粒度：Frame
- 输入：主体屏幕高度/宽度、声明景别
- 测量值：主体尺度与景别期望尺度的相对偏差
- 目标区间：偏差 ≤ ±15%
- 严重度：与意图完全不符 fatal；超差 error；轻微偏移 warning
- 失败原因：距离错误、镜头焦距错误、景别声明与画面不一致
- 修复方向：`move_camera` 或 `reframe` 修正距离/焦距
- 证据等级：production

### `horizon_stability`
- 粒度：Frame / Shot
- 输入：地平线或主导水平线的倾斜角、构图意图
- 测量值：画面滚转角与意图基准的偏差
- 目标区间：无意图时 ≤ 1°；有意图时与声明一致
- 严重度：无意图的严重倾斜 fatal；轻微漂移 error
- 失败原因：相机滚转未锁定、手持/主观镜头未声明
- 修复方向：修正相机 roll、声明倾斜意图
- 证据等级：production

## 4.2 视线与注意力层（Frame/Shot，5 项）

### `gaze_target_visibility`
- 粒度：Frame / Shot
- 输入：视线射线、视线目标位置、遮挡射线、画框
- 测量值：视线目标在画内比例 + 可见比例
- 目标区间：≥ 0.80 且目标位于合理前方区域
- 严重度：目标完全不在画内 fatal；被遮挡 error；偏移 warning
- 失败原因：机位与视线方向相反、目标出画、前景遮挡
- 修复方向：`move_camera` 换侧、`move_character` 调整目标位置
- 证据等级：production；联动 H4

### `eyeline_consistency`
- 粒度：Sequence
- 输入：对切镜头中人物视线高度、方向与目标关系
- 测量值：相邻镜头视线高度差与方向一致性
- 目标区间：高度差 ≤ 1 个头位，方向无反向跳变
- 严重度：互看关系断裂 fatal；高度跳变 error
- 失败原因：机位高度突变、视线锚点漂移
- 修复方向：统一视线锚点高度、`move_camera` 对齐机位
- 证据等级：production

### `attention_priority`
- 粒度：Frame / Shot
- 输入：意图主体排序、各主体面积/位置/对比度/运动量
- 测量值：视觉显著度排序与意图排序的匹配度
- 目标区间：≥ 0.80
- 严重度：意图主体被完全压过 fatal；排序错位 error
- 失败原因：非意图主体更大/更亮/更动、主体远离三分区
- 修复方向：`move_character`、灯光对比、景深或 `focus_competition` 联动
- 证据等级：production

### `focus_competition`
- 粒度：Frame / Shot
- 输入：非意图主体与意图主体的显著度差
- 测量值：竞争主体显著度 / 意图主体显著度
- 目标区间：≤ 0.75
- 严重度：明显抢戏 error；轻微竞争 warning
- 失败原因：配角居中、大面积高亮、背景运动
- 修复方向：移动配角、调低对比、控制背景运动
- 证据等级：production

### `beat_coverage`
- 粒度：Shot
- 输入：`IntentContract` 节拍、镜头时间范围、内容关键帧覆盖
- 测量值：节拍要求的元素（主体/动作/结果）在镜头中的覆盖率
- 目标区间：≥ 0.90
- 严重度：节拍元素完全缺失 fatal；部分缺失 error
- 失败原因：镜头过短、主体不在画、动作发生在画外
- 修复方向：延长镜头、`reframe` 覆盖动作区、拆镜补拍
- 证据等级：production

## 4.3 动作与因果层（Shot，6 项）

### `action_readability`
- 粒度：Shot
- 输入：动作关键帧中动作起点/路径/终点/接触点位置
- 测量值：各关键动作元素的可辨数量与可见比例
- 目标区间：≥ 0.80
- 严重度：任一关键元素不可辨 fatal；部分缺失 error
- 失败原因：动作过快、主体重叠、机位过远
- 修复方向：`move_camera` 近机位、错开站位、拆分动作关键帧
- 证据等级：production；联动 H2

### `cause_effect_visibility`
- 粒度：Shot
- 输入：发起者、受力者、动作结果的时序与可见性
- 测量值：因果链三段（发起→受力→结果）的可见覆盖率
- 目标区间：三段可见 ≥ 0.85
- 严重度：因果链断裂 fatal；一段不可见 error
- 失败原因：攻击者出画、受力者遮挡、结果未拍
- 修复方向：`move_character`、`move_camera`、补结果镜头
- 证据等级：production；联动 H2

### `contact_point_visibility`
- 粒度：Shot
- 输入：打击/抓取/碰撞接触点位置、遮挡、画内状态
- 测量值：接触点在接触帧的可见比例
- 目标区间：≥ 0.70
- 严重度：接触点不可辨 fatal；部分遮挡 error
- 失败原因：接触点被身体遮挡、机位与接触点共线
- 修复方向：换侧机位、错开站位、调整接触角度
- 证据等级：production；联动 H2

### `pose_phase_separation`
- 粒度：Shot
- 输入：准备/发力/接触/反应四阶段的姿态帧
- 测量值：可区分的阶段数 / 4
- 目标区间：≥ 0.75（至少 3 阶段可辨）
- 严重度：阶段混杂不可分 fatal；一阶段缺失 error
- 失败原因：动作过密、帧采样不足、姿态相似
- 修复方向：拆阶段补帧、`estimate_shot_duration` 重排节奏
- 证据等级：production

### `reaction_legibility`
- 粒度：Shot
- 输入：受击/被推动/失衡结果姿态与遮挡
- 测量值：结果姿态可见帧比例
- 目标区间：≥ 0.70
- 严重度：结果姿态完全不可见 fatal；被遮挡 error
- 失败原因：反应在画外、被前景遮挡、镜头切走过早
- 修复方向：延长反应停留、换机位、`move_character` 拉开遮挡
- 证据等级：production

### `prop_interaction_visibility`
- 粒度：Shot
- 输入：角色与关键道具的接触关系、道具可见性
- 测量值：手—道具—目标三段接触的可见比例
- 目标区间：≥ 0.80
- 严重度：关键交互不可辨 fatal；部分缺失 error
- 失败原因：道具出画、接触被遮挡、交互过快
- 修复方向：`move_character` / `create_prop` 定位、换机位
- 证据等级：production

## 4.4 连续性层（Sequence，6 项）

### `axis_continuity`
- 粒度：Sequence
- 输入：相邻镜头轴侧、角色屏幕左右关系
- 测量值：越轴事件数 / 相邻镜头对总数
- 目标区间：未声明越轴 = 0
- 严重度：未声明越轴 fatal；声明但未标记 warning
- 失败原因：机位跨轴、摆位线漂移
- 修复方向：`move_camera` 回到轴侧、声明越轴意图
- 证据等级：production；联动 H3

### `motion_vector_continuity`
- 粒度：Sequence
- 输入：角色/相机运动方向向量、相邻镜头承接
- 测量值：方向夹角与承接一致性
- 目标区间：方向连续或有明确转场意图
- 严重度：无意图反向 fatal；轻微漂移 warning
- 失败原因：追逐双方换位、剪辑时运动方向未衔接
- 修复方向：`move_camera` 保持方向、调整剪辑顺序
- 证据等级：production

### `scale_continuity`
- 粒度：Sequence
- 输入：相邻镜头景别/主体尺度
- 测量值：景别跳级数 / 相邻镜头对总数
- 目标区间：跳级均有叙事意图
- 严重度：无意图突兀跳级 error；轻微差级 warning
- 失败原因：剪辑拼错景别、意图未声明
- 修复方向：`reframe` 对齐景别、声明跳级意图
- 证据等级：production

### `eyeline_match`
- 粒度：Sequence
- 输入：对切镜头双方视线目标与高度
- 测量值：互看方向与高度匹配率
- 目标区间：≥ 0.90
- 严重度：互看关系断裂 fatal；高度漂移 error
- 失败原因：视线锚点不一致、机位高度变化
- 修复方向：统一锚点、`move_camera` 对齐
- 证据等级：production

### `screen_direction`
- 粒度：Sequence
- 输入：出画/入画方向、运动方向、剪辑承接
- 测量值：方向一致镜头对数 / 总数
- 目标区间：≥ 0.95 或有明确转场意图
- 严重度：动作接续反向 fatal；个别不一致 warning
- 失败原因：越轴、角色交换左右位、剪辑接错
- 修复方向：保持轴侧、`move_character` 纠正入画位
- 证据等级：production

### `temporal_readability`
- 粒度：Sequence
- 输入：接触事件、剪辑点、前后镜头时间信息
- 测量值：动作—结果顺序可解释的镜头对数
- 目标区间：≥ 0.90
- 严重度：结果先于动作且无法解释 fatal；信息不足 error
- 失败原因：剪辑过早切走、省略必要过程帧
- 修复方向：补过程帧、调整剪辑点
- 证据等级：production

## 4.5 摄影意图层（Shot，5 项）

### `perspective_fit`
- 粒度：Shot
- 输入：焦距、机位距离、主体关系、景别/情绪意图
- 测量值：透视特征与意图匹配度
- 目标区间：≥ 0.80
- 严重度：与意图完全不符 error；轻微偏差 warning
- 失败原因：焦距选择错误、距离与景别冲突
- 修复方向：调整 lens、`move_camera` 修正距离
- 证据等级：production

### `camera_path_clearance`
- 粒度：Shot
- 输入：相机路径采样点、角色/障碍包围盒
- 测量值：路径与碰撞体的最小距离
- 目标区间：最小距离 ≥ 安全阈值（默认 0.2 m）
- 严重度：穿过主体或碰撞体 fatal；贴边 error
- 失败原因：路径规划过近、`move_camera` 弧线穿模
- 修复方向：抬高/外移路径、分段重排运镜
- 证据等级：production；联动 H5

### `reveal_progression`
- 粒度：Shot
- 输入：建立/揭示镜头的内容关键帧空间信息增量
- 测量值：画面中新出现信息面积随时间的累积
- 目标区间：单调递增且首末帧差异可辨
- 严重度：无揭示进程 error；信息停滞 warning
- 失败原因：机位不动、主体未进入、信息一次全给
- 修复方向：加运镜、`move_camera` 移动机位、分镜揭示
- 证据等级：production

### `movement_intent_match`
- 粒度：Shot
- 输入：声明运镜类型、实际相机轨迹、意图
- 测量值：实际轨迹与意图类型的相似度
- 目标区间：≥ 0.80
- 严重度：运镜与意图无关 error；偏差 warning
- 失败原因：跟拍写成固定机位、推拉方向反了
- 修复方向：按 `camera.movements` 重写轨迹、`move_camera` 修正
- 证据等级：production

### `spatial_orientation`
- 粒度：Shot / Sequence
- 输入：环境地标、出入口、人物相对位置
- 测量值：关键空间参照物在内容关键帧中的可辨性
- 目标区间：≥ 0.80
- 严重度：空间完全无法建立 error；部分缺失 warning
- 失败原因：无地标入画、机位角度丢失参照、跳跃剪辑
- 修复方向：加建立镜、`move_camera` 纳入地标、稳定朝向
- 证据等级：production

## 4.6 鲁棒性与工程层（Shot，5 项）

### `pose_robustness`
- 粒度：Shot
- 输入：姿态微扰后的各核心指标结果
- 测量值：微扰后仍通过的指标比例
- 目标区间：≥ 0.90
- 严重度：核心指标大面积翻转 error；个别翻转 warning
- 失败原因：测量对采样点敏感、阈值边缘化
- 修复方向：加扰动回归样例、固定采样点、调整阈值边界
- 证据等级：production

### `camera_robustness`
- 粒度：Shot
- 输入：相机采样误差/轨迹插值后的核心指标
- 测量值：扰动后仍通过的指标比例
- 目标区间：≥ 0.90
- 严重度：轨迹插值导致穿模或构图翻转 error
- 失败原因：插值过粗、采样点不足
- 修复方向：加密路径采样、`move_camera` 平滑轨迹
- 证据等级：production

### `label_safe_area`
- 粒度：Frame / Shot
- 输入：标签、网格、辅助线的投影区域与关键视觉信息
- 测量值：关键视觉信息被覆盖的比例
- 目标区间：= 0
- 严重度：关键接触点/视线被遮挡 fatal；次要信息遮挡 warning
- 失败原因：标签布局压住主体、网格盖住动作区
- 修复方向：标签避让规则、`label_safe_area` 校验后调整布局
- 证据等级：production

### `visibility_stability`
- 粒度：Shot
- 输入：关键主体在内容关键帧与动作关键帧上的可见状态序列
- 测量值：出画/被遮挡帧数 / 总采样关键帧数（两类并集）
- 目标区间：≤ 0.10
- 严重度：反复出画 fatal；单次短时出画 error
- 失败原因：走位经过遮挡区、机位跟随不及时
- 修复方向：`move_character` 绕开遮挡、`move_camera` 提前跟随
- 证据等级：production

### `repair_locality`
- 粒度：Shot / Sequence
- 输入：修复前后相邻镜头与目标镜头的指标变化
- 测量值：非目标镜头发生破坏的数量
- 目标区间：= 0
- 严重度：破坏相邻镜头且未记录 fatal；可接受局部影响 warning
- 失败原因：全局移动相机/角色、共享锚点被改
- 修复方向：单镜修复工具、修复前记录基线、diff 报告
- 证据等级：production；联动 H6
