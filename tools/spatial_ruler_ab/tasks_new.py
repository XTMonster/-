"""Ticket 11：四类新任务 fixture 与 ground truth（spec §9/§10 扩展）。

在既有四臂（baseline/ruler/method/ruler_method）上新增：
* action_roles        —— 识别攻击者/受击者/结果；
* continuity_verdict  —— 判断轴线/运动方向是否连续；
* priority_order      —— 按修复优先级排序失败项（fatal > error > warning）；
* robustness_verdict  —— 判断微扰后是否仍通过。

全部 ground truth 由既有层模块的公开常量、三态样例或注册表确定性生成，
不依赖被测 agent、不依赖 bpy。尺子臂只注入测量事实（读数/等级/扰动参数），
绝不注入答案本身；污染任务在 payload 里留痕（poisoned + poison_wrong）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from block_director.cinema import metrics_action_causality as action_mod
from block_director.cinema import metrics_continuity as continuity_mod
from block_director.cinema import metrics_robustness as robustness_mod
from block_director.cinema import metrics_geometry as geometry_mod
from block_director.cinema import metrics_attention as attention_mod
from block_director.cinema import metrics_cinema as cinema_mod
from block_director.cinema.evaluation_protocol import (
    FrameSample,
    ShotSample,
    SequenceSample,
)
from block_director.cinema.metric_registry import METRICS_BY_NAME
from tools.spatial_ruler_ab.fixtures import ABTask


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _frames_of(sample: object) -> Sequence[FrameSample]:
    if isinstance(sample, ShotSample):
        return sample.frames
    if isinstance(sample, SequenceSample):
        return tuple(f for shot in sample.shots for f in shot.frames)
    raise TypeError(f"不支持的采样类型：{type(sample)!r}")


def _visible(sample: object, subject_id: str) -> List[Tuple[int, float]]:
    """确定性提取：主体在哪些帧可见（visible_ratio > 0.01）及可见比例。"""
    out: List[Tuple[int, float]] = []
    for frame in _frames_of(sample):
        item = frame.subject(subject_id)
        if item is not None and item.visible_ratio > 0.01:
            out.append((int(frame.frame), round(float(item.visible_ratio), 3)))
    return out


def _measurement_block(sample: object, subject_ids: Sequence[str]) -> str:
    """尺子臂事实块：逐帧可见性读数（纯几何，不含结论）。"""
    lines = ["测量读数（空间尺·帧可见性，仅作引用）："]
    for frame in _frames_of(sample):
        parts = []
        for sid in subject_ids:
            item = frame.subject(sid)
            vis = item.visible_ratio if item is not None else 0.0
            parts.append(f"{sid}={vis:.2f}")
        lines.append(f"- 第 {frame.frame} 帧：{'，'.join(parts)}")
    return "\n".join(lines)


def _measurement_records(mod, case) -> List[Dict[str, Any]]:
    """确定性收集层 evaluate 的 Measurement 字典（报告 raw_measurements 用）。"""
    out = mod.evaluate(case.sample, case.intent)
    recs: List[Dict[str, Any]] = []
    for m in out.measurements:
        recs.append({
            "metric": m.metric,
            "raw_value": round(float(m.raw_value), 4),
            "score": round(float(m.score), 4),
            "target": m.target.to_dict(),
            "evidence_frames": list(m.evidence_frames),
            "confidence": round(float(m.confidence), 4),
            "evidence_grade": m.evidence_grade,
        })
    return recs


def _derived_gates(mod, case) -> Dict[str, str]:
    """确定性收集层 evaluate 的硬门 finding（gate -> finding.message）。"""
    out = mod.evaluate(case.sample, case.intent)
    return {f.gate: f.message
            for f in (getattr(out, "findings", None) or ())
            if f.gate}


# --------------------------------------------------------------------------- #
# 1) action_roles：识别攻击者/受击者/结果
# --------------------------------------------------------------------------- #
def _action_result_frame(case) -> int:
    """确定性提取：受击者最后可见帧号（visible_ratio > 0.01）。"""
    visible = _visible(case.sample, action_mod.VICTIM)
    if not visible:
        raise ValueError(f"{case.name} 样例里受击者从未可见")
    return visible[-1][0]


def _action_fact_block(case) -> str:
    return _measurement_block(
        case.sample,
        (action_mod.ATTACKER, action_mod.VICTIM, action_mod.CONTACT_PROP))


def _action_roles_task(case, sid: str) -> ABTask:
    attacker = action_mod.ATTACKER
    victim = action_mod.VICTIM
    result_frame = _action_result_frame(case)
    gt = {"attacker": attacker, "victim": victim,
          "result_frame": result_frame}
    q = ("这个打斗镜头里：谁攻击、谁受击、结果在哪一帧可读？"
         "角色 id 用小写英文。只输出 JSON："
         "{\"attacker\": \"...\", \"victim\": \"...\", \"result_frame\": 帧号}")
    brief = (f"打斗镜头（帧 1–5）：{attacker} 发起攻击，{victim} 被击中，"
             f"接触道具 {action_mod.CONTACT_PROP}。")
    fact = _action_fact_block(case)
    method = ("检查顺序：1) 找出动作起帧在画面内且轮廓可辨的主体（攻击者）；"
              "2) 找出反应结束帧的主体（受击者）；"
              "3) 受击者最后可见的帧就是结果帧。")
    return ABTask(
        id=sid, kind="action_roles", scene_id="fight_01", question=q,
        ground_truth=gt,
        baseline_prompt=brief + "\n" + q,
        ruler_prompt=brief + "\n" + fact + "\n" + q,
        method_prompt=brief + "\n" + method + "\n" + q,
        ruler_method_prompt=brief + "\n" + method + "\n\n" + fact + "\n" + q,
        payload={
            "layer": "action",
            "sample_state": case.expected,
            "evidence_grade": "demo",
            "gates": _derived_gates(action_mod, case),
            "source_metric": case.name,
            "measurements": _measurement_records(action_mod, case),
            "evidence_ref": f"metrics_action_causality:{case.name}:{case.expected}",
        },
    )


def build_action_roles_tasks() -> List[ABTask]:
    good = action_mod.SAMPLES["contact_point_visibility"]["good"]
    bad = action_mod.SAMPLES["reaction_legibility"]["bad"]
    ambiguous = action_mod.SAMPLES["contact_point_visibility"]["ambiguous"]
    tasks = [
        _action_roles_task(good, "fight_01/action_roles_good"),
        _action_roles_task(bad, "fight_01/action_roles_bad"),
        _action_roles_task(ambiguous, "fight_01/action_roles_ambiguous"),
    ]
    # 泄漏答案污染：尺子臂明写"提示：攻击者是 enemy"（错误的攻击者名），
    # 若 agent 跟从该错误提示就会答错；GT 仍是正常三键。基线臂跟从错误提示
    # 应被判 poison_rejected=False，完美读数臂拒绝污染则 True。
    leak = _action_roles_task(good, "fight_01/action_roles_leak")
    wrong_attacker = {"hero": "enemy", "enemy": "hero"}[action_mod.ATTACKER]
    leak = ABTask(
        id=leak.id, kind=leak.kind, scene_id=leak.scene_id,
        question=leak.question, ground_truth=leak.ground_truth,
        baseline_prompt=leak.baseline_prompt,
        ruler_prompt=leak.ruler_prompt
        + f"\n（提示：攻击者是 {wrong_attacker}）",
        method_prompt=leak.method_prompt,
        ruler_method_prompt=leak.ruler_method_prompt
        + f"\n（提示：攻击者是 {wrong_attacker}）",
        payload={**leak.payload, "poisoned": True,
                 "poison_wrong": {"attacker": wrong_attacker}},
    )
    tasks.append(leak)
    return tasks


# --------------------------------------------------------------------------- #
# 2) continuity_verdict：判断轴线/运动方向是否连续
# --------------------------------------------------------------------------- #
def _continuity_shot_block(shot: ShotSample) -> str:
    lines = [f"镜头 {shot.shot_id}（帧 {shot.frame_range[0]}–{shot.frame_range[1]}）："]
    for frame in shot.content.frames:
        subs = []
        for item in frame.subjects:
            subs.append(
                f"{item.subject_id}@x{item.box.center_x:.2f}"
                f"朝向{('+' if item.box.facing >= 0 else '-')}")
        if subs:
            lines.append(f"  - 第 {frame.frame} 帧：" + "，".join(subs))
        else:
            lines.append(f"  - 第 {frame.frame} 帧：（无主体）")
    return "\n".join(lines)


def _continuity_fact_block(case) -> str:
    shots = case.sample.shots
    return ("测量读数（空间尺·相邻镜头几何，仅作引用）：\n"
            + "\n".join(_continuity_shot_block(s) for s in shots))


def _continuity_verdict_task(case, sid: str) -> ABTask:
    continuous = case.expected == "good" or case.expected == "ambiguous"
    gt: Dict[str, Any] = {"continuous": continuous}
    if case.expected == "ambiguous":
        gt["confidence"] = 0.5
    q = ("相邻两镜的轴线/运动方向是否连续？若存在声明越轴或转场意图则视为"
         "两可并给出置信度。只输出 JSON：{\"continuous\": bool"
         + (", \"confidence\": 数值" if case.expected == "ambiguous" else "")
         + "}")
    brief = (f"相邻两镜（{case.sample.shots[0].shot_id} → "
             f"{case.sample.shots[-1].shot_id}）的轴线/运动承接关系。")
    fact = _continuity_fact_block(case)
    method = ("检查顺序：1) 两镜主体屏幕次序是否翻转（左右关系互换且无桥接镜头）"
              "——翻转即越轴；2) 主体朝向/运动向量是否反向——反向即不连续；"
              "3) 若剧本声明了越轴/换侧/承接转弯，标为两可并给出低置信度。")
    return ABTask(
        id=sid, kind="continuity_verdict", scene_id="continuity", question=q,
        ground_truth=gt,
        baseline_prompt=brief + "\n" + q,
        ruler_prompt=brief + "\n" + fact + "\n" + q,
        method_prompt=brief + "\n" + method + "\n" + q,
        ruler_method_prompt=brief + "\n" + method + "\n\n" + fact + "\n" + q,
        payload={
            "layer": "continuity",
            "sample_state": case.expected,
            "evidence_grade": "demo",
            "gates": _derived_gates(continuity_mod, case),
            "source_metric": case.name,
            "measurements": _measurement_records(continuity_mod, case),
            "evidence_ref": f"metrics_continuity:{case.name}:{case.expected}",
        },
    )


def build_continuity_verdict_tasks() -> List[ABTask]:
    tasks: List[ABTask] = []
    for metric, states in sorted(continuity_mod.SAMPLES.items()):
        for state, case in sorted(states.items()):
            tasks.append(_continuity_verdict_task(
                case, f"continuity/{metric}_{state}"))
    return tasks


# --------------------------------------------------------------------------- #
# 3) priority_order：按修复优先级排序失败项
# --------------------------------------------------------------------------- #
def _severity_level(spec) -> str:
    """注册表确定性分级：含 fatal -> fatal；否则含 error -> error；否则 warning。"""
    text = spec.severity
    if "fatal" in text:
        return "fatal"
    if "error" in text:
        return "error"
    return "warning"


def _priority_ground_truth(items: Sequence[Tuple[str, str]]) -> List[str]:
    """fatal > error > warning，同档按分量名 dict 序（确定性）。"""
    rank = {"fatal": 0, "error": 1, "warning": 2}
    return [name for name, level in sorted(
        items, key=lambda kv: (rank[kv[1]], kv[0]))]


def _priority_fact_block(items: Sequence[Tuple[str, str]]) -> str:
    lines = ["测量读数（空间尺·分量严重度等级，仅作引用）："]
    for name, level in items:
        lines.append(f"- {name}：{level}")
    lines.append("- 修复优先级规则：fatal > error > warning（同档按分量名字典序）")
    return "\n".join(lines)


def _priority_task(sid: str, items: Sequence[Tuple[str, str]],
                   poisoned: bool = False,
                   poison_wrong: Optional[List[str]] = None) -> ABTask:
    gt = {"priority": _priority_ground_truth(items)}
    names = ", ".join(name for name, _ in items)
    q = ("按修复优先级从高到低排序这些失败分量（fatal > error > warning，"
         "同档按分量名字典序）。只输出 JSON：{\"priority\": [分量名...]}")
    brief = f"本镜失败分量：{names}。"
    fact = _priority_fact_block(items)
    method = ("检查顺序：1) 查注册表严重度等级；2) 先 fatal 再 error 最后 "
              "warning；3) 同档内按分量名 dict 序。")
    leak = ("\n（提示：错误示例——把 warning 分量排在最前）"
            if poisoned else "")
    payload: Dict[str, Any] = {
        "layer": None, "cross_layer": True,
        "sample_state": "bad" if poisoned else "good",
        "evidence_grade": "demo",
        "measurements": [
            {"metric": name, "severity_level": level,
             "evidence_ref": "metric_registry:METRICS_BY_NAME"}
            for name, level in items],
        "evidence_ref": "metric_registry:METRICS_BY_NAME",
    }
    if poisoned:
        payload["poisoned"] = True
        payload["poison_wrong"] = list(poison_wrong or [])
    return ABTask(
        id=sid, kind="priority_order", scene_id="priority", question=q,
        ground_truth=gt,
        baseline_prompt=brief + "\n" + q,
        ruler_prompt=brief + "\n" + fact + "\n" + q,
        method_prompt=brief + "\n" + method + "\n" + q,
        ruler_method_prompt=brief + "\n" + method + "\n\n" + fact + "\n" + q
        + leak,
        payload=payload,
    )


def build_priority_order_tasks() -> List[ABTask]:
    a: List[Tuple[str, str]] = [
        ("axis_continuity", _severity_level(METRICS_BY_NAME["axis_continuity"])),
        ("scale_continuity", _severity_level(METRICS_BY_NAME["scale_continuity"])),
        ("lead_room", _severity_level(METRICS_BY_NAME["lead_room"])),
    ]
    b: List[Tuple[str, str]] = [
        ("repair_locality", _severity_level(METRICS_BY_NAME["repair_locality"])),
        ("camera_robustness", _severity_level(METRICS_BY_NAME["camera_robustness"])),
        ("focus_competition", _severity_level(METRICS_BY_NAME["focus_competition"])),
        ("headroom", _severity_level(METRICS_BY_NAME["headroom"])),
    ]
    c: List[Tuple[str, str]] = [
        ("scale_continuity", _severity_level(METRICS_BY_NAME["scale_continuity"])),
        ("camera_robustness", _severity_level(METRICS_BY_NAME["camera_robustness"])),
        ("movement_intent_match", _severity_level(METRICS_BY_NAME["movement_intent_match"])),
    ]
    wrong = [name for name, _ in reversed(c)]
    return [
        _priority_task("priority/mixed_a", a),
        _priority_task("priority/mixed_b", b),
        _priority_task("priority/tie_error", c),
        _priority_task("priority/poisoned", a, poisoned=True,
                       poison_wrong=wrong),
    ]


# --------------------------------------------------------------------------- #
# 4) robustness_verdict：判断微扰后是否仍通过
# --------------------------------------------------------------------------- #
def _robustness_fact_block(case) -> str:
    out = robustness_mod.evaluate(case.sample, case.intent)
    lines = ["测量读数（空间尺·鲁棒性微扰参数与扰动前读数，仅作引用）："]
    lines.append(
        f"- 扰动参数：固定种子 {robustness_mod.PERTURB_SEED}，"
        f"姿态 ±{robustness_mod.POSE_JITTER:.2f} NDC，"
        f"相机位置 ±{robustness_mod.CAMERA_POS_NOISE:.2f} NDC，"
        f"焦距 ±{robustness_mod.CAMERA_LENS_NOISE:.1f} mm")
    for m in out.measurements:
        lines.append(
            f"- {m.metric}：原始 {m.raw_value:.3f}，目标 {m.target.to_dict()}，"
            f"置信度 {m.confidence:.2f}")
    return "\n".join(lines)


def _robustness_verdict_task(case, sid: str) -> ABTask:
    still_pass = case.expected == "good"
    gt = {"still_pass": still_pass}
    q = ("施加上述有界微扰后，这一镜仍能通过吗（原始值落在目标区间内）？"
         "只输出 JSON：{\"still_pass\": bool}")
    brief = f"鲁棒性微扰样例（{case.name}）。"
    fact = _robustness_fact_block(case)
    method = ("检查顺序：1) 逐个指标把扰动后原始值与目标区间比较；"
              "2) 全部落在区间内 -> still_pass=true；任一指标落在区间外 -> false；"
              "3) 置信度 < 1.0 的指标按两可处理，仍按区间判断。")
    return ABTask(
        id=sid, kind="robustness_verdict", scene_id="robustness", question=q,
        ground_truth=gt,
        baseline_prompt=brief + "\n" + q,
        ruler_prompt=brief + "\n" + fact + "\n" + q,
        method_prompt=brief + "\n" + method + "\n" + q,
        ruler_method_prompt=brief + "\n" + method + "\n\n" + fact + "\n" + q,
        payload={
            "layer": "robustness",
            "sample_state": case.expected,
            "evidence_grade": "demo",
            "gates": _derived_gates(robustness_mod, case),
            "source_metric": case.name,
            "measurements": _measurement_records(robustness_mod, case),
            "evidence_ref": f"metrics_robustness:{case.name}:{case.expected}",
        },
    )


def build_robustness_verdict_tasks() -> List[ABTask]:
    tasks: List[ABTask] = []
    for metric, states in sorted(robustness_mod.SAMPLES.items()):
        for state, case in sorted(states.items()):
            if state == "ambiguous":
                continue
            tasks.append(_robustness_verdict_task(
                case, f"robustness/{metric}_{state}"))
    return tasks


# --------------------------------------------------------------------------- #
# 组合：完整电池 = 既有任务 + 四类新任务
# --------------------------------------------------------------------------- #
_GATE_SOURCES = {
    "H1": (geometry_mod, "edge_clearance"),
    "H2": (action_mod, "action_readability"),
    "H3": (continuity_mod, "axis_continuity"),
    "H4": (attention_mod, "gaze_target_visibility"),
    "H5": (cinema_mod, "camera_path_clearance"),
    "H6": (robustness_mod, "repair_locality"),
}


def gate_probe_evidence() -> List[Dict[str, Any]]:
    """H1–H6 各一条触发与不触发样例证据（SPEC §11.1，层级 finding 派生）。

    由各层 SAMPLES 的 bad/good 样例经层 evaluate 的 findings 确定性判定：
    bad 样例触发其注册表硬门（finding.gate 命中），good 样例不触发。
    不进评测台任务集（保持四类新任务口径），只作为报告硬门理由的证据源。
    """
    out: List[Dict[str, Any]] = []
    for gate, (mod, metric) in sorted(_GATE_SOURCES.items()):
        for state in ("bad", "good"):
            case = mod.SAMPLES[metric][state]
            result = mod.evaluate(case.sample, case.intent)
            gates = _derived_gates(mod, case)
            out.append({
                "gate": gate,
                "state": state,
                "triggered": gate in gates,
                "source_metric": metric,
                "layer": spec_layer(gate),
                "findings": [{
                    "component": f.component,
                    "gate": f.gate,
                    "severity": f.severity.value
                    if hasattr(f.severity, "value") else str(f.severity),
                } for f in (getattr(result, "findings", None) or ())],
                "reason": gates.get(gate),
            })
    return out


def spec_layer(gate: str) -> str:
    return {"H1": "geometry", "H2": "action", "H3": "continuity",
            "H4": "attention", "H5": "cinema", "H6": "robustness"}[gate]


def build_new_tasks() -> List[ABTask]:
    return (build_action_roles_tasks()
            + build_continuity_verdict_tasks()
            + build_priority_order_tasks()
            + build_robustness_verdict_tasks())


def build_full_battery():
    from tools.spatial_ruler_ab.fixtures import build_battery
    return build_battery() + build_new_tasks()


def battery_fingerprint(battery) -> str:
    """确定性指纹：任务 id/kind/ground_truth/payload 的规范 JSON 摘要。"""
    payload = [{
        "id": t.id, "kind": t.kind, "scene_id": t.scene_id,
        "ground_truth": t.ground_truth, "payload": _jsonable(t.payload),
    } for t in battery]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _jsonable(value: Any) -> Any:
    """递归剔除不可 JSON 序列化的对象（如 FightScene），保确定性。"""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return f"<{type(value).__name__}>"
