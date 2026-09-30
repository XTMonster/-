"""oracle 精准剔除工具（`tools/knowledge/prune_holdout.py`）的对拍测试。

它只做一件事：把**断言了不可能存在的边**的条目摘掉（判据直接来自
`check_holdout.validate_entry`，不另写一套）。测试要证明它：
① 摘掉非法成员条目；② 不动合法条目；③ 重新编号连续。
"""

from __future__ import annotations

import json
import pathlib

from tools.knowledge import prune_holdout


def _entry(ident: str, spec: str, q: str = "情绪=荒诞；强度=high") -> dict:
    return {"id": ident, "from_card": "gen_cine_0001", "q": q, "must": [spec],
            "top1": [spec], "never": [],
            "annotator": {"model_id": "m", "family": "zhipu", "model_version": "v"},
            "independence": "strong"}


def test_prune_drops_illegal_members_and_keeps_the_rest():
    legal = _entry("hq_0001", "EMOTION_PACK:emotion=荒诞,intensity=high")
    illegal = _entry("hq_0002", "AXIS_RULE:pair=any_two,axis_side=left,camera_angle=骑轴",
                     q="轴线=关系轴")
    kept, dropped = prune_holdout.prune([legal, illegal])
    assert [entry["id"] for entry in kept] == ["hq_0001"]
    assert len(dropped) == 1 and dropped[0]["id"] == "hq_0002"
    assert "camera_angle" in dropped[0]["reason"]


def test_prune_renumbers_contiguously(tmp_path):
    rows = [_entry("hq_0007", "EMOTION_PACK:emotion=荒诞,intensity=high"),
            # `q` 必须与自己的 `must` 同 kind 同取值——否则会被"q 与 must 不一致"
            # 那条判据（正确地）拦下，测的就不是"重新编号"了。
            _entry("hq_0011", "EMOTION_PACK:emotion=感激,intensity=low",
                   q="情绪=感激；强度=low")]
    path = tmp_path / "holdout.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    report = prune_holdout.run(path, cards=["gen_cine_0001"])
    assert report["kept"] == 2 and report["dropped"] == 0
    written = [json.loads(line) for line in
               path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["id"] for row in written] == ["hq_0001", "hq_0002"], "id 必须连续"
    assert (tmp_path / "holdout.cards.json").is_file()
    assert (tmp_path / "holdout.cards.covered.json").is_file()


def test_prune_dry_run_writes_nothing(tmp_path):
    path = tmp_path / "holdout.jsonl"
    path.write_text(json.dumps(_entry("hq_0001", "NOPE:emotion=荒诞"), ensure_ascii=False)
                    + "\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    report = prune_holdout.run(path, write=False)
    assert report["dropped"] == 1
    assert path.read_text(encoding="utf-8") == before
