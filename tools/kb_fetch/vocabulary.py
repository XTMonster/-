"""从卡片里**确定性地**汇总节点词表（P14-1 产出，P14-2 与标注共用）。

为什么要机器汇总而不是让模型自由发挥：超边的成员必须是**闭集**里的 node_id，
否则 `norm_key` 对不上、held-out 的 `must` 也无从书写（§2.3d 的"词表未冻结前
不得开始正式标注"）。这份词表只做两件事：

1. 把枚举型 kind（`VALUE_DOMAINS` 里有的）铺成规范节点；
2. 把卡片里真实出现过的开放型取值（情绪 / 运镜 / 光位 / 机位 / 特效 / 构图规则 /
   节奏 / 题材）按**固定的词表**收进来——只收词表里认得的，不猜。

输出两份：`knowledge/hypergraph.vocab.json`（给标注与抽取）与
`fixtures/knowledge_holdout.vocab.json`（给 `tools/check_holdout.py` 的门③）。
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Dict, Iterable, List, Sequence, Tuple

try:
    from . import common
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common  # type: ignore

from block_director.contracts.enums import VFX_TYPES
from block_director.knowledge import hypergraph as hg

#: 开放型 kind 的受控词表（中文规范名 -> 别名）。只收表里认得的取值。
EMOTIONS = (
    ("荒诞", ("滑稽", "absurd", "怪诞")), ("愤怒", ("暴怒", "气急败坏")),
    ("焦虑", ("紧张", "不安")), ("恐惧", ("害怕", "惊恐")),
    ("悲伤", ("难过", "哀伤")), ("孤独", ("疏离", "落寞")),
    ("喜悦", ("开心", "愉快")), ("压抑", ("憋闷", "沉闷")),
    ("温柔", ("柔和", "亲密")), ("冷漠", ("冷峻", "无表情")),
    ("期待", ("盼望", "悬念")), ("绝望", ("无望", "崩溃")),
    ("讽刺", ("嘲弄", "黑色幽默")), ("庄严", ("肃穆", "仪式感")),
    #: `安静` 是**实测补进来的**：`cine_move_handheld` 的卡写"*禁忌：安静的对话用手持*"，
    #: 而抽出来的边是 `emotion=平静 ＋ forbid_movement=handheld` —— 意思对得上，别名表
    #: 里却没有"安静"，于是阶段二的落地判据把这条**正确的**禁令判成"主体是编的"。
    #: 同类词（`安宁`／`留白`）本来就在表里，补"安静"不是放宽判据，是把漏掉的那一个补上。
    ("混乱", ("失序", "躁动")), ("平静", ("安宁", "留白", "安静")),
)

SHOT_SIZE_NAMES = {
    "ECU": ("大特写", "极特写"), "CU": ("特写",), "MCU": ("中近景", "近景"),
    "MS": ("中景",), "MLS": ("中远景",), "LS": ("全景", "全身"), "ELS": ("远景", "大远景"),
}

LIGHTING = (
    ("逆光", ("背光", "轮廓光")), ("顶光", ("正上方光",)), ("底光", ("脚光",)),
    ("侧光", ("侧面光", "四十五度光")), ("正面光", ("顺光",)),
    ("低调", ("低照度", "暗调")), ("高调", ("高照度", "亮调")),
    ("暖光", ("低色温", "钨丝灯")), ("冷光", ("高色温", "日光")),
)

CAMERA_ANGLES = (
    ("平视", ("眼平", "eye_level")), ("低机位", ("仰拍", "低角度")),
    ("高机位", ("俯拍", "高角度")), ("荷兰角", ("倾斜", "滚转")),
    ("骑轴", ("中性机位",)), ("过肩", ("OTS",)),
)

COMPOSITION_RULES_ZH = {
    "rule_of_thirds": ("三分法",), "headroom": ("头顶留白", "头顶不切"),
    "lead_room": ("视线留白", "前视空间"), "balance": ("平衡", "重心"),
    "occlusion": ("遮挡", "前景遮挡"), "framing": ("景别匹配", "取景"),
}

PACING_ZH = {"short": ("短镜", "快切", "短镜硬切"), "medium": ("常规节奏",),
             "long": ("长镜", "长镜留白", "凝视")}

VFX_ZH = {
    "flame": ("火焰", "火"), "glow": ("发光", "辉光"), "smoke": ("烟", "烟雾"),
    "spark": ("火花", "sparks"),
}

EXTRA_VFX = (("petrify", ("石化",)), ("impact_frame", ("冲击帧", "定格冲击")))

#: 查询键覆盖但语料里不一定显式标注的 kind：给一份**受控小词表**，
#: 否则 `q` 里写到的取值会被门③ 判成"词表外的取值"。
ACTIONS = (
    ("跺脚", ("跺足",)), ("转身", ("回头",)), ("起身", ("站起",)), ("坐下", ("落座",)),
    ("挥手", ("招手",)), ("推门", ("开门",)), ("低头", ("垂头",)), ("后退", ("退步",)),
)
SFX = (
    ("低频轰鸣", ("轰鸣", "低频")), ("尖锐哨音", ("哨音", "耳鸣")), ("雨声", ("雨",)),
    ("心跳", ("心跳声",)), ("静默", ("无声", "寂静")), ("金属撞击", ("撞击",)),
)
AXIS_TOPICS = (
    ("关系轴", ("人物连线",)), ("运动轴", ("运动方向",)), ("视线轴", ("视线方向",)),
    ("越轴", ("跳轴",)), ("中性机位", ("骑轴", "中性镜头")),
)
#: v1.6 三块新增内容各自的受控词表。**为什么给闭集而不是像 `action` 那样放开**：
#: `action` 放开之后实测被话题名词污染（170/915 条边把"人物弧光"写进动作槽位），
#: 靠事后清洗才压下去。新 kind 一开始就收在闭集里，别名表负责把卡片里的常见说法
#: 映射到规范值，`occurrences` 计数因此仍然真实（卡片正文提到别名就算命中）。
DELIVERIES = (
    ("耳语", ("低语", "气声", "轻声")), ("喊叫", ("吼", "咆哮", "嘶喊")),
    ("平淡", ("平铺", "无起伏", "克制念白")), ("颤抖", ("颤声", "发抖", "哽咽")),
    ("画外音", ("旁白", "独白", "voice over", "vo")),
)
MUSIC_STRATEGIES = (
    ("静默", ("无声", "静音", "留白处理")), ("铺底", ("背景音乐", "配乐", "垫乐")),
    ("重音", ("打击乐", "强调音", "重音落下")), ("环境底噪", ("环境声", "氛围声", "底噪", "ambience")),
)
PROPS = (
    ("手持道具", ("道具", "手持物件", "手中物")), ("陈设", ("摆设", "家具", "布置")),
    ("环境元素", ("布景", "场景元素", "背景元素")),
)

GENRE_ZH = {"film": ("电影", "剧情片"), "anime": ("动画", "日式动画"),
            "documentary": ("纪录片", "纪实")}

#: 运镜的中文名（与 `contracts/enums.py::MOVEMENT_TYPES` 一一对应）。
MOVEMENT_ZH = {
    "pan_left": ("左摇",), "pan_right": ("右摇",), "tilt_up": ("上摇",),
    "tilt_down": ("下摇",), "dolly_in": ("推镜", "推近"), "dolly_out": ("拉镜", "拉远"),
    "zoom_in": ("变焦推近",), "zoom_out": ("变焦拉远",),
    "dolly_zoom": ("移焦眩晕", "希区柯克变焦", "变焦推拉"),
    "track_left": ("左移",), "track_right": ("右移",),
    "orbit_cw": ("顺时针环绕",), "orbit_ccw": ("逆时针环绕",),
    "crane_up": ("升",), "crane_down": ("降",),
    "crane_arc_up": ("弧线升",), "crane_arc_down": ("弧线降",),
    "whip_pan_left": ("左甩镜",), "whip_pan_right": ("右甩镜",),
    "handheld": ("手持",), "steadicam": ("斯坦尼康",),
    "follow_subject": ("跟拍", "跟随"), "lead_subject": ("前置引导",),
    "push_through": ("穿越推进",),
    # 查询里最常用的"固定"不在 MOVEMENT_TYPES 里（引擎用静止机位表达）
    "固定": ("固定机位", "static", "静止机位"),
}

_LENS_RE = re.compile(r"\b(\d{2,3})\s*mm\b", re.IGNORECASE)


def _add(nodes: Dict[str, Dict], node_id: str, kind: str, name: str,
         aliases: Iterable[str] = (), value: str = "") -> None:
    entry = nodes.setdefault(node_id, {"node_id": node_id, "type": kind, "name": name,
                                       "aliases": [], "value": value, "unit": ""})
    for alias in aliases:
        alias = str(alias).strip()
        if alias and alias not in entry["aliases"]:
            entry["aliases"].append(alias)


def _text_of(card) -> str:
    parts = [card.title, card.content, card.emotion, " ".join(card.keywords),
             " ".join(card.tags), " ".join(card.rules)]
    return " ".join(parts)


def build_nodes(cards) -> List[Dict]:
    nodes: Dict[str, Dict] = {}

    # 1) 枚举型 kind：规范值直接铺满
    for kind, values in hg.VALUE_DOMAINS.items():
        if values is None:
            continue
        for value in values:
            _add(nodes, f"{kind}:{value}", kind, value, value=value)

    # 2) 景别 / 运镜 / 情绪 / 光位 / 机位 / 特效 / 构图 / 节奏 / 题材：受控中文词表
    for canon, values in SHOT_SIZE_NAMES.items():
        _add(nodes, f"shot_size:{canon}", "shot_size", canon, values, value=canon)
    for canon, values in MOVEMENT_ZH.items():
        _add(nodes, f"movement:{canon}", "movement", values[0] if values else canon,
             values, value=canon)
    for canon, values in EMOTIONS:
        _add(nodes, f"emotion:{canon}", "emotion", canon, values, value=canon)
    for canon, values in LIGHTING:
        _add(nodes, f"lighting:{canon}", "lighting", canon, values, value=canon)
    for canon, values in CAMERA_ANGLES:
        _add(nodes, f"camera_angle:{canon}", "camera_angle", canon, values, value=canon)
    for canon, values in tuple(VFX_ZH.items()) + EXTRA_VFX:
        _add(nodes, f"vfx:{canon}", "vfx", canon, values, value=canon)
    for canon, values in COMPOSITION_RULES_ZH.items():
        _add(nodes, f"composition_rule:{canon}", "composition_rule", canon, values,
             value=canon)
    for canon, values in PACING_ZH.items():
        _add(nodes, f"pacing:{canon}", "pacing", canon, values, value=canon)
    for canon, values in GENRE_ZH.items():
        _add(nodes, f"genre:{canon}", "genre", canon, values, value=canon)
    for canon, values in ACTIONS:
        _add(nodes, f"action:{canon}", "action", canon, values, value=canon)
    for canon, values in SFX:
        _add(nodes, f"sfx:{canon}", "sfx", canon, values, value=canon)
    for canon, values in AXIS_TOPICS:
        _add(nodes, f"axis_topic:{canon}", "axis_topic", canon, values, value=canon)
    for canon, values in DELIVERIES:
        _add(nodes, f"delivery:{canon}", "delivery", canon, values, value=canon)
    for canon, values in MUSIC_STRATEGIES:
        _add(nodes, f"music:{canon}", "music", canon, values, value=canon)
    for canon, values in PROPS:
        _add(nodes, f"prop:{canon}", "prop", canon, values, value=canon)

    # 3) 只收卡片里**真实出现过**的取值（词表认得、且正文/标签里出现过）
    for card in cards:
        text = _text_of(card)
        for bucket in (nodes,):
            for node_id, entry in bucket.items():
                if entry["type"] == "lens":
                    continue
                names = [entry["name"]] + list(entry["aliases"])
                if any(name and name in text for name in names):
                    entry.setdefault("occurrences", 0)
                    entry["occurrences"] = int(entry.get("occurrences", 0)) + 1
        for lens in _LENS_RE.findall(text):
            _add(nodes, f"lens:{lens}mm", "lens", f"{lens}mm", value=f"{lens}mm")
            nodes[f"lens:{lens}mm"]["occurrences"] = \
                int(nodes[f"lens:{lens}mm"].get("occurrences", 0)) + 1

    # 4) `action` 只能是**看得见的身体行为**（审计 #16）。
    #
    # 旧规则把 performance／blocking 域卡片里长度 ≤6 的 tag **全部**铺成
    # `action:` 节点（"让必填槽位有的可填"）。而 tag 是卡片生成模型写的**话题词**，
    # 于是实测 343 个 action 节点里只有 7 个是真动作，837 条边里 258 条
    # （`ACTION_BEAT` 69%、`PERFORMANCE_PACK`）带一个不是动作的 `action` 取值
    # （`动作`×41、`反应`×27、`克制`×15、`人物塑造`×12…）。抽取提示早就写了
    # "不能写概念/技法/流程/职务"，可**节点表把话题词当成了合法取值**，模型自然照抄。
    #
    # 现在只收两份来源，都不靠猜：
    #   1. 受控表 `ACTIONS`（人工维护的可见行为）；
    #   2. `knowledge/action_lexicon.json` 里**判定通过**的标签——那份文件由
    #      `tools/kb_fetch/action_lexicon.py` 用抽取族模型按同一条判据逐词判定后
    #      钉进仓库（带模型与提示指纹），所以这里仍然是确定性的。
    #
    # 文件缺席时**只**回落受控表：宁可 `ACTION_BEAT` 少几条，也不要再铺话题词
    # （`build_hypergraph` 规则 8b：卡里确实没有看得见的行为时，就不该写这类边）。
    for value in _action_values():
        _add(nodes, f"action:{value}", "action", value, value=value)

    return sorted(nodes.values(), key=lambda n: (n["type"], n["node_id"]))


def _action_values() -> List[str]:
    """`action:` 节点的取值全集：受控表 ＋ 已钉住的判定结果。

    读不到 `action_lexicon.json` 时**只**返回受控表 —— 这是刻意的：回落旧规则
    等于把 258 条污染边重新放回索引（审计 #16），而"少几条 `ACTION_BEAT`"是可
    接受的代价（`docs/knowledge/AUDIT_TRIAGE.md` #16 的处分）。
    """
    values = [canon for canon, _ in ACTIONS]
    path = common.KNOWLEDGE / "action_lexicon.json"
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        for value in (payload.get("controlled") or []) + (payload.get("accepted") or []):
            value = str(value).strip()
            if value and value not in values:
                values.append(value)
    return values


def vocab_payload(nodes: Sequence[Dict]) -> Dict[str, List[str]]:
    """`tools/check_holdout.py --vocab` 的输入：{kind: [取值, ...]}。"""
    out: Dict[str, List[str]] = {}
    for node in nodes:
        if node["type"] == "lens":
            continue
        value = node.get("value") or node["node_id"]
        values = out.setdefault(node["type"], [])
        for candidate in {value, node["name"], *node.get("aliases", [])}:
            if candidate and candidate not in values:
                values.append(candidate)
    return {kind: sorted(values) for kind, values in sorted(out.items())}


#: 查询键覆盖的 kind（`tools/check_holdout.py::Q_KEY_TO_KIND` 的值集）。
#: held-out 的词表**只能**含这些 kind：校验器的门③ 是双向的，多出来的 kind
#: 的取值永远"没被用过"，会把门③ 直接判红。
HOLDOUT_KINDS: Tuple[str, ...] = (
    "emotion", "action", "movement", "shot_size", "lens", "pacing", "vfx", "sfx",
    "camera_angle", "lighting", "composition_rule", "axis_topic", "genre", "beat_type",
    "intent",
)

#: 没有查询键、只能以**空表占位**的 kind。
#:
#: v1.5 时这里是 `("character", "object")`——它们是索引侧节点类型，`q` 里没有对应键，
#: 只能在词表里占个空位（否则门③ 判"缺 kind → 该 kind 免检"并直接失败）。
#: **v1.6 已把这两个 kind 从 `NODE_TYPES` 删掉**（实测 0 节点、0 次使用，且 `object`
#: 的角色已被新增的 `prop` 取代），所以这里不再需要任何占位。留成空元组而不是删掉
#: 常量，是为了让"占位机制"本身还在——将来若再出现没有查询键的 kind，用同一处表达。
UNQUERYABLE_KINDS: Tuple[str, ...] = ()

#: 每个 kind 的上限：词表越大，"每个取值都要出现在至少 3 条不同的 (卡片,查询) 里"
#: 越难做到（`tools/check_holdout.py --min-seed-support 3`）。
HOLDOUT_CAP = 12


def holdout_vocab(nodes: Sequence[Dict]) -> Dict[str, List[str]]:
    """从节点表里裁出 held-out 的词表。

    只含 14 个查询 kind；**优先收语料里真实出现过的取值**（`occurrences ≥ 1`），
    某类不足 3 个时才回落到该类别的规范表——否则词表里会混进语料从不支持的取值，
    标注员为了覆盖它只能编数据。
    """
    grouped: Dict[str, List[Tuple[int, str]]] = {}
    for node in nodes:
        kind = node["type"]
        if kind not in HOLDOUT_KINDS:
            continue
        value = str(node.get("value") or node["node_id"])
        occurrences = int(node.get("occurrences", 0))
        grouped.setdefault(kind, []).append((occurrences, value))
    out: Dict[str, List[str]] = {}
    for kind in HOLDOUT_KINDS:
        items = sorted(set(grouped.get(kind, [])), key=lambda item: (-item[0], item[1]))
        observed = [value for count, value in items if count > 0]
        chosen = observed if len(observed) >= 3 else [value for _count, value in items]
        values = chosen[:HOLDOUT_CAP]
        out[kind] = sorted(values) if values else []
    for kind in UNQUERYABLE_KINDS:
        out[kind] = []
    return out


def vocab_fingerprint(payload: Dict[str, List[str]]) -> str:
    import hashlib
    import json as _json

    blob = _json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


#: 词表指纹里**额外**并入的索引侧表（`hypergraph.VALUE_ALIASES` 是索引侧唯一那份
#: 别名表：`static` → `固定`、`甩镜` → `whip_pan`）。
LEXICON_EXTRA_TABLES: Tuple[str, ...] = ("hg_value_aliases",)
#: 名字以这个前缀开头的模块常量不参与指纹（本机制自身的常量，自指没有意义）。
LEXICON_NAME_PREFIX = "LEXICON_"

#: "全大写名字"＝词表常量。**不手抄清单**：本仓库栽过的跟头正是"各抄一份
#: 6 类型 / 16 kind"导致的漂移（v1.5 扩类），所以这里机械发现，再用用例把
#: "哪些名字必须被发现 / 哪些名字必须不被发现"两边都钉死。
_LEXICON_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_LEXICON_TABLE_TYPES = (str, int, float, tuple, list, dict, set, frozenset)


def _canonical_table(value):
    """把表规范化成**可比对**的形状：字典按键排序，集合按元素排序，序列保序。

    序列**保序**是刻意的：顺序在这几张表里可能承载语义（例如 `EMOTIONS` 的
    分组顺序、`MOVEMENT_ZH` 的书写顺序），排序会掩盖一次真实改动。宁可多算
    一次"该重抽了"，也不接受"改了表却复用旧索引"。
    """
    if isinstance(value, dict):
        return {str(key): _canonical_table(item)
                for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        return [_canonical_table(item)
                for item in sorted(value, key=lambda item: json.dumps(
                    item, ensure_ascii=False, sort_keys=True, default=str))]
    if isinstance(value, (tuple, list)):
        return [_canonical_table(item) for item in value]
    return value if isinstance(value, (int, float)) else str(value)


def lexicon_tables() -> Dict[str, object]:
    """**词表/别名表本身**（与卡片无关）：本模块的全大写常量 ＋ 索引侧别名表。

    覆盖范围**故意取宽**："全大写名字"顺带会收进 `VFX_TYPES`（`contracts/enums`
    的闭集，确实是 `build_nodes` 的输入——收进来是对的）与 `HOLDOUT_CAP` /
    `HOLDOUT_KINDS` 这类**标注侧**常量（它们其实不进索引）。理由是两种错法的
    代价完全不对称：

    * **欠包含**（改了一张真影响索引的表，指纹却没动）→ 静默复用旧索引，
      manifest 上看不出来，只有检索结果漂移时才可能被发现；
    * **过度包含**（改了不影响索引的表，指纹动了）→ 跑一次**离线** `--rematch`
      （数秒、零 API 调用）就重新签好，边逐字节不变。

    宁可多一次离线改正，不要一次静默的陈旧索引。将来若真需要精确到"只含进索引
    的表"，那要先把"哪些表进索引"变成可判定的量，而不是靠名字碰运气。
    """
    tables: Dict[str, object] = {}
    for name, value in globals().items():
        if name.startswith("_") or name.startswith(LEXICON_NAME_PREFIX):
            continue
        if not _LEXICON_NAME_RE.match(name):
            continue
        if isinstance(value, _LEXICON_TABLE_TYPES):
            tables[name] = value
    tables["hg_value_aliases"] = dict(hg.VALUE_ALIASES)
    return tables


def lexicon_fingerprint() -> str:
    """**词表指纹**：`CACHE_KEY_FIELDS` 里第 8 个分量的唯一生产者（全 64 位）。

    为什么 `vocab_fingerprint()` 顶不了这一格：那份哈希的是"**从卡片派生出的**
    取值表"（`{}`→取值），而这里要覆盖的是**别名表本身**——`EMOTIONS`／
    `MOVEMENT_ZH`／`COMPOSITION_RULES_ZH`／`VALUE_ALIASES` 这类表是**落地判据的
    输入**，改它就会改索引，而且改的人不会想起去换版本号：

    实测（`ACCEPTANCE_STATUS.md` §20.4）：给 `EMOTIONS` 补一个别名 `安静`，
    `cine_move_handheld` 那条**正确**的禁令边的宿主就从"编的"变成"卡里写的"，
    归并期的精确度门因此 2 → 1 条拒收（索引 540 → 539 条边）——而
    `CACHE_KEY_FIELDS` 里**没有任何一格**会动。于是同一枚指纹指向了两份不同的
    索引，"同一指纹 ⇒ 同一索引"这条回归基线在别名表这一维上不成立
    （`ACCEPTANCE_STATUS.md` §20.8 第 4 条）。

    边界（刻意画清）：门阈值、否定词表这类**校验代码的常量**仍由
    `VALIDATION_RULES_VERSION` 管（"改门就换版本"是既有纪律）；本分量只负责
    **词表/别名表**——因为它是数据、不是门，改它时没有任何闸门会提醒你。
    """
    import hashlib

    payload = {"tables": _canonical_table(lexicon_tables())}
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run(cards) -> Tuple[List[Dict], Dict[str, List[str]]]:
    nodes = build_nodes(cards)
    vocab = vocab_payload(nodes)
    held_out = holdout_vocab(nodes)
    common.dump_json(common.KNOWLEDGE / "hypergraph.vocab.json",
                     {"nodes": nodes, "vocab": vocab, "holdout_vocab": held_out,
                      "_fingerprint": vocab_fingerprint(held_out)})
    # `tools/check_holdout.py` 非 pilot 模式要求词表带 `_fingerprint`
    # （把"这份词表"与"当次标注/索引"绑死，协议 §6）。
    common.dump_json(common.ROOT / "fixtures" / "knowledge_holdout.vocab.json",
                     {"_fingerprint": vocab_fingerprint(held_out), "kinds": held_out})
    common.write_jsonl(common.KNOWLEDGE / "hypergraph.nodes.jsonl",
                       [{"record": "node", **node} for node in nodes])
    return nodes, vocab


def main(argv=None) -> int:  # pragma: no cover - 薄 CLI
    import argparse

    from block_director.knowledge.corpus import CARDS

    parser = argparse.ArgumentParser(prog="kb_fetch.vocabulary")
    parser.parse_args(list(argv) if argv is not None else None)
    nodes, vocab = run(CARDS)
    print(json.dumps({"nodes": len(nodes), "kinds": {k: len(v) for k, v in vocab.items()}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
