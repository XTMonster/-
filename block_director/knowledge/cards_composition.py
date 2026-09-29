"""构图域知识卡（v1.3 诉求 5）。

v1.2 只有三分/头顶/视线留白/重心/遮挡/景别匹配/引导线七条。
这里补齐「构图法全集」里真正会影响判断的部分。
"""

from __future__ import annotations

from typing import Tuple

from ..contracts.knowledge import Card
from .card_factory import make_card as _card

_D = "composition"

CARDS: Tuple[Card, ...] = (
    _card("comp_golden_ratio", _D, "黄金分割",
          "黄金分割（≈1.618）与三等分构图都在做同一件事：把主体从正中挪开，"
          "让画面产生张力。两者差别很小，实用上的区别是黄金分割更靠近"
          "中心一点。不要为了「用黄金分割」而放弃已经成立的构图——"
          "两者的视觉收益几乎一样，反复调整只会浪费时间。",
          ["黄金分割", "黄金比", "构图法"],
          parameters={"phi": 1.618, "center_bias": 0.382},
          examples=("主体落在 0.382 处即黄金分割位"),
          related=("comp_thirds", "comp_balance")),
    _card("comp_symmetry", _D, "对称构图",
          "左右（或上下）对称的画面自带秩序、仪式与压迫。"
          "对称适合表达「没有出口」的处境（对峙、审判、仪式），"
          "也常用于表现角色的僵局。破坏对称的那一下——一个人动了——"
          "会被放大成整个画面的转折。",
          ["对称", "秩序", "仪式", "僵局"],
          examples=("两人分坐长桌两端 → 其中一人站起来，对称被打破"),
          related=("comp_balance", "axis_multi", "perf_status")),
    _card("comp_negative_space", _D, "负空间",
          "大面积留白不是为了好看，而是把「缺席」表达出来：空椅子、"
          "空床、空荡的走廊。负空间要**有内容**（能读出是谁不在），"
          "否则只是没拍满。",
          ["负空间", "留白", "缺席", "空镜"],
          examples=("刚离开的人留下的空椅占画面三分之二"),
          related=("comp_lead_room", "comp_visual_weight", "cine_establishing")),
    _card("comp_depth_layers", _D, "前中后景的层次",
          "把画面分成前景（框/遮挡）、中景（主体）、后景（环境）三层，"
          "纵深立刻成立，观众的视线也有落点。白模里最经济的做法是"
          "在前景放一个盒子当遮挡/画框，主体在中景，背景留出环境。",
          ["前中后景", "层次", "纵深", "前景"],
          examples=("前景门框 → 中景角色 → 后景街道"),
          related=("comp_lines", "comp_occlusion", "cine_depth_of_field")),
    _card("comp_horizon", _D, "地平线位置",
          "地平线压在下三分之一会强调天空（渺小、被压）；"
          "抬到上三分之一会强调地面（踏实、环境感）；"
          "正好居中则平静、对称、缺少导向。地平线是构图里最容易被忽略的"
          "一个大元素，先决定它在哪，再谈别的。",
          ["地平线", "水平线", "构图"],
          parameters={"low": 0.66, "middle": 0.50, "high": 0.33},
          examples=("人物渺小 → 地平线压到画面下方"),
          related=("comp_depth_layers", "cine_establishing")),
    _card("comp_visual_weight", _D, "视觉重量",
          "亮、大、清晰、运动、人脸都「更重」。构图平衡不是两边像素相等，"
          "而是两边的视觉重量相等——所以一个亮色小物体可以平衡一个"
          "暗色大物体。判断标准：把画面看成天平，不是看面积。",
          ["视觉重量", "平衡", "重心"],
          examples=("左侧暗色人群可以平衡右侧亮色单人"),
          related=("comp_balance", "comp_negative_space")),
    _card("comp_eye_trace", _D, "视线引导",
          "观众的视线总被这三样东西吸引：人脸、运动、高对比。"
          "构图的任务是让这三样指向你想让观众看的地方。"
          "如果画面里出现了两个高对比点，观众会来回跳——"
          "那就是一场没有主角的镜头。",
          ["视线引导", "eye trace", "注意力"],
          examples=("用街道的透视线把视线推向画面深处的角色"),
          related=("comp_lines", "comp_graphic_contrast")),
    _card("comp_graphic_contrast", _D, "图形对比",
          "形状本身就能叙事：圆对尖（柔和对攻击）、大对小（权力）、"
          "密集对疏离（拥挤对孤独）。把主体放进与它属性相反的图形环境里，"
          "性格会被读得更清楚。",
          ["图形", "对比", "形状", "性格"],
          examples=("开阔广场里一个蜷缩的圆润身影 → 孤独"),
          related=("comp_eye_trace", "comp_scale_cues")),
    _card("comp_repetition", _D, "重复与节奏",
          "画面里重复出现的元素（一排摊位、一串窗户）建立节奏，"
          "而打破重复的那一个就是视觉重点。这是最省事的「指哪打哪」："
          "把主体放在节奏里唯一的例外位置。",
          ["重复", "节奏", "打破", "重点"],
          examples=("一排相同的摊位中只有一个亮着灯"),
          related=("comp_eye_trace", "cine_establishing")),
    _card("comp_frame_in_frame", _D, "画框中的画框",
          "用门、窗、拱廊把主体框起来，既能压缩背景杂乱，"
          "又能暗示处境（被囚禁、被窥视、被观察）。画框本身越闭合，"
          "压迫感越强。",
          ["画框", "门框", "窗户", "窥视"],
          examples=("从门缝里看角色，框外全黑"),
          related=("comp_lines", "comp_depth_layers", "cine_depth_of_field")),
    _card("comp_center_composition", _D, "居中构图的用法",
          "居中被当成禁忌是误解：它稳定、直接、有对称的压迫力。"
          "适合证件式的正面交代、对称对峙、以及「面无表情」的荒诞感。"
          "居中的问题不在于它，而在于它太容易被用来逃避构图决定。",
          ["居中", "正面", "对称"],
          examples=("角色直视镜头说话时用居中"),
          related=("comp_symmetry", "comp_thirds")),
    _card("comp_diagonal", _D, "对角线构图",
          "把主体或运动线放在对角线上，画面立刻获得动势与纵深。"
          "对角线是「不安定」的构图：适合冲突、奔跑、以及正在发生的事情。"
          "相反的，水平线用来表达停下来的状态。",
          ["对角线", "动势", "纵深"],
          examples=("奔跑的角色沿对角线冲向画面深处"),
          related=("comp_lines", "cine_move_follow_subject")),
    _card("comp_triangle", _D, "三角形构图",
          "三个人（或两个人加一个道具）构成三角形是最稳的群戏构图："
          "顶点给出主次，底边给出关系。三角形的顶点应该落在说话的人身上，"
          "焦点转移时让三角形的顶点跟着换。",
          ["三角形", "三人", "群戏", "顶点"],
          examples=("三人在帐篷下交谈，说话者占据顶点位置"),
          related=("axis_group_scene", "block_pattern", "comp_visual_weight")),
    _card("comp_scale_cues", _D, "尺度参照",
          "观众判断大小靠的是参照物，不是绝对尺寸。"
          "想让一个东西显得巨大，就在旁边放一个人；"
          "想让一个人显得渺小，就让他站在巨大的结构旁。"
          "白模里这意味着要保留哪怕一个可识别的尺度参照（门、桌子、台阶）。",
          ["尺度", "参照", "大小", "比例"],
          examples=("巨浪旁留下一块小小的码头 → 立刻读出体量差"),
          related=("comp_visual_weight", "cine_establishing")),
    _card("comp_isolation", _D, "孤立构图",
          "把主体与周围的图像元素隔开（间距、色调差、景深），"
          "孤立感就出现了。它不需要台词：一个人与其他所有人之间"
          "多出来的那点距离，就是整场戏的意思。",
          ["孤立", "隔离", "疏离"],
          examples=("合影时主角与两侧各留一道空隙"),
          related=("comp_negative_space", "block_distance", "perf_emotion")),
    _card("comp_clutter", _D, "背景杂乱的处理",
          "背景杂乱不是靠「虚化」解决的，而是靠位置：把杂乱的元素从主体"
          "头部两侧挪开（抬高机位、横移、换角度）。虚化只能减轻，"
          "不能消除与主体重叠的线条。",
          ["背景", "杂乱", "重叠", "虚化"],
          examples=("把灯柱挪到主体肩膀外，而不是让它在头顶"),
          related=("comp_occlusion", "cine_depth_of_field", "cine_height")),
    _card("comp_widescreen_grouping", _D, "宽画幅里的多人排布",
          "横向空间越大，越容易排成「一字长蛇阵」而失去关系。"
          "宽画幅里的多人应该沿**纵深**分层，或者用间距分组"
          "（谁和谁站得近，谁被隔开），而不是平均铺开。",
          ["宽画幅", "多人", "分组", "纵深"],
          examples=("五人对峙分成 2-1-2 三组，而不是五人一排"),
          related=("block_ensemble", "comp_depth_layers", "axis_group_scene")),
    _card("comp_thirds_break", _D, "什么时候该打破构图默认值",
          "默认值不是戒律。需要表达压迫、僵局、正面审视时，"
          "居中与对称比默认更对；需要表达失控时，倾斜与越界的构图"
          "甚至更好。关键是「知道自己在打破什么」，而不是随手乱放。",
          ["三分法", "打破", "居中", "倾斜"],
          examples=("审判场景故意全部居中"),
          related=("comp_thirds", "comp_center_composition", "comp_symmetry")),
    _card("comp_headroom_extremes", _D, "顶到边与留过多的极端",
          "头顶贴边（几乎切到）表达被压、喘不过气；头顶留一大片表达"
          "下落、失重、被抛弃。两种极端都是工具，但都必须**刻意**——"
          "默认状态下的「顶留白 3%~12%「才是安全区。",
          ["头顶留白", "极端", "压迫", "失重"],
          parameters={"safe_min": 0.03, "safe_max": 0.12},
          examples=("被逼到墙角 → 头顶贴边"),
          related=("comp_headroom", "cine_high_angle", "perf_emotion")),
    _card("comp_foreground_blocking", _D, "前景遮挡作为构图手段",
          "前景出现部分遮挡物（柱子、肩膀、货物）会让画面有「偷看」的"
          "现场感，也能把观众放进场景里。但它与「遮挡事故」只有一线之隔："
          "关键是遮挡物**不覆盖**主体的脸与关键动作。",
          ["前景", "遮挡", "偷看", "现场感"],
          rules=("R002",),
          examples=("肩部入画占三成，但脸完整可见"),
          related=("cine_ots", "comp_occlusion", "comp_depth_layers")),
)
