"""超图 RAG 的 schema、校验门与检索（执行文档 v1.4 §2.3）。

纯 stdlib、无 bpy：本模块既能被 sidecar 直接跑，也能被插件侧的测试导入。
索引本身（LLM 抽取）在 `tools/kb_fetch/` 与 sidecar 侧构建；这里只放
**可判定的规则**：

* 节点 16 类 / qualifier 10 类 / 超边 6 类的闭集；
* `edge_id = "hg:" + sha1(type + sorted(members) + source_kind + hardness + schema_version)[:12]`；
* 9 条校验门（§2.3 第 3 步）与 `raw = valid_unique + duplicates + rejects`；
* 去重键 `(type, frozenset(members), source_kind, hardness)`，合并时保留
  `occurrences / sources / confidence_max`；
* 四步检索（种子 -> 扩展 -> 打分 -> 闭合输出）与原子注入渲染。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..cinema.composition import WEIGHTS as COMPOSITION_WEIGHTS
from ..cinema.framing import SHOT_FRAME
from .bm25 import tokenize as _bm25_tokenize

SCHEMA_VERSION = "hg/v2"

#: 构建期留痕的产物名（与 ``knowledge/cases.manifest.json`` 同一约定）。
MANIFEST_FILE = "hypergraph.manifest.json"


def manifest_fingerprint(index_dir: Any) -> str:
    """读 ``hypergraph.manifest.json`` 的六元指纹（构建期留痕，供 trace 引用）。

    为什么索引也要报指纹（2026-10-03 实测）：Q5 的运行侧判据要拿一份**真实模型
    运行的 `shots.json`** 与 held-out 的 `q` join，而这份证据可能属于**上一代
    索引**——`docs/evidence/20261002_real/` 那份就是这样（它的案例指纹已经对不上
    `knowledge/cases.manifest.json`）。E1 已经因为同一形状吃过一次亏（
    `quality.e1_evidence_is_stale`），所以运行侧证据必须能自证"我是哪一代"。
    指纹读不出来时返回空串——**空串不算证据**，调用方据此记 `stale_evidence`。
    """
    path = Path(index_dir) / MANIFEST_FILE
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("fingerprint") or "") if isinstance(payload, dict) else ""

#: 节点类型闭集（17 类，§2.3 是单一真源）。v1.5 起新增 `intent`（意图）：它是
#: "角色/导演想干什么"这一层，和 `emotion`（感受）一样是**强耦合的源头**——
#: 意图决定镜头语言，所以 `INTENT_PACK` 必须能把它写进边里。
NODE_TYPES: Tuple[str, ...] = (
    "emotion", "movement", "shot_size", "lens", "pacing", "vfx", "sfx",
    "composition_rule", "axis_topic", "action", "genre",
    "beat_type", "camera_angle", "lighting", "intent",
    #: v1.6：用户裁决"尽可能囊括除灯光以外影响电影制作的其他元素"里，还缺三块——
    #: 台词**怎么念**、**配乐/环境声**、**道具/环境元素**。三者都是零依赖的按需加载项。
    "delivery", "music", "prop",
    #: 同批删掉两个**声明了却没有任何边类型使用**的 kind：`character` 与 `object`。
    #: 实测（审查第 18 条）它们 0 个节点、0 次使用，留在闭集里只会让"闭集"看起来比实际宽；
    #: 而 `object` 的角色已经被 v1.6 的 `prop`（道具/环境元素 × 景别 × 机位）取代。
    #: 要重新引入 `character`，正确做法是**先有边类型用它、再有语料填它**，而不是先占位。
)

#: qualifier 类型闭集（10 类）。`axis_side` 必须在表里——否则最高优先级的
#: `AXIS_RULE` 会被自己的校验门 ③ 全部拒收。
QUALIFIER_KINDS: Tuple[str, ...] = (
    "pair", "axis_side", "intensity", "applies_to_genre", "applies_to_shot_size",
    "headroom_policy", "avg_shot_len", "transition", "scene_type", "example_shot",
)

ALLOWED_KINDS = frozenset(NODE_TYPES) | frozenset(QUALIFIER_KINDS)
ROLES = frozenset({"allow", "forbid", "qualifier"})

EMOTION_PACK = "EMOTION_PACK"
SHOT_PATTERN = "SHOT_PATTERN"
AXIS_RULE = "AXIS_RULE"
TROPE = "TROPE"
EDIT_RHYTHM = "EDIT_RHYTHM"
LIGHT_PACK = "LIGHT_PACK"
#: v1.5 新增：用户裁决"边要更细、把电影制作里除灯光以外的强耦合元素都囊括进来"。
#: 这七类都是**跨域强耦合**，不是"再拆一个原子字段"（单独一个字段不需要超边）。
ACTION_BEAT = "ACTION_BEAT"            # 动作×叙事节拍×强度
PERFORMANCE_PACK = "PERFORMANCE_PACK"  # 角色行为：情绪×动作×机位
INTENT_PACK = "INTENT_PACK"            # 意图×镜头语言（景别＋运镜）
IMPACT_PACK = "IMPACT_PACK"            # 震动与打击感：特效×音效×运镜
STAGING_PACK = "STAGING_PACK"          # 构图×调度：构图规则×景别×机位
SOUND_PACK = "SOUND_PACK"              # 声画关系：音效×节奏×强度
TRANSITION_PACK = "TRANSITION_PACK"    # 转场×节奏×场景类型
#: v1.6：三块"缺失的边"（实测语料支撑：dialogue 38 张卡 / music 26 / prop 160，
#: 小规模试点抽取分别产出 9 / 4 / 2 条边，都是真耦合而不是硬塞）。
DIALOGUE_PACK = "DIALOGUE_PACK"        # 台词交付：语气/发声 × 语速 × 强度
MUSIC_PACK = "MUSIC_PACK"              # 配乐与环境声：策略 × 节奏 × 强度
PROP_PACK = "PROP_PACK"                # 道具与环境元素 × 呈现景别 × 机位

EDGE_TYPES: Tuple[str, ...] = (
    EMOTION_PACK, SHOT_PATTERN, AXIS_RULE, TROPE, EDIT_RHYTHM, LIGHT_PACK,
    ACTION_BEAT, PERFORMANCE_PACK, INTENT_PACK, IMPACT_PACK, STAGING_PACK,
    SOUND_PACK, TRANSITION_PACK,
    DIALOGUE_PACK, MUSIC_PACK, PROP_PACK,
)

#: 类型优先级（§2.3 的排序表）。
TYPE_PRIORITY: Dict[str, float] = {
    AXIS_RULE: 1.0, EMOTION_PACK: 1.0, LIGHT_PACK: 0.8,
    SHOT_PATTERN: 0.9, EDIT_RHYTHM: 0.7, TROPE: 0.6,
    #: v1.5 新增类型沿用"越靠近硬约束越高"的口径：
    #: 意图/表演/调度直接影响演员与机位，打击感/声画是呈现层，转场最弱。
    INTENT_PACK: 0.95, PERFORMANCE_PACK: 0.9, STAGING_PACK: 0.85,
    ACTION_BEAT: 0.8, IMPACT_PACK: 0.75, SOUND_PACK: 0.7, TRANSITION_PACK: 0.65,
    #: v1.6 沿用同一口径：对白交付/配乐直接影响观众听到什么（高于转场），
    #: 道具调度偏呈现层（与 IMPACT_PACK 同档）。
    DIALOGUE_PACK: 0.85, MUSIC_PACK: 0.8, PROP_PACK: 0.75,
}

#: 必填成员（role, kind）。
REQUIRED_MEMBERS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    EMOTION_PACK: (("allow", "emotion"), ("qualifier", "intensity")),
    SHOT_PATTERN: (("allow", "shot_size"), ("allow", "lens"), ("qualifier", "headroom_policy")),
    AXIS_RULE: (("qualifier", "pair"), ("qualifier", "axis_side")),
    TROPE: (("allow", "genre"), ("allow", "emotion")),
    EDIT_RHYTHM: (("allow", "pacing"), ("qualifier", "avg_shot_len")),
    LIGHT_PACK: (("allow", "lighting"), ("qualifier", "intensity")),
    ACTION_BEAT: (("allow", "action"), ("qualifier", "beat_type"), ("qualifier", "intensity")),
    PERFORMANCE_PACK: (("allow", "emotion"), ("allow", "action"), ("qualifier", "camera_angle")),
    INTENT_PACK: (("allow", "intent"), ("allow", "shot_size"), ("qualifier", "movement")),
    IMPACT_PACK: (("allow", "vfx"), ("allow", "sfx"), ("qualifier", "movement")),
    STAGING_PACK: (("qualifier", "composition_rule"), ("allow", "shot_size"),
                   ("qualifier", "camera_angle")),
    SOUND_PACK: (("allow", "sfx"), ("allow", "pacing"), ("qualifier", "intensity")),
    TRANSITION_PACK: (("qualifier", "transition"), ("allow", "pacing"),
                      ("qualifier", "scene_type")),
    DIALOGUE_PACK: (("allow", "delivery"), ("qualifier", "pacing"),
                    ("qualifier", "intensity")),
    MUSIC_PACK: (("allow", "music"), ("qualifier", "pacing"),
                 ("qualifier", "intensity")),
    PROP_PACK: (("allow", "prop"), ("allow", "shot_size"),
                ("qualifier", "camera_angle")),
}

#: 选填成员：表里没有的 (role, kind) 组合即非法（防止抽取器往边里塞任意东西）。
OPTIONAL_MEMBERS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    EMOTION_PACK: (("allow", "movement"), ("allow", "shot_size"), ("allow", "lens"),
                   ("allow", "pacing"), ("allow", "vfx"), ("allow", "sfx"),
                   ("forbid", "movement"), ("forbid", "shot_size"), ("forbid", "vfx"),
                   ("qualifier", "applies_to_genre"), ("qualifier", "applies_to_shot_size")),
    SHOT_PATTERN: (("allow", "movement"), ("qualifier", "composition_rule")),
    #: v1.5：`AXIS_RULE` 的必填成员只有 `pair`/`axis_side` 两个 **schema 常量**，
    #: 它们在查询空间里没有对应取值（`轴线=` 映射到的是 `axis_topic`）——于是这类边
    #: 在检索里**一个种子都挂不上**，Q1/Q2 结构性为 0（实测 held-out 里 23/125 的
    #: 未命中就是这种）。允许把 `axis_topic` 挂在 AXIS_RULE 上，让边能锚到查询。
    AXIS_RULE: (("allow", "shot_size"), ("allow", "movement"),
                ("qualifier", "axis_topic")),
    TROPE: (("allow", "vfx"), ("allow", "movement"), ("qualifier", "example_shot")),
    EDIT_RHYTHM: (("qualifier", "transition"), ("qualifier", "scene_type")),
    LIGHT_PACK: (("allow", "emotion"), ("allow", "camera_angle")),
    ACTION_BEAT: (("allow", "movement"), ("allow", "emotion"),
                  ("qualifier", "applies_to_genre"), ("qualifier", "scene_type")),
    PERFORMANCE_PACK: (("allow", "shot_size"), ("qualifier", "intensity"),
                       ("qualifier", "beat_type")),
    INTENT_PACK: (("allow", "lens"), ("qualifier", "camera_angle"),
                  ("qualifier", "composition_rule"), ("qualifier", "intensity")),
    IMPACT_PACK: (("allow", "movement"), ("qualifier", "intensity"),
                  ("qualifier", "transition"), ("qualifier", "scene_type")),
    STAGING_PACK: (("allow", "lens"), ("allow", "movement"),
                   ("qualifier", "applies_to_shot_size")),
    SOUND_PACK: (("allow", "vfx"), ("qualifier", "transition"),
                 ("qualifier", "scene_type"), ("qualifier", "beat_type")),
    TRANSITION_PACK: (("allow", "shot_size"), ("qualifier", "avg_shot_len"),
                      ("allow", "movement"), ("qualifier", "example_shot")),
    DIALOGUE_PACK: (("allow", "emotion"), ("allow", "sfx"),
                    ("qualifier", "scene_type")),
    MUSIC_PACK: (("allow", "emotion"), ("allow", "movement"),
                 ("qualifier", "scene_type")),
    PROP_PACK: (("allow", "movement"), ("qualifier", "composition_rule"),
                ("qualifier", "scene_type")),
}


def _forbid_hosts(edge_type: str) -> Tuple[Tuple[str, str], ...]:
    """该类型**已经出现过**的内容型 kind，自动获得一个 `forbid` 宿主。

    用户裁决（2026-10-01，审查第 17 条）："边里本来就有这个槽位，就允许禁止它"。
    审查那一条的实测是：915 条边里带 `forbid` 的 **81 条全部是 `EMOTION_PACK`**，
    其余 12 类为 0 —— 于是"这个动作不该配这个运镜"这类**跨类负向知识结构上表达不了**。

    这条规则是**机械的**（不是手抄 16 张表）：本类型里凡是以 `allow`／`qualifier`
    出现过的内容型 kind（`NODE_TYPES` 里的），都自动补一个 `forbid` 宿主。
    schema 常量（`pair`／`axis_side`／`headroom_policy`／`avg_shot_len`／
    `applies_to_*`）不在此列——禁止一个常量没有意义，只会把规格空间灌水。
    `tests/test_knowledge_holdout_vocab.py` 与 `tests/test_hypergraph_schema.py`
    会复核这条不变量，防止哪天手改表把规则改破。
    """
    present = {kind for _role, kind in
               tuple(REQUIRED_MEMBERS[edge_type]) + tuple(OPTIONAL_MEMBERS[edge_type])
               if kind in NODE_TYPES}
    already = {kind for role, kind in OPTIONAL_MEMBERS[edge_type] if role == "forbid"}
    return tuple(("forbid", kind) for kind in sorted(present - already))


for _edge_type in EDGE_TYPES:  # noqa: B020 - 就地补全，见 `_forbid_hosts` 的说明
    OPTIONAL_MEMBERS[_edge_type] = (tuple(OPTIONAL_MEMBERS[_edge_type])
                                    + _forbid_hosts(_edge_type))

#: §2.3d T3：qualifier 的取值域。`None` = 显式"不设枚举"。
VALUE_DOMAINS: Dict[str, Optional[Tuple[str, ...]]] = {
    "pacing": ("short", "medium", "long"),
    "transition": ("cut", "dissolve", "fade", "whip"),
    "axis_side": ("left", "right", "neutral"),
    "avg_shot_len": ("<1s", "1-3s", "3-8s", ">8s"),
    "scene_type": ("establish", "dialogue", "action", "reaction", "transition", "insert"),
    "genre": ("film", "anime", "documentary"),
    "beat_type": ("establish", "coverage", "reaction", "insert", "transition"),
    "intensity": ("low", "mid", "high"),
    "headroom_policy": ("board", "cinematic"),
    "pair": ("any_two",),
    "applies_to_genre": ("film", "anime", "documentary"),
    "applies_to_shot_size": tuple(SHOT_FRAME.keys()),
    "composition_rule": tuple(sorted(COMPOSITION_WEIGHTS.keys())),
    "example_shot": None,  # 自由文本：参考资料引用，不参与判定
    #: v1.5：意图的闭集——"角色想要什么/导演在铺什么"。闭集才能被机器判对错；
    #: 中文取值，避免与 `must` 里的写法不一致（这正是本地模型最常翻车的地方）。
    "intent": ("铺垫", "推进", "揭示", "转折", "停顿", "压迫", "释放", "回望",
               "收束", "煽动", "留白", "对抗"),
}

#: `source_kind`（来源性质）与 `hardness`（软硬）是边级属性，
#: 与 `provenance_kind`（来源介质）不是一个东西（§2.3）。
SOURCE_KINDS = frozenset({"theory", "experience", "lesson"})
HARDNESS = frozenset({"hard", "soft"})

#: `provenance_kind` -> 来源权威度（§2.3 第 3 步）。
AUTHORITY: Dict[str, float] = {
    "拉片笔记": 1.0, "权威文档": 0.9, "生成卡片": 0.7, "网络语料": 0.5,
}
DEFAULT_AUTHORITY = 0.7

#: §2.3 的检索上限（写死，防止 hub 节点把整图炸开）。
SEED_TOP_K = 20
MAX_HOPS = 2

#: **覆盖率的分母口径**：`0.0` = 只按"种子集"算（历史口径），
#: `1.0` = 只按"查询里的取值"算。
#:
#: 为什么要这个旋钮：`seeds_for` 是**词面匹配**，一个查询取值常常命中一二十个节点
#: （`运镜=上下场` 拉进 8 个种子），于是 `_edge_coverage` 的分母 `len(seed_set)` 被
#: 稀释——实测 4928 条 `must` 里 **3544 条（71.9%）**的"本边"只覆盖到 3/8，
#: 被判成部分匹配，与竞争边只差 0.002–0.01 分。这正是 Q4/Q6b 那条硬尾巴的机制。
#:
#: 两个极端都试过、都有代价（`seeds_for` 的 docstring 记着）：只留精确命中会掉召回；
#: 纯按查询取值算会让**独立标定工具**（`tools/knowledge/ranking_quality.py`）的 Q1
#: 从 0.70 掉到 0.66。所以取**混合**，系数由一次多目标扫参定：
#: `Q1/Q2/Q4/Q6b` ＋ 标定工具四项同时不降。
#: 实测（2026-10-02，2840 条 oracle ＋ 738 条边）：0.1–0.3 是一个**平台**，
#: 取中值 0.2。同一次多目标扫参里四项同时变好（见 `seeds_for` 的 docstring）。
COVERAGE_VALUE_BLEND = 0.2
MAX_EDGES_PER_NODE = 8
MAX_EDGES_TOTAL = 40
MAX_NODES = 120

#: 枢纽节点的**单节点保底配额**：一个节点的邻边数超过 `len(edges)/20` 时会被当成
#: 枢纽并截断，但截断必须保证"查询里点名了它某个成员的边"不会被整批丢掉。
#: 旧值写死成 4（且排序键只有 coverage → occurrences → edge_id），实测把它踩穿：
#: `movement:固定` 有 66 条邻边，而
#: `EMOTION_PACK(emotion=平静, intensity=low, forbid movement=固定)` 的 occurrences=1，
#: 于是它在"coverage 全是 1.0"的并列里排最后、被切掉 —— 那条边的**三个成员全在
#: 查询里**，却连候选都不是，`tests/test_hypergraph_index_content.py` 因此红。
#: 现在按 `(coverage, precision, occurrences, edge_id)` 排序（precision 优先保住
#: "整条边都被查询解释"的那些），并把配额提到 12。
HUB_EDGES_PER_NODE = 12
MAX_RENDER_TOKENS = 400

SCORE_WEIGHTS = {
    #: 实测标定（`work` 里的调参脚本，400 条抽样）：
    #: `coverage .70 / occurrences .15` 这一档把 Q1 0.327→0.449、Q2 0.622→0.663，
    #: 是四组里最好的一组；纯覆盖率（C 组）反而更差（0.296/0.561），说明
    #: `occurrences` 提供的"这条耦合在语料里反复出现"的排序信号不能丢。
    #: 权重是"默认值 + 写进 trace"，改它不动任何验收线。
    #:
    #: v1.5 加 `precision`（查询里的成员**占这条边多大比例**）：只有 coverage 时，
    #: 一条"把种子成员全带上、另外还多带几个成员"的**超集边**能拿到同样的 1.0，
    #: 再靠 occurrences/confidence 把**精确匹配的那条边**挤到后面。
    #: 实测口径：`tools/knowledge/ranking_quality.py` **全量 683 条**索引派生查询
    #: （确定性，不抽样）——原权重（coverage .70、无 precision、forbid .03）
    #: Q1 0.5564 / Q2 0.8097；改用本行 **Q1 0.6164 / Q2 0.8653**。
    #:
    #: `forbid_hit` 从 .03 提到 .16 不是随手加的：第一版只把 coverage 让给 precision
    #: （.35/.40/.10，forbid 仍 .03）虽然 Q1 到 0.6325，却把**冲突查询数从 487 压到 52**
    #: ——Q7（禁忌拦截）的分母跌破 ≥60 下界。多目标扫参（`work/_diag_weight_sweep.py`）
    #: 后取这一档：三个指标**同时**优于原权重（Q1/Q2 见上，冲突查询 601 > 487）。
    #:
    #: **2026-10-01 二次扫参（池通道 oracle × 847 条边索引，12 点网格 + 独立复算）**：
    #: `occurrences` .14 → .02、`authority` .05 → 0，腾出的权重给 `coverage`/`precision`。
    #: 为什么要再扫一次：`Q4`（合同线 1.0）卡在 0.9513，量出来的机制是"部分匹配但
    #: 更常见"的边以 0.002–0.01 的分差把"逐字全中"的边挤出 top-3 —— `occurrences`
    #: 正是那个翻盘项。四项**同时**变好，Q7 保持 1.0：
    #:
    #:   | 权重 | Q1 | Q2 | Q4 | Q6b |
    #:   |---|---|---|---|---|
    #:   | 旧（occ .14 / auth .05）| 0.9341 | 0.9967 | 0.9513 | 0.9692 |
    #:   | 新（occ .02 / auth .00）| **0.9428** | **0.9971** | **0.9702** | **0.9811** |
    #:
    #: `authority` 留在公式里但权重为 0：实测只要给它 0.03（coverage 从 .38 让到 .35），
    #: Q1 就掉回 0.9228 —— "理论优先于经验"在这份 oracle 上是**负信号**。这不是删
    #: 功能：改回一个数就能复现旧行为，而 `hard/soft` 的语义分栏在注入侧仍由
    #: `hardness` 决定，不靠这个排序项。
    "coverage": 0.3689, "precision": 0.3883, "type_priority": 0.0485, "occurrences": 0.0194,
    "confidence": 0.0194, "authority": 0.0, "forbid_hit": 0.1553,
}

#: 查询键（中文）-> kind。布尔项（如"对白=有"）映射到 `pacing`/`scene_type`，不新造节点类型。
QUERY_KEYS: Dict[str, str] = {
    "情绪": "emotion", "动作": "action", "运镜": "movement", "景别": "shot_size",
    "镜头": "lens", "节奏": "pacing", "特效": "vfx", "音效": "sfx",
    "机位": "camera_angle", "光线": "lighting", "构图": "composition_rule",
    "轴线": "axis_topic", "题材": "genre", "桥段": "beat_type",
    #: v1.5：意图是"角色/导演想干什么"，`INTENT_PACK` 的必填成员就是它。
    "意图": "intent",
    "对白": "scene_type",
    #: v1.6：三块新内容各自的查询键（没有键的 kind 挂不上种子，AXIS_RULE 踩过这个坑）。
    "语气": "delivery",
    "配乐": "music",
    "道具": "prop",
    #: v1.5 解冻：`TRANSITION_PACK` 的必填成员是 `transition`，而冻结查询键里
    #: 没有对应项——那一类边**一个种子都挂不上**（实测：这类边在检索里恒为
    #: 0 命中，与 AXIS_RULE 早先的毛病同源）。补上键，让"转场=黑场"这类
    #: 查询能锚到边上。
    "转场": "transition",
    #: **待量证的候选**：`intensity`／`headroom_policy`／`avg_shot_len` 同样是
    #: 必填槽位却没有查询键（成因同上一条）。它们与 `transition` 的区别是：
    #: **那几类边还有别的可锚槽位**，加键是"多一个锚"而不是"从 0 到 1"。
    #: 实测（2026-10-01，`tools/knowledge/ranking_quality.py` 全量 683 条索引派生
    #: 查询）**推翻了我先前只按"可达性"下的结论**：可达性确实是 0 收益，但
    #: **区分度**不是——同一类型里大量近邻边只差一个 `intensity`，查询说不出
    #: "强度"时它们无法区分，排序只能交给 occurrences/confidence，于是目标边
    #: 常常屈居第二。加 `强度`：Q1 0.6164 → **0.7189**、Q2 0.8653 → **0.9165**
    #: （双双越过 0.70/0.90 线）；再加 `头留白`/`平均镜长` 反而回落到 0.6574/0.8668
    #: （键多了会挤掉更有区分度的成员），所以**只加 `强度`**。
    "强度": "intensity",
    #: v1.6：`avg_shot_len` 也是"必填槽位却没有查询键"。实测的后果比"少一个锚"严重得多：
    #: `EDIT_RHYTHM` 的 13 条边里 **12 条**挤在 3 个 `(类型, 查询)` 组里，组内成员
    #: **只差 `avg_shot_len`** —— 查询说不出"镜长"时它们在同一查询下完全不可区分。
    #: 于是：① oracle 通道整组跳过（组 >3 进不了 top-3），门④ 的 `EDIT_RHYTHM`
    #: 只剩 **3 个 (卡片,查询) 对**（而这三组覆盖的卡片槽位合计 **299** 个）；
    #: ② 门⑥ 连带丢掉那几百个卡片槽位。
    #: 注：早先试过**同时**加 `头留白`＋`平均镜长`，索引派生排序回落（Q1 0.7189→0.6574），
    #: 因此当时只留了 `强度`。这一次是**只加 `平均镜长`**，并且以"能不能拆开这 3 个
    #: 退化的组"为判据 —— 指标见提交信息。
    "镜长": "avg_shot_len",
}

#: `forbid` 值的**独立查询键**（v1.6，协议 §2.1 键集的扩展）。
#:
#: 为什么必须另给一套键：`q` 里同一个键只能有一个取值。当一条边的**必填**成员是
#: `构图=occlusion`、而它又**禁止** `构图=balance` 时，`构图` 这个键已经被必填值占了，
#: 被禁止的那个取值**写不进 `q`**。后果实测：`STAGING_PACK` 有 4 条边**必填成员完全相同、
#: 只差"禁止哪个构图规则"**，它们因此共用一个 `q`、彼此不可区分，oracle 通道整组跳过
#: （组 >3 进不了 top-3）——**150 张卡**在门⑥ 里永远拿不到条目。
#:
#: 新键形如 `禁<主键>`（`禁构图`／`禁运镜`／`禁音效`…），**映射到同一个 kind**，
#: 所以 `q` 里可以同时写 `构图=occlusion`（要）与 `禁构图=balance`（不要）：
#: 前者满足门⑨"必填槽位要写进 q"，后者把四条边区分开。这也正是协议 §3.3 的
#: Q7 冲突语义（"你点名了一个被这条边禁止的取值"），并且与 Q4 的机制同源。
#:
#: 只给**内容型 kind**（`NODE_TYPES`）发键：schema 常量（`pair`／`headroom_policy`／
#: `applies_to_*`）本来就禁止被当作 forbid 宿主（见 `_forbid_hosts`）。
FORBID_QUERY_KEYS: Dict[str, str] = {
    "禁" + key: kind for key, kind in QUERY_KEYS.items() if kind in NODE_TYPES
}

#: 查询值的别名（§2.3 第 1 步要求"别名至少覆盖查询里会出现的值"）。
VALUE_ALIASES: Dict[str, str] = {
    "甩镜": "whip_pan", "甩镜头": "whip_pan", "whip_pan": "whip_pan",
    "固定机位": "固定", "固定": "固定", "static": "固定",
    "中景": "MS", "中近景": "MCU", "特写": "CU", "大特写": "ECU",
    "近景": "MCU", "全景": "LS", "远景": "ELS",
    "荒诞": "荒诞", "滑稽": "荒诞", "absurd": "荒诞",
    "跺脚": "跺脚", "stomp": "跺脚",
    "石化": "petrify", "petrify": "petrify",
}


class GateError(ValueError):
    """单条超边未通过校验门。"""


@dataclass(frozen=True)
class Node:
    node_id: str
    type: str
    name: str
    aliases: Tuple[str, ...] = ()
    value: str = ""
    unit: str = ""

    @property
    def text(self) -> str:
        return f"{self.type} {self.name} {' '.join(self.aliases)} {self.value or ''}".strip()

    def to_dict(self) -> Dict:
        return {"record": "node", "node_id": self.node_id, "type": self.type,
                "name": self.name, "aliases": list(self.aliases),
                "value": self.value, "unit": self.unit}

    @classmethod
    def from_dict(cls, data: Dict) -> "Node":
        return cls(node_id=data["node_id"], type=data["type"], name=data.get("name", ""),
                   aliases=tuple(data.get("aliases", [])), value=data.get("value", ""),
                   unit=data.get("unit", ""))


@dataclass(frozen=True)
class Member:
    role: str
    kind: str
    node_id: str

    def __str__(self) -> str:
        return f"{self.role}:{self.kind}:{self.node_id}"

    def to_dict(self) -> List[str]:
        return [self.role, self.kind, self.node_id]

    @classmethod
    def from_dict(cls, data: Sequence) -> "Member":
        return cls(role=str(data[0]), kind=str(data[1]), node_id=str(data[2]))


@dataclass
class HyperEdge:
    type: str
    members: Tuple[Member, ...]
    source_kind: str = "theory"
    hardness: str = "hard"
    weight: float = 1.0
    confidence: float = 0.7
    confidence_max: float = 0.7
    occurrences: int = 1
    sources: Tuple[str, ...] = ()
    source_span: Dict = field(default_factory=dict)
    extractor: Dict = field(default_factory=dict)
    provenance_kind: str = "生成卡片"
    schema_version: str = SCHEMA_VERSION
    #: 从索引文件读回时**声明**的 id（校验门 ② 要拿它和重算值对拍；
    #: 构造函数里算出来的 id 恒等于重算值，所以只有它能让门 ② 有牙齿）。
    declared_edge_id: str = ""

    @property
    def edge_id(self) -> str:
        return edge_id_for(self.type, self.members, self.source_kind, self.hardness,
                           self.schema_version)

    @property
    def norm_key(self) -> Tuple[str, frozenset]:
        return (self.type, frozenset((m.role, m.kind, m.node_id) for m in self.members))

    @property
    def dedupe_key(self) -> Tuple[str, frozenset, str, str]:
        return (self.type, frozenset((m.role, m.kind, m.node_id) for m in self.members),
                self.source_kind, self.hardness)

    def members_with(self, role: str) -> Tuple[Member, ...]:
        return tuple(m for m in self.members if m.role == role)

    @property
    def allows(self) -> Tuple[Member, ...]:
        return self.members_with("allow")

    @property
    def forbids(self) -> Tuple[Member, ...]:
        return self.members_with("forbid")

    @property
    def qualifiers(self) -> Tuple[Member, ...]:
        return self.members_with("qualifier")

    def to_dict(self) -> Dict:
        return {
            "record": "edge",
            "edge_id": self.edge_id,
            "type": self.type,
            "members": [m.to_dict() for m in self.members],
            "weight": self.weight,
            "confidence": self.confidence,
            "confidence_max": self.confidence_max,
            "occurrences": self.occurrences,
            "sources": list(self.sources),
            "source_span": dict(self.source_span),
            "extractor": dict(self.extractor),
            "source_kind": self.source_kind,
            "hardness": self.hardness,
            "provenance_kind": self.provenance_kind,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "HyperEdge":
        return cls(
            type=str(data["type"]),
            members=tuple(Member.from_dict(m) for m in data["members"]),
            source_kind=str(data.get("source_kind", "theory")),
            hardness=str(data.get("hardness", "hard")),
            weight=float(data.get("weight", 1.0)),
            confidence=float(data.get("confidence", 0.7)),
            confidence_max=float(data.get("confidence_max", data.get("confidence", 0.7))),
            occurrences=int(data.get("occurrences", 1)),
            sources=tuple(data.get("sources", [])),
            source_span=dict(data.get("source_span", {})),
            extractor=dict(data.get("extractor", {})),
            provenance_kind=str(data.get("provenance_kind", "生成卡片")),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            declared_edge_id=str(data.get("edge_id", "")),
        )


def edge_id_for(edge_type: str, members: Iterable[Member], source_kind: str,
                hardness: str, schema_version: str = SCHEMA_VERSION) -> str:
    """§2.3 的冻结公式：必须含 `source_kind` 与 `hardness`。"""
    payload = "|".join([
        edge_type,
        ",".join(sorted(str(m) for m in members)),
        source_kind,
        hardness,
        schema_version,
    ])
    return "hg:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def render_tokens(text: str) -> int:
    """超边渲染的 token 估算：CJK 单字约 1 token，拉丁词约 0.3 token（保守上界）。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    latin_words = re.findall(r"[A-Za-z]+", text)
    latin_chars = sum(len(word) for word in latin_words)
    other = len(text) - cjk - latin_chars
    return int(cjk + len(latin_words) * 0.3 + other * 0.3) + 1


