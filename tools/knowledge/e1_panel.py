"""E1（经验引用相关性 ≥70%）的**打分通道**：把一次真实运行的逐镜查询与案例层召回的案例打分。

为什么要有这个工具（而不是留在 `work/` 里）
==========================================
链上 `tools/run_tests.ps1` 的 `quality.py --e1-reviews <file>` 消费的是**这个工具
产出的文件**，而在此之前那份文件是由 `work/zz_e1_panel.py` ＋ `work/zz_e1_zh_measure.py`
两个**未跟踪**的临时脚本生成的——"链的输入来自一个不在库里的脚本"就是
`ACCEPTANCE_STATUS.md` §24.1 那个"过期证据被当成现行证据"的同一形状：没人能复算，
也没人能在换代之后重跑。本工具把它固化下来。

判据（与 §2.3b 一致，一个字没改）
================================
* 单位是**逐镜**：查询取每一镜自己的散文（编辑器喂给 L3 的那段 `analogy`），
  不是计划期那种把整段剧本塞进去的串（那种串判官只能答"不知道"）。
* 召回 `top_k` 条案例，**两个不同族**的模型（默认 deepseek-chat ＋ glm-5.3，
  见 `DEFAULT_PANEL`——本账号的智谱资源包只覆盖 `glm-5.3`）
  逐条打 1–5 分；`score ≥ 4` 记为相关。
* 每条记录写明 `reviewed_by: "llm-panel"`（**绝不冒充 `human`**）、面板模型、
  提示指纹，以及**这一份案例索引的指纹**——`quality.py::e1_evidence_is_stale`
  靠后者判"这批打分是不是这一代语料"，缺了只能记 `stale_evidence`。

用法::

  python tools/knowledge/e1_panel.py --project <run>/project/project.bdproj \
      --out docs/evidence/<run>/e1_reviews.jsonl
  python tools/knowledge/e1_panel.py --queries work/queries.txt --out ...      # 手给查询
  python tools/knowledge/e1_panel.py ... --scripted work/stub.json             # 离线自测
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.cases import load_index  # noqa: E402
from tools.kb_fetch import llm  # noqa: E402

#: 用户裁决（2026-10-04）：**GLM 只用 `glm-5.3`**——智谱的资源包按模型分开计费，
#: 这个账号下只有 `glm-5.3` 还有额度（`glm-4.7` 会 429「余额不足或无可用资源包」，
#: 实测见 `docs/knowledge/ACCEPTANCE_STATUS.md` §七十八）。
DEFAULT_PANEL = ("deepseek-chat", "glm-5.3")
DEFAULT_FAMILIES = ("deepseek", "glm")
RELEVANT = 4.0
#: 判分是**逐查询独立**的，所以并发只改吞吐、不改产物（行序仍按查询序）。
#: 默认 4：实测串行跑一次 64 查询 × 2 模型要一小时以上，通道就没法复算了；
#: 4 是"比串行快得多、又不至于把上游打成 429"的折中（429 由客户端长退避兜底）。
DEFAULT_WORKERS = 4

SYSTEM = (
    "你是分镜预演工具的知识检索复核员。下面给你一条**导演查询串**和若干条被检索回来的"
    "**参考案例**。请判断每条案例对这条查询是否**真的相关**（能不能拿来指导这一次拍摄）。\n"
    "只输出 JSON：{\"scores\":[{\"case_id\":\"...\",\"score\":1-5,\"reason\":\"不超过 20 字\"}]}\n"
    "5=直接相关且可照做；4=相关；3=沾边；2=几乎无关；1=完全无关。"
)


def queries_from_project(path: pathlib.Path) -> List[str]:
    """每一镜的散文查询（`prompt`）——**与编辑器喂给 L3 的那段文字同源**。

    `shots.json`（交付清单）不带 `prompt`，所以这里读的是工程文件 `project.bdproj`。
    计划期那种"剧本《…》：4 场…"的串被丢掉：它把整段剧本塞进 query，
    判官无从判断"这条案例相关吗"。
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    shots = [shot for scene in payload.get("scenes") or []
             for shot in (scene.get("shots") or [])]
    out: List[str] = []
    for shot in shots:
        text = str(shot.get("prompt") or "").strip()
        if text and "剧本《" not in text and text not in out:
            out.append(text)
    return out


def queries_from_lines(path: pathlib.Path) -> List[str]:
    out: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and text not in out:
            out.append(text)
    return out


