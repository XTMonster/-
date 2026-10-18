"""定向修复提示（执行文档 v1.2 §7.1 阶段 B4 / §18.3）。

要点：回灌给模型的是**结构化违规项**（rule/target/message/suggestion），
而不是"构图不好，改改"。修复靠工具调用落地，所以工具集必须包含真正能改
场景的几个动作工具。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..cinema.spatial_digest import render_spatial_digest
from ..contracts.audit import AuditResult
from ..contracts.enums import Purpose, ToolChoice
from ..contracts.messages import ChatPayload, Message, MessageRole, new_request_id
from ..contracts.tools import CONTROL_TOOL_NAMES, SHOT_DRAFT_TOOL
from ..contracts.vlm_review import VLM_REVIEW_SCHEMA_V2
from .dialogue_budget import shot_dialogue_budget

#: **时间轴类**规则：它们读的是计划里的动作表 / 台词表，能改这两张表的只有
#: `emit_shot_draft`（`merge_draft` 整份替换 actions/dialogues）。场景工具
#: （`character_action`、`move_character`…）只往 Blender 场景里**叠**动画，
#: 一个字都不写回计划 —— 实测就是 R003 一直红的原因（见
#: `tests/test_repair_prompt_picks_the_right_tool.py` 的文件头）。
TIMELINE_RULES = frozenset({"R003", "R011", "R015"})

#: 修复尝试里的**延续轮**提示。它存在的理由是可测量的：真跑（2026-10-04，
#: `long17`）的 104 个修复回合里 **72 个**恰好是 `search_knowledge` ＋
#: `get_scene_state` 两次只读调用——模型把唯一一轮花在"查资料 + 看场景"上，
#: 然后这一轮就结束了。给了下一轮还不够：那些观测此前也**没有被发回**。
REPAIR_FOLLOWUP_NUDGE = """\
上一轮你只做了查询（场景/知识/复核），**没有改动任何东西**，所以问题依旧存在。
现在请**直接调用改动类工具**动手修正，并把要改的部分一次改到位：

- 时间轴类（R003 / R011 / R015）：用 `emit_shot_draft` 重提这一镜的草案；
- 空间/构图类（R001 / R002 / R005 / 构图分低）：用 `place_character`、
  `move_character`、`face_character`、`setup_camera`、`reframe`、
  `move_camera` 之一真的把场景挪到位；