# --------------------------------------------------------------------------- 校验门


def node_value(node: Optional["Node"], node_id: str) -> str:
    """取成员的"值"：优先节点显式 `value`，否则取 `node_id` 里 `kind:` 之后的部分。

    约定（P14-2 写死）：枚举型节点的 id 形如 `intensity:high` / `shot_size:CU`，
    因此即使抽取器忘了填 `value`，门⑨ 与打分仍然拿得到可判定的取值。
    """
    if node is not None and node.value:
        return node.value
    return node_id.split(":", 1)[1] if ":" in node_id else node_id


def _values_for(edge: HyperEdge, kind: str, roles: Sequence[str],
                nodes: Dict[str, Node]) -> List[str]:
    out: List[str] = []
    for member in edge.members:
        if member.kind != kind or member.role not in roles:
            continue
        out.append(node_value(nodes.get(member.node_id), member.node_id))
    return out


def validate_edge(edge: HyperEdge, nodes: Dict[str, Node]) -> None:
    """9 条校验门（§2.3 第 3 步）。不过门即抛 `GateError`，调用方计入 rejects。"""
    # (1) 边类型闭集
    if edge.type not in EDGE_TYPES:
        raise GateError(f"gate1_type:{edge.type}")
    # (2) edge_id 自洽（能按公式重算）＋ 边级属性闭集
    if edge.declared_edge_id:
        recomputed = edge_id_for(edge.type, edge.members, edge.source_kind,
                                 edge.hardness, edge.schema_version)
        if edge.declared_edge_id != recomputed:
            raise GateError("gate2_edge_id")
    if edge.source_kind not in SOURCE_KINDS:
        raise GateError(f"gate2_source_kind:{edge.source_kind}")
    if edge.hardness not in HARDNESS:
        raise GateError(f"gate2_hardness:{edge.hardness}")
    # (3) kind / role 闭集
    for member in edge.members:
        if member.kind not in ALLOWED_KINDS:
            raise GateError(f"gate3_kind:{member.kind}")
        if member.role not in ROLES:
            raise GateError(f"gate3_role:{member.role}")
    # (4) 必填成员齐 ＋ arity 不小于 2 ＋ 成员组合合法
    present = {(m.role, m.kind) for m in edge.members}
    for required in REQUIRED_MEMBERS[edge.type]:
        if required not in present:
            raise GateError(f"gate4_missing:{required[0]}/{required[1]}")
    legal = set(REQUIRED_MEMBERS[edge.type]) | set(OPTIONAL_MEMBERS[edge.type])
    for pair in present:
        if pair not in legal:
            raise GateError(f"gate4_illegal_member:{pair[0]}/{pair[1]}")
    if len(edge.members) < 2:
        raise GateError("gate4_arity")
    # (5) 同一 node_id 不得同时 allow 与 forbid
    allow_ids = {m.node_id for m in edge.allows}
    forbid_ids = {m.node_id for m in edge.forbids}
    if allow_ids & forbid_ids:
        raise GateError(f"gate5_allow_forbid_overlap:{sorted(allow_ids & forbid_ids)[0]}")
    # (6) source_span 可解析（chunk_id ＋ 字符区间）
    span = edge.source_span or {}
    if not str(span.get("chunk_id", "")).strip():
        raise GateError("gate6_source_span:chunk_id")
    if not (isinstance(span.get("start"), int) and isinstance(span.get("end"), int)
            and int(span["end"]) >= int(span["start"]) >= 0):
        raise GateError("gate6_source_span:range")
    # (7) 按 kind 逐类包含（只有 shot_size / genre 参与）
    for kind, applies_kind in (("shot_size", "applies_to_shot_size"),
                               ("genre", "applies_to_genre")):
        constrained = _values_for(edge, kind, ("allow", "forbid"), nodes)
        if not constrained:
            continue
        gate_values = _values_for(edge, applies_kind, ("qualifier",), nodes)
        if not gate_values:
            continue  # 缺省 = 全适用
        if not set(constrained) <= set(gate_values):
            raise GateError(f"gate7_containment:{kind}")
    # (8) 单条超边的渲染成本不超过 400 token
    if render_tokens(render_edge(edge, nodes)) > MAX_RENDER_TOKENS:
        raise GateError("gate8_render_cost")
    # (9) qualifier 的 value 必须落在 T3 的取值域内
    for member in edge.qualifiers + edge.allows:
        domain = VALUE_DOMAINS.get(member.kind)
        if domain is None:
            continue
        value = node_value(nodes.get(member.node_id), member.node_id)
        if value not in domain:
            raise GateError(f"gate9_value:{member.kind}={value}")


