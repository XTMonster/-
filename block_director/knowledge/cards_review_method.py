"""构图视觉审核方法论知识卡（spec §15.2 方法臂的知识化草案）。

用户指出：构图域已有大量「构图是什么」的理论卡，缺「怎么执行一次审核」的
方法论。本模块补的是方法论：审核前置条件、检查顺序、判定矩阵、反馈写作、
多主体镜、动态/打斗镜、防幻觉、与处方交互。

方法卡消费方是 **agent**（LLM）：评测台方法臂（``tools/spatial_ruler_ab/``）
把这里的检查清单渲染成提示词注入，将来注册进语料后还会走 ``search_knowledge``
检索注入。因此卡正文是可执行的祈使指令（先…/只…/不…/按…），不是理论重述。

⚠️ 注册状态：本模块**暂不**接入 ``corpus.py::_HANDWRITTEN``（不触发超图重
建），因为正式入库需要重新抽取超图（花 DeepSeek 额度）并重跑门⑥/Q1/E1。
它当前是「评测台方法臂话术的同源草案」：``method.py`` 直接引用这里的检查
清单，确保知识卡与评测臂不会各写一套。整合主链路的边界见
``.scratch/spatial-ruler/spec.md``。

规则号命名空间（用户 2026-10-13 裁决）：方法卡上的 ``rules`` 字段**不给现有
R 编号**——``contracts/rule_catalog.py`` 的 R001–R019 是引擎/合规语义（且被
``tests/test_rule_catalog.py`` 钉死在 18 条、只认 ``R\\d{3}``），而方法卡
描述的是**审核流程**语义，二者不是一回事。方法卡统一引用本模块的独立规则段
``METHOD_RULES``（``MR\\d{3}`` 前缀），单一真源见下。
"""

from __future__ import annotations

from typing import Tuple

from ..contracts.knowledge import Card
from .card_factory import make_card as _card

_D = "composition"

#: 方法域独立规则段（单一真源，供方法卡 ``rules`` 字段引用）。
#: MR 前缀与规则目录的 R\\d{3} 命名空间零重叠：
#: MR001 = 审核前置（固定主主体/景别/动态三前提，缺一先澄清不猜）；
#: MR002 = 处方交互（只接受/拒绝不重写，三项条件全过才接受）。
METHOD_RULES: Tuple[Tuple[str, str, str], ...] = (
    ("MR001", "warning",
     "审核前置：先固定主主体/景别/动态三前提，缺一先用问题澄清，不猜"),
    ("MR002", "error",
     "处方交互：只接受/拒绝不重写；工具存在、过 schema、无内部键三项全过才接受"),
)

#: 方法卡 rules 允许的编号闭集（供测试与未来校验使用）。
METHOD_RULE_IDS = frozenset(rule_id for rule_id, _severity, _summary in METHOD_RULES)

#: 六步检查顺序的单一真源：评测台方法臂（method.py）与知识卡都引用它。
CHECKLIST = (
    "1. 看主体入画",
    "2. 看头部留白",
    "3. 看三分/视线",
    "4. 看重心",
    "5. 看遮挡",
    "6. 看动态",
)


def render_method_checklist() -> str:
    """把检查顺序渲染成可注入提示的可读清单（方法臂话术与卡同源）。"""
    return "\n".join(CHECKLIST)


