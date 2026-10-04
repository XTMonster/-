"""sidecar 的检索面（v1.4 §2.3 / §2.3b，P14-4 的 sidecar 半边）。

这些用例真的起一个 HTTP 服务（`ThreadingHTTPServer` ＋ 端口 0），断言：

1. `/health` 的能力位**两态**——索引在就宣告 `hypergraph`，不在就不宣告
   （宣告了却用不了的静默失败是 §2.3 明令禁止的）；
2. `/v1/retrieve` 一次回三条通道 `cards[] / edges[] / cases[] / trace{}`；
3. 超边**整条**搬运，`forbid` 成员一个不少（Q6b/Q7 的前置）；
4. `cases_backend` 三态：`off` 静默空、`lightrag` 依赖缺失时降级 `hybrid`
   并留痕、索引缺失时同样留痕；
5. `--temperature 0` / `--seed 0` 是默认值，且真的转发给上游。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from block_director.knowledge.hypergraph import Member, edge_id_for
from block_director.contracts.transport import SidecarTransport
from block_director.knowledge.client import KnowledgeClient

ROOT = Path(__file__).resolve().parents[1]


def _load_sidecar():
    spec = importlib.util.spec_from_file_location(
        "bd_sidecar_server_under_test", ROOT / "tools" / "sidecar_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sidecar = _load_sidecar()


class _Sidecar:
    """把真实服务跑在后台线程上（回环地址，端口 0）。"""

    def __init__(self, argv):
        self.args = sidecar.parse_args(argv)
        self.config = sidecar.SidecarConfig(self.args)
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), sidecar.make_handler(self.config))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        return False

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post(self, path, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def health(self):
        return self.get("/health")

    def retrieve(self, query, **extra):
        return self.post("/v1/retrieve", {"query": query, **extra})


QUERY = "情绪=荒诞；运镜=固定"


def _write_jsonl(path: Path, rows) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False)
                              for row in rows) + "\n", encoding="utf-8")


@pytest.fixture()
def knowledge_dir(tmp_path: Path) -> Path:
    """一个**最小但真实**的索引：节点 ＋ 一条带 forbid 的 EMOTION_PACK。"""
    nodes = [
        {"record": "node", "node_id": "emotion:荒诞", "type": "emotion",
         "name": "荒诞", "aliases": ["滑稽", "absurd"], "value": "", "unit": ""},
        {"record": "node", "node_id": "intensity:high", "type": "intensity",
         "name": "high", "aliases": [], "value": "high", "unit": ""},
        {"record": "node", "node_id": "movement:甩镜", "type": "movement",
         "name": "甩镜", "aliases": ["甩镜头", "whip_pan"], "value": "", "unit": ""},
        {"record": "node", "node_id": "movement:固定机位", "type": "movement",
         "name": "固定机位", "aliases": ["固定", "static"], "value": "", "unit": ""},
    ]
    members = [Member("allow", "emotion", "emotion:荒诞"),
               Member("qualifier", "intensity", "intensity:high"),
               Member("allow", "movement", "movement:甩镜"),
               Member("forbid", "movement", "movement:固定机位")]
    edges = [{
        "record": "edge",
        # 线协议上回的是**公式重算**的规范 id（门②要求两者自洽）。
        "edge_id": edge_id_for("EMOTION_PACK", members, "theory", "hard", "1.4"),
        "type": "EMOTION_PACK",
        "members": [member.to_dict() for member in members],
        "weight": 1.0, "confidence": 0.8, "confidence_max": 0.8,
        "occurrences": 2, "sources": ["card:1"],
        "source_span": {"chunk_id": "c1", "start": 0, "end": 10},
        "extractor": {}, "source_kind": "theory", "hardness": "hard",
        "provenance_kind": "生成卡片", "schema_version": "1.4",
    }]
    # 案例至少要 3 篇，否则 BM25Okapi 的 IDF 全为负、任何查询都拿不到分
    # （这不是实现缺陷，是 BM25 在单文档语料上的已知退化）。
    cases = [
        {"case_id": "case_1", "case_type": "sequence_pattern",
         "title": "荒诞时刻的甩镜与固定机位对照",
         "excerpt": "遇到荒诞情绪时先甩镜，再落回固定机位。",
         "beat_sequence": ["establish", "coverage", "reaction"],
         "source_ref": {"url": "https://example.org/a", "license": "OwnWork",
                        "tags": "荒诞,甩镜,固定机位"},
         "score": 0.0},
        {"case_id": "case_2", "case_type": "narrative",
         "title": "静止长镜的留白",
         "excerpt": "长镜静止时靠表演推进，不靠剪辑。",
         "beat_sequence": [],
         "source_ref": {"url": "https://example.org/b", "license": "CC-BY",
                        "tags": "长镜,表演"},
         "score": 0.0},
        {"case_id": "case_3", "case_type": "lesson",
         "title": "越轴与银幕方向",
         "excerpt": "越轴会翻转银幕方向，必须用中性镜头过渡。",
         "beat_sequence": [],
         "source_ref": {"url": "https://example.org/c", "license": "PublicDomain",
                        "tags": "轴线,越轴"},
         "score": 0.0},
    ]
    _write_jsonl(knowledge_dir_path := tmp_path / "hypergraph.nodes.jsonl", nodes)
    _write_jsonl(tmp_path / "hypergraph.edges.jsonl", edges)
    _write_jsonl(tmp_path / "cases.jsonl", cases)
    (tmp_path / "hypergraph.manifest.json").write_text(json.dumps({
        "fingerprint": "fp-abc", "schema_version": "1.4",
        "extractor": {"model_id": "deepseek-chat"}}), encoding="utf-8")
    assert knowledge_dir_path.is_file()
    return tmp_path


def test_health_advertises_hypergraph_only_when_index_is_there(knowledge_dir, tmp_path):
    with _Sidecar(["--knowledge-dir", str(knowledge_dir)]) as server:
        caps = server.health()["capabilities"]
    assert "hypergraph" in caps and "llm" in caps

    empty = tmp_path / "empty"
    empty.mkdir()
    with _Sidecar(["--knowledge-dir", str(empty)]) as server:
        caps = server.health()["capabilities"]
    assert "hypergraph" not in caps


def test_retrieve_returns_three_lanes_and_a_trace(knowledge_dir):
    with _Sidecar(["--knowledge-dir", str(knowledge_dir),
                   "--cases-backend", "hybrid"]) as server:
        body = server.retrieve(QUERY)
    assert set(body) == {"cards", "edges", "cases", "trace"}
    assert body["edges"], "带 forbid 的超边必须被召回"
    edge = body["edges"][0]
    assert edge["type"] == "EMOTION_PACK"
    assert edge["edge_id"] == edge_id_for(
        "EMOTION_PACK", [Member(*m) for m in edge["members"]], "theory", "hard", "1.4")
    assert len(edge["members"]) == 4
    # 整条搬运：forbid 成员一个不少（Q6b/Q7 的前置）。
    assert edge["forbid"] == [["forbid", "movement", "movement:固定机位"]]
    assert body["cases"] and body["cases"][0]["case_id"] == "case_1"
    trace = body["trace"]
    assert trace["backend"] == "hypergraph"
    assert trace["query"] == QUERY
    assert trace["seeds"], "trace 必须能重放：种子不能为空"
    assert trace["lanes"] == 2
    assert trace["provenance"]["corpus_fingerprint"] == "fp-abc"


def test_retrieve_without_index_degrades_to_bm25_without_pretending(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with _Sidecar(["--knowledge-dir", str(empty)]) as server:
        body = server.retrieve(QUERY)
    assert body["edges"] == []
    assert body["trace"]["backend"] == "bm25"
    assert body["trace"]["lanes"] == 1        # 案例索引也缺失 → 单通道
    assert body["trace"]["cases_degraded"] is True
    assert body["trace"]["cases_degraded_reason"] == "cases_index_missing"


def test_the_degraded_trace_has_the_same_shape_as_the_real_one(tmp_path):
    """没有索引那条路的 trace，必须与"有索引那条路"**同一个形状**。

    实测（S1a 的收尾）：sidecar 在 `hypergraph is None` 那条分支上**手写了一份**
    trace 字面量（`tools/sidecar_server.py::_retrieve_payload`），于是它当场就漂了——
    S1a 给 `RetrievalTrace` 加的 `qualifiers` 惰性键表**没有**出现在降级路上；
    更早的 `forbid_promoted` 也从来没出现过（查 `RetrievalTrace.to_dict()` 即知）。

    判据取**形状**（dataclass 的键集 ⊆ 线上 trace 的键集），不取"某两个键名"：
    这样以后任何新增字段都自动被覆盖，不用回来补字面量——本仓在"手抄第二份
    枚举/词表"上已经栽过三次（`camera.side`、`MOVEMENT_TYPES`、`QUALIFIER_KINDS`）。
    """
    from block_director.knowledge.hypergraph import RetrievalTrace
    empty = tmp_path / "empty"
    empty.mkdir()
    with _Sidecar(["--knowledge-dir", str(empty)]) as server:
        trace = server.retrieve(QUERY)["trace"]
    expected = set(RetrievalTrace(query=QUERY).to_dict()) | {
        # sidecar 在 trace 上追加的"后端 / 通道"字段
        "backend", "lanes", "cases_backend", "cases_requested_backend",
        "cases_degraded", "cases_degraded_reason", "lightrag_index_fingerprint",
        "cases_index_fingerprint", "provenance",
    }
    missing = sorted(expected - set(trace))
    assert not missing, f"降级路的 trace 少了这些键：{missing}"
    #: S1a 的谓词在这条路上也要成立（键在、值可 null）。
    assert "seq_phase" in trace["qualifiers"] and "carry_shots" in trace["qualifiers"]


def test_seed_miss_falls_back_to_the_domain_digest(knowledge_dir):
    """§2.3 第 1 步：种子全空时必须 digest 兜底并留痕，不得静默返回空。"""
    with _Sidecar(["--knowledge-dir", str(knowledge_dir),
                   "--cases-backend", "hybrid"]) as server:
        body = server.retrieve("完全没有键值对的自由文本查询")
    trace = body["trace"]
    assert trace["seed_miss"] is True
    assert trace["digest_fallback"] is True
    ids = [card["id"] for card in body["cards"]]
    assert any(card_id.startswith("digest_") for card_id in ids), ids
    # 已有的关键词命中不许被 digest 挤掉。
    assert len(ids) == len(set(ids))


def test_a_hit_does_not_trigger_the_digest_fallback(knowledge_dir):
    with _Sidecar(["--knowledge-dir", str(knowledge_dir),
                   "--cases-backend", "hybrid"]) as server:
        body = server.retrieve(QUERY)
    assert body["trace"]["seed_miss"] is False
    assert "digest_fallback" not in body["trace"]
    assert not [c for c in body["cards"] if c["id"].startswith("digest_")]


def test_cases_backend_off_is_silent_not_degraded(knowledge_dir):
    with _Sidecar(["--knowledge-dir", str(knowledge_dir),
                   "--cases-backend", "off"]) as server:
        body = server.retrieve(QUERY)
    assert body["cases"] == []
    trace = body["trace"]
    assert trace["cases_backend"] == "off"
    assert trace["cases_degraded"] is False
    assert trace["cases_degraded_reason"] == ""
    assert trace["lanes"] == 1


def test_cases_backend_lightrag_degrades_to_hybrid_with_a_reason(knowledge_dir):
    with _Sidecar(["--knowledge-dir", str(knowledge_dir),
                   "--cases-backend", "lightrag"]) as server:
        body = server.retrieve(QUERY)
    trace = body["trace"]
    assert trace["cases_requested_backend"] == "lightrag"
    assert trace["cases_backend"] == "hybrid"          # §2.3b 的降级路径
    assert trace["cases_degraded"] is True
    assert trace["cases_degraded_reason"] == "lightrag_adapter_unavailable"
    assert body["cases"], "降级后仍要给出参考案例，不是空转"
    assert trace["lanes"] == 2


def test_retrieve_request_rejects_are_not_swallowed(knowledge_dir):
    """案例索引坏掉时必须留痕，而不是把整条检索打崩或静默返回空。"""
    (knowledge_dir / "cases.jsonl").write_text("{not json}\n", encoding="utf-8")
    with _Sidecar(["--knowledge-dir", str(knowledge_dir),
                   "--cases-backend", "hybrid"]) as server:
        body = server.retrieve(QUERY)
    assert body["cases"] == []
    assert body["trace"]["cases_degraded"] is True
    assert body["trace"]["cases_degraded_reason"].startswith("cases_index_unreadable")
    assert body["edges"], "案例通道坏掉不该影响超图通道"


def test_cli_defaults_are_deterministic():
    args = sidecar.parse_args([])
    assert args.temperature == 0.0
    assert args.seed == 0
    assert args.cases_backend == "lightrag"
    assert args.knowledge_dir == str(sidecar.DEFAULT_KNOWLEDGE_DIR)


def test_seed_and_temperature_reach_the_upstream_body():
    config = sidecar.SidecarConfig(sidecar.parse_args([]))
    ollama = sidecar._ollama_body(config, {"messages": []})
    assert ollama["options"]["seed"] == 0
    assert ollama["options"]["temperature"] == 0.0
    openai = sidecar._openai_body(config, {"messages": []})
    assert openai["seed"] == 0 and openai["temperature"] == 0.0
    # 请求级覆盖优先于启动默认值。
    assert sidecar._openai_body(config, {"messages": [], "seed": 7})["seed"] == 7


def test_a_cloud_upstream_gets_the_authorization_header_from_an_env_var(monkeypatch):
    """云端 OpenAI 兼容上游（智谱 GLM 等）必须带 `Authorization`。

    §4.4 步骤 2 的 sidecar 命令原先指向本机 Ollama（不需要鉴权）；用户裁决
    "别用本地模型了" 之后上游换成 GLM，缺这个头就 401、真实模型通路跑不起来，
    Q5/E2 只能一直记 `not_measured`。密钥**只从环境变量读**，不进仓库、不进日志。
    """
    monkeypatch.setenv("BD_TEST_UPSTREAM_KEY", "sk-test-123")
    args = sidecar.parse_args(["--upstream", "https://open.bigmodel.cn/api/paas/v4",
                               "--upstream-api-key-env", "BD_TEST_UPSTREAM_KEY"])
    config = sidecar.SidecarConfig(args)
    assert sidecar._upstream_headers(config) == {"Authorization": "Bearer sk-test-123"}

    # 正对照 1：本地 Ollama 不给这个开关 → 不带鉴权头（别给本地端点乱发密钥）。
    plain = sidecar.SidecarConfig(sidecar.parse_args([]))
    assert sidecar._upstream_headers(plain) == {}
    # 正对照 2：环境变量名给了但为空 → **当场失败**，不许静默跑一个必 401 的上游。
    monkeypatch.delenv("BD_TEST_UPSTREAM_KEY", raising=False)
    with pytest.raises(SystemExit):
        sidecar.SidecarConfig(sidecar.parse_args(
            ["--upstream-api-key-env", "BD_TEST_UPSTREAM_KEY"]))


def test_repo_index_is_loadable_by_the_sidecar():
    """仓库自带的索引必须真能被 sidecar 装配（否则 P14-2 的产物是死数据）。"""
    graph = sidecar.load_hypergraph_index(ROOT / "knowledge")
    assert graph is not None
    assert graph.nodes and graph.edges
    provenance = sidecar.load_provenance(ROOT / "knowledge")
    assert provenance["corpus_fingerprint"]
    assert provenance["extractor_model_id"]


def test_client_and_transport_drive_the_real_sidecar(knowledge_dir):
    """整条链路：`KnowledgeClient` → `SidecarTransport` → 真 HTTP → 三条通道。"""
    events = []
    with _Sidecar(["--knowledge-dir", str(knowledge_dir),
                   "--cases-backend", "hybrid"]) as server:
        transport = SidecarTransport(base_url=server.base, timeout=10.0)
        client = KnowledgeClient(transport, audit=events.append)
        response = client.retrieve(QUERY, top_k=3)
        trace = client.trace_payload()
    assert client.retrieval_calls == 1
    assert response.edges and response.edges[0].type == "EMOTION_PACK"
    assert response.edges[0].forbid == [["forbid", "movement", "movement:固定机位"]]
    assert response.cases and response.trace["backend"] == "hypergraph"
    assert events[0]["forbid_members"] == 1
    assert trace["lanes"] == 2 and trace["retrieval_calls"] == 1
