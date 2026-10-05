"""P7：LightRAG 索引的**失效钥匙**（计划 §2.3 / §5 的"六格/四元组指纹"）。

为什么必须有它：索引是**派生物**，而派生物的头号病是"语料换了、索引还是旧的，
账面全绿"——本项目在 S0 与 `53d3e3f` 上各踩过一次同形的坑。所以每次建索引都算一枚
指纹，查询端**先比对再服务**，不匹配就 fail closed（拒绝用脏索引出数）。

指纹的四格（写死口径）：

1. `cases_digest` —— 案例集合自己的摘要（不是语料指纹；只换案例集合也能变）；
2. `lightrag_version` —— 上游版本（pip 装到哪版就记哪版）；
3. `embedding` —— 嵌入路由 ＋ 模型标识（换嵌入器必须整体重建）；
4. `build_args` —— 建索引时真正用到的参数（模式／分片等）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.lightrag_service import manifest as lm  # noqa: E402


def test_the_fingerprint_covers_all_four_cells():
    parts = {"cases_digest": "a" * 64, "lightrag_version": "1.5.7",
             "embedding": "local:bge-small-zh-v1.5:512",
             "build_args": {"mode": "naive"}}
    report = lm.fingerprint(parts)
    assert len(report["fingerprint"]) == 64
    assert report["cells"]["lightrag_version"] == "1.5.7"
    #: 四格任一变化都必须换指纹——逐格反面控制。
    for cell in ("cases_digest", "lightrag_version", "embedding"):
        changed = dict(parts)
        changed[cell] = str(parts[cell]) + "X"
        assert lm.fingerprint(changed)["fingerprint"] != report["fingerprint"], cell
    changed = dict(parts)
    changed["build_args"] = {"mode": "hybrid"}
    assert lm.fingerprint(changed)["fingerprint"] != report["fingerprint"], "build_args"


def test_the_fingerprint_is_order_insensitive_for_build_args():
    first = lm.fingerprint({"cases_digest": "a", "lightrag_version": "v",
                            "embedding": "e", "build_args": {"a": 1, "b": 2}})
    second = lm.fingerprint({"cases_digest": "a", "lightrag_version": "v",
                             "embedding": "e", "build_args": {"b": 2, "a": 1}})
    assert first["fingerprint"] == second["fingerprint"], "同输入必须同指纹"


def test_a_missing_cell_is_refused_not_treated_as_empty(tmp_path):
    """缺格 ⇒ 拒收。**不许**把缺格当成空串算出一枚"看起来正常"的指纹。"""
    for missing in ("cases_digest", "lightrag_version", "embedding", "build_args"):
        parts = {"cases_digest": "a", "lightrag_version": "v", "embedding": "e",
                 "build_args": {"m": 1}}
        parts.pop(missing)
        try:
            lm.fingerprint(parts)
        except ValueError as exc:
            assert missing in str(exc), (missing, str(exc))
        else:  # pragma: no cover
            raise AssertionError("缺 %s 竟然算出了指纹" % missing)


def test_verify_refuses_a_mismatch(tmp_path):
    """查询端比对：不匹配就 fail closed，返回具名原因。"""
    index = tmp_path / "lightrag"
    index.mkdir(parents=True, exist_ok=True)
    parts = {"cases_digest": "a", "lightrag_version": "v", "embedding": "e",
             "build_args": {"m": 1}}
    report = lm.fingerprint(parts)
    (index / lm.MANIFEST_NAME).write_text(
        json.dumps({"cells": report["cells"], "fingerprint": report["fingerprint"]},
                   ensure_ascii=False), encoding="utf-8")
    ok, why = lm.verify(index, report["cells"])
    assert (ok, why) == (True, "")
    tampered = dict(report["cells"])
    tampered["embedding"] = "别的嵌入器"
    ok, why = lm.verify(index, tampered)
    assert ok is False and why.startswith("index_fingerprint_mismatch")


def test_verify_reports_a_missing_manifest_by_name(tmp_path):
    ok, why = lm.verify(tmp_path, {"cases_digest": "a", "lightrag_version": "v",
                                   "embedding": "e", "build_args": {}})
    assert ok is False and why == "index_manifest_missing"
