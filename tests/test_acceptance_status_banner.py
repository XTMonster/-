"""守门：`docs/knowledge/ACCEPTANCE_STATUS.md` 顶上的**当前读数板**必须与它引用的证据目录一致。

为什么（2026-10-06 全量审查抓到）：这份文件是 410 KB 的历史快照集，头一句写着
"2026-10-01 语料重建之后"，而它 §四 那张表里 **E1 还写着 `not_measured（人评）`、
E2 还解释成"结构性恒 0，因为 `_movements_payload` 不记知识来源"**——两处都已过时
（E1 早已量到 **0.1771 fail**，是全仓唯一的红；E2 的 provenance 通路也早在库里）。
一个看板写着"没量"，实际"量到了且是红的"，正是最危险的那种陈述。

这条守门钉三件事：
① 顶上有一节**当前读数板**，并**点名**它引用的证据目录；
② 那张表**逐个提到**该证据里 `knowledge_quality.json` 的**每一个指标 id**（不许漏项，
   免得某个指标悄悄从看板上消失）；
③ 表里引用的 **E1 数字**与证据里的 E1 **逐字一致**（看板不许比证据新、也不许比证据旧）。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STATUS = ROOT / "docs" / "knowledge" / "ACCEPTANCE_STATUS.md"
BANNER_MARK = "## 当前读数（"
EVIDENCE_RE = re.compile(r"`(docs/evidence/[0-9A-Za-z._-]+)/?`")


def _banner() -> str:
    text = STATUS.read_text(encoding="utf-8")
    start = text.find(BANNER_MARK)
    assert start != -1, "ACCEPTANCE_STATUS.md 顶上必须有一节「当前读数」（看板）"
    #: 看板在**正文开始之前**结束：取标题行到"## 〇"或第一个非引用段。
    rest = text[start:]
    lines = []
    for line in rest.split("\n"):
        if lines and line and not line.startswith(">") and not line.startswith(BANNER_MARK):
            break
        lines.append(line)
    return "\n".join(lines)


def test_the_banner_names_the_evidence_directory_it_quotes():
    banner = _banner()
    found = EVIDENCE_RE.findall(banner)
    assert found, "看板必须点名它引用的证据目录（`docs/evidence/<run-id>/`）"
    for rel in found:
        assert (ROOT / rel).is_dir(), "看板引用的证据目录不存在：%s" % rel


def test_the_banner_covers_every_metric_in_the_evidence():
    """不许漏项：证据里有的指标 id，看板上都要出现（Q0/K1..K4/Q1..Q7/E1..E3…）。"""
    banner = _banner()
    rel = EVIDENCE_RE.findall(banner)[0]
    payload = json.loads((ROOT / rel / "knowledge_quality.json").read_text(encoding="utf-8"))
    ids = [str(row.get("id")) for row in payload["metrics"]]
    missing = [metric for metric in ids if metric not in banner]
    assert missing == [], "这些指标在看板上没有落点：%s" % missing


def test_the_banner_quotes_the_e1_reading_verbatim():
    banner = _banner()
    rel = EVIDENCE_RE.findall(banner)[0]
    payload = json.loads((ROOT / rel / "knowledge_quality.json").read_text(encoding="utf-8"))
    e1 = [row for row in payload["metrics"] if str(row.get("id")) == "E1"][0]
    value = "%s" % e1["value"]
    assert value in banner, (
        "看板上的 E1 必须与证据里的 %s 一致（旧口径把 E1 写成 not_measured 是最危险的一种陈述）"
        % value)
    assert str(e1.get("status")) in banner, "E1 的状态（%s）也要写出来" % e1.get("status")
