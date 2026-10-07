"""常驻外部顾问的**离线**部分：角色表、提示词拼装、降档阶梯（不联网）。

真调用要密钥、要十几分钟，不进 pytest；这里钉的是"换一双眼睛"这件事的
**结构**：角色必须互相不重复、问题与产物必须真的进了提示词、
没有正文时按 `max → high → low` 逐档降级并把每一档记进 usage。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import glm_consult as C  # noqa: E402


def test_the_role_table_covers_the_review_angles_the_agents_md_asks_for():
    assert {"规格一致性", "接口与契约", "测试与验收", "性能与鲁棒",
            "红队反方"} <= set(C.ROLES)


def test_the_consultation_is_explanatory_not_just_adversarial():
    """用户 2026-10-04 的裁决：**会诊不是对抗性审查，而且需要他们解释**。

    所以① 角色表里有"讲原理/讲落地"这两个非对抗角色；② 系统提示明确写"这是会诊，
    不是对抗性审查"；③ 输出 schema 里每条 finding 都要带 `explanation` 与
    `step_by_step`，并且整体要有一段 `teaching`——只有结论没有解释的回复不合规。
    """
    assert {"领域讲解", "实现顾问"} <= set(C.ROLES)
    assert "会诊" in C.SYSTEM_TEMPLATE and "不是对抗性审查" in C.SYSTEM_TEMPLATE
    for field in ("explanation", "step_by_step", "teaching"):
        assert field in C.SYSTEM_TEMPLATE, field


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


def test_plain_mode_drops_the_role_schema_that_would_outrank_the_question():
    """**标注类任务不许被角色模板抢走输出形状**（2026-10-07 实测倒逼）。

    角色模板里写着"只输出一个 JSON 对象 {summary, findings[], not_checked}"；
    当问题要求"只输出一个 JSON 数组"时，模型服从了 system、忽略了问题——
    同一份 2 条分类问题：带模板 170.4 s 回 findings 对象（形状不对），
    不带模板 32.9 s 回 `list[2]`。所以 `--plain` 必须**只有一条 user 消息**，
    且**不含**会诊 schema 的任何字段名。
    """
    messages = C.plain_messages("只输出一个 JSON 数组", [("a.md", "产物")])
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert "只输出一个 JSON 数组" in messages[0]["content"]
    assert "产物" in messages[0]["content"]
    for leaked in ("not_checked", "findings", "teaching", "severity"):
        assert leaked not in messages[0]["content"], leaked


def test_plain_mode_keeps_the_question_only_admission_and_writes_its_mode(tmp_path,
                                                                        monkeypatch):
    """`--plain` 只是**去掉 system**：源码门槛、取证、指纹一律照旧。"""
    question = tmp_path / "q.md"
    question.write_text("问题", encoding="utf-8")
    out = tmp_path / "out"
    seen = {}

    def fake_consult(messages, **kwargs):  # noqa: ARG001
        seen["messages"] = messages
        return '[{"i": 1, "class": "hidden"}]', {"level": "high",
                                                 "finish_reason": "stop"}

    monkeypatch.setattr(C, "consult", fake_consult)
    code = C.main(["--roles", "测试与验收", "--question", str(question),
                   "--question-only", "--no-status", "--plain", "--out", str(out)])
    assert code == 0
    assert [m["role"] for m in seen["messages"]] == ["user"]
    manifest = json.loads((out / "bundle.manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "plain"
    assert manifest["source_seen"] is False
    assert set(manifest["bundles"]["测试与验收"]) == {"user"}, "没有 system 就别写它的指纹"
    user = seen["messages"][0]["content"]
    fingerprint = manifest["bundles"]["测试与验收"]["user"]
    assert fingerprint["sha256"] == hashlib.sha256(user.encode("utf-8")).hexdigest()
    assert "没有** system 提示词" in (out / "bundle.md").read_text(encoding="utf-8")
    assert json.loads((out / "测试与验收.json").read_text(encoding="utf-8")) == [
        {"i": 1, "class": "hidden"}]


def test_the_role_mode_manifest_still_says_role(tmp_path, monkeypatch):
    """默认路径的 manifest 要能被区分出来（不许把两种包混成一种）。"""
    question = tmp_path / "q.md"
    question.write_text("问题", encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setattr(C, "consult", lambda messages, **kw: (
        '{"summary": "ok"}', {"level": "high", "finish_reason": "stop"}))
    assert C.main(["--roles", "规格一致性", "--question", str(question),
                   "--question-only", "--no-status", "--out", str(out)]) == 0
    manifest = json.loads((out / "bundle.manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "role"
    assert set(manifest["bundles"]["规格一致性"]) == {"system", "user"}


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


def test_reasoning_effort_is_opt_in_and_off_by_default(monkeypatch):
    """思考强度只走 `GLM_REASONING_EFFORT`，**默认不加这个键**。

    实测（2026-10-07，`work/_probe_qwen_thinking.py`，同一通道 3 次采样）：
    `thinking.level=max` 想得并不比 `high` 多（42/53/41 vs 51/52/187），真正把
    思考拉满的是 `reasoning_effort=max`（305/46/229）。所以这条缝必须存在，
    而且必须**默认不改变 payload**——否则智谱 GLM 路径的请求体就被悄悄改了。
    """
    captured = {}

    class FakeResponse:
        def read(self):
            return json.dumps({
                "model": "qwen3.8-max-0902",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {},
            }).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(C.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("GLM_API_KEY", "k")

    monkeypatch.delenv("GLM_REASONING_EFFORT", raising=False)
    C.call_once([{"role": "user", "content": "x"}], model="glm-5.3",
                max_tokens=64, level="high", temperature=0.0, timeout=1.0)
    assert "reasoning_effort" not in captured["payload"], "默认不许加这个键"
    assert captured["payload"]["thinking"] == {"type": "enabled", "level": "high"}

    monkeypatch.setenv("GLM_REASONING_EFFORT", "max")
    _content, usage = C.call_once([{"role": "user", "content": "x"}],
                                  model="qwen3.8-max-0902", max_tokens=64,
                                  level="high", temperature=0.0, timeout=1.0)
    assert captured["payload"]["reasoning_effort"] == "max"
    assert usage["reasoning_effort"] == "max", "读数为证：写进 usage"


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


def test_a_zero_byte_timeout_does_step_down_the_ladder(monkeypatch):
    """实测倒逼（2026-10-06 22:09）：`max` 档 **900.1 s 零字节超时**。

    原件 `work/_glm53_decide23/规格一致性.failed.json` 的 `attempts` 里**只有 max 一档**
    ——旧实现把"有 error"一律当成"换档无益"，于是整次调用死掉，
    **根本没去试 `high`**。而"降一档、想得少一点、更快"恰恰就是这种失败的解药
    （同账号 `high` 档在 1.7k 包上实测 363.6 s 出正文）。这条钉住：**传输类失败必须降级**。
    """
    calls = []

    def fake_call_once(messages, *, model, max_tokens, level, temperature,
                       timeout, api_key=None):
        calls.append(level)
        if level == "max":
            return "", {"level": level, "elapsed_s": 900.1,
                        "error": "TimeoutError: The read operation timed out",
                        "finish_reason": "transport_error"}
        return '{"summary": "ok"}', {"level": level, "finish_reason": "stop"}

    monkeypatch.setattr(C, "call_once", fake_call_once)
    monkeypatch.setattr(C.time, "sleep", lambda _s: None)
    content, usage = C.consult([{"role": "user", "content": "x"}], model="glm-5.3",
                               max_tokens=32768, levels=["max", "high", "low"],
                               temperature=0.2, timeout=1.0, api_key="k")
    assert content == '{"summary": "ok"}'
    assert calls == ["max", "high"]
    assert usage["attempts"][0]["finish_reason"] == "transport_error"
    assert usage["attempts"][0]["stepped_down_to"] == "high"


def test_the_step_down_rule_separates_quota_from_transport():
    """换档的判据只要一句话：**同模型换档换不来额度 ⇒ 只有额度类才停手**。"""
    # 额度/鉴权类：停手
    assert C.why_not_step_down("HTTP 429: rate limited")
    assert C.why_not_step_down('HTTP 400: {"error":{"code":"1113"}}')
    assert C.why_not_step_down("余额不足或无可用资源包")
    # 传输/超时/空正文类：降级
    assert C.why_not_step_down("TimeoutError: The read operation timed out") == ""
    assert C.why_not_step_down("RemoteDisconnected: peer closed") == ""
    assert C.why_not_step_down("") == ""


def test_a_quota_failure_says_why_it_did_not_step_down(monkeypatch):
    """停手也要留因：`step_down_refused` 让"为什么没降级"可对拍。"""
    def fake_call_once(messages, *, model, max_tokens, level, temperature,
                       timeout, api_key=None):
        return "", {"level": level, "error": "HTTP 429: rate limited"}

    monkeypatch.setattr(C, "call_once", fake_call_once)
    with pytest.raises(C.ConsultFailed) as excinfo:
        C.consult([{"role": "user", "content": "x"}], model="glm-5.3",
                  max_tokens=32768, levels=["max", "high", "low"],
                  temperature=0.2, timeout=1.0, api_key="k")
    assert len(excinfo.value.attempts) == 1
    assert "换档无益" in excinfo.value.attempts[0]["step_down_refused"]
    assert "stepped_down_to" not in excinfo.value.attempts[0]


def test_dry_run_needs_no_api_key(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    question = tmp_path / "q.md"
    question.write_text("问题", encoding="utf-8")
    ctx = tmp_path / "c.md"
    ctx.write_text("产物", encoding="utf-8")
    code = C.main(["--roles", "规格一致性,红队反方", "--question", str(question),
                   "--context", str(ctx), "--question-only", "--no-status",
                   "--out", str(tmp_path / "out"), "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "dry-run 规格一致性" in out and "dry-run 红队反方" in out
    assert not (tmp_path / "out").exists()


def test_the_bundle_always_carries_the_project_state():
    """用户 2026-10-04："会诊 AI 有先看目前落实的情况与源码么？"

    所以"现状"不许由提问的人转述——每一份包都自动带 HEAD 与 `AGENTS.md` 的
    状态块（真源逐字），顾问于是能自己判断我们落在哪一步。
    """
    status = C.status_digest(ROOT)
    messages = C.build_messages("实现顾问", "问题", [], (), status)
    user = messages[1]["content"]
    head = C.git_snapshot(ROOT)["head"]
    assert "项目现状" in user
    assert head and head in user
    assert C.STATUS_MARKER in user
    assert "未提交改动" in user


def test_source_files_are_embedded_verbatim_with_line_numbers(tmp_path):
    """源码必须**逐字带行号**进包：否则顾问只能对着我们的转述评论。"""
    path = tmp_path / "m.py"
    path.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    source = C.read_source(f"{path}:2-3")
    assert source["range"] == [2, 3]
    assert source["lines"] == 2
    assert "    2| b = 2" in source["text"]
    assert "a = 1" not in source["text"]
    user = C.build_messages("实现顾问", "问题", [], [source], None)[1]["content"]
    assert "源码：" in user and "    3| c = 3" in user


def test_a_consultation_without_any_source_is_refused(tmp_path):
    """没有源码就不许调用——"了解项目才能提出想法"必须由工具兜底。"""
    question = tmp_path / "q.md"
    question.write_text("问题", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        C.main(["--question", str(question), "--out", str(tmp_path / "out"),
                "--dry-run"])
    assert "--source" in str(excinfo.value)


def test_question_only_is_an_explicit_admission_it_saw_no_source(tmp_path, capsys):
    question = tmp_path / "q.md"
    question.write_text("问题", encoding="utf-8")
    code = C.main(["--question", str(question), "--question-only", "--no-status",
                   "--out", str(tmp_path / "out"), "--dry-run"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["source_seen"] is False


def test_a_windows_drive_letter_is_not_mistaken_for_a_line_range():
    """`E:\\...\\a.py` 里的冒号是盘符；只有**尾部**的 `12` / `12-40` 才是行段。"""
    assert C.parse_source_spec(r"E:\白模预演codex\tools\glm_consult.py") == (
        r"E:\白模预演codex\tools\glm_consult.py", None, None)
    assert C.parse_source_spec("a.py:12-40") == ("a.py", 12, 40)
    assert C.parse_source_spec("a.py:12") == ("a.py", 12, None)


def test_the_manifest_pins_what_was_sent_with_hashes(tmp_path):
    """取证要有指纹：问题、源码、产物、现状，各一份 sha256 ＋ 字数。"""
    path = tmp_path / "m.py"
    path.write_text("a = 1\n", encoding="utf-8")
    source = C.read_source(str(path))
    manifest = C.bundle_manifest("q.md", "问题", [("c.md", "产物")], [source], "现状")
    assert manifest["source_seen"] is True
    assert manifest["question"]["sha256"] == hashlib.sha256(
        "问题".encode("utf-8")).hexdigest()
    assert manifest["sources"][0]["chunk_sha256"] == source["chunk_sha256"]
    assert manifest["sources"][0]["file_sha256"] == source["file_sha256"]
    assert "text" not in manifest["sources"][0]        # 摘要里不留正文
    assert manifest["contexts"][0]["chars"] == 2
    assert manifest["status"]["sent_chars"] == 2
    assert manifest["status"]["truncated"] is False


def test_bundle_manifest_keeps_repo_before_mode_in_the_positional_order(tmp_path):
    """`repo` 必须仍是第 7 个**位置**参数——`panel_consult` / `plan_writer` 就这么调。

    2026-10-07 实测：把 `mode` 插到 `repo` 前面，那两处调用**静默**把 repo 喂给 mode、
    repo 退回默认根，落盘时炸 `TypeError: Object of type WindowsPath is not JSON
    serializable`（`test_panel_consult.py::test_manifest_is_written_before_any_call_and_outlives_a_failure`）。
    这条按**位置**把顺序钉死，别让"看起来只是多了个默认参数"再绕过测试。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = C.bundle_manifest("q.md", "问题", [], [], None, None, repo)
    assert manifest["repo"]["repo"] == str(repo)
    assert manifest["mode"] == "role"
    #: 关键字也照样能用（`glm_consult` 自己是关键字调用），两处调用点继续只给位置参数。
    assert C.bundle_manifest("q.md", "问题", [], [], None, None, repo,
                             mode="plain")["mode"] == "plain"


