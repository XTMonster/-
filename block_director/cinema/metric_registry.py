"""空间尺指标注册表与分层评分（Ticket 02）。

单一真源：32 条新增指标的完整规格，逐条转录《空间尺指标规范 v1.0》
（docs/SPEC_空间尺_指标规范_v1.0.md §4.1–§4.6）；现有六项指标
（composition.py 真源）不在此重复定义，只保留真源指针；Ticket 03a
再挂 6 条 composition 真源指针指标（32 -> 38，见 §4.7）。

术语约定（用户 2026-10-13 裁决）：只使用「内容关键帧 / 动作关键帧」，
不接受混用「关键帧」指代两者。

分层分数公式（主 SPEC §5.1）：每个分量输出 0..1，每层输出 0..100，
总览分 = 六层加权平均。权重默认值以 specs/config.default.yaml 为运行时
真源（本文件 LAYER_WEIGHTS_DEFAULT 是规格快照，测试逐键对拍防漂移），
每次运行记录权重指纹（tools/evidence_fingerprint.py）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple

from .evaluation_protocol import Measurement


# --------------------------------------------------------------------------- #
# 六层与默认权重（主 SPEC §5.1 规格快照；运行时真源 = specs/config.default.yaml）
# --------------------------------------------------------------------------- #
LAYERS: Tuple[str, ...] = (
    "geometry", "attention", "action", "continuity", "cinema", "robustness",
)

#: 总览分默认权重（§5.1）：0.25/0.20/0.20/0.15/0.10/0.10。
LAYER_WEIGHTS_DEFAULT: Dict[str, float] = {
    "geometry": 0.25,
    "attention": 0.20,
    "action": 0.20,
    "continuity": 0.15,
    "cinema": 0.10,
    "robustness": 0.10,
}


# --------------------------------------------------------------------------- #
# 指标规格
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MetricSpec:
    """一条新增指标的完整规格（《指标规范 v1.0》通用 8 字段 + 联动 + 样例）。

    * ``granularity``：Frame / Shot / Sequence（含「内容关键帧 + 动作关键帧」语义）；
    * ``links_to_gates``：命中硬门条件时引用的 H1–H6 编号（§5.2）；
    * ``sample_requirements``：good/bad/ambiguous 三态样例要求（§8/§11.1）。
    """

    name: str
    layer: str
    granularity: str
    inputs: str
    measurement: str
    target: str
    severity: str
    failure_cause: str
    repair_direction: str
    evidence_grade: str = "production"
    links_to_gates: Tuple[str, ...] = ()
    sample_requirements: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.layer not in LAYERS:
            raise ValueError(f"未知层 {self.layer!r}；合法值 {LAYERS}")
        for gate in self.links_to_gates:
            if gate not in ("H1", "H2", "H3", "H4", "H5", "H6"):
                raise ValueError(f"非法硬门 {gate!r}；合法值 H1–H6")
        missing = {"good", "bad", "ambiguous"} - set(self.sample_requirements)
        if missing:
            raise ValueError(
                f"{self.name} 缺少三态样例要求：{sorted(missing)}")


# --------------------------------------------------------------------------- #
# 32 条新增指标（§4.1–§4.6）+ 6 条 composition 真源指针（§4.7，Ticket 03a）
# --------------------------------------------------------------------------- #
METRIC_REGISTRY: Tuple[MetricSpec, ...] = (
    # ------------------------- 4.1 几何基础层（5 项） ------------------------
    MetricSpec(
        name="edge_clearance",
        layer="geometry",
        granularity="Frame",
        inputs="主体关键点（头、手、脚、道具）的投影包围盒与画面边缘",
        measurement="各关键点到最近边缘的 NDC 距离，取最小值",
        target="[0.04, 0.20]；景别越小下限越低",
        severity="关键点完全出画 fatal；贴近边缘 error；其余 warning",
        failure_cause="主体贴边、景别过紧、道具伸出画面",
        repair_direction="move_character / reframe / 调整 lens，把关键点拉回安全区",
        evidence_grade="production",
        links_to_gates=("H1",),
        sample_requirements={
            "good": "单人标准中景，主体关键点到最近画面边缘的 NDC 距离 ≥ 0.04，全帧稳定",
            "bad": "景别过紧或主体贴边，关键点部分出画/贴近边缘，边缘距离 < 0.04",
            "ambiguous": "边缘距离恰在目标区间边界（≈0.04）且景别声明为近景，需人工复核",
        },
    ),
    MetricSpec(
        name="depth_separation",
        layer="geometry",
        granularity="Frame",
        inputs="前后主体深度值、投影重叠率、相对尺度",
        measurement="深度差 / 投影重叠面积的组合分",
        target="0.60..1.00",
        severity="主次深度不可辨 fatal；重叠但深度差小 error；其余 note",
        failure_cause="前后景距离过近、机位角度使两层几乎重合",
        repair_direction="move_character 拉开纵深、move_camera 改变机位角度",
        evidence_grade="production",
        sample_requirements={
            "good": "双人走位场景前后景深度差明显，投影重叠率低，组合分 ≥ 0.60",
            "bad": "前后主体距离过近、机位角度使两层几乎重合，主次深度不可辨",
            "ambiguous": "深度差中等、重叠率处于阈值边缘，斜角机位看似分离实则贴背，需人工复核",
        },
    ),
    MetricSpec(
        name="silhouette_separation",
        layer="geometry",
        granularity="Frame",
        inputs="主体轮廓与背景/他人轮廓的差分蒙版",
        measurement="轮廓重叠像素 / 主体轮廓像素",
        target="重叠率 ≤ 0.25 且可分离轮廓存在",
        severity="关键动作轮廓粘连 fatal；部分粘连 error；其余 note",
        failure_cause="人物重叠、暗背景吞边、轮廓同色",
        repair_direction="错开站位、增加边缘光或对比、调整机位",
        evidence_grade="production",
        sample_requirements={
            "good": "双人/多人场景主体轮廓与背景或他人轮廓完全可分离，重叠率 ≤ 0.25",
            "bad": "人物重叠、暗背景吞边，关键动作轮廓粘连，重叠率超限",
            "ambiguous": "轮廓部分重叠但属于有意层次（前后景压脚），需人工复核是否阻断动作可辨性",
        },
    ),
    MetricSpec(
        name="screen_size",
        layer="geometry",
        granularity="Frame",
        inputs="主体屏幕高度/宽度、声明景别",
        measurement="主体尺度与景别期望尺度的相对偏差",
        target="偏差 ≤ ±15%",
        severity="与意图完全不符 fatal；超差 error；轻微偏移 warning",
        failure_cause="距离错误、镜头焦距错误、景别声明与画面不一致",
        repair_direction="move_camera 或 reframe 修正距离/焦距",
        evidence_grade="production",
        sample_requirements={
            "good": "单人标准中景，主体尺度与声明景别偏差 ≤ ±15%",
            "bad": "距离/焦距错误使主体与声明景别完全不符（如中景拍成特写）",
            "ambiguous": "偏差处于 15% 边界附近且运镜为推拉，需人工复核按首/中/末帧哪个判定",
        },
    ),
    MetricSpec(
        name="horizon_stability",
        layer="geometry",
        granularity="Frame / Shot",
        inputs="地平线或主导水平线的倾斜角、构图意图",
        measurement="画面滚转角与意图基准的偏差",
        target="无意图时 ≤ 1°；有意图时与声明一致",
        severity="无意图的严重倾斜 fatal；轻微漂移 error",
        failure_cause="相机滚转未锁定、手持/主观镜头未声明",
        repair_direction="修正相机 roll、声明倾斜意图",
        evidence_grade="production",
        sample_requirements={
            "good": "无意图的平稳镜头滚转偏差 ≤ 1°，或倾斜地平线与特殊意图声明一致",
            "bad": "相机滚转未锁定，无意图的严重倾斜，画面明显歪斜",
            "ambiguous": "轻微倾斜且剧本有主观镜头暗示但未显式声明，需人工复核是否算有意图",
        },
    ),
    # --------------------- 4.2 视线与注意力层（5 项） -----------------------
    MetricSpec(
        name="gaze_target_visibility",
        layer="attention",
        granularity="Frame / Shot",
        inputs="视线射线、视线目标位置、遮挡射线、画框",
        measurement="视线目标在画内比例 + 可见比例",
        target="≥ 0.80 且目标位于合理前方区域",
        severity="目标完全不在画内 fatal；被遮挡 error；偏移 warning",
        failure_cause="机位与视线方向相反、目标出画、前景遮挡",
        repair_direction="move_camera 换侧、move_character 调整目标位置",
        evidence_grade="production",
        links_to_gates=("H4",),
        sample_requirements={
            "good": "双人对话，视线目标在画内且可见比例 ≥ 0.80、位于合理前方区域",
            "bad": "机位与视线方向相反导致目标完全不在画内（H4），或被前景遮挡",
            "ambiguous": "目标入画但位于画面边缘/前景半遮挡，需人工复核是否影响视线可读",
        },
    ),
    MetricSpec(
        name="eyeline_consistency",
        layer="attention",
        granularity="Sequence",
        inputs="对切镜头中人物视线高度、方向与目标关系",
        measurement="相邻镜头视线高度差与方向一致性",
        target="高度差 ≤ 1 个头位，方向无反向跳变",
        severity="互看关系断裂 fatal；高度跳变 error",
        failure_cause="机位高度突变、视线锚点漂移",
        repair_direction="统一视线锚点高度、move_camera 对齐机位",
        evidence_grade="production",
        sample_requirements={
            "good": "对切镜头双方视线高度差 ≤ 1 个头位，方向无反向跳变",
            "bad": "机位高度突变/视线锚点漂移，互看关系断裂",
            "ambiguous": "高度差恰在 1 个头位附近且角色身高不同，需人工复核是否仍成立互看",
        },
    ),
    MetricSpec(
        name="attention_priority",
        layer="attention",
        granularity="Frame / Shot",
        inputs="意图主体排序、各主体面积/位置/对比度/运动量",
        measurement="视觉显著度排序与意图排序的匹配度",
        target="≥ 0.80",
        severity="意图主体被完全压过 fatal；排序错位 error",
        failure_cause="非意图主体更大/更亮/更动、主体远离三分区",
        repair_direction="move_character、灯光对比、景深或 focus_competition 联动",
        evidence_grade="production",
        sample_requirements={
            "good": "多人群戏，意图主体在面积/位置/对比度/运动量上排序第一，匹配度 ≥ 0.80",
            "bad": "非意图主体更大更亮更动，意图主体被完全压过",
            "ambiguous": "两个主体的显著度接近、意图排序本身可两解，需人工复核",
        },
    ),
    MetricSpec(
        name="focus_competition",
        layer="attention",
        granularity="Frame / Shot",
        inputs="非意图主体与意图主体的显著度差",
        measurement="竞争主体显著度 / 意图主体显著度",
        target="≤ 0.75",
        severity="明显抢戏 error；轻微竞争 warning",
        failure_cause="配角居中、大面积高亮、背景运动",
        repair_direction="移动配角、调低对比、控制背景运动",
        evidence_grade="production",
        sample_requirements={
            "good": "非意图主体显著度 ≤ 意图主体的 0.75，意图清晰",
            "bad": "配角居中、大面积高亮或背景运动，明显抢戏，竞争比 > 0.75",
            "ambiguous": "竞争比处于 0.75 边界附近且配角有台词节拍，需人工复核是否算合理陪衬",
        },
    ),
    MetricSpec(
        name="beat_coverage",
        layer="attention",
        granularity="Shot",
        inputs="IntentContract 节拍、镜头时间范围、内容关键帧覆盖",
        measurement="节拍要求的元素（主体/动作/结果）在镜头中的覆盖率",
        target="≥ 0.90",
        severity="节拍元素完全缺失 fatal；部分缺失 error",
        failure_cause="镜头过短、主体不在画、动作发生在画外",
        repair_direction="延长镜头、reframe 覆盖动作区、拆镜补拍",
        evidence_grade="production",
        sample_requirements={
            "good": "镜头覆盖节拍要求的主体/动作/结果，覆盖率 ≥ 0.90",
            "bad": "镜头过短、主体不在画、动作发生在画外，节拍元素完全缺失",
            "ambiguous": "节拍元素部分在画外但镜头运动将带出，需人工复核内容关键帧选择",
        },
    ),
    # --------------------- 4.3 动作与因果层（6 项） -------------------------
    MetricSpec(
        name="action_readability",
        layer="action",
        granularity="Shot",
        inputs="动作关键帧中动作起点/路径/终点/接触点位置",
        measurement="各关键动作元素的可辨数量与可见比例",
        target="≥ 0.80",
        severity="任一关键元素不可辨 fatal；部分缺失 error",
        failure_cause="动作过快、主体重叠、机位过远",
        repair_direction="move_camera 近机位、错开站位、拆分动作关键帧",
        evidence_grade="production",
        links_to_gates=("H2",),
        sample_requirements={
            "good": "打斗接触，动作起点/路径/终点/接触点在动作关键帧中可辨，≥ 0.80",
            "bad": "动作过快、主体重叠或机位过远，任一关键动作元素不可辨（H2）",
            "ambiguous": "快速连击部分元素不可辨但节奏意图是乱战，需人工复核是否构成可读动作",
        },
    ),
    MetricSpec(
        name="cause_effect_visibility",
        layer="action",
        granularity="Shot",
        inputs="发起者、受力者、动作结果的时序与可见性",
        measurement="因果链三段（发起→受力→结果）的可见覆盖率",
        target="三段可见 ≥ 0.85",
        severity="因果链断裂 fatal；一段不可见 error",
        failure_cause="攻击者出画、受力者遮挡、结果未拍",
        repair_direction="move_character、move_camera、补结果镜头",
        evidence_grade="production",
        links_to_gates=("H2",),
        sample_requirements={
            "good": "发起→受力→结果三段因果链均可见，覆盖 ≥ 0.85",
            "bad": "攻击者出画、受力者遮挡或结果未拍，因果链断裂（H2）",
            "ambiguous": "攻击在画外发起但受击与结果可见，需人工复核是否仍构成可读因果",
        },
    ),
    MetricSpec(
        name="contact_point_visibility",
        layer="action",
        granularity="Shot",
        inputs="打击/抓取/碰撞接触点位置、遮挡、画内状态",
        measurement="接触点在接触帧的可见比例",
        target="≥ 0.70",
        severity="接触点不可辨 fatal；部分遮挡 error",
        failure_cause="接触点被身体遮挡、机位与接触点共线",
        repair_direction="换侧机位、错开站位、调整接触角度",
        evidence_grade="production",
        links_to_gates=("H2",),
        sample_requirements={
            "good": "打击/抓取/碰撞接触点在接触帧可见比例 ≥ 0.70",
            "bad": "接触点被身体遮挡或机位与接触点共线，接触点不可辨（H2）",
            "ambiguous": "接触点部分被遮挡但轮廓提示足够，需人工复核是否可辨",
        },
    ),
    MetricSpec(
        name="pose_phase_separation",
        layer="action",
        granularity="Shot",
        inputs="准备/发力/接触/反应四阶段的姿态帧",
        measurement="可区分的阶段数 / 4",
        target="≥ 0.75（至少 3 阶段可辨）",
        severity="阶段混杂不可分 fatal；一阶段缺失 error",
        failure_cause="动作过密、帧采样不足、姿态相似",
        repair_direction="拆阶段补帧、estimate_shot_duration 重排节奏",
        evidence_grade="production",
        sample_requirements={
            "good": "准备/发力/接触/反应四阶段可区分 ≥ 3 阶段（≥ 0.75）",
            "bad": "动作过密、采样不足或姿态相似，阶段混杂不可分",
            "ambiguous": "四阶段中某两阶段姿态相似但节奏上可推断，需人工复核",
        },
    ),
    MetricSpec(
        name="reaction_legibility",
        layer="action",
        granularity="Shot",
        inputs="受击/被推动/失衡结果姿态与遮挡",
        measurement="结果姿态可见帧比例",
        target="≥ 0.70",
        severity="结果姿态完全不可见 fatal；被遮挡 error",
        failure_cause="反应在画外、被前景遮挡、镜头切走过早",
        repair_direction="延长反应停留、换机位、move_character 拉开遮挡",
        evidence_grade="production",
        sample_requirements={
            "good": "受击/被推动/失衡结果姿态可见帧比例 ≥ 0.70",
            "bad": "反应在画外、被前景遮挡或镜头切走过早，结果姿态完全不可见",
            "ambiguous": "反应姿态部分被挡但镜头继续停留到恢复，需人工复核是否可辨",
        },
    ),
    MetricSpec(
        name="prop_interaction_visibility",
        layer="action",
        granularity="Shot",
        inputs="角色与关键道具的接触关系、道具可见性",
        measurement="手—道具—目标三段接触的可见比例",
        target="≥ 0.80",
        severity="关键交互不可辨 fatal；部分缺失 error",
        failure_cause="道具出画、接触被遮挡、交互过快",
        repair_direction="move_character / create_prop 定位、换机位",
        evidence_grade="production",
        sample_requirements={
            "good": "手—道具—目标三段接触可见比例 ≥ 0.80",
            "bad": "道具出画、接触被遮挡或交互过快，关键交互不可辨",
            "ambiguous": "手与道具接触点被身体遮挡但道具轨迹清晰，需人工复核是否可辨",
        },
    ),
    # ----------------------- 4.4 连续性层（6 项） ---------------------------
    MetricSpec(
        name="axis_continuity",
        layer="continuity",
        granularity="Sequence",
        inputs="相邻镜头轴侧、角色屏幕左右关系",
        measurement="越轴事件数 / 相邻镜头对总数",
        target="未声明越轴 = 0",
        severity="未声明越轴 fatal；声明但未标记 warning",
        failure_cause="机位跨轴、摆位线漂移",
        repair_direction="move_camera 回到轴侧、声明越轴意图",
        evidence_grade="production",
        links_to_gates=("H3",),
        sample_requirements={
            "good": "双人对话相邻镜头保持 180 度轴侧与屏幕左右关系，未声明越轴 = 0",
            "bad": "机位跨轴或摆位线漂移，未声明越轴（H3）",
            "ambiguous": "声明了越轴但未标记具体帧/方向，需人工复核越轴意图是否清楚",
        },
    ),
    MetricSpec(
        name="motion_vector_continuity",
        layer="continuity",
        granularity="Sequence",
        inputs="角色/相机运动方向向量、相邻镜头承接",
        measurement="方向夹角与承接一致性",
        target="方向连续或有明确转场意图",
        severity="无意图反向 fatal；轻微漂移 warning",
        failure_cause="追逐双方换位、剪辑时运动方向未衔接",
        repair_direction="move_camera 保持方向、调整剪辑顺序",
        evidence_grade="production",
        sample_requirements={
            "good": "追逐场景相邻镜头运动方向连续，或转场意图明确",
            "bad": "追逐双方换位、剪辑方向未衔接，无意图反向",
            "ambiguous": "方向夹角中等且转场意图隐含在台词，需人工复核",
        },
    ),
    MetricSpec(
        name="scale_continuity",
        layer="continuity",
        granularity="Sequence",
        inputs="相邻镜头景别/主体尺度",
        measurement="景别跳级数 / 相邻镜头对总数",
        target="跳级均有叙事意图",
        severity="无意图突兀跳级 error；轻微差级 warning",
        failure_cause="剪辑拼错景别、意图未声明",
        repair_direction="reframe 对齐景别、声明跳级意图",
        evidence_grade="production",
        sample_requirements={
            "good": "相邻镜头景别递进/跳级有明确叙事意图",
            "bad": "剪辑拼错景别且无意图，突兀跳级",
            "ambiguous": "景别差一级但属于强调反应的惯用跳切，需人工复核",
        },
    ),
    MetricSpec(
        name="eyeline_match",
        layer="continuity",
        granularity="Sequence",
        inputs="对切镜头双方视线目标与高度",
        measurement="互看方向与高度匹配率",
        target="≥ 0.90",
        severity="互看关系断裂 fatal；高度漂移 error",
        failure_cause="视线锚点不一致、机位高度变化",
        repair_direction="统一锚点、move_camera 对齐",
        evidence_grade="production",
        sample_requirements={
            "good": "对切镜头双方视线目标与高度匹配率 ≥ 0.90",
            "bad": "视线锚点不一致或机位高度变化，互看关系断裂",
            "ambiguous": "双方高度差略超阈但机位带俯仰意图，需人工复核是否仍成立互看",
        },
    ),
    MetricSpec(
        name="screen_direction",
        layer="continuity",
        granularity="Sequence",
        inputs="出画/入画方向、运动方向、剪辑承接",
        measurement="方向一致镜头对数 / 总数",
        target="≥ 0.95 或有明确转场意图",
        severity="动作接续反向 fatal；个别不一致 warning",
        failure_cause="越轴、角色交换左右位、剪辑接错",
        repair_direction="保持轴侧、move_character 纠正入画位",
        evidence_grade="production",
        sample_requirements={
            "good": "出画/入画方向与运动方向一致，方向一致镜头对 ≥ 0.95 或有转场意图",
            "bad": "越轴、角色交换左右位或剪辑接错，动作接续反向",
            "ambiguous": "单次方向不一致但镜头内容为回头反打，需人工复核",
        },
    ),
    MetricSpec(
        name="temporal_readability",
        layer="continuity",
        granularity="Sequence",
        inputs="接触事件、剪辑点、前后镜头时间信息",
        measurement="动作—结果顺序可解释的镜头对数",
        target="≥ 0.90",
        severity="结果先于动作且无法解释 fatal；信息不足 error",
        failure_cause="剪辑过早切走、省略必要过程帧",
        repair_direction="补过程帧、调整剪辑点",
        evidence_grade="production",
        sample_requirements={
            "good": "动作—结果顺序可解释的镜头对 ≥ 0.90",
            "bad": "剪辑过早切走、省略必要过程帧，结果先于动作且无法解释",
            "ambiguous": "省略了过程但前后镜有明确时间跳变提示，需人工复核",
        },
    ),
    # --------------------- 4.5 摄影意图层（5 项） ---------------------------
    MetricSpec(
        name="perspective_fit",
        layer="cinema",
        granularity="Shot",
        inputs="焦距、机位距离、主体关系、景别/情绪意图",
        measurement="透视特征与意图匹配度",
        target="≥ 0.80",
        severity="与意图完全不符 error；轻微偏差 warning",
        failure_cause="焦距选择错误、距离与景别冲突",
        repair_direction="调整 lens、move_camera 修正距离",
        evidence_grade="production",
        sample_requirements={
            "good": "焦距/机位距离与景别/情绪意图匹配度 ≥ 0.80",
            "bad": "焦距选择错误或距离与景别冲突，与意图完全不符",
            "ambiguous": "广角近景拍情绪但主体边缘畸变明显，需人工复核是否接受",
        },
    ),
    MetricSpec(
        name="camera_path_clearance",
        layer="cinema",
        granularity="Shot",
        inputs="相机路径采样点、角色/障碍包围盒",
        measurement="路径与碰撞体的最小距离",
        target="最小距离 ≥ 安全阈值（默认 0.2 m）",
        severity="穿过主体或碰撞体 fatal；贴边 error",
        failure_cause="路径规划过近、move_camera 弧线穿模",
        repair_direction="抬高/外移路径、分段重排运镜",
        evidence_grade="production",
        links_to_gates=("H5",),
        sample_requirements={
            "good": "相机路径与角色/障碍最小距离 ≥ 0.2 m",
            "bad": "路径穿过主体或碰撞体（H5），或弧线穿模",
            "ambiguous": "最小距离恰在 0.2 m 边界且主体快速移动，需人工复核",
        },
    ),
    MetricSpec(
        name="reveal_progression",
        layer="cinema",
        granularity="Shot",
        inputs="建立/揭示镜头的内容关键帧空间信息增量",
        measurement="画面中新出现信息面积随时间的累积",
        target="单调递增且首末帧差异可辨",
        severity="无揭示进程 error；信息停滞 warning",
        failure_cause="机位不动、主体未进入、信息一次全给",
        repair_direction="加运镜、move_camera 移动机位、分镜揭示",
        evidence_grade="production",
        sample_requirements={
            "good": "建立镜头内容关键帧信息增量单调递增且首末帧差异可辨",
            "bad": "机位不动、主体未进入或信息一次全给，无揭示进程",
            "ambiguous": "信息增量主要在动作关键帧而非内容关键帧，需人工复核",
        },
    ),
    MetricSpec(
        name="movement_intent_match",
        layer="cinema",
        granularity="Shot",
        inputs="声明运镜类型、实际相机轨迹、意图",
        measurement="实际轨迹与意图类型的相似度",
        target="≥ 0.80",
        severity="运镜与意图无关 error；偏差 warning",
        failure_cause="跟拍写成固定机位、推拉方向反了",
        repair_direction="按 camera.movements 重写轨迹、move_camera 修正",
        evidence_grade="production",
        sample_requirements={
            "good": "实际相机轨迹与声明运镜类型相似度 ≥ 0.80",
            "bad": "跟拍写成固定机位或推拉方向反了，运镜与意图无关",
            "ambiguous": "轨迹近似但节奏不同（快推 vs 缓推），需人工复核",
        },
    ),
    MetricSpec(
        name="spatial_orientation",
        layer="cinema",
        granularity="Shot / Sequence",
        inputs="环境地标、出入口、人物相对位置",
        measurement="关键空间参照物在内容关键帧中的可辨性",
        target="≥ 0.80",
        severity="空间完全无法建立 error；部分缺失 warning",
        failure_cause="无地标入画、机位角度丢失参照、跳跃剪辑",
        repair_direction="加建立镜、move_camera 纳入地标、稳定朝向",
        evidence_grade="production",
        sample_requirements={
            "good": "建立镜头中环境地标/出入口在内容关键帧可辨，≥ 0.80",
            "bad": "无地标入画、机位角度丢失参照或跳跃剪辑，空间无法建立",
            "ambiguous": "地标部分可见但被角色遮挡，需人工复核",
        },
    ),
    # --------------------- 4.6 鲁棒性与工程层（5 项） -----------------------
    MetricSpec(
        name="pose_robustness",
        layer="robustness",
        granularity="Shot",
        inputs="姿态微扰后的各核心指标结果",
        measurement="微扰后仍通过的指标比例",
        target="≥ 0.90",
        severity="核心指标大面积翻转 error；个别翻转 warning",
        failure_cause="测量对采样点敏感、阈值边缘化",
        repair_direction="加扰动回归样例、固定采样点、调整阈值边界",
        evidence_grade="production",
        sample_requirements={
            "good": "姿态微扰后核心指标仍通过比例 ≥ 0.90",
            "bad": "测量对采样点敏感、阈值边缘化，核心指标大面积翻转",
            "ambiguous": "个别指标翻转但属于边界可接受的摆动，需人工复核",
        },
    ),
    MetricSpec(
        name="camera_robustness",
        layer="robustness",
        granularity="Shot",
        inputs="相机采样误差/轨迹插值后的核心指标",
        measurement="扰动后仍通过的指标比例",
        target="≥ 0.90",
        severity="轨迹插值导致穿模或构图翻转 error",
        failure_cause="插值过粗、采样点不足",
        repair_direction="加密路径采样、move_camera 平滑轨迹",
        evidence_grade="production",
        sample_requirements={
            "good": "相机采样误差/轨迹插值后核心指标通过比例 ≥ 0.90",
            "bad": "插值过粗、采样点不足，轨迹插值导致穿模或构图翻转",
            "ambiguous": "插值误差集中在非关键帧，需人工复核",
        },
    ),
    MetricSpec(
        name="label_safe_area",
        layer="robustness",
        granularity="Frame / Shot",
        inputs="标签、网格、辅助线的投影区域与关键视觉信息",
        measurement="关键视觉信息被覆盖的比例",
        target="= 0",
        severity="关键接触点/视线被遮挡 fatal；次要信息遮挡 warning",
        failure_cause="标签布局压住主体、网格盖住动作区",
        repair_direction="标签避让规则、label_safe_area 校验后调整布局",
        evidence_grade="production",
        sample_requirements={
            "good": "标签/网格/辅助线不覆盖关键视觉信息，覆盖比例 = 0",
            "bad": "标签布局压住接触点/视线，关键视觉信息被覆盖",
            "ambiguous": "标签覆盖次要信息但可能误导注意力，需人工复核",
        },
    ),
    MetricSpec(
        name="visibility_stability",
        layer="robustness",
        granularity="Shot",
        inputs="关键主体在内容关键帧与动作关键帧上的可见状态序列",
        measurement="出画/被遮挡帧数 / 总采样关键帧数（两类并集）",
        target="≤ 0.10",
        severity="反复出画 fatal；单次短时出画 error",
        failure_cause="走位经过遮挡区、机位跟随不及时",
        repair_direction="move_character 绕开遮挡、move_camera 提前跟随",
        evidence_grade="production",
        sample_requirements={
            "good": "关键主体在内容关键帧与动作关键帧中稳定可见，出画/遮挡 ≤ 0.10",
            "bad": "走位经过遮挡区或机位跟随不及时，反复出画",
            "ambiguous": "单次短时出画但发生在动作切帧间隙，需人工复核",
        },
    ),
    MetricSpec(
        name="repair_locality",
        layer="robustness",
        granularity="Shot / Sequence",
        inputs="修复前后相邻镜头与目标镜头的指标变化",
        measurement="非目标镜头发生破坏的数量",
        target="= 0",
        severity="破坏相邻镜头且未记录 fatal；可接受局部影响 warning",
        failure_cause="全局移动相机/角色、共享锚点被改",
        repair_direction="单镜修复工具、修复前记录基线、diff 报告",
        evidence_grade="production",
        links_to_gates=("H6",),
        sample_requirements={
            "good": "修复只改变目标镜头/主体，非目标镜头破坏数量 = 0",
            "bad": "全局移动相机/角色、共享锚点被改，破坏相邻镜头且未记录（H6）",
            "ambiguous": "相邻镜头受影响但已记录且有叙事合理性，需人工复核",
        },
    ),
    # ------------- 4.7 composition 真源指针（6 项，Ticket 03a） -------------
    # 不重复定义算法：inputs/measurement 指向 composition.py 的现有分量读数，
    # 只作注册表真源指针，不参与总览分权重（LAYER_WEIGHTS_DEFAULT 不含它们）。
    MetricSpec(
        name="headroom",
        layer="geometry",
        granularity="Frame",
        inputs="composition.py 的 headroom 分量读数（SubjectBox 投影 + 头顶留白）",
        measurement="直接取 composition.py headroom 分量归一化分数（0..1）",
        target="≥ 0.8（PASS_SCORE 达标口径，沿用 composition 真源阈值）",
        severity="分数 <0.3 fatal；<0.5 error；<0.8 warning",
        failure_cause="头顶留白不足/过多，主体垂直位置偏离构图意图",
        repair_direction="按方向调整机位/景别，让头顶留白回到目标区间（不替模型选参数）",
        evidence_grade="production",
        sample_requirements={
            "good": "composition.py headroom 分量 ≥ 0.8，头顶留白在理想区间",
            "bad": "composition.py headroom 分量 < 0.8，头顶留白明显不足/过多",
            "ambiguous": "分数恰在 0.8 边界且景别声明为近景，需人工复核",
        },
    ),
    MetricSpec(
        name="lead_room",
        layer="geometry",
        granularity="Frame",
        inputs="composition.py 的 lead_room 分量读数（主体包围盒与视线方向前方空间）",
        measurement="直接取 composition.py lead_room 分量归一化分数（0..1）",
        target="≥ 0.8（PASS_SCORE 达标口径，沿用 composition 真源阈值）",
        severity="分数 <0.3 fatal；<0.5 error；<0.8 warning",
        failure_cause="视线方向前方留白不足，主体偏向画边",
        repair_direction="把主体放到画面偏对侧，让视线方向留出前方空间（不替模型选参数）",
        evidence_grade="production",
        sample_requirements={
            "good": "composition.py lead_room 分量 ≥ 0.8，视线前方留白充足",
            "bad": "composition.py lead_room 分量 < 0.8，主体前方空间不足",
            "ambiguous": "分数恰在 0.8 边界且主体贴边但属有意构图，需人工复核",
        },
    ),
    MetricSpec(
        name="rule_of_thirds",
        layer="geometry",
        granularity="Frame",
        inputs="composition.py 的 rule_of_thirds 分量读数（主体中心到三分线交点的 NDC 偏差）",
        measurement="直接取 composition.py rule_of_thirds 分量归一化分数（0..1）",
        target="≥ 0.8（PASS_SCORE 达标口径，沿用 composition 真源阈值）",
        severity="分数 <0.3 fatal；<0.5 error；<0.8 warning",
        failure_cause="主体中心偏离三分线交点，构图重心不稳",
        repair_direction="微调构图让主体中心落到三分线交点附近（不替模型选参数）",
        evidence_grade="production",
        sample_requirements={
            "good": "composition.py rule_of_thirds 分量 ≥ 0.8，主体位于三分线交点附近",
            "bad": "composition.py rule_of_thirds 分量 < 0.8，主体中心明显偏离",
            "ambiguous": "分数恰在 0.8 边界且主体居中属有意构图，需人工复核",
        },
    ),
    MetricSpec(
        name="balance",
        layer="geometry",
        granularity="Frame",
        inputs="composition.py 的 balance 分量读数（多主体投影重心的左右分布）",
        measurement="直接取 composition.py balance 分量归一化分数（0..1）",
        target="≥ 0.8（PASS_SCORE 达标口径，沿用 composition 真源阈值）",
        severity="分数 <0.3 fatal；<0.5 error；<0.8 warning",
        failure_cause="多主体挤向一侧，画面重心偏离中央稳定区",
        repair_direction="左右重新平衡人物位置，让画面重心回到中央稳定区（不替模型选参数）",
        evidence_grade="production",
        sample_requirements={
            "good": "composition.py balance 分量 ≥ 0.8，多主体重心居中稳定",
            "bad": "composition.py balance 分量 < 0.8，主体挤向一侧",
            "ambiguous": "分数恰在 0.8 边界且单侧挤压属有意构图，需人工复核",
        },
    ),
    MetricSpec(
        name="occlusion",
        layer="geometry",
        granularity="Frame",
        inputs="composition.py 的 occlusion 分量读数（主体射线可见比例与遮挡归因）",
        measurement="直接取 composition.py occlusion 分量归一化分数（0..1）",
        target="≥ 0.8（PASS_SCORE 达标口径，沿用 composition 真源阈值）",
        severity="分数 <0.3 fatal；<0.5 error；<0.8 warning",
        failure_cause="主体关键部位被前景/他人遮挡，射线可见比例不足",
        repair_direction="移开机位或调整遮挡物，让被挡主体关键部位恢复可见（不替模型选参数）",
        evidence_grade="production",
        sample_requirements={
            "good": "composition.py occlusion 分量 ≥ 0.8，关键部位可见比例达标",
            "bad": "composition.py occlusion 分量 < 0.8，关键部位被遮挡",
            "ambiguous": "分数恰在 0.8 边界且遮挡属于有意层次，需人工复核",
        },
    ),
    MetricSpec(
        name="framing",
        layer="geometry",
        granularity="Frame",
        inputs="composition.py 的 framing 分量读数（主体投影是否完整在画内）",
        measurement="直接取 composition.py framing 分量归一化分数（0..1）",
        target="≥ 0.8（PASS_SCORE 达标口径，沿用 composition 真源阈值）",
        severity="分数 <0.3 fatal；<0.5 error；<0.8 warning",
        failure_cause="主体被画面边缘截断或未按声明景别完整入画",
        repair_direction="收紧景别或重新构图，让主体完整回到画内并符合景别预期（不替模型选参数）",
        evidence_grade="production",
        sample_requirements={
            "good": "composition.py framing 分量 ≥ 0.8，主体完整入画且景别符合预期",
            "bad": "composition.py framing 分量 < 0.8，主体被边缘截断或景别不符",
            "ambiguous": "分数恰在 0.8 边界且截断属有意构图，需人工复核",
        },
    ),
)


# --------------------------------------------------------------------------- #
# 层内索引与查找
# --------------------------------------------------------------------------- #
#: 六层 -> 本层指标名（保持 LAYERS 声明顺序；每项定义只出现一次）。
LAYER_METRICS: Dict[str, Tuple[str, ...]] = {
    layer: tuple(spec.name for spec in METRIC_REGISTRY if spec.layer == layer)
    for layer in LAYERS
}

#: 指标名 -> MetricSpec。普通 dict 即可：MetricSpec 含 dict 字段（不可哈希），
#: 只作 value 不参与哈希。
METRICS_BY_NAME: Dict[str, MetricSpec] = {
    spec.name: spec for spec in METRIC_REGISTRY
}


# --------------------------------------------------------------------------- #
# 分层分数与总览分（主 SPEC §5.1）
# --------------------------------------------------------------------------- #
def layer_score(weights: Mapping[str, float],
                measurements: Sequence[Measurement]) -> float:
    """计算某一层的 0..100 分数（§5.1）。

    ``weights`` 把本层分量名映射到权重（和 = 1）；``measurements`` 是该层
    实测到的统一测量。**权重表声明但未提供的分量按 0 计**——缺证分量不能
    凭空通过。归一化分数必须是 [0,1] 内的数值；权重和 ≤ 0 时抛错。
    输出 = 加权平均 × 100（按全部声明权重的总和归一）。
    """
    if not weights:
        raise ValueError("layer_score 的权重表不能为空")
    weight_sum = float(sum(weights.values()))
    if weight_sum <= 0.0:
        raise ValueError(f"layer_score 权重和必须为正（当前 {weight_sum}）")
    provided = {m.metric: m.score for m in measurements}
    total = 0.0
    for name, weight in weights.items():
        score = provided.get(name, 0.0)
        if (isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not 0.0 <= score <= 1.0):
            raise ValueError(
                f"分量 {name!r} 的归一化分数超出 [0,1]：{score!r}")
        total += float(weight) * float(score)
    return total / weight_sum * 100.0


def overview_score(layer_scores: Mapping[str, float],
                   weights: Optional[Mapping[str, float]] = None) -> float:
    """总览分（§5.1）：六层加权平均，默认权重取 LAYER_WEIGHTS_DEFAULT。

    ``layer_scores`` 必须恰好覆盖六层且每层在 [0,100] 内；``weights`` 未提供
    时用默认权重表，提供了则必须恰好覆盖六层、各值 > 0 且和为 1。
    """
    resolved = LAYER_WEIGHTS_DEFAULT if weights is None else dict(weights)
    if set(resolved) != set(LAYERS):
        raise ValueError(
            f"overview_score 权重键必须恰好等于六层（当前 {sorted(resolved)}）")
    for name, value in resolved.items():
        if (isinstance(value, bool)
                or not isinstance(value, (int, float))
                or float(value) <= 0.0):
            raise ValueError(
                f"overview_score 权重 {name!r} 必须为正数（当前 {value!r}）")
    if abs(float(sum(resolved.values())) - 1.0) > 1e-9:
        raise ValueError(
            "overview_score 权重和必须等于 1"
            f"（当前 {float(sum(resolved.values()))}）")
    if set(layer_scores) != set(LAYERS):
        raise ValueError(
            "overview_score 层键必须恰好等于六层"
            f"（当前 {sorted(layer_scores)}）")
    for name, value in layer_scores.items():
        if (isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0.0 <= float(value) <= 100.0):
            raise ValueError(
                f"层 {name!r} 分数超出 [0,100]：{value!r}")
    return sum(float(layer_scores[layer]) * float(resolved[layer])
               for layer in LAYERS)


__all__ = [
    "LAYERS", "LAYER_METRICS", "LAYER_WEIGHTS_DEFAULT", "MetricSpec",
    "METRIC_REGISTRY", "METRICS_BY_NAME", "layer_score", "overview_score",
]
