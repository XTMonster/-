"""C4：`tools/knowledge/attestation_ledger.py` 的口径校验。

这一层守的不是判据本身（判据在 `attestation.py`），而是**判据读数被转述时的三种歪法**：
把 `unattested` 说成"编造"、只报好看的那一个分母、让 `not-checkable` 悄悄涨上去。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import attestation as AT  # noqa: E402
from tools.knowledge import attestation_ledger as LED  # noqa: E402


def _report(**overrides) -> dict:
    report = {
        "criterion_version": "attest/v1",
        "edges": 638,
        "slots": {"attested": 331, "unattested": 1262, "not-checkable": 345},
        "checkable_slots": 1593,
        "attested_share": 0.2078,
        "criterion": "成员取值能否在这条边自己的来源卡正文里找到 surface。",
    }
    report.update(overrides)
    return report


def test_a_clean_report_passes_and_reports_both_denominators():
    result = LED.check(_report())
    assert result["ok"], result["findings"]
    readings = result["readings"]
    # 两个分母**并列**：可检 1593 与全量 1938 各给自己的 share，缺一即违规。
    assert readings["checkable_denominator"] == 1593
    assert readings["total_denominator"] == 1938
    assert readings["attested_share_of_checkable"] == 0.2078
    assert readings["attested_share_of_total"] == 0.1708


def test_a_growing_not_checkable_bucket_is_caught():
    """`not-checkable ≤ 345` 是钉住的上界：桶名桶在涨＝判据被放宽。"""
    report = _report(slots={"attested": 331, "unattested": 1261, "not-checkable": 346},
                     checkable_slots=1592)
    result = LED.check(report)
    assert not result["ok"]
    assert any("not-checkable" in f and "346" in f for f in result["findings"])


def test_swapping_the_denominator_is_caught():
    """只报全量分母、把可检分母抹掉 ⇒ 必须报错（不许只报好看的那一个）。"""
    report = _report(checkable_slots=1938)
    result = LED.check(report)
    assert not result["ok"]
    assert any("可检槽位" in f or "checkable_slots" in f for f in result["findings"])


def test_a_slot_count_that_does_not_add_up_is_caught():
    report = _report(slots={"attested": 331, "unattested": 1262, "not-checkable": 344})
    result = LED.check(report)
    assert not result["ok"]
    assert any("槽位总数" in f for f in result["findings"])


def test_a_share_that_contradicts_its_bucket_counts_is_caught():
    report = _report(attested_share=0.9999)
    result = LED.check(report)
    assert not result["ok"]
    assert any("attested_share" in f for f in result["findings"])


def test_calling_unattested_fabricated_is_caught_but_a_negation_is_fine():
    """措辞纪律：`unattested` ＝ 未被来源佐证（下界），不是"编造"。

    带否定词的写法（"未被佐证 ≠ 编造"）是**正确**写法，不许误伤。
    """
    bad = LED.check(_report(criterion="这些槽位是编造出来的。"))
    assert not bad["ok"]
    assert any("措辞违规" in f for f in bad["findings"])

    good = LED.check(_report(criterion="未被来源佐证不等于编造，它只是下界。"))
    assert good["ok"], good["findings"]


def test_a_different_criterion_generation_is_caught():
    result = LED.check(_report(criterion_version="attest/v2"))
    assert not result["ok"]
    assert any("criterion_version" in f for f in result["findings"])


def test_a_report_without_slots_is_caught():
    report = _report()
    del report["slots"]
    result = LED.check(report)
    assert not result["ok"]
    assert any("slots" in f for f in result["findings"])


def test_an_undeclared_slot_bucket_is_caught():
    result = LED.check(_report(slots={"attested": 331, "unattested": 1262,
                                      "not-checkable": 345, "probably-fine": 0}))
    assert not result["ok"]
    assert any("未登记的新桶" in f for f in result["findings"])


def test_the_cli_exit_code_follows_the_verdict(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_report(), ensure_ascii=False), encoding="utf-8")
    assert LED.main(["--report", str(good)]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_report(attested_share=0.5), ensure_ascii=False),
                   encoding="utf-8")
    out = tmp_path / "out.json"
    assert LED.main(["--report", str(bad), "--json", str(out)]) == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["ok"] is False and written["findings"]


def test_the_shipped_report_on_disk_passes():
    """仓库里那份实测报告必须过——它是本代读数的留档。"""
    path = ROOT / "docs" / "evidence" / "20261003-115647" / "knowledge_attestation.json"
    if not path.is_file():
        import pytest

        pytest.skip("实测报告未入库")
    result = LED.check(LED.load_report(path))
    assert result["ok"], result["findings"]


def test_the_live_index_recomputes_to_a_clean_report():
    """现算一遍（判据在 `attestation.py`）也必须过——挡住"报告是手改的"这种可能。"""
    edges_path = ROOT / "knowledge" / "hypergraph.edges.jsonl"
    nodes_path = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
    if not edges_path.is_file() or not nodes_path.is_file():
        import pytest

        pytest.skip("索引未入库")
    from block_director.knowledge.hypergraph import Node

    nodes = {row["node_id"]: Node.from_dict(row)
             for row in AT.load_jsonl(nodes_path)}
    report = AT.audit(AT.load_jsonl(edges_path),
                      AT.load_cards(ROOT / "knowledge" / "cards_generated"), nodes)
    result = LED.check(report)
    #: **share 只防回退、不禁止变化**（2026-10-07 修，本文件自己的粒度错了）：
    #: 语料/索引**本来就会换代**（当天刚做完 `rebind/v1`：可检 share 0.2078 → 0.8751），
    #: 把"变了"直接判成失败等于**禁止换代**。`check()` 现在把"**降**"判红、
    #: 把"**升**"记进 `improvements`；口径纪律（措辞／两分母／上界）仍一律红。
    assert result["findings"] == [], result["findings"]
    assert result["ok"] is True
    #: 读数一并对照（升了就该出现在 improvements 里，而不是凭空消失）
    readings = result["readings"]
    assert readings["checkable_denominator"] == readings["slots"]["attested"] \
        + readings["slots"]["unattested"]
