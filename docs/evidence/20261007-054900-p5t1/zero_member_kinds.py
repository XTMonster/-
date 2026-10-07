"""P5-T1 / FX-6 诊断：5 个零成员 kind ——「有意不用」还是「漏抽」？

执行文档 v1.5 的卡 P5-T1（`执行文档v1.5/EXECUTION_PLAN.md`，阶段 5）＋
清单 B5（`docs/knowledge/OPEN_ITEMS_20261007.md` §二）。
**只诊断，不改任何代码与判据**（红线 R-5）。

判据是**机械的**，三层证据缺一层就不下结论：

1. **schema 声明**：这个 kind 在 `hypergraph.QUALIFIER_KINDS` 里吗？被哪些边类型
   允许、以什么角色？`VALUE_DOMAINS` 给了什么（枚举 / `None`）？
   （`None` 在本仓是**显式的「不设枚举」**，不是「漏项」——见 `hypergraph.py:70`。）
2. **能不能产**：抽取器拿到的**冻结词表**（`knowledge/hypergraph.vocab.json`）里有没有
   这个 kind 的 `kind:取值` 节点？提示词（`tools/kb_fetch/build_hypergraph.py` 的
   `SYSTEM_PROMPT`，横跨 `:374` 起）有没有点名让它填？
   —— 提示规则 2 写死「`node_id` **必须**取自下面词表」，所以**词表为空 ⇒
   结构性不可产**（模型要产就得发明 node_id，那是被明令禁止的）。
3. **产了没**：原子边（`work/hypergraph.atoms.jsonl`）与**原子拒收**
   （`work/hypergraph.atom_rejects.jsonl`）里有没有这个 kind 的成员？
   两层都是 0 ⇒ **不是被校验门拒收，而是抽取器从未产出**。

三层合起来才分得清：

* **漏抽** ＝ 提示点名 ＋ 词表有值 ＋ 原子 0（能产、被要求、却没产）；
* **有意不用/延后** ＝ 词表空 或 提示不点名，且有文档显式说明它是引用/延后项。

跑法（仓库根，纯读）：``python docs/evidence/<run-id>/zero_member_kinds.py``
产物：同目录 ``zero_member_kinds.md``。**逐字节可复现**（同一份索引 ⇒ 同一份报告）；
``--check`` 模式在产物与现算不一致时非零退出（不改任何东西）。
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import pathlib
import sys
from typing import Any, Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402

RUN_ID = "20261007-054900-p5t1"
OUT = pathlib.Path(__file__).resolve().parent / "zero_member_kinds.md"

#: 被诊断的五个 kind（卡 P5-T1 / 清单 B5 逐字点名）。
TARGETS: Tuple[str, ...] = (
    "applies_to_genre", "applies_to_shot_size", "carry_shots",
    "example_shot", "seq_phase",
)

#: 实测快照（2026-10-07，`hg/v2` ＋ `extract/v18` ＋ `gate/v2`）。
#: 这是**钉住**：schema / 词表 / 提示 / 索引任何一处动了，脚本会当场红，
#: 逼人重新分类——而不是让上面那些解释悄悄过期。
EXPECTED: Dict[str, Dict[str, Any]] = {
    "applies_to_genre": {
        "verdict": "漏抽",
        "domain_kind": "enum",
        "vocab_nodes": 3,
        "prompt_lines": [445, 519],
        "index_members": 0,
        "atoms": 0,
        "atom_rejects": 0,
    },
    "applies_to_shot_size": {
        "verdict": "漏抽",
        "domain_kind": "enum",
        "vocab_nodes": 9,
        "prompt_lines": [445, 520],
        "index_members": 0,
        "atoms": 0,
        "atom_rejects": 0,
    },
    "example_shot": {
        "verdict": "有意不用",
        "domain_kind": "none",
        "vocab_nodes": 0,
        "prompt_lines": [],
        "index_members": 0,
        "atoms": 0,
        "atom_rejects": 0,
    },
    "seq_phase": {
        "verdict": "有意延后",
        "domain_kind": "none",
        "vocab_nodes": 0,
        "prompt_lines": [],
        "index_members": 0,
        "atoms": 0,
        "atom_rejects": 0,
    },
    "carry_shots": {
        "verdict": "有意延后",
        "domain_kind": "none",
        "vocab_nodes": 0,
        "prompt_lines": [],
        "index_members": 0,
        "atoms": 0,
        "atom_rejects": 0,
    },
}

#: 「有意不用/延后」一类的**落地证据**（谁说的、写在哪）：报告里逐条引用，
#: 免得「有意」变成一句没有出处的托词。
DESIGN_NOTES: Dict[str, str] = {
    "example_shot": (
        "`改进执行文档v1.4.md:1127`：`example_shot` = 自由文本（**唯一不设枚举**的 "
        "qualifier：它是**参考资料引用**，**不参与判定**；仍必须带 `source_ref`）。"
        "⇒ 它天生不是「条件」，进不了执行闭环；且提示词从不要求它（见本报告 §2）。"),
    "seq_phase": (
        "`block_director/knowledge/hypergraph.py:139` ＋ `:292`：v3/S1a 的"
        "**惰性加键**——键先进闭集（让 schema 指纹换代、让 trace 看得见），"
        "**取值域留给 S2**；`tests/test_qualifier_lazy_keys.py:28` 把「显式延后」钉住"
        "（S2 落地时那条会红，逼着人把词表写进来）。⇒ 零成员是**设计状态**。"),
    "carry_shots": (
        "同 `seq_phase`（`hypergraph.py:139`／`:292`／`:300`，"
        "`tests/test_qualifier_lazy_keys.py:28`）。⇒ 零成员是**设计状态**。"),
}

#: 修复点（只对「漏抽」给）：改哪段提示 / 哪张表。**不改判据。**
FIX_POINTS: Dict[str, str] = {
    "applies_to_genre": (
        "`tools/kb_fetch/build_hypergraph.py` 的 `SYSTEM_PROMPT` 规则 1c"
        "（`:445`）只把它列进「额外成员清单」，**没有进 6b 的逐类自问表**"
        "（那张表才是决定模型「每张卡必须逐条问一遍」的那张）。候选修复＝把"
        "「这张卡的结论只在某题材成立吗？」加进 6b，并在规则 7 的闭集行"
        "（`:519`）再点名一次。**这属于改抽取提示 ⇒ 触发索引换代**，须先按 A6 "
        "登记（模板见 `docs/knowledge/REGEN_LOG_TEMPLATE.md`），本卡不执行。"),
    "applies_to_shot_size": (
        "同 `applies_to_genre`：`SYSTEM_PROMPT` 规则 1c（`:445`）＋规则 7"
        "（`:520`）有它，6b 的逐类自问表没有。候选修复同上一格，**同批换代**。"),
}


# --------------------------------------------------------------------- 采集


def _read_jsonl(path: pathlib.Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _member_kind(member: Any) -> str:
    #: 成员形状统一是 ``[role, kind, node_id]``（`hypergraph.Member` 的序列化）。
    if isinstance(member, (list, tuple)) and len(member) >= 2:
        return str(member[1])
    if isinstance(member, dict):
        return str(member.get("kind") or "")
    return ""


def _kind_counts(rows: Sequence[Dict[str, Any]]) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    for row in rows:
        for member in row.get("members") or []:
            kind = _member_kind(member)
            if kind:
                counts[kind] += 1
    return counts


def index_member_counts() -> collections.Counter:
    return _kind_counts(_read_jsonl(ROOT / "knowledge" / "hypergraph.edges.jsonl"))


def vocab_node_counts() -> collections.Counter:
    payload = json.loads(
        (ROOT / "knowledge" / "hypergraph.vocab.json").read_text(encoding="utf-8"))
    counts: collections.Counter = collections.Counter()
    for node in payload.get("nodes") or []:
        counts[str(node.get("type") or "")] += 1
    return counts


def _prompt_span(lines: Sequence[str]) -> Tuple[int, int]:
    """`SYSTEM_PROMPT` 的三引号区间（0 基，含头含尾）。找不到就退回全文。"""
    start = next((i for i, line in enumerate(lines)
                  if line.startswith('SYSTEM_PROMPT = """')), None)
    if start is None:
        return 0, len(lines) - 1
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == '"""'), len(lines) - 1)
    return start, end


