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

import hashlib
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
#: 中文检索线索（`tools/kb_fetch/case_search_zh.py` 产出）。**只是检索键**：
#: 返回给模型的仍然是作者的原文 `excerpt`，一个字都不改。
SEARCH_ZH_FILE = "cases.search_zh.jsonl"

#: **分片布局**（2026-10-04）。为什么需要它：§2.3c 的入库体积门写着
#: "单文件 ≤ 512 KB、总量 ≤ 20 MB"（`tools/kb_fetch/common.py::MAX_CARD_FILE_BYTES`），
#: 卡片层靠"一域一个文件"天然满足它，而案例层把整库塞进一份 `cases.jsonl`
#: ——于是**配额被迫按单文件反推**：`build_cases.DEFAULT_MAX_CASES = 810`
#: （实测：810 条 = 499 KB；`--max-cases 3804` 写出来 2.34 MB，`size_gate.passed=false`）。
#: 后果不是"文件大了点"，而是**供给被掐掉九成**：许可语料里的候选段
#: `raw_segments = 10463`，入库只有 810（`quota_truncated = 9376`），而那 810 条里
#: 只有**一个**来源产出过"面板判 ≥4"的案例（见 `docs/evidence/20261004-e1-vocab/`）。
#:
#: 分片**不放松任何门**：每片仍 ≤ 512 KB、总量仍 ≤ 20 MB，只是把"一份文件"
#: 换成"一份索引"——与 `knowledge/cards_generated/` 同一口径。
CASES_DIRNAME = "cases"
#: 案例分片的命名（有序，`part-000.jsonl`、`part-001.jsonl`…）。
CASE_SHARD_GLOB = "part-*.jsonl"
#: 中文线索的分片（与案例分片同住 `cases/`，名字带 `search_zh.` 前缀以便区分）。
SEARCH_ZH_SHARD_GLOB = "search_zh.part-*.jsonl"

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


def case_paths(index_dir: Any) -> List[pathlib.Path]:
    """案例分片的路径（**有序**）。**单一入口**——调用方不许各自 glob。

    认三种形状，**同一套读取代码**（所以旧检出仍然读得动，分片是换代不是迁移）：

    * `<index_dir>/cases/part-*.jsonl` —— 现在发货的布局（`index_dir` = `knowledge/`）；
    * `<index_dir>/part-*.jsonl` —— 直接把分片目录本身传进来时；
    * `<index_dir>/cases.jsonl` —— 旧的单文件布局。
    """
    directory = pathlib.Path(index_dir)
    shards = [path for path in sorted(directory.glob(CASE_SHARD_GLOB))
              if path.is_file()]
    if not shards:
        shards = [path for path in sorted((directory / CASES_DIRNAME)
                                          .glob(CASE_SHARD_GLOB)) if path.is_file()]
    if shards:
        return shards
    legacy = directory / CASES_FILE
    return [legacy] if legacy.is_file() else []


def search_zh_paths(index_dir: Any) -> List[pathlib.Path]:
    """中文线索的分片路径（**有序**）；没有分片时回落旧的单文件。"""
    directory = pathlib.Path(index_dir)
    shards = [path for path in sorted(directory.glob(SEARCH_ZH_SHARD_GLOB))
              if path.is_file()]
    if not shards:
        shards = [path for path in sorted((directory / CASES_DIRNAME)
                                          .glob(SEARCH_ZH_SHARD_GLOB))
                  if path.is_file()]
    if shards:
        return shards
    legacy = directory / SEARCH_ZH_FILE
    return [legacy] if legacy.is_file() else []


def cases_digest(paths: Sequence[Any]) -> str:
    """一组分片的**字节摘要**：按序把每片的字节拼起来再哈希。

    与旧布局**逐字节兼容**：只有一片时它等于 `sha256(那一份文件的字节)`
    ——中文线索文件里记的 `cases_sha256` 因此不用换口径。
    """
    digest = hashlib.sha256()
    for path in paths:
        digest.update(pathlib.Path(path).read_bytes())
    return digest.hexdigest()


def _sources(source: Any) -> List[pathlib.Path]:
    """`read_cases` 的入参规整：目录 → 分片；文件 → 它自己。"""
    path = pathlib.Path(source)
    if path.is_dir():
        return case_paths(path)
    return [path]


