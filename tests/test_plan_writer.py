"""`tools/plan_writer.py` 的判据（全部离线，不联网、不碰真 key）。

为什么值得一组用例（2026-10-05 用户裁决）：

* **写执行计划走 GLM-5.3**，**默认自我精炼 5 次** —— "5 轮"必须是被断言的事实，
  不是文档里的一句话；
* **一轮失败不许丢已有成果**：失败轮要记录、要保留上一轮草案，最终稿必须是
  **最后一轮成功稿**；
* **先留证、再联网**：草案还没拿到，`bundle.manifest.json` 就得先落盘；
* **密钥只从环境变量读**：工具源码里不许出现任何 key 材料。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import glm_consult as gc  # noqa: E402
from tools import plan_writer as pw  # noqa: E402


def _fake(texts):
    """按调用序号返回 `texts`；元素是 Exception 就抛出来。"""
    calls = {"n": 0}

    def call(messages, *, model, max_tokens, levels, temperature, timeout):
        index = calls["n"]
        calls["n"] += 1
        item = texts[min(index, len(texts) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item, {"model": model, "level": levels[0], "elapsed_s": 0.1,
                      "finish_reason": "stop"}

    return call, calls


def _bundle(tmp_path):
    question = tmp_path / "q.md"
    question.write_text("把检索层重做一遍", encoding="utf-8")
    (tmp_path / "axis.py").write_text("def side():\n    return 'left'\n", encoding="utf-8")
    contract = tmp_path / "contract.md"
    contract.write_text("# 契约\n- 必须有 PRD/TDD\n", encoding="utf-8")
    return question, contract


def test_default_rounds_is_five():
    assert pw.DEFAULT_ROUNDS == 5, "默认自我精炼轮数必须固定为 5（用户裁决）"


def test_default_max_tokens_matches_the_glm_channel():
    """同一事实两个真源要机检：预算默认值必须与 `glm_consult` 的 CLI 默认一致。"""
    text = (ROOT / "tools" / "glm_consult.py").read_text(encoding="utf-8")
    match = re.search(r'"--max-tokens",\s*type=int,\s*default=(\d+)', text)
    assert match, "glm_consult 的 --max-tokens 默认值找不到了（口径漂了）"
    assert int(match.group(1)) == pw.DEFAULT_MAX_TOKENS


def test_missing_contract_fails_loudly(tmp_path):
    with pytest.raises(SystemExit) as info:
        pw.read_contract(tmp_path / "nope.md")
    assert "契约" in str(info.value)


def test_every_round_is_saved_and_the_last_round_wins(tmp_path):
    question, contract = _bundle(tmp_path)
    out = tmp_path / "plan"
    out.mkdir()
    texts = [f"DRAFT-{i}" for i in range(pw.DEFAULT_ROUNDS + 1)]
    call, calls = _fake(texts)

    result = pw.write_plan(contract.read_text(encoding="utf-8"),
                           question.read_text(encoding="utf-8"), [], [], "status", out,
                           model="glm-5.3", rounds=pw.DEFAULT_ROUNDS, levels=["low"],
                           max_tokens=10, temperature=0.2, timeout=1, consult_fn=call)

    assert calls["n"] == pw.DEFAULT_ROUNDS + 1, "一次起草 + 5 轮精炼"
    for index in range(1, pw.DEFAULT_ROUNDS + 1):
        assert (out / f"plan.round{index}.md").read_text(encoding="utf-8") == texts[index]
        assert (out / f"plan.round{index}.usage.json").is_file()
    final = (out / "plan.md").read_text(encoding="utf-8")
    assert texts[-1] in final, "最终稿必须是最后一轮成功稿"
    assert result["provenance"]["rounds_ok"] == pw.DEFAULT_ROUNDS + 1
    history = json.loads((out / "plan.refinements.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in history["history"]] == ["ok"] * 6


def test_a_failed_refinement_keeps_the_previous_draft(tmp_path):
    question, contract = _bundle(tmp_path)
    out = tmp_path / "plan"
    out.mkdir()
    #: 第 0 轮成功，之后每一轮都失败 —— 最终稿必须还是草案。
    call, _ = _fake(["DRAFT-BODY"] + [SystemExit("empty body")] * pw.DEFAULT_ROUNDS)

    result = pw.write_plan(contract.read_text(encoding="utf-8"),
                           question.read_text(encoding="utf-8"), [], [], "status", out,
                           model="glm-5.3", rounds=pw.DEFAULT_ROUNDS, levels=["low"],
                           max_tokens=10, temperature=0.2, timeout=1, consult_fn=call)

    final = (out / "plan.md").read_text(encoding="utf-8")
    assert "DRAFT-BODY" in final, "失败轮不许把已有成果丢掉"
    assert result["provenance"]["rounds_ok"] == 1
    history = json.loads((out / "plan.refinements.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in history["history"]] == ["ok"] + ["failed"] * 5
    assert all("empty body" in item.get("error", "") for item in history["history"][1:])


def test_draft_failure_is_fatal_but_evidence_is_written_first(tmp_path, monkeypatch):
    question, contract = _bundle(tmp_path)
    out = tmp_path / "plan"

    def boom(*_args, **_kwargs):
        raise SystemExit("no key in this test")

    monkeypatch.setattr(gc, "consult", boom)
    with pytest.raises(SystemExit):
        pw.main(["--question", str(question), "--source", "axis.py",
                 "--repo", str(tmp_path), "--contract", str(contract),
                 "--out", str(out), "--rounds", "1"])
    assert (out / "bundle.manifest.json").is_file(), "联网之前必须先留证"
    assert (out / "bundle.md").is_file()


def test_dry_run_writes_nothing_and_reports_the_plan_shape(tmp_path, capsys):
    question, contract = _bundle(tmp_path)
    out = tmp_path / "plan"
    code = pw.main(["--question", str(question), "--source", "axis.py",
                    "--repo", str(tmp_path), "--contract", str(contract),
                    "--out", str(out), "--dry-run"])
    assert code == 0
    assert not out.exists(), "dry-run 不许写盘"
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["rounds"] == pw.DEFAULT_ROUNDS
    assert payload["source_seen"] is True


def test_module_carries_no_key_material():
    text = (ROOT / "tools" / "plan_writer.py").read_text(encoding="utf-8")
    assert "sk-" not in text
    assert "83a18083" not in text, "用户给的 key 绝不许出现在仓库文件里"


def test_oversized_prompt_is_refused_before_any_call(tmp_path):
    """包线纪律：prompt 超预算要**在调用前**拒绝，不许烧十分钟换一个空正文。

    实测（2026-10-05）：5164 token 的输入在 `low` 档把 32768 个 completion token
    全烧在 reasoning 上、`finish_reason=length`、正文为空。
    """
    question, contract = _bundle(tmp_path)
    big = question.read_text(encoding="utf-8") + ("填充" * 3000)
    call, calls = _fake(["NEVER"])

    with pytest.raises(SystemExit) as info:
        pw.write_plan(contract.read_text(encoding="utf-8"), big, [], [], "status",
                      tmp_path / "plan", model="glm-5.3", rounds=1, levels=["low"],
                      max_tokens=10, temperature=0.2, timeout=1, consult_fn=call)

    message = str(info.value)
    assert calls["n"] == 0, "超预算必须在联网之前拒绝"
    for knob in ("--status-chars", "--context-tail", "--max-prompt-chars"):
        assert knob in message, f"拒绝理由要给出调法：缺 {knob}"


def test_prompt_budget_is_a_pure_function():
    assert pw.prompt_budget_error(100, 3000) is None
    assert pw.prompt_budget_error(3000, 3000) is None
    assert pw.prompt_budget_error(3001, 3000) is not None
    assert pw.prompt_budget_error(9999, 0) is None, "0 = 不限"


def test_a_truncated_round_is_not_promoted(tmp_path):
    """`finish_reason=length` 的一轮是半截稿，**不算成功、不许当最终稿**。

    实测（2026-10-05 烟测）：精炼轮的 32768 个 completion token 全烧在 reasoning 上
    （30397），正文只有半截，却被当成"成功"写进 plan.md。
    """
    question, contract = _bundle(tmp_path)
    out = tmp_path / "plan"
    out.mkdir()

    def call(messages, *, model, max_tokens, levels, temperature, timeout):
        call.n += 1
        if call.n == 1:                      # 草案：完整
            return "DRAFT-COMPLETE", {"model": model, "level": levels[0],
                                      "finish_reason": "stop"}
        return "HALF", {"model": model, "level": levels[0],
                        "finish_reason": "length"}   # 精炼：被截断

    call.n = 0
    result = pw.write_plan(contract.read_text(encoding="utf-8"),
                           question.read_text(encoding="utf-8"), [], [], "status", out,
                           model="glm-5.3", rounds=2, levels=["low"],
                           max_tokens=10, temperature=0.2, timeout=1, consult_fn=call)

    assert [item["status"] for item in result["history"]] == ["ok", "truncated",
                                                              "truncated"]
    final = (out / "plan.md").read_text(encoding="utf-8")
    assert "DRAFT-COMPLETE" in final and "HALF" not in final


def test_a_big_shrink_is_flagged(tmp_path):
    """精炼后大幅缩水要留痕（可能是把内容丢了），但不自动否决。"""
    question, contract = _bundle(tmp_path)
    out = tmp_path / "plan"
    out.mkdir()
    call, _ = _fake(["A" * 1000, "B" * 100])          # 缩到 10%

    result = pw.write_plan(contract.read_text(encoding="utf-8"),
                           question.read_text(encoding="utf-8"), [], [], "status", out,
                           model="glm-5.3", rounds=1, levels=["low"],
                           max_tokens=10, temperature=0.2, timeout=1, consult_fn=call)
    assert result["history"][1]["shrink"] is True
    assert result["history"][0].get("shrink", False) is False
