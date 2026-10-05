"""P6③：把评测集**冻起来**（计划里 `freeze_eval.py` 那一步）。

为什么必须有：A/B 的可比性全靠"三臂跑在**同一批查询**上"。而这批查询来自一次
真实运行（`project.bdproj`）——运行一换代、查询就换，"哪条检索路更好"就变成
拿两把尺子量。所以评测集要落成一个**带摘要的冻结文件**，并用它当三臂的共同输入。

三条纪律：

* **可复算**：同输入 ＋ 同种子 ⇒ 同抽样、同摘要（不是"随机一次"）；
* **摘要随内容变**：改一行内容 ⇒ 摘要必须变；
* **如实记来源**：冻结文件里写清它从哪来（哪个项目／哪份查询表）＋ 条数 ＋ 抽样参数，
  否则以后没人知道这 192 行是怎么来的。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import freeze_eval as fe  # noqa: E402


def _lines(count: int):
    return ["镜号%03d：推进主线，中景固定镜头。" % index for index in range(count)]


def test_the_frozen_set_is_reproducible():
    first = fe.freeze(_lines(50), source="unit", seed=7, size=10)
    second = fe.freeze(_lines(50), source="unit", seed=7, size=10)
    assert first["sha256"] == second["sha256"]
    assert first["queries"] == second["queries"]


def test_a_different_seed_gives_a_different_sample():
    a = fe.freeze(_lines(50), source="unit", seed=1, size=10)
    b = fe.freeze(_lines(50), source="unit", seed=2, size=10)
    assert a["sha256"] != b["sha256"]


def test_the_digest_moves_when_the_content_moves():
    a = fe.freeze(_lines(20), source="unit", seed=1, size=5)
    moved = _lines(20)
    moved[3] = "改了一行。"
    b = fe.freeze(moved, source="unit", seed=1, size=5)
    assert a["sha256"] != b["sha256"]


def test_size_larger_than_available_keeps_everything():
    report = fe.freeze(_lines(6), source="unit", seed=1, size=99)
    assert len(report["queries"]) == 6 and report["size"] == 6


def test_the_manifest_remembers_where_it_came_from(tmp_path):
    out = tmp_path / "heldout.jsonl"
    report = fe.write(out, _lines(30), source="docs/evidence/x/project/project.bdproj",
                      seed=20261005, size=12)
    payload = json.loads((tmp_path / "heldout.manifest.json").read_text(encoding="utf-8"))
    assert payload["source"].endswith("project.bdproj")
    assert payload["size"] == 12 and payload["seed"] == 20261005
    assert payload["sha256"] == report["sha256"]
    #: 冻结文件本身也得落盘，且行数就是抽样后的条数。
    rows = out.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 12
    assert hashlib.sha256(out.read_bytes()).hexdigest()