不要再只是查询。如果确实已经无需修改，请明确说明是哪一条审计已经不再成立。
"""

# --------------------------------------------------------------------------- #
# v1.6 B4（FR-C5 / D-13）：告警数值证据注入修复提示 + 固定动作菜单 + 裁决留痕
# --------------------------------------------------------------------------- #
#: 固定动作菜单（卡 B4 钉死）：每条告警必须且只能选一个。
GUARD_ACTION_MENU: Tuple[str, ...] = (
    "move_camera", "reframe", "move_character", "accept")

#: accept 声明的行格式（修复回复正文逐条写）。解析与记录都走
#: :func:`parse_guard_accepts` / :func:`guard_verdict`——accept 绝不静默。
GUARD_ACCEPT_PREFIX = "ACCEPT"

#: 告警类型 → 一行里的"现象"文案（与 ``contracts/guard.py::WARNING_TYPES`` 同义）。
GUARD_PHENOMENON: Dict[str, str] = {
    "subject_out_of_frame": "主体完全出画",
    "subject_behind_camera": "主体在相机后方",
    "subject_not_visible": "主体在画内但完全不可见",
    "edge_clip": "主体被画框裁切",
    "occlusion": "主体被前景遮挡",
    "framing_too_tight": "取景过紧",
    "framing_too_loose": "取景过松",
    "headroom_off": "头顶留白出区间",
    "lead_room_short": "朝向侧留白不足",
    "thirds_deviation": "主体偏离三分线",
    "size_drift": "镜内景别漂移",
    "sudden_jump": "主体占比突变",
    "unplanned_exit": "计划外离场",
    "jump_cut_risk": "相邻镜跳切风险",
    "axis_screen_order": "银幕左右序翻转",
    "pace_monotony": "全片镜长相同",
}

#: 告警类型 → 动作菜单里**建议的那一个**（四选一，括号里是可测的操作）。
GUARD_FIX_ACTION: Dict[str, str] = {
    "subject_out_of_frame": "move_character（把主体挪回画面）",
    "subject_behind_camera": "reframe（后退或降焦段，保持主体在相机前方；"
                              "不要穿过主体或轴线）",
    "subject_not_visible": "move_character（先挪开前景遮挡者或挪动主体），"
                           "其次 move_camera（换机位）",
    "edge_clip": "reframe（拉远或调整构图）",
    "occlusion": "move_character（先挪开前景遮挡者或挪动主体），"
                 "其次 move_camera（换机位避开遮挡）",
    "framing_too_tight": "reframe（拉远距离或降焦段）",
    "framing_too_loose": "reframe（推近距离或升焦段）",
    "headroom_off": "move_camera（调整机位高度或俯仰）",
    "lead_room_short": "move_camera（横移对准点）",
    "thirds_deviation": "accept（声明刻意构图）",
    "size_drift": "move_camera（锁定机位与焦段）",
    "sudden_jump": "move_camera（检查机位/焦段关键帧）",
    "unplanned_exit": "move_character（调整走位时机）",
    "jump_cut_risk": "reframe（换角度或换景别）",
    "axis_screen_order": "move_camera（回到正确的轴侧，保持主体在前；"
                         "优先 reframe）",
    "pace_monotony": "accept（声明刻意节奏）",
}

#: evidence 里"阈值/上限"类键（渲染成 ``实测 vs 阈值``，不是另一个实测值）。
_GUARD_THRESHOLD_KEYS = frozenset({
    "edge_clip_max", "lead_room_min", "occlusion_warn", "jump_ratio",
    "size_drift", "jump_cut_size_diff", "jump_cut_angle_deg", "sustain_frames",
    "threshold",
})


def _guard_numbers(warning) -> str:
    """一条告警的「实测 vs 区间/阈值」数值文本（只收可 JSON 的数值）。"""
    measured: List[str] = []
    thresholds: List[str] = []
    band = ""
    for key, value in (warning.evidence or {}).items():
        if key == "expected_range":
            if isinstance(value, (list, tuple)) and len(value) == 2:
                band = f"区间 [{value[0]:g}, {value[1]:g}]"
            continue
        if key in _GUARD_THRESHOLD_KEYS:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                thresholds.append(f"{key}={value:g}")
            continue
        if (key in ("frames", "merged", "shot_type", "previous_shot")
                or not isinstance(value, (int, float))
                or isinstance(value, bool)):
            continue
        measured.append(f"{key}={value:g}")
    numbers = "、".join(measured) or "（无实测数值）"
    if band:
        return f"{numbers} vs {band}"
    if thresholds:
        return f"{numbers} vs {'、'.join(thresholds)}"
    return numbers


def guard_warning_line(warning) -> str:
    """每条告警一行：「现象 + 实测 vs 区间 + 一个可选动作」（卡 B4 钉死）。"""
    kind = str(getattr(warning, "type", "") or "")
    subject = str(getattr(warning, "subject", "") or "scene")
    start, end = (getattr(warning, "frame_range", None) or (0, 0))[:2]
    severity = str(getattr(getattr(warning, "severity", None), "value", "")
                   or getattr(warning, "severity", ""))
    phenomenon = GUARD_PHENOMENON.get(kind, kind)
    action = GUARD_FIX_ACTION.get(kind, "accept（声明刻意）")
    return (f"- [{kind}] ({severity}) {subject} @帧{start}-{end} "
            f"{phenomenon}：{_guard_numbers(warning)}。可选动作：{action}")


def guard_action_menu() -> str:
    """固定四选一菜单 + accept 的留痕契约。"""
    return ("可选动作菜单（每条告警必须且只能选一个）："
            "move_camera / reframe（改焦段或距离）/ move_character / "
            "accept（声明刻意——必须在回复正文里逐条写 "
            f"`{GUARD_ACCEPT_PREFIX} <warning_type> <reason>`，引擎会把每一条"
            "落成 guard_verdict 审计事件，绝不静默）")


def render_guard_warnings(warnings) -> str:
    """修复提示里的告警段；error/warning 才打扰，info 默认不注入。"""
    items = [item for item in (warnings or [])
             if str(getattr(getattr(item, "severity", None), "value", "")
                    or getattr(item, "severity", "")) in ("error", "warning")]
    if not items:
        return ""
    lines = [f"视锥校验报出 {len(items)} 条告警（带数值证据，请逐条裁决并动手）："]
    lines.extend(guard_warning_line(item) for item in items)
    lines.append(guard_action_menu())
    return "\n".join(lines)


def guard_verdict(shot_id: str, warning_type: str, *, accepted: bool,
                  reason: str = "", fix_action: str = "") -> Dict[str, Any]:
    """B4：LLM 对单条告警的裁决记录（``guard_verdict`` 事件契约）。

    五个字段与 ``contracts/audit.py::V16_EVENT_FIELDS["guard_verdict"]``
    逐键一致。accept 必须留痕——本函数就是那一条痕；记录由驱动器写进审计。
    """
    if not str(warning_type).strip():
        raise ValueError("guard_verdict.warning_type 不能为空")
    return {
        "shot_id": str(shot_id),
        "warning_type": str(warning_type),
        "accepted": bool(accepted),
        "reason": str(reason or ""),
        "fix_action": str(fix_action or ""),
    }


def parse_guard_accepts(text: str, *, shot_id: str = "") -> List[Dict[str, Any]]:
    """解析修复回复正文里的 ``ACCEPT <warning_type> <reason>`` 声明。

    每行一条，产出 :func:`guard_verdict`（accepted=True, fix_action="accept"）。
    没有声明返回空列表；形如 ``ACCEPT`` 却缺 warning_type 的行抛
    ``ValueError``——格式错了就报错，不把一次 accept 静默丢掉。
    """
    accepts: List[Dict[str, Any]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line.upper().startswith(GUARD_ACCEPT_PREFIX):
            continue
        tail = line[len(GUARD_ACCEPT_PREFIX):]
        if tail and not tail[0].isspace():
            continue                  # "ACCEPTED ..." 不是 accept 声明
        rest = tail.strip()
        if not rest:
            raise ValueError(
                f"{GUARD_ACCEPT_PREFIX} 声明缺 warning_type：{raw_line!r}")
        parts = rest.split(None, 1)
        warning_type = parts[0].strip()
        reason = parts[1].strip() if len(parts) > 1 else ""
        accepts.append(guard_verdict(shot_id or "", warning_type,
                                     accepted=True, reason=reason,
                                     fix_action="accept"))
    return accepts


def timeline_only(audit: AuditResult) -> bool:
    """这条审计的 error 是否**全部**属于时间轴类。

    只有全中时才收窄工具集：混合审计（例：R003 ＋ 构图低分）还要用场景工具
    修构图那一半，把工具拿掉反而少修一条。
    """
    rules = {str(item.rule) for item in getattr(audit, "errors", [])}
    return bool(rules) and rules <= TIMELINE_RULES


def _offers_the_draft_tool(registry) -> bool:
    """注册表里有没有 `emit_shot_draft`（假注册表没有 ``__contains__`` 时不炸）。"""
    try:
        return SHOT_DRAFT_TOOL in registry
    except TypeError:                      # 鸭子类型的最小替身：不可迭代也不算
        return False


REPAIR_SYSTEM_PROMPT = """\
你是白模预演的执行导演。当前镜头**未通过校验**，请只修复下列问题，
其余内容保持不变。

