"""Lever A, prototype driver: cloud embedding-3 rerank as the E1 delivery arm.

Why this is a *prototype* and not an instrument (honest labelling):
  * the RULER is 100% frozen -- `e1_panel.judge` / `summarise` / `rerank_cases` /
    `score_queries` are imported, not re-implemented; the queries are the same 64
    (long21 project), the judges the same two, the judging context the same C=3,
    the threshold the same 4.0 and the line the same 0.70;
  * the ONLY new ingredient is *which* label-free reranker picks the delivered 3,
    and it is injected through the frozen seam (`score_queries(rerank=...)`) with a
    fake-proof encoder (`tools/kb_fetch/embedding_cloud.py`, unit-tested offline).
  * so the number this prints is a *direction reading*; before it is quoted as the
    official E1 it must be re-run through the frozen instrument with the cloud
    route promoted into `e1_panel.load_embedder` (a separate, explicitly frozen commit).

Run:  python -u work/_e1_cloud_arm.py --retrieve-k 20 --workers 6 --tag k20
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.cases import load_index            # noqa: E402
from tools.kb_fetch import llm                                   # noqa: E402
from tools.kb_fetch.embedding_cloud import make_cloud_encoder    # noqa: E402
from tools.knowledge import e1_panel                             # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="docs/evidence/20261006-long21/project/project.bdproj")
    parser.add_argument("--cases-dir", default="knowledge")
    parser.add_argument("--retrieve-k", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--judge-batch", type=int, default=3)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--embed-model", default="embedding-3")
    parser.add_argument("--tag", default="k20")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    queries = e1_panel.queries_from_project(ROOT / args.project)
    if args.limit:
        queries = queries[:args.limit]
    index = load_index(ROOT / args.cases_dir, backend="hybrid")
    clients = [("deepseek-chat", llm.make_client("deepseek", "deepseek-chat")),
               ("glm-5.3", llm.make_client("glm", "glm-5.3"))]
    handshake = getattr(e1_panel, "preflight", None)
    if handshake is not None:
        failures = handshake(clients)
        print(json.dumps({"preflight_failures": failures}, ensure_ascii=False))
        if failures:
            return 3
    encoder = make_cloud_encoder(model=args.embed_model, expected_dim=2048)
    clue_of = lambda cid: (getattr(index, "search_zh", None) or {}).get(cid, "")  # noqa: E731
    scorer = e1_panel.make_embedding_reranker(encoder=encoder, clue_of=clue_of)
    label = "cloud:%s+clue" % args.embed_model
    rows = e1_panel.score_queries(index, queries, clients, top_k=args.top_k,
                                  workers=args.workers, rerank=scorer,
                                  retrieve_k=args.retrieve_k, rerank_label=label,
                                  judge_batch=args.judge_batch)
    out = ROOT / (args.out or "work/_e1_cloud_%s.jsonl" % args.tag)
    out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                   encoding="utf-8", newline="\n")
    summary = {"tag": args.tag, "retrieve_k": args.retrieve_k, "queries": len(queries),
               "rerank_label": label, "out": str(out),
               **e1_panel.summarise(rows)}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