# --------------------------------------------------------------------------- 渲染


def render_edge(edge: HyperEdge, nodes: Dict[str, Node]) -> str:
    """把一条超边渲染成一行。闭合输出：`forbid` 必须与 `allow` 一起出现。"""
    def name(node_id: str) -> str:
        node = nodes.get(node_id)
        return node.name if node is not None and node.name else node_id

    allows: List[str] = []
    for member in edge.allows:
        if member.kind == "emotion":
            continue
        allows.append(f"{member.kind}={name(member.node_id)}")
    quals: List[str] = []
    for member in edge.qualifiers:
        quals.append(f"{member.kind}={node_value(nodes.get(member.node_id), member.node_id)}")
    forbids = sorted(name(m.node_id) for m in edge.forbids)
    emotion = ", ".join(name(m.node_id) for m in edge.allows if m.kind == "emotion")
    parts = [f"[{edge.type}]"]
    if emotion:
        parts.append(f"{emotion} =>")
    if allows:
        parts.append(" ".join(allows))
    if quals:
        parts.append(" ".join(quals))
    if forbids:
        parts.append("禁={" + ", ".join(forbids) + "}")
    return " ".join(parts)


def render_edges(edges: Sequence[HyperEdge], nodes: Dict[str, Node],
                 token_limit: int) -> Tuple[str, List[str], bool]:
    """原子注入：整条加入直到上限；装不下就整条不注入（绝不截断）。

    返回 `(渲染文本, dropped_edge_ids, quality_fail)`；单条自超限时
    `quality_fail = True`（§2.3 第 4 步）。

    分栏不在这里做：`KnowledgeRetriever.edge_columns` 已经把"硬约束／经验建议"
    按 §2.3b 的关键纪律 2 分好（而且带 `forbid` 的边**永远**进硬约束栏），
    这里只负责"把这一栏的边渲染成原子注入块"。
    """
    lines: List[str] = []
    dropped: List[str] = []
    quality_fail = False
    used = 0
    for edge in edges:
        line = render_edge(edge, nodes)
        cost = render_tokens(line)
        if cost > token_limit:
            dropped.append(edge.edge_id)
            quality_fail = True
            continue
        if used + cost > token_limit:
            dropped.append(edge.edge_id)
            continue
        lines.append(line)
        used += cost
    return "\n".join(lines), dropped, quality_fail


