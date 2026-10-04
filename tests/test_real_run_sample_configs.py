"""真跑样例配置**不许静默降级知识栈**（2026-10-04 实测踩出来的）。

现场：`fixtures/local_sidecar.config.yaml` 里写死 `rag.backend: bm25`，而
`contracts/config.py` 与 `specs/config.default.yaml` 的默认是 **hypergraph**
（v1.4 §2.3：「后端默认是超图；装了 sidecar 客户端就走 ``/v1/retrieve``」）。

后果不是"慢一点"，是**两条链一起断**：

* `bm25` 走的是插件进程里的内置卡片检索，**不发 `/v1/retrieve`** ⇒ L1/L2 的
  `forbid` 禁忌栏与三栏注入里的超图那一栏从来没进过提示词；
* 审计里因此一条 `retrieval_call` 都没有（long14 六十四镜实测
  `retrieval_calls: 0`）⇒ §4.1b 的 Q5 join **结构性**没有分母，永远 `not_measured`。

所以这里钉两条：样例请求超图；**请求超图但没有能力/索引时必须降级并留痕**——
降级可以，静默不行（那正是 `tests/test_knowledge_trace.py` 的负例）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.enums import RagBackend  # noqa: E402

SAMPLES = ("fixtures/local_sidecar.config.yaml",
           "fixtures/local_model.config.yaml")


def _load(path: str):
    import yaml

    text = (ROOT / path).read_text(encoding="utf-8")
    return yaml.safe_load(text)


def test_the_real_run_samples_request_the_hypergraph_backend():
    """两条真跑样例都必须请求超图——否则 Q5 与 `forbid` 那两栏一起断。"""
    for path in SAMPLES:
        payload = _load(path)
        backend = str((payload.get("rag") or {}).get("backend", ""))
        assert backend == RagBackend.HYPERGRAPH.value, (
            f"{path} 的 rag.backend={backend!r}：真跑样例写死 bm25 会让 /v1/retrieve "
            f"永不发生（Q5 没有分母、forbid 那一栏永不注入）")


def test_the_shipped_default_agrees_with_the_samples():
    """样例与出厂默认不能各说一套（v1.4 §2.3 的唯一真源是 contracts/config.py）。"""
    from block_director.contracts.config import AppConfig

    assert AppConfig().rag.backend is RagBackend.HYPERGRAPH
    for path in SAMPLES:
        assert (str((_load(path).get("rag") or {}).get("backend", ""))
                == AppConfig().rag.backend.value)
