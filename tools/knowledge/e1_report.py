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
import os
import pathlib
import sys
from datetime import datetime, timezone
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

#: **轮记录文件**（V1）的终态取值——封闭枚举。V2：集外取值数＝0，两码分开计数。
#: `invalid_parse_fault` ＝ 判分通道没产出（e1_panel 非零退出／文件读不出：解析/基础设施故障）；
#: `invalid_empty_intersection` ＝ 文件合法但**零行**（那一轮没有一条查询产出可判分的行——
#: 合法空交集）。两者都在轮记录里各记各的，**没有第二条入账通道**。
ROUND_STATES = ("valid", "invalid_parse_fault", "invalid_empty_intersection")


class InputError(RuntimeError):
    """输入不齐 ⇒ 停。**不拿一份残缺的对照出数。**"""


def parse_routes(text: str) -> List[str]:
    """`"lexical,hybrid,lightrag"` → 有序去重的路由名；不认识的**当场报错**。

    允许 `<路由>+<标签>` 给**同一路由的不同配置**各起一个臂名（D3 的用途：同一条
    `lightrag` 路由，本地嵌入 `lightrag+local` vs 云端嵌入 `lightrag+cloud`）。
    臂名进文件名（`reviews.<臂名>.rep<N>.jsonl`），所以只许用文件系统安全的字符——
    冒号、斜杠、反斜杠一律拒收（Windows 上 `:` 是非法文件名字符，写盘会当场炸）。
    """
    out: List[str] = []
    for part in str(text or "").split(","):
        name = part.strip()
        if not name:
            continue
        adapter = adapter_of(name)
        if adapter not in ROUTE_ADAPTERS:
            raise InputError("未知检索路由 %r（只认 %s）"
                             % (adapter, sorted(ROUTE_ADAPTERS)))
        if any(character in name for character in (":", "/", "\\")):
            raise InputError("臂名不许含冒号或斜杠（要进文件名）：%r" % name)
        if any(character.isspace() for character in name):
            raise InputError("臂名不许含空白（要进文件名与 JSON 键）：%r" % name)
        if not name.split("+", 1)[-1].strip():
            raise InputError("`<路由>+<标签>` 的标签不能为空：%r" % name)
        if name not in out:
            out.append(name)
    if not out:
        raise InputError("一条路由都没给")
    return out


def adapter_of(route: str) -> str:
    """臂名 → `e1_panel --adapter` 的取值（`lightrag+cloud` → `lightrag`）。纯函数。"""
    return str(route).split("+", 1)[0]


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
    adapter = ROUTE_ADAPTERS[adapter_of(route)]
    argv = ["--queries", str(heldout), "--cases-dir", str(cases_dir),
            "--out", str(out_path), "--top-k", str(int(top_k)),
            "--workers", str(int(workers)), "--adapter", adapter]
    if adapter_of(route) in SIDECAR_ROUTES:
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


def _digest_or(path: pathlib.Path, missing: str = "missing") -> str:
    """文件摘要；没有就返回 `missing`（**具名**，不返回空串——空串会被读成"摘要是空的"）。"""
    return sha256_file(path) if pathlib.Path(path).is_file() else missing


def round_record_path(reviews_dir: pathlib.Path, route: str, rep: int) -> pathlib.Path:
    """V1 的轮记录文件：`round.<route>.<n>.json`（与逐行录档同住证据目录）。"""
    return pathlib.Path(reviews_dir) / ("round.%s.%d.json" % (route, int(rep)))


def heldout_seed(heldout: pathlib.Path) -> int:
    """冻结查询集的抽样种子（同目录的 `heldout.manifest.json`）；没有就 0 并如实记。"""
    manifest = pathlib.Path(heldout).parent / "heldout.manifest.json"
    if not manifest.is_file():
        return 0
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    try:
        return int(payload.get("seed") or 0)
    except (TypeError, ValueError):
        return 0