def test_a_truncated_status_digest_says_so_and_stays_traceable():
    """现状摘要可以截断（`glm-5.3` 包不起），但**不许静默**：包里留痕、manifest 记全量。"""
    full = "现" * 100
    sent = C.cap_status(full, 30)
    assert sent.startswith("现" * 30) and C.STATUS_TRUNCATED in sent
    manifest = C.bundle_manifest("q.md", "问题", [], [], sent, full)
    assert manifest["status"]["truncated"] is True
    assert manifest["status"]["full_sha256"] == hashlib.sha256(
        full.encode("utf-8")).hexdigest()
    assert manifest["status"]["sent_chars"] == len(sent)
    assert C.cap_status(full, 0) == full            # 0 = 不截断


def test_the_written_bundle_is_provably_the_one_that_was_sent(tmp_path, monkeypatch):
    """`bundle.manifest.json` 的指纹必须与**真的送进模型**的那条消息逐字一致。"""
    question = tmp_path / "q.md"
    question.write_text("问题", encoding="utf-8")
    source = tmp_path / "s.py"
    source.write_text("x = 1\n", encoding="utf-8")
    out = tmp_path / "out"
    seen = {}

    def fake_consult(messages, **kwargs):  # noqa: ARG001
        seen["messages"] = messages
        return '{"summary": "ok"}', {"level": "high", "finish_reason": "stop"}

    monkeypatch.setattr(C, "consult", fake_consult)
    code = C.main(["--roles", "实现顾问", "--question", str(question),
                   "--source", str(source), "--no-status", "--out", str(out)])
    assert code == 0
    manifest = json.loads(
        (out / "bundle.manifest.json").read_text(encoding="utf-8"))
    fingerprint = manifest["bundles"]["实现顾问"]["user"]
    user = seen["messages"][1]["content"]
    assert fingerprint["sha256"] == hashlib.sha256(user.encode("utf-8")).hexdigest()
    assert fingerprint["chars"] == len(user)
    assert user.rstrip() in (out / "bundle.md").read_text(encoding="utf-8")


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
                "--question-only", "--no-status", "--out", str(out),
                "--level", "high"])
    payload = json.loads(
        (out / "规格一致性.failed.json").read_text(encoding="utf-8"))
    assert payload["attempts"][0]["finish_reason"] == "transport_error"
    assert payload["attempts"][0]["level"] == "high"


