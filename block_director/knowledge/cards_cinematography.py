"""摄影域知识卡（v1.3 诉求 5）。

补齐两件 v1.2 缺的东西：

1. **全类型运镜**——每种给出「怎么动、什么情绪、什么时候用、什么时候别用、
   引擎当前做到什么程度「。``engine_support`` 必须与
   ``cinema/camera_motion.py`` 的 ``MOVEMENT_TYPES`` 一致，
   ``tests/test_knowledge.py`` 会对拍；否则知识库会教模型要求引擎做不到的事。
2. **光位 / 光学 / 机位极限**——白模条件下这些同样决定画面读得出来与否。
"""

from __future__ import annotations

from typing import Tuple

from ..contracts.knowledge import Card
from .card_factory import make_card as _card

_D = "cinematography"

#: 引擎当前实现的运镜（与 cinema/camera_motion.py 的 MOVEMENT_TYPES 对拍）
ENGINE_MOVEMENTS = (
    "dolly_in", "dolly_out", "track_left", "track_right",
    "crane_up", "crane_down", "pan_left", "pan_right",
    "tilt_up", "tilt_down",
)


def _movement(move_id: str, title: str, content: str, keywords, *,
              emotion: str, unit: str, default: float,
              examples: Tuple[str, ...], related: Tuple[str, ...],
              taboo: str = "", planned: bool = False) -> Card:
    "「」运镜卡：``engine_support`` 由**当前引擎**决定，不靠手写。「」"
    implemented = move_id in ENGINE_MOVEMENTS
    support = "implemented" if implemented else "unsupported"
    if taboo:
        # 每张运镜卡都必须写清"什么时候别用"——只讲怎么用的知识
        # 会让模型到处乱用（tests/test_knowledge.py 有对应的断言）。
        content = content + f"禁忌：{taboo}"
    if planned and not implemented:
        content = (content + f"（当前引擎尚未实现该运镜；"
                             f"在支持之前请用最接近的已实现运镜替代，"
                             f"或把运动交给下游视频模型。）")
    return _card(
        f"cine_move_{move_id}", _D, title, content,
        keywords,
        parameters={"amount_unit": unit, "amount_default": default},
        examples=examples, related=related,
        engine_support=support, emotion=emotion,
        tags=[move_id, "运镜", emotion])


