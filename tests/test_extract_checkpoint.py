"""长跑要能**增量落盘**：1.6 小时的全量抽取挂在中途，不能整批成果全丢。

实测背景（2026-10-05）：分层切片已经 2,112 次调用；全量外推约 1.6 小时／
16,900 次调用。`extract_scoped()` 原本只在**最后**返回结果——跑到一半挂掉
（网络抖动、进程被杀）就什么都没留下。所以给它一个**进度回调**，由调用方决定
多久落一次盘；核心逻辑不碰文件系统，仍可离线测。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.kb_fetch import extract_segmented as ex  # noqa: E402


def _nodes():
    return [{"node_id": "shot_size:MS", "type": "shot_size", "name": "中景",
             "value": "MS", "aliases": []}]


def _records(count: int):
    return [{"source_ref": {"url": "u%d" % index, "sha256": "%064d" % index},
             "text": "这一镜用中景。" * 20,
             "source": {"url": "u%d" % index, "sha256": "%064d" % index,
                        "span": [index * 100, index * 100 + 80]}}
            for index in range(count)]


def test_the_progress_callback_fires_with_the_running_totals():
    ticks = []

    def fake_llm(prompt: str) -> str:
        if "支持哪些边型" in prompt:
            return json.dumps({"types": []})
        return json.dumps({"members": [["allow", "shot_size", "shot_size:MS"]],
                           "confidence": 5})

    ex.extract_scoped(_records(3), llm=fake_llm, nodes=_nodes(), vocab={},
                      min_chars=0, on_progress=lambda drafts, rejects, stats: ticks.append(
                          (len(drafts), len(rejects), dict(stats))))
    assert ticks, "回调一次都没触发"
    #: 每次回调拿到的都是**当时的累计值**，最后一次等于最终值。
    assert ticks[-1][0] >= 1
    assert ticks[-1][2]["segments"] == 3


def test_the_callback_can_be_omitted():
    def fake_llm(prompt: str) -> str:
        return json.dumps({"members": []})

    drafts, rejects, stats = ex.extract_scoped(_records(1), llm=fake_llm,
                                               nodes=_nodes(), vocab={}, min_chars=0)
    assert drafts == [] and rejects == [] and stats["segments"] == 1