{focus}

{audit}

{guard}
可用角色（**只能逐字**使用这些名字；名单之外的名字一律是幻觉，不许写进
`shot.characters` / `actions` / `dialogues`）：{roster}

当前场景：
{scene_state}

{dialogue_budget}
**动作参数只能用它自己那一行的键**（下表就是唯一真源，由引擎的参数表生成）。
写别的键、或用同义词，**整条草案会被退回**，这一镜就只剩计划里的内容了——
实测（2026-10-04 的 64 镜真跑 `long19`）：修复回合为了错开 R003 重提草案，
因为表不在手上而给 `body_tilt`/`turn_head` 写了表外的键名，整条被退回、
R003 一直红到收尾。
{action_params}

**运镜 `amount` 的单位**（下表同样唯一真源；写错会让机位跑出画面）：
{movement_units}

**拍点与构图的闭集字段**（重提这一镜草案时，每个字段只写下列值之一，逐字、
不加前缀、不写描述句）：
{closed_sets}

要求：
- **先看清每一条问题该由谁来修**（用错工具 = 修不动，白烧一次修复回合）：
  · **时间轴类**（`R003` 同角色动作重叠、`R011` 台词装不下、`R015` 时长不符）：
    必须**重新提交这一镜的草案**（`emit_shot_draft`，把错开的起止帧写进去）。
    计划里的动作表只有这条路径能改——用场景工具（`character_action` 等）只会
    **再叠加一段动画**，原动作表原封不动，问题会一直红下去。实测（2026-10-03 的
    64 镜真跑）：383 次 `R003` 与 126 次修复调用、101 次降级，绝大多数就是这么烧掉的。
  · **空间/构图类**（`R002` 穿模、`R005` 出画、`R001` 轴线、构图分低）：
    用场景工具挪机位、挪人、调焦距、加道具，然后用复核工具确认。
  · **机位调整红线**（构图修复专用；违反会触发回滚重建，白烧这一回合）：
    主体永远保持在**相机前方**；动/重建机位时不要穿过主体、不要越过
    180° 轴线；主体被前景遮挡时优先 `move_character` 挪开遮挡者或挪动主体，
    再考虑 `reframe`（改距离/焦段），最后才 `move_camera`。
