"""`tools/kb_fetch/embedding_cloud.py` 的守门测试：**全离线**（注入 `post`，不读真密钥）。

守的是什么（不是"跑通就行"）：

* 缺密钥 ⇒ **具名**错误（不返回空串、不悄悄退回本地模型）；
* 缓存 ⇒ 同输入同输出、第二次**零**网络调用（这条臂的结果必须可复算）；
* 分批与去重 ⇒ 请求条数正确（不然成本与产物都不可预期）；
* 失败分类 ⇒ 4xx／额度码**立刻抛**、传输类**才**重试（重试把"额度没了"拖成
  "跑了两小时才发现"是本仓已经吃过一次的亏）。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from tools.kb_fetch import embedding_cloud as cloud


def _reply(vectors):
    return {"data": [{"embedding": list(vector)} for vector in vectors]}


class _FakePost:
    """记录每次请求的 `input`；按顺序返回预置回包（或按预置抛错）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append({"url": url, "input": list(payload["input"]),
                           "model": payload["model"], "auth": headers.get("Authorization")})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_missing_key_is_named():
    with pytest.raises(cloud.CloudEmbeddingError) as excinfo:
        cloud.api_key_from_env({})
    message = str(excinfo.value)
    assert "ZHIPU_API_KEY" in message and "GLM_API_KEY" in message


def test_key_prefers_zhipu_then_glm():
    assert cloud.api_key_from_env({"ZHIPU_API_KEY": "a", "GLM_API_KEY": "b"}) == "a"
    assert cloud.api_key_from_env({"GLM_API_KEY": "b"}) == "b"


def test_batches_by_size(tmp_path: pathlib.Path):
    post = _FakePost([_reply([[1.0], [2.0]]), _reply([[3.0]])])
    encode = cloud.make_cloud_encoder(api_key="k", cache_path=tmp_path / "c.jsonl",
                                      batch=2, post=post)
    vectors = encode(["a", "b", "c"])
    assert [call["input"] for call in post.calls] == [["a", "b"], ["c"]]
    assert vectors == [[1.0], [2.0], [3.0]]
    assert post.calls[0]["url"] == cloud.ZHIPU_EMBEDDINGS_URL
    assert post.calls[0]["auth"] == "Bearer k"


def test_duplicate_texts_are_sent_once(tmp_path: pathlib.Path):
    post = _FakePost([_reply([[7.0]])])
    encode = cloud.make_cloud_encoder(api_key="k", cache_path=tmp_path / "c.jsonl",
                                      post=post)
    assert encode(["same", "same", "same"]) == [[7.0], [7.0], [7.0]]
    assert [call["input"] for call in post.calls] == [["same"]]


def test_cache_makes_the_second_call_free(tmp_path: pathlib.Path):
    cache = tmp_path / "c.jsonl"
    post = _FakePost([_reply([[1.0, 2.0]])])
    first = cloud.make_cloud_encoder(api_key="k", cache_path=cache, post=post)(["x"])
    #: 第二次用**全新的** encoder（缓存来自磁盘）⇒ 不许再发请求，且输出逐字相同。
    second = cloud.make_cloud_encoder(api_key="k", cache_path=cache, post=post)(["x"])
    assert first == second == [[1.0, 2.0]]
    assert len(post.calls) == 1
    row = json.loads(cache.read_text(encoding="utf-8").splitlines()[0])
    assert row["model"] == "embedding-3" and row["vector"] == [1.0, 2.0]


def test_same_text_under_two_models_is_two_entries(tmp_path: pathlib.Path):
    """缓存键必须含模型名：换模型绝不能命中上一条模型的向量。"""
    cache = tmp_path / "c.jsonl"
    post = _FakePost([_reply([[1.0]]), _reply([[9.0]])])
    a = cloud.make_cloud_encoder(api_key="k", cache_path=cache, post=post,
                                 model="embedding-3")(["t"])
    b = cloud.make_cloud_encoder(api_key="k", cache_path=cache, post=post,
                                 model="embedding-2")(["t"])
    assert a == [[1.0]] and b == [[9.0]] and len(post.calls) == 2


def test_dimension_mismatch_is_named(tmp_path: pathlib.Path):
    post = _FakePost([_reply([[1.0, 2.0, 3.0]])])
    encode = cloud.make_cloud_encoder(api_key="k", cache_path=tmp_path / "c.jsonl",
                                      expected_dim=2048, post=post)
    with pytest.raises(cloud.CloudEmbeddingError) as excinfo:
        encode(["x"])
    assert "维度不符" in str(excinfo.value)


def test_ragged_reply_is_named(tmp_path: pathlib.Path):
    post = _FakePost([_reply([[1.0], [2.0, 3.0]])])
    encode = cloud.make_cloud_encoder(api_key="k", cache_path=tmp_path / "c.jsonl",
                                      post=post)
    with pytest.raises(cloud.CloudEmbeddingError) as excinfo:
        encode(["x", "y"])
    assert "维度不一致" in str(excinfo.value)


def test_count_mismatch_is_named(tmp_path: pathlib.Path):
    post = _FakePost([_reply([[1.0]])])
    encode = cloud.make_cloud_encoder(api_key="k", cache_path=tmp_path / "c.jsonl",
                                      post=post)
    with pytest.raises(cloud.CloudEmbeddingError) as excinfo:
        encode(["x", "y"])
    assert "条数不符" in str(excinfo.value)


def test_quota_error_is_named_and_not_retried(tmp_path: pathlib.Path):
    post = _FakePost([{"error": {"code": "1113", "message": "无可用资源包"}}])
    encode = cloud.make_cloud_encoder(api_key="k", cache_path=tmp_path / "c.jsonl",
                                      retries=3, post=post)
    with pytest.raises(cloud.CloudEmbeddingError) as excinfo:
        encode(["x"])
    assert "1113" in str(excinfo.value)
    assert len(post.calls) == 1          #: **不重试**：额度类重试没有意义


def test_client_error_is_not_retried(tmp_path: pathlib.Path):
    post = _FakePost([cloud.CloudEmbeddingError("HTTP 401: bad key")])
    encode = cloud.make_cloud_encoder(api_key="k", cache_path=tmp_path / "c.jsonl",
                                      retries=3, post=post)
    with pytest.raises(cloud.CloudEmbeddingError) as excinfo:
        encode(["x"])
    assert "401" in str(excinfo.value)
    assert len(post.calls) == 1


def test_transport_failure_is_retried_then_named(tmp_path: pathlib.Path):
    post = _FakePost([TimeoutError("read timed out")] * 3)
    encode = cloud.make_cloud_encoder(api_key="k", cache_path=tmp_path / "c.jsonl",
                                      retries=3, post=post)
    with pytest.raises(cloud.CloudEmbeddingError) as excinfo:
        encode(["x"])
    assert "传输失败" in str(excinfo.value) and len(post.calls) == 3


def test_transport_failure_recovers(tmp_path: pathlib.Path):
    post = _FakePost([TimeoutError("read timed out"), _reply([[5.0]])])
    encode = cloud.make_cloud_encoder(api_key="k", cache_path=tmp_path / "c.jsonl",
                                      retries=3, post=post)
    assert encode(["x"]) == [[5.0]] and len(post.calls) == 2