# --------------------------------------------------------------------------- 索引


@dataclass
class BuildReport:
    raw_edges: int = 0
    valid_unique: int = 0
    duplicates: int = 0
    rejects: int = 0
    reject_reasons: Dict[str, int] = field(default_factory=dict)
    processed_chunks: int = 0
    total_chunks: int = 0

    @property
    def reject_ratio(self) -> float:
        return self.rejects / self.raw_edges if self.raw_edges else 0.0

    @property
    def passed(self) -> bool:
        """§2.3 的构建门（唯一两处）：rejects 不超过 5% 且没有 chunk 被跳过。"""
        if self.raw_edges <= 0 or self.total_chunks <= 0:
            return False
        return (self.reject_ratio <= 0.05
                and self.processed_chunks == self.total_chunks
                and self.valid_unique > 0)

    def to_dict(self) -> Dict:
        return {
            "raw_edges": self.raw_edges,
            "valid_unique": self.valid_unique,
            "duplicates": self.duplicates,
            "rejects": self.rejects,
            "reject_reasons": dict(sorted(self.reject_reasons.items())),
            "reject_ratio": round(self.reject_ratio, 6),
            "processed_chunks": self.processed_chunks,
            "total_chunks": self.total_chunks,
            "passed": self.passed,
        }


def merge_duplicates(edges: Sequence[HyperEdge]) -> Tuple[List[HyperEdge], int]:
    """按 `(type, frozenset(members), source_kind, hardness)` 合并；次数只作权重。"""
    merged: Dict[Tuple, HyperEdge] = {}
    duplicates = 0
    for edge in edges:
        key = edge.dedupe_key
        if key not in merged:
            merged[key] = edge
            continue
        duplicates += 1
        keeper = merged[key]
        keeper.occurrences += edge.occurrences
        keeper.confidence_max = max(keeper.confidence_max, edge.confidence_max)
        keeper.confidence = max(keeper.confidence, edge.confidence)
        keeper.sources = tuple(sorted(set(keeper.sources) | set(edge.sources)))
    return list(merged.values()), duplicates


