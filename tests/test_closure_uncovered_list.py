"""**"不校验"必须是显式、带版本、机器可读的清单**（裁决 F1）。

裁决原话：②类本轮不给成片加字段，先把"不校验"落成**带版本的显式清单**
（kind＋原因＋数据源状态），**取代永久"未定义"**。

这条守门钉两件事：① 清单本身完整（每个 kind 都有原因与数据源状态）；
② **诊断报告里出现的 `not_covered_kinds` 必须都在清单里**——新 kind 一冒出来就红，
逼着人先登记、而不是让它悄悄变成"没人提"。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LIST = ROOT / "fixtures" / "closure_uncovered_kinds.json"
REPORTS = sorted((ROOT / "docs" / "evidence").glob(
    "*/report.long21.json")) + sorted((ROOT / "docs" / "evidence").glob(
        "*/sweep.all_runs.json"))


def test_every_uncovered_kind_has_a_reason_and_a_data_source_status():
    payload = json.loads(LIST.read_text(encoding="utf-8"))
    assert payload["version"] >= 1
    assert payload["kinds"], "清单不能是空的"
    for kind, entry in payload["kinds"].items():
        assert entry.get("reason"), "%s 缺原因" % kind
        assert entry.get("data_source"), "%s 缺数据源状态" % kind
        assert entry.get("class") == "B"


def test_every_kind_the_diagnostic_reports_as_uncovered_is_registered():
    registered = set(json.loads(LIST.read_text(encoding="utf-8"))["kinds"])
    seen = set()
    for path in REPORTS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "not_covered_kinds" in payload:
            seen |= set(payload["not_covered_kinds"])
        for row in payload.get("per_run") or []:
            seen |= set(row.get("not_covered_kinds") or {})
    assert seen, "一个诊断报告都没读到？这条守门是空转"
    missing = sorted(seen - registered)
    assert missing == [], (
        "这些 kind 在诊断里被判不了，却没登记进 fixtures/closure_uncovered_kinds.json：%s"
        % missing)
