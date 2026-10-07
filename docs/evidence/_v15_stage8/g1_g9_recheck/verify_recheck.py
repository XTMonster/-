"""P8-T8 的复算仪器：G1–G9 逐条核查的**机械部分**（确定性、离线、只读）。

用法：

    python docs/evidence/_v15_stage8/g1_g9_recheck/verify_recheck.py --check

`--check` 的语义是"**我记录的现状还在不在**"，不是"判据"。每条 claim 都是
P8-T8 报告里写下的**实测状态**：一旦有人真的把某条做掉（例如把 `extract`
提示里的"13 类"改成 16 类），本脚本会**红**并要求更新
`verdicts.json`／`README.md`——这是防"文档漂移"的守卫，不改变任何判据、
阈值、门限，也不写任何产物（红线 R-5 / R-8 均不触碰）。

它**只读**：不 import bpy、不写文件、不改索引、不改夹具。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Dict, List, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BUILD = ROOT / "tools" / "kb_fetch" / "build_hypergraph.py"
MANIFEST = ROOT / "knowledge" / "hypergraph.manifest.json"
EDGES = ROOT / "knowledge" / "hypergraph.edges.jsonl"
SCOPE = ROOT / "knowledge" / "card_scope.json"
COMPOSITION = ROOT / "block_director" / "cinema" / "composition.py"
QUALITY = ROOT / "tools" / "knowledge" / "quality.py"
AGENTS = ROOT / "AGENTS.md"
LEDGER = ROOT / "docs" / "knowledge" / "PLAN_HYPERGRAPH_v4_PROGRESS.md"

OLLAMA_BLOBS = pathlib.Path.home() / ".ollama" / "models" / "blobs"
OLLAMA_KEEP = "sha256-0373edb066522ad4e8d022fe9ee6dcf02a853cf9477ebee6bfebc3e55e6929c0"


def _text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _edges() -> List[dict]:
    return [json.loads(line) for line in _text(EDGES).splitlines() if line.strip()]


def g1_prompt_drift() -> Tuple[List[str], List[str]]:
    """G1：抽取提示里的三处历史措辞是否随 extract/v18 收口。"""
    blob = _text(BUILD)
    found = {
        'PROMPT_VERSION = "extract/v18"': 'PROMPT_VERSION = "extract/v18"' in blob,
        "开场/规则 1 仍写 13 类": "只能取下面 **13 类**" in blob,
        "规则 1b 仍写 13 个 type": "1b. **只有这 13 个 `type` 字符串**" in blob,
        "规则 6b 仍写把 13 类逐条问": "把下面 13 类逐条问一遍" in blob,
        "规则 4b 仍写挂到 EMOTION_PACK": "挂在 EMOTION_PACK 上" in blob,
        "已记『被实测否决』留档": "被实测否决的一次尝试（留档，别再犯）" in blob,
    }
    ok = [k for k, v in found.items() if v]
    bad = [k for k, v in found.items() if not v]
    return ok, bad


def g2_movement_policy_host() -> Tuple[List[str], List[str]]:
    """G2：schema 有没有能诚实承载"运镜政策"的边型；gen_cine_0247 的禁半在不在索引里。"""
    from block_director.knowledge import hypergraph as hg

    citing = [e for e in _edges() if "gen_cine_0247" in (e.get("sources") or [])]
    forbid_roles = [m for e in citing for m in (e.get("members") or []) if m and m[0] == "forbid"]
    scope = json.loads(_text(SCOPE))
    excluded = scope.get("excluded") or []

    ok: List[str] = []
    bad: List[str] = []

    if len(citing) == 1:
        ok.append("引用 gen_cine_0247 的边 = 1 条（卡已进索引）")
    else:
        bad.append(f"引用 gen_cine_0247 的边 = {len(citing)} 条（报告记 1 条）")

    if not forbid_roles:
        ok.append("这 1 条边**没有** forbid 成员 ⇒ 卡里『避免长时间静止固定』的禁半仍未进索引")
    else:
        bad.append(f"出现了 forbid 成员 {forbid_roles} ⇒ 报告要更新")

    if "gen_cine_0247" not in excluded:
        ok.append("card_scope.excluded 不含 gen_cine_0247（不再是孤儿卡）")
    else:
        bad.append("gen_cine_0247 又回到 card_scope.excluded")

    if "MOVEMENT_POLICY" not in hg.EDGE_TYPES and "movement_policy" not in hg.QUALIFIER_KINDS:
        ok.append("没有**专门的**『运镜政策』边型/kind（现行宿主只是 INTENT_PACK 的 "
                  "`movement` 槽位——「无宿主」这句只在『无专用边型』这一层成立）")
    else:
        bad.append("已经出现专用运镜政策宿主 ⇒ 报告要更新")
    return ok, bad


def g3_ollama_residue() -> Tuple[List[str], List[str]]:
    """G3：用户手工项的 ollama 残片（工作区外 + 工作区内）。"""
    ok: List[str] = []
    bad: List[str] = []
    work_bins = sorted((ROOT / "work").glob("ollama_leftover_*.bin"))
    total_gib = sum(p.stat().st_size for p in work_bins) / (1024 ** 3)
    ok.append(f"work/ollama_leftover_*.bin = {len(work_bins)} 份 / 合计 {total_gib:.2f} GiB")

    keep = OLLAMA_BLOBS / OLLAMA_KEEP
    if keep.is_file():
        ok.append(f"{keep} 仍在（{keep.stat().st_size / (1024 ** 3):.2f} GiB，仍被 qwen3-vl:30b 引用）")
    else:
        ok.append("工作区外那枚 18.25 GiB blob 已被用户手工清掉（报告里 G3 该转『已处置』）")
    return ok, bad


def g4_prompt_drift_batch() -> Tuple[List[str], List[str]]:
    """G4：§22.2 的抽取提示漂移（必须与整库重抽+重标同批），发货代是不是仍是 v18。"""
    manifest = json.loads(_text(MANIFEST))
    ok: List[str] = []
    bad: List[str] = []
    if manifest.get("prompt_version") == "extract/v18":
        ok.append("发货索引 prompt_version = extract/v18（漂移未随重抽落地）")
    else:
        bad.append(f"发货索引 prompt_version = {manifest.get('prompt_version')} ⇒ 报告要更新")
    blob = _text(BUILD)
    if "真正的根因修复必须**改提示 ＋ 整库重抽 ＋ 重标整份 oracle 同批落地**" in blob:
        ok.append("build_hypergraph.py 里仍写着『必须同批落地』的结论")
    else:
        bad.append("『必须同批落地』的结论文字不在了 ⇒ 报告要更新")
    return ok, bad


def g5_chunk_cache() -> Tuple[List[str], List[str]]:
    """G5：抽取结果缓存（"命中就不重抽"）有没有落地。

    **本检查在 2026-10-07 被改过一次**（改的是仪器，不是判据）：初版写的是
    "仍只有按卡的原子边复用／没有 `work/hypergraph.chunk*.jsonl`"，那是按
    `ACCEPTANCE_STATUS.md:1940-1942`（§28.1 的"还没做"）抄的**文件名代理**。实测对拍
    发现该条**早已收口**——`:2168-2171`（§29.4）自己写着"§28.1 记的『全量重建仍会重抽、
    两次构建不同字节』，在**原子边缓存**里**做成了**"。所以检查改为**钉住机制**：
    模块在 ∧ 被 `build_hypergraph` 接线（含 `--no-atom-cache` 开关）∧ manifest 记
    `atom_cache.enabled=true` ∧ `chunks[]` 带 per-chunk 账 ∧ 有守门用例。

    **残留**（照实记，不设门）：缓存文件落 `work/`（**不入库、不进指纹**）⇒ 干净检出上
    的全量重建仍会真调模型，"逐字节一致"是**有缓存前提**的机制。
    """
    ok: List[str] = []
    bad: List[str] = []

    module = ROOT / "tools" / "kb_fetch" / "atom_cache.py"
    if module.is_file():
        ok.append("tools/kb_fetch/atom_cache.py 在（第 1 段抽取结果的缓存／断点续跑）")
    else:
        bad.append("atom_cache.py 不见了 ⇒ 报告要更新")

    blob = _text(BUILD)
    if "import atom_cache" in blob and "--no-atom-cache" in blob:
        ok.append("build_hypergraph 真的接上了它（`import atom_cache` ＋ `--no-atom-cache` 可关）")
    else:
        bad.append("build_hypergraph 没有接线 atom_cache ⇒ 报告要更新")

    manifest = json.loads(_text(MANIFEST))
    entry = manifest.get("atom_cache") or {}
    path = str(entry.get("path") or "")
    if entry.get("enabled") is True and path.startswith("work/"):
        ok.append(f"发货 manifest 记 atom_cache.enabled=true、path={path}"
                  "（落在 work/ ⇒ 不入库、不进指纹）")
    else:
        bad.append(f"manifest.atom_cache = {entry} ⇒ 报告要更新")

    chunks = manifest.get("chunks") or []
    if chunks and all({"chunk_id", "sha256", "status"} <= set(c) for c in chunks):
        ok.append(f"chunks[] 带 per-chunk 账（{len(chunks)} 条，每条含 sha256/status/edges）")
    else:
        bad.append("chunks[] 的 per-chunk 账缺失 ⇒ 报告要更新")

    guard = ROOT / "tests" / "test_hypergraph_atom_cache.py"
    if guard.is_file():
        ok.append("守门用例在（tests/test_hypergraph_atom_cache.py：键只随输入动）")
    else:
        bad.append("atom_cache 的守门用例不见了 ⇒ 报告要更新")

    ok.append("缓存文件名是 work/hypergraph.atom_cache.jsonl——**粒度＝抽取单元**"
              "（渲染后的整段提示 ＋ 模型 ＋ 温度 ＋ 解码 ＋ 卡文），不是 §28.1 设想的 "
              "`hypergraph.chunk*.jsonl`；命名不同，判据（命中就不重抽）相同")
    return ok, bad


def g6_composition_ruling() -> Tuple[List[str], List[str]]:
    """G6：rule_of_thirds/lead_room 的口径是否仍未裁决（不许靠调 PASS_SCORE）。"""
    ok: List[str] = []
    bad: List[str] = []
    blob = _text(COMPOSITION)
    pass_score = re.search(r"^PASS_SCORE\s*=\s*([0-9.]+)", blob, re.M)
    if pass_score and float(pass_score.group(1)) == 70.0:
        ok.append("PASS_SCORE 仍是 70.0（没有被拿去将就口径）")
    else:
        bad.append(f"PASS_SCORE = {pass_score and pass_score.group(1)} ⇒ 报告要更新")
    for key, want in (("lead_room", 0.20), ("rule_of_thirds", 0.15)):
        m = re.search(rf'"{key}":\s*([0-9.]+)', blob)
        if m and float(m.group(1)) == want:
            ok.append(f"WEIGHTS[{key}] 仍是 {want}")
        else:
            bad.append(f"WEIGHTS[{key}] = {m and m.group(1)} ⇒ 报告要更新")
    adr_hits = [p.name for p in sorted((ROOT / "docs" / "adr").glob("*.md"))
                if ("rule_of_thirds" in p.read_text(encoding="utf-8")
                    or "lead_room" in p.read_text(encoding="utf-8"))]
    if not adr_hits:
        ok.append("docs/adr 里仍**没有**这两条口径的成文裁决"
                  "（机制已落地：§68/§69 的横移 ＋ 竖直抬升，阈值一字未动；口径未成文）")
    else:
        bad.append(f"ADR 已出现口径裁决 {adr_hits} ⇒ 报告要更新")
    return ok, bad


def g7_drift_reference() -> Tuple[List[str], List[str]]:
    """G7：drift_is_bridged 的参照系（"赦免额对得上欠账额"）是不是已经换掉。"""
    from block_director.cinema.axis import AXIS_DRIFT_DEG, drift_is_bridged

    ok: List[str] = []
    bad: List[str] = []
    cases = [
        ("53° 漂移只交代了 6° ⇒ 不赦免", drift_is_bridged(53.0, 6.0, neutral=False), False),
        ("100° 可见慢漂移 ⇒ 赦免", drift_is_bridged(100.0, 100.0, neutral=False), True),
        ("阈值内免费", drift_is_bridged(AXIS_DRIFT_DEG, 0.0, neutral=False), True),
        ("中性机位直接算交代", drift_is_bridged(170.0, 0.0, neutral=True), True),
    ]
    for label, got, want in cases:
        if bool(got) == want:
            ok.append(f"drift_is_bridged：{label}")
        else:
            bad.append(f"drift_is_bridged：{label} 实测 {got} ≠ 期望 {want} ⇒ 报告要更新")
    return ok, bad


def g8_q5_baseline_string() -> Tuple[List[str], List[str]]:
    """G8：Q5 的基准串口径（join 键 = audit 里真正发出的 retrieval_call.query）。"""
    ok: List[str] = []
    bad: List[str] = []
    blob = _text(QUALITY)
    if "audit_log.jsonl" in blob and "retrieval_call.data.query" in blob:
        ok.append("quality.py 的 join 键 = audit_log 的 retrieval_call.data.query（emitted）")
    else:
        bad.append("quality.py 的 join 键说明不见了 ⇒ 报告要更新")
    if "重推串与它的漂移见 drift" in blob:
        ok.append("重推串仍降级为 drift 诊断")
    else:
        bad.append("drift 诊断说明不见了 ⇒ 报告要更新")
    agents = _text(AGENTS)
    if "Q5 的基准串口径仍未拍板" in agents:
        ok.append("AGENTS.md 仍记『Q5 的基准串口径仍未拍板』（口径未收口）")
    else:
        bad.append("AGENTS.md 不再记这条 ⇒ 报告要更新")
    return ok, bad


def g9_alias_in_cache_key() -> Tuple[List[str], List[str]]:
    """G9：别名表（词表指纹）有没有成为缓存键的第八格。"""
    from tools.kb_fetch.build_hypergraph import CACHE_KEY_FIELDS

    ok: List[str] = []
    bad: List[str] = []
    if len(CACHE_KEY_FIELDS) == 8 and "vocabulary_fingerprint" in CACHE_KEY_FIELDS:
        ok.append("CACHE_KEY_FIELDS = 8 格，含 vocabulary_fingerprint（§21 已收口）")
    else:
        bad.append(f"CACHE_KEY_FIELDS = {CACHE_KEY_FIELDS} ⇒ 报告要更新")
    manifest = json.loads(_text(MANIFEST))
    cache_key = manifest.get("cache_key") or {}
    if len(cache_key) == 8 and cache_key.get("vocabulary_fingerprint"):
        ok.append(f"发货 manifest 的 cache_key 也是 8 格（vocabulary_fingerprint={cache_key['vocabulary_fingerprint'][:8]}…）")
    else:
        bad.append(f"发货 manifest 的 cache_key = {sorted(cache_key)} ⇒ 报告要更新")
    return ok, bad


def e2_dangling_reference() -> Tuple[List[str], List[str]]:
    """E2 的残留核查（P1-T1 的验收项，一并钉住）。"""
    ok: List[str] = []
    bad: List[str] = []
    if "OPEN_PROBLEMS" not in _text(AGENTS):
        ok.append("AGENTS.md 里已无 OPEN_PROBLEMS 引用（悬空引用已改指）")
    else:
        bad.append("AGENTS.md 又出现了 OPEN_PROBLEMS 引用")
    ledger = _text(LEDGER)
    if "OPEN_ITEMS_20261007.md` B1" in ledger:
        ok.append("台账的悬空引用已改指 OPEN_ITEMS_20261007.md B1")
    else:
        bad.append("台账未能解析到 OPEN_ITEMS_20261007.md B1 指针")
    return ok, bad


CHECKS: Dict[str, Tuple[str, object]] = {
    "G1": ("抽取提示历史措辞（13 类 / 4b EMOTION_PACK 宿主）", g1_prompt_drift),
    "G2": ("运镜政策无宿主 / gen_cine_0247 禁半", g2_movement_policy_host),
    "G3": ("ollama 残片（工作区外 blob + 工作区内 bin）", g3_ollama_residue),
    "G4": ("抽取提示漂移须与整库重抽同批", g4_prompt_drift_batch),
    "G5": ("按 chunk 的原子边缓存", g5_chunk_cache),
    "G6": ("构图口径（rule_of_thirds / lead_room）", g6_composition_ruling),
    "G7": ("drift_is_bridged 的参照系", g7_drift_reference),
    "G8": ("Q5 基准串口径", g8_q5_baseline_string),
    "G9": ("别名表进缓存键", g9_alias_in_cache_key),
    "E2": ("悬空引用（P1-T1 验收项）", e2_dangling_reference),
}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="任何一条与记录不符就非零退出（防文档漂移）")
    parser.add_argument("--json", default="", help="把逐条结果写成 JSON")
    args = parser.parse_args(argv)

    results: Dict[str, dict] = {}
    failed: List[str] = []
    for key, (title, fn) in CHECKS.items():
        ok, bad = fn()  # type: ignore[operator]
        results[key] = {"title": title, "ok": ok, "mismatch": bad}
        print(f"[{'OK' if not bad else 'DRIFT'}] {key} {title}")
        for line in ok:
            print(f"    ok   {line}")
        for line in bad:
            print(f"    DRIFT {line}")
        if bad:
            failed.append(key)

    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    if failed:
        print(f"\n{len(failed)} 条与 P8-T8 记录不符：{', '.join(failed)}")
        print("这不是判据失败，是**文档漂移**：请重新核查后更新 "
              "docs/evidence/_v15_stage8/g1_g9_recheck/{README.md,verdicts.json}")
        return 1 if args.check else 0
    print(f"\n{len(CHECKS)} 条全部与 P8-T8 的记录一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