_MOVEMENTS: Tuple[Card, ...] = (
    _movement("dolly_in", "推镜（推近）",
              "相机沿光轴靠近主体。景别在运动中收紧，观众被「带向」主体，"
              "注意力与压力同时上升。它是强调与逼近的标准手法；"
              "用在角色做出决定的瞬间最有效。禁忌：没有动机地一直推，"
              "会让画面像在被动放大。",
              ["推", "推镜", "dolly", "推近"], emotion="强调/逼近",
              unit="米", default=1.0,
              examples=("角色说出关键台词时缓慢推近", ),
              related=("cine_shot_size", "cine_move_zoom_in", "perf_tempo")),
    _movement("dolly_out", "拉镜（拉远）",
              "相机沿光轴远离主体，景别在运动中放宽。它把主体重新放回环境中："
              "揭示、疏离、收束都用它。段落收尾时常用来「松手」。"
              "禁忌：拉得太快会把刚建立的紧张感泄掉。",
              ["拉", "拉镜", "dolly out", "拉远"], emotion="揭示/疏离",
              unit="米", default=1.0,
              examples=("说完「我明天就走」后缓缓拉远，露出空荡的房间", ),
              related=("cine_establishing", "perf_emotion", "cine_move_zoom_out")),
    _movement("track_left", "左移（平移）",
              "相机横向平移，保持与主体的距离不变。它与主体的运动形成"
              "平行或反向关系：平行像陪伴，反向像擦肩。"
              "禁忌：平移速度与画面里主体的移动速度打架，观众会眩晕。",
              ["左移", "平移", "track", "横移"], emotion="陪伴/观察",
              unit="米", default=1.0,
              examples=("与角色同速左移，保持中景", ),
              related=("axis_direction", "cine_move_track_right", "block_walk")),
    _movement("track_right", "右移（平移）",
              "与左移镜像。银幕方向感比方向本身更重要：一段戏里左移右移"
              "混用会让观众丢失空间关系，必须与动作轴线一致。",
              ["右移", "平移", "track", "横移"], emotion="陪伴/推进",
              taboo="与左移混用会让观众丢失空间关系；一段戏里只留一个横向方向。",
              unit="米", default=1.0,
              examples=("角色向画右走，相机同向平移", ),
              related=("axis_direction", "cine_move_track_left")),
    _movement("crane_up", "升镜",
              "相机整体上移。它同时改变高度与取景：升到高处会获得全局视角，"
              "情绪从「在场」变成「抽离」。结尾常用它把人物留在画面下方。",
              ["升", "升降", "crane", "上升"], emotion="抽离/宏大",
              taboo="升得太快会把观众甩出场景；情绪没到高点就先升高，会像航拍素材。",
              unit="米", default=1.0,
              examples=("角色倒下后缓缓升起，露出整片战场", ),
              related=("cine_height", "cine_move_crane_down")),
    _movement("crane_down", "降镜",
              "相机整体下移，视角从全局收回到局部，情绪上更「逼近」与「落定」。"
              "与升镜对称使用可以形成一呼一吸。",
              ["降", "升降", "crane", "下降"], emotion="逼近/落定",
              taboo="下降要落在主体身上，否则观众会以为还有别的东西要看。",
              unit="米", default=1.0,
              examples=("从屋顶降到街角，落在主角身上", ),
              related=("cine_height", "cine_move_crane_up")),
    _movement("pan_left", "左摇",
              "机位不动、镜头水平旋转。它像人转头：用来扫描空间、"
              "把新信息带进画面（来人、开门、另一个角色）。"
              "禁忌：摇到一半停下会让观众以为还要继续。",
              ["左摇", "摇镜", "pan"], emotion="扫描/引入",
              unit="度", default=15.0,
              examples=("从左到右扫过市场，最后停在主角身上", ),
              related=("cine_move_pan_right", "cine_eyeline")),
    _movement("pan_right", "右摇",
              "与左摇镜像。摇镜的落点就是「你希望观众看的东西」，"
              "所以摇之前要清楚终点在哪，且终点必须值得这趟移动。",
              ["右摇", "摇镜", "pan"], emotion="扫描/推进",
              taboo="摇到一半停下会让观众误以为还要继续；落点必须值得这趟移动。",
              unit="度", default=15.0,
              examples=("顺着角色的视线摇向门口", ),
              related=("cine_move_pan_left", "cine_pov")),
    _movement("tilt_up", "上摇",
              "机位不动、镜头向上旋转，纵向扫描。仰视的终点会让对象显得"
              "高大、庄严、有压迫；从脚摇到头是最直接的「打量」。",
              ["上摇", "仰", "tilt"], emotion="敬畏/升格",
              taboo="仰视用多了会让所有角色都显得高大，权力关系反而失效。",
              unit="度", default=15.0,
              examples=("从靴子摇到脸，交代反派登场", ),
              related=("cine_height", "cine_move_tilt_down")),
    _movement("tilt_down", "下摇",
              "与上摇镜像。向下摇常用来把注意力交给细节（手、道具、地面），"
              "也用来表达审视、失望或压迫后的落空。",
              ["下摇", "俯", "tilt"], emotion="审视/落寞",
              taboo="下摇别扫过主体以外的空白，否则注意力会被地面抢走。",
              unit="度", default=15.0,
              examples=("从对话中的脸摇到手心里攥着的钱袋", ),
              related=("cine_move_tilt_up", "comp_occlusion")),
    _movement("zoom_in", "变焦推近",
              "机位不动、焦距变长。与推镜的区别是**透视不变**："
              "背景只被放大、不被重新组织，观众会感到「凝视」甚至「盯住」。"
              "禁忌：变焦太快像电子放大，除非刻意要那种业余质感。",
              ["变焦", "zoom", "拉近"], emotion="聚焦/警觉",
              unit="毫米", default=15.0,
              examples=("角色意识到不对时轻推焦段", ),
              related=("cine_lens", "cine_move_dolly_in"), planned=True),
    _movement("zoom_out", "变焦拉远",
              "机位不动、焦距变短，视野变宽。与拉镜的区别同样是透视："
              "变焦拉远会显得「世界突然多出来」，适合喜剧式的揭示。",
              ["变焦", "zoom", "拉远"], emotion="抽离/揭示",
              taboo="变焦拉远会让透视突然变平，与推轨镜头接在一起会露馅。",
              unit="毫米", default=15.0,
              examples=("从人物拉到整条街", ),
              related=("cine_move_dolly_out", "cine_establishing"), planned=True),
    _movement("dolly_zoom", "推拉变焦（眩晕镜头）",
              "相机前推的同时焦距变短（或反之），主体大小不变而透视剧烈变化。"
              "它表达的是一种**心理断裂**：世界在塌陷，人还站在原处。"
              "整场戏最多用一次——滥用会让它变成杂技。",
              ["推拉变焦", "眩晕", "dolly zoom", "vertigo"], emotion="眩晕/失衡",
              taboo="整场戏最多用一次；滥用会把它变成杂技。",
              unit="米", default=1.5,
              examples=("听到噩耗时背景猛地「拉远", ),
              related=("cine_move_zoom_in", "cine_lens", "perf_emotion"),
              planned=True),
    _movement("orbit_cw", "顺时针环绕",
              "相机绕主体做圆弧运动，始终对着主体。环绕把主体「包围」起来，"
              "自带仪式感与宿命感；也常用于把两个角色的关系转成背景。"
              "禁忌：绕一整圈会让人失去方向，通常 30°~120° 就够。",
              ["环绕", "弧线", "orbit", "绕"], emotion="审视/仪式",
              unit="度", default=60.0,
              examples=("两人对峙时绕半圈，把位置关系交代清楚", ),
              related=("cine_move_orbit_ccw", "axis_multi", "block_ensemble"),
              planned=True),
    _movement("orbit_ccw", "逆时针环绕",
              "与顺时针镜像。环绕方向决定「谁转到前景」，"
              "因此要与对话的主导权一致：谁在说话，谁就该转到前景。",
              ["环绕", "弧线", "orbit", "绕"], emotion="审视/仪式",
              taboo="绕圈超过 180° 会让观众失去左右方向；绕完要回到明确的一侧。",
              unit="度", default=60.0,
              examples=("说话人绕到画面前景", ),
              related=("cine_move_orbit_cw", "block_pattern"), planned=True),
    _movement("crane_arc_up", "上升弧",
              "相机沿弧线上升：一边抬高一边改变水平角度。它比纯升镜更有"
              "「告别「的意味——既拉开距离，又回头看了一眼。",
              ["上升弧", "摇臂", "crane arc"], emotion="升华/告别",
              taboo="弧线上升时不要再叠变焦，两件事一起做，观众一件都读不出来。",
              unit="度", default=45.0,
              examples=("角色离场后弧线升起，留他在画面角落", ),
              related=("cine_move_crane_up", "cine_move_orbit_cw"), planned=True),
    _movement("crane_arc_down", "下降弧",
              "与上升弧镜像。下降弧把观众「放进」场景，适合开场揭示空间。",
              ["下降弧", "摇臂", "crane arc"], emotion="揭示/压迫",
              taboo="下降弧的终点必须落在主体上，否则像摄影机掉下去了。",
              unit="度", default=45.0,
              examples=("从屋檐斜落进人群", ),
              related=("cine_move_crane_down", "cine_establishing"), planned=True),
    _movement("whip_pan_left", "左甩镜",
              "极快的水平旋转，中间过程故意模糊。它的作用是**连接与冲击**："
              "把两个空间或两个节拍硬接在一起，也常用来制造喜剧的节奏断点。",
              ["甩镜", "whip pan", "快速摇"], emotion="冲击/突变",
              taboo="两次落点都必须值得看，否则观众只记得晃了一下。",
              unit="度", default=90.0,
              examples=("从一个人甩到另一个人", ),
              related=("cine_move_pan_left", "perf_tempo"), planned=True),
    _movement("whip_pan_right", "右甩镜",
              "与左甩镜像。甩镜的两次落点必须都值得看，"
              "否则观众只记得「晃了一下」。",
              ["甩镜", "whip pan", "快速摇"], emotion="冲击/突变",
              taboo="甩镜之间不要插静止镜头，节奏一断就没有冲击力。",
              unit="度", default=90.0,
              examples=("顺着冲击方向甩到反应镜头", ),
              related=("cine_move_whip_pan_left", "axis_direction"), planned=True),
    _movement("handheld", "手持",
              "相机由人扛着，带高频微抖与不稳定构图。它把「有人在现场「"
              "这件事直接写进画面，因此纪实、混乱、紧张都用它。"
              "禁忌：安静的对话用手持，会让观众误以为有危险在逼近。",
              ["手持", "handheld", "抖动", "纪实"], emotion="混乱/纪实",
              unit="强度", default=0.5,
              examples=("冲突升级时切手持跟随", ),
              related=("cine_movement", "cine_move_steadicam", "perf_tempo"),
              planned=True),
    _movement("steadicam", "斯坦尼康",
              "稳定器跟随：相机能走路、能上楼，却几乎没有抖动。"
              "它让观众「贴着角色走」，同时又不像手持那样焦虑——"
              "长镜头与沉浸式跟随的主力。",
              ["斯坦尼康", "steadicam", "稳定器", "跟随"], emotion="沉浸/跟随",
              taboo="稳定器不等于没有运动动机；无目的的漂移最像故障。",
              unit="米", default=2.0,
              examples=("跟着角色走过整条市场", ),
              related=("cine_move_follow_subject", "cine_movement"),
              planned=True),
    _movement("follow_subject", "跟拍",
              "相机跟随主体移动，主体在画面里的相对位置保持不变。"
              "跟拍的重点是「主体在动」，背景的流动负责提供速度与空间。",
              ["跟拍", "跟随", "follow", "背影"], emotion="陪伴/被动观察",
              taboo="主体停下来时相机也要停，否则会越过被摄者。",
              unit="米", default=2.0,
              examples=("跟在奔跑者背后穿过人群", ),
              related=("cine_move_lead_subject", "block_movement"),
              planned=True),
    _movement("lead_subject", "前导",
              "相机在主体前方后退着走，主体朝镜头前进。它比跟拍更主动："
              "观众先看到主体的表情与前方空间。",
              ["前导", "倒退跟", "lead"], emotion="引导/主动揭示",
              taboo="倒退走注意脚下与障碍，撞到道具会让整条镜头作废。",
              unit="米", default=2.0,
              examples=("角色边走边说，相机在前方后退", ),
              related=("cine_move_follow_subject", "cine_eyeline"), planned=True),
    _movement("push_through", "穿越推进",
              "相机穿过一个前景（门、窗、人群）进入场景。它同时完成"
              "「转场「与」进入「，是段落之间的天然粘合剂。",
              ["穿越", "推入", "push through", "转场"], emotion="进入/侵入",
              taboo="穿越的前景不能是主体的一部分，否则观众看不清是谁进来了。",
              unit="米", default=2.0,
              examples=("推开布帘进入市场", ),
              related=("cine_establishing", "comp_lines"), planned=True),
)

