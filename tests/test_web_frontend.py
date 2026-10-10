"""v1.7 卡 C1–C6 / E3：Web 前端的静态约束与纯函数行为。

前端零构建、无 JS 测试框架，所以分两层验：

* **静态约束**（技术方案 D2/D3 ＋ 各卡禁区）：单文件 ≤600 行、资源总量 ≤1 MB、
  不引 CDN/外部 URL、轮询 ≥1.5 s、JS 不硬编码状态映射与规则清单、
  index.html 引用的静态文件都存在；
* **纯函数**：``web/lib.js`` 无 DOM，用 ``node`` 直接 import 跑断言
  （坐标映射往返 ±0.01、缺 ``paths`` 键不猜点、LCS diff、规则开关去重）。
  ``node`` 缺席时这一层**失败**而不是跳过。

页面交互（页签/离线横幅/token 抹除等）仍以附录 X2 手测为准，这里不冒充。
"""

from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
JS_FILES = sorted(WEB.glob("*.js"))
TEXT_FILES = JS_FILES + [WEB / "index.html", WEB / "pixel.css"]


def _node() -> str:
    exe = shutil.which("node")
    assert exe, "需要 node 来校验前端 JS（未找到 node 可执行文件）"
    return exe


def test_expected_files_exist():
    names = {p.name for p in TEXT_FILES}
    for required in ("index.html", "pixel.css", "app.js", "settings.js", "chat.js",
                     "knowledge.js", "rules.js", "trajectory.js", "polish.js",
                     "assistant.js", "lib.js"):
        assert required in names, required


@pytest.mark.parametrize("path", TEXT_FILES, ids=lambda p: p.name)
def test_file_at_most_600_lines(path):
    lines = path.read_text(encoding="utf-8").count("\n")
    assert lines <= 600, f"{path.name}: {lines} 行"


def test_total_resources_under_1mb_excluding_sprites():
    total = sum(p.stat().st_size for p in WEB.rglob("*")
                if p.is_file() and "assistant" not in p.relative_to(WEB).parts[:2])
    assert total <= 1_000_000, total


@pytest.mark.parametrize("path", TEXT_FILES, ids=lambda p: p.name)
def test_no_external_urls(path):
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"https?://|//cdn|unpkg|jsdelivr", text), path.name


def test_poll_interval_at_least_1500ms():
    text = (WEB / "app.js").read_text(encoding="utf-8")
    m = re.search(r"POLL_INTERVAL_MS\s*=\s*(\d+)", text)
    assert m and int(m.group(1)) >= 1500
    # 轮询只有一处：其余模块不得自建 setInterval/setTimeout 轮询
    for path in JS_FILES:
        if path.name != "app.js":
            assert "setInterval" not in path.read_text(encoding="utf-8"), path.name


def test_js_does_not_hardcode_state_map_or_rule_list():
    states = ("UNDERSTANDING", "CALLING_LLM", "EXECUTING_TOOL", "REPAIRING", "AWAIT_HUMAN")
    for path in JS_FILES:
        text = path.read_text(encoding="utf-8")
        hits = [s for s in states if s in text]
        assert not hits, f"{path.name} 硬编码了状态名 {hits}（映射真源是 /v1/ui/state_map）"
        rule_ids = set(re.findall(r"\bR0\d\d\b", text))
        assert len(rule_ids) <= 1, f"{path.name} 疑似内嵌规则清单 {sorted(rule_ids)}"


def test_config_channel_never_carries_key():
    text = (WEB / "settings.js").read_text(encoding="utf-8")
    assert 'body.llm.api_key = ""' in text
    assert '"Content-Type": "application/json"' in text
    assert "/v1/ui/secret" in text


def test_polish_accept_requires_confirm():
    text = (WEB / "polish.js").read_text(encoding="utf-8")
    # 定位真正的调用（文件头注释里也出现了同一路径）
    accept = text.index('api("/v1/ui/script/polish/accept"')
    handler = text.rfind("acceptBtn.addEventListener", 0, accept)
    assert handler != -1
    confirm = text.find("window.confirm(", handler, accept)
    assert confirm != -1, "采纳调用之前必须先过 window.confirm 二次确认"
    assert "return;" in text[confirm:accept], "取消确认必须中止采纳"


def test_index_references_existing_static_files():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="/static/([^"]+)"', html)
    assert refs
    for ref in refs:
        assert (WEB / ref).is_file(), ref


