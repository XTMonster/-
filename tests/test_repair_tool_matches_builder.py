"""修复用的 `setup_camera` 必须与**主构建器**共用同一套机位解算。

2026-10-04 实测（`work/_tool_vs_builder_probe.py`，四份冻结工程各 64 镜）：
`setup_camera` 曾经自己拼 `axis_dir/axis_side` 再直调 `place_camera_for_shot`，
于是丢了主构建器有的四样东西——

* 视线留白与头顶留白的对准点偏移（§10.4 / §六十九）；
* `spec.room` 的房间钳制；
* **逐镜**轴侧（顺序状态机 `_axis_sides_used`，换位之后会翻侧）；
* 时间点（要先 `frame_set` 到该镜首帧，`live_subject_entries` 读的才是"这镜人在哪"）。

代价：拿**计划自己的**参数重设一次，long16 里 34 镜构图更差、10 镜由通过变不通过
（最差 `shot_027` 83.2 → 20.0）。long16 那一跑"真的动了手"的 7 个修复回合
**0 个通过**，根因就是它。

本文件钉住修法，防的是**下一次**有人在工具层再抄一份解算：

1. `_tool_setup_camera` 只许经 `place_shot_camera`（唯一入口）解算；
2. 它不许自己调 `place_camera_for_shot` / `camera_direction`；
3. 声明式运镜（§3.6）在**两处**都走同一个 `apply_declared_movements`；
4. 主构建调用它时必须**显式**传 `camera=`/`target=`——`build_scene` 直到收尾才
   `set_context`，构建期间 `get_context()` 是**上一次**的场景（这一条踩过：
   整场 64 镜的运镜被静默跳过，见 `work/_kf_probe.py`）。
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
BINDINGS = ROOT / "block_director" / "layer3_engine" / "tool_bindings.py"
BUILDER = ROOT / "block_director" / "layer3_engine" / "shot_builder.py"


def _functions(path: pathlib.Path) -> dict:
    """模块里所有函数（含嵌套的顶层定义）的源码，按名字索引。"""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.setdefault(node.name, ast.get_source_segment(text, node) or "")
    return found


def _calls(source: str) -> set:
    """源码里出现过的被调用函数名（只认 `name(...)` 形式）。"""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def test_setup_camera_goes_through_the_builder_entry_point():
    source = _functions(BINDINGS)["_tool_setup_camera"]
    calls = _calls(source)
    assert "place_shot_camera" in calls, (
        "`setup_camera` 必须经 `place_shot_camera` 解算——那是主构建与单镜再生的"
        "唯一入口；自己再解一遍必然漂移（见本文件抬头）")
    assert "place_camera_for_shot" not in calls, (
        "`setup_camera` 不许直调 `place_camera_for_shot`：那正是丢掉视线留白、"
        "头顶留白、room 钳制与逐镜轴侧的那条捷径")
    assert "camera_direction" not in calls, (
        "`setup_camera` 不许自己解方向——方向（含轴侧）由 `place_shot_camera` 解")


def test_reframe_goes_through_the_builder_entry_point():
    """`reframe` 只多一条约束（复用相机对象），解算仍必须走同一个入口。

    它的抬头一度写着"与主构建、setup_camera 共用同一套参考系与同一套 side
    解析"，代码却写死 `side="front"` 并直调 `solve_framing`。实测（long16）：
    64 镜里 9 镜构图更差、3 镜由通过变不通过。
    """
    source = _functions(BINDINGS)["_tool_reframe"]
    calls = _calls(source)
    assert "place_shot_camera" in calls, (
        "`reframe` 必须走 `place_shot_camera`（`reuse=` 复用同一台相机）")
    assert "solve_framing" not in calls, (
        "`reframe` 不许自己调 `solve_framing`：那会绕开轴线侧别、视线留白与 "
        "room 钳制")
    assert "camera_direction" not in calls, "`reframe` 不许自己解方向"
    assert "reuse" in {item.arg for node in ast.walk(ast.parse(source))
                       if isinstance(node, ast.Call)
                       for item in node.keywords}, (
        "`reframe` 必须传 `reuse=`：它的契约是"
        "「相机对象未重建」（复用同一台相机与同一个对准 Empty）")


def test_declared_movements_have_one_implementation():
    bindings = _functions(BINDINGS)
    builder = _functions(BUILDER)
    assert "apply_declared_movements" in _calls(bindings["_tool_setup_camera"]), (
        "重新摆机位会重建相机对象、连关键帧一起丢掉 ⇒ 这一镜声明的运镜必须重放；"
        "工具层与主构建必须共用 `apply_declared_movements`")
    assert "apply_camera_movement" not in _calls(builder["build_scene"]), (
        "`build_scene` 不许自己写一遍运镜落地——两处各写一遍就是漂移的来源")
    assert "apply_declared_movements" in _calls(builder["build_scene"]), (
        "`build_scene` 必须走共用的 `apply_declared_movements`")


def test_builder_passes_the_camera_explicitly():
    """`build_scene` 期间 `get_context()` 还是上一次的场景（收尾才 set）。"""
    source = _functions(BUILDER)["build_scene"]
    call = None
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "apply_declared_movements"):
            call = node
    assert call is not None, "`build_scene` 里没找到 `apply_declared_movements` 调用"
    keywords = {item.arg for item in call.keywords}
    assert {"camera", "target"} <= keywords, (
        "`build_scene` 调 `apply_declared_movements` 时必须显式传 `camera=`/`target=`："
        "构建期间全局上下文还是上一次场景，靠 `get_context()` 取相机会把整场运镜"
        "静默跳过（实测 64 镜全部 0 关键帧）")