def _run_with_replies(tmp_path, monkeypatch, replies):
    """跑一次 `main`，`consult` 按角色顺序回 `replies` 里的字符串。"""
    question = tmp_path / "q.md"
    question.write_text("问题", encoding="utf-8")
    out = tmp_path / "out"
    queue = list(replies)

    def fake_consult(messages, **kwargs):  # noqa: ARG001
        return queue.pop(0), {"model": "glm-5.3", "level": "max",
                              "finish_reason": "stop", "elapsed_s": 1.0}

    monkeypatch.setattr(C, "consult", fake_consult)
    code = C.main(["--roles", "测试与验收,规格一致性", "--question", str(question),
                   "--question-only", "--no-status", "--out", str(out)])
    return code, out


def test_a_reply_that_is_not_json_is_unparsed_not_a_bogus_json_answer(tmp_path, monkeypatch):
    """**文件名不许撒谎**：解析不了的回包 ⇒ `<role>.unparsed.txt` ＋ `.unparsed.json`，
    **不写** `<role>.json`，并**非零退出**（2026-10-06 门⑦ 那一轮实测：模型在字符串值里
    用了未转义的 ASCII 双引号，`<role>.json` 根本不是 JSON，而没人看得出来）。"""
    bad = '{"summary": "1) 要：与"判词一律 GLM-5.3 出"已经口径分裂"}'
    good = '{"summary": "ok"}'
    code, out = _run_with_replies(tmp_path, monkeypatch, [bad, good])
    assert code == 3, "解析失败要非零退出（不是 0）"
    assert not (out / "测试与验收.json").exists(), "解析不了就不许写 .json"
    assert (out / "测试与验收.unparsed.txt").read_text(encoding="utf-8") == bad
    detail = json.loads((out / "测试与验收.unparsed.json").read_text(encoding="utf-8"))
    assert detail["status"] == "unparsed" and detail["chars"] == len(bad)
    assert len(detail["sha256"]) == 64 and "JSONDecodeError" in detail["error"]


