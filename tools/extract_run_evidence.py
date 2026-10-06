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

#: 换代登记表（`build_third_party_layer.py` 生成）。**每份运行都必须解析到其中一个已登记代**——
#: 这是门⑦ gen1→gen2 那次裁决给的最小跳："断言每份运行解析到**已登记代**、
#: 链头 pin 覆盖旧夹具＋增量层"。
GENERATIONS_NAME = "fixtures/knowledge_holdout.generations.json"
DEFAULT_AUDIT = Path.home() / "Documents" / "BlockDirector Projects" / "runs" / "audit_log.jsonl"
DEFAULT_TRACE = Path.home() / "Documents" / "BlockDirector Projects" / "runs" / "llm_trace.jsonl"


def sha256_file(path: Path) -> str:
    """文件的摘要——**换行归一之后**再算，因此与检出形态无关。

    为什么必须归一（2026-10-04 实测的真缺陷）：本工具用文本模式写分片，
    在 Windows 上写出的是 CRLF；而 `.gitattributes` 明确把 `*.json` / `*.jsonl`
    存成 **LF**（"Store LF in the repo for source and docs, so diffs are clean on
    every platform"）。于是此前那版**裸字节**哈希只在那棵**产它的工作树**上对得上：
    `git worktree add` 或新克隆拿到的 LF 副本一律被判 STALE——
    `tests/test_extract_run_evidence.py` 有 3 条因此在任何新检出上必红，
    也就是"验收链只在产它的那台机器上绿"。归一之后两边算出同一个摘要。

    这不削弱防篡改：任何**内容**改动（多一个字段、改一个值、删一行）
    都会改变摘要；只有纯粹的 CRLF↔LF 表示差异被视作等价——而那本来就不是
    内容。要按裸字节对拍时用 :func:`sha256_raw`。
    """
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def sha256_raw(path: Path) -> str:
    """**裸字节**的 sha256（不做任何归一）。

    只给 :func:`repin` 的安全规则用：判断一条旧 pin 是不是"同一份内容、
    只是换行口径不同"，必须拿它和盘上的**实际字节**比——归一口径比不了。
    """
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
    """落盘成 **LF**——与 `.gitattributes` 的 `*.jsonl text eol=lf` 一致。

    文本模式在 Windows 上会把 `\n` 翻成 CRLF，于是**盘上字节 ≠ 入库字节**：
    `git status` 因为 `autocrlf` 看不见这处差异，但"逐字节可复算"这句话在
    那一瞬间是假的（`sha256_file` 现在按归一摘要算，判据不再受它影响；
    这里把表示本身也统一掉，免得下次再有人拿裸字节对拍时踩同一个坑）。
    """
    target.write_text("".join(line + "\n" for line in lines), encoding="utf-8",
                      newline="\n")


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
            holdout: Path, index_manifest: Path,
            third_party: Optional[Path] = None,
            generations: Optional[Path] = None) -> Dict[str, Any]:
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
    if third_party is not None:
        #: 门⑦ 的第三方层是 gate 的**输入之一**（裁决：pin 它 = pin 这一代）。
        manifest["pins"]["third_party"] = {
            "path": str(third_party), "sha256": sha256_file(Path(third_party))}
    generation, why = resolve_generation(
        manifest["pins"], Path(generations) if generations else ROOT / GENERATIONS_NAME)
    manifest["generation"] = generation
    if generation is None:
        #: 解析不到就**如实记**（不编一个代名）：`check()` 会把它当失败理由报出来。
        manifest["generation_unresolved"] = why
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    return manifest


def resolve_generation(pins: Dict[str, Any],
                       generations: Path) -> Tuple[Optional[str], str]:
    """这份运行 pin 的**输入集合**对应哪一个「已登记代」？（空 = 解析不到，附原因）

    裁决原话（`docs/evidence/20261006-gate7-disambiguation/规格一致性.json`）：
    "**断言每份运行解析到已登记代**、链头 pin 覆盖旧夹具＋增量层"。

    匹配规则：那一代声明的 `inputs` 必须与本清单的 pins **逐项相等、且不多不少**——
    多 pin 了没登记过的输入 ⇒ 解析不到，**不许**"看着像这一代"就算。
    """
    registry = {}
    path = Path(generations)
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        registry = {str(item.get("id")): item
                    for item in (payload.get("generations") or [])}
    observed = {"holdout": str((pins.get("holdout") or {}).get("sha256") or "")}
    third_party_sha = str((pins.get("third_party") or {}).get("sha256") or "")
    if third_party_sha:
        observed["third_party"] = third_party_sha
    for generation_id, item in registry.items():
        if dict(item.get("inputs") or {}) == observed:
            return generation_id, ""
    return None, ("这份运行 pin 的输入集合 %s 不在登记表的任何一代里（登记表：%s）"
                  % (sorted(observed), sorted(registry)))


