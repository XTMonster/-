"""把**一次**真实模型运行的证据分片出来（audit_log / llm_trace ＋ `run_manifest.json`）。

为什么需要它（§24.1 的教训）：本机的 `audit_log.jsonl` 是**累积**的（2026-10-03
实测 6839 个事件、162 跑），`llm_trace.jsonl` 同样。证据目录里要能回答"这一跑
到底发了什么"，而答案必须**逐字节可复算**——所以分片只做一件事：按 `run_id`
**原样搬运整行**（不重排、不改写、不合并、不补字段），再把 4 个 sha256 钉进
`run_manifest.json`：

* 分片自己（`audit_log.jsonl` / `llm_trace.jsonl`）；
* 这一跑的 `shots.json`（`quality.run_evidence_is_stale` 从它的 `knowledge`
  块读索引代际）；
* 现行的 held-out oracle（`fixtures/knowledge_holdout.jsonl`）；
* 现行索引 manifest（`knowledge/hypergraph.manifest.json` 的 `fingerprint`）。

判据只在**证据齐且同代**时才算数：`--check` 模式就是在复算这四件事，链与用例
都用它，免得"分片跑过一次之后就再也没人对拍"。

用法::

  python tools/extract_run_evidence.py --run-id <id> --out <evidence-dir>
  python tools/extract_run_evidence.py --run-id <id> --out <evidence-dir> --check

`--audit-log` / `--llm-trace` 默认指向应用自己的运行目录
（`<用户文档>/BlockDirector Projects/{runs/audit_log.jsonl,llm_trace.jsonl}`），
也可以显式给路径（那是唯一可移植的写法——机器上的路径不进库）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MANIFEST_NAME = "run_manifest.json"
DEFAULT_AUDIT = Path.home() / "Documents" / "BlockDirector Projects" / "runs" / "audit_log.jsonl"
DEFAULT_TRACE = Path.home() / "Documents" / "BlockDirector Projects" / "runs" / "llm_trace.jsonl"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _portable(path: Path, out_dir: Path) -> str:
    """证据里的路径写成**相对证据目录**的（跨机器可解析），出不去就写绝对路径。"""
    try:
        return Path(path).resolve().relative_to(Path(out_dir).resolve()).as_posix()
    except ValueError:
        return str(path)


def slice_jsonl(path: Path, run_id: str) -> Tuple[List[str], int]:
    """按 `run_id` **原样**挑行（返回 `(行, 该文件里的总行数)`）。

    判据是"这一行里出现了这个 run_id"吗？不是——那样会把碰巧提到它的别跑
    也搬进来。这里按**解析后的 `run_id` 字段**判，解析不了的行不入选
    （但计入总数，好让"这份日志有多脏"看得见）。
    """
    kept: List[str] = []
    total = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and str(payload.get("run_id") or "") == run_id:
            kept.append(line)
    return kept, total


def _write_lines(target: Path, lines: List[str]) -> None:
    target.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _run_span(lines: List[str]) -> Dict[str, Any]:
    """这一跑的时间跨度（**确定性**：取自事件里的 ts，不用"现在几点"）。"""
    stamps = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        stamp = event.get("ts") if isinstance(event, dict) else None
        if isinstance(stamp, (int, float)):
            stamps.append(float(stamp))
    return {"events": len(lines),
            "first_ts": min(stamps) if stamps else None,
            "last_ts": max(stamps) if stamps else None}


def _count_kind(lines: List[str], kind: str) -> int:
    """数某一类事件（解析不了的行不计——它们不是证据）。"""
    total = 0
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and str(event.get("kind") or "") == kind:
            total += 1
    return total


def retrieval_cross_checks(out_dir: Path) -> List[str]:
    """证据内部的**契约对拍**：`shots.json.retrieval_calls` 是否等于审计里的事件数。

    为什么要有这一条（2026-10-03 实测）：`docs/evidence/20261003_real_glm/` 那一跑
    的 `export/shots.json` 顶层写着 `retrieval_calls: 0`，而同一份证据的
    `knowledge.retrieval_calls` 与 `audit_log.jsonl` 都写着 **7**。成因是时间线：
    `tools/run_headless.py` 把 `retrieval_calls=` 传进 `export_project()` 的修复
    **晚于**那一跑（`b661f23` 之后才落盘），所以那份交付件是修复前的产物。
    §3.3 把 `retrieval_calls` 写成契约字段，两个数不一致就是"契约字段在说假话"——
    而 §4.1b 硬规则 2 只允许拿**逐次事件**（audit）当独立计数，所以这里拿它当
    裁判：audit 是唯一真源，shots.json 只能对拍。

    语义：这是**硬失败**还是**警告**？这一份是已知的"修复前产物"（字段 0 而事件
    非 0，且整条链的验收判据都不读它），按证据纪律**如实记账、不静默**，所以记
    `warning` 而不是 `reason`：`--check` 的退出码不变，但 `main` 会把它们打出来，
    并在 JSON 里返回。想让这一跑彻底干净，需要一次**修复后**的真实运行覆盖它——
    那要模型额度，不在本工具的职责里。
    """
    warnings: List[str] = []
    audit_path = Path(out_dir) / "audit_log.jsonl"
    manifest_path = Path(out_dir) / MANIFEST_NAME
    if not audit_path.is_file() or not manifest_path.is_file():
        return warnings
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return warnings
    shots_rel = ((manifest.get("artifacts") or {}).get("shots.json") or {}).get("path")
    if not shots_rel:
        return warnings
    shots_path = Path(out_dir) / str(shots_rel)
    if not shots_path.is_file():
        return warnings
    try:
        shots = json.loads(shots_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return warnings
    if not isinstance(shots, dict):
        return warnings
    recorded = int(shots.get("retrieval_calls") or 0)
    events = _count_kind(
        audit_path.read_text(encoding="utf-8").splitlines(), "retrieval_call")
    if recorded != events:
        warnings.append(
            f"shots.json 顶层 retrieval_calls={recorded}，而审计日志里 "
            f"retrieval_call 事件 {events} 条（§3.3 的契约字段与逐次事件对不上；"
            f"审计是唯一真源）。成因通常是这一跑发生在 "
            f"tools/run_headless.py 把 retrieval_calls 传进 export_project() 之前。")
    return warnings


def extract(*, run_id: str, out_dir: Path, audit_log: Path, llm_trace: Path,
            shots: Optional[Path], knowledge_trace: Optional[Path],
            holdout: Path, index_manifest: Path) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not Path(audit_log).is_file():
        raise FileNotFoundError(f"审计日志不存在：{audit_log}")
    audit_lines, audit_total = slice_jsonl(Path(audit_log), run_id)
    if not audit_lines:
        raise ValueError(f"{audit_log} 里没有 run_id={run_id} 的事件：先核对该跑是否写进了这份日志")
    _write_lines(out_dir / "audit_log.jsonl", audit_lines)

    artifacts: Dict[str, Any] = {
        "audit_log.jsonl": {"sha256": sha256_file(out_dir / "audit_log.jsonl"),
                            "lines": len(audit_lines),
                            "source": str(audit_log),
                            "source_lines": audit_total},
    }
    if Path(llm_trace).is_file():
        trace_lines, trace_total = slice_jsonl(Path(llm_trace), run_id)
        _write_lines(out_dir / "llm_trace.jsonl", trace_lines)
        artifacts["llm_trace.jsonl"] = {
            "sha256": sha256_file(out_dir / "llm_trace.jsonl"),
            "lines": len(trace_lines), "source": str(llm_trace),
            "source_lines": trace_total}
    if knowledge_trace is not None and Path(knowledge_trace).is_file():
        target = out_dir / "knowledge_trace.json"
        target.write_bytes(Path(knowledge_trace).read_bytes())
        artifacts["knowledge_trace.json"] = {
            "sha256": sha256_file(target), "source": str(knowledge_trace)}
    if shots is not None:
        #: `shots.json` 由导出通路自己写（本工具**不重写它**：证据要原样）；
        #: 这里只记它的 sha，让"报告读的那一份"与"库里这一份"能对拍。
        artifacts["shots.json"] = {"path": _portable(Path(shots), out_dir),
                                   "sha256": sha256_file(Path(shots))}

    from block_director.knowledge.cases import manifest_fingerprint as cases_fp
    from block_director.knowledge.hypergraph import (
        manifest_fingerprint as hypergraph_fp,
    )

    manifest = {
        "run_id": run_id,
        "artifacts": artifacts,
        "run_span": _run_span(audit_lines),
        "pins": {
            "holdout": {"path": str(holdout), "sha256": sha256_file(Path(holdout))},
            "index": {"path": str(index_manifest),
                      "fingerprint": hypergraph_fp(Path(index_manifest).parent)},
            "cases": {"fingerprint": cases_fp(ROOT / "knowledge")},
        },
    }
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def check(*, out_dir: Path, holdout: Path, index_manifest: Path,
          with_warnings: bool = False):
    """复算分片与 pins；返回**不能用的理由**（空列表 = 证据齐且同代）。

    ``with_warnings=True`` 时返回 ``(reasons, warnings)``：`warnings` 是**不影响
    同代性**但必须如实记账的契约对拍（当前只有 `retrieval_calls` 一条，见
    :func:`retrieval_cross_checks`）。默认仍只返回 reasons，改动对既有调用点透明。
    """
    out_dir = Path(out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        reasons = [f"缺 {manifest_path}：这份证据没有来源说明"]
        return (reasons, []) if with_warnings else reasons
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reasons: List[str] = []
    for name, item in (manifest.get("artifacts") or {}).items():
        target = out_dir / str(item.get("path") or name)
        if not target.is_file():
            reasons.append(f"缺分片 {name}（{target}）")
            continue
        if item.get("sha256") and sha256_file(target) != item["sha256"]:
            reasons.append(f"{name} 的 sha256 与 manifest 不符：分片被改过或重放过")
    pins = manifest.get("pins") or {}
    pinned_holdout = ((pins.get("holdout") or {}).get("sha256") or "")
    if not pinned_holdout:
        reasons.append("manifest 没钉 held-out 的 sha256")
    elif pinned_holdout != sha256_file(Path(holdout)):
        reasons.append("held-out oracle 已换代：这份运行证据不是当前那一份 oracle 的")
    from block_director.knowledge.hypergraph import (
        manifest_fingerprint as hypergraph_fp,
    )

    pinned_index = ((pins.get("index") or {}).get("fingerprint") or "")
    live_index = hypergraph_fp(Path(index_manifest).parent)
    if not pinned_index or pinned_index != live_index:
        reasons.append(f"索引指纹不符（证据 {pinned_index[:12]}… vs 现行 "
                       f"{live_index[:12]}…）：这份运行不是这一代索引跑的")
    if not with_warnings:
        return reasons
    return reasons, retrieval_cross_checks(out_dir)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="extract-run-evidence")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT))
    parser.add_argument("--llm-trace", default=str(DEFAULT_TRACE))
    parser.add_argument("--knowledge-trace", default="")
    parser.add_argument("--shots", default="")
    parser.add_argument("--holdout", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--index-manifest", default="knowledge/hypergraph.manifest.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    out_dir = Path(args.out)
    holdout = ROOT / args.holdout
    index_manifest = ROOT / args.index_manifest
    if args.check:
        reasons, warnings = check(out_dir=out_dir, holdout=holdout,
                                  index_manifest=index_manifest,
                                  with_warnings=True)
        for reason in reasons:
            print(f"STALE: {reason}")
        for warning in warnings:
            print(f"WARNING: {warning}")
        print(json.dumps({"ok": not reasons, "reasons": reasons,
                          "warnings": warnings},
                         ensure_ascii=False))
        return 0 if not reasons else 1

    manifest = extract(
        run_id=args.run_id, out_dir=out_dir,
        audit_log=Path(args.audit_log), llm_trace=Path(args.llm_trace),
        shots=Path(args.shots) if args.shots else None,
        knowledge_trace=Path(args.knowledge_trace) if args.knowledge_trace else None,
        holdout=holdout, index_manifest=index_manifest)
    print(json.dumps({"ok": True, "out": str(out_dir),
                      "events": manifest["run_span"]["events"],
                      "artifacts": sorted(manifest["artifacts"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
