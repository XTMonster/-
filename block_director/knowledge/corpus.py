"""五大知识域的结构化条目（执行文档 v1.2 §6.2 / §6.3）。

所有数值都以**引擎实现为准**，避免最危险的一种漂移——知识库教模型用一套数，
引擎实际按另一套算：

- 景别画面高度 / 焦距 / 机位高度 → ``block_director/cinema/framing.py`` 的
  ``SHOT_FRAME``（§10.5 的实现修正表）；
- 构图分项与权重 → §10.4；
- 动作冲突表 → §9.7；
- 角色尺寸、移动速度 → §9.1 与 §21.5 的配置默认值。

``tests/test_knowledge.py::test_corpus_matches_the_engine`` 会把这些数字与
``framing.py`` / ``config.py`` 的实际值对拍，任何一边改动都会立刻红。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..contracts.knowledge import Card
from ..cinema.framing import CHEST_Z, EYE_Z, SHOT_FRAME
from .generated import load_generated as _load_generated
from .generated import merge_cards as _merge_cards
from .card_factory import as_list as _as_list
from .card_factory import make_card as _card
from .cards_axis import CARDS as _AXIS_CARDS
from .cards_blocking import CARDS as _BLOCKING_CARDS
from .cards_cinematography import CARDS as _CINEMATOGRAPHY_CARDS
from .cards_composition import CARDS as _COMPOSITION_CARDS
from .cards_performance import CARDS as _PERFORMANCE_CARDS

DOMAINS: Tuple[str, ...] = (
    "cinematography", "axis_theory", "composition", "blocking", "performance",
    "storyboard", "editing", "anime", "production",
)

DOMAIN_LABELS: Dict[str, str] = {
    "cinematography": "摄影（景别 / 焦距 / 机位 / 运动）",
    "axis_theory": "轴线理论（180°/30°/越轴）",
    "composition": "构图（三分法 / 留白 / 重心 / 遮挡）",
    "blocking": "调度（站位 / 运动 / 距离 / 群戏）",
    "performance": "表演（情绪 / 节奏 / 微动作）",
    "storyboard": "分镜（镜头清单 / 段落节拍 / 画面说明）",
    "editing": "剪辑（节奏 / 连贯 / 转场）",
    "anime": "动画（作画节奏 / 演出 / 套路）",
    "production": "制片（流程 / 预算 / 交付）",
}

#: 九宫格的**冻结顺序**（与 ``framing.SHOT_FRAME`` 的键同源）。
_SHOT_ORDER: Tuple[str, ...] = ("ECU", "CU", "MCU", "MS", "MLS", "LS", "ELS")


def _frame_heights() -> Dict[str, float]:
    """景别画面高度：直接从 ``framing.SHOT_FRAME`` 取（v1.4 P10）。"""
    return {key: SHOT_FRAME[key].frame_height for key in _SHOT_ORDER}


def _target_heights() -> Dict[str, float]:
    return {key: SHOT_FRAME[key].target_z for key in _SHOT_ORDER}


def _lenses() -> Dict[str, float]:
    return {key: SHOT_FRAME[key].lens for key in _SHOT_ORDER}


def _cinematography_digest() -> str:
    """摄影域摘要：数字全部派生自 ``SHOT_FRAME`` / profile，不手抄。

    §1.6 的量错项（digest 里写着 "CU 0.75" 而 ``SHOT_FRAME["CU"]`` 是别的
    值）就是这么来的：**没有断言对拍**的手抄数字迟早会教旧几何。
    """
    heights = " / ".join(f"{key} {SHOT_FRAME[key].frame_height:.2f}"
                         for key in _SHOT_ORDER)
    lenses = "/".join(str(int(SHOT_FRAME[key].lens)) for key in _SHOT_ORDER)
    return (f"景别越紧画面高度越小：{heights}；建议焦距 {lenses}mm。"
            f"机位高度：眼睛 {EYE_Z:.2f}、胸口 {CHEST_Z:.2f}。")


# RAG 整体关闭时用的"顶层摘要卡"（§6.1 的 digest 兜底，≤2000 token）
DOMAIN_DIGESTS: Dict[str, str] = {
    "cinematography": _cinematography_digest(),
    "axis_theory": "180° 规则：相邻镜头必须留在两人连线的同一侧；30° 规则：相邻"
                   "同景别镜头机位角度变化须 > 30°。合法越轴靠运动、中性镜头或"
                   "骑轴过渡。",
    "composition": "构图六项加权：遮挡 0.25、视线留白 0.20、头顶 0.15、三分法 "
                   "0.15、重心 0.15、景别匹配 0.10。遮挡最致命，先解决。",
    "blocking": "站位决定心理距离：亲密 <0.6、社交 1.2~2.0、公众 >3.0（Blender "
                "单位）。移动必须给目标位置与起止帧，速度 walk 0.05 / run 0.10 "
                "单位每帧。",
    "performance": "Q 版角色靠头部角度与躯干倾斜表达情绪；动作要有快慢对比；对白"
                   "配微动作（点头/摇头/转头）。walk_to 与 fall_down 冲突，必须先"
                   "停下再摔。",
}


CARDS: Tuple[Card, ...] = (
    # ----------------------------------------------------------------- 摄影
    _card(
        "cine_shot_size", "cinematography", "九种景别与画面高度",
        "景别不是称呼，而是一组可执行的取景数字。本项目的权威定义来自 "
        "framing.py 的 SHOT_FRAME：画面高度越小越紧。ECU 只拍眼睛/局部，"
        "CU 拍头部，MCU 到胸，MS 到腰，MLS 到膝，LS 全身，ELS 人物只占一小块。"
        "景别跳跃要有依据：从 LS 直接切 ECU 只在强调情绪反转时使用。",
        ["景别", "取景", "shot size", "画面高度", "ECU", "MS", "ELS"],
        rules=("R009",),
        parameters={"frame_height": _frame_heights()},
        examples=("对话主力用 MCU/MS", "交代空间用 LS/ELS，情绪爆点用 CU/ECU"),
        related=("cine_lens", "cine_height", "comp_framing"),
    ),
    _card(
        "cine_lens", "cinematography", "焦距与透视",
        "焦距同时改变取景范围与空间感。长焦（85mm）压缩纵深、让背景贴近主体，"
        "适合特写与情绪隔离；标准（50mm）接近人眼，是对话主力；广角（35/24mm）"
        "强化纵深与空间关系，适合走位与环境交代。改焦距而不改机位会同时改变"
        "景别，需要重新解算距离（§10.6）。",
        ["焦距", "镜头", "透视", "长焦", "广角", "85mm", "50mm", "35mm"],
        parameters={"lens": _lenses()},
        examples=("特写用 85mm 压缩背景", "室内走位用 35mm 保留纵深"),
        related=("cine_shot_size", "cine_movement", "comp_framing"),
    ),
    _card(
        "cine_height", "cinematography", "机位高度",
        f"机位高度是除景别外最影响观感的变量。眼睛高度（{EYE_Z:.2f}）中立、平等；"
        f"胸口高度（{CHEST_Z:.2f}）常用在 MLS/LS；低机位让角色显得强势、压迫；高机位"
        "俯拍显得渺小、被动。对准高度同样重要：特写要对准脸部，全景要覆盖"
        "脚到头顶。",
        ["机位高度", "仰拍", "俯拍", "眼睛高度", "胸口高度"],
        parameters={"camera_z": {"eye": EYE_Z, "chest": CHEST_Z},
                    "target_z": _target_heights()},
        examples=("反派登场用低机位", "受挫镜头用高机位俯拍"),
        related=("cine_shot_size", "comp_headroom", "cine_lens"),
    ),
    _card(
        "cine_movement", "cinematography", "镜头运动的六种基本型",
        "推（靠近，强调）、拉（远离，揭示）、摇（旋转，扫描空间）、移（平移，"
        "跟随空间关系）、跟（跟随主体）、升降（高度变化）。运动必须有动机："
        "要么跟随角色动作，要么揭示新信息。无动机的运动在参考视频里会被视频"
        "模型当成内容学走，慎用。",
        ["运镜", "推", "拉", "摇", "移", "跟", "升降", "camera movement"],
        examples=("角色起身 → 跟随上摇", "揭示门口来人 → 缓慢摇向门口"),
        related=("cine_coverage", "cine_establishing", "block_movement"),
    ),
    _card(
        "cine_ots", "cinematography", "过肩镜头（OTS）",
        "OTS 让前景角色的肩部占据画面一角，焦点落在对手的脸上。它同时给出"
        "两个人的空间关系与一方的视角态度，是正反打的标准构件。机位应略高于"
        "目标肩部、靠近前景角色的后侧，避免肩部挡住对方的脸。",
        ["过肩", "OTS", "正反打", "肩部"],
        examples=("A 说话 → OTS 从 B 肩后拍 A", "反打时保持视线高度一致"),
        related=("axis_180", "cine_eyeline", "cine_pov"),
    ),
    _card(
        "cine_pov", "cinematography", "主观镜头（POV）",
        "POV 把机位放在角色的眼睛位置，观众看到角色所看。使用前必须先交代"
        "「谁在看」（前一个镜头给出角色与视线方向），否则观众会迷失。POV 之后"
        "通常需要回到客观机位确认角色的反应。",
        ["主观", "POV", "视点", "视线"],
        examples=("角色望向窗外 → POV 空镜 → 回到角色脸部反应"),
        related=("cine_eyeline", "cine_ots", "axis_neutral"),
    ),
    _card(
        "cine_eyeline", "cinematography", "视线匹配与视线高度",
        "正反打时，A 看向画右，B 就要看向画左，且两人的视线高度必须一致（同高"
        "或按身高差调整）。视线错位（一人看画左上、另一人看画右下）会让观众"
        "感到两人没在对话。角色看画外时，留白方向必须与视线方向一致。",
        ["视线", "eyeline", "正反打", "视线匹配"],
        rules=("R001",),
        examples=("矮个子抬头看 → 对手镜头机位略高"),
        related=("cine_ots", "comp_lead_room", "axis_180"),
    ),
    _card(
        "cine_duration", "cinematography", "镜头时长预算",
        "镜头时长必须装得下它内部的全部对白，并在末尾留出收尾余量。中文语速按"
        "3 字/秒估算，情绪会改变语速（生气更快、悲伤更慢），因此时长要按语速"
        "倍率调整后再加上余量帧。宁可略长，也不要让对白被切掉。",
        ["时长", "对白", "语速", "收尾余量", "duration"],
        rules=("R011",),
        parameters={"chinese_cps": 3.0, "english_wps": 2.5,
                    "dialogue_tail_frames": 12},
        examples=("12 字对白 ≈ 4 秒 ≈ 96 帧，再加 12 帧余量"),
        related=("perf_tempo", "axis_30"),
    ),
    _card(
        "cine_establishing", "cinematography", "建立镜头",
        "开场或换场时先用 ELS/LS 交代空间、人物位置与光环境，再进入中近景的"
        "对话。没有建立镜头，观众会在后续特写中失去方位感，正反打也容易越轴。"
        "建立镜头通常也是确立轴线的镜头。",
        ["建立镜头", "establishing", "开场", "空间交代"],
        examples=("咖啡馆全景交代两人隔桌 → 进入对话中景"),
        related=("axis_180", "cine_shot_size", "block_pattern"),
    ),
    _card(
        "cine_coverage", "cinematography", "覆盖与可剪辑性",
        "一个段落至少要有主镜（master）与必要的反打/插入镜，保证剪辑时能改变"
        "节奏。相同景别的相邻镜头要有 >30° 的角度变化，否则会出现「跳切」。"
        "覆盖不足会让后期无路可退，覆盖过多则成本浪费。",
        ["覆盖", "coverage", "主镜", "剪辑", "跳切"],
        rules=("R010",),
        examples=("对话段落：master + A 特写 + B 特写 + 手部插入"),
        related=("axis_30", "cine_movement", "cine_ots"),
    ),

    # ----------------------------------------------------------------- 轴线
    _card(
        "axis_180", "axis_theory", "180° 轴线规则",
        "把两个对话角色连成一条线，机位只能待在这条线的同一侧。越到另一侧，"
        "观众会看到两人交换了左右位置，空间感瞬间崩掉。本项目的轴线由第一个"
        "镜头确立，后续镜头必须保持同一侧。",
        ["180度", "轴线", "越轴", "同侧", "axis"],
        rules=("R001",),
        examples=("首镜从小明左侧拍 → 后续都留在这条线左侧"),
        related=("axis_30", "axis_cross", "axis_multi"),
    ),
    _card(
        "axis_30", "axis_theory", "30° 规则",
        "相邻两个镜头如果景别相同，机位角度变化必须大于 30°；否则两个画面"
        "过于相似，剪辑时会出现「跳帧」感。要么改变角度 >30°，要么改变景别至少"
        "一档（例如 MCU → MS）。",
        ["30度", "30°", "跳切", "角度变化"],
        rules=("R010",),
        examples=("两个 MCU 相邻 → 把第二个机位转 45° 或改成 MS"),
        related=("axis_180", "cine_coverage", "axis_neutral"),
    ),
    _card(
        "axis_cross", "axis_theory", "合法越轴的四种方式",
        "需要换侧时，用这些手段让观众跟得上：(1) 运动越轴——角色在镜头内移动"
        "到另一侧；(2) 中性镜头——机位落在轴线上，没有左右信息；(3) 骑轴"
        "过渡——从一个中性镜头穿过去；(4) 插入无关镜头（空镜/道具）作为缓冲。"
        "直接硬切到另一侧是禁忌。",
        ["越轴", "越轴之后", "越过轴线", "换到另一侧", "运动越轴", "中性镜头", "骑轴",
         "插入镜头", "硬切", "轴线", "左右互换", "换边", "视线轴"],
        rules=("R001",),
        examples=("角色起身走向对面 → 机位随动作绕到另一侧"),
        related=("axis_neutral", "axis_180", "axis_action"),
    ),
    _card(
        "axis_multi", "axis_theory", "多人轴线",
        "三人以上时先选一条主轴线（通常是主导对话的两人连线），第三人按他的"
        "阵营归属到轴的某一侧。不要为每一对人都画一条轴，那会互相矛盾。群戏"
        "里保持主轴线稳定，靠景别与站位区分层次。",
        ["多人", "群戏", "主轴线", "阵营"],
        rules=("R001",),
        examples=("三人对峙 → 以主角与对手连线为轴，第三人在主角侧后方"),
        related=("axis_180", "block_ensemble", "axis_direction"),
    ),
    _card(
        "axis_action", "axis_theory", "动作轴线",
        "当主体在运动（走路、开车、追逐）时，轴线由运动方向决定：朝画右运动的"
        "人，下一个镜头也要朝画右。动作轴线比对话轴线更容易被忽略，尤其在"
        "多机位覆盖时。",
        ["动作轴线", "运动方向", "追逐"],
        rules=("R001",),
        examples=("A 从左走向右 → 反打镜头里 A 仍向右"),
        related=("axis_direction", "axis_180", "block_movement"),
    ),
    _card(
        "axis_direction", "axis_theory", "银幕方向一致性",
        "所有镜头里的运动方向必须构成连贯的几何关系：A 向右，B 向左，观众读作"
        "「相向而行」；两个都向右则读作「同向追赶」。方向一旦打乱，观众会以为"
        "人物瞬移。这条规则与轴线互为表里。",
        ["银幕方向", "方向", "相向", "同向"],
        rules=("R001",),
        examples=("两人奔向对方 → 一个向右一个向左"),
        related=("axis_action", "axis_180", "block_walk"),
    ),
    _card(
        "axis_neutral", "axis_theory", "中性镜头作为过渡",
        "机位正好落在轴线上（正面或正后方）时，画面里没有明确的左右信息，"
        "因此中性镜头可以作为跨轴的桥梁：中性镜头之前在一侧，之后可以在另一侧。"
        "注意中性镜头不可滥用，连续多个会失去空间感。",
        ["中性镜头", "正面", "过渡", "跨轴"],
        examples=("越过某人肩膀正视 → 中性镜头 → 转到另一侧"),
        related=("axis_cross", "axis_30", "cine_pov"),
    ),

    # ----------------------------------------------------------------- 构图
    _card(
        "comp_thirds", "composition", "三分法",
        "把画面横竖各三等分，主体放在交点或线上比居中更有张力。单主体镜头"
        "放在三分交点上时，重心会自然偏向一侧——本项目的平衡项对主体数量做了"
        "死区处理，因此单人放在交点不会被误扣分。",
        ["三分法", "三分线", "交点", "rule of thirds"],
        parameters={"weight": 0.15},
        examples=("单人特写眼睛落在上三分线"),
        related=("comp_balance", "comp_lead_room", "comp_lines"),
    ),
    _card(
        "comp_headroom", "composition", "头顶留白",
        "头顶留白应控制在画面高度的 3%~12%：太小显得憋闷、像要被切掉；太大"
        "显得画面空旷、主体下坠。特写与全景的合适值不同，特写可以略小。",
        ["头顶留白", "headroom", "留白"],
        parameters={"min_ratio": 0.03, "max_ratio": 0.12, "weight": 0.15},
        examples=("CU 头顶留白约 5%"),
        related=("cine_height", "comp_framing", "comp_thirds"),
    ),
    _card(
        "comp_lead_room", "composition", "视线留白",
        "角色看向某个方向时，画面上要在他视线前方留出空间，否则观众会感到"
        "「撞墙」。留白方向必须与视线方向一致，这也是视线匹配的另一半。"
        "权重 0.20，仅次于遮挡。",
        ["视线留白", "lead room", "留白", "看向"],
        parameters={"weight": 0.20},
        examples=("角色看向画右 → 画面右侧留出更多空间"),
        related=("cine_eyeline", "comp_thirds", "comp_balance"),
    ),
    _card(
        "comp_balance", "composition", "画面重心",
        "画面重心不能偏塌：主体与背景重量要大致均衡。单人主体加死区后可居中，"
        "多人镜头则要避免所有人都挤在一边。重心问题常常与留白问题同时出现。",
        ["重心", "平衡", "balance", "偏塌"],
        parameters={"weight": 0.15},
        examples=("两人对话 → 分列两侧而不是挤在左边"),
        related=("comp_thirds", "comp_lead_room", "block_ensemble"),
    ),
    _card(
        "comp_occlusion", "composition", "遮挡检测",
        "主体被前景物体挡住是最致命的构图问题，因此权重最高（0.25）。本项目的"
        "遮挡检测用相机到角色关键点的射线求交（§17.5）：只要关键点被挡，该项"
        "评分归零。修复优先级也是第一位的——先把人拍清楚，再谈构图美感。",
        ["遮挡", "occlusion", "挡板", "射线"],
        parameters={"weight": 0.25},
        rules=("R002",),
        examples=("桌子挡住了坐着的角色 → 抬高机位或挪开道具"),
        related=("comp_framing", "comp_balance", "block_prop"),
    ),
    _card(
        "comp_framing", "composition", "景别与主体占比匹配",
        "画面里主体的占比必须与声明的景别一致：说是特写就不能拍到半身，说是"
        "全景就必须从头到脚。占比不匹配时，观众读到的情绪强度会与导演意图"
        "错位。该项权重 0.10，但它常是景别写错的信号。",
        ["景别匹配", "主体占比", "framing"],
        parameters={"weight": 0.10},
        rules=("R009",),
        examples=("声明 CU 却只拍到胸口 → 重新解算距离"),
        related=("cine_shot_size", "cine_lens", "comp_headroom"),
    ),
    _card(
        "comp_lines", "composition", "引导线与框架构图",
        "用环境中的线条（门框、走廊、桌面边缘）把观众视线引向主体，或用前景"
        "框（门、窗）把主体包起来。框架构图能强化纵深，也能自然地遮掉杂乱"
        "背景。与遮挡的区别：框架是设计，遮挡是事故。",
        ["引导线", "框架构图", "纵深", "前景"],
        examples=("从门框内拍角色 → 天然画框"),
        related=("comp_thirds", "comp_occlusion", "cine_lens"),
    ),

    # ----------------------------------------------------------------- 调度
    _card(
        "block_pattern", "blocking", "站位模式",
        "常见站位有三种：对峙（面对面，冲突感强）、并肩（同向，同盟感）、"
        "三角（三人或两人加一个道具，最稳定且便于多机位）。站位一旦确定，"
        "轴线也基本确定，因此站位要最先决定。",
        ["站位", "调度", "对峙", "并肩", "三角"],
        examples=("谈判场景用对峙站位", "并肩站位用于共同面对威胁"),
        related=("axis_180", "block_distance", "block_ensemble"),
    ),
    _card(
        "block_movement", "blocking", "运动调度要有动机",
        "角色移动必须有理由：走向对方、去拿东西、退开躲避。无动机的走位会让"
        "参考视频看起来像在随机漂移。移动要给目标位置与起止帧，并且同一角色的"
        "动作不得时间重叠。",
        ["调度", "走位", "动机", "移动"],
        rules=("R003",),
        examples=("争吵时后退半步 → 用 walk_to 给目标位置"),
        related=("block_walk", "block_distance", "perf_conflict"),
    ),
    _card(
        "block_distance", "blocking", "角色距离与心理关系",
        "距离就是关系：亲密距离 <0.6 单位，社交距离 1.2~2.0，公众距离 >3.0。"
        "角色之间距离的**变化**比绝对值更有表现力——靠近是威胁或亲密，退开是"
        "防御或疏离。",
        ["距离", "心理", "亲密", "社交", "公众"],
        parameters={"intimate": 0.6, "social_min": 1.2, "social_max": 2.0,
                    "public": 3.0},
        examples=("争吵升级 → 两人从 2.0 逼近到 0.8"),
        related=("block_pattern", "block_movement", "perf_emotion"),
    ),
    _card(
        "block_ensemble", "blocking", "群戏调度",
        "群戏先定主轴与阵营，再给每人一个清晰的画面层次（前/中/后景），避免"
        "所有人挤在同一平面上。用景别区分主次：说话者给 MCU，倾听者给 MLS。"
        "群戏的镜头数不要太多，否则轴线难保一致。",
        ["群戏", "多人", "层次", "阵营"],
        rules=("R001",),
        examples=("四人桌 → 说话者中近景，其余留中远景层次"),
        related=("axis_multi", "block_pattern", "comp_balance"),
    ),
    _card(
        "block_entrance", "blocking", "进场与退场",
        "新角色进场要先给一个「注意」的镜头（声音、门开、他人视线），再给"
        "进场者的镜头；退场则相反，让对方视线跟随。进场会改变轴线的重心，"
        "必要时用中性镜头过渡。",
        ["进场", "退场", "门", "视线"],
        examples=("门开 → 众人抬头 → 来人全景"),
        related=("axis_neutral", "block_ensemble", "cine_establishing"),
    ),
    _card(
        "block_prop", "blocking", "道具交互（代理模式）",
        "道具交互用代理模式：桌子、椅子、门先按盒子创建，坐/推/拿等动作通过"
        "角色姿态体现。交互动作要和道具位置对齐，否则角色会坐在空气里。"
        "道具状态要写进连贯性台账，跨镜头保持一致。",
        ["道具", "交互", "坐", "推", "拿"],
        rules=("R002",),
        examples=("坐下 → 身体高度降到 0.2，与椅面高度对齐"),
        related=("perf_posture", "block_distance", "comp_occlusion"),
    ),
    _card(
        "block_walk", "blocking", "画线规划移动",
        "移动用「画线」方式规划：给定起点、目标位置与起止帧，由路径平滑与"
        "简化（Catmull-Rom + RDP，§17.1/§17.2）生成关键帧。速度默认 "
        "walk 0.05、run 0.10 单位/帧；距离除以速度就是所需帧数，不够就是设计错误。",
        ["走位", "画线", "路径", "速度"],
        parameters={"walk_speed": 0.05, "run_speed": 0.10, "blend_frames": 6},
        examples=("走 2.0 单位 ≈ 40 帧（walk）"),
        related=("block_movement", "axis_action", "perf_conflict"),
    ),

    # ----------------------------------------------------------------- 表演
    _card(
        "perf_emotion", "performance", "Q 版情绪表达",
        "白模角色没有面部表情，情绪只能靠姿态传达：开心抬头、沮丧低头并微"
        "含胸、愤怒前倾、恐惧后仰。头部角度与躯干倾斜的组合就是「表情」。"
        "幅度要够大，否则在参考视频里读不出来。",
        ["情绪", "表演", "姿态", "低头", "前倾"],
        examples=("沮丧 → 头部前倾 20° + 身体下沉"),
        related=("perf_gaze", "perf_tempo", "block_distance"),
    ),
    _card(
        "perf_tempo", "performance", "动作节奏与对比",
        "动作要有快慢对比：长镜头里持续匀速的运动会显得呆板，加入停顿、加速"
        "或反转才有呼吸感。关键动作（转身、拍桌、起身）应放在镜头的中后段，"
        "给观众心理预期。",
        ["节奏", "停顿", "加速", "时长"],
        examples=("沉默 2 秒 → 突然拍桌 → 停顿"),
        related=("cine_duration", "perf_micro", "perf_emotion"),
    ),
    _card(
        "perf_micro", "performance", "对白微动作",
        "说话时配微动作能显著提升可信度：点头表示认同、摇头表示否定、转头"
        "表示注意转移。微动作幅度要小于主要动作，并且不要与对白时长打架——"
        "点头的节奏应落在语句的重音上。",
        ["微动作", "点头", "摇头", "转头", "对白"],
        examples=("对方说完 → 轻轻点头 0.5 秒"),
        related=("perf_gaze", "perf_tempo", "cine_duration"),
    ),
    _card(
        "perf_gaze", "performance", "注视与转移",
        "注视方向传达关系：直视表示对抗或亲密，回避表示心虚或退让，垂眼表示"
        "顺从。视线转移是情绪的转折点，值得用一个镜头或一次头部动作来强调。",
        ["注视", "视线", "回避", "转移"],
        examples=("被质问 → 视线下移避开对方"),
        related=("cine_eyeline", "perf_emotion", "perf_micro"),
    ),
    _card(
        "perf_posture", "performance", "坐与立的身体高度",
        "站立时身体高度回到 0.4；坐下后降到约 0.2（下蹲 0.2 单位）。坐/立"
        "必须成对使用：先 sit 后 stand 才能精确复原，只 sit 不 stand 会让角色"
        "在后续镜头里一直保持坐姿。起立与落座各有自己的节奏，不要压缩成"
        "一帧。",
        ["坐", "立", "高度", "姿态"],
        parameters={"stand_height": 0.4, "sit_height": 0.2, "sit_drop": 0.2},
        examples=("坐下 30 帧 → 说话 → 起立 24 帧"),
        related=("block_prop", "perf_conflict", "perf_tempo"),
    ),
    _card(
        "perf_conflict", "performance", "动作冲突与合法组合",
        "四层（base/body/head/legs）可并行，但有些组合语义矛盾必须禁止："
        "walk/run 与 fall_down 冲突（摔倒前要先停下），fall_down 与 jump 冲突，"
        "同层动作互斥要排队。冲突时工具会返回明确错误，按提示改而不是绕过。",
        ["冲突", "动作组合", "摔倒", "走路", "jump"],
        rules=("R003",),
        examples=("要摔倒 → 先结束 walk_to，再 fall_down"),
        related=("block_movement", "perf_posture", "perf_tempo"),
    ),
)


#: v1.2 的基础语料 + v1.3 按域扩充的部分。
#: 分模块是为了让每个域的内容能独立演进；``cards_by_domain`` 与检索都按
#: ``DOMAINS`` 过滤，因此模块拼接顺序不影响检索结果。
#: P14-1：九域扩容（§2.3c 的 K3、§2.3d 的 T7）——只补新增四个域的摘要，
#: 原有五个域的文案一字不改。
DOMAIN_DIGESTS.update({
    "storyboard": "分镜先定轴线再定机位；段落默认四拍＝建立→覆盖→反应→收束；"
                  "每个镜头只承担一条新信息；台词镜按每秒 3 字估时长。",
    "editing": "相邻镜头的机位角度差 > 30°、景别至少拉开一档；视线匹配要求一方"
               "看右侧、另一方从左侧回看；动作在中途切；节奏靠长短对比而不是"
               "一味求快。",
    "anime": "动画的「快」来自前面足够长的静；冲击帧只占 1–2 帧且必须与前一帧"
             "形成强对比；台词、动作、运镜至少错开一项；构图上留白表达被环境"
             "压住或望向远方。",
    "production": "一次运行交付逐镜片段＋首帧＋镜头清单＋提示词＋合片；镜号稳定、"
                  "一镜一台相机；预算显式（调用上限＋墙钟）且超限报错；记录基线"
                  "以支持逐镜返工；留下语料/模型/参数指纹。",
})

_BASE_CARDS: Tuple[Card, ...] = CARDS

_HANDWRITTEN: List[Card] = list(
    _BASE_CARDS + _CINEMATOGRAPHY_CARDS + _AXIS_CARDS
    + _COMPOSITION_CARDS + _BLOCKING_CARDS + _PERFORMANCE_CARDS
)

#: 手写卡（v1.2 基础语料 ＋ v1.3/P10 按域扩充）。语料的域覆盖（K3）算的是
#: **整份语料**，所以 `tools/kb_fetch/import_cards.py` 需要读得到这一份。
HANDWRITTEN_CARDS: Tuple[Card, ...] = tuple(_HANDWRITTEN)

#: P14-1：采集进来的卡片（`knowledge/cards_generated/*.jsonl`）。
GENERATED_CARDS: Tuple[Card, ...] = tuple(_load_generated())

#: T8：生成卡与手写卡撞 id 时以手写卡为准，冲突记录在这里（测试断言为空）。
_MERGED, _COLLISIONS = _merge_cards(_HANDWRITTEN, list(GENERATED_CARDS))
CARDS: Tuple[Card, ...] = tuple(_MERGED)
CARD_ID_COLLISIONS: Tuple[Tuple[str, str], ...] = tuple(_COLLISIONS)


def cards_by_domain(domain: str) -> List[Card]:
    """取某个域的全部条目（域不存在时返回空列表）。"""
    return [card for card in CARDS if card.domain == domain]


def digest_cards() -> List[Card]:
    """构造五张"顶层摘要卡"，供 digest 兜底路径直接注入系统提示。"""
    return [_card(f"digest_{domain}", domain, DOMAIN_LABELS[domain], text,
                  keywords=[domain])
            for domain, text in DOMAIN_DIGESTS.items()]
