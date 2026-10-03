"""常驻外部顾问的**离线**部分：角色表、提示词拼装、降档阶梯（不联网）。

真调用要密钥、要十几分钟，不进 pytest；这里钉的是"换一双眼睛"这件事的
**结构**：角色必须互相不重复、问题与产物必须真的进了提示词、
没有正文时按 `max → high → low` 逐档降级并把每一档记进 usage。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import glm_consult as C  # noqa: E402


def test_the_role_table_covers_the_review_angles_the_agents_md_asks_for():
    assert {"规格一致性", "接口与契约", "测试与验收", "性能与鲁棒",
            "红队反方"} <= set(C.ROLES)


def test_every_role_gets_a_distinct_instruction():
    """多 agent 会诊的意义在"角度不重复"——两组同义词不算两组。"""
    texts = list(C.ROLES.values())
    assert len(set(texts)) == len(texts)
    for text in texts:
        assert len(text) >= 30


def test_the_system_prompt_names_the_role_and_demands_one_json_object():
    messages = C.build_messages("红队反方", "问题", [("a.md", "正文")])
    system = messages[0]["content"]
    assert "红队反方" in system
    assert "JSON" in system and "not_checked" in system
    assert C.ROLES["红队反方"] in system


def test_the_question_and_every_artefact_reach_the_prompt():
    messages = C.build_messages("测试与验收", "这是问题",
                                [("x.md", "产物一"), ("y.md", "产物二")])
    user = messages[1]["content"]
    assert "这是问题" in user
    assert "产物一" in user and "产物二" in user
    assert "x.md" in user and "y.md" in user


def test_an_unknown_role_is_refused_by_name():
    with pytest.raises(SystemExit) as excinfo:
        C.build_messages("查水表的", "问题", [])
    assert "规格一致性" in str(excinfo.value)      # 报错要列出可用角色


def test_context_tail_keeps_the_newest_section(tmp_path):
    """长状态文档的最新一节在**末尾**：截断必须从前面截。"""
    path = tmp_path / "status.md"
    path.write_text("旧" * 100 + "最新一节", encoding="utf-8")
    (_, text), = C.read_contexts([str(path)], tail=12)
    assert text.endswith("最新一节")
    assert text.startswith("... [earlier part omitted]")


def test_without_a_tail_the_whole_artefact_is_embedded(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("全文", encoding="utf-8")
    (_, text), = C.read_contexts([str(path)])
    assert text == "全文"


def test_the_ladder_steps_down_when_the_model_gives_no_text(monkeypatch):
    """`level=max` ＋ 小 `max_tokens` 会把预算烧在 reasoning 上、正文为空。

    阶梯必须**逐档降级**、每一档都记进 `attempts`，而不是把空正文当成功。
    """
    seen = []

    def fake_call_once(messages, *, model, max_tokens, level, temperature,
                       timeout, api_key=None):
        seen.append(level)
        if level == "max":
            return "", {"level": level, "finish_reason": "length",
                        "usage": {"completion_tokens": 8192}}
        return '{"summary": "ok"}', {"level": level, "finish_reason": "stop"}

    monkeypatch.setattr(C, "call_once", fake_call_once)
    monkeypatch.setattr(C.time, "sleep", lambda _s: None)
    content, usage = C.consult([{"role": "user", "content": "x"}], model="glm-5.3",
                               max_tokens=32768, levels=["max", "high", "low"],
                               temperature=0.2, timeout=1.0, api_key="k")
    assert content == '{"summary": "ok"}'
    assert seen == ["max", "high"], "应当降一档就拿到正文"
    assert [item["level"] for item in usage["attempts"]] == ["max", "high"]
    assert usage["attempts"][0]["finish_reason"] == "length"


def test_a_transport_error_is_not_retried_through_the_ladder(monkeypatch):
    """429/HTTP 错误换档无益：直接上报，不许把错误吞成"重试"。"""
    calls = []

    def fake_call_once(messages, *, model, max_tokens, level, temperature,
                       timeout, api_key=None):
        calls.append(level)
        return "", {"level": level, "error": "HTTP 429: rate limited"}

    monkeypatch.setattr(C, "call_once", fake_call_once)
    with pytest.raises(SystemExit) as excinfo:
        C.consult([{"role": "user", "content": "x"}], model="glm-5.3",
                  max_tokens=32768, levels=["max", "high", "low"],
                  temperature=0.2, timeout=1.0, api_key="k")
    assert calls == ["max"]
    assert "429" in str(excinfo.value)


def test_dry_run_needs_no_api_key(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    question = tmp_path / "q.md"
    question.write_text("问题", encoding="utf-8")
    ctx = tmp_path / "c.md"
    ctx.write_text("产物", encoding="utf-8")
    code = C.main(["--roles", "规格一致性,红队反方", "--question", str(question),
                   "--context", str(ctx), "--out", str(tmp_path / "out"),
                   "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "dry-run 规格一致性" in out and "dry-run 红队反方" in out
    assert not (tmp_path / "out").exists()


def test_the_usage_sidecar_is_json_serialisable():
    """usage 里塞了 attempts —— 必须不构成自引用（2026-10-03 真的踩过）。

    做法与 `consult()` 一致：**先把当前这一档拷进 list，再**把 list 挂到
    usage 上；直接 append `usage` 自己会让 `json.dumps` 抛
    "Circular reference detected"（那条 usage 文件当时根本没写成）。
    """
    usage = {"level": "high", "finish_reason": "stop"}
    tried = [dict(usage)]
    usage["attempts"] = tried
    payload = json.dumps(usage)
    assert '"attempts"' in payload
    assert "attempts" not in usage["attempts"][0]


def test_a_peer_disconnect_is_recorded_instead_of_crashing(monkeypatch):
    """实测（2026-10-04）：大 bundle 跑到 ~30 分钟会被对端**直接掐断**连接。

    这一刻必须落成一条可写盘的失败记录（哪一档、跑了多久、断在哪一层），
    而不是把 traceback 抛出去——崩掉的话连 usage 都留不下，
    "这次真的调过 glm-5.3、调到哪一档"就无从取证。
    """
    import http.client

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        raise http.client.RemoteDisconnected("Remote end closed connection")

    monkeypatch.setattr(C.urllib.request, "urlopen", fake_urlopen)
    content, usage = C.call_once([{"role": "user", "content": "x"}],
                                 model="glm-5.3", max_tokens=32768, level="high",
                                 temperature=0.2, timeout=1.0, api_key="k")
    assert content == ""
    assert usage["level"] == "high"
    assert "RemoteDisconnected" in usage["error"]
    assert usage["finish_reason"] == "transport_error"
    assert isinstance(usage["elapsed_s"], float)


def test_a_failed_consult_still_leaves_its_attempts_on_disk(tmp_path, monkeypatch):
    """失败也要留证：`<role>.failed.json` 里必须能看到逐档尝试。"""
    question = tmp_path / "q.md"
    question.write_text("问题", encoding="utf-8")

    def fake_call_once(messages, *, model, max_tokens, level, temperature,
                       timeout, api_key=None):
        return "", {"level": level, "elapsed_s": 1.0,
                    "error": "RemoteDisconnected: peer closed",
                    "finish_reason": "transport_error"}

    monkeypatch.setattr(C, "call_once", fake_call_once)
    out = tmp_path / "out"
    with pytest.raises(SystemExit):
        C.main(["--roles", "规格一致性", "--question", str(question),
                "--out", str(out), "--level", "high"])
    payload = json.loads(
        (out / "规格一致性.failed.json").read_text(encoding="utf-8"))
    assert payload["attempts"][0]["finish_reason"] == "transport_error"
    assert payload["attempts"][0]["level"] == "high"