def prompt_lines(kind: str) -> List[int]:
    """`kind` 在**抽取提示词主体**里出现的行号（源码注释不算——那正是要区分的）。"""
    lines = (ROOT / "tools" / "kb_fetch" / "build_hypergraph.py").read_text(
        encoding="utf-8").splitlines()
    start, end = _prompt_span(lines)
    return [i + 1 for i in range(start, end + 1) if kind in lines[i]]


def allowed_by(edge_members: Dict[str, Sequence[Tuple[str, str]]],
               kind: str) -> List[str]:
    return sorted(etype for etype, pairs in edge_members.items()
                  if any(pair[1] == kind for pair in pairs))


def closure_bindings() -> Dict[str, Any]:
    """执行闭环诊断的映射表（**导入**，不抄第二份）。"""
    path = ROOT / "tools" / "knowledge" / "execution_closure_report.py"
    spec = importlib.util.spec_from_file_location("_ecr_for_p5t1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)          # type: ignore[union-attr]
    return module.BINDINGS


def measure() -> Dict[str, Dict[str, Any]]:
    index_counts = index_member_counts()
    vocab_counts = vocab_node_counts()
    atoms = _kind_counts(_read_jsonl(ROOT / "work" / "hypergraph.atoms.jsonl"))
    rejects = _kind_counts(
        _read_jsonl(ROOT / "work" / "hypergraph.atom_rejects.jsonl"))
    result: Dict[str, Dict[str, Any]] = {}
    for kind in TARGETS:
        domain = hg.VALUE_DOMAINS.get(kind)
        result[kind] = {
            "declared": kind in hg.QUALIFIER_KINDS,
            "domain_kind": "none" if domain is None else "enum",
            "domain": None if domain is None else list(domain),
            "required_by": allowed_by(hg.REQUIRED_MEMBERS, kind),
            "optional_by": allowed_by(hg.OPTIONAL_MEMBERS, kind),
            "vocab_nodes": int(vocab_counts.get(kind, 0)),
            "prompt_lines": prompt_lines(kind),
            "index_members": int(index_counts.get(kind, 0)),
            "atoms": int(atoms.get(kind, 0)),
            "atom_rejects": int(rejects.get(kind, 0)),
            "verdict": EXPECTED[kind]["verdict"],
        }
    return result


# --------------------------------------------------------------- 自洽与报告


def self_check(measured: Dict[str, Dict[str, Any]]) -> List[str]:
    """把实测与 `EXPECTED` 对拍；任何漂移都列出来（调用方决定要不要非零退出）。"""
    drift: List[str] = []
    for kind, expected in EXPECTED.items():
        got = measured[kind]
        for key, want in expected.items():
            if key == "prompt_lines":
                if sorted(got[key]) != sorted(want):
                    drift.append(f"{kind}.{key}: {got[key]} != {want}")
                continue
            if got.get(key) != want:
                drift.append(f"{kind}.{key}: {got.get(key)} != {want}")
    return drift


def _table(measured: Dict[str, Dict[str, Any]]) -> str:
    lines = [
        "| kind | schema 声明 | `VALUE_DOMAINS` | 词表节点 | 提示点名行 | "
        "索引成员 | 原子边 | 原子拒收 | 判定 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for kind in TARGETS:
        item = measured[kind]
        declared = "qualifier ✓" if item["declared"] else "（不在闭集）"
        domain = ("`None`（显式不设枚举）" if item["domain_kind"] == "none"
                  else "枚举 " + "/".join(item["domain"] or []))
        prompt = ("、".join(f":{n}" for n in item["prompt_lines"])
                  if item["prompt_lines"] else "**未点名**")
        lines.append(
            f"| `{kind}` | {declared} | {domain} | {item['vocab_nodes']} | "
            f"{prompt} | {item['index_members']} | {item['atoms']} | "
            f"{item['atom_rejects']} | **{item['verdict']}** |")
    return "\n".join(lines)


def render(measured: Dict[str, Dict[str, Any]]) -> str:
    manifest = json.loads(
        (ROOT / "knowledge" / "hypergraph.manifest.json").read_text(
            encoding="utf-8"))
    bindings = closure_bindings()
    out: List[str] = []
    add = out.append

    add("# 5 个零成员 kind 的诊断（执行文档 v1.5 / P5-T1 / FX-6 / 清单 B5）")
    add("")
    add(f"**run-id**：{RUN_ID}　**生成者**：`zero_member_kinds.py`（本文档由它逐字节生成）")
    add(f"**schema**：`{hg.SCHEMA_VERSION}`　指纹 `{hg.schema_fingerprint()[:16]}`　"
        f"判定仪器：`gate/v2` / `extract/v18` / `corpus 8b308f0b`")
    add("")
    add("**性质**：诊断。**不改任何代码与判据**（红线 R-5）；不给「该不该删」的结论，")
    add("只回答卡 P5-T1 问的那件事——这五个 kind 是**有意不用**还是**漏抽**。")
    add("")
    add("## 1. 三层证据（机械，逐字节可复算）")
    add("")
    add(_table(measured))
    add("")
    add("列义：**schema 声明**＝在 `QUALIFIER_KINDS` 里；**词表节点**＝抽取器拿到的")
    add("冻结词表（`knowledge/hypergraph.vocab.json`）里 `kind:取值` 节点的条数；")
    add("**提示点名行**＝`tools/kb_fetch/build_hypergraph.py` 的 **`SYSTEM_PROMPT` 主体**")
    add("（`:374` 起的三引号块）里出现该串的行号——**源码注释里的出现不算**；")
    add("**索引成员**＝已发货的 638 条边里该 kind 的成员数；**原子边/原子拒收**＝上一段")
    add("抽取的两个中间产物（`work/hypergraph.atoms.jsonl` /")
    add("`work/hypergraph.atom_rejects.jsonl`）。")
    add("")
    add(f"索引级佐证（`knowledge/hypergraph.manifest.json`）：`cards {manifest['cards']}`、"
        f"`valid_unique {manifest['valid_unique']}`、**`rejects {manifest['rejects']}`**、"
        f"`atom_rejects {manifest['atom_rejects']}`、"
        f"`merge_rejects {manifest['merge_rejects']}`、"
        f"`dangling_members_dropped {manifest['merge']['dangling_members_dropped']}`。")
    add("⇒ 归并期**没有**任何一条边因挂了这五个 kind 被拒（`rejects 0`、"
        "`dangling 0`）；夹在中间的 464 条原子拒收里也**一条都没有**它们"
        "（见上表最后两列）。")
    add("")
    add("## 2. 逐条判定与出处")
    add("")
    for kind in TARGETS:
        item = measured[kind]
        add(f"### `{kind}` —— **{item['verdict']}**")
        add("")
        add(f"* **schema**：qualifier 闭集成员；必填于 "
            f"{item['required_by'] or '（无）'}，选填于 "
            f"{item['optional_by'] or '（无）'}；`VALUE_DOMAINS` = "
            + ("`None`（显式不设枚举）" if item["domain_kind"] == "none"
               else "、".join(item["domain"] or [])) + "。")
        add(f"* **词表**：`kind:取值` 节点 **{item['vocab_nodes']}** 个"
            + ("　⇒ 模型**无从可填**（规则 2：`node_id` 必须取自词表）。"
               if item["vocab_nodes"] == 0 else "　⇒ 模型**有值可填**。"))
        if item["prompt_lines"]:
            where = "、".join(f"`:{n}`" for n in item["prompt_lines"])
            add(f"* **提示**：点名于 {where}。")
        else:
            add("* **提示**：**未点名**（提示词从不要求模型产出它）。")
        add(f"* **实测产量**：索引成员 **{item['index_members']}**、原子边 "
            f"**{item['atoms']}**、原子拒收 **{item['atom_rejects']}**。")
        if kind in DESIGN_NOTES:
            add(f"* **有意不用/延后的落地证据**：{DESIGN_NOTES[kind]}")
        if kind in FIX_POINTS:
            add(f"* **修复点（只提案，本卡不做）**：{FIX_POINTS[kind]}")
        add("")

    add("## 3. 结论")
    add("")
    add("* **漏抽（2 个）**：`applies_to_genre`、`applies_to_shot_size`。提示点名了、"
        "词表给了值、校验门也放行，但**原子层就是 0**——抽取器从未产出。修复点在抽取")
    add("  提示（把它们从「额外成员清单」提到 6b 的逐类自问表），**属改提示 ⇒ 索引换代**，")
    add("  须按 A6 登记；本卡不改。")
    add("* **有意不用（1 个）**：`example_shot`。自由文本的**参考资料引用**，天生不是条件；")
    add("  且词表里 0 个节点 ⇒ 结构性不可产。")
    add("* **有意延后（2 个）**：`seq_phase`、`carry_shots`。v3/S1a 的惰性键：键先进闭集、")
    add("  取值域留给 S2；`tests/test_qualifier_lazy_keys.py` 把「延后」钉住。")
    add("")

    add("## 4. 若纳入执行闭环判定所需的**映射增量**（清单 B6 备料，只列不设门）")
    add("")
    add("现行闭环诊断的映射表（**导入自** `tools/knowledge/execution_closure_report.py`，")
    add("不抄第二份）只收能**精确判等**的 kind：")
    add("")
    add("```")
    for kind in sorted(bindings):
        add(f"{kind} -> {tuple(bindings[kind][0])}")
    add("```")
    add("")
    add("这五个 kind **一个都不在**映射表里 ⇒ 它们现在全部落进 `not_covered_kinds`")
    add("（「判不了」），**不当违规报**。若要把它们纳入判定，各自需要的增量是：")
    add("")
    add("| kind | 成片侧有没有对应字段 | 需要的增量 | 性质 |")
    add("|---|---|---|---|")
    add("| `applies_to_shot_size` | 有（`shots[].shot_type`，已被 `shot_size` 用着） "
        "| 加一条绑定即可（与 `shot_size` 同字段） | ① 类，**可实现** |")
    add("| `applies_to_genre` | 无（成片侧没有题材字段） "
        "| 生成器先产 `shots[].declared.genre` | ② 类，**要新字段** |")
    add("| `example_shot` | 无 | 它是自由文本引用、**不参与判定** | "
        "③ 类，**不该纳入** |")
    add("| `seq_phase` | 无 | 先有 S2 产取值、再谈成片侧字段 | ② 类，**依赖 S2** |")
    add("| `carry_shots` | 无 | 同 `seq_phase` | ② 类，**依赖 S2** |")
    add("")
    add("**口径纪律**：本表只是「若要判、缺什么」的清单，**不是**设门提案——"
        "设门＝新判据，须用户裁决（清单 D11）。")
    add("")

    add("## 5. 复算")
    add("")
    add("```")
    add(f"python docs/evidence/{RUN_ID}/zero_member_kinds.py          # 重新生成本文档")
    add(f"python docs/evidence/{RUN_ID}/zero_member_kinds.py --check  # 与本文档对拍")
    add("```")
    return "\n".join(out) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="只对拍，不写盘；不一致时非零退出")
    args = parser.parse_args(argv)

    measured = measure()
    text = render(measured)

    drift = self_check(measured)
    if drift:
        for line in drift:
            print(f"[DRIFT] {line}", file=sys.stderr)
        print("实测与 EXPECTED 快照不符 —— 先核对语料/索引是否换代，再改本脚本。",
              file=sys.stderr)
        return 2

    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"[FAIL] {OUT} 与现算不一致（删掉它再跑本脚本即可重生成）",
                  file=sys.stderr)
            return 1
        print(f"[OK] {OUT.name} 与现算一致")
        return 0

    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"[OK] 已生成 {OUT.relative_to(ROOT)}（{len(text)} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
