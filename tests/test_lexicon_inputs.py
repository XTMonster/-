"""门读到的**数据表**必须都在缓存指纹里（`ACCEPTANCE_STATUS.md` §21 那一格的查漏补缺）。

§21 把 `CACHE_KEY_FIELDS` 的第八格补成"词表/别名表"，依据是"改一张**数据表** ⇒
索引变、指纹却一格不动"。但那次画的边界是**按模块**画的：它收了
`tools/kb_fetch/vocabulary.py` 的全大写常量与索引侧的 `hg.VALUE_ALIASES`，
漏了阶段二精确度门 `unsupported_prohibition_hosts` 的**否定词半边**——
`block_director/knowledge/grounding.py::NEGATION_CUES`（同样是数据，只是住在另一个模块）。

实测（只读探针，`--rematch` 跑两遍、只写临时目录）：

```
baseline                       edges=539  forbidden_dropped=1  指纹变化=无
+ 一个别名（反面控制）              edges=539  forbidden_dropped=1  指纹变化=['lexicon_fingerprint', ...]   ← §21 修对了
- 否定词 '避免'（待测）             edges=540  forbidden_dropped=0  指纹变化=无                                ← 同一枚指纹指向两份索引
```

两条用例各钉一边，缺一条就是空断言：

* `..._negation_cues_are_inside_the_fingerprint`：改这张数据表 ⇒ 指纹**必须**动；
* `..._the_negation_cue_really_moves_the_index`：这张表确实是索引的输入——
  用一条**合成边**（不依赖 `work/`，那些中间产物不入库）把精度门跑两遍，
  有 / 没有否定词时"拒收 vs 保留"必须不同。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import build_hypergraph as bh  # noqa: E402
from tools.kb_fetch import vocabulary as vocab  # noqa: E402
from block_director.knowledge import grounding  # noqa: E402
from block_director.knowledge import hypergraph as hg  # noqa: E402

#: 探针与两条用例共用的那个词：它是 `gen_cine_0247` 那张卡里**唯一**的否定表述，
#: 去掉它，精度门就没有依据去拒收那条"主体是编的"禁令边。
CUE = "避免"


def _gate_once(cues) -> dict:
    """把精度门跑一遍：合成一条 `gen_cine_0247` 形状的边，看它被拒还是被留。

    形状照抄 `unsupported_prohibition_hosts` 的 docstring：**禁半**（`固定`）在卡里
    落地，**主体**（`平静`／`low`）卡里一个字都没有。
    """
    edge = hg.HyperEdge(
        type="EMOTION_PACK",
        members=(hg.Member("allow", "emotion", "emotion:平静"),
                 hg.Member("qualifier", "intensity", "intensity:low"),
                 hg.Member("forbid", "movement", "movement:固定")),
        source_kind="theory", hardness="hard", sources=("card_x",),
        confidence=0.6, confidence_max=0.6,
        source_span={"chunk_id": "c", "start": 0, "end": 4},
        extractor={"prompt_version": "test"}, provenance_kind="生成卡片")
    cards = {"card_x": {"id": "card_x", "title": "运镜纪律",
                        "content": "摄影机始终处于某种运动中，%s长时间静止固定" % CUE}}
    nodes = {
        "emotion:平静": hg.Node(node_id="emotion:平静", type="emotion",
                              name="平静", value="平静"),
        "movement:固定": hg.Node(node_id="movement:固定", type="movement",
                               name="固定", value="固定"),
        "intensity:low": hg.Node(node_id="intensity:low", type="intensity",
                                 name="low", value="low"),
    }
    saved = grounding.NEGATION_CUES
    grounding.NEGATION_CUES = tuple(cues)
    try:
        kept, report = bh.unsupported_prohibition_hosts([edge], cards, nodes)
    finally:
        grounding.NEGATION_CUES = saved
    return {"kept": len(kept), "dropped": report["dropped"]}


def test_the_negation_cue_really_moves_the_index():
    """反面控制：被收进指纹的那张表，真的能让阶段二的产出变。

    少了这一条，"指纹动了"可能只是空转——一条永远不改任何东西的表进了指纹，
    看起来一样绿。这里证明**同一张表**有 / 无那个词时，精度门的判定相反。
    """
    assert CUE in grounding.NEGATION_CUES, "词表里必须真的有这个否定词"
    with_cue = _gate_once(grounding.NEGATION_CUES)
    without_cue = _gate_once(tuple(c for c in grounding.NEGATION_CUES if c != CUE))
    assert with_cue == {"kept": 0, "dropped": 1}, with_cue
    assert without_cue == {"kept": 1, "dropped": 0}, without_cue


def test_negation_cues_are_inside_the_fingerprint(monkeypatch):
    """§21 的第八格必须覆盖这张表：改了它指纹就得动，撤销就得回到原值。"""
    assert "grounding_negation_cues" in vocab.lexicon_tables(), \
        "`grounding.NEGATION_CUES` 没有被并进词表指纹（它就是一张词表，只是住在另一个模块）"

    baseline = vocab.lexicon_fingerprint()
    assert bh.fingerprint_components(
        [], _Stub())["vocabulary_fingerprint"] == baseline

    monkeypatch.setattr(grounding, "NEGATION_CUES",
                        tuple(c for c in grounding.NEGATION_CUES if c != CUE))
    assert vocab.lexicon_fingerprint() != baseline, \
        "`grounding.NEGATION_CUES` 改了，词表指纹却没动——同一枚指纹又会指向两份索引"
    monkeypatch.undo()
    assert vocab.lexicon_fingerprint() == baseline, "撤销之后必须回到原指纹"


class _Stub:
    """`fingerprint_components()` 只要这两个字段。"""

    model_id = "test-model"
    model_version = "v0"
    family = "deepseek"
