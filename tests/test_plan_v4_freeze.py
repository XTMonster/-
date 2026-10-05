"""P0 的守门：用户 U6 要求的**三循环**真的走完了，而且证据在库里。

用户原话（2026-10-05）："**开始之前**你先用 glm5.3 写执行计划，然后对抗性审查，
一共循环三遍再开始"。所以"三循环收口"是**开工的前置条件**，它必须在机器上可判——
不能靠"我记得跑过了"。本文件钉三件事：

1. 三个循环各自的**审查产物**与**处置/修订产物**都在库里；
2. 循环 2／3 的审查是**双侧**的（DeepSeek × GLM-5.3 都出了正文，
   即判词文件里 `reviewed_by: llm-panel` 且 `complete: true`）；
3. 收口决议里**如实记账**了那次截断（`finish_reason=length` 的处置稿
   **不整段采纳**）——"缺证据不得判通过"这条纪律对计划流程自己一样适用。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KNOWLEDGE = ROOT / "docs" / "knowledge"

#: 三循环的产物（循环 1 的"审查"由主线核对承担，它的产物是一个 critique 文件，
#: 不在 docs/ 里——那一条只在决议表里记名，不在这里当文件断言）。
LOOP2_REVIEW = KNOWLEDGE / "PLAN_V4_REVIEW_LOOP2.md"
LOOP2_DISPOSITION = KNOWLEDGE / "PLAN_V4_LOOP2_DISPOSITION.md"
LOOP3_REVIEW = KNOWLEDGE / "PLAN_V4_REVIEW_LOOP3.md"
LOOP3_REVISIONS = KNOWLEDGE / "PLAN_V4_LOOP3_REVISIONS.md"
PLAN = KNOWLEDGE / "PLAN_HYPERGRAPH_v4.md"
ADJUDICATIONS = KNOWLEDGE / "ADJUDICATIONS_v4.md"
CORPUS = KNOWLEDGE / "CORPUS_V4.md"


def test_every_loop_artifact_is_in_the_repository():
    for path in (LOOP2_REVIEW, LOOP2_DISPOSITION, LOOP3_REVIEW, LOOP3_REVISIONS,
                 PLAN, ADJUDICATIONS, CORPUS):
        assert path.is_file(), "缺 %s" % path.relative_to(ROOT)


def test_loop_reviews_are_two_sided_both_models_produced_text():
    """一侧缺席永远不算同意：两份审查都必须记 `reviewed_by: llm-panel` 且双侧 ok。"""
    for path in (LOOP2_REVIEW, LOOP3_REVIEW):
        text = path.read_text(encoding="utf-8")
        assert "reviewed_by: llm-panel" in text, path.name
        for side in ("deepseek=`ok`", "glm=`ok`"):
            assert side in text, "%s 缺 %s" % (path.name, side)


def test_loop2_panel_json_says_complete():
    payload = json.loads(
        (ROOT / "work" / "_review_loop2" / "panel.json").read_text(encoding="utf-8")) \
        if (ROOT / "work" / "_review_loop2" / "panel.json").is_file() else None
    if payload is None:
        return  # 草稿区（work/）不入库；缺它不算失败，README 里记着它在哪
    assert payload.get("complete") is True


def test_the_truncated_disposition_is_recorded_not_silently_adopted():
    """循环 3 的处置稿被截断 ⇒ 决议必须写明"不整段采纳"。"""
    text = LOOP3_REVISIONS.read_text(encoding="utf-8")
    assert "finish_reason=length" in text
    assert "不整段采用" in text or "不整段采纳" in text


def test_the_five_numeric_blanks_are_still_listed_as_open():
    """数值型留白不许被悄悄填掉：它们必须仍然以"留白/待裁"出现。"""
    text = LOOP3_REVISIONS.read_text(encoding="utf-8")
    section = text.split("仍然留白的数值", 1)
    assert len(section) == 2, "决议里找不到'仍然留白的数值'那一节"
    blanks = re.findall(r"^\| N[1-5] ", section[1], flags=re.M)
    assert len(blanks) == 5, "留白条数不是 5：%s" % blanks


def test_the_plan_still_declares_itself_unfinished():
    """计划里必须仍写着"循环 3 未做"这类如实状态，不许被改成已完成。

    注意：这份 `plan.md` 是 `tools/plan_writer.py` 的**原样产物**，它的开头是
    那一轮的精炼报告、正文在 60 行之后——所以这里按**全文**找，不切片。
    """
    text = PLAN.read_text(encoding="utf-8")
    assert "三循环" in text, "计划里没有三循环的进度说明"
    assert "循环 3 未做" in text, "计划里没有如实标注'循环 3 未做'"


def test_the_binding_annex_exists_and_declares_precedence():
    """P1 的动作产物：V1-V9 的修订必须有一份**有约束力**的附件，并写明优先级。"""
    annex = KNOWLEDGE / "PLAN_HYPERGRAPH_v4_ANNEX.md"
    assert annex.is_file(), "缺 %s（P1：把 V1-V9 写进计划）" % annex.name
    text = annex.read_text(encoding="utf-8")
    assert "以本附件为准" in text, "附件没有声明与正文冲突时的优先级"
    for tag in ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9"):
        assert ("**%s**" % tag) in text or ("| %s " % tag) in text, "附件缺 %s" % tag