CARDS: Tuple[Card, ...] = (
    _card(
        "rev_method_preconditions", _D, "审核前置条件：先确认看的是什么",
        "开始构图审核前先固定三件事，否则判定会漂移：① 主主体是谁（多主体镜"
        "以可见最高盒为准，出画者不参与主锚）；② 景别是否比全身更紧（只有此时"
        "头部留白才适用）；③ 是否动态/打斗镜（要不要做第六步）。这三条是审核"
        "的前置步骤，缺一条就先用问题澄清，不猜。",
        ["审核", "前置", "主主体", "景别", "动态"],
        rules=("MR001",),
        examples=("双人镜里一个角色完全出画 → 主锚取画内那个"),
        related=("comp_headroom", "rev_method_order"),
    ),
    _card(
        "rev_method_order", _D, "六步检查顺序",
        "构图审核按固定顺序执行，不要凭整体印象：\n"
        + render_method_checklist() + "\n"
        "先看入画，再看留白、三分/视线、重心、遮挡，动态镜最后看运动。"
        "顺序的意义：先排除致命项（出画、整体遮挡），再谈微调项（三分、重心）",
        ["检查顺序", "步骤", "流程", "审核"],
        examples=("一镜先确认没有出画，再谈三分偏差"),
        related=("comp_framing", "comp_headroom", "rev_method_decision"),
    ),
    _card(
        "rev_method_decision", _D, "判定矩阵：过/不过 + 失败分量",
        "构图过门的判定给到可复算的规则：总分 **> 80**（严格高于，等于 80 不算过）"
        "且由六分项按固定权重加权"
        "（headroom 0.15 / lead_room 0.20 / rule_of_thirds 0.15 / balance 0.15"
        "/ occlusion 0.25 / framing 0.10）。“挂了哪个分量”只看该分项分数 < 0.8，"
        "不看总分。每项先读读数（当前值 vs 目标区间），再判过/不过，最后汇成"
        "JSON：{\"passed\": bool, \"failed\": [分量名]}。",
        ["判定", "过门", "分量", "阈值", "矩阵"],
        parameters={"pass_score": 80.0, "item_threshold": 0.8},
        related=("comp_headroom", "comp_balance", "rev_method_order"),
    ),
    _card(
        "rev_method_feedback", _D, "反馈写作规范：结论先行，数值可选",
        "审核反馈按固定结构写，复核顺序固定为结论→失败分量→依据→下一步，"
        "避免空话：① 结论（这镜过/不过）；② 失败分量（挂了什么，按严重度排序："
        "遮挡/出画 > 视线/重心 > 三分/留白微调）；③ 依据（有读数写当前值与目标"
        "区间，无读数写定性判断，不编数字）；④ 下一步（只给方向性描述，不给工具"
        "调用建议）。反馈只描述画面事实，不评价导演意图。",
        ["反馈", "规范", "结论先行", "严重度"],
        examples=("不过：主主体部分出画（framing 0.55 < 0.90）→ 建议收紧景别"),
        related=("comp_framing", "rev_method_decision"),
    ),
    _card(
        "rev_method_multi_subject", _D, "多主体/群戏镜的审核顺序",
        "多主体镜先按可见度定主锚（完全出画者不当主锚），再按主锚判入画/留白/"
        "三分；重心按全部在画主体算；遮挡逐个主体核对“脸与关键动作是否被盖”，"
        "只要关键主体被盖就记 occlusion 失败。不要用“画面挺平衡”代替逐项检查，"
        "也不要让出画角色带偏主锚。",
        ["多主体", "群戏", "主锚", "遮挡"],
        rules=("MR001",),
        related=("comp_widescreen_grouping", "rev_method_order"),
    ),
    _card(
        "rev_method_dynamic", _D, "动态/打斗镜：先静态后动态",
        "打斗镜在六步检查上追加时间维度，顺序固定：先按静态六项看每一帧（入画/"
        "留白/三分/重心/遮挡），再追运动事实——谁出画、在哪帧；出画后是否从另一侧"
        "回冲；方向反转几次、在哪帧；关键帧里谁挡了谁的哪个部位；速度档有哪些。"
        "只报告可复算的几何与运动事实，不裁决“这一拳够不够力”。",
        ["打斗", "动态", "出画", "回冲", "方向反转"],
        related=("rev_method_order", "comp_eye_trace"),
    ),
    _card(
        "rev_method_anti_hallucination", _D, "防幻觉：没有读数不下数值结论",
        "没有测量读数时，只做定性判断（“头部留白看起来偏多”），不编“0.18”这类"
        "精确数值；有读数时引用读数并与目标区间比较，不脑补。无法判定某项（如无"
        "朝向时 lead_room 不适用）就如实标“不适用”，不要硬给一个分数。",
        ["防幻觉", "读数", "数值", "不适用"],
        examples=("无朝向主体 → lead_room 标“不适用”而非 0.5"),
        related=("comp_lead_room", "rev_method_decision"),
    ),
    _card(
        "rev_method_prescription", _D, "与处方交互：只接受/拒绝，不重写",
        "收到构图处方时，审核方的职责是接受/拒绝，不是重写处方。接受条件检查"
        "清单：处方工具存在、参数通过该工具 schema、不含求解器内部键（如 "
        "camera_z）。任一不满足就拒绝并说明原因。处方里的数值与方向只作参考，"
        "不写入自己的判定依据（判定依据只能用读数）。",
        ["处方", "接受", "拒绝", "guard_verdict"],
        rules=("MR002",),
        related=("rev_method_feedback", "comp_occlusion"),
    ),
)
