"""P7：真建索引——可离线测的纯函数部分（重活留给 venv 里的实跑）。

三个纯函数是这条链的"可判定面"：

1. `case_documents()`：每条案例变成一段**带 `[CASE <id>]` 前缀**的文档——
   检索回来的上下文里因此带着 id，能还原成 `case_id`；
2. `case_ids_in_context()`：从上下文里把 id 抠出来（顺序＝相关度序）；
3. `index_cells()`：四格指纹的取值从**产物**现算（不是手填）。

重活（LightRAG 建库）只在 venv 里跑：`HF_ENDPOINT` 镜像 ＋ 本地 GPU 嵌入 ＋
`EmbeddingFunc` 实例，这三条是 spike 实测的硬要求（见 `UPSTREAM_LIGHTRAG.md` §五）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.lightrag_service import build_index as bi  # noqa: E402


def _case(case_id: str, excerpt: str = "正反打要偏轴 30 度。") -> dict:
    return {"case_id": case_id, "case_type": "narrative", "title": "t",
            "excerpt": excerpt, "beat_sequence": [], "source_ref": {}, "score": 0.0}


def test_each_case_becomes_a_document_with_its_id_prefix():
    docs = bi.case_documents([_case("case_1"), _case("case_2", "越轴会让观众糊涂。")])
    assert docs[0][0] == "case_1"
    assert docs[0][1].startswith("[CASE case_1]")
    assert "正反打要偏轴 30 度。" in docs[0][1]
    assert docs[1][0] == "case_2"
    #: 前缀必须**逐条**带 id——不然上下文回来就还原不了。
    assert all(("[CASE %s]" % case_id) in text for case_id, text in docs)


def test_the_ids_come_back_out_of_the_context_in_order():
    context = ("Document Chunks ...\n"
               "[CASE case_7] 越轴的处理\n"
               "...\n[CASE case_3] 手持的价值\n")
    assert bi.case_ids_in_context(context) == ["case_7", "case_3"]
    assert bi.case_ids_in_context("") == []


def test_the_ids_are_deduplicated_but_keep_first_seen_order():
    context = "[CASE case_2] a\n[CASE case_9] b\n[CASE case_2] c\n"
    assert bi.case_ids_in_context(context) == ["case_2", "case_9"]


def test_the_index_cells_are_computed_from_the_artifacts(tmp_path):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps(_case("case_1")) + "\n", encoding="utf-8")
    cells = bi.index_cells(cases, lightrag_version="1.5.7",
                           embedding="local:bge-small-zh-v1.5:512",
                           build_args={"mode": "naive"})
    #: 第一格是**案例集合自己**的摘要（换案例集合就变；语料指纹对它不敏感）。
    assert len(cells["cases_digest"]) == 64
    assert cells["lightrag_version"] == "1.5.7"
    other = tmp_path / "cases2.jsonl"
    other.write_text(json.dumps(_case("case_1", "换了摘录")) + "\n", encoding="utf-8")
    assert bi.index_cells(other, lightrag_version="1.5.7",
                          embedding="local:bge-small-zh-v1.5:512",
                          build_args={"mode": "naive"})["cases_digest"] != cells["cases_digest"]


def test_a_case_without_an_id_is_refused_not_silently_skipped():
    try:
        bi.case_documents([{"case_id": "", "excerpt": "x"}])
    except ValueError as exc:
        assert "case_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("缺 case_id 的案例竟然被收下了")


def test_the_case_source_can_be_a_directory_of_shards(tmp_path):
    """案例层是**分片**的（`cases/part-000.jsonl`），不是单个 `cases.jsonl`。

    实测踩过：直接传 `.../cases/cases.jsonl` 会 `FileNotFoundError`。
    """
    shards = tmp_path / "cases"
    shards.mkdir()
    (shards / "part-000.jsonl").write_text(json.dumps(_case("case_1")) + "\n",
                                            encoding="utf-8")
    (shards / "part-001.jsonl").write_text(json.dumps(_case("case_2")) + "\n",
                                            encoding="utf-8")
    cases = bi.load_cases(shards)
    assert [case["case_id"] for case in cases] == ["case_1", "case_2"]
    #: 摘要必须**跨分片**算——只看一片会把"换了另一个分片"当成没变。
    assert len(bi.cases_digest(shards)) == 64


def test_the_embedding_cell_names_the_route_model_and_dimension(tmp_path):
    """指纹的第三格必须**指名道姓**：换嵌入路由／模型／维度都要换指纹。

    实测（2026-10-05）：用户购买了智谱 `embedding-3` 资源包后该模型可用
    （`dim 2048`，0.4 s；`embedding-2` 仍是 1113——资源包只覆盖 embedding-3）。
    于是"本地 bge（512 维）"与"云端 embedding-3（2048 维）"是**两代索引**，
    指纹必须把它们分开，否则换了嵌入器还能命中旧索引。
    """
    local = bi.embedding_cell("local", "bge-small-zh-v1.5", 512)
    cloud = bi.embedding_cell("cloud", "embedding-3", 2048)
    assert local == "local:bge-small-zh-v1.5:512"
    assert cloud == "cloud:embedding-3:2048"
    assert local != cloud
    sample = tmp_path / "cases.jsonl"
    sample.write_text(json.dumps(_case("case_1")) + "\n", encoding="utf-8")
    cells = bi.index_cells(sample, lightrag_version="1.5.7",
                           embedding=cloud, build_args={})
    assert cells["embedding"] == "cloud:embedding-3:2048"


def test_the_llm_func_passes_the_system_prompt_through():
    """**上游把格式规范放在 system prompt 里**，丢弃它就等于丢弃格式。

    实测（2026-10-05）：索引建完 `graphml` 里 **0 节点 0 边**、每篇文档
    `entity_names: []`。查缓存发现 DeepSeek 回的是自己编的 `A | rel | B`，
    而 LightRAG 1.5.7 要的是
    `entity<|#|><name><|#|><type><|#|><desc>`（分隔符 `DEFAULT_TUPLE_DELIMITER =
    "<|#|>"`、收尾 `<|COMPLETE|>`）。根因：`llm_model_func` 只发了 user 消息，
    **没把 `system_prompt` 带过去**——而格式规范正是写在 system 里的。
    """
    messages = bi.chat_messages("正文", system_prompt="格式规范：entity<|#|>…")
    assert messages[0]["role"] == "system"
    assert "entity" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "正文"}
    #: 没给 system 时不硬塞一个空 system。
    assert [m["role"] for m in bi.chat_messages("正文")] == ["user"]


def test_the_index_can_be_queried_in_any_upstream_mode(tmp_path):
    """检索模式必须是**可选的**：`naive` 只用向量，`hybrid`/`local`/`global` 用图谱。

    为什么（实测 2026-10-05）：第一版硬编码 `mode="naive"`，而当时图谱是空的
    （`llm_model_func` 丢 system_prompt 那个 bug），于是"LightRAG 弱"这个结论
    **只反映了 naive 模式**。修好图谱之后必须能把模式当变量比。
    """
    index = bi.LightRAGIndex(tmp_path, mode="hybrid")
    assert index.mode == "hybrid"
    assert bi.LightRAGIndex(tmp_path).mode == "naive"   # 默认不变，保持可比


def test_documents_are_inserted_in_batches_not_one_by_one():
    """批量插入：`ainsert` 收 `str | list[str]`，列表走内部并发（默认
    `max_parallel_insert=3`）。逐篇 `await` 会把它压回串行——实测 49 篇要 30 分钟。
    """
    items = list(range(7))
    assert list(bi.batches(items, 3)) == [[0, 1, 2], [3, 4, 5], [6]]
    assert list(bi.batches(items, 0)) == [items]      # 0/负数 ⇒ 不分批
    assert list(bi.batches([], 3)) == []
