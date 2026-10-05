"""P7：把案例层建成 LightRAG 索引（**本地 GPU 嵌入，不需要云端 embedding、不需要 key**）。

可行性已实测（`docs/knowledge/UPSTREAM_LIGHTRAG.md` §五）。三条**部署硬要求**：

1. `embedding_func` 必须是 `EmbeddingFunc` **实例**（上游读 `.func`）；
2. 必须在 **import transformers 之前**设 `HF_ENDPOINT=https://hf-mirror.com`
   （本机 `huggingface.co` 不可达，不设就整条管线崩）；
3. `llm_model_func` 是检索路径的**必要参数**（hybrid 模式会用它抽关键词），
   按用户 U10 用 DeepSeek。

可离线测的纯函数在上半部分；重活（真建库）在下半部分，只在 venv 里跑。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from typing import Callable, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

try:
    from . import manifest as lm  # type: ignore
except ImportError:  # pragma: no cover - 直跑
    from tools.lightrag_service import manifest as lm  # type: ignore

#: 文档前缀：检索回来的上下文里因此带着 id（`case_ids_in_context` 靠它还原）。
CASE_PREFIX = "[CASE %s]"
_CASE_RE = re.compile(r"\[CASE\s+([^\]]+)\]")


def case_documents(cases: Sequence[Dict]) -> List[Tuple[str, str]]:
    """`[{case_id, excerpt, ...}]` → `[(case_id, 带前缀的文档)]`。

    缺 `case_id` 的案例**拒收**（`ValueError`）——没有 id 就没法把检索结果还原成
    本仓的 `Case`，收下它等于往索引里塞不可引用的东西。
    """
    out: List[Tuple[str, str]] = []
    for case in cases:
        case_id = str(case.get("case_id") or "").strip()
        if not case_id:
            raise ValueError("案例缺 case_id（没了它检索结果还原不回本仓的 Case）")
        excerpt = str(case.get("excerpt") or "").strip()
        title = str(case.get("title") or "").strip()
        body = "\n".join(part for part in (title, excerpt) if part)
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


def _deepseek_model_func():
    """检索路径的 LLM（用户 U10：沿用别家方案处的内部 LLM 用 DeepSeek）。"""
    import os
    import urllib.request
    key = os.environ.get("DEEPSEEK_API_KEY", "")

    async def call(prompt, **kwargs):
        if not key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY（只从环境变量读）")
        body = json.dumps({
            "model": "deepseek-chat", "temperature": 0,
            "messages": [{"role": "user", "content": str(prompt)}],
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
          mode: str = "naive", limit: int = 0) -> Dict:
    """真建索引。`out_dir/lightrag/` 是 LightRAG 的 working_dir。"""
    import asyncio
    import lightrag as lightrag_pkg
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc

    cases = load_cases(cases_path)
    if limit:
        cases = cases[:limit]
    docs = case_documents(cases)
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
                   embedding_func=EmbeddingFunc(embedding_dim=dim,
                                                max_token_size=512, func=embed))

    async def _run():
        await rag.initialize_storages()
        for index, (_case_id, text) in enumerate(docs, 1):
            await rag.ainsert(text)
            if index % 50 == 0:
                print(json.dumps({"inserted": index, "of": len(docs)}), flush=True)
        await rag.finalize_storages()

    asyncio.run(_run())
    cells = index_cells(pathlib.Path(cases_path), lightrag_version=version,
                        embedding=embedding_cell(embedding_route, embedding_model, dim),
                        build_args={"mode": mode, "cases": len(docs)})
    payload = lm.write(out_dir, cells, extra={"documents": len(docs)})
    print(json.dumps({"overall": "pass", "documents": len(docs),
                      "fingerprint": payload["fingerprint"],
                      "out": str(working)}, ensure_ascii=False))
    return payload


class LightRAGIndex:
    """服务层要的索引接口：`fingerprint` / `version` / `search(query, top_k)`。"""

    def __init__(self, index_dir: pathlib.Path) -> None:
        self.index_dir = pathlib.Path(index_dir)
        shipped = lm.read(self.index_dir) or {}
        self.fingerprint = str(shipped.get("fingerprint") or "")
        self.version = str((shipped.get("cells") or {}).get("lightrag_version") or "")
        self._rag = None

    async def _ensure(self):
        if self._rag is None:
            from lightrag import LightRAG
            from lightrag.utils import EmbeddingFunc
            embed, dim = _load_embedding()
            #: `llm_model_func` 是**必要参数**（不是可选的）：上游 `lightrag.py:1512`
            #: 直接 `raise ValueError("llm_model_func must be provided")`——
            #: 这正是 `UPSTREAM_LIGHTRAG.md` §二那条"检索路径也会调用 LLM"的现场印证。
            self._rag = LightRAG(working_dir=str(self.index_dir / "lightrag"),
                                 llm_model_func=_deepseek_model_func(),
                                 embedding_func=EmbeddingFunc(embedding_dim=dim,
                                                              max_token_size=512,
                                                              func=embed))
            await self._rag.initialize_storages()
        return self._rag

    def search(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """检索：`only_need_context=True`（**不生成**），从上下文还原 case_id。"""
        import asyncio
        from lightrag import QueryParam

        async def _run():
            rag = await self._ensure()
            context = await rag.aquery(query, param=QueryParam(
                mode="naive", only_need_context=True))
            ids = case_ids_in_context(str(context or ""))
            return [(case_id, 1.0 - index * 0.01)
                    for index, case_id in enumerate(ids[:top_k])]

        return asyncio.run(_run())


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
    parser.add_argument("--limit", type=int, default=0)
    cli = parser.parse_args()
    model = cli.embedding_model or ("embedding-3" if cli.embedding_route == "cloud"
                                    else "BAAI/bge-small-zh-v1.5")
    build(pathlib.Path(cli.cases), pathlib.Path(cli.out),
          embedding_route=cli.embedding_route, embedding_model=model,
          limit=cli.limit)
