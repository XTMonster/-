"""表演域知识卡（v1.3 诉求 5）。

白模没有表情，情绪只能靠姿态、节奏与视线传达。这里补齐「行动动词/
潜台词/反应「这类真正指导表演的条目。
"""

from __future__ import annotations

from typing import Tuple

from ..contracts.knowledge import Card
from .card_factory import make_card as _card

_D = "performance"

CARDS: Tuple[Card, ...] = (
    _card("perf_objective", _D, "用行动动词代替情绪词",
          "\「他很生气\」不是可执行的指令；\「他把杯子推开\」才是。"
          "把情绪翻译成**动作**：想说服、想赶走、想藏起来、想试探。"
          "动作动词能被解算成姿态与节奏，情绪词不能。",
          ["行动动词", "目标", "表演", "可执行"],
          examples=("\"他很生气\" → \"他推开杯子并且站起来\""),
          related=("perf_emotion", "perf_subtext", "perf_beat_change")),
    _card("perf_beat_change", _D, "节拍与转折点",
          "一个镜头里至少要有一个节拍变化：角色改变主意、得到新信息、"
          "或者做出决定。没有节拍的镜头只是「在动」，有节拍的镜头才「发生」。"
          "节拍通常落在镜头的后 2/3，给观众留出预期的时间。",
          ["节拍", "转折", "变化", "节奏"],
          examples=("沉默 2 秒 → 听见远处声音 → 决定转身"),
          related=("perf_tempo", "cine_duration", "perf_objective")),
    _card("perf_listen", _D, "倾听也是表演",
          "对话里最有信息量的是**听的人**。听者的反应（眼神、点头、"
          "停下手上的事）告诉观众这句话造成了什么影响。"
          "只拍说话的人，对话就变成朗读。",
          ["倾听", "反应", "对话", "正反打"],
          examples=("对方说完 → 听者停下手里的动作 0.5 秒才回答"),
          related=("axis_reverse_shot", "perf_micro", "block_focal_point")),
    _card("perf_subtext", _D, "潜台词与表面动作的落差",
          "台词说的和角色真正想要的往往不一样。表演的层次来自这个落差："
          "嘴上说\「没关系\」，手却把杯子握紧。"
          "白模靠一个不一致的微动作就能把潜台词做出来。",
          ["潜台词", "言外之意", "落差", "微动作"],
          examples=("说\"我很好\"的同时后退半步"),
          related=("perf_objective", "perf_business", "perf_status")),
    _card("perf_status", _D, "地位博弈",
          "两个人的相对地位会通过姿态持续交换：谁先移开视线、"
          "谁先低头、谁站着谁坐着、谁的身体更占空间。"
          "地位是可以**反转**的，反转的那一刻就是这场戏的高潮。",
          ["地位", "权力", "博弈", "反转"],
          examples=("一直低头的人抬起头直视 → 地位反转"),
          related=("block_seating", "perf_gaze", "perf_proxemic_reaction")),
    _card("perf_business", _D, "小动作（business）",
          "给角色安排一个与对话无关的日常动作（擦汗、系鞋带、数钱），"
          "表演立刻有了真实感与停顿点。动作的节奏要与台词错开："
          "在台词的重音上停手，比一直动更有效。",
          ["小动作", "business", "真实感", "停顿"],
          examples=("数钱的手在听到\"发财\"时停住"),
          related=("block_prop_business", "perf_micro", "perf_tempo")),
    _card("perf_breath", _D, "呼吸与身体起伏",
          "呼吸是最低成本的「活着的证据」：急促=紧张或兴奋，"
          "屏住=恐惧或期待，长出一口气=释然。"
          "白模里用躯干的小幅起伏与肩线变化表达，幅度不必大但要连续。",
          ["呼吸", "起伏", "紧张", "释然"],
          examples=("听到坏消息前屏住，之后长出一口气"),
          related=("perf_emotion", "perf_tempo")),
    _card("perf_walk_rhythm", _D, "走路节奏与性格",
          "同一个人，走得快慢与步幅改变性格读法：急步小碎步=焦虑，"
          "大步慢走=从容或压迫，走走停停=犹豫。"
          "走路的速度必须与镜头时长对得上，否则会「走到一半被切」。",
          ["走路", "节奏", "步幅", "性格"],
          parameters={"walk_speed": 0.05, "run_speed": 0.10},
          examples=("犹豫的人走三步停一次"),
          related=("block_walk", "perf_tempo", "cine_duration")),
    _card("perf_proxemic_reaction", _D, "对方靠近时的反应",
          "有人靠近时，角色的第一反应永远是身体先动（后退/后仰/侧身），"
          "然后才是语言。先说话再动身体，观众读到的就是「没被冒犯」。"
          "所以靠近与反应的时机必须对齐。",
          ["靠近", "反应", "后退", "时机"],
          examples=("对方逼近 0.3m → 身体先后仰，再开口"),
          related=("block_proxemic_shift", "perf_status", "perf_emotion")),
    _card("perf_group_reaction", _D, "群戏里的反应层次",
          "一群人同时做同一个反应（同时转头、同时笑）看起来像排练过。"
          "做法是**错开**：领先者先动，其余人跟上半拍，"
          "还可以有一个人完全不动——那个不动的人最有戏。",
          ["群体反应", "错开", "层次", "群戏"],
          examples=("一个人先抬头 → 两个跟上 → 一个始终不动"),
          related=("block_ensemble_focus_rotation", "perf_tempo")),
)
