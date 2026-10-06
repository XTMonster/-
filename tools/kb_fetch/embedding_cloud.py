"""智谱**云端嵌入**（`embedding-3`）的同步客户端：给"重排臂"提供一个**确定性、可缓存**的编码器。

为什么要有它（不是"顺手多加一个工具"）
====================================

* `docs/knowledge/OPEN_PROBLEMS.md` 的 **P3** 是空位：本地 `bge-small-zh-v1.5` 做重排实测是
  **负结果**（0.0938 / 0.0833，比不重排的 0.2188 还差），于是"嵌入重排"这个位置一度被判死；
  但同一份清单记着 **D3 的实测**——**同一路由换云端嵌入器，E1 提高约 5.6 倍**
  （`docs/evidence/20261005-d3-embedding/`：本地 512 维 0.020833 → 云端 2048 维 0.117188）。
  也就是说：**负结果属于那个本地模型，不属于"嵌入重排"这条路**。
* 用户 2026-10-05 买下智谱 `embedding-3` 资源包后该路线可用（`ADJUDICATIONS_v4.md` D3：
  `dim 2048`、单条 0.4 s；`embedding-2` 仍报 1113）。
* 它天然**不看判分** ⇒ 拿它构造"去标签池"完全合法（GPT-6A 的 RK-13 裁定禁止选择器看判分，
  这正是 `docs/knowledge/E1_LEVERS_v1.md` 的杠杆 A）。

它为什么必须是"确定性 + 可缓存"的
------------------------------
`tools/knowledge/e1_panel.py` 的每条打分记录都自述 `cases_rerank` 标签；**同一个标签下重跑若
得到不同分数，"这条臂更好"就不可复算**。所以：同一份 (model, text) 永远返回同一个向量，
并落磁盘缓存——第二次跑（换池深、换判分语境）**零网络调用**。

它为什么必须**吵**（而不是静默降级）
------------------------------
本仓红线：缺 key、额度不足、维度不符**都不许**悄悄退回别的模型或返回零向量——那会把
"云端嵌入臂"的读数污染成"某个没人知道的替代品"的读数。所以一律 `CloudEmbeddingError`
抛出来，消息里带**是谁**（模型）、**为什么**（状态码／错误码／字段缺失）。

与 `tools/lightrag_service/build_index.py::_load_cloud_embedding()` 的关系
--------------------------------------------------------------------
那一份是 **async**（给它自己的事件循环用）；本模块是**同步**的，好让
`e1_panel --cases-rerank embedding` 那条单线程/线程池路径直接调用，并且**带缓存**。
两者的端点、模型名、维度约定一致（`https://open.bigmodel.cn/api/paas/v4/embeddings`、
`embedding-3`、2048）；密钥都**只从环境变量读**，绝不写进仓库。
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 智谱的 OpenAI 兼容嵌入端点（与 `build_index.py` 同一个）。
ZHIPU_EMBEDDINGS_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"

#: 默认缓存落在 `work/`（gitignore 的草稿区）：它是**可重建**的中间产物，不是证据，
#: 所以不进库；但它必须存在，否则每换一个池深都要把 1,280 条文本重编一遍。
DEFAULT_CACHE = ROOT / "work" / "_embedding_cache.jsonl"

#: 传输类失败（超时、连接被掐）**才**值得重试；额度/鉴权类重试只会白等。
_TRANSIENT = (urllib.error.URLError, TimeoutError, ConnectionError, OSError)


class CloudEmbeddingError(RuntimeError):
    """云端嵌入的任何具名失败：缺 key／HTTP 状态／回包结构／维度不符。"""


def api_key_from_env(env: Optional[Dict[str, str]] = None) -> str:
    """读密钥：`ZHIPU_API_KEY` 优先，其次 `GLM_API_KEY`（同一个账号的两个常见命名）。

    都没有 ⇒ 抛具名错误（**不返回空串**，也不退回本地模型——那是静默降级）。
    """
    source = os.environ if env is None else env
    for name in ("ZHIPU_API_KEY", "GLM_API_KEY"):
        value = str(source.get(name) or "").strip()
        if value:
            return value
    raise CloudEmbeddingError(
        "缺少智谱嵌入密钥：环境变量 ZHIPU_API_KEY 与 GLM_API_KEY 都为空"
        "（密钥只从环境变量读，不许写进仓库）")


def _cache_key(model: str, text: str) -> str:
    return hashlib.sha256(("%s\x00%s" % (model, text)).encode("utf-8")).hexdigest()


def read_cache(path: pathlib.Path) -> Dict[str, List[float]]:
    """读磁盘缓存（缺文件 ⇒ 空表）。行格式见模块 docstring 与 `encode` 的写入。"""
    out: Dict[str, List[float]] = {}
    if not pathlib.Path(path).exists():
        return out
    with pathlib.Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                #: 半行／坏行**跳过但不崩**：缓存是可重建的中间产物，
                #: 坏一行只该让它被重编一次，不该让整条臂跑不起来。
                continue
            key, vector = row.get("key"), row.get("vector")
            if isinstance(key, str) and isinstance(vector, list) and vector:
                out[key] = [float(value) for value in vector]
    return out


def _default_post(url: str, payload: Dict, headers: Dict[str, str],
                  timeout: float) -> Dict:
    """真发请求（`urllib`，零依赖）。错误一律翻成 `CloudEmbeddingError` 并带上状态码。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise CloudEmbeddingError("HTTP %s: %s" % (exc.code, detail)) from exc
    except urllib.error.URLError as exc:      # 连接被拒／DNS／超时都落这里
        raise CloudEmbeddingError("传输失败: %s" % (exc.reason,)) from exc