_GRAMMAR: Tuple[Card, ...] = (
    _card("cine_move_motivation", _D, "运镜必须有动机",
          "任何一次运动都要能回答「为什么动」：跟随角色、揭示新信息、"
          "或强化情绪。三者都答不上来的运动，在参考视频里会被视频模型"
          "当成内容学走——它会把「镜头在飘」理解成「场景在动」。"
          "宁可不动的固定镜头，也不要有动机不明的运动。",
          ["运镜动机", "为什么动", "固定机位"],
          rules=("R014",),
          examples=("角色起身 → 上摇跟随；揭示门口来人 → 摇向门口"),
          related=("cine_movement", "cine_move_speed", "cine_static_contrast")),
    _card("cine_move_speed", _D, "运镜速度与情绪强度",
          "同一种运动，速度快慢改变的是情绪强度而不是方向：慢速=观察与"
          "沉浸，中速=叙述，快速=冲击与慌乱。切换速度要有理由，"
          "否则观众读到的是「摄影师手抖」。",
          ["运镜速度", "快慢", "节奏"],
          parameters={"slow": 0.5, "normal": 1.0, "fast": 2.5},
          examples=("同一个推镜：0.5 倍速是凝视，2.5 倍速是惊吓"),
          related=("cine_move_motivation", "perf_tempo")),
    _card("cine_move_stacking", _D, "运镜叠加的禁忌",
          "推 + 摇 + 升降同时进行会把空间关系彻底搅乱，观众既读不出景别"
          "变化也读不出方向。一次只做一件事是安全默认；确需组合时，"
          "选两个正交自由度（例如推 + 升降），并保证主体始终在画。",
          ["运镜组合", "叠加", "禁忌"],
          examples=("推近时不要再摇；需要同时改变高度就用升降弧"),
          related=("cine_move_motivation", "cine_movement")),
    _card("cine_static_contrast", _D, "运动与静止的对比",
          "整场戏都有运动，等于整场都没有运动。固定镜头是运动的参照系："
          "在它之后出现的第一次推镜，会被读成「事情开始了」。"
          "把固定镜头留给铺垫，把运动留给转折。",
          ["固定镜头", "对比", "节奏"],
          examples=("三个固定镜头铺垫 → 第四个快速推镜引爆"),
          related=("cine_move_motivation", "perf_tempo", "cine_duration")),
    _card("cine_move_and_axis", _D, "运镜与轴线的交互",
          "运镜会移动机位，因此会改变它在轴线哪一侧。环摇、横移、"
          "环绕都可能把相机送到轴线的另一侧——运动越轴是合法的换侧手段，"
          "前提是**观众看得到这次移动**。硬切式的换侧仍然禁止。",
          ["运动越轴", "轴线", "换侧", "环绕"],
          rules=("R001",),
          examples=("让相机随角色走过桌面，自然绕到另一侧"),
          related=("axis_cross", "cine_move_orbit_cw", "axis_direction")),
)

