"""案例摘录要挑**讲拍法的正文句**，不能挑到标题/导航碎片。

实测（2026-10-02，E1 的同语言对照）：旧口径"取每段开头 1–2 句"在网页语料上稳定地
取到样板文字——

* `TV Writing and Development / We're in a golden age of TV writing…`（StudioBinder 的
  面包屑 + 导语）；
* `MEDIUM CLOSE-UP SHOT DEFINITION / What is a medium close-up shot?`（小标题 +
  定义问句）。

双模型面板给这两条 1–2 分（"没有参考价值"）。这与 §24.2 修掉的"OCR 说明文字当 excerpt"
是同一形状，修法也一样：**别取段首，按内容打分选窗**。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import build_cases as BC  # noqa: E402

STUDIOBINDER_NAV = (
    "TV Writing and Development\n\n"
    "We're in a golden age of TV writing and development. More and more people are "
    "flocking to streaming platforms to see how their favorite shows come together."
)

STUDIOBINDER_DEFINITION = (
    "MEDIUM CLOSE-UP SHOT DEFINITION\n\n"
    "What is a medium close-up shot? A medium close-up shot frames a character from "
    "the chest up and is used to show their emotional state without losing context."
)

ANALYSIS = (
    "You can also show the passage of time with establishing shots. A slow dolly in "
    "on the market tells the audience that the place matters before anyone speaks."
)


def test_a_breadcrumb_plus_lede_is_not_picked_over_the_body():
    """面包屑 + 导语 ≠ 分析句：要么不选它，要么选到真正讲拍法的那句。"""
    picked = BC.pick_excerpt(STUDIOBINDER_NAV)
    assert picked is not None
    assert "TV Writing and Development" not in picked


def test_an_all_caps_heading_and_its_definition_question_are_avoided():
    picked = BC.pick_excerpt(STUDIOBINDER_DEFINITION)
    assert picked is not None
    assert "MEDIUM CLOSE-UP SHOT DEFINITION" not in picked
    assert not picked.strip().lower().startswith("what is")


def test_the_craft_sentence_wins_even_when_it_is_not_first():
    """段首是标题、正文在后面 ⇒ **选正文**（不是标题）。

    真实性质只有这一条："摘录必须来自正文"。至于正文里选定义句还是选分析句，
    打分是"长度优先 + 创作动词加分"，**不保证**一定是对分析句——那是下一步
    （要是将来做，应该用更细的判据，而不是把这条用例写成它的代理）。
    """
    segment = STUDIOBINDER_DEFINITION + "\n\n" + ANALYSIS
    picked = BC.pick_excerpt(segment)
    assert picked is not None
    assert "MEDIUM CLOSE-UP SHOT DEFINITION" not in picked
    assert not picked.strip().lower().startswith("what is")
    body = STUDIOBINDER_DEFINITION.split("\n\n", 1)[1] + ANALYSIS
    assert picked in body, "摘录必须逐字来自正文"


def test_scoring_is_deterministic():
    first = BC.pick_excerpt(STUDIOBINDER_NAV + "\n\n" + ANALYSIS)
    second = BC.pick_excerpt(STUDIOBINDER_NAV + "\n\n" + ANALYSIS)
    assert first == second


def test_the_quote_still_has_to_be_verbatim():
    """打分不改约束：摘录必须逐字回指原文（拿不到就整段作废）。"""
    import pytest

    assert BC.pick_excerpt("") is None
    assert BC.pick_excerpt("短") is None
    picked = BC.pick_excerpt(ANALYSIS)
    assert picked and picked in ANALYSIS


def test_a_heading_alone_yields_nothing_rather_than_a_heading():
    """整段只有标题 ⇒ 宁可返回空（宁缺勿猜），也不要把标题当摘录。"""
    assert BC.pick_excerpt("CAMERA ANGLES") is None
    assert BC.pick_excerpt("What is a shot list?") is None
