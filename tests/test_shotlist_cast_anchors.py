"""R2 空计划漏洞（final5）：分镜表解析必须收【角色锚】/【场景锚】声明。

真跑 20261020-market-real-final5：剧本含【角色锚】米迦尔/伊恩/偷盗者，
但 ``parse_text`` 走了 shotlist 路径，该路径此前不收集 cast_declarations，
``ParsedScript.character_names`` 返回 [] -> 计划提示丢角色 -> LLM 产出
characters=[] 空计划 -> 粗排门按空镜豁免放行 -> 细排构图 0.0。
本测试钉住：shotlist 与 fountain 两条路径对角色锚/场景锚同一口径。
"""

from __future__ import annotations

from block_director.layer1_input import parse_text


SHOTLIST_WITH_CAST = """节点1（约16s）

【角色锚】
米迦尔：兽人，具体种族由用户设定；只有四根手指，手部为带肉垫的兽爪。
伊恩：年轻男性，衣着朴素（暂定外观），全程保持外观一致。
偷盗者：身形瘦削的成年男性，穿旧外套（暂定外观），全程保持外观一致。

【场景锚】第十四街区码头市场，白天晴天，日光从画面深处的海面方向打来。

【衔接头】第十四街区码头市场：偷盗者站在画面右侧银币摊前，双手捧着金子；
米迦尔站在画面左侧生蚝摊旁，右手停在身侧；伊恩站在画面中左。

镜头 1（约4s）：
- 景别视角：近景，正面平视米迦尔。
- 主体动作：米迦尔看到金子，表情猛然僵住。

镜头 2（约4s）：
- 景别视角：特写，平视米迦尔面部。
- 主体动作：米迦尔脸色涨红，气得跺了一下脚。
- 音频：米迦尔（说）：{什么乱七八糟的，不应该是让钱出错然后爆炸么？}
"""


def test_shotlist_path_collects_cast_declarations():
    """分镜表路径：【角色锚】三个角色必须进 character_names。"""
    script = parse_text(SHOTLIST_WITH_CAST, title="market")
    assert script.source_format == "shotlist"
    assert "米迦尔" in script.cast_declarations
    assert "伊恩" in script.cast_declarations
    assert "偷盗者" in script.cast_declarations
    names = script.character_names
    assert names == ["米迦尔", "伊恩", "偷盗者"]


def test_shotlist_path_collects_scene_anchor_texts():
    """分镜表路径：【场景锚】原文必须进 scene_anchor_texts。"""
    script = parse_text(SHOTLIST_WITH_CAST, title="market")
    assert any("第十四街区码头市场" in text
               for text in script.scene_anchor_texts)


def test_fountain_and_shotlist_same_anchor_contract():
    """同一份剧本：fountain 与 shotlist 两路径对角色锚收同一批名字。"""
    from block_director.layer1_input.fountain import parse_fountain

    fountain_script = parse_fountain(SHOTLIST_WITH_CAST, title="market")
    shotlist_script = parse_text(SHOTLIST_WITH_CAST, title="market")
    assert fountain_script.cast_declarations == \
        shotlist_script.cast_declarations
