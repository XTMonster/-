"""入库证据的摘要必须**跟检出形态无关**——否则"验收链只在产它的机器上绿"。

现场（2026-10-04 实测）：`tools/extract_run_evidence.py::sha256_file` 原来是**裸字节**
哈希，而 `.gitattributes` 明确把 `*.json` / `*.jsonl` 存成 **LF**
（"Store LF in the repo for source and docs"）。Windows 上文本模式写出的证据是 CRLF，
于是：

* 产它的那棵工作树：pin 对得上（因为它从没被重新检出过）；
* `git worktree add` / 新克隆：拿到 LF 副本 ⇒ `audit_log.jsonl` / `llm_trace.jsonl` /
  `knowledge_trace.json` / `shots.json` 四条 pin **全部**报 STALE，
  `tests/test_extract_run_evidence.py` 有 3 条必红。

实测对照（同一份分片）：主树 96766 字节 / 248 个 CRLF；新 worktree 96518 字节 / 0 个 CRLF。

这里钉三件事，缺一不可：
1. 归一摘要**跨换行形态相等**（LF 与 CRLF 算出同一个值）；
2. 归一**不削弱防篡改**：内容真变了摘要就要变；
3. `repin` 只重签"同一份内容、换行口径不同"的 pin，**不许**把换代洗成没换代。
4. 把一份入库证据**按新检出（全 LF）重放**，`check` 必须零理由——这才是"新克隆也能过"。
5. 新落的证据在**盘上**就是 LF（与入库形态一致，而不是"提交时才被 git 归一"）。
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.extract_run_evidence as X  # noqa: E402

HOLDOUT = ROOT / "fixtures" / "knowledge_holdout.jsonl"
INDEX_MANIFEST = ROOT / "knowledge" / "hypergraph.manifest.json"


def _write(path: pathlib.Path, text: str, *, newline: str) -> pathlib.Path:
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


def test_the_digest_does_not_depend_on_line_endings(tmp_path):
    body = '{"a": 1, "b": "中文"}\n{"a": 2}\n'
    lf = _write(tmp_path / "lf.jsonl", body, newline="\n")
    crlf = _write(tmp_path / "crlf.jsonl", body, newline="\r\n")

    assert lf.read_bytes() != crlf.read_bytes()      # 盘上确实不是同一串字节
    assert X.sha256_file(lf) == X.sha256_file(crlf)  # 但摘要必须相等
    #: 裸字节口径仍然分得开——repin 的安全规则要靠它。
    assert X.sha256_raw(lf) != X.sha256_raw(crlf)


def test_normalising_does_not_weaken_tamper_detection(tmp_path):
    original = _write(tmp_path / "a.jsonl", '{"a": 1}\n', newline="\r\n")
    before = X.sha256_file(original)
    #: 值改了
    _write(original, '{"a": 2}\n', newline="\r\n")
    assert X.sha256_file(original) != before
    #: 只是多了一行，也要变
    _write(original, '{"a": 1}\n{"a": 1}\n', newline="\r\n")
    assert X.sha256_file(original) != before
    #: 空行（真内容）也要变——归一化只把 `\r\n` 看成 `\n`，不吞行
    _write(original, '{"a": 1}\n\n', newline="\r\n")
    assert X.sha256_file(original) != before


def _seed_manifest(run_dir: pathlib.Path, *, pin: str) -> pathlib.Path:
    """造一份最小清单：分片 CRLF 落盘，pin 由调用方给。"""
    _write(run_dir / "audit_log.jsonl", '{"run_id": "r1"}\n', newline="\r\n")
    manifest = {
        "run_id": "r1",
        "artifacts": {"audit_log.jsonl": {"sha256": pin, "lines": 1}},
        "pins": {"holdout": {"path": str(HOLDOUT),
                             "sha256": X.sha256_file(HOLDOUT)},
                 "index": {"fingerprint": "unused"}},
    }
    path = run_dir / X.MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def test_repin_resigns_a_line_ending_only_pin(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    raw_pin = _write(run_dir / "audit_log.jsonl", '{"run_id": "r1"}\n',
                     newline="\r\n")
    manifest_path = _seed_manifest(run_dir, pin=X.sha256_raw(raw_pin))

    report = X.repin(out_dir=run_dir, holdout=HOLDOUT)

    assert [item.split(":")[0] for item in report["updated"]] == [
        "audit_log.jsonl"]
    assert report["skipped"] == []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifacts"]["audit_log.jsonl"]["sha256"] == \
        X.sha256_file(raw_pin)


def test_repin_refuses_to_hide_a_generation_change(tmp_path):
    """旧 pin 既不是归一摘要、也不是裸字节摘要 ⇒ 内容是**真的**变了，不许重签。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write(run_dir / "audit_log.jsonl", '{"run_id": "r1"}\n', newline="\r\n")
    manifest_path = _seed_manifest(run_dir, pin="f" * 64)

    report = X.repin(out_dir=run_dir, holdout=HOLDOUT)

    assert report["updated"] == []
    assert len(report["skipped"]) == 1
    assert "真的" in report["skipped"][0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifacts"]["audit_log.jsonl"]["sha256"] == "f" * 64


def test_repin_leaves_a_correct_pin_alone(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    target = _write(run_dir / "audit_log.jsonl", '{"run_id": "r1"}\n',
                    newline="\r\n")
    _seed_manifest(run_dir, pin=X.sha256_file(target))

    report = X.repin(out_dir=run_dir, holdout=HOLDOUT)

    assert report["updated"] == []
    #: 分片与 oracle 的 pin 都已经是对的 → 一个都不改。
    assert report["unchanged"] == ["audit_log.jsonl", "pins.holdout"]
    assert report["skipped"] == []


def test_extract_writes_lf_to_disk(tmp_path):
    """源日志是 CRLF（Windows 上文本模式的常态），落盘的分片与清单必须是 **LF**。

    这样"盘上字节 == 入库字节"，不会出现"git status 干净、字节却不一样"的假象。
    """
    source = tmp_path / "audit.jsonl"
    source.write_text('{"run_id": "r1"}\n{"run_id": "r1"}\n{"run_id": "x"}\n',
                      encoding="utf-8")          # Windows 上这里写出 CRLF
    assert b"\r\n" in source.read_bytes(), "前提：源日志是 CRLF"

    out = tmp_path / "out"
    X.extract(run_id="r1", out_dir=out, audit_log=source,
              llm_trace=tmp_path / "no-such-trace.jsonl", shots=None,
              knowledge_trace=None, holdout=HOLDOUT,
              index_manifest=INDEX_MANIFEST)

    for name in ("audit_log.jsonl", X.MANIFEST_NAME):
        data = (out / name).read_bytes()
        assert b"\r" not in data, f"{name} 里还有 CR，盘上字节与入库形态不一致"
    manifest = json.loads((out / X.MANIFEST_NAME).read_text(encoding="utf-8"))
    #: 只搬 run_id 相符的两行，且 pin 是归一摘要（等于 LF 形态的裸字节摘要）。
    assert manifest["artifacts"]["audit_log.jsonl"]["lines"] == 2
    assert manifest["artifacts"]["audit_log.jsonl"]["sha256"] == \
        X.sha256_raw(out / "audit_log.jsonl")


@pytest.mark.parametrize("run_id", ["20261007-v15-6shot-ds", "20261007-v15-long"])
def test_a_landed_run_still_checks_out_after_an_lf_checkout(tmp_path, run_id):
    """把入库证据**按新检出重放**（每个文本文件都变成 LF），`check` 必须零理由。

    这就是原缺陷的判据：此前那四条 pin 是从 CRLF 字节算的，LF 副本一律 STALE。

    **2026-10-07（`rebind/v2` 换代）**：参数表从
    `20261003_real_glm / _ds / _long` 换成本代的两份真跑——`check()` 里那条
    "索引指纹必须与现行一致"是**同代性**判据，上一代的证据件会被（正确地）判红。
    旧那三份**留在库里当历史**，不再被这条用例读。判据与断言强度一个字没动。
    """
    source = ROOT / "docs" / "evidence" / run_id
    if not (source / X.MANIFEST_NAME).is_file():
        pytest.skip(f"{run_id} 的证据还没入库")
    target = tmp_path / run_id
    shutil.copytree(source, target)
    for path in target.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}:
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))

    reasons = X.check(out_dir=target, holdout=HOLDOUT,
                      index_manifest=INDEX_MANIFEST)

    assert reasons == [], reasons
