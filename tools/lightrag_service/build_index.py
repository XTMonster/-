"""P7：把案例层建成 LightRAG 索引（**两条嵌入路线：本地 GPU bge ／ 云端智谱 embedding-3**）。

可行性已实测（`docs/knowledge/UPSTREAM_LIGHTRAG.md` §五）。三条**部署硬要求**：

1. `embedding_func` 必须是 `EmbeddingFunc` **实例**（上游读 `.func`）；
2. 必须在 **import transformers 之前**设 `HF_ENDPOINT=https://hf-mirror.com`
   （本机 `huggingface.co` 不可达，不设就整条管线崩）；
3. `llm_model_func` 是检索路径的**必要参数**（hybrid 模式会用它抽关键词），
   按用户 U10 用 DeepSeek。

嵌入路线由 `--embedding-route` 选（`local` 默认 / `cloud`），**它们不是同一个索引**：
指纹第三格写成 `<路由>:<模型>:<维度>`，消费端（`LightRAGIndex`）按这一格装嵌入器
——换路线必然换代，旧索引不可能被拿错嵌入器检索。

可离线测的纯函数在上半部分；重活（真建库）在下半部分，只在 venv 里跑。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import pathlib
import re
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

try:
    from . import manifest as lm  # type: ignore
except ImportError:  # pragma: no cover - 直跑
    from tools.lightrag_service import manifest as lm  # type: ignore

#: 文档前缀：检索回来的上下文里因此带着 id（`case_ids_in_context` 靠它还原）。
CASE_PREFIX = "[CASE %s]"
_CASE_RE = re.compile(r"\[CASE\s+([^\]]+)\]")

#: 单次检索的超时（秒）。LightRAG 的 `hybrid`/`local`/`global` 模式会调 LLM 抽关键词，
#: 本来就慢；但"卡死"必须变成**具名失败**（`serve.py` 翻成 `index_error:TimeoutError`），
#: 不许把 sidecar 挂在那里、也不许伪装成"成功空列表"。
DEFAULT_QUERY_TIMEOUT = 120.0


def case_documents(cases: Sequence[Dict],
                   clues: Optional[Dict[str, str]] = None) -> List[Tuple[str, str]]:
    """`[{case_id, excerpt, ...}]` → `[(case_id, 带前缀的文档)]`。

    缺 `case_id` 的案例**拒收**（`ValueError`）——没有 id 就没法把检索结果还原成
    本仓的 `Case`，收下它等于往索引里塞不可引用的东西。

    `clues` 是**中文检索线索**（`tools/kb_fetch/case_search_zh.py` 产出）。为什么
    LightRAG 也要它（2026-10-05 实测）：产品的查询是**中文散文**，案例原文是英文；
    另两条臂（hybrid / lexical）的检索面是"案例文本 ＋ 线索"
    （见 `block_director.knowledge.cases.CaseIndex._text`），只有 LightRAG 臂是
    `title+excerpt`。同一个 E1 面板，**三条臂必须拿同一把尺子**——否则
    "LightRAG 更差"里混着"它的文档少了中文面"这个与检索算法无关的差别。
    线索**只是检索键**：返回给模型的仍是作者的 `excerpt`，一个字不改。
    """
    out: List[Tuple[str, str]] = []
    for case in cases:
        case_id = str(case.get("case_id") or "").strip()
        if not case_id:
            raise ValueError("案例缺 case_id（没了它检索结果还原不回本仓的 Case）")
        excerpt = str(case.get("excerpt") or "").strip()
        title = str(case.get("title") or "").strip()
        clue = str((clues or {}).get(case_id) or "").strip()
        body = "\n".join(part for part in (title, excerpt, clue) if part)
        out.append((case_id, "%s %s" % (CASE_PREFIX % case_id, body)))
    return out


def case_ids_in_context(context: str) -> List[str]:
    """从检索上下文里抠出 case_id（**顺序＝相关度序**，去重保首个）。"""
    seen: List[str] = []
    for match in _CASE_RE.finditer(str(context or "")):
        case_id = match.group(1).strip()
        if case_id and case_id not in seen:
            seen.append(case_id)
    return seen


def case_files(source: pathlib.Path) -> List[pathlib.Path]:
    """案例源可以是**单文件**，也可以是**分片目录**（`part-*.jsonl`）。

    实测踩过：案例层落盘是分片的（`knowledge/cases/part-000.jsonl`），
    直接传 `.../cases.jsonl` 会 `FileNotFoundError`。
    """
    path = pathlib.Path(source)
    if path.is_dir():
        return sorted(path.glob("part-*.jsonl"))
    return [path]


def load_cases(source: pathlib.Path) -> List[Dict]:
    cases: List[Dict] = []
    try:  # noqa: PLC0415 - 只在这一步用到构建期工具
        from tools.kb_fetch import common as kb_common  # type: ignore
    except ImportError:  # pragma: no cover
        kb_common = None
    for path in case_files(source):
        #: **必须**用 `common.read_jsonl`（只按换行符切）：`splitlines()` 会按
        #: Unicode 行边界切开 JSON 字符串（`\u2028` 一类）。守门
        #: `tests/test_jsonl_reading_convention.py` 当场抓过我一次。
        if kb_common is not None:
            cases.extend(kb_common.read_jsonl(path))
            continue
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                cases.append(json.loads(line))
    return cases


def cases_digest(source: pathlib.Path) -> str:
    """**案例集合自己**的摘要（跨分片；换一条案例就变；语料指纹对它不敏感）。"""
    payload = hashlib.sha256()
    for path in case_files(source):
        payload.update(str(path.name).encode("utf-8"))
        for line in path.read_bytes().split(b"\n"):
            if line.strip():
                payload.update(line.strip())
                payload.update(b"\n")
    return payload.hexdigest()


def index_cells(cases_path: pathlib.Path, *, lightrag_version: str,
                embedding: str, build_args: Dict) -> Dict:
    """四格指纹的取值——**从产物现算**，不是手填。"""
    return {"cases_digest": cases_digest(cases_path),
            "lightrag_version": str(lightrag_version),
            "embedding": str(embedding),
            "build_args": dict(build_args or {})}


def embedding_cell(route: str, model: str, dim: int) -> str:
    """指纹第三格的**规范写法**：`<路由>:<模型>:<维度>`。

    换路由（本地 ↔ 云端）／换模型／换维度，都是**另一代索引**——指纹必须变，
    否则换了嵌入器还能命中旧索引（本项目最怕的那类静默 no-op）。

    实测（2026-10-05）：用户买下智谱 `embedding-3` 资源包后它可用了——
    `dim 2048`、单条 0.4 s；`embedding-2` 仍报 1113（资源包只覆盖 embedding-3）。
    所以现在有**两代**可对照：`local:bge-small-zh-v1.5:512` 与
    `cloud:embedding-3:2048`。
    """
    return "%s:%s:%d" % (str(route), str(model), int(dim))


def embedding_route_of(cell: str) -> Tuple[str, str, int]:
    """指纹第三格 → ``(路由, 模型, 维度)``；**解析不出就抛**（不猜、不退回默认）。

    为什么需要它（2026-10-05 的实缺陷）：`LightRAGIndex._ensure()` 写死了本地
    `_load_embedding()`。索引的 manifest 里第三格明明指名道姓
    （`cloud:embedding-3:2048`），检索端却仍装 512 维的本地模型——用户一改用云端
    那一代，检索就会**拿错嵌入器**（维度对不上直接崩，或"恰好"跑起来却把查询
    映到另一个空间，静默出垃圾）。构建期做了代际纪律，这里是**消费期的同一条**。
    """
    parts = str(cell or "").split(":")
    if len(parts) != 3:
        raise ValueError("嵌入格形状不对（应为 `<路由>:<模型>:<维度>`）：%r" % (cell,))
    route, model, dimension = parts[0].strip(), parts[1].strip(), parts[2].strip()
    if route not in ("local", "cloud"):
        raise ValueError("未知嵌入路由 %r（只认 local/cloud）：%r" % (route, cell))
    if not model:
        raise ValueError("嵌入格缺模型名：%r" % (cell,))
    try:
        dim = int(dimension)
    except ValueError as exc:
        raise ValueError("嵌入格缺维度（应为整数）：%r" % (cell,)) from exc
    return route, model, dim


def load_embedding_for(cell: str):
    """按**格子记的路由**装嵌入器；维度与格子不符 ⇒ 抛（不许静默换一代）。"""
    route, model, dim = embedding_route_of(cell)
    if route == "cloud":
        embed, actual = _load_cloud_embedding(model)
    else:
        embed, actual = _load_embedding(model)
    if int(actual) != int(dim):
        raise RuntimeError("嵌入维度与索引不符：格记 %d，实得 %d（换嵌入器必须整体重建）"
                           % (dim, actual))
    return embed, int(actual)


def clues_digest(clues: Optional[Dict[str, str]]) -> str:
    """线索层的**内容**摘要（`case_id` ＋ `zh`，与顺序无关）。

    为什么需要它（2026-10-05）：四格指纹的第一格 `cases_digest` 只摘**案例分片**
    （`cases/part-*.jsonl`），线索分片不在里面。而 LightRAG 的文档现在**含线索**
    ——只改一条线索的文案（条数不变）→ 第一格不动 ⇒ 旧索引照旧被当成现行。
    这正是本项目反复吃过的"换了输入还能命中旧派生"（S0 缓存键、`53d3e3f` 手抄 trace）。
    把线索层的内容也摘进 `build_args`，换线索即换指纹。
    """
    payload = hashlib.sha256()
    for case_id, text in sorted((clues or {}).items()):
        payload.update(str(case_id).encode("utf-8"))
        payload.update(b"\x00")
        payload.update(str(text).encode("utf-8"))
        payload.update(b"\n")
    return payload.hexdigest()


def batches(items: Sequence, size: int):
    """把序列按 `size` 切批。`size <= 0` ⇒ 整批一次（不分批）。"""
    data = list(items)
    if size is None or int(size) <= 0:
        return [data] if data else []
    step = int(size)
    return [data[index:index + step] for index in range(0, len(data), step)]


def _load_cloud_embedding(model: str = "embedding-3"):
    """智谱云端嵌入（OpenAI 兼容的 `/embeddings`）。key 只从环境变量读。"""
    import os
    import urllib.request
    import numpy as np
    key = os.environ.get("GLM_API_KEY", "")

    async def embed(texts):
        if isinstance(texts, str):
            texts = [texts]
        body = json.dumps({"model": model, "input": list(texts)}).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - 固定 https 端点
            "https://open.bigmodel.cn/api/paas/v4/embeddings", data=body, method="POST",
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        vectors = [item.get("embedding") for item in payload.get("data") or []]
        if not vectors or any(vector is None for vector in vectors):
            raise RuntimeError("云端嵌入回包缺向量")
        return np.asarray(vectors, dtype="float32")

    return embed, 2048


def _load_embedding(model_name: str = "BAAI/bge-small-zh-v1.5"):
    """本地 GPU 嵌入。**必须**先设 `HF_ENDPOINT`（见模块 docstring 第 2 条）。"""
    import os
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    import torch
    from transformers import AutoModel, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModel.from_pretrained(model_name, trust_remote_code=True)
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)

    async def embed(texts):
        if isinstance(texts, str):
            texts = [texts]
        with torch.no_grad():
            batch = tokenizer(list(texts), padding=True, truncation=True,
                              max_length=512, return_tensors="pt")
            batch = {key: value.to(device) for key, value in batch.items()}
            out = model(**batch).last_hidden_state[:, 0]
            out = torch.nn.functional.normalize(out, p=2, dim=1)
        return out.cpu().numpy()

    return embed, 512


def chat_messages(prompt, system_prompt="") -> List[Dict]:
    """把 `llm_model_func` 收到的两段拼成 OpenAI 的 messages。

    **`system_prompt` 必须带过去**（实测 2026-10-05 抓到的根因）：LightRAG 的
    **格式规范写在 system prompt 里**（`entity<|#|>name<|#|>type<|#|>desc`，
    收尾 `<|COMPLETE|>`）。第一版实现只发了 user 消息，模型于是自己编了个
    `A | rel | B` 的写法 —— 索引建完 `graphml` 里 **0 节点 0 边**、每篇文档
    `entity_names: []`，`hybrid`/`local`/`global` 三种模式全废，只剩 `naive`。
    """
    messages: List[Dict] = []
    if str(system_prompt or "").strip():
        messages.append({"role": "system", "content": str(system_prompt)})
    messages.append({"role": "user", "content": str(prompt)})
    return messages


def _deepseek_model_func():
    """检索/构建路径的 LLM（用户 U10：沿用别家方案处的内部 LLM 用 DeepSeek）。"""
    import os
    import urllib.request
    key = os.environ.get("DEEPSEEK_API_KEY", "")

    async def call(prompt, system_prompt="", **kwargs):
        if not key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY（只从环境变量读）")
        body = json.dumps({
            "model": "deepseek-chat", "temperature": 0,
            #: **`system_prompt` 一定要传**（格式规范在它里面，见 `chat_messages`）。
            "messages": chat_messages(prompt, system_prompt),
        }).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - 固定 https 端点
            "https://api.deepseek.com/chat/completions", data=body, method="POST",
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        return str(((payload.get("choices") or [{}])[0].get("message") or {})
                   .get("content") or "")

    return call


def build(cases_path: pathlib.Path, out_dir: pathlib.Path, *,
          llm_model_func: Optional[Callable] = None,
          embedding_model: str = "BAAI/bge-small-zh-v1.5",
          embedding_route: str = "local",
          mode: str = "naive", limit: int = 0,
          batch_size: int = 40, max_parallel_insert: int = 8,
          clue_mode: str = "local") -> Dict:
    """真建索引。`out_dir/lightrag/` 是 LightRAG 的 working_dir。"""
    import asyncio
    import lightrag as lightrag_pkg
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc

    cases = load_cases(cases_path)
    if limit:
        cases = cases[:limit]
    #: 中文线索（与案例分片同住 `<案例目录>/search_zh.part-*.jsonl`）。缺/陈旧
    #: **不抛**——那是设计内的降级（退回"只吃原文"），但状态会如实写进 manifest，
    #: 于是"这一代索引没有中文面"在产物里**看得见**：v4 那次三臂 E1 从 0.20 塌到
    #: 0.0065 就是因为这条降级**没有任何痕迹**。
    clues: Dict[str, str] = {}
    clue_state = "clues_off"
    if str(clue_mode) == "local":
        from block_director.knowledge import cases as block_cases  # noqa: PLC0415
        clues, clue_state = block_cases.read_search_zh(cases_path, cases_path)
    docs = case_documents(cases, clues)
    #: 两条嵌入路线（**指纹第三格会随它变**，所以它们是两代索引）：
    #: `local`＝本地 torch/CUDA（bge-small-zh，512 维）；`cloud`＝智谱 embedding-3
    #: （2048 维，用户 2026-10-05 购买资源包后可用）。
    if embedding_route == "cloud":
        embed, dim = _load_cloud_embedding(embedding_model or "embedding-3")
    else:
        embed, dim = _load_embedding(embedding_model)
    version = str(getattr(lightrag_pkg, "__version__", "unknown"))
    working = pathlib.Path(out_dir) / "lightrag"
    working.mkdir(parents=True, exist_ok=True)
    if llm_model_func is None:
        llm_model_func = _deepseek_model_func()
    rag = LightRAG(working_dir=str(working), llm_model_func=llm_model_func,
                   #: **批量并发**：默认 `max_parallel_insert=3`，而逐篇 `await`
                   #: 把它压回串行（实测 49 篇要 30 分钟）。
                   max_parallel_insert=int(max_parallel_insert),
                   embedding_func=EmbeddingFunc(embedding_dim=dim,
                                                max_token_size=512, func=embed))

    async def _run():
        await rag.initialize_storages()
        inserted = 0
        for group in batches([text for _case_id, text in docs], int(batch_size)):
            #: `ainsert` 收列表 ⇒ 走内部并发（比逐篇 await 快数倍）。
            await rag.ainsert(group)
            inserted += len(group)
            print(json.dumps({"inserted": inserted, "of": len(docs)}), flush=True)
        await rag.finalize_storages()

    asyncio.run(_run())
    cells = index_cells(pathlib.Path(cases_path), lightrag_version=version,
                        embedding=embedding_cell(embedding_route, embedding_model, dim),
                        build_args={"mode": mode, "cases": len(docs),
                                    "clues": len(clues),
                                    #: 线索层的**内容**摘要：`cases_digest` 只摘案例分片，
                                    #: 只改一条线索的文案（条数不变）第一格不动 ⇒ 会把旧
                                    #: 索引当成现行。摘进来，换线索即换指纹。
                                    "clues_digest": clues_digest(clues)})
    payload = lm.write(out_dir, cells, extra={"documents": len(docs),
                                              "clues": len(clues),
                                              "clue_state": clue_state})
    print(json.dumps({"overall": "pass", "documents": len(docs),
                      "clues": len(clues), "clue_state": clue_state,
                      "fingerprint": payload["fingerprint"],
                      "out": str(working)}, ensure_ascii=False))
    return payload


class LightRAGIndex:
    """服务层要的索引接口：`fingerprint` / `version` / `search(query, top_k)`。

    事件循环纪律（2026-10-05 实测缺陷）
    ==================================
    以前 `search()` 每次调用都 `asyncio.run()`——每次新建一条事件循环，而
    `self._rag`（它身上挂着 `EmbeddingFunc` 的 `PriorityQueue`／连接池／锁）是
    跨调用复用的对象。异步原语绑定在第一次的那条循环上，第二次调用必抛
    `... is bound to a different event loop`。实测 `work/_sidecar4.err` 里 5773 行
    同一条错误；`serve.py` 是 `ThreadingHTTPServer`（每请求一个新 OS 线程），
    只会让问题更早复现。

    修法：本对象自持一条常驻事件循环（专用守护线程），`initialize_storages()` 与
    每次 `aquery()` 都用 `run_coroutine_threadsafe` 提交到同一条循环上运行——
    "复用同一个对象"于是也就"复用同一条循环"。
    """

    def __init__(self, index_dir: pathlib.Path, *, mode: str = "naive",
                 rag_factory: Optional[Callable[[], Any]] = None,
                 query_param_factory: Optional[Callable[..., Any]] = None,
                 query_timeout: float = DEFAULT_QUERY_TIMEOUT) -> None:
        self.index_dir = pathlib.Path(index_dir)
        shipped = lm.read(self.index_dir) or {}
        self.fingerprint = str(shipped.get("fingerprint") or "")
        cells = shipped.get("cells") or {}
        self.version = str(cells.get("lightrag_version") or "")
        #: **嵌入器必须与索引同代**（第三格）。装不上就 fail closed（`search` 抛，
        #: `serve.py` 把它翻成具名的 `index_error:<类型>`），绝不"用本地的先跑着看"。
        self.embedding_cell = str(cells.get("embedding") or "")
        #: 检索模式**必须可变量化**：`naive` 只用向量，而 `hybrid`/`local`/`global`
        #: 需要**非空图谱**（图谱由构建期的实体抽取填，见 `chat_messages` 那段）。
        self.mode = str(mode or "naive")
        self.query_timeout = float(query_timeout)
        #: 两个注入缝（默认走真实的 lightrag）：核心缺陷"跨循环复用"因此能**离线**
        #: 复现——假 rag 自己带"换循环就抛"的判据，不需要装 lightrag。
        self._rag_factory = rag_factory
        self._query_param_factory = query_param_factory
        self._rag = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._loop_guard = threading.Lock()
        self._query_guard = threading.Lock()

    # ---- 常驻事件循环 ----
    def _loop_for_queries(self) -> asyncio.AbstractEventLoop:
        """取（必要时启动）那条常驻循环；每条索引只有一条。"""
        with self._loop_guard:
            loop = self._loop
            if loop is not None and not loop.is_closed():
                return loop
            ready = threading.Event()
            holder: Dict[str, Any] = {}

            def _boot() -> None:  # pragma: no cover - 线程体；行为由可注入的假 rag 覆盖
                booted = asyncio.new_event_loop()
                asyncio.set_event_loop(booted)
                holder["loop"] = booted
                ready.set()
                booted.run_forever()

            thread = threading.Thread(target=_boot, name="lightrag-loop", daemon=True)
            thread.start()
            ready.wait(timeout=5.0)
            booted = holder.get("loop")
            if booted is None:  # pragma: no cover - 只有线程起不来才会走到
                raise RuntimeError("lightrag 常驻事件循环启动失败")
            self._loop, self._loop_thread = booted, thread
            return booted

    def close(self) -> None:
        """停掉常驻循环（服务退出时调；不调也只是留下一条守护线程）。"""
        with self._loop_guard:
            loop, thread = self._loop, self._loop_thread
            self._loop = self._loop_thread = None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
            if thread is not None:
                thread.join(timeout=5.0)
            if not loop.is_running():
                loop.close()

    # ---- 检索 ----
    def _query_param(self, **kwargs) -> Any:
        if self._query_param_factory is not None:
            return self._query_param_factory(**kwargs)
        from lightrag import QueryParam
        return QueryParam(**kwargs)

    async def _ensure(self):
        if self._rag is None:
            if self._rag_factory is not None:
                self._rag = await self._rag_factory()
            else:
                self._rag = await self._build_rag()
        return self._rag

    async def _build_rag(self):
        from lightrag import LightRAG
        from lightrag.utils import EmbeddingFunc
        embed, dim = load_embedding_for(self.embedding_cell)
        #: `llm_model_func` 是**必要参数**（不是可选的）：上游 `lightrag.py:1512`
        #: 直接 `raise ValueError("llm_model_func must be provided")`——
        #: 这正是 `UPSTREAM_LIGHTRAG.md` §二那条"检索路径也会调用 LLM"的现场印证。
        rag = LightRAG(working_dir=str(self.index_dir / "lightrag"),
                       llm_model_func=_deepseek_model_func(),
                       embedding_func=EmbeddingFunc(embedding_dim=dim,
                                                    max_token_size=512,
                                                    func=embed))
        await rag.initialize_storages()
        return rag

    async def _search_async(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        rag = await self._ensure()
        context = await rag.aquery(query, param=self._query_param(
            mode=self.mode, only_need_context=True))
        ids = case_ids_in_context(str(context or ""))
        return [(case_id, 1.0 - index * 0.01)
                for index, case_id in enumerate(ids[:top_k])]

    def search(self, query: str, top_k: int = 5,
               timeout: Optional[float] = None) -> List[Tuple[str, float]]:
        """检索：`only_need_context=True`（**不生成**），从上下文还原 case_id。

        所有查询都提交到**同一条常驻循环**；超过 `timeout` 抛 `TimeoutError`
        （`serve.py` 翻成 `index_error:TimeoutError`，不伪装成空列表）。
        `_query_guard` 把并发查询串行化——LightRAG 的存储层不是为并发查询设计的，
        而"稳"在这里比"快"重要（一次 63 查询的评测里，串行完全跑得动）。
        """
        budget = self.query_timeout if timeout is None else float(timeout)
        with self._query_guard:
            loop = self._loop_for_queries()
            future = asyncio.run_coroutine_threadsafe(
                self._search_async(query, top_k), loop)
            try:
                return future.result(budget)
            except concurrent.futures.TimeoutError as exc:
                future.cancel()
                raise TimeoutError(
                    "lightrag 检索超时（%.0f s）：%s" % (budget, str(query)[:40])) from exc


if __name__ == "__main__":  # pragma: no cover
    import argparse
    parser = argparse.ArgumentParser(prog="lightrag_service.build_index")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--embedding-route", default="local",
                        choices=("local", "cloud"),
                        help="local=本地 torch/CUDA（bge-small-zh，512 维）；"
                             "cloud=智谱 embedding-3（2048 维）")
    parser.add_argument("--embedding-model", default="",
                        help="留空时按路由取默认（local→BAAI/bge-small-zh-v1.5；cloud→embedding-3）")
    parser.add_argument("--clues", default="local", choices=("local", "none"),
                        help="local＝并入案例层的中文检索线索（与另两条臂同一把尺子）；"
                             "none＝只吃 author 的 title+excerpt")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=40,
                        help="每次 ainsert 塞几篇（列表走内部并发；逐篇 await 会串行）")
    parser.add_argument("--max-parallel-insert", type=int, default=8)
    cli = parser.parse_args()
    model = cli.embedding_model or ("embedding-3" if cli.embedding_route == "cloud"
                                    else "BAAI/bge-small-zh-v1.5")
    build(pathlib.Path(cli.cases), pathlib.Path(cli.out),
          embedding_route=cli.embedding_route, embedding_model=model,
          limit=cli.limit, batch_size=cli.batch_size,
          max_parallel_insert=cli.max_parallel_insert, clue_mode=cli.clues)
