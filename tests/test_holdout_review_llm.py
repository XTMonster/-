"""双模型复核（用户裁决）：三种分支 ＋ **绝不冒充人审**。

协议 §4.1b 把 Q5／Q7／E3 的最终裁定留给**人**（量的是作者意图）。用户明确指示这一层
让 DeepSeek 与 GLM 两个模型来判，于是本工具把复核者写成 `llm-panel`：门⑦ 照旧只认
`reviewed_by == "human"`，所以**验收标准没有被放宽**，只是多了一份辅助证据；
两模型都否决的条目被剔除，分歧条目留给人的清单通常只有几十条。
"""

from __future__ import annotations

import json
import datetime
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


# --------------------------------------------------------------------------- #
# 断点续跑（2026-10-03 加）：这一趟是**双模型 × 每一条 needs_human**，当前 157 条
# ⇒ ≥314 次调用，按实测是**小时级**。原实现只在全部跑完之后才写 `--out`，中途
# 429/断网/被杀就整趟白跑（§34.3 已经为同一形状付过一次代价）。
# --------------------------------------------------------------------------- #
def _run(tmp_path, entries, *, resume: bool, counter, monkeypatch):
    scripted = tmp_path / "a.json"
    scripted.write_text(json.dumps({"responses": {}}), encoding="utf-8")
    out = tmp_path / "reviewed.jsonl"

    def judge(client, entry, card):
        counter["n"] += 1
        return {"verdict": "accepted", "reason": "ok", "fix": ""}

    monkeypatch.setattr(panel, "_judge", judge)
    argv = ["--entries", str(entries), "--limit", "0",
            "--scripted-a", str(scripted), "--scripted-b", str(scripted),
            "--out", str(out), "--report", str(tmp_path / "panel.json"),
            "--sheet", str(tmp_path / "sheet.md")]
    if resume:
        argv += ["--resume", "1"]
    rc = panel.main(argv)
    assert rc == 0
    return out