def judge(client, query: str, cases) -> Dict[str, Dict[str, Any]]:
    listing = "\n".join(
        "%s｜%s｜%s" % (case.case_id, str(getattr(case, "title", ""))[:60],
                       str(getattr(case, "summary", "")
                           or getattr(case, "excerpt", ""))[:220])
        for case in cases)
    #: `key=query` 是给 `scripted` 后端用的：离线用例按查询串取预置回答，
    #: 测试因此**不用碰网络**（生产后端忽略这个参数）。
    reply = client.chat_json(SYSTEM, "查询串：%s\n\n案例：\n%s" % (query, listing),
                             0.0, 0, 2048, key=query)
    out: Dict[str, Dict[str, Any]] = {}
    for row in reply.get("scores") or []:
        if isinstance(row, dict) and row.get("case_id") is not None:
            out[str(row["case_id"])] = row
    return out


def _score_one(index, query: str, clients: Sequence[tuple],
               top_k: int) -> List[Dict[str, Any]]:
    """一条查询的打分行（逐镜）。失败侧在 `scores` 里留 ``None``，不写成 1 分。"""
    rows: List[Dict[str, Any]] = []
    cases = index.retrieve(query, top_k=top_k)
    if not cases:
        return rows
    verdicts: Dict[str, Dict[str, Any]] = {}
    for name, client in clients:
        try:
            verdicts[name] = judge(client, query, cases)
        except Exception as exc:  # noqa: BLE001 — 单条失败不吞掉整批
            verdicts[name] = {"__error__": f"{type(exc).__name__}: {exc}"[:120]}
    for case in cases:
        scores = [verdicts.get(name, {}).get(str(case.case_id), {}).get("score")
                  for name, _client in clients]
        numbers = [float(s) for s in scores if isinstance(s, (int, float))]
        if not numbers:
            continue
        rows.append({
            "case_id": str(case.case_id), "query": query,
            "zh": str(getattr(index, "search_zh", {}).get(str(case.case_id), "")),
            "excerpt": str(getattr(case, "excerpt", "") or "")[:200],
            "scores": scores,
            "score": sum(numbers) / len(numbers),
            "reviewed_by": "llm-panel",
            #: `quality.e1_evidence_is_stale` 要求每条自带**这一份**索引的指纹。
            "cases_fingerprint": str(getattr(index, "fingerprint", "") or ""),
            #: **案例集合**的摘要（2026-10-05 会诊 D1）。`cases_fingerprint` 是
            #: **语料**指纹：只换案例集合（`--max-cases`/闸门/线索）它一个字都不变，
            #: 于是"上一代索引上的打分"会被当成现行证据（实测：案例 810→1097 时
            #: `cases_digest` 由 `e1148200…` 变 `227869414e0e014b…`，而
            #: `manifest.fingerprint` 仍是 `69791dbacd…`，E1 照报旧读数的 0.0885）。
            #: 这枚摘要只有"案例集合"能改，所以它才是代际的真钥匙。
            "cases_digest": str(getattr(index, "cases_digest", "") or ""),
            #: 这次检索走的是哪条路（`hybrid` = 产品现行的 BM25；`lexical` = 零依赖适配器）。
            #: 判分必须能自证"测的是哪条路"，否则两条路的读数会混在一份证据里。
            "retrieval_path": str(getattr(index, "path_label", "") or ""),
            "panel": [name for name, _client in clients],
            "prompt_sha256": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest(),
        })
    return rows


def score_queries(index, queries: Sequence[str], clients: Sequence[tuple], *,
                  top_k: int = 3, workers: int = DEFAULT_WORKERS
                  ) -> List[Dict[str, Any]]:
    """跑一遍打分。**纯函数式**：索引与客户端都由调用方注入，因此可离线测。

    `workers` 只改**吞吐**，不改判据、不改产物形状：判分是**逐查询独立**的，
    汇总仍是"查询序 × 该查询的案例序"，所以并发与否得到**同序同内容的行**。
    为什么需要它（2026-10-04 实测）：一次 64 条查询 × 两条模型 = 128 次调用，
    串行跑（其中一条是"始终思考"的 `glm-5.3`）实测要一小时以上——那种通道既没法
    迭代，也没法在换代之后重测。守门见 `tests/test_e1_panel.py` 的
    "串行与并发产出逐行相同"。
    """
    if int(workers) > 1 and len(queries) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=int(workers)) as pool:
            batches = list(pool.map(
                lambda query: _score_one(index, query, clients, top_k), queries))
        return [row for batch in batches for row in batch]
    return [row for query in queries
            for row in _score_one(index, query, clients, top_k)]