def read_cases(source: Any) -> List[Case]:
    """读案例（逐行一个 :class:`Case`）。坏行**抛错**，不静默跳过。

    `source` 可以是**目录**（`knowledge/`）或**任意一份文件**（旧布局的单文件、
    或单独一片）。分片按文件名排序拼接，顺序稳定。
    """
    rows: List[Case] = []
    for path in _sources(source):
        text = path.read_text(encoding="utf-8")
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


def read_search_zh(directory: Any, cases_source: Any) -> Tuple[Dict[str, str], str]:
    """读中文检索线索，返回 ``({case_id: 中文}, 拒用原因)``。

    **代际纪律**（与 §24.1 的案例层陈旧门同一条）：线索文件记着自己生成时
    案例索引的**字节摘要**；对不上就整份不用（返回空 + 具名原因），
    而不是把一批"指向上一条案例"的线索喂进 BM25——那会静默地把检索带偏。

    `cases_source` 可以是 `knowledge/`（目录，走 :func:`case_paths` 的分片），
    也可以是旧的单文件路径——摘要口径见 :func:`cases_digest`（单片时与旧值逐字节相同）。
    线索本身也支持分片（`cases/search_zh.part-*.jsonl`）。
    """
    paths = search_zh_paths(directory)
    if not paths:
        return {}, "search_zh_missing"
    try:
        digest = cases_digest(_sources(cases_source))
        out: Dict[str, str] = {}
        seen_digest = ""
        seen_prompt = ""
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                seen_digest = str(row.get("cases_sha256") or "")
                prompt = str(row.get("prompt_sha256") or "")
                #: **同文件里不许混代**：不同行记着不同 `prompt_sha256` 就说明
                #: 这份文件是"跑了一半又改了提示词"的产物。整份拒用，不当成"各代
                #: 都算数"——混代的键既不等于旧代也不等于新代，检索面会静默偏掉。
                if prompt:
                    if seen_prompt and prompt != seen_prompt:
                        return {}, "search_zh_mixed_prompt"
                    seen_prompt = prompt
                case_id, zh = str(row.get("case_id") or ""), str(row.get("zh") or "")
                if case_id and zh:
                    out[case_id] = zh
        if not out:
            return {}, "search_zh_empty"
        if seen_digest != digest:
            return {}, "search_zh_stale"
        #: **代际基准在 manifest 上**（`clue_attached.prompt_sha256`）。`block_director`
        #: 不许 import `tools/`，所以基准只能由产物自己带；manifest 记了就**必须**
        #: 对上，否则这次读数用的是别的提示词产出的键，E1 会静默地不是当前口径。
        expected_prompt = clue_prompt_sha(index_dir=directory)
        if expected_prompt and seen_prompt and seen_prompt != expected_prompt:
            return {}, "search_zh_prompt_stale"
        if expected_prompt and not seen_prompt:
            return {}, "search_zh_prompt_unverified"
        return out, ""
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {}, f"search_zh_unreadable:{type(exc).__name__}"


