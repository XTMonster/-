"""`tools/holdout_expect_movements.py` 的**并发与续跑**（不联网，模型被替身顶掉）。

为什么值得一组用例：这份标注是 Q5 分母的唯一来源，而单条含思考要 40-70 s ⇒
176 条顺序跑要数小时。并发是必需的，但它必须**不改变产物形状**：每条一行、
append + flush、失败只影响那一条、`--resume` 一条都不重跑。

模型调用被 `StubClient` 顶掉：本用例量的是**编排**（并发/落盘/续跑），
不是模型的判断质量——那由管线外的独立标注与面板复核负责。
"""

from __future__ import annotations

import json

import tools.holdout_expect_movements as H
from block_director.knowledge.corpus import CARDS


class StubClient:
    """答固定内容的替身：只验证"取回来的东西怎么落盘"。"""

    model_id = "stub-annotator"
    model_version = "stub-annotator"
    family = "zhipu"
    decode_tag = "thinking=stub;max_tokens=0"

    def __init__(self, *args, **kwargs) -> None:
        pass

    def chat_json(self, system, user, temperature, seed, num_ctx, **_kwargs):
        return {"expect_movements": [{"value": "dolly_in",
                                      "quote": "镜头缓慢推进到脸部"}],
                "empty_reason": ""}


def _holdout(tmp_path, count):
    card = CARDS[0]
    path = tmp_path / "holdout.jsonl"
    rows = [{"id": f"t_{index:03d}", "from_card": card.id,
             "q": "景别=MS；运镜=固定",
             "must": ["SHOT_PATTERN:shot_size=MS,lens=35mm,"
                      "headroom_policy=cinematic"],
             "top1": [], "never": [],
             "annotator": {"model_id": "stub", "family": "deepseek",
                           "model_version": "stub", "prompt_sha256": "x"}}
            for index in range(count)]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
                    + "\n", encoding="utf-8")
    return path


def test_concurrency_writes_every_row(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "GLMClient", StubClient)
    holdout = _holdout(tmp_path, 6)
    out = tmp_path / "out.jsonl"
    code = H.main(["--holdout", str(holdout), "--out", str(out),
                   "--concurrency", "3"])
    assert code == 0
    rows = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 6
    assert {row["id"] for row in rows} == {f"t_{index:03d}" for index in range(6)}
    #: 标注者身份必须随行落盘（换族纪律的证据链），不是"工具说的"。
    assert all(row["annotator"]["family"] == "zhipu" for row in rows)
    assert all(row["expect_movements"] == ["dolly_in"] for row in rows)
    assert all(row["evidence"][0]["quote"] for row in rows)


def test_resume_reruns_nothing(tmp_path, monkeypatch):
    """带 `--resume` 的第二趟**一次模型调用都不发生**。"""
    calls = {"n": 0}

    class Counting(StubClient):
        def chat_json(self, *args, **kwargs):
            calls["n"] += 1
            return super().chat_json(*args, **kwargs)

    monkeypatch.setattr(H, "GLMClient", Counting)
    holdout = _holdout(tmp_path, 4)
    out = tmp_path / "out.jsonl"
    assert H.main(["--holdout", str(holdout), "--out", str(out),
                   "--concurrency", "2"]) == 0
    assert calls["n"] == 4
    assert H.main(["--holdout", str(holdout), "--out", str(out),
                   "--concurrency", "2", "--resume"]) == 0
    assert calls["n"] == 4
    assert len(out.read_text(encoding="utf-8").splitlines()) == 4


def test_a_missing_card_is_reported_not_swallowed(tmp_path, monkeypatch, capsys):
    """卡片不存在 ⇒ 如实进 failures（缺证据不算通过），其它条照常落盘。"""
    monkeypatch.setattr(H, "GLMClient", StubClient)
    holdout = _holdout(tmp_path, 2)
    lines = holdout.read_text(encoding="utf-8").splitlines()
    broken = json.loads(lines[0])
    broken["from_card"] = "gen_does_not_exist"
    lines[0] = json.dumps(broken, ensure_ascii=False)
    holdout.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "out.jsonl"
    code = H.main(["--holdout", str(holdout), "--out", str(out),
                   "--concurrency", "2"])
    assert code == 1
    printed = capsys.readouterr().out.strip()
    summary = json.loads(printed[printed.index("{"):])
    assert summary["failure_count"] == 1
    assert "gen_does_not_exist" in summary["failures"][0]["reason"]
    failure_rows = [json.loads(line) for line in
                    out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(failure_rows) == 1
    assert failure_rows[0]["id"] == "t_001"