def build_index(edges: Sequence[HyperEdge], nodes: Dict[str, Node],
                processed_chunks: int, total_chunks: int,
                reject_sink: Optional[List[Dict]] = None,
                ) -> Tuple[List[HyperEdge], BuildReport]:
    """过 9 条门 -> 去重合并 -> 构建门报告（`raw = valid_unique + duplicates + rejects`）。

    `reject_sink` 给了就把**边级**拒收明细逐条追加进去。这条账必须能被外面的
    `hypergraph.rejects.jsonl` 逐行对上：manifest 说 `rejects=N` 而文件有 M 行时
    （N≠M），外人无法判断索引到底被门挡掉了多少东西——P14-5 的 Q0 就是这么判的。
    """
    report = BuildReport(raw_edges=len(edges), processed_chunks=processed_chunks,
                         total_chunks=total_chunks)
    valid: List[HyperEdge] = []
    for edge in edges:
        try:
            validate_edge(edge, nodes)
        except GateError as exc:
            report.rejects += 1
            key = str(exc).split(":", 1)[0]
            report.reject_reasons[key] = report.reject_reasons.get(key, 0) + 1
            if reject_sink is not None:
                reject_sink.append({"phase": "gate", "edge_id": edge.edge_id,
                                    "type": edge.type, "reason": str(exc)})
            continue
        valid.append(edge)
    unique, duplicates = merge_duplicates(valid)
    report.valid_unique = len(unique)
    report.duplicates = duplicates
    if report.raw_edges != report.valid_unique + report.duplicates + report.rejects:
        raise AssertionError("超边计数恒等式被打破：raw ≠ valid_unique + duplicates + rejects")
    return unique, report


