"""P14-4 的可复算探针：插件检索器 → 真 sidecar → 三条通道注入（§2.3/§2.3b）。

它回答的是"接线到底通没通"这个只有真跑一次才能回答的问题：

* `/health` 是否宣告 `hypergraph`（索引在）；
* `_make_knowledge` 是否真的把 sidecar 装进检索器（`backend=hypergraph`、
  `degraded=False`）；
* 注入块里**有没有 `禁={...}`**——超边以整条为单位进了提示词；
* `retrieval_calls` 有没有与 `llm_calls` 分列记账；
* L3 那一栏（参考案例）在不在。

纯标准库、不用 Blender、不联网：只在本机回环上起一个 sidecar。

用法：
  python tools/probe_sidecar_wiring.py [--out docs/evidence/adhoc/wiring_probe.txt]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.contracts.transport import SidecarTransport  # noqa: E402
from block_director.layer5_orchestrator.headless_runner import (  # noqa: E402
    _make_knowledge,
)

#: §2.3 的 `约束查询` 形状（`SceneContract` 的结构化串）。
SHOT_QUERY = "情绪=荒诞；运镜=固定；景别=中景"
PLAN_QUERY = "情绪=紧张；景别=特写"


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_wiring_probe", ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="probe_sidecar_wiring")
    parser.add_argument("--knowledge-dir", default=str(ROOT / "knowledge"))
    parser.add_argument("--cases-backend", default="hybrid",
                        help="用 hybrid 才能在没有 LightRAG 依赖时也拿到案例栏")
    parser.add_argument("--out", default=str(ROOT / "docs" / "evidence" / "adhoc"
                                             / "wiring_probe.txt"))
    args = parser.parse_args(argv)

    sidecar = _load_sidecar()
    config = sidecar.SidecarConfig(sidecar.parse_args(
        ["--knowledge-dir", args.knowledge_dir,
         "--cases-backend", args.cases_backend]))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), sidecar.make_handler(config))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    retriever = _make_knowledge(AppConfig(),
                                SidecarTransport(base_url=base, timeout=30.0))
    shot_block = retriever.block_for_shot(SHOT_QUERY)
    plan_block = retriever.block_for_plan(PLAN_QUERY)
    httpd.shutdown()
    httpd.server_close()

    trace = retriever.trace_payload()
    trace_digest = json.dumps({k: trace.get(k) for k in
                               ("backend", "lanes", "cases_backend")},
                              ensure_ascii=False)
    lines: List[str] = [
        "命令：python tools/probe_sidecar_wiring.py",
        f"capabilities={[str(c) for c in config.capabilities]}",
        f"backend={retriever.backend} degraded={retriever.degraded} "
        f"retrieval_calls={retriever.retrieval_calls}",
        f"trace={trace_digest}",
        "",
        "【单镜注入块（节选）】",
        "\n".join(shot_block.splitlines()[:12]),
        "",
        "【整场预取块（节选）】",
        "\n".join(plan_block.splitlines()[:12]),
    ]
    report = "\n".join(lines)
    print(report)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report + "\n", encoding="utf-8")
    # 探针本身也是验收：这些条件不成立就该让调用方失败。
    ok = (str(retriever.backend) == "hypergraph"
          and not retriever.degraded
          and retriever.retrieval_calls >= 2
          and "禁={" in shot_block)
    if not ok:
        print("PROBE_FAILED：接线未通（backend/degraded/retrieval_calls/禁 四项之一不成立）",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
