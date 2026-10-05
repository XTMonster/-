"""P9①：三路由 × N 次重复的**成对读数**（计划里 `e1_report.py` 那一步）。

为什么必须有它（而不是各跑一次再由人肉对拍）
==========================================
计划 v4 的 P9① 要的产物是 `work/e1_v4pop_ab.json`：**三条路由 × N 次读数 ＋ 成对差值
＋ inconclusive 标记**。判分本身是随机的（两位 LLM 评委的 1–5 分取均值 ≥ 4.0），
实测**同臂两次重复的极差** hybrid 0.0208／lexical 0.0365（见
`docs/evidence/20261006-e1-baselines/README.md`）——不把"噪声带以下算 inconclusive"
写进产物，任何 0.01 的差都会被读成"某条路由更好"。

判读纪律**不在这里重写**
========================
噪声带与成对判词走 `e1_baseline_summary.paired_report`（同一份实现、同一套反面用例）；
单次读数走 `e1_panel.py`（**冻结仪器**，本工具只按它的 CLI 调它，不改它一行）。
本工具只做编排与留痕：

* 编排出 `三轮 × N 次` 的运行计划（纯函数，可离线测）；
* 每次跑的逐行录档落 `reviews.<route>.rep<N>.jsonl`（默认 `<out>.reviews/`）；
* 每条读数自带**评委覆盖**（两位评委都回了分的行数）——`judge_coverage.complete=false`
  的那一轮**不是有效轮**（一侧缺席永远不算同意），这条读出来才算数；
* 附 `provenance`：冻结查询集的摘要、案例层目录、lightrag 索引指纹（若走那条路）。

lightrag 路由的**代际**从哪来
============================
`--lightrag-fingerprint` 没给时，从 `<index-dir>/lightrag/INDEX_MANIFEST.json` 现读
（计划 v4 的布局：影子**层目录**下挂 `lightrag/`）。读不到就**具名报错**，
不许"没有指纹也照查"——那是 ADR-0014 的陈旧化陷阱。

用法（与计划 P9 的验收命令逐字一致；`<影子层>` 就是当时的影子案例目录）::

    python tools/knowledge/e1_report.py --index-dir <影子层> \\
        --heldout <影子层>/eval/heldout_v4.jsonl \\
        --routes lexical,hybrid,lightrag --runs 2 --out work/e1_v4pop_ab.json

**为什么这里要写占位符而不是字面路径**（§3.3 的 P10 门可达性）：`tools/` 与
`block_director/` 下的代码不得硬编码影子目录的字面量——指针切换之后那个目录就
不存在了，而 `git grep` 的门要在切换前就是 0。路径一律由 CLI 给（`--index-dir`
因此没有默认值：**必须**点名量的是哪一代）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.utils.console import force_utf8_streams  # noqa: E402
from tools.knowledge import e1_baseline_summary as ebs  # noqa: E402
from tools.knowledge import e1_panel  # noqa: E402

#: 路由名 → `e1_panel --adapter` 的取值。`hybrid` 是**产品现行的 BM25**（`none`），
#: 名字不同是因为 CLI 说的是"用哪个适配器"，而台账说的是"哪条检索路"。
ROUTE_ADAPTERS: Dict[str, str] = {"hybrid": "none", "lexical": "lexical",
                                  "lightrag": "lightrag"}
#: 走 sidecar 的路由（需要指纹；见 `lightrag_fingerprint_from`）。
SIDECAR_ROUTES = ("lightrag",)
LIGHTRAG_MANIFEST = pathlib.Path("lightrag") / "INDEX_MANIFEST.json"


class InputError(RuntimeError):
    """输入不齐 ⇒ 停。**不拿一份残缺的对照出数。**"""


def parse_routes(text: str) -> List[str]:
    """`"lexical,hybrid,lightrag"` → 有序去重的路由名；不认识的**当场报错**。"""
    out: List[str] = []
    for part in str(text or "").split(","):
        name = part.strip()
        if not name:
            continue
        if name not in ROUTE_ADAPTERS:
            raise InputError("未知检索路由 %r（只认 %s）"
                             % (name, sorted(ROUTE_ADAPTERS)))
        if name not in out:
            out.append(name)
    if not out:
        raise InputError("一条路由都没给")
    return out


def plan_runs(routes: Sequence[str], runs: int) -> List[Tuple[str, int]]:
    """运行计划：`[(route, rep), ...]`，按**路由外层、重复内层**。纯函数。"""
    count = int(runs)
    if count < 1:
        raise InputError("--runs 至少是 1（0 次重复等于没读数）")
    return [(route, rep) for route in routes for rep in range(1, count + 1)]


def rep_name(route: str, rep: int) -> str:
    """一条读数的文件名——与 `paired_report` 认的名字**逐字一致**。"""
    return "reviews.%s.rep%d.jsonl" % (route, int(rep))


def reviews_dir_for(out_path: pathlib.Path) -> pathlib.Path:
    """逐行录档的落点：`<out>.reviews/`（与产物 JSON 放一起，便于一起引用）。"""
    return pathlib.Path(str(out_path) + ".reviews")


def lightrag_fingerprint_from(index_dir: pathlib.Path) -> str:
    """从 `<index-dir>/lightrag/INDEX_MANIFEST.json` 现读指纹；没有就返回空串。"""
    path = pathlib.Path(index_dir) / LIGHTRAG_MANIFEST
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(payload.get("fingerprint") or "") if isinstance(payload, dict) else ""


def panel_argv(route: str, *, heldout: pathlib.Path, cases_dir: pathlib.Path,
               out_path: pathlib.Path, top_k: int, workers: int,
               lightrag_url: str = "", lightrag_fingerprint: str = "") -> List[str]:
    """一条读数 → `e1_panel` 的 argv（**冻结仪器的 CLI 就是这条缝**）。纯函数。"""
    adapter = ROUTE_ADAPTERS[route]
    argv = ["--queries", str(heldout), "--cases-dir", str(cases_dir),
            "--out", str(out_path), "--top-k", str(int(top_k)),
            "--workers", str(int(workers)), "--adapter", adapter]
    if route in SIDECAR_ROUTES:
        if lightrag_url:
            argv += ["--lightrag-url", str(lightrag_url)]
        if not lightrag_fingerprint:
            raise InputError("lightrag 路由缺索引指纹（`--lightrag-fingerprint` 或 "
                             "`<index-dir>/lightrag/INDEX_MANIFEST.json`）："
                             "没有它就没法保证量的是哪一代索引")
        argv += ["--lightrag-fingerprint", str(lightrag_fingerprint)]
    return argv


def judge_coverage(path: pathlib.Path) -> Dict[str, object]:
    """这一轮里"两位评委都回了分"的行数。**一侧缺席不是同意。**"""
    rows = ebs.read_rows(path)
    panel = rows[0].get("panel") or ["?"]
    two = 0
    single = 0
    for row in rows:
        scores = list(row.get("scores") or [])
        answered = [float(s) for s in scores if isinstance(s, (int, float))]
        if len(answered) >= len(panel):
            two += 1
        elif answered:
            single += 1
    return {"rows": len(rows), "two_judge_rows": two, "single_judge_rows": single,
            "panel_size": len(panel), "complete": single == 0}


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def build_report(reviews_dir: pathlib.Path, routes: Sequence[str], runs: int,
                 *, provenance: Optional[Dict] = None) -> Dict:
    """把逐行录档读成计划 P9① 要的那份 JSON（判词全走 `paired_report`）。"""
    report = ebs.paired_report(pathlib.Path(reviews_dir), arms=list(routes),
                               reps=list(range(1, int(runs) + 1)))
    #: 键是**文件名**（每条读数一格）——按路由名做键的话，同一路由的第 2 轮会把
    #: 第 1 轮覆盖掉，覆盖检查就只剩最后一轮（这是本条用例当场抓到的实现缺陷）。
    coverage = {rep_name(route, rep):
                judge_coverage(pathlib.Path(reviews_dir) / rep_name(route, rep))
                for route, rep in plan_runs(routes, runs)}
    report["judge_coverage"] = coverage
    #: **有效轮**：两位评委都回了分的行必须覆盖**每一轮**。有一条不齐就说明这一轮
    #: 有"一侧缺席"，按 V1 的纪律它不算有效轮——据它下的判词要打折扣。
    report["all_rounds_complete"] = all(entry["complete"] for entry in coverage.values())
    #: **一次重复算不出噪声带**：`noise_band` 由"同臂极差"推出来，只有 1 轮时它恒为 0，
    #: 于是任何非零 Δ 都会被机械地判成 `separated`——那条判词**恒真、无信息量**。
    #: 这不是 `paired_report` 的缺陷（它只报它算得出的东西），而是本工具必须写明的
    #: 前提：要"分开两条路由"，至少 2 次重复。见 `docs/evidence/20261006-e1-baselines`。
    report["repetition_sufficient"] = int(runs) >= 2
    if not report["repetition_sufficient"]:
        report["separation_verdicts_valid"] = False
        report["note"] = ("只有 1 次重复 ⇒ 噪声带恒为 0、`separated` 恒真："
                          "本条读数只能用于**对照同一批查询上的量级**，"
                          "不能据它判「哪条路由更好」。")
    else:
        report["separation_verdicts_valid"] = True
    report["provenance"] = dict(provenance or {})
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="knowledge-e1-report")
    #: 没有默认值：**必须**点名量的是哪一代案例层（见模块 docstring 的 P10 门理由）。
    parser.add_argument("--index-dir", required=True, help="案例层目录（当时的影子层）")
    parser.add_argument("--heldout", required=True,
                        help="冻结查询集（一行一条；`freeze_eval.py` 的产物）")
    parser.add_argument("--routes", default="lexical,hybrid",
                        help="逗号分隔：lexical/hybrid/lightrag")
    parser.add_argument("--runs", type=int, default=2, help="每条路由跑几次")
    parser.add_argument("--out", required=True, help="产物 JSON（逐行录档落 <out>.reviews/）")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--lightrag-url", default="",
                        help="sidecar 地址（默认走适配器的 127.0.0.1:8765）")
    parser.add_argument("--lightrag-fingerprint", default="",
                        help="留空则从 <index-dir>/lightrag/INDEX_MANIFEST.json 现读")
    parser.add_argument("--reuse", action="store_true",
                        help="已有逐行录档就直接判读（不重跑判分）")
    parser.add_argument("--reviews-dir", default="",
                        help="逐行录档目录（默认 <out>.reviews/；给 `--reuse` 时常用）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    routes = parse_routes(args.routes)
    heldout = pathlib.Path(args.heldout)
    cases_dir = pathlib.Path(args.index_dir)
    if not heldout.is_file():
        raise InputError("冻结查询集不存在：%s" % heldout)
    if not cases_dir.is_dir():
        raise InputError("案例层目录不存在：%s" % cases_dir)

    fingerprint = args.lightrag_fingerprint
    if "lightrag" in routes and not fingerprint:
        fingerprint = lightrag_fingerprint_from(cases_dir)

    out_path = pathlib.Path(args.out)
    reviews_dir = (pathlib.Path(args.reviews_dir) if args.reviews_dir
                   else reviews_dir_for(out_path))
    reviews_dir.mkdir(parents=True, exist_ok=True)
    for route, rep in plan_runs(routes, args.runs):
        target = reviews_dir / rep_name(route, rep)
        if args.reuse and target.is_file():
            print(json.dumps({"skip": target.name, "reason": "reuse"}, ensure_ascii=False))
            continue
        argv_next = panel_argv(route, heldout=heldout, cases_dir=cases_dir,
                               out_path=target, top_k=args.top_k, workers=args.workers,
                               lightrag_url=args.lightrag_url,
                               lightrag_fingerprint=fingerprint)
        print(json.dumps({"run": target.name, "argv": argv_next}, ensure_ascii=False))
        code = e1_panel.main(argv_next)
        if code != 0:
            raise InputError("%s 没跑出读数（e1_panel 退出码 %s）" % (route, code))

    report = build_report(reviews_dir, routes, args.runs, provenance={
        "generated_by": "tools/knowledge/e1_report.py",
        "cases_dir": str(cases_dir),
        "heldout": str(heldout),
        "heldout_sha256": sha256_file(heldout),
        "lightrag_fingerprint": fingerprint,
        "reviews_dir": str(reviews_dir),
        "review_files": {rep_name(route, rep): sha256_file(reviews_dir / rep_name(route, rep))
                         for route, rep in plan_runs(routes, args.runs)},
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"out": str(out_path), "routes": routes, "runs": args.runs,
                      "noise_band": report["noise_band"],
                      "all_rounds_complete": report["all_rounds_complete"],
                      "pairs": report["pairs"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