# --------------------------------------------------------------------------- 检索


def parse_query(text: str) -> Dict[str, List[str]]:
    """解析 `SceneContract` 查询串：`情绪=荒诞；动作=跺脚；运镜=固定；景别=中景`。"""
    return parse_query_full(text)[0]


def parse_query_full(text: str) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """解析查询串，返回 ``(正向槽位, 禁用槽位)``。

    **为什么需要第二个字典（2026-10-01 修）**：`6c82511` 给 `forbid` 值配了独立查询键
    `禁<键>`（`FORBID_QUERY_KEYS`，例如 `禁运镜=固定`），标注通道也确实按它写 `q`——
    但这里的解析器**只查 `QUERY_KEYS`**，于是 `禁…=…` 那一段被**整段丢掉**：检索器既
    不知道"用户要的是禁止固定机位"，`score()` 里那段 `forbid_hit` 也永远算不出来。
    协议 §2.1 的契约串里，"要"与"不要"是两半，只解析一半等于把禁忌那半扔了。

    `parse_query` 的行为**保持不变**（只返回正向那半），这样既有调用点（holdout_score、
    expansion_caps、holdout_ceiling、测试）不受影响；检索器改用这个完整版。
    """
    out: Dict[str, List[str]] = {}
    forbid: Dict[str, List[str]] = {}
    for chunk in re.split(r"[；;]", text or ""):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, raw_value = chunk.partition("=")
        key = key.strip()
        value = raw_value.strip()
        kind = QUERY_KEYS.get(key)
        bucket = out
        if kind is None:
            kind = FORBID_QUERY_KEYS.get(key)
            bucket = forbid
        if kind is None:
            continue
        if kind == "scene_type" and value in ("有", "是", "yes", "true"):
            value = "dialogue"
        bucket.setdefault(kind, []).append(VALUE_ALIASES.get(value, value))
    return out, forbid


