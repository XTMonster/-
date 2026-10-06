"""`tools/relay_adaptive.py`：**让 GPT-6A 自适应吃下比一次能喂的更大**的材料。

起因（2026-10-06 用户："四五万字符不行么？……**我是说让 gpt6A 自适应**"）：
实测包线是 **5,309 B 可用 / 17.5 KB 死亡**，所以"把常数改大"是错的解法，
**分块**才是。这里守住三件事——① 切块不丢内容；② 块太大被拒时**自适应对半切**；
③ 切到下限还失败时**如实报失败**，不静默丢弃。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import relay_adaptive as ra  # noqa: E402


def _client(max_ok_chars):
    """块超过 `max_ok_chars` 就抛（模拟"包太大 ⇒ 超时/空正文"）。"""
    seen = []

    def call(messages, *, model, max_tokens, levels, temperature, timeout):
        body = messages[-1]["content"]
        seen.append(len(body))
        if len(body) > max_ok_chars:
            raise RuntimeError("too big")
        return ("要点-" + str(len(seen)), {"model": model, "usage": {}})

    call.seen = seen
    return call


def test_split_chunks_respects_the_budget_and_keeps_every_paragraph():
    text = "\n\n".join("第%d段：" % i + "内容" * 40 for i in range(20))
    chunks = ra.split_chunks(text, 500)
    assert len(chunks) > 1, "20 段 x ~85 字符在 500 的预算下必须被切开"
    assert all(len(c) <= 500 for c in chunks), "没有一块可以超过预算"
    joined = "".join(chunks)
    for i in range(20):
        assert ("第%d段：" % i) in joined, "第 %d 段在切块里丢了" % i


def test_a_single_oversized_paragraph_is_hard_split_not_dropped():
    """单段本身就超预算时**硬切**（而不是丢掉）——不静默丢内容。"""
    chunks = ra.split_chunks("甲" * 2500, 600)
    assert all(len(c) <= 600 for c in chunks)
    assert "".join(chunks) == "甲" * 2500, "硬切也要一字不丢"


def test_it_halves_a_rejected_chunk_until_it_fits():
    """自适应：块被拒 ⇒ **对半切重试**，直到装得下。"""
    call = _client(max_ok_chars=700)
    result = ra.adaptive_consult("问题？", ["乙" * 4000], budget=1000,
                                 consult_fn=call, model="m", max_tokens=64,
                                 temperature=0.2, timeout=1.0)
    assert not result["failures"], "缩块之后应当全部成功"
    failed = [c for c in result["calls"] if not c["ok"]]
    assert failed, "至少要有一块先被拒过（否则这条用例没测到缩块）"
    assert result["answer"], "最后必须给出答复"
    assert [c["kind"] for c in result["calls"]][-1] == "final"


def test_it_reports_failure_instead_of_pretending_when_even_the_floor_fails():
    """切到下限（`MIN_CHUNK`）还失败 ⇒ **如实报失败**，答复为空、失败列非空。"""
    call = _client(max_ok_chars=10)
    result = ra.adaptive_consult("问题？", ["丙" * 900], budget=600,
                                 consult_fn=call, model="m", max_tokens=64,
                                 temperature=0.2, timeout=1.0)
    assert result["failures"], "到底还是失败就必须报出来"
    assert result["answer"] == "", "失败时不许编一个答复"


def test_the_final_call_sees_every_chunks_notes():
    """最后那次调用必须**看得见每一块的要点**（否则分块就等于丢材料）。"""
    seen_final = {}

    def call(messages, *, model, max_tokens, levels, temperature, timeout):
        body = messages[-1]["content"]
        if "从长材料各块里摘出的要点" in body:
            seen_final["body"] = body
        return "要点", {"model": model, "usage": {}}

    ra.adaptive_consult("问题？", ["丁" * 1500, "戊" * 1500], budget=800,
                        consult_fn=call, model="m", max_tokens=64,
                        temperature=0.2, timeout=1.0)
    body = seen_final.get("body", "")
    assert body, "必须真的发过 final 调用"
    assert body.count("要点") >= 2, "各块的要点都要进去（这里两块 ⇒ 至少 2 次出现）"


class _ChannelDead(SystemExit):
    """模拟本仓通道的报错方式：`glm_consult.ConsultFailed` 就是 `SystemExit` 的子类。"""


def test_a_systemexit_from_the_channel_is_recorded_not_swallowed():
    """`SystemExit` 必须被**接住并记账**——漏掉它，`answer.md` / `calls.json` 一个都不会落盘。

    这是 2026-10-06 的现场（`docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md` P14-294）：
    一次"直接喂大包"的裁决请求跑了 ~70 分钟，**进程没了、产物 0 字节、stdout 也 0 字节**，
    谁都不知道它为什么停。同仓的 `plan_writer.py` / `panel_consult.py` 早就改成
    `except (Exception, SystemExit)`，`relay_adaptive.py` 这一处是漏网的。
    """
    attempts = []

    def call(messages, *, model, max_tokens, levels, temperature, timeout):
        attempts.append(len(messages[-1]["content"]))
        raise _ChannelDead("中转站没给出正文：通道挂了")

    result = ra.adaptive_consult("问题？", ["己" * 900], budget=600,
                                 consult_fn=call, model="m", max_tokens=64,
                                 temperature=0.2, timeout=1.0)
    assert result["failures"], "通道报错必须进 failures（不许穿出去、不许当成成功）"
    assert result["answer"] == "", "没拿到正文就不许编一个答复"
    assert result["calls"], "每一次尝试都要留在 calls 里（含错误原文）"
    assert "_ChannelDead" in result["calls"][0]["error"], (
        "错误类型要具名写出来（这里记的是**具体子类名**，不是笼统的 SystemExit）")
    assert attempts, "确实调用过通道"


def test_main_writes_artifacts_even_when_the_channel_is_dead(tmp_path):
    """同上的**端到端**形态：通道全死时 `main()` 仍要落 `answer.md` / `calls.json` 并以非零退出。"""
    question = tmp_path / "q.md"
    question.write_text("问题？", encoding="utf-8")
    material = tmp_path / "m.md"
    material.write_text("庚" * 3000, encoding="utf-8")
    out = tmp_path / "out"

    def dead(*args, **kwargs):
        raise _ChannelDead("中转站没给出正文：通道挂了")

    import tools.plan_writer as pw

    original = pw.choose_channel
    pw.choose_channel = lambda provider, model: ("fake-model", dead)
    try:
        code = ra.main(["--question", str(question), "--material", str(material),
                        "--provider", "relay", "--out", str(out),
                        "--max-prompt-chars", "400", "--timeout", "1"])
    finally:
        pw.choose_channel = original
    assert code == 1, "有失败就必须非零退出"
    assert (out / "calls.json").is_file(), "就算通道全死，现场也要留下 calls.json"
    assert (out / "answer.md").is_file(), "answer.md 也要落（内容为空是如实的）"
    assert (out / "answer.md").read_text(encoding="utf-8") == ""
