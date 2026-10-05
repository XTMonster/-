"""P6：把影子语料按**现役管线**喂成案例层的输入（分段 → 许可门），再交给 `build_cases`。

为什么是"编排"而不是"重写"：`chunk.py`（分段/预算）与 `build_cases.py`（线索门、
体积门、按源配额）加起来一百多 KB，都是**已被门检验过**的；重写等于把那些门
再实现一遍，而且一定会漂。所以本模块只做三件事：按顺序调用、把中间产物落在
**影子目录**、把拒绝具名记下来。

一条纪律（踩过两次的同一类坑）：`validate_licenses.run()` **有副作用**——它会写
现役的 `work/licensed.jsonl`。所以这里只用它的**纯函数** `check()` 逐条判，
并由守门用例盯着"影子构建不许动现役 `work/` 下的输入文件"。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import build_cases_v4 as bv  # noqa: E402
from tools.kb_fetch import common  # noqa: E402
from tools.kb_fetch import case_search_zh as ZH  # noqa: E402


def _records():
    #: 夹具必须**过得了现役许可门**：`check()` 要「出处 ＋ 许可」＋ 正文长度下限，
    #: 所以这里带 `license` 且正文够长（否则走真默认函数时它会一条不剩地拒掉）。
    #: 正文长度必须过 `validate_licenses.MIN_DOC_CHARS = 600`。
    body = ("正反打要偏轴 30 度到 45 度，否则会越轴。"
            "连续两个中性镜头会让观众失去左右关系，所以中性镜头只能当跨轴桥梁。") * 12
    #: `check()` 还要 `retrieved_at`（出处四件套：url/title/author/license ＋ 抓取时刻）。
    ref = {"url": "https://example.org/a", "sha256": "a" * 64, "title": "t",
           "author": "a", "license": "CC-BY", "retrieved_at": "2026-10-05T00:00:00Z"}
    return [{"source_ref": dict(ref),
             "domain": "cinematography", "text": body},
            {"source_ref": {**ref, "url": "https://example.org/b"},
             "domain": "anime", "text": body}]


def test_the_stages_run_in_order_chunk_then_license(tmp_path):
    order = []

    def chunker(records):
        order.append("chunk")
        return [{"source_ref": r["source_ref"], "domain": r["domain"],
                 "text": r["text"], "chunk_index": 0} for r in records]

    def checker(record):
        order.append("check:%s" % record["domain"])
        return True, ""

    kept, rejects, stats = bv.prepare_case_inputs(
        _records(), out_dir=tmp_path / "shadow", chunk_fn=chunker, check_fn=checker)
    assert order[0] == "chunk" and order.count("chunk") == 1
    assert len(kept) == 2 and rejects == []
    assert stats["chunks"] == 2 and stats["kept"] == 2


def test_the_case_layer_input_is_the_licensed_documents_not_the_chunked_stream(tmp_path):
    """**案例层的输入是许可门后的"整篇来源"**，不是 `chunk.run` 的产物。

    实测抓到的缺陷（2026-10-05）：我最初把 `chunk.run` 接在这里，而它是 **L1/L2 那条路**
    的分段器——它**跳过全部 `layers: [L3]` 来源**（`chunk.py:181` 起：L3 只喂案例层，
    不进 chunks）。于是 v4 案例层只看到 43 个来源（810 条案例），
    而 **202 条 L3 来源**（StudioBinder／Animation Studies 那一批，正是现役 1143 条案例的
    主力）**整批没进去**。现役 `build_cases.INPUT` 指的是 `licensed.jsonl`（整篇来源），
    它自己会 `segments_of(text)` 再切——所以这里默认必须是**直通**。
    """
    kept, _rejects, stats = bv.prepare_case_inputs(_records(),
                                                   out_dir=tmp_path / "shadow")
    #: 直通 ⇒ 段数 == 输入来源数（没有经过任何按段裁剪）。
    assert stats["chunks"] == len(_records())
    assert len(kept) == len(_records())


def test_a_licence_reject_is_named_and_kept_out_of_the_output(tmp_path):
    def chunker(records):
        return [{"source_ref": r["source_ref"], "domain": r["domain"],
                 "text": r["text"]} for r in records]

    def checker(record):
        if record["domain"] == "anime":
            return False, "licence_not_allowed:X"
        return True, ""

    kept, rejects, stats = bv.prepare_case_inputs(
        _records(), out_dir=tmp_path / "shadow", chunk_fn=chunker, check_fn=checker)
    assert len(kept) == 1 and len(rejects) == 1
    assert rejects[0]["reason"] == "licence_not_allowed:X"
    assert stats["rejected"] == 1


def test_the_output_lands_in_the_shadow_dir(tmp_path):
    shadow = tmp_path / "shadow"
    bv.prepare_case_inputs(_records(), out_dir=shadow)
    assert (shadow / bv.INPUT_NAME).is_file()
    rows = [json.loads(line) for line in
            (shadow / bv.INPUT_NAME).read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 2


def test_the_shadow_build_does_not_touch_the_shipped_work_inputs(tmp_path):
    """**回归守门**：影子构建不许写现役 `work/` 下的管线输入。

    `validate_licenses.run()` 会写 `work/licensed.jsonl`——本模块只用它的纯函数
    `check()`，就是为了不碰那一份（与 `vocabulary.run()` 那次是同一类坑）。
    """
    watched = [common.WORK / "licensed.jsonl", common.WORK / "chunks.jsonl",
               common.WORK / "deduped.jsonl"]
    before = {str(path): (hashlib.sha256(path.read_bytes()).hexdigest()
                          if path.is_file() else "")
              for path in watched}
    bv.prepare_case_inputs(_records(), out_dir=tmp_path / "shadow")
    after = {str(path): (hashlib.sha256(path.read_bytes()).hexdigest()
                         if path.is_file() else "")
             for path in watched}
    assert before == after, "影子构建动了现役输入：%s" % [
        name for name in before if before[name] != after[name]]


def test_attach_clues_records_the_generation_without_touching_the_case_set(tmp_path):
    """**2026-10-05 的实缺陷**：v4 案例层只做了"生成线索"，没做"重签 ＋ 记账"。

    线索行记着生成时案例集合的 `cases_sha256`，对不上就**整份拒用**（代际纪律）；
    于是读者看到的是 `search_zh_missing`（中文面整份消失），而 manifest 里既没有
    `clue_attached` 可查、台账上也看不出任何异常——三臂 E1 就是这么从 0.20 塌到
    0.0065 的。这一步只写线索与 manifest，**案例集合一个字节都不许动**。
    """
    out = tmp_path / "shadow"
    shards = out / "cases"
    shards.mkdir(parents=True)
    case = {"case_id": "case_a", "case_type": "narrative", "title": "t",
            "excerpt": "A slow dolly in on the market stalls.",
            "beat_sequence": [], "source_ref": {}, "score": 0.0}
    (shards / "part-000.jsonl").write_text(json.dumps(case, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    (out / "cases.manifest.json").write_text(json.dumps({"cases": 1}), encoding="utf-8")
    #: 线索分片带着**另一代的摘要**签名（这正是 v4 的现场：生成时的案例集合与
    #: 最终落盘的案例集合不是同一枚摘要）⇒ 重签前它整份不可用。
    (shards / "search_zh.part-000.jsonl").write_text(json.dumps(
        {"case_id": "case_a", "zh": "镜头缓缓推近市场摊位的货物",
         "cases_sha256": "0" * 64, "prompt_sha256": ZH.prompt_sha()},
        ensure_ascii=False) + "\n", encoding="utf-8")

    from block_director.knowledge import cases as block_cases

    assert block_cases.read_search_zh(out, out)[1] == "search_zh_stale"
    before = (shards / "part-000.jsonl").read_bytes()

    stats = bv.attach_clues_to_layer(out)

    assert stats["clue_attached"]["clues"] == 1
    loaded, reason = block_cases.read_search_zh(out, out)
    assert reason == "", reason
    assert loaded == {"case_a": "镜头缓缓推近市场摊位的货物"}
    assert (shards / "part-000.jsonl").read_bytes() == before, "案例集合被改动了"
    manifest = json.loads((out / "cases.manifest.json").read_text(encoding="utf-8"))
    assert manifest["clue_attached"]["clues"] == 1
    assert manifest["size_gate"]["passed"] is True
