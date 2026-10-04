"""Q5 的**运行侧 join**（§4.1b 第二步）：真的能算，且算不出来时如实说原因。

背景：Q5 以前只实现了第一步（夹具下界）。第二步是"把真实运行里逐镜的
`SceneContract` 查询串与本条 `q` 按**键值对集合相等**对起来"——没有这一步，
夹具再全也只是个摆设。本文件钉住四件事：

* 逐镜查询串由**同一个生产者**（`scene_contract.shot_constraint_query`）产出，
  测试拿 `shots.json` 的真实字段形状复算一遍（`镜头` 由取景求解器后补，
  `对白=dialogue`、运镜走 `movements[].kind`）；
* 别名/全半角归一后 `static` 与 `固定` 是同一个值（否则一边写引擎名、一边写
  中文别名的 oracle 永远 join 不上，这是实测踩过的死值）；
* 分母为 0 **判失败**（§4.1b 硬规则 1）并**报出真实发出的契约串**，绝不当成"通过"；
* 判据是**相等**，子集匹配只作诊断单独记账（放宽判据不许偷偷变成分子）；
* 这份运行证据**属于哪一代索引**：`shots.json` 的 `knowledge` 块必须与
  `knowledge/hypergraph.manifest.json` 的指纹对得上，否则记
  `stale_evidence` ＋ `not_measured`（2026-10-03：盘上那份旧证据就是这么被
  钉住的——否则"拿旧索引的运行去 join 新 oracle"会量出一个假的 0）；
* join 键是**真实发出**的那条串（`audit_log.jsonl` 的 `retrieval_call` 事件），
  不是从 `shots.json` 重推的：通道与漂移另见 `tests/test_q5_audit_channel.py`。
  本文件里那些"算术"用例就用 `_emit_from_plan()` 造一份**零漂移**的运行
  （发出的就是重推的那条），好让它们只考算术、不考通道。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import quality as Q  # noqa: E402

LIVE_MANIFEST = ROOT / "knowledge" / "hypergraph.manifest.json"
#: 案例索引是**分片**布局（`knowledge/cases/part-*.jsonl`）——传索引目录。
LIVE_CASES = ROOT / "knowledge"


def _live_knowledge(**overrides) -> dict:
    """一份**与当前索引同代**的 `knowledge` 块（`driver.py` 的真实形状）。"""
    from block_director.knowledge.cases import manifest_fingerprint as cases_fp
    from block_director.knowledge.hypergraph import (
        manifest_fingerprint as hg_fp,
    )

    block = {"hypergraph_fingerprint": hg_fp(LIVE_MANIFEST.parent),
             #: `LIVE_CASES` 是**索引目录**（分片布局），所以指纹取它自己。
             "cases_index_fingerprint": cases_fp(LIVE_CASES),
             "cases_backend": "hybrid"}
    block.update(overrides)
    return block


def _shot(shot_id, *, shot_type="MCU", lens=50.0, movements=(), actions=(),
          dialogues=()) -> dict:
    return {
        "shot_id": shot_id,
        "shot_type": shot_type,
        "camera": {"lens": lens},
        "movements": [{"kind": kind} for kind in movements],
        "action_types": list(actions),
        "dialogue_ids": list(dialogues),
    }


def test_the_declared_technique_reaches_the_query_that_gets_emitted():
    """剧本**声明**的拍摄手法必须进逐镜契约串——它是检索前已知的输入。

    实测缺陷（2026-10-03）：`shotlist_market` 第 1 镜写"拍摄手法：固定镜头"，
    `_map_camera_move` 把它折成 `static`，而 `_pin_declared_camera` 明确跳过
    `static`（引擎的 24 种运镜里没有"不动"）。于是这一镜真实发出的契约串只有
    `景别=MCU`：超图那一栏拿不到"固定机位该怎么构图"那族边（含禁忌）。

    修法是把**声明**钉进计划（`ShotPlan.declared_camera_move`），由契约串那一侧
    折到**查询**词表（`static` → `固定`）；引擎词表与查询词表本来就不是一回事，
    前者是"能不能做"，后者是"要不要找"。
    """
    from block_director.contracts.enums import ShotType
    from block_director.contracts.plan import ShotPlan
    from block_director.layer5_orchestrator.scene_contract import (
        shot_constraint_query,
    )

    shot = ShotPlan(shot_id="shot_001", intent="建立", shot_type=ShotType.MCU,
                    duration_frames=120, declared_camera_move="static")
    assert shot_constraint_query(shot) == "景别=MCU；运镜=固定", (
        "声明是 static 时必须折成查询词表的 `固定`，否则这一镜一个运镜种子都没有")

    # 计划自己排的运镜**另算一个值**：声明与落实不同时两个都要挂在查询里
    # （`per_kind=3`），因为"剧本要固定、计划改成推镜"恰恰是这一镜的真实形态。
    shot.camera = {"lens": 50.0, "movements": [{"type": "dolly_in"}]}
    assert shot_constraint_query(shot) == "景别=MCU；运镜=固定；镜头=50mm；运镜=dolly_in"

    # 两侧相同时去重（同一个值不该在查询里出现两次）。
    same = ShotPlan(shot_id="shot_002", intent="推进", shot_type=ShotType.MS,
                    duration_frames=96, declared_camera_move="dolly_in",
                    camera={"movements": [{"type": "dolly_in"}]})
    assert shot_constraint_query(same) == "景别=MS；运镜=dolly_in"

    # 负对照：没有声明就**不许**凭空加一个 `运镜=`（那会造出永不命中的种子）。
    bare = ShotPlan(shot_id="shot_003", intent="收束", shot_type=ShotType.CU,
                    duration_frames=72)
    assert shot_constraint_query(bare) == "景别=CU"


def _write(tmp_path: pathlib.Path, shots, *, knowledge="live") -> pathlib.Path:
    path = tmp_path / "shots.json"
    payload = {"shots": shots}
    if knowledge is not None:
        payload["knowledge"] = (_live_knowledge() if knowledge == "live"
                                else knowledge)
    path.write_text(json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _emit_from_plan(tmp_path: pathlib.Path, shots) -> pathlib.Path:
    """造一份**零漂移**的 `audit_log.jsonl`：每镜发出的就是重推的那条串。

    这样本文件的算术用例与通道解耦（通道本身由
    `tests/test_q5_audit_channel.py` 钉住），而不是"因为没给审计日志所以跳过"。
    """
    path = tmp_path / "audit_log.jsonl"
    lines = [json.dumps({
        "kind": "retrieval_call", "run_id": "ut-run", "level": "info",
        "data": {"event": "retrieval_call", "scope": "shot",
                 "shot_id": record["shot_id"],
                 "query": Q.plan_query_of_shot(record)}},
        ensure_ascii=False) for record in shots]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _join(entries, shots, audit):
    """链上的真实调用形状：shots ＋ audit ＋ 现行索引路径（代际可对拍）。"""
    return Q.q5_run_join(entries, shots, audit_path=audit,
                         manifest_path=LIVE_MANIFEST, cases_path=LIVE_CASES)


def _run(tmp_path: pathlib.Path, shots, *, knowledge="live"):
    """写一份 `shots.json` ＋ 与它**零漂移**的 `audit_log.jsonl`。"""
    return _write(tmp_path, shots, knowledge=knowledge), _emit_from_plan(tmp_path, shots)


def test_the_plan_query_comes_from_the_same_producer_as_the_contract():
    """正对照：`shots.json` 的字段被折成契约串，且折法与引擎同源。"""
    record = _shot("shot_001", shot_type="CU", lens=85.0,
                   movements=["dolly_in"], dialogues=["d1"])
    assert Q.plan_query_of_shot(record) == "景别=CU；镜头=85mm；运镜=dolly_in；对白=dialogue"


def test_a_shot_without_a_lens_or_extras_is_only_the_shot_size():
    """负对照：没有焦距、没有运镜/动作/对白时，契约串只剩景别——不许伪造键。"""
    assert Q.plan_query_of_shot(_shot("shot_002", shot_type="ELS", lens=None)) == "景别=ELS"


def test_a_locked_off_shot_is_static_and_can_satisfy_the_expectation(tmp_path):
    """一条运镜都没排 = 机位锁死 = 词表里的 `固定`；作者期望 `固定` 时命中。"""
    shots, audit = _run(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0)])
    entries = [{"id": "hq_1", "q": "景别=MS；镜头=50mm", "expect_movements": ["固定"]}]
    report = _join(entries, shots, audit)
    assert report["denominator"] == 1
    assert report["numerator"] == 1
    assert report["status"] == Q.PASS


def test_equality_join_honours_movement_aliases(tmp_path):
    """`static` / `fixed` 与中文规范值 `固定` 归一后算同一个值（实测踩过的死值）。"""
    shots, audit = _run(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0,
                                         movements=["static"])])
    entries = [{"id": "hq_1", "q": "景别=MS；镜头=50mm；运镜=static",
                "expect_movements": ["固定"]}]
    report = _join(entries, shots, audit)
    assert report["denominator"] == 1
    assert report["numerator"] == 1
    assert report["status"] == Q.PASS


def test_a_shot_that_declares_no_movement_does_not_satisfy_the_expectation(tmp_path):
    """负对照：作者期望 `dolly_in`、而这一镜一条运镜都没排 → 分子不进。"""
    shots, audit = _run(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0)])
    entries = [{"id": "hq_1", "q": "景别=MS；镜头=50mm", "expect_movements": ["dolly_in"]}]
    report = _join(entries, shots, audit)
    assert report["denominator"] == 1
    assert report["numerator"] == 0
    assert report["status"] == Q.FAIL


def test_a_movement_that_is_not_an_alias_is_never_folded_into_static(tmp_path):
    """分子上的真实缺陷（2026-10-03 抓到）：`VALUE_ALIASES` 是**部分**别名表，
    `dolly_in` 不在表里——旧写法把它折成空串再丢掉，于是每一镜都被当成"锁死"
    （`固定`），作者期望 `固定` 的条目会被 `dolly_in` 的镜头**骗成命中**。"""
    shots, audit = _run(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0,
                                         movements=["dolly_in"])])
    entries = [{"id": "hq_static", "q": "景别=MS；镜头=50mm；运镜=dolly_in",
                "expect_movements": ["固定"]},
               {"id": "hq_dolly", "q": "景别=MS；镜头=50mm；运镜=dolly_in",
                "expect_movements": ["dolly_in"]}]
    report = _join(entries, shots, audit)
    assert report["denominator"] == 2       # 两条 oracle 的 q 都等于发出串
    assert report["numerator"] == 1         # 只有期望 dolly_in 的那条命中
    assert [item["entry"] for item in report["matched_shots"]] == [
        "hq_static", "hq_dolly"]


def test_zero_matches_after_a_measured_run_is_a_failure(tmp_path):
    """分母为 0 且**这一跑真的发过**逐镜查询：按硬规则 1 判失败，并把发出串报出来。"""
    shots, audit = _run(tmp_path, [_shot("shot_001", shot_type="MCU", lens=50.0,
                                         dialogues=["d1"])])
    entries = [{"id": "hq_1", "q": "景别=MCU；镜头=50mm", "expect_movements": ["固定"]}]
    report = _join(entries, shots, audit)
    assert report["status"] == Q.FAIL
    assert report["denominator"] == 0
    # 相等判据 0 命中，但子集判据命中 1 条——两个数**分开**报，不许混。
    assert report["subset_denominator"] == 1
    assert report["emitted_queries"] == {
        "shot_001": ["景别=MCU；镜头=50mm；对白=dialogue"]}
    assert "硬规则 1" in report["note"]


def test_entries_without_expect_movements_never_enter_the_join(tmp_path):
    """没有 `expect_movements` 的条目（其余 2800+ 条）不是 Q5 的样本。"""
    shots, audit = _run(tmp_path, [_shot("shot_001")])
    entries = [{"id": "hq_1", "q": "景别=MCU；镜头=50mm"}]
    report = _join(entries, shots, audit)
    assert report["fixture_entries"] == 0
    assert report["denominator"] == 0


def test_the_shipped_plan_shaped_entries_are_really_plan_shaped():
    """入库 oracle 里那一批必须是**计划形状**（键 ⊆ 生产者会产出的键）。"""
    from tools.holdout_score import load_holdout

    entries = load_holdout(ROOT / "fixtures" / "knowledge_holdout.jsonl")
    shaped = [entry for entry in entries if Q._normalise_query_pairs(entry.get("q"))]
    shaped = [entry for entry in shaped
              if {key for key, _value in Q._normalise_query_pairs(entry["q"])}
              <= set(Q.PLAN_QUERY_KEYS)]
    # §4.1b 的 Q5 夹具侧下界是 30；这一批就是它能用的全部样本。
    assert len(shaped) >= Q.MIN_Q5_FIXTURE_ITEMS


# ------------------------------------------------ 运行证据的代际（不许过期当现行）


def test_the_run_report_carries_the_index_fingerprint():
    """`driver.py` 的运行结果必须有 `knowledge.hypergraph_fingerprint`，
    且它就是 `knowledge/hypergraph.manifest.json` 的那一个（单一真源）。"""
    from block_director.knowledge.hypergraph import manifest_fingerprint
    from block_director.knowledge.retriever import KnowledgeRetriever

    described = KnowledgeRetriever().describe()
    live = manifest_fingerprint(LIVE_MANIFEST.parent)
    assert live, "入库索引必须带指纹：没有它，运行证据无法证明代际"
    assert described["hypergraph_fingerprint"] == live


def test_a_run_without_the_index_fingerprint_is_not_evidence(tmp_path):
    """负对照：旧版运行结果里**没有**这个字段（2026-10-03 之前的产物）——
    即使算术上命中，也不许判过，只能记 `stale_evidence`。"""
    shots, audit = _run(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0)],
                        knowledge={"cases_backend": "hybrid"})
    entries = [{"id": "hq_1", "q": "景别=MS；镜头=50mm", "expect_movements": ["固定"]}]
    report = _join(entries, shots, audit)
    assert report["status"] == Q.NA
    assert report["stale_evidence"] is True
    assert "hypergraph_fingerprint" in report["note"]
    # 算术仍然报出来——但状态是"测不了"，不是"通过"。
    assert report["denominator"] == 1
    assert report["numerator"] == 1


def test_a_run_from_another_index_generation_is_stale(tmp_path):
    """负对照：指纹对不上 = 上一代索引跑出来的证据（`docs/evidence/20261002_real/`
    就是这个形状）——分子分母照报，状态记 `not_measured`。"""
    shots, audit = _run(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0)],
                        knowledge=_live_knowledge(hypergraph_fingerprint="0" * 64))
    entries = [{"id": "hq_1", "q": "景别=MS；镜头=50mm", "expect_movements": ["固定"]}]
    report = _join(entries, shots, audit)
    assert report["status"] == Q.NA
    assert report["stale_evidence"] is True
    assert "上一代索引" in report["note"]


def test_a_run_with_the_case_lane_off_is_not_stale(tmp_path):
    """正对照：`cases_backend=off` 是用户显式关闭（§2.3b），案例指纹本来就空——
    那不是过期，不许把它判成 stale。"""
    shots, audit = _run(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0)],
                        knowledge=_live_knowledge(cases_backend="off",
                                                  cases_index_fingerprint=""))
    entries = [{"id": "hq_1", "q": "景别=MS；镜头=50mm", "expect_movements": ["固定"]}]
    report = _join(entries, shots, audit)
    assert not report.get("stale_evidence")
    assert report["status"] == Q.PASS


def test_a_stale_run_never_shows_up_as_a_pass_in_the_metric(tmp_path):
    """`q5_movement_hit` 这一层也要如实透传：不许把 stale 的运行读成通过。"""
    shots, audit = _run(tmp_path, [_shot("shot_001", shot_type="MS", lens=50.0)],
                        knowledge=_live_knowledge(hypergraph_fingerprint="0" * 64))
    entries = [{"id": f"hq_{index}", "q": "景别=MS；镜头=50mm",
                "expect_movements": ["固定"]} for index in range(30)]
    metric = Q.q5_movement_hit(entries, shots, audit_path=audit,
                               manifest_path=LIVE_MANIFEST, cases_path=LIVE_CASES)
    assert metric["status"] == Q.NA
    assert metric["run_stale_evidence"] is True
    assert metric["fixture_items"] == 30


def test_the_shipped_movement_entries_decompose_into_tautological_and_usable():
    """入册的 70 条里，**只有 18 条有鉴别力**（2026-10-03 盘点；数字被本用例钉住）。

    为什么这条要单独钉：Q5 的分子是"计划实际产出的运镜 ∈ 条目期望"。如果条目
    自己的 `q` 里就写了同一个运镜，那么 join 一旦成功就**构造上必中**——它证明的
    是"计划把 q 里已有的运镜又写了一遍"，不是"计划采纳了这张卡的理论"。真实逐镜
    检索发生在运镜被决定**之前**，所以把运镜写进 `q` 等于"先给答案再提问"。

    三分类（口径与 `docs/knowledge/ACCEPTANCE_STATUS.md` §35.6 一字不差）：

    * `q` 带 `运镜=X` 且期望与 `X` 有交集 ⇒ **86 条**（近似恒真）；
    * `q` 带 `运镜=X` 而期望是**另一个**运镜 ⇒ **11 条**（反向样本，最有价值）；
    * `q` 不带 `运镜` ⇒ **8 条**（真正的预测）。

    **2026-10-03 16:5x 的第二轮标注**把数字从 `(52, 10, 8)` 推到 `(86, 11, 8)`：
    意图轴落地后，`INTENT_PACK`（意图×景别×运镜）第一次成为**可 join** 的一族，
    于是按协议给它补了 176 条独立标注（GLM 换族），其中 35 条拿到期望、140 条
    如实记空。**新增的 35 条里 34 条是恒真的**（`q` 里点了名的那条运镜就是期望），
    有鉴别力的只从 18 增到 19——这不是标注没做好，而是这条通道**构造上**就先给了
    答案（见 §35.6）：`q` 的 `运镜` 来自边、边的 `movement` 来自卡，于是"作者期望"
    与"查询里写的"天然同源。所以 Q5 的这条通道即便分母非零，也基本测不出
    "计划采纳了理论"——把它当绿的依据必须谨慎，这正是 `docs/knowledge/Q5_DECISION_v1.md`
    要请你裁决的那件事。

    数字变了就说明 oracle 的入口形状被改过（重标 / 换标注口径 / 扩表），那时
    §35.6 与待裁决清单必须同批更新——不能让"有鉴别力的样本还剩几条"这件事
    悄悄漂走。
    """
    rows = [json.loads(line) for line in
            (ROOT / "fixtures" / "knowledge_holdout.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()]
    entries = [row for row in rows if row.get("expect_movements")]

    tautological = discriminating = predictive = 0
    for entry in entries:
        named = {value for key, value in Q._normalise_query_pairs(entry["q"])
                 if key == "运镜"}
        expected = {str(item) for item in entry["expect_movements"]}
        if not named:
            predictive += 1
        elif named & expected:
            tautological += 1
        else:
            discriminating += 1

    assert (tautological, discriminating, predictive) == (86, 11, 8), (
        "带 expect_movements 的条目形状变了："
        f"恒真 {tautological} / 反向 {discriminating} / 预测 {predictive}。"
        "改 oracle 或改标注口径时，请同批更新 ACCEPTANCE_STATUS §35.6 与"
        "待裁决清单里的数字，别让 Q5 的鉴别力悄悄变了。")
    # 下界断言：真正能证伪"计划采纳了理论"的样本（反向 ＋ 预测）不得低于 18——
    # 它比 §4.1b 的夹具下界（≥30 条带 expect_movements）**更严**，两者不冲突：
    # 前者是"有没有标注"，这一条是"标注能不能测出东西"。
    assert discriminating + predictive >= 18
