"""真实剧本的**另一种写法**必须被同一个解析器认出来（v1.5）。

验收基准是用户 2026-10-08 交来的那份真实剧本 `码头市场_电影级分镜_v10.docx`
（docx sha256 `904e4f8d6d9009d5…`）的前四个节点，逐字抽成
`fixtures/shotlist_market_v10_nodes1_4.txt`（sha256 `8c62f20a396256d6…`，
**只做了 docx→txt 的抽取，没有改一个字**）。它与 `shotlist_market.md` 同源但是
**另一套排版**，v1.4 的解析器在这套排版上会**静默降级**：

| 写法 | 旧行为 | 后果 |
|---|---|---|
| ``**节点1：风起·定场与出场**（12s）`` | 不认（要求 `节点` 紧跟在行首的可选 `#` 之后） | 4 个节点塌成 1 个场景 |
| ``预估时长：5s`` | 不认（只认 `秒`） | 13 个镜号的**声明时长全部丢失**，模型自行重排时长 |
| ``台词："…"（2.75s）`` | 把行首那两个字当成一个叫"台词"的角色 | 说话人集合 = {台词}，`角色：米迦尔` 被整条过滤掉 ⇒ **13 个镜号零角色** |
| ``角色：米迦尔（尾巴…，尾尖…）`` | 括注里的逗号被当成分隔符 | 该镜的声明角色整条丢掉 |

四条都不是"容错与否"的口味问题：前两条丢掉导演写死的时长，后两条丢掉**出场角色**。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from block_director.layer1_input import looks_like_shot_list, parse_script

ROOT = Path(__file__).resolve().parents[1]
V10 = ROOT / "fixtures" / "shotlist_market_v10_nodes1_4.txt"


def _v10():
    return parse_script(V10)


def test_the_fixture_is_the_verbatim_slice_of_the_real_script():
    """夹具是"用户剧本的前四节点"，不是手写的样例——哈希钉住它。"""
    assert hashlib.sha256(V10.read_bytes()).hexdigest() == (
        "8c62f20a396256d65fb446ae55c03b5b458ef8967b75847403e00d48d4616c79")


def test_the_v10_spelling_is_recognised_as_a_shot_list():
    assert looks_like_shot_list(V10.read_text(encoding="utf-8"))
    assert _v10().source_format == "shotlist"


def test_four_nodes_and_thirteen_shots_survive_the_bold_node_header():
    script = _v10()
    assert [node.node_number for node in script.declared_nodes] == [1, 2, 3, 4]
    assert [shot.shot_number for shot in script.declared_shots] == list(range(1, 14))
    assert len(script.scenes) == 4
    assert [node.declared_seconds for node in script.declared_nodes] == \
        [12.0, 18.0, 22.0, 18.0]


def test_declared_seconds_are_read_from_the_s_suffix():
    """``预估时长：5s`` 与 ``预估时长：5秒`` 是同一个声明。"""
    shots = {shot.shot_number: shot for shot in _v10().declared_shots}
    assert [shots[n].declared_seconds for n in range(1, 14)] == \
        [5.0, 4.0, 4.0, 5.0, 3.0, 9.0, 4.0, 8.0, 4.0, 6.0, 6.0, 8.0, 3.0]
    assert _v10().declared_total_seconds == pytest.approx(69.0)


def test_line_dialogues_take_their_speaker_from_the_role_field():
    """``台词："…"`` 的说话人写在「角色」字段里——不许认成"台词"这个角色。"""
    script = _v10()
    assert "台词" not in script.character_names
    assert sorted(script.character_names) == \
        sorted(["米迦尔", "伊恩", "偷盗者", "莉莉安娜"])
    shots = {shot.shot_number: shot for shot in script.declared_shots}
    assert [(d.character, d.text[:6]) for d in shots[2].dialogues] == \
        [("米迦尔", "伊恩，这里就")]
    assert [d.character for d in shots[4].dialogues] == ["米迦尔", "米迦尔"]
    assert [d.character for d in shots[11].dialogues] == ["莉莉安娜"]
    assert [d.character for d in shots[12].dialogues] == ["伊恩"]
    assert script.dialogue_count == 9


def test_every_shot_declares_the_cast_the_script_wrote():
    """零角色是最要命的那种降级：白模里会**没有人**。"""
    shots = {shot.shot_number: shot for shot in _v10().declared_shots}
    assert shots[2].characters == ["米迦尔"]
    assert shots[3].characters == ["伊恩"]
    assert shots[4].characters == ["米迦尔"]        # 括注里有逗号，仍是一个角色
    assert shots[6].characters == ["偷盗者"]
    assert shots[13].characters == ["莉莉安娜", "伊恩"]
    assert shots[1].characters == []                # 「无角色出场；背景中路人1-3…」


def test_node_total_gaps_are_reported_not_hidden():
    """用户剧本里 13s 取整成 12s 这类差值要**说出来**，不是悄悄抹平。"""
    warnings = [w for w in _v10().warnings if "各镜声明之和" in w]
    assert len(warnings) == 3
    assert all(node in warnings[0] for node in ("节点 1", "12", "13"))


def test_the_old_spelling_still_parses_identically():
    """负对照：`shotlist_market.md`（``米迦尔（自信）："…"`` 那种写法）一个数不变。"""
    script = parse_script(ROOT / "fixtures" / "shotlist_market.md")
    assert script.declared_total_seconds == pytest.approx(33.0)
    assert len(script.declared_shots) == 6
    assert sorted(script.character_names) == sorted(["米迦尔", "伊恩", "偷盗者"])
    assert script.warnings == []
