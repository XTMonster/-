"""镜头清单 shots.json（执行文档 v1.2 §15.4）。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.beats import PACE_VALUES
from ..contracts.elements import ElementRegistry, shot_element_ids
from ..contracts.plan import Plan
from ..contracts.rhythm import CURVE_VALUES

FPS = 24


def generated_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_manifest(plan: Plan, *,
                   build_summary: Optional[Dict[str, Any]] = None,
                   resolution: Sequence[int] = (1280, 720),
                   fps: int = FPS,
                   project: str = "BlockDirector",
                   style: str = "",
                   generated_at: Optional[str] = None,
                   llm_calls: int = 0,
                   retrieval_calls: int = 0,
                   crowd: Optional[Sequence[Dict[str, Any]]] = None,
                   parsed=None,
                   timing_overrides: Optional[Sequence[Dict[str, Any]]] = None,
                   action_conflicts: Optional[Sequence[Dict[str, Any]]] = None,
                   audit_pass_rate: Optional[Dict[str, Any]] = None,
                   knowledge_provenance: Optional[Dict[str, Any]] = None,
                   knowledge: Optional[Dict[str, Any]] = None,
                   review_requests: Optional[Sequence[Dict[str, Any]]] = None,
                   registry: Optional[ElementRegistry] = None,
                   rhythm_arc: Optional[Sequence[Dict[str, Any]]] = None,
                  ) -> Dict[str, Any]:
    """把分镜计划与构建结果拼成交付用清单。

    v1.4 R45：``llm_calls`` / ``retrieval_calls`` / ``crowd{}`` 三个字段的
    生产**提前到 P9.4**——P9.4 的 RK-18、P13 的 "``llm_calls`` ≤ 528" 与
    P12 的 RK-16 都要读它们，而此前 manifest 一个都不写。

    v1.4 P15（§3.3）：补齐交付字段 schema。逐镜字段是 ``declared{}`` /
    ``labels{}`` / ``movements[]``，跨镜字段是 ``crowd{}`` /
    ``timing_overrides[]`` / ``action_conflicts[]`` / ``dialogue_pins[]`` /
    ``audit_pass_rate{}``。

    ``knowledge_provenance``（2026-10-01，审查 #21）：``{shot_id: {来源类:
    [[kind, 取值], ...]}}``，来自该镜 B1 **那一次**检索真的注入的超边。有它，
    ``movements[].source`` 才写得出 ``theory`` / ``lesson`` / ``experience``——
    在那之前这一栏只有 ``declared|planned``，E2（经验采纳率）因此结构性恒为 0
    （"有指标没数据"）。缺省 ``None`` ＝ 没有知识层，行为与 P15 逐字相同。
    """
    results = {r.get("shot_id"): r for r in
               (build_summary or {}).get("results", [])}
    label_offsets = dict(((build_summary or {}).get("label_report") or {})
                         .get("offsets") or {})
    declarations = _declarations(parsed)
    review_counts = Counter(str(item.get("shot_id") or "")
                            for item in (review_requests or []))
    tensions = _rhythm_tensions(rhythm_arc)

    shots: List[Dict[str, Any]] = []
    cursor = 1
    for order, shot in enumerate(plan.shots, start=1):
        result = results.get(shot.shot_id, {})
        declared = declarations.get(order - 1)
        start = int(result.get("start_frame", cursor))
        end = int(result.get("end_frame", start + shot.duration_frames - 1))
        cursor = end + 1
        payload = {
            "shot_id": shot.shot_id,
            "order": shot.order or order,
            "intent": shot.intent,
            #: v1.5 §2.3d T3：意图闭集取值。必须落盘——Q5 的 `derived` 诊断串
            #: 由 `shots.json` 重推（`quality.plan_query_of_shot`），缺了它，
            #: 重推串与真实发出的串会**每一镜都漂**（那一栏就废了）。
            "intent_type": str(getattr(shot, "intent_type", "") or ""),
            "shot_type": str(shot.shot_type),
            "start_frame": start,
            "end_frame": end,
            "duration_frames": end - start + 1,
            "duration_seconds": round((end - start + 1) / fps, 3),
            "video_file": f"blockout_{shot.shot_id}.mp4",
            "first_frame": f"first_frames/{shot.shot_id}.png",
            "camera": {
                "name": result.get("camera", f"BD_Cam_{shot.shot_id}"),
                "position": result.get("camera_position"),
                "lens": result.get("lens"),
            },
            #: v1.5（P14-313，轴族裁决）：**生成器原生值**——有序 pair ＋ 叉积符号 ＋ 状态。
            #: 只有生成器真的算过它们才有值（`shot_builder` 的 `ShotBuildResult`），
            #: 所以老运行/老结果里这三个键是空的（`pair=[]`、`sign=0`、`status=""`）——
            #: **不补默认值、不猜**。`left/right` 在约定定案前**不进成片**。
            "axis": {
                "pair": list(result.get("axis_pair", [])),
                "side_sign": int(result.get("axis_side_sign", 0)),
                "status": str(result.get("axis_status", "")),
            },
            #: v1.7 I3：本镜相机 9 帧等距采样路径（渲染循环写入 build_summary.result.paths）。
            #: 无采样（老构建/离线回放）时为空 dict——不补默认值、不猜。
            "paths": dict(result.get("paths") or {}),
            "characters": list(shot.characters),
            #: v1.6 E1（FR-A2）：这一镜里的**道具 + 环境件**（角色仍走
            #: ``characters``）。成员资格来自该镜计划内的引用（动作
            #: ``params.prop`` 与拍点 ``target``），不做图像推断；元素身份
            #: 的唯一真源是登记表——``registry=None``（旧调用方）时为空表。
            "elements_in_frame": _elements_in_frame(shot, registry),
            "dialogue_ids": list(shot.dialogue_ids),
            "action_types": [str(a.get("action_type")) for a in shot.actions],
            "axis_note": shot.axis_note,
            "continuity_in": shot.continuity_in,
            "needs_review": review_counts[shot.shot_id] > 0,
            "review_request_count": review_counts[shot.shot_id],
            "degraded": bool(result.get("warnings")),
            "warnings": list(result.get("warnings", [])),
            # ---- v1.6 D3（FR-B2 / FR-B5）的逐镜字段 ----
            #: 节奏三元组：tension 只来自节奏弧（brief.rhythm_arc）；pace/curve
            #: 只来自这一镜拍点表的**一致声明**。数据缺席就缺席、绝不补默认值
            #: （猜一个默认值会把"没写"伪装成"写了"）。每镜都有这个键（可为空）。
            "rhythm": _shot_rhythm_payload(shot, tensions.get(shot.shot_id)),
            # ---- v1.4 P15（§3.3）的逐镜字段 ----
            "declared": _declared_payload(declared, shot),
            "labels": _labels_payload(shot, label_offsets),
            "movements": _movements_payload(
                shot, declared,
                (knowledge_provenance or {}).get(shot.shot_id)),
            # ---- v1.5（P4-T4，TDD §6 第 8 步）的逐镜字段 ----
            #: 执行拍点表 / 构图声明 / 破例辩护：计划里的**契约字段**，逐字段可对拍
            #: （P15 纪律）。它们是**引擎内部键**，因此 `prompts.md` 里绝不出现
            #: （delivery/prompts.py 只渲染画面相关的可读字段）。
            "beats": [dict(item) for item in
                      (getattr(shot, "beats", None) or [])],
            "composition": dict(getattr(shot, "composition", None) or {}),
            "rule_justifications": [dict(item) for item in
                                    (getattr(shot, "rule_justifications", None)
                                     or [])],
            #: 破例辩护对拍（声明 vs 实测）：**只记录、不设门**。审核没跑到这一镜
            #: 时写四个空集，而不是省略这个键——"查过、两边都空"与"根本没查"
            #: 在读账时必须分得开。
            "justification_audit": _justification_audit(result),
            #: v1.5 §7（P6-T2）Best-of-N：这一镜被规则评分 rerank 降为备选的
            #: 候选草案（**不过滤、不丢**）。默认 draft_candidates=1 时是空表。
            "alternates": [dict(item) for item in
                           (result.get("alternates") or [])],
        }
        #: v1.5 §5.5（P6-T1）的 VLM 外部评审判词。与 `justification_audit`
        #: 相反，这里**没有"查过但两边都空"的状态**——没评过（缺省关）就是
        #: 整个键不出现，`shots.json` 与升级前逐字节一致；评过（含"评委不可用
        #: ⇒ 跳过"）就如实落 `status`，跳过 ≠ 通过。
        review = result.get("vlm_review")
        if isinstance(review, dict) and review:
            payload["vlm_review"] = dict(review)
        shots.append(payload)

    return {
        "project": project,
        "fps": fps,
        "resolution": list(resolution),
        "style": style,
        "generated_at": generated_at or generated_now(),
        "scene_heading": plan.scene_heading,
        "total_frames": sum(s["duration_frames"] for s in shots),
        "llm_calls": int(llm_calls or 0),
        "retrieval_calls": int(retrieval_calls or 0),
        "crowd": {
            "entries": [dict(item) for item in (crowd or [])],
            "total": sum(int(item.get("count") or 0)
                         for item in (crowd or [])),
        },
        "timing_overrides": [dict(item) for item in (timing_overrides or [])],
        "action_conflicts": [dict(item) for item in (action_conflicts or [])],
        "dialogue_pins": [dict(pin) for shot in plan.shots
                          for pin in (getattr(shot, "dialogue_pins", None)
                                      or [])],
        "audit_pass_rate": dict(audit_pass_rate or {
            "numerator": 0, "denominator": 0, "rules": [],
            "sampled_frames": 0, "exempt_shots": []}),
        #: v1.4 §4.1b 的 Q5 只在**真实模型运行**上判，而"运行证据属于哪一代
        #: 索引"必须能从证据文件本身读出来（跨文件对日志就是 §24.1 那个"过期
        #: 证据被当成现行证据"的形状）。这里把 `driver.py` 的运行期 knowledge
        #: 块整块带进交付清单：纯离线通路没有它 ⇒ 空块 ⇒ Q5 记 `stale_evidence`，
        #: 这在机制上就等于把 R46 的"离线不许判 Q5"变成了一条可执行的门。
        "knowledge": dict(knowledge or {}),
        "shots": shots,
    }


def _declarations(parsed) -> Dict[int, Any]:
    """分镜表声明：``{index: ParsedShotDeclaration}``（按镜序）。"""
    if parsed is None:
        return {}
    return {index: item for index, item in
            enumerate(getattr(parsed, "declared_shots", []) or [])}


#: ``rhythm{}`` 里 pace/curve 的闭集真源（与 B1 校验同一份词表，不抄第二份）。
_RHYTHM_BEAT_DOMAINS = {
    "pace": frozenset(PACE_VALUES),
    "curve": frozenset(CURVE_VALUES),
}


def _rhythm_tensions(rhythm_arc) -> Dict[str, int]:
    """``shot_id -> tension``：只收合法整数（bool 不算）；其余缺席、不猜。"""
    tensions: Dict[str, int] = {}
    for item in (rhythm_arc or []):
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        tension = item.get("tension")
        if shot_id and isinstance(tension, int) and not isinstance(tension, bool):
            tensions.setdefault(shot_id, tension)
    return tensions


def _shot_rhythm_payload(shot, tension: Optional[int]) -> Dict[str, Any]:
    """``shots.json`` 的 ``rhythm{}``。

    * ``tension``：节奏弧（brief.rhythm_arc）里这一镜的那一拍；没有就缺席；
    * ``pace`` / ``curve``：拍点表（``shot.beats[]``）里**每一拍**都声明了同一个
      闭集词才落盘；拍点表为空、任一拍没写、或同镜拍点互相打架 ⇒ 该键缺席。

    "缺席就缺席"是硬纪律：不补 ShotRhythm 的缺省值（默认值不等于模型写的数据）。
    """
    payload: Dict[str, Any] = {}
    if tension is not None:
        payload["tension"] = int(tension)
    beats = [item for item in (getattr(shot, "beats", None) or [])
             if isinstance(item, dict)]
    for key, closed in _RHYTHM_BEAT_DOMAINS.items():
        declared = [str(item.get(key) or "").strip() for item in beats
                    if str(item.get(key) or "").strip() in closed]
        if beats and len(declared) == len(beats) and len(set(declared)) == 1:
            payload[key] = declared[0]
    return payload


def _elements_in_frame(shot, registry: Optional[ElementRegistry]) -> List[str]:
    """§5 的 ``elements_in_frame``：道具 + 环境件，成员与顺序由登记表决定。"""
    if registry is None:
        return []
    return list(shot_element_ids(shot, registry))


#: 破例对拍的固定列（TDD §5.4 的命名；顺序即交付清单里的字段顺序）。
JUSTIFICATION_AUDIT_KEYS = (
    "declared_breaks", "declared_follows", "detected_violations",
    "undeclared_violations", "declared_but_clean",
)


def _justification_audit(result) -> Dict[str, List[str]]:
    """这一镜的破例对拍：``build_summary["results"]`` 里有就抄，没有就是空集。

    **不猜**：没有审核结果时不是"补一个通过的结论"，而是如实地写"两边都空"。
    """
    payload = result.get("justification_audit") if isinstance(result, dict) else None
    if not isinstance(payload, dict):
        payload = {}
    return {key: [str(item) for item in (payload.get(key) or [])]
            for key in JUSTIFICATION_AUDIT_KEYS}


def _declared_payload(declaration, shot) -> Dict[str, Any]:
    """§3.3 的 ``declared{}``：**全部可空**，没有声明时逐字段为 ``None``。"""
    payload = {
        "shot_number": None, "camera_number": None, "technique": None,
        "transition": None, "location": None, "time": None, "lighting": None,
        "sfx": None, "declared_duration_s": None,
        #: v1.5（P14-316）：**计划里已经算好的**归一化运镜枚举（`static`/`dolly_in`/…），
        #: 原样抄进成片记录。为什么必须有：`technique` 是剧本原话（"固定镜头"），
        #: 而知识侧的 `movement` 取值域是**英文枚举**——两边词表对不上，成片侧此前
        #: **一个可比的运镜值都没有**（实测 294/300 个 `movement` 成员落进 `film_side_empty`）。
        #: 只抄不改名、不翻译：计划里没有就是 `None`（本 payload 的规矩是**全部可空**）。
        "camera_move": None,
    }
    if declaration is None:
        pinned = int(getattr(shot, "declared_shot_number", 0) or 0)
        payload["shot_number"] = pinned or None
        payload["camera_move"] = str(getattr(shot, "declared_camera_move", "") or "") or None
        return payload
    payload.update({
        "shot_number": int(getattr(declaration, "shot_number", 0) or 0) or None,
        "camera_number": declaration.field("机号") or None,
        "technique": declaration.field("拍摄手法") or None,
        "transition": declaration.field("技巧") or None,
        "location": declaration.field("地点") or None,
        "time": declaration.field("时间") or None,
        "lighting": declaration.field("灯光") or None,
        "sfx": declaration.field("音效") or None,
        "declared_duration_s": getattr(declaration, "declared_seconds", None),
        "camera_move": str(getattr(shot, "declared_camera_move", "") or "") or None,
    })
    return payload


def _labels_payload(shot, offsets: Dict[str, Any]) -> Dict[str, Any]:
    """§3.3 的 ``labels{}``：``{char_id: {text, anchor_z, offset_px}}``。"""
    payload: Dict[str, Any] = {}
    for character_id in shot.characters or []:
        entry = offsets.get(str(character_id))
        if entry is None:
            continue
        payload[str(character_id)] = {
            "text": str(entry.get("text") or ""),
            "anchor_z": entry.get("anchor_z"),
            "offset_px": [0.0, float(entry.get("applied_offset_px") or 0.0)],
            "offset_reason": str(entry.get("offset_reason") or "none"),
        }
    return payload


#: R46（§3.3）的统一词表里"由知识带来的"那四个取值，也定下了优先级：
#: 硬理论 > 教训 > 结构化经验 > 案例类比（§2.3b 的冲突裁决顺序）。
KNOWLEDGE_SOURCE_ORDER = ("theory", "lesson", "experience", "case")


def _movements_payload(shot, declaration, provenance=None) -> List[Dict[str, Any]]:
    """§3.3 的 ``movements[]``：``source`` 只用 R46 的统一词表。

    取值优先级：剧本**声明**的运镜（``declared``）→ 该镜检索命中的知识
    （``theory`` / ``lesson`` / ``experience`` / ``case``，按
    :data:`KNOWLEDGE_SOURCE_ORDER` 取第一个命中）→ 计划自己排的（``planned``）。
    判据是"这条运镜的取值，被这一镜注入的超边点过名"，不是猜，也不拿别的
    镜头的命中来顶。
    """
    lookup: Dict[Tuple[str, str], str] = {}
    for source_kind in KNOWLEDGE_SOURCE_ORDER:
        for pair in (provenance or {}).get(source_kind, []) or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                lookup.setdefault((str(pair[0]), str(pair[1])), source_kind)
    items = []
    declared_move = str(getattr(declaration, "camera_move", "") or "")
    for raw in (getattr(shot, "camera", None) or {}).get("movements", []) or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or raw.get("kind") or "")
        if not kind:
            continue
        if declared_move and kind == declared_move:
            source = "declared"
        else:
            source = lookup.get(("movement", kind), "planned")
        items.append({
            "kind": kind,
            "start_frame": int(raw.get("start_frame") or 1),
            "end_frame": int(raw.get("end_frame") or shot.duration_frames),
            "source": source,
        })
    return items