def test_module_imports_resolve():
    for path in JS_FILES:
        for ref in re.findall(r'(?:from|import\()\s*"(\./[^"]+)"', path.read_text(encoding="utf-8")):
            assert (WEB / ref[2:]).is_file(), f"{path.name} -> {ref}"


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_js_syntax(path, tmp_path):
    # .mjs 副本让 node 按 ES module 解析 import/export
    copy = tmp_path / (path.stem + ".mjs")
    copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    proc = subprocess.run([_node(), "--check", str(copy)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


LIB_PROBE = r"""
import * as L from %s;
const out = {};
const ext = 12, W = 640, H = 640;
out.roundtrip = [[0,0],[3.37,-2.21],[-11.99,11.99],[5.005,0.004]].map(([x,y]) => {
  const [px,py] = L.worldToCanvas(x,y,ext,W,H); const [wx,wy] = L.canvasToWorld(px,py,ext,W,H);
  return Math.max(Math.abs(wx-x), Math.abs(wy-y));
});
out.centre = L.worldToCanvas(0,0,ext,W,H);
out.corner = L.worldToCanvas(12,12,ext,W,H);
out.paths = L.collectPaths([
  {shot_id:"s2", order:2, paths:{A:[[2,0,0],[3,0,0]]}},
  {shot_id:"s1", order:1, paths:{A:[[0,0,0],[1,0,0]], B:[[5,5,0]]}},
  {shot_id:"s3", order:3},
  {shot_id:"s4", order:4, paths:{}},
]);
out.noPaths = L.collectPaths([{shot_id:"old", order:1}]);
out.diff = L.lineDiff("a\nb\nc", "a\nx\nc\nd").map(o => o.op);
out.diffSame = L.lineDiff("p\nq", "p\nq").map(o => o.op);
const cfg = {rag:{top_k:15}, extra:{keep:1}};
L.setPath(cfg, "rag.top_k", 12);
out.cfg = cfg; out.get = L.getPath(cfg, "rag.top_k"); out.missing = L.getPath(cfg, "nope.x") === undefined;
out.off = L.toggleDisabled(["R012"], "R009", false);
out.offTwice = L.toggleDisabled(["R009"], "R009", false);
out.on = L.toggleDisabled(["R009","R012"], "R009", true);
console.log(JSON.stringify(out));
"""


def test_lib_pure_functions(tmp_path):
    lib_url = json.dumps((WEB / "lib.js").resolve().as_uri())
    probe = tmp_path / "probe.mjs"
    probe.write_text(LIB_PROBE % lib_url, encoding="utf-8")
    proc = subprocess.run([_node(), str(probe)], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert max(out["roundtrip"]) < 0.01                 # A-U4-2 ±0.01 m
    assert out["centre"] == [320, 320]
    assert out["corner"] == [640, 0]                    # 世界 +X 向右、+Y 向上
    assert out["paths"] == {"A": [[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]], "B": [[5, 5, 0]]}
    assert out["noPaths"] == {}                         # 缺 paths 键：不猜点
    assert out["diff"] == ["eq", "del", "add", "eq", "add"]
    assert out["diffSame"] == ["eq", "eq"]
    assert out["cfg"] == {"rag": {"top_k": 12}, "extra": {"keep": 1}}  # 未知键原样保留
    assert out["get"] == 12 and out["missing"] is True
    assert out["off"] == ["R009", "R012"]
    assert out["offTwice"] == ["R009"]
    assert out["on"] == ["R012"]


# ---- C3 占位帧生成器（不依赖 A1 的那一半；clip 名对拍在 tests/test_assistant_assets.py）----

def _load_generator():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import gen_placeholder_sprites as gen
    finally:
        sys.path.pop(0)
    return gen


def test_sprite_generator_deterministic_and_sized(tmp_path):
    gen = _load_generator()
    a, b = tmp_path / "a", tmp_path / "b"
    table = gen.build(a)
    gen.build(b)
    for name, spec in table["clips"].items():
        data = (a / spec["file"]).read_bytes()
        assert data == (b / spec["file"]).read_bytes(), name
        assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
        width, height = struct.unpack(">II", data[16:24])
        assert (width, height) == (48 * spec["frames"], 48), name
        assert 4 <= spec["frames"] <= 8, name
    assert (a / "frames.json").read_bytes() == (b / "frames.json").read_bytes()


def test_committed_sprites_match_generator(tmp_path):
    gen = _load_generator()
    gen.build(tmp_path)
    committed = WEB / "assets" / "assistant"
    for path in sorted(tmp_path.iterdir()):
        assert (committed / path.name).read_bytes() == path.read_bytes(), \
            f"{path.name} 与生成器漂移：重跑 python tools/gen_placeholder_sprites.py"
