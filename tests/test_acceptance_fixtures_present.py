"""验收夹具必须在位——否则"知识栈的验收"会静默消失而不是变红。

为什么需要这个文件（两个并列的失败模式，都在本仓库真实发生过或真实可触发）：

1. **夹具缺失 ⇒ 一整套检查退化成 skip。** ``tests/`` 里有二十多处
   ``pytest.skip("索引未入库")`` 一类的守卫。它们本身是对的（夹具不在时"测不了"），
   但**没有任何东西要求夹具必须在位**。删掉 ``knowledge/hypergraph.*.jsonl``
   或 held-out 三件套之后：

   * pytest 仍然是绿的——那些用例整批变成 skip；
   * ``tools/run_tests.ps1`` 里 RK-13 从"实测失败"退化成"没有可用 oracle →
     not_measured"，链子照旧打印 ``All checks passed.``；
   * 净效果是"知识栈的验收被删掉了，而所有绿灯都还在"。

   §4.1b 硬规则 1 写的是"缺证据不得当作通过"。这里把"夹具在位"变成**可执行的
   前提**：缺任何一个 ⇒ pytest 红，而不是 skip。

2. **验收链的步骤可能"跑不起来/跑完不判"。** 2026-10-02 的
   ``a1fe8c4`` 就是一次真实事故：``run_tests.ps1`` 是 BOM-less UTF-8、
   Windows PowerShell 5.1 按 ANSI 解码，一个悬空的 GBK 前导字节吃掉了换行，
   整条 ``python tools/check_holdout.py`` 命令行**变成注释的一部分**；
   ``$LASTEXITCODE`` 还留着上一条命令的 0，于是脚本打印"门全过"、实际一次没跑。
   第二条用例按行判：命令必须出现在**活行**上（不是注释里），且后面紧跟退出码
   检查或失败归属。它对着的就是这个形状。
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------- #
# 一、夹具在位（缺 ⇒ 红，不 ⇒ skip）
# --------------------------------------------------------------------------- #
#: ``(相对路径, 这是什么, 谁依赖它)``。``who`` 写的是**真实消费者的名字**，
#: 这样失败信息能直接告诉下一个人"少了它会让哪一批检查变哑"，而不是一句"文件不存在"。
FIXTURES = [
    ("knowledge/hypergraph.nodes.jsonl", "超图节点表",
     "build_ledger / 词表 / 门③⑥⑩ / 检索"),
    ("knowledge/hypergraph.edges.jsonl", "超图边表",
     "门④⑤⑩ / Q1-Q7 / E3 / 检索（没有它 = 整个 hypergraph 后端为空）"),
    ("knowledge/hypergraph.manifest.json", "超图构建账本",
     "test_build_ledger / test_hypergraph_determinism（缺 ⇒ 3 条用例整批 skip）"),
    ("knowledge/hypergraph.vocab.json", "冻结词表快照",
     "test_knowledge_holdout_vocab / 门③"),
    ("knowledge/action_lexicon.json", "动作词表",
     "test_action_lexicon（缺 ⇒ 整文件 skip）"),
    ("knowledge/cases.jsonl", "L3 案例层",
     "case_block / E1-E3 / 三栏注入"),
    ("knowledge/card_scope.json", "卡片范围裁决（门⑥ 的分母）",
     "check_holdout --exclude-cards"),
    ("knowledge/sources.yaml", "来源清单",
     "authorship_report / 许可门 K2"),
    ("fixtures/knowledge_holdout.jsonl", "held-out oracle（Q0-Q7 的测量对象）",
     "holdout_score / 门①-⑩"),
    ("fixtures/knowledge_holdout.cards.json", "held-out 覆盖的卡片清单",
     "门⑥"),
    ("fixtures/knowledge_holdout.vocab.json", "held-out 词表快照",
     "门③"),
    ("fixtures/knowledge_holdout.assertable.json", "每类的可断言对数上限",
     "门④"),
    ("fixtures/knowledge_holdout.cards.covered.json", "已被条目覆盖的卡片清单",
     "card_scope_audit 的对照组"),
    ("fixtures/expected_sdl_long.json", "长剧本的 SDL 期望值",
     "gen_golden --check / 长基线"),
    ("fixtures/script_long_61.md", "61 镜长剧本",
     "§4.4 步骤 1 的 --script / gen_golden"),
]


def require_fixture(path, rel: str, what: str, who: str) -> None:
    """夹具判据本体（抽出来是为了能对**不存在的路径**自证它会开火）。"""
    assert path.is_file(), (
        f"{rel}（{what}）不在仓库里。依赖它的检查会退化成 skip / not_measured，"
        f"而链子依旧全绿——缺证据不是通过（§4.1b 硬规则 1）。消费者：{who}")
    assert path.stat().st_size > 0, f"{rel}（{what}）是空文件。消费者：{who}"


@pytest.mark.parametrize("rel,what,who", FIXTURES, ids=[item[0] for item in FIXTURES])
def test_acceptance_fixture_is_present_and_non_empty(rel, what, who):
    """每个夹具必须在位且非空——"缺了"要让 pytest 红，而不是让它 skip。"""
    require_fixture(ROOT / rel, rel, what, who)


@pytest.mark.parametrize("rel", [item[0] for item in FIXTURES
                                 if item[0].endswith(".jsonl")])
def test_jsonl_fixtures_parse_line_by_line(rel):
    """.jsonl 夹具必须**逐行可解析且至少一行**。

    空文件能过"存在且非空"之外的任何检查，会让依赖它的门在分母为 0 时
    悄悄"通过"（§4.1b 硬规则 1 的同一个洞）。
    """
    lines = [line for line in (ROOT / rel).read_text(encoding="utf-8").splitlines()
             if line.strip()]
    assert lines, f"{rel} 一行都没有"
    for number, line in enumerate(lines, 1):
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(f"{rel}:{number} 不是合法 JSON：{exc}")


def test_the_generated_card_corpus_is_committed():
    """生成卡语料（``knowledge/cards_generated/``）在库——门⑥ 与署名门的分母。"""
    directory = ROOT / "knowledge" / "cards_generated"
    assert directory.is_dir(), "knowledge/cards_generated/ 不在仓库里"
    cards = sorted(directory.glob("*.jsonl"))
    assert cards, "knowledge/cards_generated/ 里没有 .jsonl 语料"


def test_an_absent_fixture_makes_the_guard_fire(tmp_path):
    """自证：把夹具判据用在**一个不存在的路径**上必须"红"，不是静默。

    这条防的是"守卫本身变成橡皮章"——判据只有真的会开火才算判据。
    """
    missing = tmp_path / "not_here.jsonl"
    with pytest.raises(AssertionError) as excinfo:
        require_fixture(missing, "knowledge/not_here.jsonl", "演示夹具", "本用例")
    assert "not_here.jsonl" in str(excinfo.value)
    # 反面对照：同一判据对**真实存在的**夹具必须放行，否则它就是恒红。
    present = tmp_path / "here.jsonl"
    present.write_text("{}", encoding="utf-8")
    require_fixture(present, "here.jsonl", "演示夹具", "本用例")
    # 空文件也必须判红（存在 ≠ 可用）。
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(AssertionError) as excinfo:
        require_fixture(empty, "empty.jsonl", "空夹具", "本用例")
    assert "空文件" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 二、``pytest.skip`` 必须是条件调用
# --------------------------------------------------------------------------- #
def unconditional_skips(source: str, name: str = "<source>") -> list:
    """返回源码里**无条件** ``pytest.skip(...)`` 的位置。

    判据刻意保守：只要 `pytest.skip` 的祖先里有 ``if``/``for``/``while``
    就算"有条件"。跳过测试是允许的——**静默**跳过不允许（验收契约的红线：
    不得用跳过测试让套件变绿）。
    """
    tree = ast.parse(source, filename=name)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    guarded = (ast.If, ast.For, ast.AsyncFor, ast.While)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "skip"
                and isinstance(func.value, ast.Name) and func.value.id == "pytest"):
            continue
        cursor = parents.get(id(node))
        conditional = False
        while cursor is not None:
            if isinstance(cursor, guarded):
                conditional = True
                break
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                break
            cursor = parents.get(id(cursor))
        if not conditional:
            offenders.append(f"{name}:{node.lineno}")
    return offenders


def test_every_skip_in_the_suite_is_conditional():
    """``tests/`` 里不许出现无条件的 ``pytest.skip``（那会让套件凭空变绿）。"""
    offenders = []
    skip_sites = 0
    for path in sorted((ROOT / "tests").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        skip_sites += source.count("pytest.skip(")
        offenders += unconditional_skips(source, path.name)
    assert skip_sites, "tests/ 里连一个 skip 都没有？这条守卫就失去了对象，请复核判据"
    assert not offenders, (
        "pytest.skip 必须落在 if/for/while 里（夹具缺失时也要留下理由）："
        + ", ".join(offenders))


def test_the_skip_checker_fires_on_a_crafted_source():
    """自证：造一份"顶层 skip"的源码必须被判出来，条件 skip 必须放行。

    没有这条，"零违规"可能只是判据没在判东西（§B.5 的空断言问题）。
    """
    bad = "import pytest\n\ndef test_a():\n    pytest.skip('no reason')\n"
    good = ("import pytest\n\n\ndef test_a(path):\n"
            "    if not path:\n        pytest.skip('not here')\n")
    assert unconditional_skips(bad, "bad.py") == ["bad.py:4"]
    assert unconditional_skips(good, "good.py") == []
    # 模块级（连函数都没有）也要判出来。
    assert unconditional_skips("import pytest\npytest.skip('x')\n", "mod.py") == ["mod.py:2"]


# --------------------------------------------------------------------------- #
# 三、验收链的每一步都必须"活着并且会判"
# --------------------------------------------------------------------------- #
#: ``(命令片段, 这是哪一步)``。片段必须在**活行**上出现，且后面紧跟退出码
#: 检查或 ``Fail`` 归属——`a1fe8c4` 的事故形状（命令行被注释吃掉、退出码还留着
#: 上一条的 0）会被这条判出来。
CHAIN_STEPS = [
    ("tools/gen_specs.py --check", "spec 与代码不漂移"),
    ("tools/gen_golden.py --check", "golden 夹具不漂移"),
    ("-m pytest", "pytest 套件"),
    ("tools/holdout_score.py", "held-out 质量指标（RK-13 的测量）"),
    ("tools/check_holdout.py", "held-out 覆盖门（RK-13 的可用性）"),
    ("tools/knowledge/authorship_report.py", "署名门"),
]


def dead_chain_steps(text: str) -> list:
    """返回链里"不会跑"或"跑了不判"的步骤描述。空列表 = 每一步都活着且会判。"""
    lines = text.splitlines()
    problems = []
    for command, what in CHAIN_STEPS:
        hits = [number for number, line in enumerate(lines, 1) if command in line]
        if not hits:
            problems.append(f"{command} 不在链里（{what} 没跑 = 没测）")
            continue
        for number in hits:
            if lines[number - 1].strip().startswith("#"):
                problems.append(f"{number}: {command} 落在注释里，这一行不会执行")
                continue
            window = lines[number:number + 12]
            if not any(("$LASTEXITCODE" in item) or ("Fail " in item)
                       or ("Fail(" in item) for item in window):
                problems.append(f"{number}: {command} 之后没有退出码检查/失败归属")
    return problems


def test_the_acceptance_chain_runs_every_gate_and_judges_it():
    """``tools/run_tests.ps1`` 里每一步门命令都要**活着**且**会判**。"""
    chain = (ROOT / "tools" / "run_tests.ps1").read_text(encoding="utf-8")
    problems = dead_chain_steps(chain)
    assert not problems, "; ".join(problems)


def test_the_chain_checker_fires_on_the_a1fe8c4_shape():
    """自证：命令行被注释吃掉、退出码沿用旧值 —— 必须被判出来。"""
    swallowed = (
        "# NOTE: 中文注释块\n"
        "# ... # python tools/check_holdout.py fixtures/x.jsonl --out y.json\n"
        "$gateExit = $LASTEXITCODE\n"
        "python tools/gen_specs.py --check\n"
        "if ($LASTEXITCODE -ne 0) { Fail 'spec drift' }\n"
        "python tools/gen_golden.py --check\n"
        "if ($LASTEXITCODE -ne 0) { Fail 'golden drift' }\n"
        "python -m pytest\n"
        "if ($LASTEXITCODE -ne 0) { Fail 'pytest' }\n"
        "python tools/holdout_score.py --holdout x --json y\n"
        "$rk13Exit = $LASTEXITCODE\n"
        "python tools/knowledge/authorship_report.py --json z\n"
        "$authorshipExit = $LASTEXITCODE\n"
    )
    problems = dead_chain_steps(swallowed)
    assert any("注释" in item for item in problems), problems
    # 少了退出码检查的那种也要被抓到（"跑完不判"）。
    unjudged = swallowed.replace(
        "$gateExit = $LASTEXITCODE\n", "") + "\npython tools/check_holdout.py x\n"
    assert dead_chain_steps(unjudged), unjudged
