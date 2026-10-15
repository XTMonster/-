"""评测台场景 fixture 与任务集构建（spec §15.2/15.3）。

全部纯层、确定性；地面真值由既有纯几何代码算出，不靠人工打分。
组成构图场景与打斗场景两类；任务按 kind 生成两臂提示。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from block_director.cinema.composition import (
    HEADROOM_IDEAL,
    SubjectBox,
    evaluate_composition,
    thirds_deviation,
)
from block_director.cinema.dynamic_measure import analyze_fight
from block_director.cinema.prescription import build_prescriptions
from tools.spatial_ruler_fight_demo import build_fight_scene
from .method import render_method_block


# --------------------------------------------------------------------------- #
# 构图场景
# --------------------------------------------------------------------------- #
def _box(cx: float, cy: float, name: str = "甲", facing: float = 1.0,
         top: Optional[float] = None, bottom: Optional[float] = None,
         left: Optional[float] = None, right: Optional[float] = None,
         half: float = 0.18) -> SubjectBox:
    return SubjectBox(
        name=name,
        left=cx - half if left is None else left,
        right=cx + half if right is None else right,
        top=cy + 0.5 if top is None else top,
        bottom=cy - 0.5 if bottom is None else bottom,
        facing=facing,
    )


def _primary(boxes: List[SubjectBox]) -> SubjectBox:
    return max(boxes, key=lambda b: (b.inside_ratio() > 0.05, b.height))


def _scene(boxes: List[SubjectBox], brief: str, scene_id: str,
           occluded: Optional[Dict[str, bool]] = None,
           expected_height: Optional[float] = None,
           headroom_applies: bool = True) -> Dict[str, Any]:
    report = evaluate_composition(boxes, occluded, expected_height,
                                  headroom_applies)
    primary = _primary(boxes)
    failed = sorted(k for k, v in report.items.items() if v.score < 0.7)
    lead_ratio = None
    if abs(primary.facing) > 1e-6:
        ahead = (1.0 - primary.center_x) if primary.facing > 0 else primary.center_x
        behind = primary.center_x if primary.facing > 0 else 1.0 - primary.center_x
        lead_ratio = ahead / max(ahead + behind, 1e-9)
    mean_x = sum(b.center_x for b in boxes) / len(boxes)
    return {
        "id": scene_id,
        "boxes": boxes,
        "occluded": occluded or {},
        "expected_height": expected_height,
        "headroom_applies": headroom_applies,
        "brief": brief,
        "report": report,
        "gt": {"passed": report.passed, "failed": failed},
        "facts": {
            "headroom_current": (1.0 - primary.top) if headroom_applies else None,
            "headroom_range": list(HEADROOM_IDEAL),
            "thirds_current": round(thirds_deviation(primary.center_x,
                                                     primary.center_y), 3),
            "thirds_target": round(0.35 * (1.0 - 0.7), 3),  # 0.105
            "balance_current": round(abs(mean_x - 0.5), 3),
            "balance_dead_zone": 0.20 if len(boxes) == 1 else 0.12,
            "lead_current": round(lead_ratio, 3) if lead_ratio is not None else None,
            "lead_target": round(0.4 + 0.35 * 0.7, 3),  # 0.645
            "framing_current": round(primary.inside_ratio(), 3),
            "framing_target": 0.90,
            "occlusion": "无遮挡" if not [b for b in boxes
                                         if occluded and occluded.get(b.name)]
                          else "有遮挡",
            "score": report.score,
        },
    }


def composition_scenes() -> List[Dict[str, Any]]:
    """七类构图场景：良、头留白、三分、视线留白、重心、遮挡、出画。"""
    return [
        _scene([_box(0.33, 0.33, name="甲", top=0.93, bottom=0.42)],
               "单主体位于左下三分交点，整身入画，朝向右侧。", "good"),
        _scene([_box(0.33, 0.33, name="甲", top=0.60, bottom=0.25)],
               "单主体偏下，头顶留白过多，整身入画，朝向右侧。", "headroom_fail"),
        _scene([_box(0.72, 0.72, name="甲", top=1.15, bottom=0.30)],
               "单主体贴近画面右侧，偏离三分交点，整身入画。", "thirds_fail"),
        _scene([_box(0.82, 0.50, name="甲", top=0.95, bottom=0.06)],
               "单主体大幅偏右且朝右，视线方向几乎没有留白。", "lead_fail"),
        _scene([_box(0.25, 0.50, name="甲"), _box(0.30, 0.55, name="乙")],
               "双主体都挤在画面左侧，重心偏塌。", "balance_fail"),
        _scene([_box(0.33, 0.33, name="甲", top=0.93, bottom=0.42)],
               "主体被前景遮挡头部，整身入画。", "occlusion_fail",
               occluded={"甲": True}),
        _scene([_box(0.33, 0.33, name="甲", left=0.85, right=1.20)],
               "主体大部分在画外，只有局部入画。", "framing_fail"),
    ]


# --------------------------------------------------------------------------- #
# 打斗场景
# --------------------------------------------------------------------------- #
def fight_scene():
    """打斗 fixture：复用打斗 demo 的同一组合成采样（事件帧一致）。"""
    return build_fight_scene()


# --------------------------------------------------------------------------- #
# 方向闭集与规则（评测台声明的期望，非产品改动）
# --------------------------------------------------------------------------- #
DIRECTION_CLOSED_SET = [
    "抬高机位", "降低机位", "向左平移", "向右平移", "推近", "拉远",
    "左右平衡", "平移", "收紧景别",
]

DIRECTION_RULE: Dict[str, List[str]] = {
    "headroom": ["抬高机位", "推近"],
    "lead_room": ["平移", "向左平移", "向右平移"],
    "rule_of_thirds": ["平移", "向左平移", "向右平移"],
    "balance": ["左右平衡"],
    "occlusion": ["平移", "向左平移", "向右平移"],
    "framing": ["推近", "收紧景别"],
}


# --------------------------------------------------------------------------- #
# 任务集
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ABTask:
    id: str
    kind: str
    scene_id: str
    question: str
    ground_truth: Any
    baseline_prompt: str
    ruler_prompt: str
    method_prompt: str = ""
    ruler_method_prompt: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


def _failed_components(scene: Dict[str, Any]) -> List[str]:
    return scene["gt"]["failed"]


def _prescription_for(scene: Dict[str, Any], component: str):
    for p in build_prescriptions(scene["report"]):
        if p.component == component:
            return p
    return None


def _fix_ground_truth(p) -> Dict[str, Any]:
    """fix 任务地面真值：工具 = 处方允许白名单的首选（确定性）。

    03a 收敛后处方只给方向与 allowed_tools，不再携带可执行 tool/tool_args；
    这里从白名单推导 ground truth，评分器按 demo schema 校验"工具在白名单内
    且参数可执行"，参数本身不参与对拍（参数样本只供 mock 判官构造答案）。
    """
    tool = p.allowed_tools[0] if p.allowed_tools else ""
    return {"allowed_tools": list(p.allowed_tools), "tool": tool}


def build_battery() -> List[ABTask]:
    tasks: List[ABTask] = []

    for scene in composition_scenes():
        sid = scene["id"]
        report = scene["report"]
        gt = scene["gt"]
        facts = scene["facts"]
        method = render_method_block(scene)
        method_measure = method + "\n\n" + _measurement_block(scene)

        # verdict
        q = "这镜构图过门吗？如果不过，挂了哪些分量？" \
            "只输出 JSON：{\"passed\": bool, \"failed\": [分量名]}"
        tasks.append(ABTask(
            id=f"{sid}/verdict", kind="verdict", scene_id=sid, question=q,
            ground_truth={"passed": gt["passed"], "failed": gt["failed"]},
            baseline_prompt=scene["brief"] + "\n" + q,
            ruler_prompt=scene["brief"] + "\n" + _measurement_block(scene) + "\n" + q,
            method_prompt=scene["brief"] + "\n" + method + "\n" + q,
            ruler_method_prompt=scene["brief"] + "\n" + method_measure + "\n" + q,
            payload={"component": None},
        ))

        # estimate（对每个"不合格的数值事实"问一个数值）
        for metric, qtext in (
            ("headroom", "头顶留白占画面高度多少（0~1）？只输出 JSON：{\"value\": 数值}"),
            ("thirds", "主体中心到最近三分线交点的偏差是多少（0~1）？" \
                       "只输出 JSON：{\"value\": 数值}"),
            ("balance", "画面重心偏离画面中心多少（0~1）？" \
                        "只输出 JSON：{\"value\": 数值}"),
            ("lead", "视线方向留白的前瞻比例是多少（0~1）？" \
                     "只输出 JSON：{\"value\": 数值}"),
        ):
            metric_key = {"headroom": "headroom_current",
                          "thirds": "thirds_current",
                          "balance": "balance_current",
                          "lead": "lead_current"}[metric]
            value = facts.get(metric_key)
            if value is None:
                continue
            component = {"headroom": "headroom", "thirds": "rule_of_thirds",
                         "balance": "balance", "lead": "lead_room"}[metric]
            if component not in _failed_components(scene):
                continue
            tasks.append(ABTask(
                id=f"{sid}/estimate_{metric}", kind="estimate", scene_id=sid,
                question=qtext, ground_truth={"value": value},
                baseline_prompt=scene["brief"] + "\n" + qtext,
                ruler_prompt=scene["brief"] + "\n" + _measurement_block(scene) + "\n" + qtext,
                method_prompt=scene["brief"] + "\n" + method + "\n" + qtext,
                ruler_method_prompt=scene["brief"] + "\n" + method_measure + "\n" + qtext,
                payload={"metric": metric, "component": component},
            ))

        # direction / fix：对每个失败分量
        for comp in _failed_components(scene):
            choice = " / ".join(DIRECTION_CLOSED_SET)
            qdir = f"（{comp}）该往哪个方向调？从《{choice}》中选择，" \
                   "只输出 JSON：{\"direction\": \"...\"}"
            qfix = "给出一个可执行修复（工具名 + 参数）。" \
                   "只输出 JSON：{\"tool\": \"...\", \"tool_args\": {...}}"
            p = _prescription_for(scene, comp)
            if p is None:
                continue
            tasks.append(ABTask(
                id=f"{sid}/direction_{comp}", kind="direction", scene_id=sid,
                question=qdir,
                ground_truth={"acceptable": DIRECTION_RULE[comp],
                              "primary": DIRECTION_RULE[comp][0]},
                baseline_prompt=scene["brief"] + "\n" + "当前建议：" +
                                _suggestions_text(scene) + "\n" + qdir,
                ruler_prompt=scene["brief"] + "\n" + _measurement_block(scene) + "\n" + qdir,
                method_prompt=scene["brief"] + "\n" + method + "\n" + qdir,
                ruler_method_prompt=scene["brief"] + "\n" + method_measure + "\n" + qdir,
                payload={"component": comp},
            ))
            tasks.append(ABTask(
                id=f"{sid}/fix_{comp}", kind="fix", scene_id=sid, question=qfix,
                ground_truth=_fix_ground_truth(p),
                baseline_prompt=scene["brief"] + "\n" + "当前建议：" +
                                _suggestions_text(scene) + "\n" + qfix,
                ruler_prompt=scene["brief"] + "\n" + _measurement_block(scene) + "\n" + qfix,
                method_prompt=scene["brief"] + "\n" + method + "\n" + qfix,
                ruler_method_prompt=scene["brief"] + "\n" + method_measure + "\n" + qfix,
                payload={"component": comp},
            ))

            # prescription_verdict：合法处方（接受）与下毒处方（拒绝）
            qpv = "这个处方可执行吗？接受还是拒绝？" \
                  "只输出 JSON：{\"accept\": bool, \"reason\": \"...\"}"
            tasks.append(ABTask(
                id=f"{sid}/pv_{comp}", kind="prescription_verdict", scene_id=sid,
                question=qpv, ground_truth={"accept": True},
                baseline_prompt=scene["brief"] + "\n" + "当前建议：" +
                                _suggestions_text(scene) + "\n" +
                                render_prescription_block(p) + "\n" + qpv,
                ruler_prompt=scene["brief"] + "\n" + _measurement_block(scene) + "\n" +
                             render_prescription_block(p) + "\n" + qpv,
                method_prompt=scene["brief"] + "\n" + method + "\n" +
                              render_prescription_block(p) + "\n" + qpv,
                ruler_method_prompt=scene["brief"] + "\n" + method_measure + "\n" +
                                    render_prescription_block(p) + "\n" + qpv,
                payload={"component": comp, "poisoned": False},
            ))
            tasks.append(ABTask(
                id=f"{sid}/pv_{comp}_poison", kind="prescription_verdict",
                scene_id=sid, question=qpv, ground_truth={"accept": False},
                baseline_prompt=scene["brief"] + "\n" + "当前建议：" +
                                _suggestions_text(scene) + "\n" +
                                render_prescription_block(_poison(p)) + "\n" + qpv,
                ruler_prompt=scene["brief"] + "\n" + _measurement_block(scene) + "\n" +
                             render_prescription_block(_poison(p)) + "\n" + qpv,
                method_prompt=scene["brief"] + "\n" + method + "\n" +
                              render_prescription_block(_poison(p)) + "\n" + qpv,
                ruler_method_prompt=scene["brief"] + "\n" + method_measure + "\n" +
                                    render_prescription_block(_poison(p)) + "\n" + qpv,
                payload={"component": comp, "poisoned": True},
            ))

    # 打斗动态事实
    fight = fight_scene()
    dynamic = analyze_fight(fight)
    exits = [(e.character_id, e.frame) for e in dynamic.events
             if e.kind == "exit_frame"]
    reentries = [(e.character_id, e.frame) for e in dynamic.events
                 if e.kind == "reentry_frame"]
    flips = {e.kind for e in dynamic.events if e.kind == "direction_change"}
    hero_bands = sorted(dynamic.trajectory["hero"].bands.keys())
    qdyn = ("这个打斗镜头里：谁在第几帧出画？谁重新入画？方向反转几次？"
            "英雄的速度档有哪些？只输出 JSON："
            "{\"exits\": [[角色, 帧]], \"reentries\": [[角色, 帧]], "
            "\"direction_changes\": 次数, \"hero_bands\": [档位]}"
            "（exits/reentries 中“角色”用小写英文角色 id）")
    fight_method = render_method_block(fight)
    fight_method_measure = fight_method + "\n\n" + _dynamic_block(fight, dynamic)
    tasks.append(ABTask(
        id="fight_01/dynamic_facts", kind="dynamic_facts", scene_id="fight_01",
        question=qdyn,
        ground_truth={
            "exits": exits, "reentries": reentries,
            "direction_changes": len(flips), "hero_bands": hero_bands,
        },
        baseline_prompt=("打斗：英雄从左侧步步进逼，反派被击飞出画后从另一侧"
                         "回冲，两人在第5-6帧重叠且头部被挡。\n" + qdyn),
        ruler_prompt=("打斗：英雄从左侧步步进逼，反派被击飞出画后从另一侧"
                      "回冲。\n" + _dynamic_block(fight, dynamic) + "\n" + qdyn),
        method_prompt=("打斗：英雄从左侧步步进逼，反派被击飞出画后从另一侧"
                       "回冲。\n" + fight_method + "\n" + qdyn),
        ruler_method_prompt=("打斗：英雄从左侧步步进逼，反派被击飞出画后从另一侧"
                             "回冲。\n" + fight_method_measure + "\n" + qdyn),
        payload={"hero_bands": hero_bands, "scene": fight},
    ))
    return tasks


# --------------------------------------------------------------------------- #
# 提示渲染（arms 渲染放在本模块，避免循环依赖）
# --------------------------------------------------------------------------- #
def _measurement_block(scene: Dict[str, Any]) -> str:
    f = scene["facts"]
    lines = ["测量读数（空间尺：分量未达标给出当前值与目标区间，仅作引用）："]
    lo, hi = f["headroom_range"]
    lines.append(f"- headroom 留白: {f['headroom_current']:.3f}（目标 [{lo:.3f}, {hi:.3f}]）")
    if f["lead_current"] is not None:
        lines.append(f"- lead_room 前瞻比例: {f['lead_current']:.3f}（目标 ≥ {f['lead_target']:.3f}）")
    else:
        lines.append("- lead_room 前瞻比例: 不适用（主体无明确朝向）")
    lines.append(f"- thirds 偏差: {f['thirds_current']:.3f}（目标 ≤ {f['thirds_target']:.3f}）")
    dz = f["balance_dead_zone"]
    lines.append(f"- balance 重心偏移: {f['balance_current']:.3f}（目标 ≤ {dz:.3f}）")
    lines.append(f"- occlusion: {f['occlusion']}（目标：无）")
    lines.append(f"- framing 入画比例: {f['framing_current']:.3f}（目标 ≥ {f['framing_target']:.3f}）")
    lines.append(f"- 总分: {f['score']:.1f} / 100（过门线 70）")
    return "\n".join(lines)


def _dynamic_block(fight, dynamic) -> str:
    from block_director.cinema.dynamic_measure import render_dynamic_report
    return ("测量读数（空间尺·战斗动态，仅作引用）：\n"
            + render_dynamic_report(dynamic))


def _suggestions_text(scene: Dict[str, Any]) -> str:
    s = scene["report"].suggestions
    return "；".join(s) if s else "无"


def render_prescription_block(p) -> str:
    """把处方渲染成对拍块：只含分量/严重度/当前/目标/方向/预期影响。

    接受 Prescription 或其 ``to_dict()`` 产物；allowed_tools 是污染源，一律
    不渲染（工具名/参数/"建议执行"都在 detect_pollution 的拒绝词表里）。
    若载荷携带未注册内部键（下毒样本），component 本身就是 camera_z，
    detect_pollution 据此判中。
    """
    d = p.to_dict() if hasattr(p, "to_dict") else dict(p)
    return (f"处方：分量 {d['component']}（严重度 {d['severity']}）\n"
            f"  当前 {float(d['current']):.2f}，目标 {d['target']}\n"
            f"  修复方向：{d['direction']}\n"
            f"  预期影响：{'、'.join(d['expected_effect'])}")


def _poison(p):
    """把合法处方的分量换成未注册内部键 camera_z，构造"必须拒绝"样本。

    03a 收敛后处方不再携带 tool/tool_args，"给参数下毒"迁移为
    "component 用 camera_z"——与 validate_prescription 的拒绝分支同一语义。
    """
    from dataclasses import replace
    return replace(p, component="camera_z")