_LIGHT_AND_OPTICS: Tuple[Card, ...] = (
    _card("cine_light_direction", _D, "光位与情绪",
          "白模没有材质，光位几乎就是全部的情绪：正面光平、无秘密；"
          "侧光（45°）立体、有戏剧性；逆光把主体变成剪影、强调轮廓；"
          "顶光制造眼窝阴影，天然带压迫。选光位等于选这场戏的态度。",
          ["光位", "侧光", "逆光", "顶光", "光线"],
          parameters={"key_angle_deg": {"flat": 0, "three_quarter": 45,
                                        "side": 90, "back": 180}},
          examples=("审讯用顶光；回忆用柔和侧光"),
          related=("cine_light_contrast", "comp_occlusion")),
    _card("cine_light_contrast", _D, "明暗对比与藏信息",
          "让画面的一部分留在暗处，是「不必展示全部」的表达。"
          "白模里最有效的做法是保留大面积受光面 + 一块明确的阴影，"
          "而不是把整体调暗——整体变暗只会让人看不清形体。",
          ["明暗", "对比", "阴影", "低调"],
          examples=("半张脸在光下半张在阴影里 → 心里有事"),
          related=("cine_light_direction", "perf_emotion")),
    _card("cine_color_temperature", _D, "色温与情绪",
          "暖色（3200K 附近）亲近、怀旧、安全；冷色（5600K 以上）疏离、"
          "理性、危险。**同一场戏里色温的改变**比绝对值更有叙事力："
          "从暖到冷往往意味着关系的破裂。",
          ["色温", "暖色", "冷色", "色调"],
          parameters={"warm_k": 3200, "daylight_k": 5600},
          examples=("开场暖黄 → 冲突后转冷蓝"),
          related=("cine_light_direction", "cine_light_contrast")),
    _card("cine_depth_of_field", _D, "景深与焦平面",
          "景深是「让观众看哪里」的强制手段：浅景深把背景变成色块，"
          "焦点在哪就等于台词给谁；大景深则要求观众自己在画面里找重点。"
          "白模下景深靠光圈与焦距模拟，实拍感的浅景深通常在特写里用。",
          ["景深", "焦点", "虚化", "浅景深"],
          examples=("双人对话用浅景深，焦点在说话人身上"),
          related=("cine_lens", "comp_lead_room", "cine_eyeline")),
    _card("cine_lens_compression", _D, "长焦压缩与广角纵深",
          "长焦把前后景压在一起，空间变扁、人物像被「贴」在一起——"
          "适合亲密与压迫；广角把前后景拉开，纵深感强、移动显得更快——"
          "适合环境交代与走位。换焦距必须同时重新解算距离（§10.6），"
          "否则景别会跟着一起变。",
          ["焦距", "压缩", "广角", "纵深", "透视"],
          parameters={"compression_lens": 85, "wide_lens": 35},
          examples=("拥挤的压迫感用 85mm；市场纵深用 35mm"),
          related=("cine_lens", "cine_move_dolly_zoom", "cine_shot_size")),
    _card("cine_aspect_ratio", _D, "画幅比与构图",
          "画幅比决定「横向能放多少关系、纵向能放多少高度」："
          "16:9 适合并置与横向运动，2.39:1 强化孤立与横向疏离，"
          "9:16 把纵向关系推到前台（站立、高度差、垂直压迫）。"
          "切换画幅比必须是全局决定，不能在段落中间偷换。",
          ["画幅比", "宽银幕", "竖屏", "构图"],
          parameters={"hd16x9": 1.778, "scope": 2.39, "vertical": 0.5625},
          examples=("竖屏叙事把人物高度差当构图主轴"),
          related=("cine_shot_size", "comp_thirds")),
    _card("cine_low_angle", _D, "低机位",
          "机位低于被摄者视线时，对象显得高大、强势、有威胁；"
          "用在权力关系上是直白的语法。极限低机位（贴地）会同时改变"
          "景别与地面占比，要注意别把主体顶到画外。",
          ["低机位", "仰拍", "强势", "压迫"],
          examples=("反派登场用低机位，主角用平视或略高"),
          related=("cine_height", "cine_high_angle", "cine_dutch_angle")),
    _card("cine_high_angle", _D, "高机位",
          "机位高于被摄者视线时，对象显得渺小、被动、被围观。"
          "俯拍到极限会变成地图式构图，人物变成画面里的符号——"
          "这时观众看的是局势，不再是表情。",
          ["高机位", "俯拍", "渺小", "局势"],
          examples=("战败后俯拍孤立的身影"),
          related=("cine_height", "cine_low_angle", "cine_establishing")),
    _card("cine_dutch_angle", _D, "荷兰角（倾斜构图）",
          "相机水平线倾斜，画面里的垂直物全部歪掉。它表达失衡、"
          "危险、精神异常。因为太显眼，只能在关键节拍上用一两个镜头，"
          "用多了会变成风格噪音。",
          ["荷兰角", "倾斜", "失衡", "dutch"],
          parameters={"typical_deg": 10.0, "extreme_deg": 30.0},
          examples=("角色崩溃的一个镜头给 15° 倾斜"),
          related=("cine_low_angle", "perf_emotion")),
    _card("cine_eye_level", _D, "平视机位",
          "机位与被摄者眼睛同高，是最中性的态度：既不仰视也不俯视。"
          "对话戏的默认选择就是平视——它让观众与角色平等地待在一起。",
          ["平视", "眼高", "中性"],
          parameters={"eye_z": 1.10},
          examples=("两人坦诚交谈的整段都用平视"),
          related=("cine_height", "cine_eyeline", "cine_low_angle")),
)