def identity_fields(*, heldout: pathlib.Path, cases_dir: pathlib.Path,
                    panel: Sequence[str]) -> Dict[str, object]:
    """V1 的**身份字段**：同批各轮这些字段必须逐字相同（diff 不一致字段数＝0）。

    五项分别对应 V1 点名的：`seed`（抽样种子）、行清单摘要（`rows_digest`/`rows`）、
    评委配置摘要（`panel`/`panel_digest`）、语料 manifest 摘要、超图 manifest 摘要。
    评委配置摘要里带上**判分提示词的 sha**（`e1_panel.SYSTEM`）——换了提示词就是换了
    评委配置，两轮不能算成对的（读一次冻结仪器里的常量，不改它）。
    """
    prompt_sha = hashlib.sha256(str(e1_panel.SYSTEM).encode("utf-8")).hexdigest()
    return {
        "seed": heldout_seed(heldout),
        "rows": count_queries(heldout),
        "rows_digest": sha256_file(heldout),
        "panel": list(panel),
        "panel_digest": hashlib.sha256(
            ("\n".join(panel) + "|" + prompt_sha).encode("utf-8")).hexdigest(),
        "corpus_manifest_digest": _digest_or(pathlib.Path(cases_dir) / "cases.manifest.json"),
        "hypergraph_manifest_digest": _digest_or(
            pathlib.Path(cases_dir) / "hypergraph.manifest.json"),
    }


def round_state(review_path: pathlib.Path, exit_code: int) -> str:
    """这一轮的**终态**（V2 的两码分开）。纯函数：判据只看产物与退出码。"""
    rows = None
    if pathlib.Path(review_path).is_file():
        try:
            rows = ebs.read_rows(pathlib.Path(review_path))
        except ebs.InputError:
            rows = None
    if rows is None:
        return "invalid_parse_fault"
    if int(exit_code) != 0 and not rows:
        return "invalid_parse_fault"
    return "valid" if rows else "invalid_empty_intersection"