def repin(*, out_dir: Path, holdout: Path) -> Dict[str, Any]:
    """按当前口径**重签**一份已入库清单的摘要（运行数据一个字节都不动）。

    为什么需要它（2026-10-04 实测）：`sha256_file` 曾经是裸字节哈希，而
    `.gitattributes` 把 `*.json` / `*.jsonl` 存成 LF——Windows 上文本模式写出的
    证据是 CRLF，于是 **pin 只在那棵产它的工作树里对得上**，`git worktree` /
    新克隆一律 STALE（`tests/test_extract_run_evidence.py` 3 条必红）。摘要换成
    "换行归一后再哈希"之后，旧 pin 要按新口径重签一次。

    **安全规则（不许把"换代"洗成"没换代"）**：只有旧 pin 恰好等于该文件**现在的
    裸字节**哈希时，才认定它是"同一份内容、只是换行口径不同"并改写；否则跳过并
    如实记进 `skipped`——那说明内容真的变了，重签会掩盖它。
    索引/案例的**指纹**一律不动（它们不是文件字节哈希，换行归一与它们无关）。
    """
    out_dir = Path(out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"没有 {manifest_path}：先跑一次 --run-id 提出证据")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report: Dict[str, Any] = {"updated": [], "unchanged": [], "skipped": []}

    def _resign(where: str, target: Path, old: str) -> Optional[str]:
        """返回**该写回的新摘要**；`None` = 不动（已正确或内容真变了）。"""
        if not target.is_file():
            report["skipped"].append(f"{where}：分片不在（{target}）")
            return None
        new = sha256_file(target)
        if old == new:
            report["unchanged"].append(where)
            return None
        if old == sha256_raw(target):
            report["updated"].append(f"{where}: {old[:12]}… → {new[:12]}…")
            return new
        report["skipped"].append(
            f"{where}：旧 pin 既不是归一摘要也不是裸字节摘要——"
            f"内容是**真的**变了，不重签（由 --check 如实报 STALE）")
        return None

    for name, item in (manifest.get("artifacts") or {}).items():
        if not item.get("sha256"):
            continue
        resigned = _resign(str(name), out_dir / str(item.get("path") or name),
                           str(item["sha256"]))
        if resigned:
            item["sha256"] = resigned

    pins = manifest.get("pins") or {}
    holdout_pin = pins.get("holdout") or {}
    if holdout_pin.get("sha256"):
        resigned = _resign("pins.holdout", Path(holdout),
                           str(holdout_pin["sha256"]))
        if resigned:
            holdout_pin["sha256"] = resigned
            pins["holdout"] = holdout_pin
            manifest["pins"] = pins

    # 每次 --repin 都写：清单里没有东西要改时，这也是一次幂等的"落盘成 LF"。
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    report["manifest"] = str(manifest_path)
    return report


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
    #: 换代登记：**每份运行都要解析到已登记代**（裁决给的最小跳）。历史运行 pin 的
    #: 只是夹具 ⇒ 落在 gen1；新运行 pin 了夹具＋第三方层 ⇒ 落在 gen2。
    #: 解析不到（例如 pin 了没登记过的输入）就如实报，**不猜**。
    generation, why = resolve_generation(pins, ROOT / GENERATIONS_NAME)
    if generation is None:
        reasons.append("这份运行没有对应的已登记代：" + why)
    if not with_warnings:
        return reasons
    return reasons, retrieval_cross_checks(out_dir)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="extract-run-evidence")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT))
    parser.add_argument("--llm-trace", default=str(DEFAULT_TRACE))
    parser.add_argument("--knowledge-trace", default="")
    parser.add_argument("--shots", default="")
    parser.add_argument("--holdout", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--third-party", default="",
                        help="门⑦ 的第三方代裁层（`fixtures/knowledge_holdout.third_party.jsonl`）。"
                             "给了就进 pins（pin 它 = pin 这一代）")
    parser.add_argument("--generations", default=GENERATIONS_NAME,
                        help="换代登记表（每份运行必须解析到其中一代）")
    parser.add_argument("--index-manifest", default="knowledge/hypergraph.manifest.json")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--repin", action="store_true",
                        help="按当前摘要口径重签已入库清单（只改 sha256，"
                             "不动运行数据；内容真变了的一律跳过）")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    out_dir = Path(args.out)
    holdout = ROOT / args.holdout
    index_manifest = ROOT / args.index_manifest
    if args.repin:
        if args.check:
            print("--repin 与 --check 互斥：先重签、再用 --check 复核")
            return 2
        report = repin(out_dir=out_dir, holdout=holdout)
        for line in report["updated"]:
            print(f"REPINNED: {line}")
        for line in report["skipped"]:
            print(f"SKIPPED: {line}")
        print(json.dumps({"ok": not report["skipped"],
                          "updated": len(report["updated"]),
                          "unchanged": len(report["unchanged"]),
                          "skipped": report["skipped"]},
                         ensure_ascii=False))
        return 0 if not report["skipped"] else 1
    if args.check:
        #: `--check` 只读 `--out` 里的清单，**不需要** `--run-id`（它只用于提炼
        #: 分片）。历史命令一直带着它，这里保持兼容：给了不用，没给也不报错。
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

    if not args.run_id:
        print("--run-id 是提出证据的必填项（或用 --check / --repin）")
        return 2
    manifest = extract(
        run_id=args.run_id, out_dir=out_dir,
        audit_log=Path(args.audit_log), llm_trace=Path(args.llm_trace),
        shots=Path(args.shots) if args.shots else None,
        knowledge_trace=Path(args.knowledge_trace) if args.knowledge_trace else None,
        holdout=holdout, index_manifest=index_manifest,
        third_party=Path(args.third_party) if args.third_party else None,
        generations=ROOT / args.generations)
    print(json.dumps({"ok": True, "out": str(out_dir),
                      "events": manifest["run_span"]["events"],
                      "artifacts": sorted(manifest["artifacts"]),
                      "generation": manifest.get("generation")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