def make_cloud_encoder(model: str = "embedding-3", api_key: str = "",
                       cache_path: Optional[pathlib.Path] = None, batch: int = 16,
                       timeout: float = 90.0, retries: int = 3,
                       expected_dim: int = 0,
                       post: Optional[Callable[[str, Dict, Dict[str, str], float], Dict]] = None,
                       ) -> Callable[[Sequence[str]], List[List[float]]]:
    """造一个 `encode(texts) -> List[List[float]]`：**确定性、带缓存、失败具名**。

    * `post` 注入了就**完全**用注入的（守门测试靠它，绝不联网）；
    * `cache_path=None` ⇒ 用 `work/_embedding_cache.jsonl`；`cache_path=""` 这类"不要缓存"
      的用法**不给**——缓存是这条臂可复算的一部分，不该被随手关掉；
    * `expected_dim>0` 时逐条校验维度（`embedding-3` 是 2048）。
    """
    key = (str(api_key).strip() or api_key_from_env())
    path = pathlib.Path(DEFAULT_CACHE if cache_path is None else cache_path)
    sender = post or _default_post
    size = max(1, int(batch))
    tries = max(1, int(retries))
    cache = read_cache(path)

    def _request(texts: Sequence[str]) -> List[List[float]]:
        payload = {"model": str(model), "input": list(texts)}
        headers = {"Authorization": "Bearer %s" % key,
                   "Content-Type": "application/json"}
        last: Optional[Exception] = None
        for attempt in range(tries):
            try:
                reply = sender(ZHIPU_EMBEDDINGS_URL, payload, headers, float(timeout))
                break
            except CloudEmbeddingError as exc:
                message = str(exc)
                #: 429（限流）与 5xx **值得重试**；其余 4xx（鉴权／余额／参数）立刻抛，
                #: 重试只会把"额度没了"拖成"跑了两小时才发现"。
                retryable = ("HTTP 429" in message or "传输失败" in message
                             or "HTTP 5" in message)
                if not retryable or attempt == tries - 1:
                    raise
                last = exc
            except _TRANSIENT as exc:          # 注入的 post 抛原生异常也照样重试
                if attempt == tries - 1:
                    raise CloudEmbeddingError("传输失败: %s" % (exc,)) from exc
                last = exc
            time.sleep(min(2.0 ** attempt, 8.0))
        else:  # pragma: no cover - 上面的分支已经把最后一步抛掉了
            raise CloudEmbeddingError("重试 %d 次仍失败: %s" % (tries, last))
        if not isinstance(reply, dict):
            raise CloudEmbeddingError("回包不是 JSON 对象：%r" % (type(reply).__name__,))
        error = reply.get("error")
        if error:
            #: 智谱把"无可用资源包"这类写成 `error.code`（实测 1113）。**立即抛**：
            #: 它不是抖动，重试没有意义。
            raise CloudEmbeddingError("上游报错 %s: %s" % (error, str(error)[:200])
                                      if not isinstance(error, dict) else
                                      "上游报错 %s: %s" % (error.get("code"),
                                                           str(error.get("message"))[:200]))
        data = reply.get("data")
        if not isinstance(data, list):
            raise CloudEmbeddingError("回包里没有 data 数组：%s" % (str(reply)[:200],))
        vectors: List[List[float]] = []
        for position, item in enumerate(data):
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list) or not vector:
                raise CloudEmbeddingError("第 %d 条回包缺 embedding" % position)
            if expected_dim and len(vector) != int(expected_dim):
                raise CloudEmbeddingError(
                    "第 %d 条维度不符：%d ≠ 期望 %d" % (position, len(vector), expected_dim))
            vectors.append([float(value) for value in vector])
        if len(vectors) != len(texts):
            raise CloudEmbeddingError("回包条数不符：%d ≠ 请求 %d"
                                      % (len(vectors), len(texts)))
        widths = {len(vector) for vector in vectors}
        if len(widths) != 1:
            raise CloudEmbeddingError("同一次回包内维度不一致：%s" % (sorted(widths),))
        return vectors

    def encode(texts: Sequence[str]) -> List[List[float]]:
        items = [str(text) for text in texts]
        need: List[str] = []
        seen = set()
        for text in items:
            digest = _cache_key(str(model), text)
            if digest in cache or digest in seen:
                continue
            seen.add(digest)
            need.append(text)
        fresh: Dict[str, List[float]] = {}
        for start in range(0, len(need), size):
            chunk = need[start:start + size]
            for text, vector in zip(chunk, _request(chunk)):
                fresh[_cache_key(str(model), text)] = vector
        if fresh:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                for digest, vector in fresh.items():
                    handle.write(json.dumps({"key": digest, "model": str(model),
                                             "vector": vector}, ensure_ascii=False) + "\n")
            cache.update(fresh)
        out: List[List[float]] = []
        for text in items:
            digest = _cache_key(str(model), text)
            if digest not in cache:
                raise CloudEmbeddingError(
                    "缓存里没有这条文本、也没拿到新向量（内部不一致）：%s" % text[:80])
            out.append(list(cache[digest]))
        return out

    return encode