- 必须**调用工具**实际修改，不要只在回复里描述计划；
- 只改与问题相关的部分，不要顺手重做整个镜头；
- 修改后用 check_composition / check_axis 复核一次；
- 问题已解决就直接停止调用工具。
"""


def _vlm_correction_text(audit: AuditResult, shot_id: str) -> str:
    """vlm-feedback 卡 V6：把 VLM v2 判词与几何告警合成纠正候选（提示侧）。

    注入条件**全部**成立才返回非空文本：``vlm_review`` 是 dict、
    ``status=="ok"``、``schema=="vlm-review/v2"``、``disposition.status``
    不是 ``escalate_human``（无 disposition 键视为可注入）、合成出的候选
    非空。任一条件不成立 ⇒ 返回空串（不注入、不改模板）。

    注入文本 = ``render_candidates(candidates, shot_id_for_text, max_chars=300)``；
    ``shot_id_for_text`` 依次取参数 ``shot_id``、记录里的 ``shot_id``、
    ``audit.target``，三者都空 ⇒ 不注入。VLM 只作提示，永不进门。
    """
    record = getattr(audit, "vlm_review", None)
    if not isinstance(record, dict):
        return ""
    if record.get("status") != "ok":
        return ""
    if record.get("schema") != VLM_REVIEW_SCHEMA_V2:
        return ""
    disposition = record.get("disposition")
    if isinstance(disposition, dict) and \
            disposition.get("status") == "escalate_human":
        return ""
    issues = record.get("issues")
    if not isinstance(issues, list):
        return ""                     # 形状残缺 ⇒ 条件不成立，逐字节不变
    #: 延迟导入：correction_candidates 顶层 ``from .repair import
    #: guard_warning_line``，模块级反向导入会成环。
    from .correction_candidates import (build_correction_candidates,
                                        render_candidates)
    candidates = build_correction_candidates(
        getattr(audit, "guard_warnings", None), issues)
    if not candidates:
        return ""
    shot_id_for_text = str(shot_id or "")
    if not shot_id_for_text:
        shot_id_for_text = str(record.get("shot_id") or "")
    if not shot_id_for_text:
        shot_id_for_text = str(getattr(audit, "target", "") or "")
    if not shot_id_for_text:
        return ""
    return render_candidates(candidates, shot_id_for_text, max_chars=300)


def _framing_summary_lines(digest: Dict[str, Any]) -> List[str]:
    """画面摘要行（卡 V12）：每个主体取 ``framing`` 里**首帧**数据一行。

    形状 ``{subject}｜中心({x},{y})在{thirds_cell}｜占画高{h}｜
    {动作安全区内/越出动作安全区}``；数值沿用 ``framing_digest`` 已折好的
    3 位小数，不再四舍五入。坏形状的条目（非列表/非 dict）跳过，不崩。
    """
    subjects = (digest.get("framing") or {}).get("subjects") or {}
    if not isinstance(subjects, dict):
        return []
    lines: List[str] = []
    for subject in sorted(subjects, key=str):
        records = subjects[subject]
        if not isinstance(records, list) or not records:
            continue
        first = records[0]
        if not isinstance(first, dict):
            continue
        center = first.get("center")
        if not isinstance(center, (list, tuple)) or len(center) != 2:
            continue
        in_safe = "动作安全区内" if bool(first.get("in_action_safe")) \
            else "越出动作安全区"
        lines.append(
            f"{subject}｜中心({center[0]},{center[1]})在"
            f"{first.get('thirds', '')}｜占画高"
            f"{first.get('screen_height_ratio', '')}｜{in_safe}")
    return lines


def build_vlm_guard_summary(warning_text: str,
                            scene_digest: Optional[Dict[str, Any]],
                            *, max_chars: int = 1800) -> str:
    """拼 VLM 评审的 ``guard_summary``（卡 V12）：告警行 → 画面行 → 空间行。

    - ``scene_digest`` 为空 ⇒ 原样返回 ``warning_text``（与卡 V3 改动前
      逐字节一致，评审提示零形状差）；
    - 非空 ⇒ 按上述顺序追加，总长 ≤ ``max_chars``：**整行追加**，放不下的
      那一行起整行舍弃（绝不截半行）；空间段用
      :func:`render_spatial_digest`（上限 1200 字，同一条渲染文本）。
    """
    if not isinstance(scene_digest, dict) or not scene_digest:
        return str(warning_text or "")
    if max_chars <= 0:
        return ""
    lines: List[str] = []

    def fits(line: str) -> bool:
        current = len("\n".join(lines)) if lines else 0
        cost = len(line) + (1 if lines else 0)
        return current + cost <= max_chars

    for line in str(warning_text or "").splitlines():
        if not fits(line):
            break
        lines.append(line)
    for line in _framing_summary_lines(scene_digest):
        if not fits(line):
            break
        lines.append(line)
    spatial = scene_digest.get("spatial")
    if isinstance(spatial, dict):
        rendered = render_spatial_digest(spatial, max_chars=1200)
        for line in rendered.splitlines():
            if not fits(line):
                break
            lines.append(line)
    return "\n".join(lines)


def scene_digest_repair_text(audit: AuditResult, shot_id: str, *,
                             max_chars: int = 1200) -> str:
    """修复提示里的几何测量事实段（卡 V12）。

    ``audit.scene_digest`` 非空 ⇒
    ``【几何测量事实｜镜 {shot_id}】`` + :func:`render_spatial_digest`（上限
    ``max_chars``，与评审提示同一份渲染文本）；shot_id 参数为空时回退
    ``audit.target``。摘要缺失/空间段渲染为空 ⇒ 返回空串（不追加）。
    """
    digest = getattr(audit, "scene_digest", None)
    if not isinstance(digest, dict) or not digest:
        return ""
    shot = str(shot_id or "")
    if not shot:
        shot = str(getattr(audit, "target", "") or "")
    if not shot:
        return ""
    spatial = digest.get("spatial")
    if not isinstance(spatial, dict):
        return ""
    rendered = render_spatial_digest(spatial, max_chars=max_chars)
    if not rendered:
        return ""
    return f"【几何测量事实｜镜 {shot}】\n{rendered}"


def build_repair_payload(audit: AuditResult, registry, *,
                         scene_state: str = "", temperature: float = 0.2,
                         shot=None,
                         shot_id: str = "",
                         max_tokens: Optional[int] = None,
                         request_id: Optional[str] = None,
                         roster: Optional[Sequence[str]] = None,
                         diff_block: str = ""
                         ) -> ChatPayload:
    """构造一次修复请求。``registry`` 提供可调用的工具 schema。

    ``shot`` 给了就附上这一镜的**对白帧预算**（§4.4）。没有它时，修复
    提示只会说"重新提交这一镜的草案、把起止帧错开"——而模型手上既没有
    每句要几帧、也没有那 12 帧余量是多少，只能再猜一遍（实测：
    2026-10-03 的 64 镜真跑里 26 个镜头的 S6 一直红到收尾）。

    ``shot_id`` 是**本次要修的镜头**。提示词里必须写死它：场景摘要里的
    "当前镜头"是 `SceneContext.current_shot_id`（构建时落在第一镜），
    实测（`long10`）7 次 `emit_shot_draft` 里有 2 次把 `shot_id` 写成了
    `shot_001`——正是那条过期的摘要值，于是真正要修的 `shot_043` 一直没被改。

    纯时间轴审计还会把工具集**收窄到** `emit_shot_draft` ＋ 控制类工具：
    提示词早就写着"用场景工具修不动时间轴"，可实测修复回合仍然是
    86 次 `get_scene_state` / 65 次 `check_composition` / 40 次
    `check_visibility` 对 7 次 `emit_shot_draft`——叫不动就换工具集。
    """
    budget_text = ""
    if shot is not None:
        budget = shot_dialogue_budget(shot)
        if budget.lines:
            budget_text = budget.render() + "\n"
    guard_text = render_guard_warnings(getattr(audit, "guard_warnings", None))
    focus = ""
    if shot_id:
        focus = (f"**本次要修的镜头：`{shot_id}`**。"
                 f"用 `{SHOT_DRAFT_TOOL}` 时 `shot_id` 必须写成它"
                 f"（场景摘要里的\"当前镜头\"是场景默认值，不是本次的目标）。")
    #: 注册表里没有 `emit_shot_draft`（例：纯单测的最小注册表）时不收窄——
    #: 收窄到空工具集会让 `tool_choice=required` 的请求直接无法满足。
    narrow = timeline_only(audit) and _offers_the_draft_tool(registry)
    if narrow:
        focus += ("\n\n这条审计**全部是时间轴类**问题 ⇒ 本次请求的工具集**只有**"
                  f" `{SHOT_DRAFT_TOOL}` 与控制类工具：请直接重新提交这一镜的草案，"
                  "把错开的起止帧写进去。")
    #: 参数表与运镜单位表**必须和编辑器用的是同一份**（`editor.render_action_params`
    #: / `render_movement_units`）：修复回合最常见的动作就是"重提这一镜的草案"，
    #: 表不在手上时模型会自己发明键名，整条草案被退回、原来的问题一直红到收尾
    #: （实测 2026-10-04：`body_tilt(lean_deg)`、`turn_head(direction_deg)`）。
    from .editor import (render_action_params, render_closed_sets,
                         render_movement_units)

    system_text = REPAIR_SYSTEM_PROMPT.format(
        focus=focus,
        audit=audit.format_for_llm(),
        guard=guard_text,
        roster="、".join(str(item) for item in roster)
        if roster else "（未提供）",
        scene_state=scene_state or "（尚未采集）",
        dialogue_budget=budget_text,
        action_params=render_action_params(),
        movement_units=render_movement_units(),
        closed_sets=render_closed_sets())
    #: vlm-feedback 卡 V6/V12：纠偏建议与几何测量事实只作提示追加；任一
    #: 注入条件不成立时与改动前逐字节相同（d1 合入保留）。
    correction_text = _vlm_correction_text(audit, shot_id)
    if correction_text:
        system_text += "\n\n" + correction_text
    digest_text = scene_digest_repair_text(audit, shot_id)
    if digest_text:
        system_text += "\n\n" + digest_text
    #: 空间理解/设计快照：设计 vs 实测偏差块（Ticket 05）。空 -> 零形状差，
    #: 与改动前的提示逐字节一致；非空以整块追加（长度上限由渲染函数保证）。
    if diff_block:
        system_text += "\n\n" + diff_block
    tools = (registry.schemas_only(SHOT_DRAFT_TOOL, *CONTROL_TOOL_NAMES)
             if narrow else registry.schemas_except("emit_plan"))
    return ChatPayload(
        messages=[
            Message(role=MessageRole.SYSTEM, content=system_text),
            Message(role=MessageRole.USER,
                    content="请调用工具修复上面的问题。"),
        ],
        # 修复阶段不给 emit_plan：计划的唯一入口是阶段 A（§7.1）
        tools=tools,
        tool_choice=ToolChoice.REQUIRED,
        temperature=temperature,
        max_tokens=max_tokens,
        purpose=Purpose.REPAIR,
        request_id=request_id or new_request_id(),
    )
