"""轴线理论域知识卡（v1.3 诉求 5）。

v1.2 已经有 180°/30°/越轴/多人/动作/方向/中性七条，但缺「实操换算」与
"代价「这类真正会在片场出问题的条目。
"""

from __future__ import annotations

from typing import Tuple

from ..contracts.knowledge import Card
from .card_factory import make_card as _card

_D = "axis_theory"

CARDS: Tuple[Card, ...] = (
    _card("axis_reverse_shot", _D, "正反打的机位落点",
          "正反打是两人对话的主力覆盖，但它最容易越轴：A 与 B 面对面时，"
          "拍 A 的正面机位恰好落在两人连线上。正确做法是把机位**偏离轴线"
          "30°~45°**（干净的过肩或侧面单人），既拿到脸又保住左右关系。"
          "机位正好压在轴线上时属于中性镜头，偶尔用可以，连着用会失去方位。",
          ["正反打", "反打", "对话覆盖", "单人镜头"],
          rules=("R001", "R012"),
          parameters={"off_axis_deg": 30.0},
          examples=("两人相距 1.8m、特写距离 2.4m → 必须偏轴才不会被对方挡住"),
          related=("axis_180", "cine_eyeline", "comp_lead_room")),
    _card("axis_neutral_chain", _D, "连续中性镜头的代价",
          "单个中性镜头（机位落在轴线上）是合法的跨轴桥梁，但连续两个以上"
          "中性镜头会让观众彻底失去左右关系——画面看起来「都在正面」，"
          "人物像并排站着念台词。判定上它是 WARNING 而不是 ERROR，"
          "正是因为它合法但不宜连续。",
          ["中性镜头", "连续", "正面", "方位感"],
          rules=("R001",),
          examples=("中性镜头之后接一个明确侧别，再接中性"),
          related=("axis_neutral", "axis_reverse_shot", "axis_cross")),
    _card("axis_30_degree_practice", _D, "30° 规则的实操换算",
          "30° 不是玄学：两人相距 2m 时，机位沿垂直于连线的方向移动约 1.1m"
          "或沿连线方向变化约 0.5m，就跨过了 30°。景别变化可以替代角度"
          "变化，但只对**相邻且同景别**的镜头成立；两个 MS 挨着且角度只差"
          "10° 就是跳切。",
          ["30度", "跳切", "机位移动", "换算"],
          rules=("R010",),
          parameters={"min_angle_deg": 30.0},
          examples=("2m 距离下横向让开 1.1m 即满足 30°"),
          related=("axis_30", "cine_coverage")),
    _card("axis_cross_cost", _D, "越轴的代价",
          "越轴的后果不是「不专业」，而是观众会以为两个人**换了位置**。"
          "一旦发生，观众需要一次镜头的时间重新建立空间关系，"
          "这期间台词是被浪费的。所以越轴要么别做，要么用一个明确的中性"
          "镜头或运动镜头把它交代清楚。",
          ["越轴", "代价", "空间关系", "观众困惑"],
          rules=("R001",),
          examples=("硬切到另一侧 → 观众以为角色瞬移"),
          related=("axis_cross", "axis_neutral", "axis_direction")),
    _card("axis_group_scene", _D, "群戏里只保留一条主轴",
          "三个人以上时，为每一对人都画一条轴会互相矛盾。正确做法是先选"
          "主轴（通常是主导冲突的两人连线），其余人按阵营挂在轴的某一侧，"
          "再靠景别与前后景层次区分主次。群戏的镜头数要克制，"
          "每多一个机位就多一次破坏轴线的机会。",
          ["群戏", "主轴线", "阵营", "层次"],
          rules=("R001",),
          examples=("三人对峙：主角与对手连线为轴，第三人在主角侧后方"),
          related=("axis_multi", "block_ensemble", "comp_depth_layers")),
    _card("axis_insert_shot", _D, "插入镜头作为缓冲",
          "需要换侧又不想用中性镜头时，插入一个与空间无关的镜头"
          "（手、道具、空镜）可以重置观众的空间记忆，下一镜从新的一侧开始"
          "就不算越轴。插入镜头本身要有信息量，纯装饰的插入会被读成"
          "剪辑事故。",
          ["插入镜头", "缓冲", "换侧", "空镜"],
          examples=("拍一下钱袋 → 之后可以从另一侧拍对话"),
          related=("axis_cross", "axis_neutral_chain")),
    _card("axis_action_match", _D, "动作匹配与轴线",
          "同一动作跨镜头时（开门、坐下、递东西），动作的运动方向必须连续："
          "前一镜角色向画右伸手，下一镜必须从画左入画。动作匹配同时锁住"
          "了轴线与时间，是剪辑能「无痕」的前提。",
          ["动作匹配", "动作轴线", "剪辑", "连续"],
          rules=("R001",),
          examples=("开门的手从画右伸出 → 下一镜门从画左被推开"),
          related=("axis_action", "axis_direction")),
    _card("axis_eyeline_height", _D, "视线高度必须匹配",
          "正反打里两人的视线高度要一致：矮个子抬头看高个子时，"
          "高个子的镜头机位要略高、矮个子的镜头机位要略低，"
          "观众才会觉得他们在看彼此。视线高度错位是最常见的「假对话」来源。",
          ["视线高度", "视线匹配", "正反打", "眼高"],
          rules=("R012",),
          parameters={"max_eye_delta": 0.15},
          examples=("坐着的角色与站着的角色对话，两台相机的眼高都随之调整"),
          related=("cine_eyeline", "axis_reverse_shot", "comp_lead_room")),
    _card("axis_screen_position", _D, "位置与银幕方向的绑定",
          "一场戏里角色的银幕位置要稳定：A 一直在画左、B 一直在画右。"
          "位置一旦交换，观众会先理解成「他们换了座位」，再理解成"
          "「谁赢了这场争执」——后者才是导演的意图，所以不能靠偶然。",
          ["银幕位置", "画左", "画右", "稳定性"],
          rules=("R001",),
          examples=("争执升级时让 A 走到画右、B 退到画左，位置交换即胜负"),
          related=("axis_direction", "comp_balance")),
    _card("axis_ots_stays_on_side", _D, "过肩镜头与轴侧",
          "过肩镜头的机位天然靠近轴线（就在对方的肩膀后面），"
          "因此它近似中性：既给出了空间关系，又不强绑左右。"
          "连续两个过肩（A 肩上拍 B、B 肩上拍 A）是合法的，"
          "但要保证两次的肩部属于不同的对手，且视线方向相反。",
          ["过肩", "OTS", "轴侧", "肩部"],
          rules=("R001",),
          examples=("A 肩上拍 B → B 肩上拍 A，构成完整正反打"),
          related=("cine_ots", "axis_reverse_shot", "axis_neutral")),
)
