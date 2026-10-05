"""D8 的判定需要 E1 面板能跑**第三条臂**（`lightrag`）。

三条臂：`hybrid`（产品现行 BM25）／`lexical`（零依赖适配器）／`lightrag`
（真索引 ＋ sidecar）。面板必须能显式选任一条，并把 `retrieval_path` 写进每一行——
不然一份证据里三条路的读数会混账。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PANEL = ROOT / "tools" / "knowledge" / "e1_panel.py"


def _code() -> str:
    text = PANEL.read_text(encoding="utf-8")
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("#"))


def test_the_panel_offers_the_lightrag_arm():
    code = _code()
    assert 'choices=("none", "lexical", "lightrag")' in code, \
        "--adapter 必须能选 lightrag，否则 D8 的第三条臂跑不了"


def test_the_lightrag_arm_wires_the_adapter_and_labels_the_path():
    code = _code()
    assert "make_lightrag_adapter" in code
    #: 每一行必须自带 `retrieval_path`，且这一臂要标成 `lightrag`（不是 hybrid）。
    assert 'path_label = "lightrag"' in code


def test_the_lightrag_arm_can_take_the_sidecar_url_and_fingerprint():
    code = _code()
    assert "--lightrag-url" in code
    assert "--lightrag-fingerprint" in code