def write_round_record(path: pathlib.Path, *, route: str, rep: int,
                       identity: Dict[str, object], state: str,
                       identity_written_at: str = "") -> Dict:
    """写/更新轮记录（**唯一写入方＝执行器**，V1）。

    判分**之前**先写一次（身份字段就此冻结，带 `identity_written_at` 与空终态），
    判分之后再更新终态（带 `state_written_at`）——于是"身份先冻结、终态后落"两件事
    在产物里各自有时间戳，而不是事后补一份看起来完整的记录。
    """
    if state and state not in ROUND_STATES:
        raise InputError("轮记录的终态不在封闭枚举里：%r（只认 %s）"
                         % (state, list(ROUND_STATES)))
    path = pathlib.Path(path)
    previous: Dict = {}
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {**identity, "route": str(route), "rep": int(rep),
               "terminal_state": str(state),
               "identity_written_at": (identity_written_at
                                       or previous.get("identity_written_at") or now),
               "state_written_at": now if state else "",
               "written_by": "tools/knowledge/e1_report.py"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return payload


def count_queries(path: pathlib.Path) -> int:
    """冻结查询集的条数（一行一条；空行不算）。"""
    return sum(1 for line in pathlib.Path(path).read_text(encoding="utf-8").split("\n")
               if line.strip())


def round_usage(path: pathlib.Path, expected_queries: Optional[int]) -> Dict[str, object]:
    """这一轮**到底是不是这条路由答的**——两种坏法都要看得见。

    1. **降级**：`cases_degrade_reason` 非空 ⇒ `CaseIndex` 已经退回 BM25，行里的
       `retrieval_path` 仍写着请求的臂（2026-10-05 实测：客户端 10 秒超时把 lightrag
       臂打回 BM25，读数量的其实是超时）。**这是报告，不是门**——"看得见的降级要不要
       升格成'该臂无效'"是判据级问题，单列在 `ADJUDICATIONS_v4.md` 的 D11，等用户拍板。
    2. **静默空**：查询有行数少于查询集条数 ⇒ 那些查询一条都没召回（适配器返回空、
       上层也就没有行可记）——分母会因此无声变小。
    """
    rows = ebs.read_rows(path)
    queries = {str(row.get("query") or "") for row in rows}
    degraded = sum(1 for row in rows
                   if str(row.get("cases_degrade_reason") or "").strip())
    missing = (None if expected_queries is None
               else max(0, int(expected_queries) - len(queries)))
    return {"queries_expected": expected_queries,
            "queries_with_rows": len(queries),
            "queries_missing": missing,
            "backends_effective": sorted({str(row.get("cases_backend_effective") or "")
                                          for row in rows}),
            "degraded_rows": degraded,
            "used_the_route": bool(degraded == 0 and (missing in (None, 0)))}


def build_report(reviews_dir: pathlib.Path, routes: Sequence[str], runs: int,
                 *, provenance: Optional[Dict] = None,
                 expected_queries: Optional[int] = None) -> Dict:
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
    report["route_usage"] = {rep_name(route, rep):
                             round_usage(pathlib.Path(reviews_dir) / rep_name(route, rep),
                                         expected_queries)
                             for route, rep in plan_runs(routes, runs)}
    #: **报告**不是**门**：这一条只说明"这一轮是不是这条路由答的"。把它当成
    #: "该臂无效"是判据级的改动，单列 D11（须用户点头），本工具不擅自升级。
    report["all_rounds_used_the_route"] = all(
        entry["used_the_route"] for entry in report["route_usage"].values())
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
    parser.add_argument("--rounds-only", action="store_true",
                        help="只跑轮次（写逐行录档＋轮记录），**不**出报告——"
                             "分次跑不同路由时用（最后再用 `--reuse` 汇总三臂）")
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
    #: 评委配置取**冻结仪器**的默认面板（本工具不另设 `--models`：判据里"两位换族评委"
    #: 是写死的；要换评委就是换仪器，得走重新冻结）。
    panel = list(e1_panel.DEFAULT_PANEL)
    identity = identity_fields(heldout=heldout, cases_dir=cases_dir, panel=panel)
    for route, rep in plan_runs(routes, args.runs):
        target = reviews_dir / rep_name(route, rep)
        record = round_record_path(reviews_dir, route, rep)
        #: `--reuse` 只认**V1 合规**的旧读数（逐行录档 ＋ 轮记录都在）。少了轮记录的
        #: 那是 V1 之前的产物——重跑它，而不是给它补一份事后写出来的身份记录。
        if args.reuse and target.is_file() and record.is_file():
            print(json.dumps({"skip": target.name, "reason": "reuse"}, ensure_ascii=False))
            continue
        #: **先写身份、再判分**（V1）：身份字段在跑之前就冻结，终态之后补。
        write_round_record(record, route=route, rep=rep, identity=identity, state="")
        argv_next = panel_argv(route, heldout=heldout, cases_dir=cases_dir,
                               out_path=target, top_k=args.top_k, workers=args.workers,
                               lightrag_url=args.lightrag_url,
                               lightrag_fingerprint=fingerprint)
        print(json.dumps({"run": target.name, "argv": argv_next}, ensure_ascii=False))
        code = e1_panel.main(argv_next)
        state = round_state(target, code)
        write_round_record(record, route=route, rep=rep, identity=identity, state=state)
        if state != "valid":
            #: 作废轮**照记**（V2：只写进轮记录，没有第二条通道），但喊出来——
            #: 最后 `paired_report` 会因为"有非 valid 轮"整批拒读。
            print(json.dumps({"round_invalid": target.name, "terminal_state": state,
                              "e1_panel_exit": code}, ensure_ascii=False))

    if args.rounds_only:
        #: 分次跑不同路由（例如先把两臂跑完，等 sidecar 起来再跑第三臂），
        #: 最后用 `--reuse` 把所有轮次一起判读——`paired_report` 至少两臂才成立。
        print(json.dumps({"rounds_written": [rep_name(route, rep)
                                             for route, rep in plan_runs(routes, args.runs)],
                          "reviews_dir": str(reviews_dir)}, ensure_ascii=False))
        return 0

    report = build_report(reviews_dir, routes, args.runs, provenance={
        "generated_by": "tools/knowledge/e1_report.py",
        "cases_dir": str(cases_dir),
        "heldout": str(heldout),
        "heldout_sha256": sha256_file(heldout),
        "lightrag_fingerprint": fingerprint,
        #: 这一轮 lightrag 路由用的读超时（产品默认 10 秒对**测量**太短；见
        #: `block_director/knowledge/lightrag_adapter.py:TIMEOUT_ENV` 那段）。
        "lightrag_timeout": os.environ.get("BLOCK_DIRECTOR_LIGHTRAG_TIMEOUT", ""),
        "reviews_dir": str(reviews_dir),
        "review_files": {rep_name(route, rep): sha256_file(reviews_dir / rep_name(route, rep))
                         for route, rep in plan_runs(routes, args.runs)},
    }, expected_queries=count_queries(heldout))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"out": str(out_path), "routes": routes, "runs": args.runs,
                      "noise_band": report["noise_band"],
                      "all_rounds_complete": report["all_rounds_complete"],
                      "all_rounds_used_the_route": report["all_rounds_used_the_route"],
                      "pairs": report["pairs"]}, ensure_ascii=False, indent=2))
    if not report["all_rounds_used_the_route"]:
        #: 只**喊一声**（不拦、不判）：这是 D11 要裁的那件事，本工具不擅自升级。
        print(json.dumps({"warning": "有轮次不是这条路由答的（降级或静默空）",
                          "route_usage": report["route_usage"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
