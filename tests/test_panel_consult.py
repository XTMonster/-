"""联合会诊（DeepSeek × GLM-5.3）的判据都在这里钉住——全部离线，不联网。

为什么值得一组用例（2026-10-04）：

* "换个模型再问一遍"很容易被读成"两个模型都同意"；真正要防的是**把缺席读成同意**，
  所以每条失败路径都必须留下 `failed`/`unparsed` 而不是静默通过；
* 会诊包的取证纪律（**先写 manifest 再联网**）与 GLM 通道的默认值同源，
  这两件事一漂，读者就没法判断"它到底看到了什么、跑的是哪个预算"。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import panel_consult as pc  # noqa: E402


def _side(*findings: dict) -> str:
    return json.dumps({"summary": "s", "teaching": "t", "findings": list(findings)},
                      ensure_ascii=False)


def _finding(ident: str, title: str, claim: str, severity: str = "major") -> dict:
    return {"id": ident, "severity": severity, "title": title, "claim": claim,
            "where": "x.py:1", "confidence": "high"}


def _write_bundle(tmp_path: pathlib.Path) -> tuple:
    question = tmp_path / "q.md"
    question.write_text("轴侧判据对不对？", encoding="utf-8")
    source = tmp_path / "axis.py"
    source.write_text("def side():\n    return 'left'\n", encoding="utf-8")
    return question, "axis.py"


def test_parse_side_tolerates_code_fences_and_trailing_prose():
    fenced = "```json\n" + _side(_finding("F1", "轴侧", "机位不在同侧")) + "\n```"
    assert pc.parse_side(fenced)["findings"][0]["title"] == "轴侧"
    assert pc.parse_side("说明一句：" + _side())["findings"] == []
    assert pc.parse_side("完全不是 JSON") is None
    assert pc.parse_side("") is None


def test_pair_findings_puts_every_side_in_its_own_bucket():
    glm = [_finding("G1", "轴侧判据看的是世界轴", "机位不在同一侧就报越轴"),
           _finding("G2", "缺成对复验", "只有单跑数字", "minor"),
           _finding("G3", "只有 GLM 提到的东西", "GLM 独有")]
    deepseek = [_finding("D1", "轴侧判据看的是世界轴", "机位不在同一侧就报越轴"),
                _finding("D2", "缺成对复验", "只有单跑数字", "major"),
                _finding("D3", "只有 DeepSeek 提到的东西", "DeepSeek 独有")]
    pairs = pc.pair_findings(glm, deepseek)
    assert [item["left"]["id"] for item in pairs["both"]] == ["G1"]
    assert [item["left"]["id"] for item in pairs["severity_conflict"]] == ["G2"]
    assert [item["id"] for item in pairs["glm_only"]] == ["G3"]
    assert [item["id"] for item in pairs["deepseek_only"]] == ["D3"]


def test_pair_findings_labels_the_sides_by_name_not_by_position():
    """按位置返回过 `left/right` 时，消费端把 left（GLM）标成了 DeepSeek——这条钉住命名。"""
    pairs = pc.pair_findings([_finding("G1", "只有 GLM 说的事", "甲")], [])
    assert [item["id"] for item in pairs["glm_only"]] == ["G1"]
    assert pairs["deepseek_only"] == []


def test_run_role_records_a_failed_side_instead_of_treating_it_as_agreement():
    def boom(messages):
        raise SystemExit("缺少 GLM_API_KEY（只从环境变量读，绝不写进仓库）")

    report = pc.run_role("规格一致性", "q", [], [], "status", None,
                         glm_model="glm-5.3", deepseek_model="deepseek-chat",
                         glm_call=boom,
                         deepseek_call=lambda messages: (_side(_finding("D1", "a", "b")), {}),
                         main_answer=None)
    assert report["status"]["glm"] == "failed"
    assert report["status"]["deepseek"] == "ok"
    assert report["complete"] is False
    assert report["pairs"]["both"] == []            # 一侧缺席 ⇒ 没有任何"都同意"
    assert report["pairs"]["deepseek_only"][0]["id"] == "D1"


def test_run_role_unparsed_body_is_not_a_pass():
    report = pc.run_role("红队反方", "q", [], [], "status", None,
                         glm_model="glm-5.3", deepseek_model="deepseek-chat",
                         glm_call=lambda messages: ("完全不是 JSON", {"model": "glm-5.3"}),
                         deepseek_call=None, main_answer=None)
    assert report["status"]["glm"] == "unparsed"
    assert report["complete"] is False


def test_main_answer_substitutes_the_deepseek_side():
    main = json.loads(_side(_finding("D1", "轴侧", "机位不在同侧")))
    report = pc.run_role("规格一致性", "q", [], [], "status", None,
                         glm_model="glm-5.3", deepseek_model="deepseek-chat",
                         glm_call=lambda messages: (_side(_finding("G1", "轴侧", "机位不在同侧")), {}),
                         deepseek_call=None, main_answer=main)
    assert report["status"]["deepseek"] == "main-answer"
    assert report["complete"] is True
    assert len(report["pairs"]["both"]) == 1


def test_panel_never_claims_a_human_reviewer():
    report = pc.run_role("规格一致性", "q", [], [], "status", None,
                         glm_model="glm-5.3", deepseek_model="deepseek-chat",
                         glm_call=lambda messages: (_side(), {}),
                         deepseek_call=None,
                         main_answer=json.loads(_side()))
    text = pc.render_panel([report], glm_model="glm-5.3",
                           deepseek_model="deepseek-chat", sources=[], contexts=[])
    assert pc.PANEL_TAG == "llm-panel"
    assert report["reviewed_by"] == "llm-panel"
    assert "reviewed_by: llm-panel" in text
    #: 要防的是**声称人审**（`reviewed_by: human`），不是"正文里出现 human 这个词"。
    assert re.search(r"reviewed_by[`\s:]*human", text) is None
    assert re.search(r'reviewed_by["\s:]+human', json.dumps(report, ensure_ascii=False)) is None


def _failing_caller(*_args, **_kwargs):
    """替身：两个通道都不可用（用例必须离线、可复算——绝不真打 API）。"""
    def call(_messages):
        raise SystemExit("这个用例里没有可用通道")
    return call


def test_manifest_is_written_before_any_call_and_outlives_a_failure(tmp_path, monkeypatch):
    """**先留证、再联网**：两侧都失败时，manifest 与 panel 仍必须落盘。"""
    monkeypatch.setattr(pc, "glm_caller", _failing_caller)
    monkeypatch.setattr(pc, "deepseek_caller", _failing_caller)
    question, source = _write_bundle(tmp_path)
    out = tmp_path / "panel"
    code = pc.main(["--question", str(question), "--source", source,
                    "--repo", str(tmp_path), "--out", str(out),
                    "--question-only"])
    assert code == 1, "一侧都没答上来时必须判不完整（非 0）"
    assert (out / "bundle.manifest.json").is_file()
    assert (out / "bundle.md").is_file()
    panel = json.loads((out / "panel.json").read_text(encoding="utf-8"))
    assert panel["complete"] is False
    assert panel["reviewed_by"] == "llm-panel"
    statuses = panel["roles"][0]["status"]
    assert statuses["deepseek"] == "failed" and statuses["glm"] == "failed"


def test_dry_run_builds_bundles_and_writes_nothing(tmp_path, capsys):
    question, source = _write_bundle(tmp_path)
    out = tmp_path / "panel"
    code = pc.main(["--question", str(question), "--source", source,
                    "--repo", str(tmp_path), "--out", str(out), "--dry-run"])
    assert code == 0
    assert not out.exists(), "dry-run 不许写盘"
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["source_seen"] is True
    assert payload["bundles"], "每个角色都要留下包指纹"


def test_default_max_tokens_matches_the_glm_channel():
    """同一事实两个真源要机检：本工具的默认预算必须与 `glm_consult` 的 CLI 默认一致。"""
    text = (ROOT / "tools" / "glm_consult.py").read_text(encoding="utf-8")
    match = re.search(r'"--max-tokens",\s*type=int,\s*default=(\d+)', text)
    assert match, "glm_consult 的 --max-tokens 默认值找不到了（口径漂了）"
    assert int(match.group(1)) == pc.DEFAULT_MAX_TOKENS