def _freeze_clock(monkeypatch) -> None:
    """把 `ran_at`/`generated_at` 钉到固定时刻，让跨次运行的字节对拍确定。

    这两条时间戳是运行元数据，真实墙钟会让"同一批条目、同一批判决"的两趟
    运行在秒边界上字节不等——判据量的是并发/续跑不改变判决与顺序，
    不是运行发生在哪一秒。冻结时钟只移除环境噪声，断言本身一字未动。
    """

    class _Frozen(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime.datetime(2026, 10, 12, 12, 0, 0)
            return base if tz is None else base.replace(tzinfo=tz)

    monkeypatch.setattr(panel.datetime, "datetime", _Frozen)


def test_a_second_run_with_resume_re_judges_nothing(tmp_path, monkeypatch):
    """`--resume` 之后**一次模型调用都不该发生**，产物必须与第一趟一致。"""
    _freeze_clock(monkeypatch)
    entries = _write(tmp_path, [_entry("hq_0001", "axis_180", forbid=True),
                               _entry("hq_0002", "axis_180", forbid=True)])
    counter = {"n": 0}
    first = _run(tmp_path, entries, resume=False, counter=counter,
                 monkeypatch=monkeypatch)
    assert counter["n"] == 4, "两条 × 两个模型"
    before = first.read_text(encoding="utf-8")
    counter["n"] = 0
    second = _run(tmp_path, entries, resume=True, counter=counter,
                  monkeypatch=monkeypatch)
    assert counter["n"] == 0, "--resume 之后不许再调模型（那正是它存在的理由）"
    assert second.read_text(encoding="utf-8") == before

    # 负对照：不带 `--resume` 的同一条命令必须**重新判**（不是"永远跳过"）。
    counter["n"] = 0
    _run(tmp_path, entries, resume=False, counter=counter, monkeypatch=monkeypatch)
    assert counter["n"] == 4


def test_the_panel_records_which_prompt_version_judged_it(tmp_path, monkeypatch):
    """判据改一次，`prompt_sha256` 就变；把它和版本号一起写进记录。

    没有这两个字段，门⑦ 读到的"裁决记录"无法说明**是谁、按哪一版判据**判的——
    那正是 §4.1b 硬规则 2 禁止的自证形状。
    """
    entries = _write(tmp_path, [_entry("hq_0001", "axis_180", forbid=True)])
    counter = {"n": 0}
    out = _run(tmp_path, entries, resume=False, counter=counter,
               monkeypatch=monkeypatch)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    source = row["review"]["source"]
    assert source["prompt_version"] == panel.PROMPT_VERSION
    assert len(source["prompt_sha256"]) == 64
    assert len(set(source["models"])) == 2


def test_concurrency_does_not_change_the_result(tmp_path, monkeypatch):
    """`--concurrency N` 只改吞吐，不改产物。

    为什么值得钉：面板一趟是**小时级**（157 条 × 2 个模型，实测约 3 分钟/条），
    所以并发是必需项；但并发很容易顺手把"谁先判完谁先落盘"渗进产物里 —— 那样
    `--out` 的逐行顺序就会随网络抖动变化，链上的对拍与 `--resume` 都会漂。
    判据：同一批条目、同一批桩判决，串行与 6 并发的 `--out` **逐字节相同**。
    """
    _freeze_clock(monkeypatch)
    rows = [_entry(f"hq_{index:04d}", "axis_180", forbid=True)
            for index in range(1, 13)]
    entries = _write(tmp_path, rows)
    counter = {"n": 0}
    serial = _run(tmp_path, entries, resume=False, counter=counter,
                  monkeypatch=monkeypatch)
    baseline = serial.read_text(encoding="utf-8")
    assert counter["n"] == 24

    # 换一个目录跑 6 并发：产物必须与串行逐字节相同。
    other = tmp_path / "concurrent"
    other.mkdir()
    scripted = other / "a.json"
    scripted.write_text(json.dumps({"responses": {}}), encoding="utf-8")

    def judge(client, entry, card):
        counter["n"] += 1
        return {"verdict": "accepted", "reason": "ok", "fix": ""}

    monkeypatch.setattr(panel, "_judge", judge)
    counter["n"] = 0
    out = other / "reviewed.jsonl"
    rc = panel.main(["--entries", str(entries), "--limit", "0",
                     "--concurrency", "6",
                     "--scripted-a", str(scripted), "--scripted-b", str(scripted),
                     "--out", str(out), "--report", str(other / "panel.json"),
                     "--sheet", str(other / "sheet.md")])
    assert rc == 0
    assert counter["n"] == 24
    assert out.read_text(encoding="utf-8") == baseline
    # 进度文件也要齐：12 条，一条一行（并发不许丢行）。
    lines = [line for line in
             (other / "reviewed.jsonl.decisions.jsonl").read_text(
                 encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 12


def test_a_judge_error_is_retried_and_never_becomes_a_verdict(tmp_path, monkeypatch):
    """**模型报错不是判决**（2026-10-03 实测的真缺陷）。

    现场：177 条里 **92 条**记录是 `('accepted','error')` —— GLM 的
    `HTTP 429 code 1302`（速率限制）被旧的 `merge()` 按"分歧"处理，写成了
    `verdict:"amended"` ＋ `needs_human:true`。后果是分歧清单里 78% 是基础设施
    问题（人看它等于白看），而门⑦ 会把"模型挂了"数成"已复核"。

    现在：`error` ⇒ `retry`（不进记录、不进分歧清单）；整轮重试用尽仍失败就
    **没有记录**（缺证据不是通过）。这里让 B 侧第一次调用报错、重试时成功。
    """
    scripted = tmp_path / "a.json"
    scripted.write_text(json.dumps({"responses": {}}), encoding="utf-8")
    entries = _write(tmp_path, [_entry("hq_0001", "axis_180", forbid=True),
                               _entry("hq_0002", "axis_180", forbid=True)])
    state = {"calls": 0, "errors_left": 1}

    def judge(client, entry, card):
        state["calls"] += 1
        if entry["id"] == "hq_0002" and state["errors_left"]:
            state["errors_left"] -= 1
            return {"verdict": "error", "reason": "HTTP 429 code 1302", "fix": ""}
        return {"verdict": "accepted", "reason": "ok", "fix": ""}

    monkeypatch.setattr(panel, "_judge", judge)
    out = tmp_path / "reviewed.jsonl"
    rc = panel.main(["--entries", str(entries), "--limit", "0", "--retries", "1",
                     "--scripted-a", str(scripted), "--scripted-b", str(scripted),
                     "--out", str(out), "--report", str(tmp_path / "panel.json"),
                     "--sheet", str(tmp_path / "sheet.md")])
    assert rc == 0
    decisions = [json.loads(line) for line in
                 (tmp_path / "reviewed.jsonl.decisions.jsonl").read_text(
                     encoding="utf-8").splitlines() if line.strip()]
    assert [item["id"] for item in decisions] == ["hq_0001", "hq_0002"]
    assert all(item["review"]["verdict"] == "accepted" for item in decisions), (
        "报错被重试之后应当拿到真判决，而不是被写成 amended/needs_human")
    report = json.loads((tmp_path / "panel.json").read_text(encoding="utf-8"))
    assert report["unresolved"] == []


def test_merge_never_turns_an_error_into_a_disagreement():
    """单元级：`merge` 见到 `error` 只能回 `retry`，不许回 `flag`。"""
    for a, b in (({"verdict": "error"}, {"verdict": "accepted"}),
                 ({"verdict": "rejected"}, {"verdict": "error"}),
                 ({"verdict": "error"}, {"verdict": "error"})):
        action, review = panel.merge(a, b)
        assert action == "retry"
        assert review == {}, "没判出来就不许留下任何裁决字段"
