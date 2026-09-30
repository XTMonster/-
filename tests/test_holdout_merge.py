"""分片 held-out 的合并工具（`tools/holdout_merge.py`）的对拍测试。

合并是 oracle 的唯一入口，所以这里测的不是"能不能跑通"，而是四件会让
oracle 不可信的事：重复条目、不合规条目、id 编号、以及卡片全集的写法。
"""

from __future__ import annotations

import json
import pathlib

from tools import holdout_merge


def _entry(card: str, q: str, must: list, ident: str = "hq_0001") -> dict:
    return {
        "id": ident, "from_card": card, "q": q,
        "must": list(must), "top1": [must[0]], "never": [],
        "annotator": {"model_id": "glm-4.6", "family": "zhipu",
                      "model_version": "glm-4.6"},
        "independence": "strong",
    }


def _write(path: pathlib.Path, rows: list) -> pathlib.Path:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return path


def test_merge_dedupes_validates_and_renumbers(tmp_path):
    good = _entry("gen_cine_0001", "情绪=荒诞；运镜=固定",
                  ["EMOTION_PACK:emotion=荒诞,intensity=high"])
    other = _entry("gen_cine_0002", "题材=film；情绪=荒诞",
                   ["TROPE:genre=film,emotion=荒诞"])
    # 取值域由门③判（`unknown_values`），合并这一步判的是**格式**：
    # 未知边类型、top1 不在 must 里、缺字段这类问题在这里就被拦下。
    broken = _entry("gen_cine_0003", "情绪=荒诞", ["NOPE_PACK:emotion=荒诞"])
    shard_a = _write(tmp_path / "partial0.jsonl", [good, other])
    shard_b = _write(tmp_path / "partial1.jsonl", [good, broken])   # good 是重复

    report = holdout_merge.run([str(shard_a), str(shard_b)],
                               tmp_path / "holdout.jsonl",
                               cards=["gen_cine_0001", "gen_cine_0002", "gen_cine_0003"])

    assert report["raw"] == 4 and report["after_dedupe"] == 3
    assert report["valid"] == 2 and report["invalid"] == 1
    rows = [json.loads(line) for line in
            (tmp_path / "holdout.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assert [row["id"] for row in rows] == ["hq_0001", "hq_0002"], "id 必须连续重编号"
    assert (tmp_path / "holdout.cards.json").exists()
    assert json.loads((tmp_path / "holdout.cards.covered.json").read_text(encoding="utf-8")) \
        == ["gen_cine_0001", "gen_cine_0002"]
    assert report["cards_missing"] == ["gen_cine_0003"], "没覆盖到的卡要如实报出来"


def test_merge_dry_run_writes_nothing(tmp_path):
    shard = _write(tmp_path / "partial0.jsonl",
                   [_entry("gen_cine_0001", "情绪=荒诞",
                           ["EMOTION_PACK:emotion=荒诞,intensity=high"])])
    out = tmp_path / "holdout.jsonl"
    report = holdout_merge.run([str(shard)], out, dry_run=True, cards=["gen_cine_0001"])
    assert report["dry_run"] is True and report["valid"] == 1
    assert not out.exists() and not out.with_suffix(".cards.json").exists()


def test_merge_expands_directories_and_rejects_unknown_inputs(tmp_path):
    directory = tmp_path / "shards"
    directory.mkdir()
    _write(directory / "partial0.jsonl",
           [_entry("gen_cine_0001", "情绪=荒诞",
                   ["EMOTION_PACK:emotion=荒诞,intensity=high"])])
    assert [path.name for path in holdout_merge.expand([str(directory)])] == ["partial0.jsonl"]
    assert [path.name for path in
            holdout_merge.expand([str(directory / "partial*.jsonl")])] == ["partial0.jsonl"]
    assert holdout_merge.expand([str(tmp_path / "nope.jsonl")]) == []


def test_merge_main_returns_nonzero_when_nothing_valid(tmp_path, capsys):
    broken = _write(tmp_path / "partial0.jsonl",
                    [_entry("gen_cine_0001", "情绪=荒诞", ["NOPE:emotion=荒诞"])])
    code = holdout_merge.main(["--inputs", str(broken),
                               "--out", str(tmp_path / "holdout.jsonl")])
    assert code == 1
    assert json.loads(capsys.readouterr().out.splitlines()[0])["valid"] == 0


def test_merge_refuses_to_invent_cards_it_was_not_given(tmp_path):
    """`--cards` 是"这次要求标注的全量"；不给就用运行时的语料全集。"""
    shard = _write(tmp_path / "partial0.jsonl",
                   [_entry("gen_cine_0001", "情绪=荒诞",
                           ["EMOTION_PACK:emotion=荒诞,intensity=high"])])
    report = holdout_merge.run([str(shard)], tmp_path / "holdout.jsonl",
                               cards=["gen_cine_0001", "gen_cine_0009"])
    assert report["cards"] == 2 and report["cards_covered"] == 1
    assert report["cards_missing"] == ["gen_cine_0009"]
    assert report["ghost_cards"] == []
