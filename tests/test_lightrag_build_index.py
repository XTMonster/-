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

import asyncio
import json
import pathlib
import sys
import time

import pytest

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


def test_the_chinese_clue_rides_along_in_the_document():
    """**三条臂必须拿同一把尺子**：另两条臂的检索面是"案例文本 ＋ 中文线索"
    （`CaseIndex._text`），LightRAG 臂只要 `title+excerpt` 就少了中文面。

    实测（2026-10-05）：v4 案例层整份缺线索时，同一批中文查询上三臂 E1 从 0.20
    塌到 0.0065——**这不全是检索算法差，是文档少了中文面**。
    """
    case = _case("case_1", "A slow dolly in on the market stalls.")
    plain = bi.case_documents([case])[0][1]
    enriched = bi.case_documents([case], {"case_1": "镜头缓缓推近市场摊位的货物"})[0][1]
    assert plain in enriched and enriched != plain
    assert "镜头缓缓推近" in enriched
    #: 没有线索的案例**一个字都不多**（不许用空串拼出多余空行）。
    assert bi.case_documents([case], {})[0][1] == plain
    assert bi.case_documents([case], {"case_other": "别的"})[0][1] == plain


def test_the_embedding_cell_is_parsed_back_into_a_route_model_and_dimension():
    """消费端要按指纹第三格装嵌入器——所以它必须能被**解析回来**。"""
    assert bi.embedding_route_of("local:bge-small-zh-v1.5:512") == (
        "local", "bge-small-zh-v1.5", 512)
    assert bi.embedding_route_of("cloud:embedding-3:2048") == (
        "cloud", "embedding-3", 2048)
    for bad in ("", "local:bge", "turbo:x:8", "local::8", "cloud:embedding-3:many"):
        try:
            bi.embedding_route_of(bad)
        except ValueError:
            continue
        raise AssertionError("坏嵌入格 %r 竟然被收下了（该 fail closed，不许猜）" % bad)


def test_the_serving_side_loads_the_embedder_the_manifest_names(monkeypatch):
    """**2026-10-05 的实缺陷**：`LightRAGIndex._ensure()` 写死了本地 `_load_embedding()`。

    manifest 里第三格明明写着 `cloud:embedding-3:2048`，检索端仍装 512 维的本地模型
    ——换成云端那一代就会拿错嵌入器（维度对不上崩，或"恰好"跑起来却把查询映到
    另一个空间）。构建期的代际纪律必须**在消费期同样成立**。
    """
    called = []

    def fake_local(model):
        called.append(("local", model))
        return (lambda texts: texts), 512

    def fake_cloud(model):
        called.append(("cloud", model))
        return (lambda texts: texts), 2048

    monkeypatch.setattr(bi, "_load_embedding", fake_local)
    monkeypatch.setattr(bi, "_load_cloud_embedding", fake_cloud)

    bi.load_embedding_for("local:bge-small-zh-v1.5:512")
    bi.load_embedding_for("cloud:embedding-3:2048")
    assert called == [("local", "bge-small-zh-v1.5"), ("cloud", "embedding-3")]

    #: 格子说 2048 而嵌入器回 512 ⇒ 抛（不许静默用另一代）。
    monkeypatch.setattr(bi, "_load_embedding", lambda model: ((lambda t: t), 1024))
    try:
        bi.load_embedding_for("local:bge-small-zh-v1.5:512")
    except RuntimeError as exc:
        assert "维度" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("维度不符竟然通过了")


def test_the_index_reads_its_own_embedding_cell_from_the_manifest(tmp_path):
    """检索对象必须**自述**它是哪一代嵌入器——照着 manifest 现读，不是猜。"""
    from tools.lightrag_service import manifest as lm

    lm.write(tmp_path, {"cases_digest": "d" * 64, "lightrag_version": "1.5.7",
                        "embedding": "cloud:embedding-3:2048",
                        "build_args": {"mode": "naive"}})
    index = bi.LightRAGIndex(tmp_path)
    assert index.embedding_cell == "cloud:embedding-3:2048"
    assert bi.embedding_route_of(index.embedding_cell)[0] == "cloud"


