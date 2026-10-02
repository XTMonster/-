"""真实运行证据的**分片**与**同代性**：`tools/extract_run_evidence.py`。

这些用例钉住三件事：

* 分片是"按 `run_id` 原样搬整行"——碰巧在同一行里出现该 id 的**别跑**不许进来，
  解析不了的行不许进来，搬进来的行必须与源文件**逐字节相同**；
* `run_manifest.json` 的 4 个 pin（分片自己 / shots.json / oracle / 索引指纹）
  真的会对拍：改一个字节、换一份 oracle、换一代索引都必须判红；
* 入库的那份真实运行证据**当前就是同代的**——这条是链上 Q5 能读它的前提
  （过期证据被当成现行证据正是 §24.1 修掉的形状）。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.extract_run_evidence as X  # noqa: E402


def _event(run_id, kind, ts, **data):
    return {"ts": ts, "run_id": run_id, "kind": kind, "data": data}


def _write_accumulated(path: pathlib.Path) -> None:
    lines = [
        json.dumps(_event("run-a", "run_started", 100.0), ensure_ascii=False),
        json.dumps(_event("run-b", "run_started", 200.0), ensure_ascii=False),
        "{ not json",
        json.dumps(_event("run-a", "retrieval_call", 101.5,
                          scope="shot", shot_id="shot_001",
                          query="景别=MCU"), ensure_ascii=False),
        # 别跑的事件里**提到** run-a（字符串出现在 query 里）——不许被搬进来。
        json.dumps(_event("run-b", "retrieval_call", 202.0,
                          scope="shot", shot_id="shot_001",
                          query="run-a 的查询"), ensure_ascii=False),
        json.dumps(_event("run-a", "run_finished", 103.0), ensure_ascii=False),
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _extract(tmp_path, run_id="run-a"):
    source = tmp_path / "audit_log.jsonl"
    _write_accumulated(source)
    trace = tmp_path / "llm_trace.jsonl"
    trace.write_text("\n".join([
        json.dumps(_event("run-a", "llm_request", 101.0), ensure_ascii=False),
        json.dumps(_event("run-b", "llm_request", 201.0), ensure_ascii=False),
    ]) + "\n", encoding="utf-8")
    shots = tmp_path / "shots.json"
    shots.write_text(json.dumps({"shots": []}), encoding="utf-8")
    out = tmp_path / "evidence"
    X.extract(run_id=run_id, out_dir=out, audit_log=source, llm_trace=trace,
              shots=shots, knowledge_trace=None,
              holdout=ROOT / "fixtures" / "knowledge_holdout.jsonl",
              index_manifest=ROOT / "knowledge" / "hypergraph.manifest.json")
    return out, source


def test_the_slice_is_byte_for_byte_and_only_this_run(tmp_path):
    out, source = _extract(tmp_path)
    original = source.read_text(encoding="utf-8").splitlines()
    sliced = (out / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(sliced) == 3                     # run-a 的三条；解析不了的那行不进
    for line in sliced:
        assert line in original                 # 逐字节：没有被重排/改写
        assert json.loads(line)["run_id"] == "run-a"
    # 别跑里"提到 run-a"的那条不许被搬进来
    assert all("run-a 的查询" not in line for line in sliced)
    # llm_trace 同样只留这一跑
    assert len((out / "llm_trace.jsonl").read_text(
        encoding="utf-8").splitlines()) == 1


def test_a_run_with_no_events_is_refused(tmp_path):
    source = tmp_path / "audit_log.jsonl"
    _write_accumulated(source)
    with pytest.raises(ValueError, match="run_id=run-c"):
        X.extract(run_id="run-c", out_dir=tmp_path / "out", audit_log=source,
                  llm_trace=tmp_path / "missing.jsonl", shots=None,
                  knowledge_trace=None,
                  holdout=ROOT / "fixtures" / "knowledge_holdout.jsonl",
                  index_manifest=ROOT / "knowledge" / "hypergraph.manifest.json")


def test_the_manifest_pins_the_slice_shots_oracle_and_index(tmp_path):
    out, _source = _extract(tmp_path)
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "run-a"
    assert set(manifest["artifacts"]) == {"audit_log.jsonl", "llm_trace.jsonl",
                                         "shots.json"}
    assert manifest["artifacts"]["audit_log.jsonl"]["lines"] == 3
    assert manifest["run_span"] == {"events": 3, "first_ts": 100.0,
                                    "last_ts": 103.0}
    for name, item in manifest["artifacts"].items():
        if "sha256" in item and (out / name).is_file():
            assert X.sha256_file(out / name) == item["sha256"]
    pins = manifest["pins"]
    assert pins["holdout"]["sha256"] == X.sha256_file(
        ROOT / "fixtures" / "knowledge_holdout.jsonl")
    assert pins["index"]["fingerprint"]


def test_check_fires_on_a_tampered_slice(tmp_path):
    out, _source = _extract(tmp_path)
    target = out / "audit_log.jsonl"
    target.write_text(target.read_text(encoding="utf-8").replace(
        "景别=MCU", "景别=MS"), encoding="utf-8")
    reasons = X.check(out_dir=out, holdout=ROOT / "fixtures" / "knowledge_holdout.jsonl",
                      index_manifest=ROOT / "knowledge" / "hypergraph.manifest.json")
    assert reasons and "sha256" in reasons[0]


def test_check_fires_when_the_oracle_or_the_index_moved_on(tmp_path):
    out, _source = _extract(tmp_path)
    manifest_path = out / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest["pins"]["holdout"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False),
                             encoding="utf-8")
    reasons = X.check(out_dir=out, holdout=ROOT / "fixtures" / "knowledge_holdout.jsonl",
                      index_manifest=ROOT / "knowledge" / "hypergraph.manifest.json")
    assert any("换代" in reason for reason in reasons), reasons

    manifest["pins"]["holdout"]["sha256"] = X.sha256_file(
        ROOT / "fixtures" / "knowledge_holdout.jsonl")
    manifest["pins"]["index"]["fingerprint"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False),
                             encoding="utf-8")
    reasons = X.check(out_dir=out, holdout=ROOT / "fixtures" / "knowledge_holdout.jsonl",
                      index_manifest=ROOT / "knowledge" / "hypergraph.manifest.json")
    assert any("索引指纹不符" in reason for reason in reasons), reasons


def test_the_landed_real_run_evidence_is_fresh():
    """入库的那份真实运行证据必须**同代**（否则链上 Q5 读的就是过期证据）。"""
    run_dir = ROOT / "docs" / "evidence" / "20261003_real_glm"
    assert (run_dir / "run_manifest.json").is_file(), (
        "真实运行的证据还没入库：缺 run_manifest.json")
    reasons = X.check(out_dir=run_dir,
                      holdout=ROOT / "fixtures" / "knowledge_holdout.jsonl",
                      index_manifest=ROOT / "knowledge" / "hypergraph.manifest.json")
    assert reasons == [], reasons
