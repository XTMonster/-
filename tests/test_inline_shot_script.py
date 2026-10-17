from block_director.layer1_input.script_parser import parse_text


def test_inline_camera_script_keeps_declared_shot_timing_and_fields():
    text = """节点1（约16s）
镜头 1（约5s）：
- 景别视角：大远景，低机位平视。
- 构图：纵深引导线构图。
- 镜头运动：缓慢推近。
- 主体动作：米迦尔站立。
- 音频：无台词。
镜头 2（约4s）：
- 景别视角：中景，平视。
- 构图：三分法。
- 镜头运动：固定机位。
- 主体动作：伊恩站立。
- 音频：无台词。
"""
    parsed = parse_text(text, title="inline")
    assert parsed.declared_shots
    assert [shot.shot_number for shot in parsed.declared_shots] == [1, 2]
    assert [shot.declared_seconds for shot in parsed.declared_shots] == [5.0, 4.0]
    assert parsed.declared_shots[0].field("构图技巧") == "纵深引导线构图。"
    assert parsed.declared_shots[0].field("拍摄手法") == "缓慢推近。"
