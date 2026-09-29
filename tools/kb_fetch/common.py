"""管线共用件：路径、哈希、许可白名单、引用块门、SimHash。

口径全部来自执行文档 v1.4：

* 许可白名单 —— §2.3c「许可门」；
* `source_ref` 六字段非空 —— §2.3c 的 K1；
* 引用块 ≤2 句且 ≤120 字，且必须与正文分离（`quote` 字段）—— §2.3d
  「"改写而非转载"的可判定口径」；
* 九域枚举 —— §2.3c 的 K3 与 §2.3d 的 T7。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Dict, Iterable, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "knowledge"
SOURCES_YAML = KNOWLEDGE / "sources.yaml"
CARDS_DIR = KNOWLEDGE / "cards_generated"
WORK = ROOT / "work"
RAW_DIR = WORK / "raw"

#: 九域（§2.3c 的 K3）。顺序与 `block_director/knowledge/corpus.py::DOMAINS` 同源。
DOMAINS: Tuple[str, ...] = (
    "cinematography", "axis_theory", "composition", "blocking", "performance",
    "storyboard", "editing", "anime", "production",
)

#: §2.3c 的许可白名单：不在表内一律拒收。
LICENSE_WHITELIST = frozenset(
    {"CC0", "CC-BY", "CC-BY-SA", "PublicDomain", "OwnWork", "ExplicitPermission"}
)

#: §2.3c 的 K1：六个字段全非空，缺一不得入库。
SOURCE_REF_FIELDS: Tuple[str, ...] = (
    "url", "title", "author", "license", "retrieved_at", "sha256",
)

#: §2.3c 的「六块缺口」主题配额（K5，诊断量）。
TOPIC_QUOTAS: Tuple[str, ...] = (
    "lighting", "color", "camera_angle", "editing", "anime", "storyboard",
)

CHUNKER_VERSION = "para-2400/v1"
SCHEMA_VERSION = "p14-1/v1"
ANNOTATE_PROMPT_VERSION = "annotate/v4"

#: `mode: manual` 的来源用这个 URI 方案指向仓库内的笔记文件（见 LICENSES.md）。
OWNWORK_SCHEME = "repo://"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_WS_RE = re.compile(r"[ \t\u3000]+")
_BLANK_RE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """折叠空白但保留段落边界——去重与哈希都必须建立在同一份归一化上。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_RE.sub("\n\n", text).strip()


_CJK = r"\u3000-\u303f\u4e00-\u9fff\uff00-\uffef"
#: CJK 的句末标点后面可以直接接下一句（中文不写空格）；ASCII 的 `.!?` 只有
#: 后面跟空白或行尾时才算句末，否则 `3.5` 与 `Mr.` 会被误切成两句。
_SENT_END = re.compile(r"[。！？]+|[.!?]+(?=\s|$)")


def split_sentences(text: str) -> List[str]:
    """句边界 = CJK `。！？` 与 ASCII `.!?`（§2.3d 的冻结定义）。"""
    out: List[str] = []
    start = 0
    for match in _SENT_END.finditer(text):
        piece = text[start:match.end()].strip()
        if piece:
            out.append(piece)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def visible_len(text: str) -> int:
    """引用块的字数口径：去掉空白后的字符数（CJK 逐字计）。"""
    return len(re.sub(r"\s+", "", text))


MAX_QUOTE_SENTENCES = 2
MAX_QUOTE_CHARS = 120


def quote_check(quote: str) -> Tuple[bool, str]:
    """§2.3d：引用块 ≤2 句、≤120 字。返回 (通过?, 原因)。"""
    if not isinstance(quote, str) or not quote.strip():
        return False, "quote_empty"
    sentences = split_sentences(quote)
    if len(sentences) > MAX_QUOTE_SENTENCES:
        return False, f"quote_too_many_sentences:{len(sentences)}"
    if visible_len(quote) > MAX_QUOTE_CHARS:
        return False, f"quote_too_long:{visible_len(quote)}"
    return True, ""


def quote_is_verbatim(quote: str, source_text: str) -> bool:
    """引用必须是原文的子串（允许空白差异）——防止"引用"其实是自由发挥。"""
    if not quote or not source_text:
        return False
    def squeeze(text: str) -> str:
        return re.sub(r"\s+", "", text)
    return squeeze(quote) in squeeze(source_text)


def locate_quote(quote: str, source_text: str) -> Tuple[int, int]:
    """在原文里定位引用块，返回 `(start, end)`；找不到返回 `(-1, -1)`。

    先试直接子串匹配；失败时退化为**空白容忍**的正则（引用块与原文之间只允许
    空白差异——这条容忍与 `quote_is_verbatim` 完全一致，不是为了放宽门）。
    """
    if not quote or not source_text:
        return -1, -1
    index = source_text.find(quote)
    if index >= 0:
        return index, index + len(quote)
    pattern = r"\s*".join(re.escape(part) for part in re.split(r"\s+", quote.strip()))
    match = re.search(pattern, source_text)
    if match:
        return match.start(), match.end()
    return -1, -1


