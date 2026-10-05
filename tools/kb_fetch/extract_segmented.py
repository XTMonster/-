"""P4：两趟「分段 → 归属」抽取器（`extract/v19-seg`）。

**算法参考，零拷贝**：结构取自 `LHRLAB/HyperGraphRAG@d587cdf8c3fe`
（MIT）的两趟做法——先切"完整知识片段"，再把片段里的耦合归到片段上。
上游那一层的载荷是"一句话 ＋ 0–10 完整度分"，**没有类型／角色／槽位**
（见 `docs/knowledge/S2_UPSTREAM_PREMISE.md` 的逐行实测），所以在我们的槽位
schema 下"移植上游抽取层"不成立；本模块按**本仓 schema 自实现**，
只借它的结构。按 ADR-0014 的判例，这层翻译／实现算**自研**。

三条纪律：

1. **闭集是单一真源**：边型、角色、kind 一律从 `block_director.knowledge.hypergraph`
   读，本模块不许自带第二份清单（`check_hypergraph.py` 的注释点名过这个坑）。
2. **拒收必须具名**：闭集外的一切进 `rejects`，带 `reason`，**绝不静默丢弃**——
   本项目最反复踩的就是"静默 no-op"（S0 的缓存键、`53d3e3f` 的手抄漂移同族）。
3. **每条草稿带出处**：哪份来源（url ＋ sha256）＋ 在正文里的 `span`。
   P5 的构建按 `span` 回到那段文字取证，不许出现"指向空气"的成员。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

try:
    from . import common  # type: ignore
except ImportError:  # pragma: no cover - 直跑
    from tools.kb_fetch import common  # type: ignore

from block_director.knowledge import hypergraph as hg  # noqa: E402

#: 提到模型的那一版提示词的版本号（进缓存键的 `prompt_version` 分量）。
PROMPT_VERSION = "extract/v19-seg"

#: 一段最多多少字符（超出按句号再切；再超出就硬切）。取 2400 与
#: `common.CHUNKER_VERSION = "para-2400/v1"` 同量级，便于与现役产物对拍。
DEFAULT_MAX_CHARS = 2400

#: 短于这个长度的段**不送模型**（站点样板与残句）。实测依据：抽掉 HTML 之后，
#: 文章页开头仍是 "Skip to main content"／标题一类的碎片，模型对它们返空是对的。
DEFAULT_MIN_CHARS = 80


@dataclass(frozen=True)
class Segment:
    """一段"完整知识片段"：`span` 是**在原文里的**连续区间，`text` 是它去空白后的样子。"""

    index: int
    text: str
    span: Tuple[int, int]
    source_ref: Dict


_PARA_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[。！？；])")


def _hard_split(text: str, start: int, cap: int) -> List[Tuple[int, int]]:
    """没有任何句读的长串：按 `cap` 硬切（宁可切得难看，也不许丢字）。"""
    out: List[Tuple[int, int]] = []
    cursor = start
    while cursor < start + len(text):
        out.append((cursor, min(cursor + cap, start + len(text))))
        cursor += cap
    return out


def _split_block(block: str, start: int, cap: int) -> List[Tuple[int, int]]:
    """把一个段落按句子攒到不超过 `cap`；攒不下就开新块。"""
    spans: List[Tuple[int, int]] = []
    cursor = start
    pending = ""
    for piece in _SENTENCE_END.split(block):
        if not piece:
            continue
        if len(piece) > cap:
            if pending:
                spans.append((cursor, cursor + len(pending)))
                cursor += len(pending)
                pending = ""
            for sub_start, sub_end in _hard_split(piece, cursor, cap):
                spans.append((sub_start, sub_end))
            cursor += len(piece)
            continue
        if len(pending) + len(piece) > cap and pending:
            spans.append((cursor, cursor + len(pending)))
            cursor += len(pending)
            pending = piece
        else:
            pending += piece
    if pending:
        spans.append((cursor, cursor + len(pending)))
    return spans


def segment_text(text: str, *, source_ref: Dict, max_chars: int = DEFAULT_MAX_CHARS
                 ) -> List[Segment]:
    """把正文切成若干"完整知识片段"。**确定性**，且**覆盖全部正文**。

    `span` 连续且首尾相接（拼起来正好是 `text`），所以调用方任何时候都能
    按 `text[span[0]:span[1]]` 回到原文——这是"成员级依据"能成立的前提。
    """
    if max_chars <= 0:
        raise ValueError("max_chars 必须为正，收到 %r" % (max_chars,))
    spans: List[Tuple[int, int]] = []
    cursor = 0
    for match in list(_PARA_BREAK.finditer(text)) + [None]:
        end = match.start() if match is not None else len(text)
        if end > cursor:
            block = text[cursor:end]
            spans.extend(_split_block(block, cursor, max_chars))
            cursor = end
        if match is not None:
            cursor = match.end()
    if not spans and text:
        spans = _split_block(text, 0, max_chars)
    segments: List[Segment] = []
    for index, (start, end) in enumerate(spans):
        chunk = text[start:end]
        if not chunk.strip():
            continue
        segments.append(Segment(index=len(segments), text=chunk.strip(),
                                span=(start, end), source_ref=dict(source_ref or {})))
    return segments


def segments_of(record: Dict, *, max_chars: int = DEFAULT_MAX_CHARS) -> List[Segment]:
    """一条记录的片段。**自带出处指针时就当原子段**，不再重新分段。

    台账 ⑪ 的修法。为什么必须这样（实测 2026-10-05）：A 路把蒸馏出的短陈述当记录喂回来，
    而 `extract()` 会把它**又分一次段**——草稿的 `span` 于是相对**陈述串**，
    丢了指向原语料段的指针，影子构建里 3/3 全判 `no_segment_for_span`。

    判据：记录里 `source = {url, sha256, span:[start,end]}` 且 `start < end` ⇒
    整条文本就是那个 span，`Segment.span` 原样用它（P5 的卡片按原 span 建，能对上）。
    """
    pointer = record.get("source")
    span = (pointer or {}).get("span") if isinstance(pointer, dict) else None
    if isinstance(span, (list, tuple)) and len(span) == 2:
        try:
            start, end = int(span[0]), int(span[1])
        except (TypeError, ValueError):
            start = end = -1
        if 0 <= start < end:
            text = str(record.get("text") or "").strip()
            if text:
                return [Segment(index=0, text=text, span=(start, end),
                                source_ref=dict(record.get("source_ref") or {}))]
    return segment_text(str(record.get("text") or ""),
                        source_ref=dict(record.get("source_ref") or {}),
                        max_chars=max_chars)


def _role_for_kind(edge_type: str, kind: str) -> str:
    """在 schema 里查 `(边型, kind)` 对应的角色（必填优先，其次可选）。查不到给空串。"""
    for table in (hg.REQUIRED_MEMBERS, getattr(hg, "OPTIONAL_MEMBERS", {})):
        for role, candidate in table.get(edge_type, ()):
            if candidate == kind:
                return role
    return ""


def normalise_members(members, edge_type: str = "") -> List[List]:
    """把成员**形状**归一成 `[role, kind, node_id(, evidence)]`。**只改形状，不造内容。**

    实测（2026-10-05 的 scoped 试点）：21 条草稿里 **19 条**是同一种滑倒——
    模型把角色与 kind 合成一格写成 `["allow/emotion", "emotion:喜悦"]`（两段），
    拒收原因清一色 `bad_role:allow/emotion`。有的模型则给
    `{"role":…,"kind":…,"node_id":…}`。

    这两类都归一化；**归一化不是放宽判据**：闭集（边型／角色／kind）与必填槽位照样
    由 `validate_draft` 与现役 `to_edge` 把关，归一化只是把"同一件事的另一种写法"
    还原成契约形状（与 `to_edge` 里既有别名归一同一性质）。
    """
    out: List[List] = []
    for item in members or []:
        if isinstance(item, dict):
            role = item.get("role")
            kind = item.get("kind")
            node_id = item.get("node_id") or item.get("node") or item.get("value")
            evidence = item.get("evidence") or item.get("quote")
            if role is not None and kind is not None and node_id is not None:
                row = [str(role), str(kind), str(node_id)]
                if evidence:
                    row.append(str(evidence))
                out.append(row)
                continue
            out.append(item)
            continue
        if not isinstance(item, (list, tuple)):
            out.append(item)
            continue
        row = [str(part) for part in item]
        if len(row) == 2:
            #: `["allow/emotion", "emotion:喜悦"]`：角色与 kind 合成一格。
            head = row[0]
            if "/" in head:
                role, _sep, kind = head.partition("/")
                if role in hg.ROLES and kind:
                    out.append([role, kind, row[1]])
                    continue
            out.append(row)
            continue
        if len(row) >= 3:
            first, second, third = row[0], row[1], row[2]
            if first in hg.ROLES and second in hg.ALLOWED_KINDS:
                out.append([first, second, *row[2:]])
                continue
            if "/" in first:
                role, _sep, kind = first.partition("/")
                if role in hg.ROLES and kind:
                    out.append([role, kind, *row[2:]])
                    continue
            #: `["beat_type","qualifier","beat_type:establish"]`：角色与 kind **互换**了。
            if second in hg.ROLES and first in hg.ALLOWED_KINDS:
                out.append([second, first, *row[2:]])
                continue
            #: `["action","action","action:出场"]`：首格是 kind，角色要从 schema 里查。
            if first in hg.ALLOWED_KINDS and (second == first
                                              or second not in hg.ROLES):
                role = _role_for_kind(edge_type, first)
                if role:
                    out.append([role, first, *row[2:]])
                    continue
        out.append(row)
    return out


def validate_draft(draft: Dict) -> Tuple[bool, str]:
    """**粗闭集 ＋ 出处**检查。返回 ``(ok, reason)``；reason 是**具名**的。

    它查的是三样：边型 ∈ `EDGE_TYPES`、角色 ∈ `ROLES`、kind ∈ `ALLOWED_KINDS`，
    外加"草稿必须带出处（url ＋ span）"。

    **它不查什么**（P5 的门负责，别把这一层当成完整校验）：

    * **取值词表**：`kind:取值` 里的取值是否在 `VALUE_DOMAINS` 内。实测（2026-10-05
      的 P4 试点）模型会写 `pacing:followed the singer`、`vfx:video feedback` 这类
      **自由文本**——它们过得了这一层，过不了 `hypergraph.validate_edge` 的词表关；
    * **必填槽位结构**：`REQUIRED_MEMBERS`（例如某类边必须带哪个 qualifier）——
      试点里出现过 `allow/applies_to_genre` 这种**角色与 kind 不搭**的写法；
    * **禁忌宿主**与**成员级依据是否逐字出自原文**。

    所以本函数的"通过"只说明"形状像一条本仓边"，**不说明它会被索引收下**。
    P5 的拒绝率与填充率才是那些门的读数。
    """
    if not isinstance(draft, dict):
        return False, "draft_not_object"
    edge_type = str(draft.get("type") or "").strip()
    if edge_type not in hg.EDGE_TYPES:
        return False, "bad_type:%s" % edge_type
    members = normalise_members(draft.get("members"), str(draft.get("type") or ""))
    if not isinstance(members, (list, tuple)) or not members:
        return False, "no_members"
    for item in members:
        if not isinstance(item, (list, tuple)) or len(item) not in (3, 4):
            return False, "bad_member:%r" % (item,)
        role, kind = str(item[0]), str(item[1])
        if role not in hg.ROLES:
            return False, "bad_role:%s" % role
        if kind not in hg.ALLOWED_KINDS:
            return False, "bad_kind:%s" % kind
    source = draft.get("source")
    if not isinstance(source, dict) or not str(source.get("url") or ""):
        return False, "missing_source"
    span = source.get("span")
    if (not isinstance(span, (list, tuple)) or len(span) != 2
            or not all(isinstance(value, int) for value in span)
            or span[0] >= span[1]):
        return False, "bad_span:%r" % (span,)
    return True, ""


#: 提示词（**单一段**）。要点：只输出 JSON；成员必须是 `[role, kind, node_id]`
#: 或 `[role, kind, node_id, 依据]`；线索里没有的就**不要写**——宁少勿编。
SEGMENT_SYSTEM = (
    "你是分镜/表演知识的抽取器。给你一段他人著作里的**完整知识片段**，"
    "请抽出其中的**强耦合约束**，每条写成一条超边。\n"
    "只输出 JSON：{\"drafts\":[{\"type\":\"<边型>\",\"members\":[[\"<角色>\",\"<kind>\","
    "\"<kind>:<取值>\"],...],\"confidence\":0-10}]}。\n"
    "规则：①边型、角色、kind 只能用上面列出的闭集，闭集外的**不要写**；"
    "②**必填槽位一个都不能少**；③**原文明说**的槽位，第 4 项写逐字依据；"
    "④**没明说但能推出的**槽位照样写上、**不写第 4 项**（机器记成 `inferred`，"
    "本仓设计如此）；⑤只有连推都推不出时才不写这条边。"
)


def value_lines(vocab: Optional[Dict[str, Sequence[str]]] = None) -> str:
    """**每个 kind 允许写什么**。

    给了词表（v4 语料上现建的）就按它列；没给就退回 `hg.VALUE_DOMAINS` 的冻结枚举。
    有词表的 kind 与没有的 kind 都要能分辨——没有的**明写**"自由文本，取本段逐字
    出现的那个"，而不是留空让模型去猜。

    为什么要写这一节（实测 2026-10-05）：只给 kind 闭集时模型自由造值
    （`pacing:rapid`、`lens:长镜头`、`genre:music video`），接上取值词表关之后
    **4/4 全被拒**。
    """
    table: Dict[str, Sequence[str]] = {}
    for kind, values in (hg.VALUE_DOMAINS or {}).items():
        if values:
            table[kind] = tuple(values)
    for kind, values in (vocab or {}).items():
        values = tuple(str(value) for value in (values or ()) if str(value))
        if values:
            table[kind] = values
    lines = []
    for kind in sorted(hg.ALLOWED_KINDS):
        values = table.get(kind)
        if values:
            lines.append("%s：%s" % (kind, "/".join(values)))
        else:
            lines.append("%s：（自由文本，取本段逐字出现的那个）" % kind)
    return "\n".join(lines)


def edge_type_menu(vocab: Optional[Dict[str, Sequence[str]]] = None) -> str:
    """单段提示词的闭集菜单——**只给边型与必填槽位**（已知最好状态）。

    实测阶梯（2026-10-05，同一批 60 段／DeepSeek，temperature=0）：

    | 提示词里多给什么 | 草稿数 |
    |---|---|
    | 只给边型（连必填都没有） | 21 |
    | ＋必填槽位 | **4**（本函数现在的位置） |
    | ＋每个 kind 的允许取值 | 0（pilot3/4） |
    | ＋边型语义注解 | 0（pilot8/9，重复两次） |
    | 拆成两段式（A 问边型／B 填槽位） | 0（pilot5/6） |

    ⇒ **每加一层 schema 细节，产量就掉一截，直到归零**。所以默认只给必填槽位：
    它是"影子构建里 4/4 通过"的那个状态。取值表与语义注解保留为**可选件**
    （`value_lines()`／`type_glosses()`，两段式的 B 段用得上），
    **不许**因为"看起来更严"就把它们塞回单段提示词。
    """
    lines = []
    for edge_type in hg.EDGE_TYPES:
        required = ", ".join("%s/%s" % (role, kind)
                             for role, kind in hg.REQUIRED_MEMBERS.get(edge_type, ()))
        lines.append("%s ← 必填：%s" % (edge_type, required or "（无）"))
    return ("边型与**必填槽位**（缺一即整条边作废）：\n%s\n\n"
            "角色闭集：%s\nkind 闭集：%s\n"
            "（取值词表由检索侧冻结。原文明说的槽位写逐字依据；**没明说但能推出的**"
            "照样写上、**不写依据**——机器记成 `inferred`，本仓设计如此。）"
            % ("\n".join(lines), "/".join(sorted(hg.ROLES)),
               "/".join(hg.ALLOWED_KINDS)))


def build_prompt(segment: Segment,
                 vocab: Optional[Dict[str, Sequence[str]]] = None) -> str:
    return "%s\n\n知识片段：\n%s" % (edge_type_menu(vocab), segment.text)


def parse_reply(reply: str) -> Tuple[List[Dict], Optional[str]]:
    """解析模型的回包。坏 JSON 返回 ``( [], "parse_fault:<err>" )``。"""
    text = str(reply or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        payload = json.loads(text.strip() or "{}")
    except ValueError as exc:
        return [], "parse_fault:%s" % exc
    drafts = payload.get("drafts") if isinstance(payload, dict) else payload
    if not isinstance(drafts, list):
        return [], "parse_fault:no_drafts_array"
    return [item for item in drafts if isinstance(item, dict)], None


def extract(records: Iterable[Dict], *, llm: Callable[[str], str],
            max_chars: int = DEFAULT_MAX_CHARS,
            limit_segments: int = 0,
            min_chars: int = DEFAULT_MIN_CHARS,
            vocab: Optional[Dict[str, Sequence[str]]] = None
            ) -> Tuple[List[Dict], List[Dict], Dict]:
    """两趟驱动：分段 → 逐段归属 → 闭集校验 → 分账。

    `llm` 是注入的（生产用 :class:`DeepSeekClient`，测试用替身），
    所以本函数**不碰网络**，可离线跑。
    """
    drafts_out: List[Dict] = []
    rejects: List[Dict] = []
    segments_seen = 0
    skipped_short = 0
    drafts_seen = 0
    for record in records:
        source_ref = dict(record.get("source_ref") or {})
        segments = segments_of(record, max_chars=max_chars)
        for segment in segments:
            if limit_segments and segments_seen >= limit_segments:
                break
            segments_seen += 1
            #: 站点样板（"Skip to main content"）不值得一次 LLM 调用。跳过**不算拒收**：
            #: 账上单列 `skipped_short`，免得把"没内容"记成"抽取失败"。
            if len(segment.text) < min_chars:
                skipped_short += 1
                continue
            try:
                reply = llm(build_prompt(segment, vocab))
            except Exception as exc:  # noqa: BLE001 - 单段失败不吞掉整批
                drafts_seen += 1
                rejects.append({"reason": "llm_error:%s: %s" % (type(exc).__name__, exc),
                                "source": {"url": source_ref.get("url"),
                                           "sha256": source_ref.get("sha256"),
                                           "span": list(segment.span)}})
                continue
            parsed, fault = parse_reply(reply)
            if fault is not None:
                drafts_seen += 1
                rejects.append({"reason": fault,
                                "source": {"url": source_ref.get("url"),
                                           "sha256": source_ref.get("sha256"),
                                           "span": list(segment.span)}})
                continue
            for draft in parsed:
                drafts_seen += 1
                candidate = dict(draft)
                #: **归一化放在写进草稿之前**：下游 `to_edge` 看到的是契约形状，
                #: 而不是模型这次的写法（否则归一化只在校验里生效、下游照样被拒）。
                candidate["members"] = normalise_members(
                    candidate.get("members"), str(candidate.get("type") or ""))
                candidate["source"] = {"url": source_ref.get("url"),
                                       "sha256": source_ref.get("sha256"),
                                       "span": list(segment.span)}
                ok, reason = validate_draft(candidate)
                if ok:
                    drafts_out.append(candidate)
                else:
                    rejects.append({"reason": reason, "draft": draft,
                                    "source": candidate["source"]})
    stats = {"segments": segments_seen, "skipped_short": skipped_short,
             "drafts_seen": drafts_seen,
             "kept": len(drafts_out), "rejected": len(rejects)}
    return drafts_out, rejects, stats


TYPE_STEP_SYSTEM = (
    "你是分镜/表演知识的抽取器。第一步只做一件事：判断给你的**知识片段支持哪些边型**。\n"
    "只输出 JSON：{\"types\":[\"<边型>\",...]}。\n"
    "规则：①只写下面列出过的边型；②一段可以支持 0 个边型，那就返回空数组——"
    "**宁可空手，也不许硬凑**；③只判断边型，不要写成员、不要写取值。"
)

MEMBER_STEP_SYSTEM = (
    "你是分镜/表演知识的抽取器。第二步只做一件事：为**指定的那一个边型**填齐它的槽位。\n"
    "只输出 JSON：{\"members\":[[\"<角色>\",\"<kind>\",\"<kind>:<取值>\"(,\"<依据>\")],...],"
    "\"confidence\":0-10}。\n"
    "规则：①**必填槽位一个都不能少**，缺一即整条边作废；②取值只用下面列出的；"
    "③**原文明说**的槽位：第 4 项写一句**逐字出自本段**的依据；"
    "④**原文没明说但按本段的规则可以推出的**槽位：照样写上，**不要写第 4 项**"
    "（机器会把它记成 `inferred`，这是本仓设计的一部分，不丢人）；"
    "⑤只有**连推都推不出**时才返回空数组。"
)

#: A 段用的标记（测试与排障都靠它区分两段）。
TYPE_STEP_MARK = "支持哪些边型"
MEMBER_STEP_MARK = "填齐它的槽位"


def type_prompt(segment: Segment) -> str:
    """A 段提示词：边型 ＋ 必填槽位 ＋ **语义注解**；**不带取值表**（那会压死模型）。

    语义注解**必须**在（实测 2026-10-05）：没有它时模型对 700–1,040 字的段
    一律返回 `{"types":[]}`——`EMOTION_PACK`／`TROPE` 这些是我们自造的抽象名。
    """
    glosses = type_glosses()
    lines = []
    for edge_type in hg.EDGE_TYPES:
        required = ", ".join("%s/%s" % (role, kind)
                             for role, kind in hg.REQUIRED_MEMBERS.get(edge_type, ()))
        gloss = str(glosses.get(edge_type) or "").strip()
        lines.append("%s ← 必填：%s%s"
                     % (edge_type, required or "（无）",
                        ("；" + gloss) if gloss else ""))
    return ("%s\n\n边型、必填槽位与**它管什么**（用来判断这段支不支持它）：\n%s\n\n"
            "知识片段：\n%s" % (TYPE_STEP_SYSTEM, "\n".join(lines), segment.text))


#: 现役 v18 提示词里那块边型清单的起点（解析的锚）。它变了就**大声失败**，
#: 不许静默退化成"没有注解也照样跑"。
_V18_TYPE_BLOCK_ANCHOR = "1. `type` 只能取下面"


def type_glosses() -> Dict[str, str]:
    """从现役 v18 的 `SYSTEM_PROMPT` 里**解析**每个边型的一句人话注解。

    为什么解析而不是抄一份到本模块：抄一份就有两份真源，加边型时必漂
    （本项目反复踩过）。这里锚定 v18 提示词里那块清单，按 `TYPE: …` 起头、
    后续缩进行续句；`hg.EDGE_TYPES` 里任何一个边型取不到注解就**抛错**，
    由 `tests/test_extract_segmented.py::test_every_edge_type_has_a_semantic_gloss_taken_from_the_v18_prompt`
    当场变红——而不是让 A 段悄悄退回"只有槽位形状"的版本。
    """
    try:
        from . import build_hypergraph as bh  # noqa: PLC0415 - 延迟导入，避免重模块进包加载链
    except ImportError:  # pragma: no cover - 直跑
        from tools.kb_fetch import build_hypergraph as bh  # type: ignore
    text = str(getattr(bh, "SYSTEM_PROMPT", ""))
    start = text.find(_V18_TYPE_BLOCK_ANCHOR)
    if start < 0:
        raise RuntimeError("v18 提示词里找不到边型清单的锚点：%r" % _V18_TYPE_BLOCK_ANCHOR)
    #: 清单到第 2 条规则为止。
    stop = text.find("\n2. ", start)
    block = text[start:stop if stop > start else start + 4000]
    glosses: Dict[str, str] = {}
    current = ""
    for line in block.splitlines()[1:]:
        head = re.match(r"^\s{3}([A-Z_]+)\s*:\s*(.*)$", line)
        if head:
            current = head.group(1)
            glosses[current] = head.group(2).strip()
        elif current and re.match(r"^\s{5,}\S", line):
            glosses[current] = (glosses[current] + " " + line.strip()).strip()
    missing = sorted(set(hg.EDGE_TYPES) - set(glosses))
    if missing:
        raise RuntimeError(
            "v18 提示词里没有这些边型的注解：%s——加边型时必须同时给它一句人话注解，"
            "否则 A 段会退回「只有槽位形状」的版本（实测那样模型一律返空）" % missing)
    return {key: value for key, value in glosses.items() if key in set(hg.EDGE_TYPES)}


def _kinds_of(edge_type: str) -> List[str]:
    kinds = [kind for _role, kind in hg.REQUIRED_MEMBERS.get(edge_type, ())]
    return sorted(dict.fromkeys(kinds))


def member_prompt(segment, edge_type: str,
                  vocab: Optional[Dict[str, Sequence[str]]] = None) -> str:
    """B 段提示词：**只**带这一个边型的 kind 与其允许取值。

    这是"两段式"的全部意义：每次调用的枚举面从 26 kind／374 取值缩到"一个边型的
    那几个 kind"（实测：平铺全表时模型对 1,040 字的段也返回空）。
    """
    kinds = _kinds_of(edge_type)
    table = {}
    for kind, values in (hg.VALUE_DOMAINS or {}).items():
        if values:
            table[kind] = tuple(values)
    for kind, values in (vocab or {}).items():
        cleaned = tuple(str(value) for value in (values or ()) if str(value))
        if cleaned:
            table[kind] = cleaned
    lines = []
    for kind in kinds:
        values = table.get(kind)
        lines.append("%s：%s" % (kind, "/".join(values)) if values
                     else "%s：（自由文本，取本段逐字出现的那个）" % kind)
    required = ", ".join("%s/%s" % (role, kind)
                         for role, kind in hg.REQUIRED_MEMBERS.get(edge_type, ()))
    return ("%s\n\n边型：%s\n必填槽位：%s\n这个边型用到的 kind 与允许取值：\n%s\n\n知识片段：\n%s"
            % (MEMBER_STEP_SYSTEM, edge_type, required, "\n".join(lines),
               getattr(segment, "text", "")))


def parse_types(reply: str) -> Tuple[List[str], Optional[str]]:
    """解 A 段回包：只认闭集里的边型。"""
    text = str(reply or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        payload = json.loads(text.strip() or "{}")
    except ValueError as exc:
        return [], "parse_fault:%s" % exc
    raw = payload.get("types") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return [], "parse_fault:no_types_array"
    return [str(item) for item in raw if str(item) in hg.EDGE_TYPES], None


def parse_members(reply: str) -> Tuple[List, Optional[int], Optional[str]]:
    """解 B 段回包：返回 ``(members, confidence, fault)``。"""
    text = str(reply or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        payload = json.loads(text.strip() or "{}")
    except ValueError as exc:
        return [], None, "parse_fault:%s" % exc
    if not isinstance(payload, dict):
        return [], None, "parse_fault:not_object"
    members = payload.get("members")
    if not isinstance(members, list):
        return [], None, "parse_fault:no_members_array"
    confidence = payload.get("confidence")
    try:
        confidence = int(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    return members, confidence, None


def extract_two_step(records: Iterable[Dict], *, llm: Callable[[str], str],
                     max_chars: int = DEFAULT_MAX_CHARS,
                     limit_segments: int = 0,
                     min_chars: int = DEFAULT_MIN_CHARS,
                     vocab: Optional[Dict[str, Sequence[str]]] = None
                     ) -> Tuple[List[Dict], List[Dict], Dict]:
    """**两段式**驱动：A 问边型 → B 填槽位。

    为什么要拆（实测 2026-10-05 的负结果）：把 374 个取值平铺进一次调用，模型对
    96 字与 1,040 字的段**都返回空**；约束越加越严的曲线是 21 → 4 → **0** 条。
    拆开之后每次调用的枚举面从 26 kind 缩到"一个边型的那几个 kind"。

    调用数记在 `stats["calls"]`（A 每段 1 次；B 只在 A 选中边型时才有）。
    """
    drafts_out: List[Dict] = []
    rejects: List[Dict] = []
    segments_seen = 0
    skipped_short = 0
    drafts_seen = 0
    segments_failed = 0
    calls = 0
    for record in records:
        source_ref = dict(record.get("source_ref") or {})
        for segment in segments_of(record, max_chars=max_chars):
            if limit_segments and segments_seen >= limit_segments:
                break
            segments_seen += 1
            if len(segment.text) < min_chars:
                skipped_short += 1
                continue
            where = {"url": source_ref.get("url"), "sha256": source_ref.get("sha256"),
                     "span": list(segment.span)}
            # ---- A 段：只问边型 ----
            try:
                calls += 1
                types, fault = parse_types(llm(type_prompt(segment)))
            except Exception as exc:  # noqa: BLE001
                types, fault = [], "llm_error:%s: %s" % (type(exc).__name__, exc)
            if fault is not None:
                segments_failed += 1
                rejects.append({"reason": fault, "source": where, "step": "types"})
                continue
            if not types:
                #: A 段空手是**合法**结果（这段确实没有强耦合），不是失败。
                continue
            # ---- B 段：逐个边型填槽位 ----
            for edge_type in types:
                try:
                    calls += 1
                    members, confidence, fault = parse_members(
                        llm(member_prompt(segment, edge_type, vocab)))
                except Exception as exc:  # noqa: BLE001
                    members, confidence, fault = [], None, (
                        "llm_error:%s: %s" % (type(exc).__name__, exc))
                if fault is not None:
                    drafts_seen += 1
                    rejects.append({"reason": fault, "source": where, "step": "members",
                                    "type": edge_type})
                    continue
                if not members:
                    #: B 段空手同样合法（填不齐就不写）。
                    continue
                drafts_seen += 1
                candidate = {"type": edge_type,
                             "members": normalise_members(members, edge_type),
                             "confidence": confidence, "source": where}
                ok, reason = validate_draft(candidate)
                if ok:
                    drafts_out.append(candidate)
                else:
                    rejects.append({"reason": reason, "draft": candidate, "step": "validate"})
    stats = {"segments": segments_seen, "skipped_short": skipped_short,
             "drafts_seen": drafts_seen, "kept": len(drafts_out),
             "rejected": len(rejects), "segments_failed": segments_failed,
             "calls": calls}
    return drafts_out, rejects, stats


# --------------------------------------------------------------------------- #
# ⑬ 候选边型由**查词表**决定（不问模型）
# --------------------------------------------------------------------------- #

def node_surfaces(node: Dict) -> List[str]:
    """一个节点在**正文里可能怎么写**：取值／规范名／同义说法／node_id 的取值段。

    与 `build_hypergraph.node_surfaces()` 同一口径（那边是给"成员依据"回查用的）：
    中文词表里 `shot_size:MS` 的写法是"中景"，光比对 `MS` 会漏掉绝大多数散文。
    """
    out: List[str] = []
    for key in ("name", "value"):
        text = str(node.get(key) or "").strip()
        if text:
            out.append(text)
    for alias in node.get("aliases") or ():
        text = str(alias).strip()
        if text:
            out.append(text)
    node_id = str(node.get("node_id") or "")
    if ":" in node_id:
        tail = node_id.split(":", 1)[1].strip()
        if tail:
            out.append(tail)
    return list(dict.fromkeys(out))


def candidate_types(text: str, nodes: Sequence[Dict]) -> List[str]:
    """**确定性**地选出候选边型：正文里出现了它必填 kind 的词表取值就算候选。

    为什么不让模型分类（台账 ⑬）：A 段那种"先问支持哪些边型"实测对 700–1,040 字的
    段**一律返回空**；而"这段里出现了哪些取值"是**词表在手就能判**的事。

    排序：命中必填 kind 数多的在前；并列时按 `hg.EDGE_TYPES` 的顺序（稳定）。
    """
    haystack = str(text or "")
    matched_kinds = set()
    for node in nodes or ():
        kind = str(node.get("type") or "")
        if not kind or kind not in hg.ALLOWED_KINDS:
            continue
        if any(surface and surface in haystack for surface in node_surfaces(node)):
            matched_kinds.add(kind)
    scored = []
    for order, edge_type in enumerate(hg.EDGE_TYPES):
        required = {kind for _role, kind in hg.REQUIRED_MEMBERS.get(edge_type, ())}
        hits = len(required & matched_kinds)
        if hits:
            scored.append((-hits, order, edge_type))
    return [edge_type for _hits, _order, edge_type in sorted(scored)]


def vocab_from_nodes(nodes: Sequence[Dict]) -> Dict[str, List[str]]:
    """把节点表收成 `kind -> [取值]`（`member_prompt` 要的形状）。"""
    table: Dict[str, List[str]] = {}
    for node in nodes or ():
        kind = str(node.get("type") or "")
        value = str(node.get("value") or node.get("name") or "").strip()
        if kind and value:
            table.setdefault(kind, [])
            if value not in table[kind]:
                table[kind].append(value)
    return {kind: sorted(values) for kind, values in table.items()}


def extract_scoped(records: Iterable[Dict], *, llm: Callable[[str], str],
                   nodes: Sequence[Dict],
                   max_chars: int = DEFAULT_MAX_CHARS,
                   limit_segments: int = 0,
                   min_chars: int = DEFAULT_MIN_CHARS,
                   vocab: Optional[Dict[str, Sequence[str]]] = None,
                   max_types_per_segment: int = 3
                   ) -> Tuple[List[Dict], List[Dict], Dict]:
    """**查表选边型 ＋ 逐边型填槽位**的驱动（⑬）。

    与 `extract_two_step` 的唯一区别：**候选边型不看模型**，由
    :func:`candidate_types` 用词表在正文里查出来；只有这样才绕开"A 段返空"那个失败。
    没命中的段**一次调用都不花**（记 `segments_skipped_no_candidate`）。
    """
    table = dict(vocab) if vocab is not None else vocab_from_nodes(nodes)
    drafts_out: List[Dict] = []
    rejects: List[Dict] = []
    segments_seen = 0
    skipped_short = 0
    skipped_no_candidate = 0
    drafts_seen = 0
    calls = 0
    for record in records:
        source_ref = dict(record.get("source_ref") or {})
        for segment in segments_of(record, max_chars=max_chars):
            if limit_segments and segments_seen >= limit_segments:
                break
            segments_seen += 1
            if len(segment.text) < min_chars:
                skipped_short += 1
                continue
            candidates = candidate_types(segment.text, nodes)[:max_types_per_segment]
            if not candidates:
                skipped_no_candidate += 1
                continue
            where = {"url": source_ref.get("url"), "sha256": source_ref.get("sha256"),
                     "span": list(segment.span)}
            for edge_type in candidates:
                try:
                    calls += 1
                    members, confidence, fault = parse_members(
                        llm(member_prompt(segment, edge_type, table)))
                except Exception as exc:  # noqa: BLE001
                    members, confidence, fault = [], None, (
                        "llm_error:%s: %s" % (type(exc).__name__, exc))
                if fault is not None:
                    drafts_seen += 1
                    rejects.append({"reason": fault, "source": where, "step": "members",
                                    "type": edge_type})
                    continue
                if not members:
                    continue          # 空手合法
                drafts_seen += 1
                candidate = {"type": edge_type,
                             "members": normalise_members(members, edge_type),
                             "confidence": confidence, "source": where}
                ok, reason = validate_draft(candidate)
                if ok:
                    drafts_out.append(candidate)
                else:
                    rejects.append({"reason": reason, "draft": candidate,
                                    "step": "validate"})
    stats = {"segments": segments_seen, "skipped_short": skipped_short,
             "segments_skipped_no_candidate": skipped_no_candidate,
             "drafts_seen": drafts_seen, "kept": len(drafts_out),
             "rejected": len(rejects), "calls": calls}
    return drafts_out, rejects, stats


class DeepSeekClient:
    """构建期抽取用的 LLM 通道（用户 U10：沿用别家方案处的内部 LLM 用 DeepSeek）。

    OpenAI 兼容的 `/chat/completions`，key 只从环境变量 `DEEPSEEK_API_KEY` 读，
    **绝不写进仓库**（与 `tools/kb_fetch/llm.py` 的纪律同源）。
    """

    BASE = "https://api.deepseek.com"

    def __init__(self, model: str = "deepseek-chat", api_key: str = "",
                 temperature: float = 0.0, timeout: float = 120.0,
                 max_tokens: int = 4096):
        import os
        self.model = model
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.temperature = temperature
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.calls = 0
        self.spend_path = common.WORK / "corpus_v4" / "spend.jsonl"

    def __call__(self, prompt: str) -> str:
        import urllib.request
        if not self.api_key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY（只从环境变量读）")
        body = json.dumps({
            "model": self.model, "temperature": self.temperature,
            "max_tokens": self.max_tokens, "stream": False,
            "messages": [{"role": "system", "content": SEGMENT_SYSTEM},
                         {"role": "user", "content": prompt}],
        }).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - 固定 https 端点
            self.BASE + "/chat/completions", data=body, method="POST",
            headers={"Authorization": "Bearer " + self.api_key,
                     "Content-Type": "application/json"})
        started = time.time()
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.calls += 1
        usage = payload.get("usage") or {}
        #: 花费台账（P5 的预算护栏 D6 从这里读）。
        try:
            self.spend_path.parent.mkdir(parents=True, exist_ok=True)
            with self.spend_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "model": self.model, "calls": self.calls,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "elapsed_s": round(time.time() - started, 1),
                }, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 记账失败不许把抽取打掉（但它会被 P5 的预算护栏看见"缺账"）
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("上游没有返回 choices")
        return str((choices[0].get("message") or {}).get("content") or "")


EXTRACT_NAME = "extract_segmented.jsonl"
REJECTS_NAME = "extract_rejected.jsonl"


def load_records(corpus_dir: pathlib.Path) -> List[Dict]:
    """读影子语料（P3 的 `fetched.jsonl`）。缺文件就**大声失败**，不静默空跑。"""
    path = pathlib.Path(corpus_dir) / "fetched.jsonl"
    if not path.is_file():
        raise FileNotFoundError("找不到 %s——P3 的入库还没跑？" % path)
    out: List[Dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.extract_segmented")
    parser.add_argument("--corpus", default=str(common.WORK / "corpus_v4"),
                        help="P3 的影子语料目录（读 fetched.jsonl）")
    parser.add_argument("--out", required=True, help="抽取产物目录，例如 work/extracted_v4")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS,
                        help="短于它的段不送模型（站点样板）")
    parser.add_argument("--limit-records", type=int, default=0, help="0 = 全部")
    parser.add_argument("--limit-segments", type=int, default=0, help="0 = 全部")
    parser.add_argument("--dry-run", action="store_true",
                        help="只分段、不调 LLM（用来量一次要花多少段）")
    parser.add_argument("--vocab-from-corpus", action="store_true",
                        help="先在这份语料上现建 v4 词表，把**每个 kind 的允许取值**"
                             "写进提示词（实测：不写它模型会自由造值，接上取值词表关后"
                             "4/4 被拒）")
    parser.add_argument("--mode", default="single",
                        choices=["single", "two-step", "scoped"],
                        help="single＝一次调用给全部约束（实测会把模型压死）；"
                             "two-step＝A 问边型、B 只带那一个边型的 kind 与取值"
                             "（A 实测返空）；"
                             "scoped＝**查词表**选候选边型、再逐个填槽位（不看模型分类）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    records = load_records(pathlib.Path(args.corpus))
    if args.limit_records:
        records = records[:args.limit_records]
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        total = sum(len(segment_text(str(record.get("text") or ""),
                                     source_ref=dict(record.get("source_ref") or {}),
                                     max_chars=args.max_chars))
                    for record in records)
        print(json.dumps({"overall": "pass", "dry_run": True, "records": len(records),
                          "segments": total, "max_chars": args.max_chars},
                         ensure_ascii=False))
        return 0

    client = DeepSeekClient(model=args.model)
    vocab = None
    if args.vocab_from_corpus:
        #: **延迟导入**：`build_shadow` 依赖本模块，模块级互相 import 会成环。
        #: 两种入口都要认：当包导入（`relative`）与当脚本直跑（绝对路径）。
        try:  # noqa: PLC0415
            from . import build_shadow as bs  # type: ignore
        except ImportError:
            from tools.kb_fetch import build_shadow as bs  # type: ignore
        _nodes, vocab = bs.build_vocab(
            bs.segment_cards(pathlib.Path(args.corpus), max_chars=args.max_chars))
    if args.mode == "scoped":
        #: 查表选边型要节点表（取值 ＋ 中文写法），走影子构建同一份建表逻辑。
        try:  # noqa: PLC0415
            from . import build_shadow as bs  # type: ignore
        except ImportError:
            from tools.kb_fetch import build_shadow as bs  # type: ignore
        nodes, built = bs.build_vocab(
            bs.segment_cards(pathlib.Path(args.corpus), max_chars=args.max_chars))
        drafts, rejects, stats = extract_scoped(
            records, llm=client, nodes=nodes,
            max_chars=args.max_chars, limit_segments=args.limit_segments,
            min_chars=args.min_chars, vocab=vocab or built)
    else:
        runner = extract_two_step if args.mode == "two-step" else extract
        drafts, rejects, stats = runner(records, llm=client, max_chars=args.max_chars,
                                        limit_segments=args.limit_segments,
                                        min_chars=args.min_chars, vocab=vocab)
    common.write_jsonl(out_dir / EXTRACT_NAME, drafts)
    common.write_jsonl(out_dir / REJECTS_NAME, rejects)
    print(json.dumps({"overall": "pass", "prompt_version": PROMPT_VERSION,
                      "mode": args.mode,
                      "model": args.model, **stats,
                      "out": str(out_dir)}, ensure_ascii=False))
    return 0 if drafts else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
