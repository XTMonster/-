"""调度域知识卡（v1.3 诉求 5）。

补群戏与群众调度——这是「约 30 名路人」那类剧本最需要的知识，
也是 v1.2 完全没有覆盖的部分。
"""

from __future__ import annotations

from typing import Tuple

from ..contracts.knowledge import Card
from .card_factory import make_card as _card

_D = "blocking"

CARDS: Tuple[Card, ...] = (
    _card("block_crowd_purpose", _D, "群众先问「来干什么」",
          "背景人群不是装饰：他们要**穿过**画面、**停下来**交易、"
          "或者**围观**事件。三种目的对应三种走位方向与密度。"
          "没有目的的群众只会站在原地抖动，看起来像故障。",
          ["群众", "路人", "背景人群", "目的"],
          examples=("穿行的人群用横向流；围观的人群用朝向事件聚集"),
          related=("block_crowd_flow", "block_ensemble")),
    _card("block_crowd_flow", _D, "群众流的方向与银幕方向",
          "群众的主要流动方向应当与主角的银幕方向**相反或垂直**，"
          "这样主角才会从人群里「凸显」出来。群众与主角同向同速时，"
          "主角会被淹没在流里。",
          ["群众", "走向", "银幕方向", "流动"],
          rules=("R001",),
          examples=("市场人群横向流动，主角纵向穿过"),
          related=("axis_direction", "block_crowd_purpose", "comp_depth_layers")),
    _card("block_crowd_density", _D, "群众密度与镜头景别",
          "同一群人，近景里两三个人就够「拥挤」，全景里需要十几个才读得出"
          "\「人海\」。密度要按镜头景别调整，而不是全场固定——"
          "按全景的密度去填近景，角色会被挤得无法表演。",
          ["群众", "密度", "景别", "人海"],
          parameters={"close_shot": 3, "mid_shot": 8, "wide_shot": 20},
          examples=("特写里背景只需 2~3 个虚化人影"),
          related=("block_crowd_purpose", "cine_shot_size")),
    _card("block_depth_staging", _D, "把角色放到不同纵深",
          "两个角色一前一后（而不是并排）时，画面天然产生层次与关系："
          "前面的人挡着后面的、后面的人被压住。纵深调度也让相同景别"
          "产生不同的心理距离——这比额外的镜头便宜得多。",
          ["纵深", "前后", "层次", "调度"],
          examples=("说话人靠前一步，听众留在后面半步"),
          related=("comp_depth_layers", "block_distance", "perf_status")),
    _card("block_proxemic_shift", _D, "距离变化即关系变化",
          "角色之间距离的**变化**比绝对值更有表现力：靠近是亲密或威胁，"
          "退开是防御或疏离。给每一段关系标一个起始距离与结束距离，"
          "中间的变化就是这场戏的曲线。",
          ["距离", "靠近", "退开", "关系"],
          parameters={"intimate": 0.6, "social": 1.8, "public": 3.0},
          examples=("争吵从 2.0m 逼近到 0.8m，再退回到 2.5m"),
          related=("block_distance", "perf_status", "block_movement")),
    _card("block_focal_point", _D, "画面的焦点人物",
          "每一镜都要有一个焦点人物：所有其他人的视线、朝向、"
          "身体开口都指向他。焦点人物由「谁在被看」决定，"
          "而不是由谁在说话——听者被注视时也是焦点。",
          ["焦点", "注意力", "视线", "主次"],
          examples=("众人看着他说话 → 他是焦点；他沉默时焦点转到发问者"),
          related=("comp_eye_trace", "perf_listen", "block_ensemble")),
    _card("block_entrance_motivation", _D, "进场要有理由",
          "新角色进场前必须给一个「注意」的信号：声音（脚步）、"
          "他人的视线转移、或者门本身动了一下。没有信号的出现会让观众"
          "把注意力花在确认「他是谁」上，而不是剧情上。",
          ["进场", "注意", "信号", "入场"],
          examples=("脚步声明先行 → 众人抬头 → 来人全景"),
          related=("block_entrance", "perf_gaze", "axis_neutral")),
    _card("block_exit_follow", _D, "退场要有人送",
          "角色离场后，画面里要有人**目送**他离开，"
          "否则观众不知道这事算不算结束。目送镜头同时承担了"
          "\「这次离开意味着什么\」的解释工作。",
          ["退场", "离场", "目送", "结束"],
          examples=("角色出门 → 留下的人看着门的方向停一拍"),
          related=("block_entrance_motivation", "perf_listen")),
    _card("block_seating", _D, "坐姿与座位关系",
          "谁坐主位、谁坐侧面、谁站着，本身就是权力关系。"
          "坐下之后角色高度降到约 0.2 单位（§9.1），"
          "机位与视线高度都要跟着调整，否则会出现「坐着却像站着」的比例错误。",
          ["座位", "坐姿", "权力", "高度"],
          parameters={"sit_height": 0.2, "stand_height": 0.4},
          examples=("主位面门而坐，客位侧对"),
          related=("perf_posture", "block_prop", "cine_height")),
    _card("block_prop_business", _D, "用小道具承载对话",
          "让角色在说话时做一件事（擦杯子、数钱、拧瓶盖），"
          "对话就有了节拍与停顿的借口，也避免了「两个人干站着说话」。"
          "道具的状态必须跨镜头连续（§7.9 连贯性台账）。",
          ["道具", "小动作", "节拍", "连续性"],
          rules=("R002",),
          examples=("讲到关键句时手停下来，再继续擦"),
          related=("block_prop", "perf_business", "perf_tempo")),
    _card("block_territory", _D, "地盘与侵入",
          "每个角色都有「自己的那一块」画面空间。别人进入这块空间，"
          "冲突就立刻成立——不需要台词。用地面标记、道具边界、"
          "或简单的间距就能把「地盘」做出来。",
          ["地盘", "侵入", "空间", "冲突"],
          examples=("对方跨过桌子这条线 → 冲突升级"),
          related=("block_proxemic_shift", "axis_180", "perf_status")),
    _card("block_handoff", _D, "交接动作的调度",
          "递东西、交钱、传话这类交接把两个人的动作联成一个动作，"
          "是群戏里最有效的连接件。机位要让两个人的手同时可见，"
          "并且交接的两端必须是同一次拍摄里的连续动作。",
          ["交接", "传递", "连接", "动作"],
          examples=("一个镜头里完成：手伸出 → 接住 → 收回"),
          related=("axis_action_match", "block_prop_business")),
    _card("block_blocking_for_lens", _D, "按镜头反推走位",
          "走位不是先想好再找机位，而是**为镜头设计**：知道这一镜要用 "
          "35mm 的全景，就该让角色在纵向拉开距离；知道要用 85mm 的特写，"
          "就该让两个人在同一条轴线上。先有镜头方案，再安排站位。",
          ["走位", "镜头", "焦距", "设计"],
          examples=("为 85mm 特写把两人安排在一条轴上，避免透视压缩错位"),
          related=("cine_lens", "block_depth_staging", "cine_move_dolly_in")),
    _card("block_comfort_zone", _D, "给演员留出可动范围",
          "角色周围要留出至少一个身位（≈0.5 单位）的自由空间，"
          "否则任何表演动作都会撞到道具或走出画面。白模里的常见事故是"
          "把角色摆在桌子边缘，一动就穿模（R002）。",
          ["可动范围", "空间", "穿模", "安全距离"],
          rules=("R002",),
          parameters={"clearance": 0.5},
          examples=("角色与摊位之间至少留 0.5 单位"),
          related=("block_prop_business", "comp_occlusion")),
    _card("block_ensemble_focus_rotation", _D, "群戏的焦点轮转",
          "群戏不能一直对着一个人。焦点轮转的规则是："
          "**谁改变了局面，镜头就给谁**——说话的人、做出动作的人、"
          "或者被迫做出反应的人。轮转要有节奏，平均分配会让每个角色"
          "都变得不重要。",
          ["群戏", "焦点", "轮转", "节奏"],
          examples=("甲挑衅 → 乙 → 丙插话 → 回到甲"),
          related=("block_focal_point", "block_ensemble", "cine_coverage")),
)
