"""`source_kind` 按**知识形态**判（§2.3b 的 L2 经验层）。

缺陷形状（2026-10-02 实测）：738 条边的 `source_kind=experience` 是 **0 条**。
成因不是抽取器不听话，而是提示给每张卡塞了一句假的"来源性质：theory"——
1981 张生成卡**全部**没有这个字段，`card.get('source_kind', 'theory')` 恒为 theory。
后果：`E3 经验越权率` 分母为 0，按 §4.1b 硬规则 1 直接判**失败**。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import source_kind_audit as SK  # noqa: E402


def _atoms(tmp_path, *rows) -> pathlib.Path:
    path = tmp_path / "atoms.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return path


def _atom(card: str, *, forbid: bool = False) -> dict:
    members = [["allow", "emotion", "emotion:荒诞"],
               ["qualifier", "intensity", "intensity:high"]]
    if forbid:
        members.append(["forbid", "movement", "movement:固定"])
    return {"record": "edge", "edge_id": "hg:x", "type": "EMOTION_PACK",
            "sources": [card], "members": members, "source_kind": "theory",
            "hardness": "hard"}


def test_a_tradeoff_card_becomes_soft_experience(tmp_path):
    """条件→取舍的卡 → `experience`＋`soft`。"""
    path = _atoms(tmp_path, _atom("c1"))
    result = SK.apply(path, {"c1": {"form": "tradeoff", "quote": "", "reason": ""}})
    row = json.loads(path.read_text(encoding="utf-8").split("\n")[0])
    assert (row["source_kind"], row["hardness"]) == ("experience", "soft")
    assert result["by_kind"]["experience"] == 1


def test_a_tradeoff_that_states_a_prohibition_becomes_lesson(tmp_path):
    """**关键纪律 1**：经验不得越权——带 `forbid` 的取舍只能记成 `lesson`（仍是软边）。"""
    path = _atoms(tmp_path, _atom("c1", forbid=True))
    SK.apply(path, {"c1": {"form": "tradeoff", "quote": "", "reason": ""}})
    row = json.loads(path.read_text(encoding="utf-8").split("\n")[0])
    assert (row["source_kind"], row["hardness"]) == ("lesson", "soft")
    assert any(m[0] == "forbid" for m in row["members"]), "lesson 允许带 forbid"


def test_a_pure_constraint_stays_hard_theory(tmp_path):
    """正对照：普遍规则仍是 `theory`＋`hard`，别把整库都变成经验。"""
    path = _atoms(tmp_path, _atom("c2"), _atom("c3", forbid=True))
    decisions = {"c2": {"form": "constraint", "quote": "", "reason": ""},
                 "c3": {"form": "constraint", "quote": "", "reason": ""}}
    result = SK.apply(path, decisions)
    rows = [json.loads(l) for l in
            path.read_text(encoding="utf-8").split("\n") if l.strip()]
    assert all(r["source_kind"] == "theory" and r["hardness"] == "hard" for r in rows)
    assert result["by_kind"]["theory"] == 2


def test_the_classifier_never_invents_a_form_and_defaults_to_constraint(tmp_path):
    """模型漏答／给出非法取值时按 `constraint` 计，绝不默认成经验（宁缺勿滥）。"""
    class _Stub:
        model_id = "stub"

        def chat_json(self, system, user, temperature, seed, num_ctx, retries=3):
            return {"decisions": [{"id": "c1", "form": "maybe", "quote": "", "reason": ""}]}

    decisions = SK.classify([{"id": "c1", "title": "t", "content": "c"}], _Stub())
    assert decisions["c1"]["form"] == "constraint"

    class _Boom:
        model_id = "boom"

        def chat_json(self, *args, **kwargs):
            raise RuntimeError("nope")

    decisions = SK.classify([{"id": "c1", "title": "t", "content": "c"}], _Boom())
    assert decisions["c1"]["form"] == "constraint"
