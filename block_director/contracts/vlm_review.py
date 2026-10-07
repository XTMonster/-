"""VLM 评审外回路（执行文档 v1.5 §5.5 / 卡 P6-T1）——**纯 Python**。

本模块是 P6-T1 的**无 bpy** 半边：rubric、请求装配、响应解析与"重试一次后
放弃"的策略都在这里，`layer3_engine/shot_auditor.py` 只负责取帧调用它。
这样"默认关⇒零行为差""评委不可用⇒跳过并记录"两条纪律可以脱离 Blender
单测（与 `contracts/beats.py::reconcile_justifications` 同一分工）。

**它不是门**：结果只进 `shots.json` 与面板展示，**不参与任何既有门**
（`AuditResult.passed` / `score` / `errors` 一个字节都不受影响；TDD §5.5 的
"不作唯一裁决"）。

调用形状（OpenAI 兼容 vision）::

    messages=[
        Message(role=SYSTEM, content=<rubric 文本>),
        Message(role=USER, content=[{"type": "text", ...},
                                    {"type": "image_url",
                                     "image_url": {"url": "data:image/png;base64,…"}}]),
    ]

`Message.content` 直到 P6-T1 都只声明了 `str`；vision 请求体要求 content 是
**分片数组**，因此 `contracts/messages.py` 的类型标注与 `specs/openapi.yaml`
的 `Message.content` 同批放宽为 `string | array | null`（两条都被
`tests/test_openapi_matches_contracts.py` 钉住）。
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .enums import MessageRole, Purpose, ToolChoice
from .messages import ChatPayload, ChatReply, Message

#: 外部评审判词形状的版本号——写进每一条评审记录，便于日后解释"当时用的是哪把尺"。
REVIEW_SCHEMA_VERSION = "vlm-review/v1"

#: 每镜取哪三帧（TDD §5.5："每镜首帧/中帧/末帧"）。顺序即请求里的顺序。
FRAME_LABELS: Tuple[str, ...] = ("first", "middle", "last")

#: 1–5 档的锚点。**不是** E1 案例相关率那把尺（那把尺在
#: `tools/knowledge/e1_panel.py`，判据 `RELEVANT = 4.0`，红线圈死）。
#: 这里的五档只服务于"候选排序与人审参考"，所以措辞落在**白模 blocking 能
#: 看见的东西**上（形体可读性/视线留白/主体是否被压边），不假装能判表演。
REVIEW_RUBRIC: Dict[int, str] = {
    1: "主体不可辨：压边、出画、被遮挡，或压根看不出这一镜要说什么",
    2: "勉强可辨：主体在画内但严重偏边/偏小，观者要先找人才看得懂",
    3: "合格白模：主体清楚、留白可用，但因构图平庸而有明显改进余地",
    4: "好：主体占位与视线留白配合得当，景别与构图意图一致",
    5: "很好：构图服务叙事（留白/失衡/纵深被刻意使用），一眼可读且有意图",
}

#: 评审提示词。刻意把"只输出 JSON"写死，且**只**要 score + reason 两个键——
#: 解析器不认识别的形状，模型多说反而会被判为不可用（记录在案，不猜）。
SYSTEM_PROMPT = (
    "你是白模预演（blocking）的摄影评审员。给你同一镜头的首/中/末三帧（按顺序），"
    "以及这一镜的意图与构图声明。请只评判**画面本身**能否承担这次拍摄，"
    "不要评判剧本、表演或后期。\n\n"
    "评分锚点（1–5）：\n"
    + "\n".join(f"{score}. {text}" for score, text in REVIEW_RUBRIC.items())
    + "\n\n只输出一个 JSON 对象，不要解释、不要代码块："
    '{"score": <1-5 的整数>, "reason": "<不超过 40 字的一句理由>"}'
)


class VlmReviewError(ValueError):
    """评审响应不可用（形状不对/分数越界/没有正文）——可重试一次。"""


# --------------------------------------------------------------------------- #
# 帧
# --------------------------------------------------------------------------- #
def frame_indices(start_frame: int, end_frame: int) -> List[Tuple[str, int]]:
    """首/中/末三帧的 (label, frame) —— 单帧镜头三张同号（不重复渲染同一帧）。"""
    start = int(start_frame)
    end = int(end_frame)
    if end < start:
        start, end = end, start
    middle = start + (end - start) // 2
    pairs: List[Tuple[str, int]] = []
    for label, frame in zip(FRAME_LABELS, (start, middle, end)):
        if pairs and pairs[-1][1] == frame:
            continue
        pairs.append((label, frame))
    return pairs


def frame_data_uri(path) -> str:
    """把一张渲染好的图读成 data URI（stdlib base64；格式按扩展名判）。"""
    target = Path(path)
    suffix = target.suffix.lower().lstrip(".") or "png"
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
    payload = base64.b64encode(target.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def build_review_messages(*, shot_id: str, frames: Sequence[Tuple[str, str]],
                          intent: str = "",
                          composition: Optional[Dict[str, Any]] = None,
                          ) -> List[Message]:
    """装配一次评审请求的消息列表。

    ``frames`` 是 ``(label, data_uri)`` 序列——**已经是** data URI，读盘/编码由
    调用方做（帧的取得是 bpy 侧的事）。空帧列表 ⇒ :class:`VlmReviewError`
    （"没有画面可评"不该假装评过）。
    """
    if not frames:
        raise VlmReviewError("没有可评审的帧（frames 为空）")
    lines = [f"镜号：{shot_id}"]
    lines.append(f"意图：{intent.strip() or '（未声明）'}")
    declaration = dict(composition or {})
    lines.append("构图声明："
                 + (json.dumps(declaration, ensure_ascii=False)
                    if declaration else "（未声明）"))
    lines.append("像素顺序：" + " → ".join(label for label, _ in frames))
    parts: List[Dict[str, Any]] = [{"type": "text", "text": "\n".join(lines)}]
    for label, uri in frames:
        parts.append({"type": "text", "text": f"【{label}】"})
        parts.append({"type": "image_url", "image_url": {"url": uri}})
    return [
        Message(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        Message(role=MessageRole.USER, content=parts),
    ]


def build_review_payload(*, shot_id: str, frames: Sequence[Tuple[str, str]],
                         intent: str = "",
                         composition: Optional[Dict[str, Any]] = None,
                         max_tokens: int = 256) -> ChatPayload:
    """评审用的 :class:`ChatPayload`：temperature=0、无工具、``purpose=review``。"""
    return ChatPayload(
        messages=build_review_messages(shot_id=shot_id, frames=frames,
                                       intent=intent, composition=composition),
        tools=[],
        tool_choice=ToolChoice.NONE,
        temperature=0.0,
        purpose=Purpose.REVIEW,
        max_tokens=int(max_tokens),
    )


# --------------------------------------------------------------------------- #
# 响应
# --------------------------------------------------------------------------- #
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_review_reply(reply: ChatReply) -> Dict[str, Any]:
    """从一次回复里抠出 ``{"score": int, "reason": str}``；抠不出就报错。

    容忍 ```json 围栏与前后废话（``_JSON_OBJECT`` 取第一个平衡意义上的大括号块），
    但**分数必须落在 1–5 的整数**上——越界就抛 :class:`VlmReviewError`，
    由调用方按"重试一次后放弃"处理，不许夹到边界（那是静默降级）。
    """
    content = getattr(reply, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise VlmReviewError("评审回复没有正文（content 为空）")
    match = _JSON_OBJECT.search(content)
    if match is None:
        raise VlmReviewError(f"评审回复里找不到 JSON 对象：{content[:120]!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise VlmReviewError(f"评审 JSON 解析失败：{exc}")
    if not isinstance(data, dict):
        raise VlmReviewError("评审 JSON 不是对象")
    raw = data.get("score")
    if isinstance(raw, bool) or raw is None:
        raise VlmReviewError(f"评审缺少 score：{data!r}")
    try:
        score = int(raw)
    except (TypeError, ValueError):
        raise VlmReviewError(f"评审 score 不是整数：{raw!r}")
    if isinstance(raw, float) and float(raw) != float(score):
        raise VlmReviewError(f"评审 score 不是整数：{raw!r}")
    if not (1 <= score <= 5):
        raise VlmReviewError(f"评审 score 越界（1–5）：{raw!r}")
    reason = data.get("reason")
    return {"score": score,
            "reason": str(reason).strip() if reason is not None else ""}


# --------------------------------------------------------------------------- #
# 策略：重试一次后放弃
# --------------------------------------------------------------------------- #
def review_shot(transport, *, shot_id: str,
                frames: Sequence[Tuple[str, str]],
                intent: str = "",
                composition: Optional[Dict[str, Any]] = None,
                timeout: float = 60.0,
                attempts: int = 2,
                max_tokens: int = 256) -> Dict[str, Any]:
    """评一镜，返回一条**总是可记**的记录。

    成功 → ``{"status": "ok", "score", "reason", "attempts", "schema"}``；
    失败（超时 / 429 / 524 / 形状不对）→ ``{"status": "skipped",
    "reason": <原因>, "error": <最后一次异常文本>, "attempts", "schema"}``。

    ``attempts=2`` 就是卡里那句"重试一次后放弃"——**不做指数退避**（README
    环境约束：GLM 类调用串行、评委抖动的根因未查），也不把失败吞成 0 分。
    调用方必须把 ``status="skipped"`` 如实落盘：跳过 ≠ 通过。
    """
    if not frames:
        return {"status": "skipped", "reason": "没有可评审的帧",
                "error": "frames 为空", "attempts": 0,
                "schema": REVIEW_SCHEMA_VERSION}
    payload = build_review_payload(shot_id=shot_id, frames=frames, intent=intent,
                                   composition=composition, max_tokens=max_tokens)
    last_error = ""
    tries = max(1, int(attempts))
    for attempt in range(1, tries + 1):
        try:
            reply = transport.chat(payload, timeout=timeout)
            parsed = parse_review_reply(reply)
        except Exception as exc:  # noqa: BLE001 - 评委不可用＝跳过并记录（§5.5）
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        return {"status": "ok", "score": parsed["score"],
                "reason": parsed["reason"], "attempts": attempt,
                "schema": REVIEW_SCHEMA_VERSION}
    return {"status": "skipped", "reason": "评委不可用（重试一次后放弃）",
            "error": last_error or "未知错误",
            "attempts": tries, "schema": REVIEW_SCHEMA_VERSION}


def summarise_reviews(reviews: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """把逐镜记录汇总成一行（面板/README 用）。

    只统计**真的评过**的镜（``status == "ok"``）；被跳过的单独计数——"跳过"
    与"评过且低分"必须分得开，否则"看得见的降级"又变成看不见的。
    """
    scored = {shot_id: int(item.get("score") or 0)
              for shot_id, item in (reviews or {}).items()
              if str(item.get("status")) == "ok"}
    skipped = [shot_id for shot_id, item in (reviews or {}).items()
               if str(item.get("status")) != "ok"]
    total = sum(scored.values())
    return {"reviewed": len(scored), "skipped": len(skipped),
            "skipped_shots": sorted(skipped),
            "mean_score": round(total / len(scored), 3) if scored else None,
            "schema": REVIEW_SCHEMA_VERSION}