_MOVEMENT_TITLES = {
    "dolly_in": "推近", "dolly_out": "拉远", "track_left": "左移",
    "track_right": "右移", "crane_up": "升", "crane_down": "降",
    "pan_left": "左摇", "pan_right": "右摇", "tilt_up": "上摇",
    "tilt_down": "下摇",
}


def _index_card() -> Card:
    """运镜总表：让模型一眼看到有哪些运镜、哪几种现在就能用。"""
    implemented = "、".join(_MOVEMENT_TITLES[key] for key in ENGINE_MOVEMENTS)
    planned = "、".join(card.title for card in _MOVEMENTS
                        if card.engine_support != "implemented")
    return _card(
        "cine_move_index", _D, "运镜总表与当前能力",
        f"引擎**当前已实现**的运镜：{implemented}。"
        f"剧本或计划里出现这些之外的运镜时，要么改用最接近的已实现项，"
        f"要么把运动交给下游视频模型——不要让引擎假装做到了。"
        f"计划实现但尚未落地的：{planned}。",
        ["运镜", "总表", "能力", "支持"],
        parameters={"implemented": list(ENGINE_MOVEMENTS)},
        examples=("想用「环绕」但目前不支持 → 用侧向横移 + 景别变化近似"),
        related=("cine_movement", "cine_move_motivation"),
        engine_support="implemented", emotion="—",
        tags=["运镜", "总表", "能力协商"])


CARDS: Tuple[Card, ...] = _MOVEMENTS + _GRAMMAR + _LIGHT_AND_OPTICS + (
    _index_card(),)