def summarise(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    good = [row for row in rows if float(row["score"]) >= RELEVANT]
    return {"scored": len(rows), "relevant": len(good),
            "value": round(len(good) / len(rows), 4) if rows else None,
            "line": 0.70}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge-e1-panel")
    parser.add_argument("--project", default="",
                        help="真实运行的 project.bdproj（逐镜散文查询的来源）")
    parser.add_argument("--queries", default="", help="或直接给一行一条查询的文本文件")
    parser.add_argument("--cases-dir", default="knowledge")
    parser.add_argument("--out", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--models", default=",".join(DEFAULT_PANEL))
    parser.add_argument("--scripted", default="",
                        help="离线桩（`llm` 的 scripted 后端）；给了就完全不碰网络")
    parser.add_argument("--limit", type=int, default=0, help="0 = 全部")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="并发判分的查询条数（只改吞吐，不改判据与产物形状）")
    parser.add_argument("--adapter", default="none",
                        choices=("none", "lexical", "lightrag"),
                        help="检索臂：none=产品现行 hybrid；lexical=零依赖适配器；"
                             "lightrag=sidecar 上的真索引（需要先起服务）")
    parser.add_argument("--lightrag-url", default="",
                        help="lightrag 臂的 sidecar 地址（默认走适配器的环境变量/默认值）")
    parser.add_argument("--lightrag-fingerprint", default="",
                        help="lightrag 臂要求的索引指纹（给了就 fail closed）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    if bool(args.project) == bool(args.queries):
        print(json.dumps({"error": "必须**恰好**给一个：--project 或 --queries"},
                         ensure_ascii=False))
        return 2
    queries = (queries_from_project(ROOT / args.project) if args.project
               else queries_from_lines(ROOT / args.queries))
    if args.limit:
        queries = queries[:args.limit]
    if not queries:
        print(json.dumps({"error": "一条查询都没有：分母为 0，不许当成通过"},
                         ensure_ascii=False))
        return 2

    if args.adapter == "lexical":
        from block_director.knowledge.lexical_adapter import make_lexical_adapter

        index = load_index(ROOT / args.cases_dir, backend="lightrag",
                           adapter=make_lexical_adapter(ROOT / args.cases_dir))
        index.path_label = "lexical"          # type: ignore[attr-defined]
    elif args.adapter == "lightrag":
        #: 第三条臂（D8 的判定对象）：走 sidecar 上的**真** LightRAG 索引。
        #: `expected_fingerprint` 给了就 fail closed——不匹配连查都不查。
        from block_director.knowledge.lightrag_adapter import make_lightrag_adapter

        index = load_index(
            ROOT / args.cases_dir, backend="lightrag",
            adapter=make_lightrag_adapter(base_url=args.lightrag_url,
                                          expected_fingerprint=args.lightrag_fingerprint))
        index.path_label = "lightrag"         # type: ignore[attr-defined]
    else:
        index = load_index(ROOT / args.cases_dir, backend="hybrid")
        index.path_label = "hybrid"           # type: ignore[attr-defined]
    #: 把**案例集合摘要**挂到索引上，供每条打分自带（`e1_evidence_is_stale` 用它判代际）。
    #: `load_index` 自己不记它（那是案例层的事），而这里正是"这份索引被拿去打分"的现场，
    #: 所以在这一处取一次、跟着行落盘。
    from block_director.knowledge import cases as _cases

    index.cases_digest = _cases.cases_digest(
        _cases.case_paths(ROOT / args.cases_dir))       # type: ignore[attr-defined]
    names = [item.strip() for item in str(args.models).split(",") if item.strip()]
    families = list(DEFAULT_FAMILIES[:len(names)]) or ["scripted"]
    if len(set(families[:len(names)])) < 2 and not args.scripted:
        print(json.dumps({"error": "面板必须换族（两个不同的 family）"},
                         ensure_ascii=False))
        return 2
    clients = []
    for position, name in enumerate(names):
        if args.scripted:
            client = llm.make_client("scripted", name, args.scripted)
        else:
            client = llm.make_client(families[position], name)
        clients.append((name, client))

    rows = score_queries(index, queries, clients, top_k=args.top_k,
                         workers=args.workers)
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                               for row in rows), encoding="utf-8", newline="\n")
    summary = {"out": str(out_path), "queries": len(queries),
               "cases_fingerprint": str(getattr(index, "fingerprint", "") or ""),
               **summarise(rows)}
    print(json.dumps(summary, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if rows else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
