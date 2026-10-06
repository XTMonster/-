"""`e1_panel.preflight()`：**开跑前的握手**——评委不在就别开始那场长跑。

为什么要有它（2026-10-06 的实测事故）：`tools/knowledge/e1_labelfree_pool.py` 第一次跑 64 条时，
那个子进程里**没有 `GLM_API_KEY`** ⇒ `GLMClient` 每次立刻抛错 ⇒ 1,280 行全是"没判到"、
**四分钟就"跑完"**，汇总行写着 `labelfree_oracle 0.0` —— **看起来像灾难性读数、其实是仪器坏了**。

这些用例守住三件事：① 全通时**不误报**；② 抛错的评委被**具名**报出来；
③ 回了但**分不出来**（空正文）也算失败；④ 两个长跑工具**在握手失败时拒绝开跑**（退出码 3）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import e1_labelfree_pool as labelfree  # noqa: E402
from tools.knowledge import e1_panel  # noqa: E402
from tools.knowledge import e1_triple_search as triple  # noqa: E402


class _Client:
    """按 `user` 串里出现的 case_id 给分；`reply=None` 时装作回了个空包。"""

    def __init__(self, score=5, *, boom=False, reply=None):
        self.score = score
        self.boom = boom
        self.reply = reply
        self.calls = 0

    def chat_json(self, system, user, temperature, seed, num_ctx, key="", retries=1):
        self.calls += 1
        if self.boom:
            raise RuntimeError("缺少 GLM_API_KEY")
        if self.reply is not None:
            return self.reply
        ids = [line.split("｜")[0].strip()
               for line in user.splitlines() if "｜" in line]
        return {"scores": [{"case_id": cid, "score": self.score} for cid in ids]}


def test_preflight_passes_when_every_judge_answers():
    a, b = _Client(5), _Client(3)
    assert e1_panel.preflight([("m-a", a), ("m-b", b)]) == []
    assert (a.calls, b.calls) == (1, 1), "握手就是一人一次，不多不少"


def test_preflight_names_the_judge_that_raised():
    good, bad = _Client(5), _Client(boom=True)
    failures = e1_panel.preflight([("m-a", good), ("m-b", bad)])
    assert [f["judge"] for f in failures] == ["m-b"]
    assert "缺少 GLM_API_KEY" in failures[0]["error"], "错误原文要带出来，不许只说'失败'"


def test_preflight_treats_an_empty_reply_as_a_failure():
    """回了包但**分不出来**（空正文／形状不对）也要算失败——`judge` 会把它解析成 {}。"""
    failures = e1_panel.preflight([("m-a", _Client(reply={"cards": []}))])
    assert len(failures) == 1 and "no parsable score" in failures[0]["error"]


def test_preflight_uses_the_judge_itself_and_collects_no_reading():
    """握手走的是**同一个 `judge()`**（不是另写一份判分），且自检案例带 `preflight_` 前缀——
    它们**不可能**与真案例同 id，所以自检永远混不进任何分母。"""
    client = _Client(5)
    e1_panel.preflight([("m-a", client)])
    assert e1_panel.PREFLIGHT_QUERY.startswith("自检")
    sent = []

    class _Recorder(_Client):
        def chat_json(self, system, user, temperature, seed, num_ctx, key="", retries=1):
            sent.append(user)
            return super().chat_json(system, user, temperature, seed, num_ctx,
                                     key=key, retries=retries)

    e1_panel.preflight([("m-a", _Recorder(5))])
    assert "preflight_1" in sent[0] and "preflight_3" in sent[0]
    assert "没有" not in sent[0]


def _write_queries(tmp_path):
    path = tmp_path / "q.jsonl"
    path.write_text(json.dumps({"query": "zebra"}) + "\n", encoding="utf-8")
    return path


def test_labelfree_pool_refuses_to_start_when_preflight_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(labelfree.e1_panel, "preflight",
                        lambda clients: [{"judge": "glm-5.3", "error": "缺少 GLM_API_KEY"}])
    monkeypatch.setattr(labelfree.llm, "make_client", lambda *a, **k: object())
    monkeypatch.setattr(labelfree, "load_index", lambda *a, **k: object())
    out = tmp_path / "o.json"
    code = labelfree.main(["--queries", str(_write_queries(tmp_path)),
                           "--cases", str(tmp_path), "--out", str(out)])
    assert code == 3, "握手失败 ⇒ 拒绝开跑（不是跑完再报 0.0）"
    assert not out.exists(), "拒绝开跑时**不许**产出任何'读数'文件"


def test_triple_search_refuses_to_start_when_preflight_fails(tmp_path, monkeypatch):
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"query": "q1", "case_id": "c1", "score": 4.0}) + "\n",
                      encoding="utf-8")
    monkeypatch.setattr(triple.e1_panel, "preflight",
                        lambda clients: [{"judge": "glm-5.3", "error": "缺少 GLM_API_KEY"}])
    monkeypatch.setattr(triple.llm, "make_client", lambda *a, **k: object())
    out = tmp_path / "o.json"
    code = triple.main(["--labels", str(labels), "--cases", str(tmp_path),
                        "--out", str(out)])
    assert code == 3
    assert not out.exists()


def test_e1_panel_cli_refuses_to_start_when_preflight_fails(tmp_path, monkeypatch):
    """面板那条 CLI 一轮**一小时以上**，更不能等到跑完才发现评委不在。"""
    monkeypatch.setattr(e1_panel, "preflight",
                        lambda clients: [{"judge": "glm-5.3", "error": "缺少 GLM_API_KEY"}])
    monkeypatch.setattr(e1_panel.llm, "make_client", lambda *a, **k: object())
    class _DummyIndex:
        """面板 CLI 在握手之前只碰这几样（`path_label` 由 CLI 自己写上去）。"""

        cases: list = []
        search_zh: dict = {}
        fingerprint = ""

        def describe(self):
            return {}

    monkeypatch.setattr(e1_panel, "load_index", lambda *a, **k: _DummyIndex())
    out = tmp_path / "o.jsonl"
    code = e1_panel.main(["--queries", str(_write_queries(tmp_path)),
                          "--cases-dir", str(tmp_path), "--out", str(out)])
    assert code == 3
    assert not out.exists(), "拒绝开跑 ⇒ 不落任何打分文件"
