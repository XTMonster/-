"""L3 案例层（执行文档 v1.4 §2.3b / §2.3d T1 / §3.1）。**纯 Python，不 import bpy**。

L3 与 L1/L2（超图）**不是同一种东西**：超图承载"条件 → 取舍/禁忌"的**多元约束**，
案例层承载"只能整段讲"的叙事与多跳关联（拉片笔记、影评、失败复盘、参考书摘，
以及序列型分镜套路）。因此两条纪律写死在类型层与渲染层：

1. **永不产出约束**：:class:`~block_director.contracts.knowledge.Case` **没有**
   ``forbid`` 字段，本模块也不渲染任何"必须/禁止"的措辞——这是 §2.3b 的 E3
   （经验越权率 = 0）在机制侧的保证，而不是靠调用方自觉；
2. **降级必须留痕**（§2.3b 的取值表）：``lightrag`` 依赖或索引不可用时退到
   ``hybrid``（BM25 ＋ 标签），并置 ``degraded=True`` ＋ 具名 ``reason``；
   ``off`` 是用户显式关闭——``cases[]`` 恒空但**不算降级**，两者不得混为一谈。

为什么 ``lightrag`` 走适配器协议而不是直接调库：LightRAG 的索引要靠它自己的
抽取管线（还需要模型与向量库）建出来，本仓库**没有**这个依赖、也没有对应的索引
产物，所以默认路径必然是 §2.3b 写明的降级路径。为了让"可用时"的分支不是死代码，
适配器走**注册协议**（见 :func:`register_lightrag_adapter`），由 sidecar 或测试注入；
真正接上 LightRAG 时只需注册一个工厂，取值、留痕与渲染都不必改。
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..contracts.knowledge import Case
from .bm25 import make_bm25, ranked, tokenize
from .tokens import estimate_tokens

#: §2.3b 的三个取值（写死；CLI 的 choices 也引用它）
CASE_BACKENDS: Tuple[str, ...] = ("lightrag", "hybrid", "off")
#: ``case_type`` 的冻结取值（§2.3b / §3.3 的线协议）
CASE_TYPES: Tuple[str, ...] = ("narrative", "sequence_pattern", "lesson")
#: ``beat_sequence`` 的取值词表——与 §2.3d T3 的 ``beat_type`` 同一套（不得自造）
BEAT_TYPES: Tuple[str, ...] = ("establish", "coverage", "reaction", "insert",
                               "transition")
#: 案例行里**不允许出现**的键：出现即"经验越权"（E3）。与
#: `tools/knowledge/quality.py::e3_cases` 扫的是同一组词。
CONSTRAINT_KEYS: Tuple[str, ...] = ("forbid", "forbids", "constraint")

CASES_FILE = "cases.jsonl"
MANIFEST_FILE = "cases.manifest.json"
LIGHTRAG_FINGERPRINT_FILE = "lightrag.fingerprint.json"

DEGRADED_NO_ADAPTER = "lightrag_adapter_unavailable"
DEGRADED_NO_INDEX = "lightrag_index_missing"

CASE_COLUMN_TITLE = "参考案例（仅参考）"


def repo_knowledge_dir() -> pathlib.Path:
    """仓库自带的索引目录（``<repo>/knowledge``）。"""
    return pathlib.Path(__file__).resolve().parents[2] / "knowledge"


# --------------------------------------------------------------------------- #
# 适配器协议：可用时用它，不可用时降级（§2.3b）
# --------------------------------------------------------------------------- #

#: 工厂签名：``(index_dir) -> adapter``；adapter 必须有
#: ``retrieve(query, *, top_k, cases) -> Sequence[Case]``。
_ADAPTER_FACTORIES: List[Callable[[pathlib.Path], Any]] = []


def register_lightrag_adapter(factory: Callable[[pathlib.Path], Any]) -> None:
    """注册一个 LightRAG 适配器工厂（最后注册的胜出，且只探测一次）。

    这是**扩展点**，不是"假装实现了 LightRAG"：仓库里没有 LightRAG 依赖与索引，
    默认路径就是 §2.3b 的降级路径；接上真依赖时由 sidecar 注册工厂即可。
    """
    if factory not in _ADAPTER_FACTORIES:
        _ADAPTER_FACTORIES.append(factory)


def reset_lightrag_adapters() -> None:
    """测试用：清掉已注册的适配器工厂。"""
    _ADAPTER_FACTORIES.clear()


def _find_lightrag_adapter(index_dir: pathlib.Path) -> Optional[Any]:
    """探测可用的 LightRAG 适配器；没有就返回 ``None``（调用方据此降级）。"""
    for factory in list(reversed(_ADAPTER_FACTORIES)):
        try:
            adapter = factory(index_dir)
        except Exception:  # noqa: BLE001 - 工厂失败＝该适配器不可用，换下一个
            continue
        if adapter is not None:
            return adapter
    return None


def lightrag_fingerprint(index_dir: Any) -> str:
    """读 ``lightrag.fingerprint.json``（§2.3b 要求 trace 必记）。缺文件返回空串。"""
    path = pathlib.Path(index_dir) / LIGHTRAG_FINGERPRINT_FILE
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if isinstance(payload, dict):
        return str(payload.get("fingerprint") or payload.get("sha256") or "")
    return ""


def manifest_fingerprint(index_dir: Any) -> str:
    """读 ``cases.manifest.json`` 的六元指纹（构建期留痕，供 trace 引用）。"""
    path = pathlib.Path(index_dir) / MANIFEST_FILE
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("fingerprint") or "") if isinstance(payload, dict) else ""


def read_cases(path: Any) -> List[Case]:
    """读 ``cases.jsonl``（逐行一个 :class:`Case`）。坏行**抛错**，不静默跳过。"""
    rows: List[Case] = []
    text = pathlib.Path(path).read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number} 不是合法 JSON：{exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{number} 不是对象：{type(payload).__name__}")
        rows.append(Case.from_dict(payload))
    return rows


def carries_constraint(row: Dict[str, Any]) -> bool:
    """这一行案例是否带了约束字段（E3 的机制侧判定）。"""
    return any(key in row for key in CONSTRAINT_KEYS)


# --------------------------------------------------------------------------- #
# 索引
# --------------------------------------------------------------------------- #


@dataclass
class CaseIndex:
    """L3 案例索引：三态选择 ＋ BM25 兜底 ＋ 原子渲染。

    与 sidecar 的取值语义**同名同义**（``requested`` / ``effective`` /
    ``degraded`` / ``reason`` / ``enabled``），因此 sidecar 直接复用本类即可，
    不必再维护第二份实现。
    """

    cases: Sequence[Case] = ()
    backend: str = "lightrag"
    reason: str = ""
    fingerprint: str = ""
    lightrag_index_fingerprint: str = ""
    adapter: Optional[Any] = None
    _engine: Optional[Any] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.cases = list(self.cases)
        self.requested = str(self.backend)
        self.effective = str(self.backend)
        self.degraded = False
        if self.backend == "off":
            return
        if self.reason:                      # 索引缺失/读不出来：明确降级
            self.degraded = True
            self.effective = "off"
            return
        if self.backend == "lightrag" and self.adapter is None:
            # §2.3b 的降级路径：退到 hybrid，并留下具名原因（不是静默）。
            self.degraded = True
            self.effective = "hybrid"
            self.reason = DEGRADED_NO_ADAPTER
        if self.effective == "hybrid" and self.cases:
            documents = [tokenize(self._text(case)) for case in self.cases]
            self._engine, _name = make_bm25(documents)

    # --------------------------------------------------------------- 自述
    @property
    def enabled(self) -> bool:
        return self.requested != "off" and self.effective != "off"

    @property
    def lanes(self) -> int:
        """§2.4：L3 开启时检索是两通道（``lanes = 2``），关闭时一条。"""
        return 2 if self.enabled else 1

    def describe(self) -> Dict[str, Any]:
        return {"cases_backend": self.effective,
                "cases_requested_backend": self.requested,
                "cases_degraded": bool(self.degraded),
                "cases_degraded_reason": self.reason,
                "cases": len(self.cases),
                "lanes": self.lanes,
                "lightrag_index_fingerprint": self.lightrag_index_fingerprint,
                "cases_index_fingerprint": self.fingerprint}

    # --------------------------------------------------------------- 检索
    @staticmethod
    def _text(case: Case) -> str:
        """检索**只吃作者写的字**：`excerpt` ＋ 出处标题。

        为什么不能把 `case_id` 与 `title` 也算进去（2026-10-02 实测）：`title` 是我们
        生成的标签（`镜头与焦距：Practical Cinema摘记086`），`case_id` 是
        `case_pg76304_txt_007` —— 两者都不是作者写的。把标签喂进 BM25 的直接后果是
        **拿中文查询去"命中"中文标签前缀**：`偷盗者奔逃中…` 会命中 `镜头与焦距：…`
        里的 `镜/头` 两个字，于是案例层总是返回一堆与作者原文毫无关系的 1900 年代
        散句（双模型面板 1–2 分，E1 = 0/16）。`source_ref.tags` 同样是**我们的**域标签
        （`色彩`／`剪辑与节奏`），实测它让中文查询单字命中（查询里的 `色`／`画`／`向`
        命中标签里的同一个字），所以一并去掉。去掉之后中文查询不再有词命中
        ——**返回空是诚实的"没有参考案例"，返回噪声不是**。
        """
        source = case.source_ref if isinstance(case.source_ref, dict) else {}
        return "\n".join([case.excerpt, str(source.get("title", ""))])

    def retrieve(self, query: str, top_k: int = 3) -> List[Case]:
        """取参考案例；不可用/无命中返回 ``[]``（**不抛**，也不造假数据）。"""
        if not self.enabled or not self.cases:
            return []
        limit = max(1, int(top_k))
        if self.effective == "lightrag" and self.adapter is not None:
            try:
                hits = list(self.adapter.retrieve(query, top_k=limit,
                                                  cases=self.cases))
            except Exception as exc:  # noqa: BLE001 - 记因由并降级，不静默
                self.degraded = True
                self.effective = "hybrid"
                self.reason = f"lightrag_query_failed:{type(exc).__name__}"
                documents = [tokenize(self._text(case)) for case in self.cases]
                self._engine, _name = make_bm25(documents)
            else:
                return self._scored(hits, limit)
        if self._engine is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scored = ranked(self._engine, tokens, 0)
        hits = [(index, score) for index, score in scored if score > 0]
        hits.sort(key=lambda item: (-item[1], self.cases[item[0]].case_id))
        return self._scored(hits, limit)

    def _scored(self, hits: Sequence[Any], limit: int) -> List[Case]:
        out: List[Case] = []
        for item in list(hits)[:limit]:
            if isinstance(item, tuple):
                case, score = self.cases[item[0]], float(item[1])
                out.append(Case.from_dict({**case.to_dict(),
                                           "score": round(score, 4)}))
            elif isinstance(item, Case):
                out.append(item)
            else:                             # 适配器回的是 dict
                out.append(Case.from_dict(dict(item)))
        return out


def load_index(knowledge_dir: Any, backend: str = "lightrag",
               *, adapter: Optional[Any] = None) -> CaseIndex:
    """装配 L3 索引。缺索引/坏索引**不抛**，而是回一个带具名原因的降级对象。"""
    directory = pathlib.Path(knowledge_dir)
    if str(backend) == "off":
        return CaseIndex([], "off")
    path = directory / CASES_FILE
    if not path.is_file():
        return CaseIndex([], str(backend), reason="cases_index_missing")
    try:
        cases = read_cases(path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return CaseIndex([], str(backend),
                         reason=f"cases_index_unreadable:{type(exc).__name__}")
    if not cases:
        return CaseIndex([], str(backend), reason="cases_index_empty")
    chosen = adapter
    if chosen is None and str(backend) == "lightrag":
        if (directory / LIGHTRAG_FINGERPRINT_FILE).is_file():
            chosen = _find_lightrag_adapter(directory)
    return CaseIndex(cases, str(backend),
                     fingerprint=manifest_fingerprint(directory),
                     lightrag_index_fingerprint=lightrag_fingerprint(directory),
                     adapter=chosen)


# --------------------------------------------------------------------------- #
# 渲染（§2.3b 的第三栏；原子注入，绝不截断）
# --------------------------------------------------------------------------- #


def render_case(case: Case) -> str:
    """一条案例的注入文本：标题 ＋ 序列（若有）＋ 摘要 ＋ **出处**。"""
    lines = [f"[{case.case_id}] {case.title}"]
    if case.beat_sequence:
        lines.append("序列：" + "→".join(str(beat) for beat in case.beat_sequence))
    if case.excerpt:
        lines.append(case.excerpt)
    source = case.source_ref if isinstance(case.source_ref, dict) else {}
    parts = [str(source.get(key) or "").strip()
             for key in ("title", "author", "license")]
    attribution = "／".join(part for part in parts if part)
    if attribution:
        lines.append("出处：" + attribution)
    return "\n".join(lines)


def render_cases(cases: Sequence[Case], token_limit: int,
                 title: str = CASE_COLUMN_TITLE) -> Tuple[str, List[str]]:
    """把参考案例渲染成"仅参考"栏；**装不下就整条丢弃**（与超边同一纪律）。

    返回 ``(文本, dropped_case_ids)``。文本为空表示一条都没装下——调用方据此
    不要输出空栏。绝不截断：截断会把"出处"切掉，模型就分不清"某人的经验"
    与"必守的规则"。
    """
    lines: List[str] = []
    dropped: List[str] = []
    used = 0
    for case in cases:
        line = render_case(case)
        cost = estimate_tokens(line) + 1
        if used + cost > int(token_limit):
            dropped.append(str(case.case_id))
            continue
        lines.append(line)
        used += cost
    if not lines:
        return "", dropped
    return f"【{title}】\n" + "\n\n".join(lines), dropped