def clue_prompt_sha(index_dir: Any) -> str:
    """manifest 里记的**线索生成代际**（`clue_attached.prompt_sha256`）。

    没记就返回空串（旧产物）：调用方据此**不做**那一步比对——判据不变严也不放松，
    只是"没记就没有可比的东西"。
    """
    path = pathlib.Path(index_dir) / MANIFEST_FILE
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    attached = payload.get("clue_attached") if isinstance(payload, dict) else None
    if not isinstance(attached, dict):
        return ""
    return str(attached.get("prompt_sha256") or "")


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
    #: `case_id -> 中文检索线索`（空 = 没有可用线索，退回"只吃原文"的旧行为）。
    search_zh: Dict[str, str] = field(default_factory=dict)
    #: **相关性过滤器**（可选）：`(query, cases) -> Sequence[Case]`。
    #:
    #: 为什么需要它（2026-10-03 实测）：E1 是**精确率**指标——"返回的案例里相关
    #: （≥4/5）的比例"。BM25 只懂词面：查询"…表情从困惑转为狂喜"的 top-1 是 1900 年代
    #: 一句"银幕明星在每种表情和每个角度下都应同样美丽"（只是短 + 命中"表情"）。
    #: 离线实验（`work/zz_e1_rerank_sim.py`，用**已记录**的面板分算）：
    #: 对 top-8 做一次"只留真的能指导这一镜怎么拍"的过滤之后，E1 从 **3/18 = 0.167**
    #: 升到 **3/7 = 0.429**——留下的还是那三条相关的，去掉的是 11 条噪声。
    #: 对产品也是真改进：塞给模型的"参考案例"里一半是无关噪声时，它只会误导。
    #:
    #: 过滤器由**调用方注入**（sidecar 用上游模型装配；进程内路径没有模型，保持不装）。
    #: 它**只许做减法**（返回入参的子集），不许引入新案例——否则检索面就不确定了。
    case_filter: Optional[Callable[[str, Sequence[Case]], Sequence[Case]]] = None
    filter_reason: str = ""
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
            documents = [tokenize(self._text(case, self.search_zh.get(case.case_id)))
                         for case in self.cases]
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
                "cases_filter": "on" if self.case_filter is not None else "off",
                "cases_filter_reason": self.filter_reason,
                "lanes": self.lanes,
                "lightrag_index_fingerprint": self.lightrag_index_fingerprint,
                "cases_index_fingerprint": self.fingerprint}

    # --------------------------------------------------------------- 检索
    @staticmethod
    def _text(case: Case, extra: Optional[str] = None) -> str:
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
        `extra` 是这条案例的**中文检索线索**（有的话）。它不是我们编的理论——它是
        `tools/kb_fetch/case_search_zh.py` 对**作者自己的摘录**做的中文改写，存在的
        唯一理由是"产品的查询是中文、语料是英文"：没有它，BM25 对中文查询**恒 0 命中**
        （实测 6/6 逐镜查询命中 0，E1 连分母都没有）。上面那条"不要把**我们的标签**喂进来"
        的纪律不受影响：线索是**内容的翻译**，不是分类标签。
        """
        source = case.source_ref if isinstance(case.source_ref, dict) else {}
        parts = [case.excerpt, str(source.get("title", ""))]
        if extra:
            parts.append(str(extra))
        return "\n".join(parts)

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
                return self._filtered(query, self._scored(hits, limit))
        if self._engine is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scored = ranked(self._engine, tokens, 0)
        hits = [(index, score) for index, score in scored if score > 0]
        hits.sort(key=lambda item: (-item[1], self.cases[item[0]].case_id))
        return self._filtered(query, self._scored(hits, limit))

    def _filtered(self, query: str, cases: List[Case]) -> List[Case]:
        """过一遍相关性过滤器；**只许做减法**，失败就如实记账并原样返回。

        `case_filter` 由 sidecar 注入（上游模型）。它抛错时**不能**把整条检索弄挂：
        退回未过滤的结果，并把原因写进 `filter_reason`（trace 里看得到）。
        """
        if self.case_filter is None or not cases:
            return cases
        try:
            kept = list(self.case_filter(query, cases))
        except Exception as exc:  # noqa: BLE001 - 过滤是增强，不是关键路径
            self.filter_reason = f"cases_filter_failed:{type(exc).__name__}"
            return cases
        allowed = {str(case.case_id) for case in cases}
        kept = [case for case in kept if str(getattr(case, "case_id", "")) in allowed]
        self.filter_reason = ""
        return kept

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
               *, adapter: Optional[Any] = None,
               case_filter: Optional[Callable[[str, Sequence[Case]], Sequence[Case]]] = None
               ) -> CaseIndex:
    """装配 L3 索引。缺索引/坏索引**不抛**，而是回一个带具名原因的降级对象。"""
    directory = pathlib.Path(knowledge_dir)
    if str(backend) == "off":
        return CaseIndex([], "off")
    paths = case_paths(directory)
    if not paths:
        return CaseIndex([], str(backend), reason="cases_index_missing")
    try:
        cases = read_cases(directory)
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
                     adapter=chosen,
                     search_zh=read_search_zh(directory, directory)[0],
                     case_filter=case_filter)


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