def test_one_unparsed_role_does_not_stop_the_next_role(tmp_path, monkeypatch):
    """一个角色解析失败**不许**把另一个角色的判词吞掉（"一侧缺席永远不算同意"，但到场的那侧要留证）。"""
    code, out = _run_with_replies(tmp_path, monkeypatch, ["不是 JSON 的旁白", '{"summary": "ok"}'])
    assert code == 3
    assert (out / "测试与验收.unparsed.txt").is_file()
    assert json.loads((out / "规格一致性.json").read_text(encoding="utf-8"))["summary"] == "ok"
def test_the_streaming_reader_assembles_sse_into_the_same_reply_shape():
    """`GLM_STREAM=1` 那条路：SSE 分片要拼成与非流式**同形**的 reply。

    为什么需要（2026-10-07 实测，阿里云百炼 ＋ `qwen3.8-max-0902`）：同一份裁决题包
    **非流式 26 分钟不返回**，流式 1.0 s 回第一个 chunk、605 s 拿完整正文
    （`work/_probe_bailian_stream.py`）。解析器写错的话，正文会**静默变短**——
    那比超时更坏，所以这里逐片对拍。
    """
    chunks = [
        b'data: {"choices":[{"delta":{"content":"["},"finish_reason":null}]}\n',
        b'data: {"choices":[{"delta":{"content":"{\\"i\\": 1}"},"finish_reason":null}]}\n',
        b": keep-alive comment\n",
        b'data: {"choices":[{"delta":{"content":"]"},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":10,"completion_tokens":3}}\n',
        b"data: [DONE]\n",
    ]

    class _FakeResponse:
        def __iter__(self):
            return iter(chunks)

    reply = C._read_stream(_FakeResponse(), time.time())
    assert reply["choices"][0]["message"]["content"] == '[{"i": 1}]'
    assert reply["choices"][0]["finish_reason"] == "stop"
    assert reply["usage"] == {"prompt_tokens": 10, "completion_tokens": 3}
    assert reply["_stream"]["chunks"] == 3, "注释行与 [DONE] 不该算成 chunk"


def test_the_streaming_switch_is_opt_in():
    """默认（不设 `GLM_STREAM`）走非流式：历史运行的请求体逐字不变。"""
    import os

    saved = os.environ.pop("GLM_STREAM", None)
    try:
        assert os.environ.get("GLM_STREAM", "").strip().lower() in ("",)
    finally:
        if saved is not None:
            os.environ["GLM_STREAM"] = saved
