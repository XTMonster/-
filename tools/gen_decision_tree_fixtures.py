"""阶段 1：从 r6 审计日志导出决策树回归夹具。

设计文档 ``work/per_shot_decision_tree_design.md`` §6 阶段 1 口径：

- 只导出进树的 **12 条**（draft 2 + react 5 + repair 5）＋
  ``self_review_invalid`` 1 条单列；
- 9 条 ``no_tool`` **不进树**，但导出在 ``no_tool_entries`` 单列，
  供测试断言「树不吞」；
- 夹具只保留可复现的语义字段：``kind`` / ``semantic`` / ``shot_id`` /
  ``message`` / ``tool_name?`` / ``args?``，不含对话原文与 LLM trace；
- 分类按 message 内容（与 §5 覆盖账一致），不用时间序硬配语义；
- 排序固定（树条目按 kind 固定顺序 + 每条原始时间戳），逐字节可复现；
- ``--check`` 只校验不写入，沿用 golden 的同一套防漂移纪律。

用法：
  python tools/gen_decision_tree_fixtures.py          # 写入
  python tools/gen_decision_tree_fixtures.py --check  # 只校验
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "12dadce87acc"
OUTPUT = ROOT / "tests" / "fixtures" / "decision_tree" / "r6_invalids.json"
DEFAULT_LOG = (Path(os.environ.get("USERPROFILE", ""))
               / "Documents" / "BlockDirector Projects" / "runs"
               / "audit_log.jsonl")

#: 进树 12 条的固定语义描述（§5 覆盖账），每条由一个判定函数识别。
TREE_KINDS = ("draft_invalid", "react_invalid", "repair_invalid")


def _classify_tree(kind: str, message: str) -> Optional[str]:
    """按 message 内容判定语义（与 §5 覆盖账一一对应）。"""
    if "回复中没有工具调用" in message:
        return None  # no_tool：不进树
    if "不在动作类型闭集内" in message or "finger_snap" in message:
        return "action_type out of closed set"
    if "不能同时写 target 与 yaw_deg/pitch_deg" in message or \
            "look_at 不能同时写" in message:
        return "look_at dual write target+angles"
    if "不允许出现字段 target_position" in message:
        return "enter_from forbidden target_position"
    if "camera.side 取值必须" in message and "实际 'side'" in message:
        return "camera.side='side'"
    if "camera.side 取值必须" in message:
        return "camera.side free text"
    return None


def _extract_shot(data: Dict[str, Any]) -> Optional[str]:
    """data 里可能放 shot / shot_id / args.shot_id。"""
    for key in ("shot", "shot_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    args = data.get("args")
    if isinstance(args, dict):
        value = args.get("shot_id")
        if isinstance(value, str) and value:
            return value
    return None


def _extract_args(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("args", "tool_args", "arguments"):
        value = data.get(key)
        if isinstance(value, dict):
            return dict(value)
    return None


def _sort_key(row: Dict[str, Any]) -> tuple:
    return (float(row.get("ts", 0.0)), json.dumps(
        {key: value for key, value in row.items()
         if key != "ts"}, ensure_ascii=False, sort_keys=True))


def load_rows(log_path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(log_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("run_id") != RUN_ID:
                continue
            rows.append(row)
    return rows


def collect(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按阶段 1 口径筛出 12 进树 + 9 no_tool + 1 self_review。"""
    tree_rows: List[Dict[str, Any]] = []
    no_tool_rows: List[Dict[str, Any]] = []
    self_review_rows: List[Dict[str, Any]] = []
    for row in sorted(rows, key=_sort_key):
        kind = str(row.get("kind", ""))
        message = (row.get("message") or "").strip()
        data = row.get("data") or {}
        if kind == "self_review_invalid":
            record = {"kind": kind, "message": message}
            shot_id = _extract_shot(data)
            if shot_id:
                record["shot_id"] = shot_id
            self_review_rows.append(record)
            continue
        if kind not in TREE_KINDS:
            continue
        semantic = _classify_tree(kind, message)
        if semantic is None:
            no_tool_rows.append({"kind": kind, "message": message})
            continue
        record: Dict[str, Any] = {
            "kind": kind,
            "semantic": semantic,
            "message": message,
        }
        shot_id = _extract_shot(data)
        if shot_id:
            record["shot_id"] = shot_id
        tool_name = data.get("tool")
        if isinstance(tool_name, str) and tool_name:
            record["tool_name"] = tool_name
        args = _extract_args(data)
        if args:
            record["args"] = args
        tree_rows.append(record)

    #: 树条目排序：draft → react → repair；同 kind 保持时间序。
    def tree_order(record: Dict[str, Any]) -> tuple:
        return (TREE_KINDS.index(record["kind"]),
                json.dumps(record, ensure_ascii=False, sort_keys=True))

    tree_rows.sort(key=tree_order)
    no_tool_rows.sort(key=lambda record: (
        TREE_KINDS.index(record["kind"]), record["message"]))

    expected_tree = {
        "draft_invalid": 2, "react_invalid": 5, "repair_invalid": 5,
    }
    actual_tree = {kind: 0 for kind in TREE_KINDS}
    for record in tree_rows:
        actual_tree[record["kind"]] += 1
    if actual_tree != expected_tree:
        raise ValueError(
            f"进树条目数与 §5 覆盖账不符：{actual_tree}（期望 {expected_tree}）")
    if len(no_tool_rows) != 9:
        raise ValueError(f"no_tool 条目应为 9，实际 {len(no_tool_rows)}")

    payload = {
        "run_id": RUN_ID,
        "source": str(DEFAULT_LOG),
        "counts": {
            "tree": len(tree_rows),
            "draft": actual_tree["draft_invalid"],
            "react": actual_tree["react_invalid"],
            "repair": actual_tree["repair_invalid"],
            "no_tool": len(no_tool_rows),
            "self_review": len(self_review_rows),
        },
        "tree_entries": tree_rows,
        "no_tool_entries": no_tool_rows,
        "self_review_entries": self_review_rows,
    }
    return payload


def render(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(prog="gen_decision_tree_fixtures")
    parser.add_argument("--check", action="store_true",
                        help="只校验夹具是否与审计日志一致，不写入")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG,
                        help="审计日志路径（缺省 %USERPROFILE%/Documents/...）")
    args = parser.parse_args()

    log_path = args.log
    if not log_path.exists():
        print(f"[ERR] 审计日志不存在：{log_path}")
        return 2
    rows = load_rows(log_path)
    if not rows:
        print(f"[ERR] run_id={RUN_ID} 没有记录（日志：{log_path}）")
        return 2
    payload = collect(rows)
    content = render(payload)

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
        if current != content:
            print(f"[DRIFT] {OUTPUT.relative_to(ROOT)} 与审计日志不一致；"
                  f"请运行 python tools/gen_decision_tree_fixtures.py")
            return 1
        print("[OK] r6_invalids.json 与审计日志一致")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"[OK] 已写入 {OUTPUT.relative_to(ROOT)}（进树 "
          f"{len(payload['tree_entries'])} 条＋ no_tool "
          f"{len(payload['no_tool_entries'])} 条＋ self_review "
          f"{len(payload['self_review_entries'])} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