def source_ref_problems(source_ref: Dict[str, str]) -> List[str]:
    """K1：六个字段全非空。返回缺失/为空的字段名。"""
    bad: List[str] = []
    for field in SOURCE_REF_FIELDS:
        value = source_ref.get(field)
        if value is None or not str(value).strip():
            bad.append(field)
    return bad


def license_allowed(license_name: str) -> bool:
    return str(license_name or "").strip() in LICENSE_WHITELIST


_TOKEN_RE = re.compile(rf"[{_CJK}]|[A-Za-z][A-Za-z0-9_\-]*|\d+(?:\.\d+)?")


def tokens(text: str) -> List[str]:
    """与 `block_director/knowledge/bm25.py::tokenize` 同源的粗切分（单字＋整词）。"""
    return _TOKEN_RE.findall(text or "")


def simhash64(text: str, bits: int = 64) -> int:
    """64 位 SimHash；全空文本返回 0。

    每个**去重后**的词元权重都是 1（binary weighting）。这一点不是可选项：
    按出现次数加权时，长文本会被 "the/of/and" 这类高频词主导，两本完全不同的
    英文书会落到同一个指纹上（实测 26 份语料里有 79 对误判为近重复）；
    改成按**词表**投票后，同一批语料的误判降为 0，而真正的近重复
    （只改了几个词的同一段文本）仍然落在 `SIMHASH_MAX_HAMMING` 以内。
    """
    counts = [0] * bits
    token_list = sorted(set(tokens(text)))
    if not token_list:
        return 0
    for token in token_list:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for i in range(bits):
            counts[i] += 1 if (value >> i) & 1 else -1
    out = 0
    for i in range(bits):
        if counts[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


SIMHASH_BITS = 64
SIMHASH_SIMILARITY = 0.90
#: 0.90 × 64 → 允许 6 位差（>6 位差即 <0.90）。
SIMHASH_MAX_HAMMING = int((1.0 - SIMHASH_SIMILARITY) * SIMHASH_BITS)


def is_near_duplicate(a: str, b: str) -> bool:
    return hamming(a, b) <= SIMHASH_MAX_HAMMING


def ensure_work_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)


def read_jsonl(path: pathlib.Path) -> List[Dict]:
    if not path.exists():
        return []
    out: List[Dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError as exc:  # pragma: no cover - 明确报错而不是跳过
            raise ValueError(f"{path}:{lineno} 不是合法 JSON: {exc}") from exc
    return out


def write_jsonl(path: pathlib.Path, records: Iterable[Dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def dump_json(path: pathlib.Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def load_sources(path: pathlib.Path | None = None) -> List[Dict]:
    """读 `knowledge/sources.yaml`。字段口径见 §2.3c 的「产出与落点」表。"""
    import yaml  # 开发侧依赖；block_director/ 不导入本模块

    source_path = path or SOURCES_YAML
    if not source_path.exists():
        raise FileNotFoundError(f"缺少来源清单：{source_path}")
    payload = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        entries = payload.get("sources", [])
    else:
        entries = payload or []
    if not isinstance(entries, list):
        raise ValueError("sources.yaml 顶层必须是 list 或 {sources: [...]}")
    out: List[Dict] = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"sources.yaml 第 {index} 条不是映射")
        missing = [f for f in ("url", "title", "author", "license", "domain", "mode")
                   if not str(entry.get(f, "")).strip()]
        if missing:
            raise ValueError(f"sources.yaml 第 {index} 条缺字段 {missing}")
        if entry["domain"] not in DOMAINS:
            raise ValueError(f"sources.yaml 第 {index} 条 domain 不在九域内: {entry['domain']!r}")
        if entry["mode"] not in ("http", "manual", "dataset"):
            raise ValueError(f"sources.yaml 第 {index} 条 mode 非法: {entry['mode']!r}")
        out.append(dict(entry))
    return out


def source_slug(source: Dict) -> str:
    """稳定 slug：手工来源用文件名，http 来源用 URL 尾部。"""
    url = str(source.get("url", ""))
    if url.startswith(OWNWORK_SCHEME):
        stem = pathlib.PurePosixPath(url[len(OWNWORK_SCHEME):]).name
    else:
        stem = url.rstrip("/").rsplit("/", 1)[-1] or "source"
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", stem).strip("_") or "source"
    return stem[:48]


def sentence_join(parts: Sequence[str]) -> str:
    return "".join(parts)
