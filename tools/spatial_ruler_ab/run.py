"""空间尺外挂 A/B 评测台入口（spec §15.5）。

用法：
    python tools/spatial_ruler_ab/run.py --judge mock   # 离线，plumbing
    python tools/spatial_ruler_ab/run.py --judge real   # 真实模型，ab_result

real 判官读取环境变量 SR_EVAL_API_BASE / SR_EVAL_API_KEY / SR_EVAL_MODEL。
产物：docs/evidence/spatial-ruler-eval/<timestamp>/{report.json,report.md,
transcript.jsonl}。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.spatial_ruler_ab.fixtures import build_battery  # noqa: E402
from tools.spatial_ruler_ab.llm import MockJudge, RealJudge  # noqa: E402
from tools.spatial_ruler_ab.report import (  # noqa: E402
    default_timestamp,
    run_experiment,
    write_report,
)


def _make_judge(judge_kind: str):
    if judge_kind == "mock":
        return MockJudge()
    api_base = os.environ.get("SR_EVAL_API_BASE")
    api_key = os.environ.get("SR_EVAL_API_KEY")
    model = os.environ.get("SR_EVAL_MODEL")
    missing = [name for name, val in
               (("SR_EVAL_API_BASE", api_base), ("SR_EVAL_API_KEY", api_key),
                ("SR_EVAL_MODEL", model)) if not val]
    if missing:
        sys.exit("--judge real 需要环境变量：" + ", ".join(missing))
    return RealJudge(api_base=api_base, api_key=api_key, model=model)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge", choices=["mock", "real"], default="mock",
                        help="判官：mock 离线确定性 / real 真实模型")
    parser.add_argument("--out", default=None,
                        help="产物目录，默认 docs/evidence/spatial-ruler-eval/<ts>")
    parser.add_argument("--timestamp", default=None)
    args = parser.parse_args()

    judge = _make_judge(args.judge)
    if getattr(judge, "evidence_grade", "") == "plumbing":
        print("⚠️  mock 判官：只证明管线通（plumbing），不是效果证据。")
        print("    真实结论请用 --judge real（ab_result）。")

    battery = build_battery()
    ts = args.timestamp or default_timestamp()
    report = run_experiment(judge, battery, timestamp=ts)
    out_dir = Path(args.out) if args.out else \
        ROOT / "docs" / "evidence" / "spatial-ruler-eval" / ts
    paths = write_report(report, out_dir)

    arms = report["arms"]
    b, r = arms["baseline"], arms["ruler"]
    m, rm = arms["method"], arms["ruler_method"]
    print(f"任务数：{b['total']}×4 臂（{len(battery)} 任务）")
    print(f"基线臂：{b['correct']}/{b['total']} = {b['overall']:.4f}")
    print(f"尺子臂：{r['correct']}/{r['total']} = {r['overall']:.4f}")
    print(f"方法臂：{m['correct']}/{m['total']} = {m['overall']:.4f}")
    print(f"方法+尺子：{rm['correct']}/{rm['total']} = {rm['overall']:.4f}")
    d = report["delta"]
    print(f"读数增量  ：{d['ruler_vs_baseline']['overall']:+.4f}")
    print(f"方法论增量：{d['method_vs_baseline']['overall']:+.4f}")
    print(f"总增量    ：{d['ruler_method_vs_baseline']['overall']:+.4f}")
    print(f"交互增量  ：{d['ruler_method_vs_sum']['overall']:+.4f}")
    print(f"judge  ：{report['judge']['name']}"
          f"{' / ' + str(report['judge']['model']) if report['judge']['model'] else ''}"
          f"（evidence_grade={report['judge']['evidence_grade']}）")
    print("产物：")
    for label, path in paths.items():
        print(f"  {label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