@dataclass
class RetrievalTrace:
    query: str = ""
    seeds: List[str] = field(default_factory=list)
    #: 查询里显式写下的 `禁<键>=值`（`parse_query_full` 的第二半）。
    #: 以前这一半被解析器整段丢掉，trace 里也就看不到"这次到底禁了什么"。
    forbid_seeds: Dict[str, List[str]] = field(default_factory=dict)
    expanded_edges: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    selected: List[str] = field(default_factory=list)
    seed_miss: bool = False
    expansion_truncated: bool = False
    dropped_edge_ids: List[str] = field(default_factory=list)
    quality_fail: bool = False

    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "seeds": list(self.seeds),
            "expanded_edges": list(self.expanded_edges),
            "scores": {k: round(v, 6) for k, v in self.scores.items()},
            "selected": list(self.selected),
            "seed_miss": self.seed_miss,
            "expansion_truncated": self.expansion_truncated,
            "dropped_edge_ids": list(self.dropped_edge_ids),
            "quality_fail": self.quality_fail,
        }


class Hypergraph:
    """节点 ＋ 超边 ＋ 四步检索。"""

    def __init__(self, nodes: Sequence[Node], edges: Sequence[HyperEdge]) -> None:
        self.nodes: Dict[str, Node] = {node.node_id: node for node in nodes}
        self.edges: List[HyperEdge] = list(edges)
        self.by_id: Dict[str, HyperEdge] = {edge.edge_id: edge for edge in self.edges}
        self.adjacency: Dict[str, List[str]] = {}
        for edge in self.edges:
            for member in edge.members:
                self.adjacency.setdefault(member.node_id, []).append(edge.edge_id)
        self.max_occurrences = max((e.occurrences for e in self.edges), default=1)

    # ------------------------------------------------------------------ 种子
    def seeds_for(self, query: Dict[str, List[str]],
                  per_value: Optional[Dict[Tuple[str, str], set]] = None
                  ) -> List[str]:
        """在 `node_text` 上做词面匹配（词元命中数 / 长度归一）。

        **曾经的单点修法都失败过，别重犯**：只留精确命中会让 Q1 0.934 → 0.917、
        Q2 0.997 → 0.971（召回掉了）；把覆盖率整个改成"按查询取值算"会让独立标定
        工具（`tools/knowledge/ranking_quality.py`）的 Q1 从 0.70 掉到 0.66。

        **2026-10-02：多目标扫参之后改成混合口径**，见 `COVERAGE_VALUE_BLEND` ——
        两个分母按系数相加，0.1–0.3 是一个平台。同一次修正还改了扩展额度
        （`expand`：按边排队而不是按遍历顺序），两项合起来实测：

            Q1  0.8599 → 0.8655     Q2  0.9954 → 1.0000
            Q4  0.9956 → 1.0000     Q6b 0.9994 → 1.0000
            标定 Q1 0.6870 → 0.7005   标定 Q2 0.9851 → 0.9919

        四项**同时**变好，且两条合同线（Q4/Q6b = 1.0）第一次被关上。
        产出侧的 `per_value` 由本函数顺带填好（哪个取值把哪些节点拉成了种子）——
        `_edge_coverage` 按它算第二种分母。
        """
        wanted = [value for values in query.values() for value in values]
        if not wanted:
            return []
        #: 哪些节点是被**哪一个查询取值**拉进来的——`_edge_coverage` 的第二种分母
        #: （按查询取值算）要用它：一个取值命中 8 个节点时，边只要命中其中任一节点，
        #: 就算"这个取值被解释了"，不再被那 8 个节点稀释。
        owner: Dict[str, Tuple[str, str]] = {}
        for kind, values in query.items():
            for value in values:
                owner.setdefault(value, (kind, value))
        scored: List[Tuple[float, str]] = []
        for node in self.nodes.values():
            text_tokens = set(_bm25_tokenize(node.text))
            if not text_tokens:
                continue
            hits = 0
            for value in wanted:
                value_tokens = set(_bm25_tokenize(value))
                if value_tokens and (value_tokens <= text_tokens or value == node.value):
                    hits += 1
                    if per_value is not None:
                        per_value.setdefault(owner[value], set()).add(node.node_id)
            if hits:
                scored.append((hits / (1.0 + math.log1p(len(text_tokens))), node.node_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [node_id for _score, node_id in scored[:SEED_TOP_K]]

    # ------------------------------------------------------------------ 扩展
    def _edge_coverage(self, edge: HyperEdge, seed_set: set,
                       per_value: Optional[Dict[Tuple[str, str], set]] = None,
                       query: Optional[Dict[str, List[str]]] = None) -> float:
        if not seed_set:
            return 0.0
        # **禁用成员不算"正向覆盖"**：查询 `构图=rule_of_thirds` 不能被一条
        # `禁构图=rule_of_thirds` 的边满足 —— 那正是"问三分法、答不要用三分法"。
        # 与 `_edge_precision`（本来就排除 forbid）取同一口径。实测：这条改动把
        # 主导 Q4 缺口的那一条查询（重复 34 次）的 required 边从 top-3 之外拉回来。
        members = {m.node_id for m in edge.members if m.role != "forbid"}
        by_seed_set = len(members & seed_set) / len(seed_set)
        blend = COVERAGE_VALUE_BLEND
        if blend <= 0.0 or not per_value or not query:
            return by_seed_set
        #: 按**查询取值**算：这个取值命中的节点里，只要有一个落在这条边上，
        #: 就算"这个取值被解释了"。分母是查询取值数，不是被展开出来的种子数。
        values = [(kind, value) for kind, values in query.items() for value in values]
        if not values:
            return by_seed_set
        kinds = {m.kind: set() for m in edge.members if m.role != "forbid"}
        for member in edge.members:
            if member.role != "forbid":
                kinds.setdefault(member.kind, set()).add(member.node_id)
        explained = 0
        for kind, value in values:
            nodes_for_value = per_value.get((kind, value)) or set()
            if nodes_for_value & kinds.get(kind, set()):
                explained += 1
        by_value = explained / len(values)
        return (1.0 - blend) * by_seed_set + blend * by_value

    def _edge_precision(self, edge: HyperEdge, seed_set: set) -> float:
        """查询里的种子解释了这条边的多少（`forbid` 成员不计入分母）。

        与 `score()` 里那一项**同一份口径**：枢纽截断要按"整条边都被查询解释"
        优先保住，否则一条成员全在查询里的边会被 occurrences 挤出候选。
        """
        members = [m for m in edge.members if m.role != "forbid"]
        if not members or not seed_set:
            return 0.0
        return len({m.node_id for m in members} & seed_set) / len(members)

    def expand(self, seed_ids: Sequence[str]) -> Tuple[List[HyperEdge], bool]:
        seed_set = set(seed_ids)
        frontier = list(seed_ids)
        seen_nodes = set(seed_ids)
        seen_edges: Dict[str, HyperEdge] = {}
        truncated = False
        hub_threshold = len(self.edges) / 20.0 if self.edges else 0.0
        #: 一条边的排序键：**候选额度要按这个全局排**，不能按"哪个种子先被遍历到"。
        #: 实测（2026-10-02）：`构图=headroom；景别=MCU；机位=平视` 的 required 边在
        #: 它相邻的**每一个**节点上都排第 1，却因为前几个种子（`headroom_policy:board`
        #: 这种通用节点）先把 `MAX_EDGES_TOTAL=40` 的额度吃光，连候选都不是——
        #: Q4 就永远差那一对。改成"本跳所有邻居先合并、再按同一把尺子取前 40"，
        #: 额度分配与遍历顺序无关。
        def rank_key(edge: HyperEdge) -> Tuple:
            return (-self._edge_coverage(edge, seed_set),
                    -self._edge_precision(edge, seed_set),
                    -edge.occurrences, edge.edge_id)

        for _hop in range(MAX_HOPS):
            next_frontier: List[str] = []
            pooled: Dict[str, HyperEdge] = {}
            for node_id in frontier:
                candidates = self.adjacency.get(node_id, [])
                edges = [self.by_id[eid] for eid in candidates]
                if hub_threshold and len(candidates) > hub_threshold:
                    edges.sort(key=rank_key)
                    edges = edges[:HUB_EDGES_PER_NODE]
                    truncated = truncated or len(candidates) > len(edges)
                for edge in edges:
                    if edge.edge_id in seen_edges:
                        continue
                    pooled.setdefault(edge.edge_id, edge)
            budget = MAX_EDGES_TOTAL - len(seen_edges)
            ordered = sorted(pooled.values(), key=rank_key)
            if len(ordered) > budget:
                truncated = True
            for edge in ordered[:budget]:
                seen_edges[edge.edge_id] = edge
                for member in edge.members:
                    if member.node_id in seen_nodes:
                        continue
                    if len(seen_nodes) >= MAX_NODES:
                        truncated = True
                        continue
                    seen_nodes.add(member.node_id)
                    next_frontier.append(member.node_id)
            frontier = next_frontier
            if not frontier:
                break
        return list(seen_edges.values()), truncated

    # ------------------------------------------------------------------ 打分
    def score(self, edge: HyperEdge, query: Dict[str, List[str]], seed_set: set,
              forbid_query: Optional[Dict[str, List[str]]] = None,
              per_value: Optional[Dict[Tuple[str, str], set]] = None) -> float:
        coverage = self._edge_coverage(edge, seed_set, per_value, query)
        # 精确率：种子解释了这条边的多少。**超集边**在只有 coverage 时与精确匹配同分，
        # 会靠 occurrences/confidence 挤掉后者（实测 Q1 0.517 → 加这一项后 0.587）。
        precision = self._edge_precision(edge, seed_set)
        priority = TYPE_PRIORITY.get(edge.type, 0.5)
        occurrence = (math.log1p(edge.occurrences) / math.log1p(self.max_occurrences)
                      if self.max_occurrences > 0 else 0.0)
        authority = AUTHORITY.get(edge.provenance_kind, DEFAULT_AUTHORITY)
        forbid_hit = 0.0
        for member in edge.forbids:
            value = node_value(self.nodes.get(member.node_id), member.node_id)
            # 两种"命中"都算，但**都不再影响正向覆盖**（见 `_edge_coverage`）：
            # ① 查询显式写了 `禁<键>=值`（`parse_query_full` 的第二半，此前被解析器
            #    整段丢掉）→ 这条边正是用户要避开的对象，顶上来；
            # ② 查询**正向**点名了某个取值、而这条边把它标成禁忌 → 冲突信息，
            #    照样值得顶上来（R31 的"禁忌命中加成"原意）。
            # 实测（2026-10-01，v12 的 2438 条）：只做 ① Q1 0.8712 / Q4 0.9953 /
            # Q6b 0.9991；① ＋ ② 全部再涨一点（0.8724 / 0.9957 / 0.9993）。
            if (value in (forbid_query or {}).get(member.kind, [])
                    or value in query.get(member.kind, [])):
                forbid_hit = 1.0
                break
        return (SCORE_WEIGHTS["coverage"] * coverage
                + SCORE_WEIGHTS["precision"] * precision
                + SCORE_WEIGHTS["type_priority"] * priority
                + SCORE_WEIGHTS["occurrences"] * occurrence
                + SCORE_WEIGHTS["confidence"] * edge.confidence
                + SCORE_WEIGHTS["authority"] * authority
                + SCORE_WEIGHTS["forbid_hit"] * forbid_hit)

    # ------------------------------------------------------------------ 四步
    def retrieve(self, query_text: str, top_k: int = 5,
                 token_limit: int = MAX_RENDER_TOKENS
                 ) -> Tuple[List[HyperEdge], str, RetrievalTrace]:
        #: 契约串的**两半都要**：正向槽位决定"要什么"，`禁<键>=值` 决定"不要什么"。
        #: 种子展开把两半都算上（禁忌所在的节点也要能成为入口），但覆盖/精确率只
        #: 用正向那半（见 `_edge_coverage` 与 `_edge_precision`）。
        query, forbid_query = parse_query_full(query_text)
        trace = RetrievalTrace(query=query_text)
        seed_query = {kind: list(values) for kind, values in query.items()}
        for kind, values in forbid_query.items():
            seed_query.setdefault(kind, []).extend(values)
        per_value: Dict[Tuple[str, str], set] = {}
        seed_ids = self.seeds_for(seed_query, per_value)
        if not seed_ids:
            trace.seed_miss = True
            return [], "", trace
        if forbid_query:
            trace.forbid_seeds = {kind: list(values)
                                  for kind, values in forbid_query.items()}
        trace.seeds = list(seed_ids)
        seed_set = set(seed_ids)
        candidates, truncated = self.expand(seed_ids)
        trace.expansion_truncated = truncated
        trace.expanded_edges = [e.edge_id for e in candidates]
        scored = [(self.score(edge, query, seed_set, forbid_query, per_value), edge)
                  for edge in candidates]
        scored.sort(key=lambda item: (-item[0], item[1].edge_id))
        for value, edge in scored:
            trace.scores[edge.edge_id] = value
        selected = [edge for _value, edge in scored[:max(1, top_k)]]
        trace.selected = [e.edge_id for e in selected]
        text, dropped, quality_fail = render_edges(selected, self.nodes, token_limit)
        trace.dropped_edge_ids = dropped
        trace.quality_fail = quality_fail
        return selected, text, trace
