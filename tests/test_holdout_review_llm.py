"""双模型复核（用户裁决）：三种分支 ＋ **绝不冒充人审**。

协议 §4.1b 把 Q5／Q7／E3 的最终裁定留给**人**（量的是作者意图）。用户明确指示这一层
让 DeepSeek 与 GLM 两个模型来判，于是本工具把复核者写成 `llm-panel`：门⑦ 照旧只认
`reviewed_by == "human"`，所以**验收标准没有被放宽**，只是多了一份辅助证据；
两模型都否决的条目被剔除，分歧条目留给人的清单通常只有几十条。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import holdout_review_llm as panel  # noqa: E402


def _entry(ident: str, card: str, *, forbid: bool = False) -> dict:
    slot = ",forbid_movement=固定" if forbid else ""
    spec = "EMOTION_PACK:emotion=荒诞,intensity=high" + slot
    return {"id": ident, "from_card": card, "q": "情绪=荒诞" + ("；运镜=固定" if forbid else ""),
            "must": [spec], "top1": [spec], "never": [],
            "expect_movements": ["甩镜"] if forbid else [],
            "annotator": {"model_id": "glm-4.7", "family": "zhipu",
                          "model_version": "glm-4.7", "prompt_sha256": "x"},
            "independence": "strong"}


def _write(tmp_path: pathlib.Path, rows) -> pathlib.Path:
    path = tmp_path / "entries.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return path


def test_both_accept_keeps_the_entry_and_labels_the_panel(tmp_path, monkeypatch):
    scripted = tmp_path / "a.json"
    scripted.write_text(json.dumps({"responses": {}}), encoding="utf-8")
    entries = _write(tmp_path, [_entry("hq_0001", "axis_180", forbid=True)])
    monkeypatch.setattr(panel, "_judge",
                        lambda client, entry, card: {"verdict": "accepted", "reason": "ok",
                                                     "fix": ""})
    out = tmp_path / "reviewed.jsonl"
    report = tmp_path / "panel.json"
    rc = panel.main(["--entries", str(entries), "--limit", "5",
                     "--scripted-a", str(scripted), "--scripted-b", str(scripted),
                     "--out", str(out), "--report", str(report),
                     "--sheet", str(tmp_path / "sheet.md")])
    assert rc == 0
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["review"]["verdict"] == "accepted"
    assert row["review"]["reviewed_by"] == panel.PANEL_TAG
    assert "human" not in json.dumps(row["review"], ensure_ascii=False)


def test_both_reject_drops_the_entry(tmp_path, monkeypatch):
    scripted = tmp_path / "a.json"
    scripted.write_text(json.dumps({"responses": {}}), encoding="utf-8")
    entries = _write(tmp_path, [_entry("hq_0001", "axis_180", forbid=True),
                               _entry("hq_0002", "axis_180")])
    monkeypatch.setattr(panel, "_judge",
                        lambda client, entry, card: (
                            {"verdict": "rejected", "reason": "卡里没这条", "fix": ""}
                            if entry["id"] == "hq_0001"
                            else {"verdict": "accepted", "reason": "ok", "fix": ""}))
    out = tmp_path / "reviewed.jsonl"
    rc = panel.main(["--entries", str(entries), "--limit", "5",
                     "--scripted-a", str(scripted), "--scripted-b", str(scripted),
                     "--out", str(out), "--report", str(tmp_path / "panel.json"),
                     "--sheet", str(tmp_path / "sheet.md")])
    assert rc == 0
    ids = [json.loads(line)["id"] for line in out.read_text(encoding="utf-8").splitlines()
           if line.strip()]
    assert ids == ["hq_0002"], "两模型一致否决的条目必须被剔除"


def test_disagreement_is_flagged_and_listed_for_a_human(tmp_path, monkeypatch):
    scripted = tmp_path / "a.json"
    scripted.write_text(json.dumps({"responses": {}}), encoding="utf-8")
    entries = _write(tmp_path, [_entry("hq_0007", "axis_180", forbid=True)])
    calls = {"n": 0}

    def judge(client, entry, card):
        calls["n"] += 1
        return ({"verdict": "accepted", "reason": "A 认为可以", "fix": ""} if calls["n"] == 1
                else {"verdict": "rejected", "reason": "B 说不支持", "fix": ""})

    monkeypatch.setattr(panel, "_judge", judge)
    out = tmp_path / "reviewed.jsonl"
    sheet = tmp_path / "sheet.md"
    rc = panel.main(["--entries", str(entries), "--limit", "5",
                     "--scripted-a", str(scripted), "--scripted-b", str(scripted),
                     "--out", str(out), "--report", str(tmp_path / "panel.json"),
                     "--sheet", str(sheet)])
    assert rc == 0
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["review"]["agreement"] is False
    assert row["review"]["needs_human"] is True
    text = sheet.read_text(encoding="utf-8")
    assert "hq_0007" in text and "A 认为可以" in text and "B 说不支持" in text


def test_merge_never_emits_a_human_reviewer():
    for a, b in ((("accepted"), ("accepted")), (("rejected"), ("rejected")),
                 (("accepted"), ("rejected"))):
        _action, review = panel.merge({"verdict": a}, {"verdict": b})
        assert review["reviewed_by"] == panel.PANEL_TAG != "human"


def test_selector_never_re_judges_an_entry_that_already_has_a_record():
    """复核必须**幂等**：已经有裁决记录的条目不重判。

    为什么这条重要：复核会**剔除**条目，而剔除会牵动别的门——实测第一趟把
    44 条一致否决的条目剔掉之后，门③ 的 `movement=track_left` 掉到 2 个支撑
    （低于线 3），补跑一轮才回来。于是"补齐新条目"这件事必须能**只判新增的**：
    否则第二趟会把上一趟裁过的条目重判一遍，同一对模型对同一条期望给出不同
    结论时，"哪一份记录为准"就没有答案了；而且可能再剔一次，门③ 再掉一次。
    """
    fresh = _entry("hq_0001", "card_a", forbid=True)
    judged = dict(_entry("hq_0002", "card_b", forbid=True),
                  review={"reviewed_by": "llm-panel", "verdict": "amended",
                          "agreement": False, "needs_human": True})
    clean = _entry("hq_0003", "card_c")

    picked = panel.select([fresh, judged, clean], 0)
    assert [item["id"] for item in picked] == ["hq_0001"]

    # 正对照：去掉那条记录，同一条就会被重新选中（不是"永远跳过"）。
    again = dict(judged)
    again.pop("review")
    assert [item["id"] for item in panel.select([again], 0)] == ["hq_0002"]
