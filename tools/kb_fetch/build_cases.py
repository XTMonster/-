"""L3 案例层语料构建（执行文档 v1.4 §2.3b / §2.3c / §2.3d T1 / §3.1）。

**只从已经过许可门与出处门的语料派生**（``work/licensed.jsonl``，与卡片同源、
同一批 ``source_ref``），不新抓任何东西。产物两件：

* ``knowledge/cases.jsonl`` —— 一行一个 :class:`~block_director.contracts.knowledge.Case`
  （``case_id/case_type/title/excerpt/beat_sequence/source_ref/score``）；
* ``knowledge/cases.manifest.json`` —— 逐类/逐域/逐来源计数、rejects 与其因由、
  六元指纹（语料指纹／生成器／模板版本／chunking／解码／schema 版本）。

三类案例（§2.3b 的 ``case_type``）：

* ``sequence_pattern`` —— **显式列举**的镜序套路（"建立→覆盖→反应"）。
  判据只认**箭头枚举**（``→`` / ``->``）：一行里被箭头分开的每一段都要落到
  一个节拍上，且**至少两个不同节拍**；``beat_sequence`` 的取值严格取自
  §2.3d T3 的 ``beat_type`` 词表（宁缺勿猜，映射不上就整行不算套路）。
  ``excerpt`` 就是那一行套路本身——因此"节拍顺序 == 文本里出现的顺序"这条
  判据在构建期就能机械验证（见 :func:`evaluate` 的 ``beat_order_mismatch``）；
* ``lesson`` —— 复盘/教训型段落（"失败/误区/切忌"这类词）；
* ``narrative`` —— 其余（拉片、书摘、手法叙述）。

纪律（写死，不因"想多产几条"而放宽）：

1. **改写而非转载**：``excerpt`` 是**原文短引**（≤2 句、≤120 字，必须能在
   原文里回指），``title`` 是改写出来的标签——两者分离；
2. **出处完整性 100%**：``source_ref`` 六字段全非空，缺一即整条 reject；
3. **不产出约束**：案例行里**不得**出现 ``forbid``/``forbids``/``constraint``
   （E3 的机制保证在 :mod:`block_director.knowledge.cases` 里也没有这些字段）；
4. **幂等**：同一份输入重复构建得到**逐字节相同**的两份产物。

用法::

  python tools/kb_fetch/build_cases.py
  python tools/kb_fetch/build_cases.py --check     # 只校验产物是否与重算一致
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.cases import (  # noqa: E402
    BEAT_TYPES,
    CASE_TYPES,
    CONSTRAINT_KEYS,
)
from tools.kb_fetch import common  # noqa: E402

INPUT = common.WORK / "licensed.jsonl"
CASES_PATH = common.KNOWLEDGE / "cases.jsonl"
MANIFEST_PATH = common.KNOWLEDGE / "cases.manifest.json"

SCHEMA_VERSION = "cases/v1"
TEMPLATE_VERSION = "case-template/v1"
CHUNKER_VERSION = "para-2400/v1"
DECODE = "deterministic;no-model"
#: §2.3c 的入库体积门（与卡片同口径）：单文件 ≤ 512 KB、总量 ≤ 20 MB。
MAX_CASE_FILE_BYTES = 512 * 1024
BUILD_REJECT_RATIO = 0.05

MIN_SEGMENT_CHARS = 120
MAX_SEGMENT_CHARS = 420
SENTENCES_PER_SEGMENT = 3
#: 条数上限**由入库体积门反推**（单文件 ≤ 512 KB，见 `MAX_CASE_FILE_BYTES`）：
#: 实测每条案例序列化后约 630 B，512 KB ÷ 630 ≈ 830；取 **810** 留出余量。
#: 原值 900 是在较小的旧语料上定的，重建后的语料一跑就写出 567 KB —— 直接违反
#: 体积门（写盘路径自己报了 `oversize`）。这不是放宽判据：`min_cases` 仍是 300，
#: 被裁掉的条数进 `quota_truncated`（实测 1710），账目照记。
DEFAULT_MAX_CASES = 810
DEFAULT_PER_SOURCE = 40

#: 有序镜序套路的节拍词 → §2.3d T3 的 ``beat_type`` 取值（**不得自造**）。
#: 词表按**领域同义词**放宽（"正反打/过肩/对切"都是 coverage，"淡出/叠化"都是
#: transition），但判据不放宽：仍要求 ≥2 个不同节拍 ＋ 1 个顺序词，
#: 且 ``beat_sequence`` 的取值必须落在 ``BEAT_TYPES`` 内（宁缺勿猜）。
BEAT_CUES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("establish", ("建立", "全貌", "定场", "交代环境", "交代位置", "开场镜", "主镜",
                   "远景", "全景", "establishing shot", "establish the scene",
                   "master shot", "wide shot", "long shot")),
    ("coverage", ("覆盖", "正反打", "对切", "过肩", "反打", "交替剪辑", "两人对话",
                  "中景", "中近景", "近景", "准备", "过程", "动作",
                  "coverage", "shot-reverse", "shot/reverse", "reverse angle",
                  "over-the-shoulder", "over the shoulder")),
    ("reaction", ("反应", "反作用", "结果", "听者",
                  "reaction shot", "reaction")),
    ("insert", ("细节", "插入", "特写", "极端帧",
                "insert shot", "cutaway", "cut away to", "close-up", "closeup")),
    ("transition", ("转场", "过渡", "淡出", "淡入", "叠化", "划像", "拉远", "收尾",
                    "transition shot", "fade in", "fade out", "dissolve", "wipe to")),
)
#: 箭头枚举的切分符（显式列举的唯一判据）。`—>` 是中文长破折号后缀的写法。
ARROW_RE = re.compile(r"\s*(?:→|->|—>)\s*")
#: **散文里的显式顺序枚举**（v1.6 新增）。为什么需要：`sequence_pattern` 原先只认
#: 箭头（`→`/`->`），而箭头是**我们自己的笔记**的写法；外部他人著作里基本没有箭头，
#: 于是"理论必须由他人写"的裁决一生效，派生数直接归零，而门限 7 是从那批自撰笔记的
#: 条数（4＋3）来的 —— 门与语料一起失效。
#: 外部语料表达镜序用的是**顺序词**："先给建立镜头，再切覆盖，最后落到反应"。
#: 这类同样是**显式枚举**（不是我们推断出来的顺序），只是标点不同：
#: 判据仍然全部保留 —— 每段至多一个节拍、≥2 个不同节拍、节拍顺序 == 文本顺序、
#: `excerpt` 必须逐字可回指，且**必须出现顺序标记**（否则"提到过两个节拍"会被误判成套路，
#: 那正是这条分支以前被删掉的原因）。
#: **中英双语**：外部他人著作（Gutenberg／MIT OCW）绝大多数是英文，
#: 只写中文顺序词等于一条都命中不到 —— 实测第一版就是 0 条（语料是英文散文）。
ORDER_CUES = ("先", "首先", "然后", "再", "接着", "随后", "随即", "最后", "之后", "继而",
              "first", "then", "next", "finally", "lastly", "after that", "second",
              "third", "subsequently", "afterwards", "at last")
#: 行首的列表装饰（`- ` / `* ` / `1. ` / `1、` / `一、`），只脱前缀不脱正文——
#: 脱掉的都是装饰符，剩下的仍然是原文的**连续子串**（"可回指原文"成立）。
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*·]|\d+\s*[.、)]|[一二三四五六七八九十]+\s*[、.)])\s*")
#: 行内强调装饰（`**粗体**` / `__粗体__`）。去掉的是**装饰符**，不是正文；
#: "可回指原文"的判据在**同样去掉装饰符**的正文上做（见 `sequence_pattern_of`），
#: 因此这一步不是放宽门，只是让注入文本里不再出现裸 asterisk。
MARKUP_RE = re.compile(r"\*\*|__")
#: §2.3d T1 的 ``sequence_pattern`` 门：**语料里有多少条显式枚举，就必须产出多少条**。
#:
#: 原来的常量是 **7**，依据是 `knowledge/source_notes/` 里那批**自撰笔记**的箭头行
#: （storyboard_practice.md 4 条 ＋ anime_language.md 3 条）。2026-10-01 的用户裁决
#: `docs/adr/0013-theory-must-be-authored-by-others.md` 把自撰笔记全部移出语料，
#: 依据随之消失 —— 而外部他人著作里实测只有 **1 条**显式枚举（箭头 0、散文顺序词 1）。
#: 用户对"L3 无解"的处置明确回过"**改门限吧**"，因此这个数不再写死：
#:
#:   门限 = 本次语料里**显式枚举的条数**（`enumerations_in_corpus`，构建时实测），
#:          且它必须 ≥1（空集判失败 —— §4.1b 硬规则 1 的分母下界）。
#:
#: 这样它测的东西从"许可语料够不够多"（供给，本项目已两次查到底）变成
#: "**产出有没有漏掉语料里真实存在的枚举**"（实现质量）——配额截断、切分退化、
#: 去重误杀都会当场判红，而它不再依赖一个已经不存在的数据来源。
SEQUENCE_FLOOR = 1
LESSON_CUES = ("失败", "错误", "切忌", "避免", "不要", "不可", "禁忌", "教训",
               "误区", "误用", "不宜", "avoid", "mistake", "never", "fault",
               "error", "don't", "do not")

#: 标题用的主题词表（改写，不抄句子）。按**固定顺序**取第一个命中的主题，
#: 保证同一段文本每次构建得到同一个标题。
TOPIC_LABELS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("镜头与焦距", ("焦距", "镜头", "lens", "广角", "长焦", "视角")),
    ("机位与角度", ("机位", "角度", "俯", "仰", "平视", "低机位", "高机位")),
    ("构图", ("构图", "三分", "对称", "框架", "留白", "视线空间")),
    ("光线", ("光线", "照明", "布光", "逆光", "侧光", "曝光", "light")),
    ("色彩", ("色彩", "色温", "色调", "color", "colour")),
    ("景别", ("景别", "特写", "中景", "全景", "近景", "远")),
    ("轴线与方向", ("轴线", "越轴", "银幕方向", "180")),
    ("剪辑与节奏", ("剪辑", "节奏", "切", "蒙太奇", "过渡", "cut", "edit")),
    ("运动", ("平移", "推轨", "摇", "升降", "跟拍", "移动", "crane", "dolly")),
    ("表演与走位", ("表演", "走位", "调度", "姿态", "情绪")),
    ("分镜", ("分镜", "故事板", "镜头脚本", "storyboard")),
    ("动画", ("动画", "作画", "动画电影", "anime")),
    ("制作", ("制片", "预算", "排期", "production")),
    ("声音", ("声音", "音效", "配乐", "对白")),
)


class BuildError(RuntimeError):
    """构建门未过（体积门 / rejects 比例）。"""


def corpus_fingerprint(docs: Sequence[Dict]) -> str:
    """语料指纹：逐篇 ``source_ref.sha256`` ＋ 正文哈希，排序后整体哈希。"""
    payload = "".join(sorted(
        str(doc.get("source_ref", {}).get("sha256", "")) + "|" + common.sha256_text(
            common.normalize_text(str(doc.get("text", ""))))
        for doc in docs))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def case_fingerprint(docs: Sequence[Dict]) -> str:
    """六元指纹（与超图同口径，只是"模型"这一项退化成确定性生成器）。"""
    return hashlib.sha256("|".join([
        corpus_fingerprint(docs), "deterministic", TEMPLATE_VERSION,
        CHUNKER_VERSION, DECODE, SCHEMA_VERSION,
    ]).encode("utf-8")).hexdigest()


#: 公有领域扫描件里夹着的站点/许可样板——它不是知识，必须挡在门外。
BOILERPLATE_CUES = ("project gutenberg", "gutenberg.org", "gutenberg-tm",
                    "www.gutenberg", "pgutenberg", "ebook", "e-book",
                    "copyright", "all rights reserved", "license terms",
                    "redistribution", "trademark", "donation", "isbn")
#: 标题里的括注（"（自撰笔记）"这类）不进标题——它占位置但不带信息。
BOILERPLATE_RE = re.compile(r"[（(][^）)]*[）)]")

#: 扫描件里的**插图说明/OCR 残片**。它不是知识，而且会**当上 `excerpt`**：
#: `pick_excerpt` 取的是段首那一对句子，于是 `[Illustration: MELTON MEADOWS. A.` 这种
#: 说明文字被当成"作者写的经验"发出去。实测代价（2026-10-02）：拿真实运行的逐镜查询
#: 去打 L3，返回的 6 条案例里有 **2 条是说明文字**，双模型面板给 1–2 分，
#: E1（经验引用相关性 ≥70%）得 **0.0** —— 那一栏在镜头上等于噪声。
#: 判据是**句级**的（见 `segments_of`）：说明句在切窗之前就被丢掉，
#: 于是它既不会单独成窗，也不会当上 excerpt。
CAPTION_MARKERS = ("[illustration", "[figure", "[diagram", "[plate", "[map",
                   "[chart", "[sketch", "[engraving", "illustration:",
                   "photograph by", "see illustration")

#: **整段方括号**（Gutenberg 的 `[Illustration: …]` 就是这种）在**切句之前**整块去掉。
#: 只按句滤是不够的：说明文字里带句点（`[Illustration: MELTON MEADOWS. A. Lewis…]`），
#: 切句会把它切成 3 段，只有第一段带得出 `[illustration`，剩下两段留下并把紧随其后的
#: **第一句正文**吞进同一个三句窗 —— 实测那样窗口整体错位、`narrative` 案例 1 → 0。
BRACKET_SPAN_RE = re.compile(r"\[[^\]]{0,400}\]")


def is_artifact_sentence(sentence: str) -> bool:
    """这一句是不是扫描件的说明/残片（不是作者写的知识）。"""
    lowered = sentence.strip().lower()
    return any(marker in lowered for marker in CAPTION_MARKERS)


def segments_of(text: str) -> List[str]:
    """把正文切成**不重叠**的句窗（每窗 3 句），并按可见长度过滤。

    句窗在**整篇**的句子流上滑（不按行切）：Gutenberg 的英文扫描件按行断句，
    一行往往只有一句，按段落切会一个窗口都组不出来——实测这样会得到 0 条案例。
    """
    out: List[str] = []
    #: 两步：① 方括号说明**整块**去掉（切句之前——否则它会被切成几段、只滤掉第一段）；
    #: ② 剩下的句子再逐句滤一次（无括号的 `Illustration: …` 写法）。
    plain = BRACKET_SPAN_RE.sub(" ", common.normalize_text(text))
    sentences = [s for s in common.split_sentences(plain)
                 if s.strip() and not is_artifact_sentence(s)]
    for start in range(0, len(sentences), SENTENCES_PER_SEGMENT):
        window = sentences[start:start + SENTENCES_PER_SEGMENT]
        if len(window) < SENTENCES_PER_SEGMENT:
            continue
        segment = " ".join(window).strip()
        length = common.visible_len(segment)
        if not MIN_SEGMENT_CHARS <= length <= MAX_SEGMENT_CHARS:
            continue
        lowered = segment.lower()
        if any(cue in lowered for cue in BOILERPLATE_CUES):
            continue
        out.append(segment)
    return out


def classify(segment: str) -> str:
    """判散文段落的 ``case_type``（``lesson`` ／ ``narrative``）。

    ``sequence_pattern`` **不在这里**：套路只由**显式箭头枚举**产生（见
    :func:`sequence_pattern_of`）。以前这里靠"≥2 个节拍词 ＋ 任意一个顺序词"
    判套路，实测把"准备—执行—收势"这种**不是镜序**的段落判成了套路，
    还把 ``beat_sequence`` 写反——宁缺勿猜，那条分支已删除。
    """
    if any(cue in segment for cue in LESSON_CUES):
        return "lesson"
    return "narrative"


def _beat_of(part: str) -> Optional[str]:
    """把箭头分隔出的一段文字映射到节拍；映射不上返回 ``None``。"""
    lowered = part.lower()
    hits: List[Tuple[int, str]] = []
    for beat, cues in BEAT_CUES:
        positions = [lowered.find(cue.lower()) for cue in cues]
        hits.extend((position, beat) for position in positions if position >= 0)
    if not hits:
        return None
    hits.sort(key=lambda item: (item[0], item[1]))
    return hits[0][1]


def _clip_quote(text: str) -> Optional[str]:
    """把一行原文裁成**仍然是原文子串**的 ≤2 句 / ≤120 字的短引。"""
    candidate = text.strip()
    if common.quote_check(candidate)[0]:
        return candidate
    sentences = common.split_sentences(candidate)
    if sentences and common.quote_check(sentences[0])[0]:
        return sentences[0].strip()
    best: Optional[str] = None
    for match in re.finditer(r"[，、；：,;:]", candidate):
        piece = candidate[: match.start() + 1].strip()
        if common.quote_check(piece)[0]:
            best = piece
        else:
            break
    return best


def sequence_pattern_of(text: str) -> List[Tuple[str, List[str]]]:
    """抽**显式箭头枚举**的镜序套路，返回 ``[(excerpt, beat_sequence), ...]``。

    判据（全部必要，缺一不算）：

    1. 该行含 ``→`` / ``->``；
    2. 被箭头分开的每一段**至多**映射到一个节拍（一段落进两个节拍时取最靠前
       的那一个，避免"一段既是覆盖又是反应"这种含糊）；
    3. 映射到的**不同**节拍 ≥2；
    4. 节拍顺序 == 文本顺序（``beat_sequence`` 按出现位置排，不做任何重排）。

    ``excerpt`` 是**脱掉行首列表装饰后的那一行**（仍是原文连续子串），并按
    §2.3d 的引用门裁到 ≤2 句 / ≤120 字。构建期会把"节拍顺序 == excerpt 里
    的出现顺序"再机械验一遍（:func:`evaluate`），所以这一步不许猜。
    """
    out: List[Tuple[str, List[str]]] = []
    plain = MARKUP_RE.sub("", str(text or ""))
    for raw_line in str(text or "").splitlines():
        if not ARROW_RE.search(raw_line):
            continue
        line = MARKUP_RE.sub("", LIST_MARKER_RE.sub("", raw_line)).strip()
        if not line:
            continue
        beats: List[str] = []
        for part in ARROW_RE.split(line):
            beat = _beat_of(part)
            if beat is not None and beat in BEAT_TYPES and beat not in beats:
                beats.append(beat)
        if len(beats) < 2:
            continue                      # 映射不上就整行不算套路（宁缺勿猜）
        excerpt = _clip_quote(line)
        if excerpt is None:
            continue
        if not common.quote_is_verbatim(excerpt, plain):
            continue          # 脱装饰后仍必须能在正文里回指（可审计）
        out.append((excerpt, beats))
    return out


def prose_sequence_pattern_of(text: str) -> List[Tuple[str, List[str]]]:
    """抽**散文里的显式顺序枚举**：`先建立镜头，再切覆盖，最后落到反应`。

    为什么要有这一条（2026-10-01 用户裁决"理论必须由他人写"之后）：箭头枚举是
    **我们自己笔记**的写法，外部他人著作里几乎不用；只用箭头会让 `sequence_pattern`
    这一类比配额外全部落空，而门限 `SEQUENCE_FLOOR = 7` 又是从那批自撰笔记的条数
    （4＋3）来的 —— 门和语料一起失去依据。

    判据**一条都不放宽**（缺一不算）：

    1. 按句读切出的每一段**至多**映射到一个节拍（复用 `_beat_of`，同一套 `BEAT_CUES`）；
    2. 映射到的**不同**节拍 ≥2；
    3. `beat_sequence` 严格按文本出现位置排（不做任何重排）；
    4. 整段里**必须出现显式顺序标记**（`ORDER_CUES`）—— 这条是防"只是提到了两个
       节拍"被误判成套路的闸门：这条分支以前就是因为放过 3 而把"准备—执行—收势"
       判成镜序，才被删掉的；
    5. `excerpt` 必须逐字可回指原文（复用 `_clip_quote` 与 `quote_is_verbatim`）。
    """
    plain = MARKUP_RE.sub("", str(text or ""))
    out: List[Tuple[str, List[str]]] = []
    for raw_segment in common.split_sentences(plain):
        segment = raw_segment.strip()
        if len(segment) < 12 or not any(cue in segment for cue in ORDER_CUES):
            continue
        beats: List[str] = []
        for clause in re.split(r"[，、；,;]", segment):
            beat = _beat_of(clause)
            if beat is not None and beat in BEAT_TYPES and beat not in beats:
                beats.append(beat)
        if len(beats) < 2:
            continue
        # **裁剪必须罩住全部节拍**：`_clip_quote` 是按句子/逗号截最长前缀的，
        # 实测会把最后一个节拍切在引之外（"first…then…finally…" 引到第二个逗号就停），
        # 于是 `beat_positions` 给出 -1、整条被门判 `beat_not_in_excerpt`。
        # 先定位第一个节拍到最后一个节拍的那一段，再对它裁剪。
        span_positions = beat_positions(segment, beats)
        if any(position < 0 for position in span_positions):
            continue
        excerpt = _clip_quote(segment[min(span_positions):])
        if excerpt is None or not common.quote_is_verbatim(excerpt, plain):
            continue
        # 节拍必须都能在 excerpt 里找到出处，且顺序一致（与门里的复核同一口径）。
        positions = beat_positions(excerpt, beats)
        if any(position < 0 for position in positions) or positions != sorted(positions):
            continue
        out.append((excerpt, beats))
    return out


def pick_excerpt(segment: str) -> Optional[str]:
    """取一段**可回指原文**的短引：≤2 句且 ≤120 字；取不到就整段作废。"""
    sentences = common.split_sentences(segment)
    for size in (2, 1):
        for start in range(0, max(len(sentences) - size + 1, 1)):
            candidate = "".join(sentences[start:start + size]).strip()
            ok, _reason = common.quote_check(candidate)
            if ok and common.quote_is_verbatim(candidate, segment):
                return candidate
    return None


def topic_of(segment: str) -> str:
    for label, cues in TOPIC_LABELS:
        if any(cue in segment for cue in cues):
            return label
    return "通用"


def tags_of(segment: str, limit: int = 6) -> List[str]:
    out: List[str] = []
    for label, cues in TOPIC_LABELS:
        if any(cue in segment for cue in cues) and label not in out:
            out.append(label)
        if len(out) >= limit:
            break
    return out


def build_cases(docs: Sequence[Dict], *, max_cases: int = DEFAULT_MAX_CASES,
                per_source: int = DEFAULT_PER_SOURCE
                ) -> Tuple[List[Dict], List[Dict], Dict]:
    """确定性构建：同一输入 → 同一输出（含 id、顺序与计数）。"""
    cases: List[Dict] = []
    rejects: List[Dict] = []
    duplicates: List[Dict] = []
    quota: List[Dict] = []
    seen_excerpts: List[int] = []            # SimHash 近重复
    seen_keys: set = set()
    counters: Dict[str, int] = {name: 0 for name in CASE_TYPES}
    per_domain: Dict[str, int] = {}
    per_source_docs: Dict[str, int] = {}
    raw_segments = 0
    segments_total = 0
    #: 语料里**显式枚举**的条数（箭头行 ＋ 散文顺序枚举），**在配额/去重之前**数。
    #: 它是门限的来源：产出的 `sequence_pattern` 少于它，就说明有真的枚举被漏掉
    #: （配额截断、切分退化、或近重复误杀），而不是"语料不够多"。
    enumerations_in_corpus = 0

    #: 第一遍：**每个来源先把候选攒齐**（不消费配额），第二遍按轮转分配。
    #:
    #: 为什么不能一遍到底：原来的写法是"按来源 URL 字母序，谁先来谁吃满配额"，
    #: 实测在重建后的语料上**饿死整域**——`per_domain` 里 `anime` / `production` /
    #: `blocking` 直接是 0 条（9 个域里 3 个在 L3 层完全没有覆盖），而它们是
    #: 用户点名要的（动漫/制片）。轮转让每个来源先各拿 1 条、再拿第 2 条……，
    #: 于是"某几个域一条都没有"只可能发生在预算连来源数都不够的时候。
    plans: List[Dict] = []
    for doc in sorted(docs, key=lambda item: str(item.get("source_ref", {}).get("url", ""))):
        source_ref = dict(doc.get("source_ref", {}))
        slug = common.source_slug({"url": source_ref.get("url", "")})
        missing = common.source_ref_problems(source_ref)
        if missing:
            rejects.append({"source": slug, "reason": f"source_ref_incomplete:{missing}"})
            continue
        if not common.license_allowed(source_ref.get("license", "")):
            rejects.append({"source": slug,
                            "reason": f"license_not_allowed:{source_ref.get('license')}"})
            continue
        body = str(doc.get("text", ""))
        # 候选一：显式箭头枚举的镜序套路（`sequence_pattern`）。它们**先于**
        # 散文段落参评：套路是 §2.3d T1 点名要 L3 承载的东西，不能被配额挤掉。
        candidates: List[Tuple[str, str, List[str], str, str]] = []
        for pattern_index, (excerpt, beats) in enumerate(
                sequence_pattern_of(body), 1):
            candidates.append((f"case_{slug}_seq{pattern_index:03d}",
                               "sequence_pattern", list(beats), excerpt, excerpt))
        # 候选一b：**散文里的显式顺序枚举**（外部他人著作的主要写法，见
        # `prose_sequence_pattern_of`）。与箭头枚举同一张表、同一套判据，只是标点不同。
        for pattern_index, (excerpt, beats) in enumerate(
                prose_sequence_pattern_of(body), 1):
            candidates.append((f"case_{slug}_pseq{pattern_index:03d}",
                               "sequence_pattern", list(beats), excerpt, excerpt))
        enumerations_in_corpus += sum(1 for item in candidates
                                      if item[1] == "sequence_pattern")
        # 候选二：散文段落（`lesson` ／ `narrative`）。
        items = list(enumerate(segments_of(body), 1))
        segments_total += len(items)
        # **按域关键词排序后再截**（2026-10-02）：同一套"可审计的确定性筛选"设备，
        # `chunk.py` 早就用它挑卡片语料，而案例层原先只按**文档顺序**取样。
        # 实测代价（英文查询打英文语料的**同语言**对照）：返回的 18 条案例里只有
        # 1 条 ≥4 分（**5.6%**），被捞上来的多是目录行（"1--The Fairy Camera--…"）、
        # 器材机械句（"each single turn of the camera handle…"）与无关叙述
        # （"Danjuro's widow cut her hair short"）——它们都排在被均匀抽样的位置上。
        # 改成按域关键词打分从高到低排（同分保持原顺序），"讲拍法"的段就排到了配额之前。
        from .chunk import DOMAIN_KEYWORDS, relevance_score

        domain_name = str(doc.get("domain", ""))
        if domain_name in DOMAIN_KEYWORDS:
            items.sort(key=lambda pair: (-relevance_score(pair[1], domain_name), pair[0]))
        else:
            items.sort(key=lambda pair: pair[0])
        # 跨整篇**均匀抽样**只作为**同分内的兜底顺序**：`mode: manual`（我们自己的笔记）
        # 只有几 KB，抽样反而会把"建立→覆盖→反应"这类**序列套路**整段跳过，所以不抽。
        if str(doc.get("mode")) != "manual" and items:
            ranked = items
            stride = max(1, len(ranked) // max(per_source, 1))
            #: 取前 `per_source × stride` 条（打分已经把它们排出优先级），
            #: 仍按 strided 顺序喂给候选列表，避免同一篇的相邻三段同时挤进配额。
            head = ranked[:max(per_source * stride, per_source)]
            items = head[::stride] if stride > 1 else head
        for index, segment in items:
            excerpt = pick_excerpt(segment)
            if excerpt is None:
                raw_segments += 1
                rejects.append({"source": slug, "segment": index,
                                "reason": "quote_gate"})
                continue
            candidates.append((f"case_{slug}_{index:03d}", classify(segment), [],
                               excerpt, segment))
        plans.append({"slug": slug, "source_ref": source_ref,
                      "domain": str(doc.get("domain", "")),
                      "candidates": candidates, "accepted": 0})

    #: 第二遍：**轮转配额**（每个来源第 1 条 → 第 2 条 → …）。候选在来源内的相对
    #: 顺序不变（套路永远排在散文段之前），所以 `sequence_pattern` 仍然优先。
    rounds = max((len(plan["candidates"]) for plan in plans), default=0)
    for round_index in range(rounds):
        for plan in plans:
            candidates = plan["candidates"]
            if round_index >= len(candidates):
                continue
            slug = plan["slug"]
            source_ref = plan["source_ref"]
            case_id, case_type, beats, excerpt, hint = candidates[round_index]
            raw_segments += 1
            if plan["accepted"] >= per_source or len(cases) >= max_cases:
                # 超出配额：不是"拒绝"，是**配额截断**，单独计数（别混进 rejects）。
                quota.append({"source": slug, "segment": case_id, "reason": "quota"})
                continue
            source_name = BOILERPLATE_RE.sub("", str(source_ref.get("title", "")))
            if case_type == "sequence_pattern":
                title = f"镜序套路：{source_name.strip()[:16]}"
            else:
                title = f"{topic_of(hint)}：{source_name.strip()[:16]}摘记{case_id[-3:]}"
            digest = common.sha256_text(title + "|" + excerpt)
            if digest in seen_keys:
                duplicates.append({"source": slug, "segment": case_id,
                                   "reason": "exact_duplicate"})
                continue
            signature = common.simhash64(excerpt)
            if any(common.is_near_duplicate(signature, other)
                   for other in seen_excerpts):
                duplicates.append({"source": slug, "segment": case_id,
                                   "reason": "near_duplicate"})
                continue
            tags = tags_of(hint)
            row = {
                "case_id": case_id,
                "case_type": case_type,
                "title": title,
                "excerpt": excerpt,
                "beat_sequence": list(beats),
                # source_ref 六字段来自许可门后的语料；`tags` 供 BM25 的标签检索
                # （sidecar 的 CaseIndex._text 读它）。
                "source_ref": {**source_ref, "tags": "、".join(tags)},
                "score": 0.0,
            }
            if any(key in row for key in CONSTRAINT_KEYS):  # 机制自检（E3）
                rejects.append({"source": slug, "segment": case_id,
                                "reason": "case_carries_constraint"})
                continue
            seen_keys.add(digest)
            seen_excerpts.append(signature)
            cases.append(row)
            plan["accepted"] += 1
            counters[case_type] += 1
            per_domain[plan["domain"]] = per_domain.get(plan["domain"], 0) + 1
    for plan in plans:
        per_source_docs[plan["slug"]] = plan["accepted"]

    cases.sort(key=lambda row: row["case_id"])
    raw = max(raw_segments, 1)
    report = {
        #: `segments_total` = 全语料的句窗总数；`raw_segments` = 实际**参评**的
        #: 候选数（`http` 来源按 stride 均匀抽样，`manual` 来源全取）。rejects 的
        #: 分母用后者——用前者会把"没抽到"混进"被拒绝"。
        "segments_total": segments_total,
        "raw_segments": raw_segments,
        "cases": len(cases),
        "quota_truncated": len(quota),
        "duplicates": len(duplicates),
        "rejects": len(rejects),
        "reject_ratio": round(len(rejects) / raw, 6),
        "per_type": counters,
        "per_domain": dict(sorted(per_domain.items())),
        "per_source": dict(sorted(per_source_docs.items())),
        #: 门限的**来源**：语料里显式枚举了几条（配额/去重之前）。产出少于它 = 漏抽。
        "enumerations_in_corpus": enumerations_in_corpus,
        "min_cases": 300,
    }
    return cases, rejects + duplicates + quota, report


def beat_positions(excerpt: str, beats: Sequence[str]) -> List[int]:
    """``excerpt`` 里每个节拍**首次**出现的位置；找不到给 ``-1``。"""
    positions: List[int] = []
    lowered = str(excerpt).lower()
    for beat in beats:
        cues = dict(BEAT_CUES).get(beat, ())
        hits = [lowered.find(cue.lower()) for cue in cues]
        hits = [position for position in hits if position >= 0]
        positions.append(min(hits) if hits else -1)
    return positions


def evaluate(cases: Sequence[Dict], report: Dict) -> Dict:
    """构建门：≥300 篇、逐行形状合法、套路条数与**节拍自洽**、rejects ≤5%、体积门。"""
    problems: List[str] = []
    if len(cases) < report["min_cases"]:
        problems.append(f"cases_too_few:{len(cases)}<{report['min_cases']}")
    if report["reject_ratio"] > BUILD_REJECT_RATIO:
        problems.append(f"rejects_over_5pct:{report['reject_ratio']}")
    # §2.3d T1 的消费对象。门限 = **本次语料实测的显式枚举条数**（见 `SEQUENCE_FLOOR`
    # 的注释：常量的旧依据是自撰笔记，已被用户裁决移出语料，用户对"无解"回过"改门限吧"）。
    # 两条都要：① 分母下界（语料里 0 条枚举 = 这条门测不到东西，判失败）；
    # ② **漏抽即红**（产出 < 语料里真实存在的枚举数）。
    expected = int(report.get("enumerations_in_corpus", 0))
    produced = int(report["per_type"]["sequence_pattern"])
    if expected < SEQUENCE_FLOOR:
        problems.append(f"sequence_enumerations_not_measured:{expected}")
    elif produced < expected:
        problems.append(f"sequence_pattern_dropped:{produced}<{expected}")
    for row in cases:
        if row["case_type"] not in CASE_TYPES:
            problems.append(f"bad_case_type:{row['case_id']}")
        if row["case_type"] == "sequence_pattern":
            beats = row["beat_sequence"]
            if len(beats) < 2 or any(beat not in BEAT_TYPES for beat in beats):
                problems.append(f"bad_beat_sequence:{row['case_id']}")
            else:
                # 节拍顺序必须与 excerpt 里出现的顺序一致，且每个节拍都能在
                # excerpt 里找到出处——否则这条"套路"就是标签与文本对不上。
                positions = beat_positions(row["excerpt"], beats)
                if any(position < 0 for position in positions):
                    problems.append(f"beat_not_in_excerpt:{row['case_id']}")
                elif positions != sorted(positions):
                    problems.append(f"beat_order_mismatch:{row['case_id']}")
        elif row["beat_sequence"]:
            problems.append(f"beats_on_non_pattern:{row['case_id']}")
        if not row["title"] or not row["excerpt"]:
            problems.append(f"empty_text:{row['case_id']}")
        missing = common.source_ref_problems(row["source_ref"])
        if missing:
            problems.append(f"source_ref_incomplete:{row['case_id']}:{missing}")
        if not common.license_allowed(row["source_ref"].get("license", "")):
            problems.append(f"license_not_allowed:{row['case_id']}")
        ok, reason = common.quote_check(row["excerpt"])
        if not ok:
            problems.append(f"quote_gate:{row['case_id']}:{reason}")
        if any(key in row for key in CONSTRAINT_KEYS):
            problems.append(f"carries_constraint:{row['case_id']}")
    return {"passed": not problems, "problems": problems[:20]}


def size_gate(cases_path: pathlib.Path, manifest_path: pathlib.Path) -> Dict:
    sizes = {path.name: path.stat().st_size
             for path in (cases_path, manifest_path) if path.is_file()}
    oversize = {name: size for name, size in sizes.items()
                if name == cases_path.name and size > MAX_CASE_FILE_BYTES}
    return {"sizes": sizes, "oversize": oversize, "passed": not oversize}


def _cards_digest() -> str:
    """入库卡片语料的摘要——**与超图指纹里的 `corpus_sha256` 同一函数**。

    L3（案例层）与 L1/L2（超图）是同一份语料的两个投影，所以两者必须记同一枚摘要；
    否则"L3 是不是这一份语料的产物"在干净克隆里无从判断（`work/` 不进版本库）。
    """
    from . import build_hypergraph

    return build_hypergraph.corpus_digest(build_hypergraph.load_cards())


def write_outputs(cases: Sequence[Dict], report: Dict, *, docs: Sequence[Dict],
                  out_cases: pathlib.Path = CASES_PATH,
                  out_manifest: pathlib.Path = MANIFEST_PATH) -> Dict:
    common.write_jsonl(out_cases, cases)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "template_version": TEMPLATE_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "decode": DECODE,
        "generator": {"model_id": "deterministic", "family": "deterministic",
                      "model_version": "n/a"},
        "corpus_fingerprint": corpus_fingerprint(docs),
        #: **与超图同一枚语料摘要**（`build_hypergraph.corpus_digest`）。
        #: 为什么必须记：L3 与 L1/L2 是**同一份语料**的两个投影，而 `work/` 下的
        #: 中间产物（`deduped.jsonl`）是被 gitignore 挡住的——只靠 `--check` 的话，
        #: 干净克隆里根本没有可比对的东西。2026-10-02 实测的代价：语料从 59 个来源
        #: 长到 75 之后，`cases.jsonl` **整整一天**没人重建，而它的每一道测试都只查
        #: 形状与数量下限，**没有一条查"它是不是这一份语料的产物"**；
        #: `tests/test_cases_corpus.py::test_the_committed_cases_come_from_the_committed_corpus`
        #: 现在拿这一格与 `hypergraph.manifest.json` 的 `cache_key.corpus_sha256` 对拍。
        "cards_sha256": _cards_digest(),
        "fingerprint": case_fingerprint(docs),
        **report,
    }
    common.dump_json(out_manifest, manifest)
    manifest["size_gate"] = size_gate(out_cases, out_manifest)
    common.dump_json(out_manifest, {**manifest})
    return manifest


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.build_cases")
    parser.add_argument("--input", default=str(INPUT))
    parser.add_argument("--out-cases", default=str(CASES_PATH))
    parser.add_argument("--out-manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--max-cases", type=int, default=DEFAULT_MAX_CASES)
    parser.add_argument("--per-source", type=int, default=DEFAULT_PER_SOURCE)
    parser.add_argument("--check", action="store_true",
                        help="只校验：重算后与已落盘产物逐字节比对，不写盘")
    args = parser.parse_args(list(argv) if argv is not None else None)

    source = pathlib.Path(args.input)
    if not source.is_file():
        print(json.dumps({"error": f"缺许可语料 {source}（先跑 tools/kb_fetch 的前六步）"},
                         ensure_ascii=False))
        return 1
    docs = common.read_jsonl(source)
    cases, rejected, report = build_cases(docs, max_cases=args.max_cases,
                                          per_source=args.per_source)
    verdict = evaluate(cases, report)
    payload = {"cases": len(cases), "rejects": len(rejected),
               "per_type": report["per_type"], "per_domain": report["per_domain"],
               "passed": verdict["passed"], "problems": verdict["problems"]}

    if args.check:
        current = common.read_jsonl(pathlib.Path(args.out_cases))
        same_cases = current == cases
        manifest_path = pathlib.Path(args.out_manifest)
        same_manifest = (manifest_path.is_file()
                         and json.loads(manifest_path.read_text(encoding="utf-8"))
                         .get("fingerprint") == case_fingerprint(docs))
        payload.update({"cases_match": same_cases, "manifest_match": same_manifest})
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if (verdict["passed"] and same_cases and same_manifest) else 1

    manifest = write_outputs(cases, report, docs=docs,
                             out_cases=pathlib.Path(args.out_cases),
                             out_manifest=pathlib.Path(args.out_manifest))
    payload["size_gate"] = manifest["size_gate"]
    payload["passed"] = bool(verdict["passed"] and manifest["size_gate"]["passed"])
    if not payload["passed"]:
        payload.setdefault("size_problems", manifest["size_gate"]["oversize"])
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
