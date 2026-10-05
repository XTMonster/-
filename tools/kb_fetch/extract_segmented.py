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
    members = draft.get("members")
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
    "②成员的第 4 项（可选）写**逐字出自本段**的依据短语；"
    "③本段没有的耦合就不要写，宁可少一条，也不许编。"
)


def edge_type_menu() -> str:
    """闭集菜单（提示词里用）——**现读** schema，不抄第二份。"""
    return ("边型闭集：%s\n角色闭集：%s\nkind 闭集：%s"
            % ("/".join(hg.EDGE_TYPES), "/".join(sorted(hg.ROLES)),
               "/".join(hg.ALLOWED_KINDS)))


def build_prompt(segment: Segment) -> str:
    return "%s\n\n知识片段：\n%s" % (edge_type_menu(), segment.text)


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
            min_chars: int = DEFAULT_MIN_CHARS) -> Tuple[List[Dict], List[Dict], Dict]:
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
        segments = segment_text(str(record.get("text") or ""),
                                source_ref=source_ref, max_chars=max_chars)
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
                reply = llm(build_prompt(segment))
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
    drafts, rejects, stats = extract(records, llm=client, max_chars=args.max_chars,
                                     limit_segments=args.limit_segments,
                                     min_chars=args.min_chars)
    common.write_jsonl(out_dir / EXTRACT_NAME, drafts)
    common.write_jsonl(out_dir / REJECTS_NAME, rejects)
    print(json.dumps({"overall": "pass", "prompt_version": PROMPT_VERSION,
                      "model": args.model, **stats,
                      "out": str(out_dir)}, ensure_ascii=False))
    return 0 if drafts else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