def test_changing_a_clue_changes_the_fingerprint_even_when_the_count_is_the_same():
    """`cases_digest` 只摘**案例分片**，线索分片不在里面——而文档现在含线索。

    所以"只改一条线索的文案"（条数不变）会让第一格不动。这正是本项目反复吃过的
    "换了输入还能命中旧派生"（S0 缓存键、`53d3e3f` 手抄 trace）。线索层的内容摘要
    因此必须进 `build_args`。
    """
    one = {"case_a": "镜头缓缓推近市场摊位"}
    other = {"case_a": "手持跟拍穿过人群"}
    assert bi.clues_digest(one) != bi.clues_digest(other)
    #: 顺序不影响（字典本来就无序，摘要必须稳定）。
    assert bi.clues_digest({"a": "1", "b": "2"}) == bi.clues_digest({"b": "2", "a": "1"})
    assert bi.clues_digest({}) == bi.clues_digest(None)
    assert len(bi.clues_digest(one)) == 64


class _LoopBoundRag:
    """只有**同一条事件循环**上才能用的假 rag——复现 `bound to a different event loop`。

    它不是"mock 一个返回值"：换循环就抛，正是 LightRAG 内部 `PriorityQueue`
    在跨循环复用时的行为（`work/_sidecar4.err`）。
    """

    def __init__(self) -> None:
        self.loop = None
        self.queries = []

    async def initialize_storages(self) -> None:
        self.loop = asyncio.get_running_loop()

    async def aquery(self, query, param=None):  # noqa: ARG002
        if asyncio.get_running_loop() is not self.loop:
            raise RuntimeError("<PriorityQueue> is bound to a different event loop")
        self.queries.append(query)
        return "[CASE case_alpha]"


def test_repeated_searches_reuse_one_event_loop(tmp_path):
    """**2026-10-05 的实缺陷**：`search()` 每次调用都 `asyncio.run()`（新建一条循环），
    而 `_rag` 是跨调用复用的对象 ⇒ 第二次必然抛 `bound to a different event loop`
    （实测 `work/_sidecar4.err` 里 5773 行）。修法是常驻循环：两次检索必须在同一条
    循环上跑成功，且 rag 只建一次。这条用例**不需要装 lightrag**——判据长在假 rag 上。
    """
    built = []

    async def factory():
        rag = _LoopBoundRag()
        await rag.initialize_storages()
        built.append(rag)
        return rag

    index = bi.LightRAGIndex(tmp_path, rag_factory=factory,
                             query_param_factory=lambda **kwargs: kwargs)
    try:
        first = index.search("第一镜：固定机位 50mm", top_k=3)
        second = index.search("第二镜：推轨进入", top_k=3)
        assert first == second == [("case_alpha", 1.0)]
        assert len(built) == 1, "rag 必须复用（建两次就不是同一个循环的问题了）"
        assert index._loop is not None and index._loop.is_running()
        assert built[0].queries == ["第一镜：固定机位 50mm", "第二镜：推轨进入"]
    finally:
        index.close()


def test_a_hung_query_fails_by_name_instead_of_hanging_the_sidecar(tmp_path):
    """卡死的查询必须变成具名 `TimeoutError`（`serve.py` 翻成 500 `index_error:`），
    而不是把 sidecar 挂住、也不是伪装成"成功空列表"。"""

    class _Hang:
        async def initialize_storages(self) -> None:
            return None

        async def aquery(self, query, param=None):  # noqa: ARG002
            await asyncio.sleep(30)

    async def factory():
        return _Hang()

    index = bi.LightRAGIndex(tmp_path, rag_factory=factory,
                             query_param_factory=lambda **kwargs: kwargs,
                             query_timeout=0.2)
    try:
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            index.search("慢查询", top_k=3)
        assert time.monotonic() - started < 10
    finally:
        index.close()
