"""P14-2：把卡片抽取成超边并建索引（执行文档 v1.4 §2.3 的"索引构建"）。

两段式（§2.3）在这里落地为：**逐卡抽原子事实**（batch = 若干张卡）→ **同域归并**。
归并窗口写死为"同一 `domain`（含卡片自身的 `related` 邻域）且每批不超过 8 张卡"，
这与 §2.3 的"同域 ＋ 一跳 related 闭包；每次归并最多 8 张卡"一致。

校验：`block_director/knowledge/hypergraph.build_index` 的 9 条门。不合格的边进
`knowledge/hypergraph.rejects.jsonl`；构建门是 `rejects ≤ 5%` 且没有 chunk 被跳过。

断点续跑：六元指纹（语料 sha256 ＋ 抽取器 model id＋版本 ＋ prompt 版本 ＋ chunk 策略 ＋
解码参数 ＋ schema 版本）加**校验门代码版本**，写进 `knowledge/hypergraph.manifest.json`。

**指纹必须是"记录下来的分量的纯函数"**（§2.3 的缓存键 / §6 的"重抽取成本"）：
`fingerprint_of(manifest["cache_key"]) == manifest["fingerprint"]`，且任一个分量变了
指纹就必须变——否则"改了 prompt / 换了 chunk 策略"会复用旧索引，而 manifest 上看不出来。
本模块只认 `CACHE_KEY_FIELDS` 这一组键（多一个少一个都直接报错），免得以后加了新分量
却忘了进哈希。

第七个分量是 §2.3 表格里那句"**六元指纹 ＋ 校验门代码版本**"的后半句，也是 §6「重抽取
成本」那条缓解措施（"另建议把校验门代码版本也纳入——门改了只需重跑门，不必重抽"）。
`--rematch` 就是"只重跑第 2 段"，所以第 2 段的判据一变，指纹**必须**跟着变：否则同一枚
指纹会同时指向"过滤之前"和"过滤之后"两份不同的索引，而 manifest 上看不出来。
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import hashlib
import json
import pathlib
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from . import common, llm
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common, llm  # type: ignore

from block_director.knowledge import grounding
from block_director.knowledge import hypergraph as hg

EDGES = common.KNOWLEDGE / "hypergraph.edges.jsonl"
NODES = common.KNOWLEDGE / "hypergraph.nodes.jsonl"
REJECTS = common.KNOWLEDGE / "hypergraph.rejects.jsonl"
#: **第 1 段**的原子级拒收（缺必填槽位等）。它与"过门被拒的边"不是一件事，
#: 因此**不写进** `hypergraph.rejects.jsonl`：那个文件的每一行都必须能被
#: `manifest.rejects` 计数对上（P14-5 的 Q0 交叉校验）。
ATOM_REJECTS = common.WORK / "hypergraph.atom_rejects.jsonl"
MANIFEST = common.KNOWLEDGE / "hypergraph.manifest.json"
REPORT = common.WORK / "hypergraph_report.json"
VOCAB = common.KNOWLEDGE / "hypergraph.vocab.json"
#: 第 1 段的**原子边**落盘（可只看归并口径重跑第 2 段，不必重抽）。
ATOMS = common.WORK / "hypergraph.atoms.jsonl"

#: 版本进六元指纹：改了提示就整体重抽，不拿旧原子边冒充新口径。
#: v5：把"每张卡至少一条边"改成**按耦合写**（实测 1241/1359 张卡只抽出一条，
#: 卡里其余的耦合整块丢失）。
#: v6：**逐类自问**。v5 之后类型选择仍然严重偏移——实测 oracle 要求的 5043 条
#: 边里，`TROPE` 244 条中 **224 条**是"那张卡有边、但不是这个类型"，
#: `EMOTION_PACK` 677/771、`IMPACT_PACK` 240/256 同样如此：两个读者（标注方与
#: 抽取器）对同一张卡选了不同类型，这是当前最大的召回损失。v6 要求对每张卡
#: **把 13 类逐条过一遍**，命中一类写一条。
#: v7：规则 8b —— `action` 只能是"看得见的身体行为"。实测 v6 的产物里 915 条
#: 归并边有 **170 条（18.6%）**把 `人物弧光`／`分镜写法`／`制作流程` 这类**话题名词**
#: 塞进了 `action`（`ACTION_BEAT` 85 条里一半是这种），覆盖 329 张卡 —— 成因是必填
#: 槽位逼出来的：讲"人物塑造"的卡没有动作可写，模型就抓卡片主题顶上。
#: 改提示文本 ⇒ 必须换版本号，否则 `--only-missing`／`--replace-cards` 的续跑判定
#: 会把 v6 的原子边当成同一批（那正是 §2.3 禁止的事）。
#: v8：schema 扩到 16 类（＋`DIALOGUE_PACK`／`MUSIC_PACK`／`PROP_PACK`），并把
#: `forbid` 的宿主从"只有 EMOTION_PACK"放宽到"这条边里本来就有这个槽位"
#: （用户裁决）。两处都是提示正文的改动 ⇒ 必须换版本号，否则整库续跑判定会把
#: v7 的原子边当成同一批。换版本号同时意味着**全库重抽**（旧边里没有这三类）。
#: **被证伪的一次尝试（留档，别再犯）**：v9 曾加过一条"出现 vfx/sfx/music 取值就必须
#: 自问一遍三类薄边"的规则，依据是"提到这些取值的 91 张卡里只有 1 张产出了
#: IMPACT_PACK"。但把 95 张卡按 v9 重抽之后，`IMPACT_PACK` 的原子边只从 **1 → 3**、
#: 归并边数**没变**（22）。也就是说那个"91 张"的口径太松：**提到 `smoke` 的照明卡
#: 不等于一次冲击耦合**，抽取器原本不写是对的。这条规则已回退，索引也随之回到单一版本。
#: v10：`forbid` 纪律（规则 8d）——**只有卡里真写了"不要/避免/切忌…"并且那个取值
#: 就写在同一张卡里时，才允许写 `forbid_<kind>=取值`**。实测旧产物 101 个 `forbid`
#: 成员里只有 9 个有卡里理据，双模型复核因此判掉 93/116 条 Q7 条目。
#: v11：修掉规则 10 里那句**与规则 4 自相矛盾**的旧约束（"只有 EMOTION_PACK 允许
#: forbid"）。实测代价是禁忌全挤在情绪包上、其余 12 类为 0（`AUDIT_TRIAGE.md` #17），
#: 而这个语料里"不要正面光""避免三分法""别用手持"这类跨类禁忌本来很多——
#: 结果是 Q7 的 ≥60 条冲突查询只能靠**编出来的**禁忌去填（复核两模型一致判掉 45 条）。
#: v12：把 `source_kind` 的判据从"来源"改成"**知识形态**"（§2.3b 的用户裁决），
#: 并且不再给每张卡塞一句假的"来源性质：theory"——正是那句让 738 条边的
#: `source_kind=experience` 恒为 0，L2 经验层形同不存在、`E3 经验越权率` 因分母为 0 判失败。
PROMPT_VERSION = "extract/v12"
#: §2.3 的缓存键写的是"六元指纹 ＋ **校验门代码版本**"，§6「重抽取成本」也点名建议把
#: 它纳入——因为 `--rematch` 这条路径**只重跑第 2 段、不重抽**（第 2 段是纯函数）。
#: 门一变、索引就变，指纹不跟着变的话，同一枚指纹会指向两份不同的索引。
#: 与 `PROMPT_VERSION` 的分工：那个管**第 1 段**（提示文本），这个管**第 2 段**（归并
#: 与精确度门）。v1：新增 `unsupported_prohibition_hosts`（禁令必须有宿主）。
VALIDATION_RULES_VERSION = "gate/v1"
BATCH_CARDS = 8
#: 归并窗口的卡片数上限（§2.3 第 2 步写死为 8）。
MERGE_WINDOW = 8
#: 单张卡在一个批次里最多贡献几条**原子边**。旧值 2 把"一张卡讲了三条耦合"
#: 直接记成 `too_many_edges_for_card` 丢掉——那是第 2 段归并没实现时的代偿，
#: 不是 §2.3 的要求。放宽到 4，超出的仍逐条留痕（不静默）。
#: 单张卡最多产几条原子边。v6 起由 4 提到 8：实测"逐类自问"把稀有类型
#: （EMOTION_PACK 46→95、STAGING_PACK 79→168）抬起来的同时**挤掉了充裕类型**
#: （SHOT_PATTERN 266→190）——上限 4 是那个取舍的**真实约束**，不是提示词问题。
#: 实测（同一语料、同一模型，逐轮只改一处）：
#:   v5 / cap 4  → 678 条
#:   v6 / cap 8  → **791 条**（且几乎无类型下降：EMOTION 101→129、TROPE 16→27…）
#:   v6 / cap 12 ＋ EDIT_RHYTHM 取值映射 → 739 条（**更差**：EDIT_RHYTHM 只有
#:      十几种唯一组合，写多了全被归并吃掉，还挤掉别的类型）
#: 所以取测量最好的一档 8，并把 12 那一轮记在这里——调参要有回头看的依据。
MAX_EDGES_PER_CARD = 8
#: 解码参数属于六元指纹的一部分：它写死在调用里（`extract()` 的 temperature=0/seed=0/ctx=8192）。
DECODE = "temperature=0;seed=0;ctx=8192"

#: 指纹的分量名（顺序即 `cache_key` 的键序）。前六个是 §2.3 的"六元"，
#: 第七个是同一行里写的"＋ 校验门代码版本"。
CACHE_KEY_FIELDS = ("corpus_sha256", "model", "prompt_version",
                    "chunker_version", "decode", "schema_version",
                    "validation_rules_version")


def corpus_digest(cards: Sequence[Dict]) -> str:
    """语料指纹：卡片 id ＋ chunk ＋ 源文档 sha256 ＋ 正文 sha256，按字典序拼后取 sha256。

    只拿 id 列表去哈希是不够的：**同样的 id、改过的正文**必须让指纹变（否则缓存会
    拿旧索引当新语料的产物）。源文档 sha256 与正文 sha256 同时计入，正是为此。
    """
    rows = []
    for card in cards:
        span = card.get("source_span") or {}
        rows.append([
            str(card.get("id", "")),
            str(card.get("chunk_id") or span.get("chunk_id") or ""),
            str((card.get("source_ref") or {}).get("sha256", "")),
            common.sha256_text(str(card.get("content", ""))),
        ])
    rows.sort()
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_components(cards: Sequence[Dict], client, *,
                           prompt_version: str = PROMPT_VERSION,
                           validation_rules_version: str = VALIDATION_RULES_VERSION,
                           decode: str = DECODE,
                           chunker_version: str = "",
                           schema_version: str = "") -> Dict[str, str]:
    """把指纹的分量算出来（`cache_key` 的**唯一**生产者）。"""
    return {
        "corpus_sha256": corpus_digest(cards),
        "model": f"{client.model_id}@{getattr(client, 'model_version', '')}",
        "prompt_version": str(prompt_version),
        "chunker_version": str(chunker_version or common.CHUNKER_VERSION),
        "decode": str(decode),
        "schema_version": str(schema_version or hg.SCHEMA_VERSION),
        "validation_rules_version": str(validation_rules_version),
    }


def fingerprint_of(components: Dict) -> str:
    """六元指纹：对**恰好这六个**分量做规范化 JSON 哈希。

    键集不对就报错（不是忽略多余键）：这是"加了新分量却没进哈希"的机械防线。
    """
    keys = set(components)
    expected = set(CACHE_KEY_FIELDS)
    if keys != expected:
        raise ValueError(f"六元指纹的分量不匹配：多 {sorted(keys - expected)} / "
                         f"少 {sorted(expected - keys)}")
    payload = json.dumps({key: str(components[key]) for key in CACHE_KEY_FIELDS},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def rekey_manifest(path: pathlib.Path | None = None,
                   cards: Sequence[Dict] | None = None) -> Dict:
    """只重算 `cache_key`/`fingerprint`，**不重抽**。

    指纹是"记录下来的分量"的纯函数，所以口径升级（例如以前只哈希 id＋model）
    之后可以就地重算：`corpus_sha256` 用当前卡片重算，其余的量从 manifest 自己读。
    旧的六元 manifest 没有 `validation_rules_version`，那时**读默认值**——这正是
    "补上第七个分量"这条升级要求的动作，不是把缺失当成空串。
    """
    target = pathlib.Path(path or MANIFEST)
    manifest = json.loads(target.read_text(encoding="utf-8"))
    extractor = manifest.get("extractor") or {}
    components = {
        "corpus_sha256": corpus_digest(list(cards if cards is not None else load_cards())),
        "model": f"{extractor.get('model_id', '')}@{extractor.get('model_version', '')}",
        "prompt_version": str(manifest.get("prompt_version", PROMPT_VERSION)),
        "chunker_version": str(manifest.get("chunker_version", common.CHUNKER_VERSION)),
        "decode": str(manifest.get("decode", DECODE)),
        "schema_version": str(manifest.get("schema_version", hg.SCHEMA_VERSION)),
        "validation_rules_version": str(manifest.get("validation_rules_version",
                                                     VALIDATION_RULES_VERSION)),
    }
    rekeyed = {"fingerprint": fingerprint_of(components), "cache_key": components}
    rekeyed.update({key: value for key, value in manifest.items()
                    if key not in ("fingerprint", "cache_key")})
    common.dump_json(target, rekeyed)
    return {"manifest": str(target), "fingerprint": rekeyed["fingerprint"],
            "cache_key": components}

def _forbid_slots_text() -> str:
    """规则 10 的那张表：**每个边类型允许带哪些 `forbid` 槽位**。

    唯一真源是 `hg.OPTIONAL_MEMBERS`——与 `check_holdout.illegal_members()` 判非法角色
    用的是同一张表。旧版提示在规则 10 里写死了一句"只有 EMOTION_PACK 允许 forbid"，
    与规则 4 自相矛盾，实测后果就是 915 条边里带 forbid 的 81 条**全是情绪包**、
    其余 12 类为 0（`AUDIT_TRIAGE.md` #17）。把表渲染出来，这条矛盾就不再有落点。
    """
    rows = []
    for etype in hg.EDGE_TYPES:
        kinds = sorted({kind for role, kind in (hg.OPTIONAL_MEMBERS.get(etype) or ())
                        if role == "forbid"})
        if kinds:
            rows.append("      %-16s %s" % (etype + ":", " / ".join("forbid_" + k for k in kinds)))
        else:
            rows.append("      %-16s （这一类型不许带 forbid）" % (etype + ":"))
    return "\n".join(rows)


SYSTEM_PROMPT = """你是超图索引的抽取器。给定若干条知识卡与一份**冻结的取值词表**，把卡片里\
的多元耦合（情绪×运镜×景别×剪辑×特效×禁忌）收敛成下面六类超边之一。

只输出 JSON：{"edges":[{"type":..., "members":[["role","kind","node_id"], ...],
 "source_kind":"theory|experience|lesson", "hardness":"hard|soft",
 "confidence":0.0-1.0, "source_card":"<卡片 id>"}]}

硬规则（违反的边会被机器丢弃，因此宁少勿错）：
1. `type` 只能取下面 **13 类**之一，必填成员必须写全（v1.5 扩充：把电影制作里除灯光
   以外的强耦合元素都建模进来——动作/表演/意图/打击感/调度/声画/转场）：
   EMOTION_PACK: (allow,emotion) ＋ (qualifier,intensity)；
   SHOT_PATTERN: (allow,shot_size) ＋ (allow,lens) ＋ (qualifier,headroom_policy)；
   AXIS_RULE: (qualifier,pair) ＋ (qualifier,axis_side) ＋ **(qualifier,axis_topic)**
     —— `axis_topic` 必须写（`轴线:<中性机位|关系轴|视线轴|越轴|运动轴>`），
     否则这条边在检索里挂不上任何种子（实测：不写它时 AXIS_RULE 整类召不回）；
   TROPE: (allow,genre) ＋ (allow,emotion)；
   EDIT_RHYTHM: (allow,pacing) ＋ (qualifier,avg_shot_len)；
   LIGHT_PACK: (allow,lighting) ＋ (qualifier,intensity)；
   ACTION_BEAT: (allow,action) ＋ (qualifier,beat_type) ＋ (qualifier,intensity)
     —— 角色的**动作**与叙事**节拍**、强度绑死（"推门 = establish = high"）；
   PERFORMANCE_PACK: (allow,emotion) ＋ (allow,action) ＋ (qualifier,camera_angle)
     —— **角色行为**：情绪外化成动作，并规定机位怎么看它；
   INTENT_PACK: (allow,intent) ＋ (allow,shot_size) ＋ (qualifier,movement)
     —— **意图**决定镜头语言（`intent:<取值>` 见词表，中文闭集）；
   IMPACT_PACK: (allow,vfx) ＋ (allow,sfx) ＋ (qualifier,movement)
     —— **震动与打击感**：冲击帧/抖屏 × 音效 × 运镜；
   STAGING_PACK: (qualifier,composition_rule) ＋ (allow,shot_size) ＋ (qualifier,camera_angle)
     —— **构图与场面调度**：构图规则决定景别与机位；
   SOUND_PACK: (allow,sfx) ＋ (allow,pacing) ＋ (qualifier,intensity)
     —— **声画关系**：音效 × 剪辑节奏 × 强度；
   TRANSITION_PACK: (qualifier,transition) ＋ (allow,pacing) ＋ (qualifier,scene_type)
     —— **转场** × 节奏 × 场景类型。
   DIALOGUE_PACK: (allow,delivery) ＋ (qualifier,pacing) ＋ (qualifier,intensity)
     —— **台词怎么念**：语气/发声方式（耳语/喊叫/平淡/颤抖/画外音）× 语速 × 强度；
   MUSIC_PACK: (allow,music) ＋ (qualifier,pacing) ＋ (qualifier,intensity)
     —— **配乐与环境声**（静默/铺底/重音/环境底噪）× 剪辑节奏 × 强度；
   PROP_PACK: (allow,prop) ＋ (allow,shot_size) ＋ (qualifier,camera_angle)
     —— **道具与环境元素** × 呈现景别 × 机位。
   （v1.6 新增这三类，是用户裁决"尽可能囊括除灯光以外影响电影制作的其他元素"里
     还缺的三块；语料支撑实测：台词交付 38 张卡、配乐 26、道具 160。）
1b. **只有这 13 个 `type` 字符串**。不要发明 `COMPOSITION`／`SOUND`／`SHAKE` 之类
   的新类型——那些会被校验门以 `bad_type` 丢掉。
1c. **卡片属于哪个 `domain` 与 `type` 无关**：构图/机位/特效/音效/动作类的知识要挂到
   最接近的那一类边上，作为**额外成员**（必填成员照旧写全）。词表里有这些 kind：
   * 构图（均衡/三分/留白/引导空间/遮挡/头部空间）→ `SHOT_PATTERN` ＋
     `(allow|qualifier, composition_rule, composition_rule:<取值>)`；
   * 机位（高低/荷兰角/过肩/骑轴）→ 就近那类 ＋ `(qualifier, camera_angle, …)`；
   * 特效/音效 → 就近那类 ＋ `(qualifier, vfx|sfx, …)`；
   * 动作 → 就近那类 ＋ `(allow, action, …)`；
   * 适用题材/景别 → `(qualifier, applies_to_genre|applies_to_shot_size, …)`。
   **每一张卡都必须至少产出一条边**（见第 6 条）；抽不出情绪/运镜耦合的构图卡，
   就写成带 `composition_rule` 的 `SHOT_PATTERN`。
2. `node_id` **必须**取自下面词表（`kind:取值` 已经写好）；词表里没有的取值就不要抽。
3. 同一个 `node_id` 不能既出现在 `allow` 又出现在 `forbid`。
4. 禁忌写成 `["forbid", kind, node_id]`——它是这条边最有价值的部分，别省略。
   **v1.6 起 `forbid` 的宿主放宽到"这条边里本来就有这个槽位"**（用户裁决）：一个
   kind 只要在本类型里以 `allow`／`qualifier` 出现过，就可以再以 `forbid` 出现
   （取值必须与它自己的 allow／qualifier 取值**不同**——"要求 crane_up、禁止
   dolly_out" 是合法的；"要求 X 又禁止 X" 会被门② 拒收）。旧规则只许挂在
   EMOTION_PACK 上，实测后果是 915 条边里 81 条带 forbid **全是情绪包**，其余 12 类
   为 0 —— "这个动作不该配这个运镜"这类跨类负向知识**结构上表达不了**。
   仍然不许碰 schema 常量（`pair`／`axis_side`／`headroom_policy`／`avg_shot_len`／
   `applies_to_*`）：禁止一个常量没有意义。
4b. **卡片里凡是出现"忌讳/避免/不要/禁用/宁可…也不"这类表述的，必须把那个取值写成
   `forbid` 成员**（挂在 EMOTION_PACK 上；如果这张卡本身不是情绪卡，就把它写成
   "该情绪下不要这样拍"的 EMOTION_PACK）。词表里已经给了 `movement`／`shot_size`／
   `lens`／`composition_rule` 等 kind 的取值，不要漏掉这条"最有价值"的边。
   实测教训：不写这一条时整库只剩 1 个 forbid 成员，Q7 就没有可拦截对象。
5. **`source_kind` 按"知识的形态"判，不按来源判**（§2.3b 的用户裁决：切分标准是形态）：
   * `theory`＋`hard`：普遍适用的规则/结论/定义（"180 度轴线两侧不能跳""三分法把
     主体放在交点"）；
   * `experience`＋`soft`：**明确带条件的实践取舍**——某个具体条件（镜头/光位/景别/
     情绪/场景/成本）下优先什么、避开什么、换来什么结果，常带实践口吻（"实测""一般来说"
     "在…时""会显得""别用"）。例："24mm 拍饭桌会显得脏"、"喜剧别用长镜静止"、
     "若对方动作夸张会分散注意力，需主动屏蔽"；
   * `lesson`：卡片**明确写成"教训/禁忌"**时（只有这一档、以及 `theory`，允许带 `forbid`）。
   **每张卡都要先判形态再落边**：同一批卡里既有理论也有取舍，不要一律写 `theory`
   （实测：一律 `theory` 时 L2 经验层是 **0/738** 条边，`E3 经验越权率` 因为分母为 0
   直接判失败——§4.1b 硬规则 1）。
6b. **逐类自问（v6 的核心修正，务必执行）**：实测 oracle 要求的 5043 条边里，
   `TROPE` 的 244 条中有 **224 条**是"那张卡有边、但抽取器选了**别的类型**"，
   `EMOTION_PACK` 677/771、`INTENT_PACK` 605/679、`IMPACT_PACK` 240/256 同样如此
   ——两个读者对**同一张卡**选了不同类型，是当前最大的召回损失。所以对每一张卡
   **把下面 13 类逐条问一遍**，命中就写一条（每卡上限 4 条）：
   * 有「情绪＋强度」→ `EMOTION_PACK`
   * 有「题材＋情绪」→ `TROPE`（**别只写 EMOTION_PACK 就完事**）
   * 有「景别＋镜头＋留白」→ `SHOT_PATTERN`
   * 有「节奏＋平均镜长」→ `EDIT_RHYTHM`
   * 有「光线＋强度」→ `LIGHT_PACK`
   * 有「动作＋节拍＋强度」→ `ACTION_BEAT`
   * 有「情绪＋动作＋机位」→ `PERFORMANCE_PACK`
   * 有「意图＋景别＋运镜」→ `INTENT_PACK`
   * 有「特效＋音效＋运镜」→ `IMPACT_PACK`
   * 有「构图＋景别＋机位」→ `STAGING_PACK`
   * 有「音效＋节奏＋强度」→ `SOUND_PACK`
   * 有「转场＋节奏＋场景类型」→ `TRANSITION_PACK`
   * 有「配对方式＋轴线侧」→ `AXIS_RULE`（**必须再带上 `axis_topic`**）
   **只挑"最像的那一条"是错的**：漏掉的那几类知识在索引里就不存在，检索再准也召不回。
   上限 8 条（够把一张卡的多重耦合都写下来），所以**不必取舍**：能写就都写。
   `TROPE` 的 `genre` **不必等卡里明写**：卡片内容讲的是动画/日式作画惯例 → `genre=anime`；
   现场实拍/剧情片 → `genre=film`；纪录片 → `documentary`。实测 TROPE 只有 4 条边、
   而 oracle 需求 244 条，绝大多数是因为模型从不主动写 `genre`。

6. **每一张卡都要写出它表达的全部耦合**（除非它只是孤立术语的定义）。一张卡最多 4 条。
   实测教训（2026-10-01）：只要求"至少一条"时，模型给 1359 张卡一共写了 1241 张
   **只有一条边**的卡——一张讲"冲击帧只占 1–2 帧，配低频音效与手持机位"的卡，
   最后只落成一条 `EDIT_RHYTHM`，卡里真正的**打击感**与**声画**耦合整块丢失，
   检索再怎么排都召不回它。所以这里的口径是**按耦合写、不是按卡写**：
   * 卡里同时讲了 A×B 与 C×D，就写**两条**边；
   * 讲了两件事却只写一条，等于把那件事从索引里删掉；
   * 拿不准时先自问："这张卡还讲了什么**别的**类型的耦合？"
   **自检：如果一条卡抽出 1 条边，回头再看一遍它的正文**，多半漏了一条。
   例（照这个粒度写）：卡写着"冲击帧只占 1–2 帧，配合低频音效与手持机位，剪辑上
   前后要留 6–10 格静止" → 至少两条：
   `IMPACT_PACK:vfx=<冲击帧>,sfx=<低频>,movement=<手持>` ＋
   `EDIT_RHYTHM:pacing=short,avg_shot_len=<1s>`。
   宁可少写成员，也不要空手而归——索引里没有边，这条知识就等于不存在。
7. `value` 必须落在冻结取值域内（例如 intensity 只能是 low/mid/high）。
   受限取值只有这几组，抄错即被拒收：intensity∈{low,mid,high}；
   avg_shot_len∈{<1s,1-3s,3-8s,>8s}；pacing∈{short,medium,long}；
   axis_side∈{left,right,neutral}；pair=any_two；headroom_policy∈{board,cinematic}；
   transition∈{cut,dissolve,fade,whip}；
   scene_type∈{establish,dialogue,action,reaction,transition,insert}；
   genre 与 applies_to_genre∈{film,anime,documentary}；
   shot_size 与 applies_to_shot_size∈{ECU,CU,MCU,MS,MLS,LS,ELS}。
8. 若一组卡片表达的是同一条耦合（同 type ＋ 同成员），只写一条，让 `occurrences` 去计权。

8b. **`action` 只能是"看得见的身体行为"，不能是概念/技法/流程/职务**（v7 的核心修正）。
8d. **`forbid` 只在卡里真写了"不要"时才写**（v10 的核心修正）。
   实测（2026-10-01）：索引里 **101 个 `forbid` 成员中只有 9 个**能在来源卡的正文里
   找到理据（取值／名字／别名出现，且同一张卡有"不要/避免/切忌…"类否定词）。
   也就是说 **91% 的禁忌是抽取器自己加的**。代价是把两个**双模型复核**判掉
   93/116 条 Q7 条目（复核员的原话："卡未涉及该槽位"、"与卡无关的强耦合"），
   而 oracle 的另外几道门又踩在这批条目上 —— 一剔就红。
   所以：**只有卡里真的出现否定表述**（`不要`／`避免`／`切忌`／`禁忌`／`禁用`／
   `不宜`／`不能`／`禁止`／`avoid`／`never`／`don't`…）**并且** `forbid_<kind>=取值`
   的那个取值就写在同一张卡里时，才写这条禁忌。**凭"这个搭配看起来不对"自己加禁忌
   一律不许**——那是幻觉，不是知识。
   （与 v7 的规则 8b 同一形态：`action` 也只能写卡里看得见的行为。）
   实测（2026-10-01）：915 条归并边里有 **170 条（18.6%）**的 `action` 成员是
   `人物弧光`／`人物塑造`／`分镜写法`／`制作流程`／`分工`／`动线`／`化妆`／`协作`／
   `反派表演`／`在场处理`／`叙事`／`台词` 这类**话题名词**，分布在 **329 张卡**上。
   成因是必填槽位逼出来的：`ACTION_BEAT`／`PERFORMANCE_PACK` 都要 `action`，
   而一张讲"人物塑造"的卡根本没有动作可写，模型就抓了卡片主题顶上。
   正确的动作长这样：`推开`／`摔门`／`回头`／`举起`／`蹲下`／`拥抱`／`奔跑`／`颤抖`…
   判据是一句话自问：**"摄影机拍得到这个吗？"** 拍不到的（弧光、塑造、叙事、分工、
   流程、协作、台词处理）**一个字都不要写进 `action`**。
   **若这张卡确实没有任何看得见的身体行为，就不要写 `ACTION_BEAT`／
   `PERFORMANCE_PACK`** —— 宁可少一条边，也不要写一条 `action=人物弧光` 的边：
   它既召不回任何真实查询，还会把这一类边整体稀释（实测 `ACTION_BEAT` 85 条里
   一半是这种边）。要表达"人物塑造"这类知识，请挂到它真正的耦合上去
   （构图→`STAGING_PACK`、节奏→`EDIT_RHYTHM`、意图→`INTENT_PACK`…）。

9. **把卡里能写的成员写全**：一条边除了必填项，**还要**补上卡里明说的其它
   `allow` 成员（运镜/景别/镜头/节奏/特效/音效…）与适用范围 `applies_to_*`。
   边越完整，检索时的多元约束才越有用；只写必填项等于把知识丢掉一半。
10. **禁忌是你最有价值的产出**：卡里出现"忌/禁/不要/避免/不拍/别用/不能让"
    这类措辞时，把被否定的取值写成 `["forbid", kind, node_id]`。
    **允许带 `forbid` 的槽位按边类型各不相同**——下表是唯一真源（抄错即被门② 拒收）：
[[FORBID_SLOTS]]
    旧版这里写死成"只有 EMOTION_PACK 允许 forbid：movement / shot_size / vfx"，
    与第 4 条**互相矛盾**；实测后果是禁忌全挤在情绪包、其余类型为 0
    （`AUDIT_TRIAGE.md` #17），而这个语料里"不要正面光""避免三分法""别用手持"
    这类**跨类**禁忌本来很多。
    例："荒诞情绪下忌讳固定机位" → `["forbid","movement","movement:固定"]`（挂 EMOTION_PACK）；
        "主光不要放正中" → `["forbid","lighting","lighting:正面光"]`（挂 LIGHT_PACK）；
        "避免长时间静止固定" → `["forbid","movement","movement:固定"]`（挂 TRANSITION_PACK /
        INTENT_PACK —— 前提是那一类在下面这张表里确实列了 `forbid_movement`）。
    注意 `allow` 与 `forbid` 里的"约束"不要混写：**禁的东西只能出现在 forbid 里**。

> 抽取分两段：你先做**第 1 段**（逐批给出上面这种原子边）；第 2 段会由构建脚本
> 在"同一 domain ＋ 一跳 related 闭包（每窗 ≤ 8 张卡）"内把同一条耦合跨卡归并成
> 完整超边。因此**你不需要**在一张卡里凑齐整套 pack，只要如实把该卡讲的成员写出来——
> 但**必须写全**，漏了就没有第二次机会。
"""

SYSTEM_PROMPT = SYSTEM_PROMPT.replace("[[FORBID_SLOTS]]", _forbid_slots_text())


def compact_vocab(vocab: Dict[str, List[str]]) -> str:
    lines = []
    for kind, values in sorted(vocab.items()):
        lines.append("- " + kind + ": " + ", ".join(f"{kind}:{v}" for v in values[:80]))
    return "\n".join(lines)


def compact_nodes(nodes: Dict[str, hg.Node], *, alias_cap: int = 12) -> str:
    """把**真实存在的 node_id** 按 kind 列出来（别名另列，明确不是 node_id）。

    旧写法把 `vocab_payload()` 的取值直接拼成 `kind:取值` 当 node_id 发出去，而那份
    取值表**混了别名**（`pacing` 里就有 `短镜硬切`，它只是 `pacing:short` 的别名）。
    模型很听话地照抄，结果索引里存进一批**没有节点记录**的悬空 id——门③ 只查
    `kind` 合法，查不出这种引用。这里改成"列真实 node_id ＋ 另列同义说法"。
    """
    buckets: Dict[str, List[hg.Node]] = {}
    for node in nodes.values():
        buckets.setdefault(node.type, []).append(node)
    lines = []
    for kind in sorted(buckets):
        items = sorted(buckets[kind], key=lambda n: n.node_id)
        ids = ", ".join(node.node_id for node in items[:80])
        aliases: List[str] = []
        for node in items:
            for alias in node.aliases or ():
                alias = str(alias)
                if alias and alias not in aliases:
                    aliases.append(alias)
        line = f"- {kind}: {ids}"
        if aliases:
            line += "（同义说法：" + "/".join(aliases[:alias_cap]) + "——**不要**写成 node_id）"
        lines.append(line)
    return "\n".join(lines)


def build_prompt(cards: Sequence[Dict], vocab: Dict[str, List[str]],
                 nodes: Optional[Dict[str, hg.Node]] = None) -> str:
    table = compact_nodes(nodes) if nodes else compact_vocab(vocab)
    parts = ["【冻结 node_id 词表（`members` 里的第三个元素必须原样取自此表）】",
             table, "", "【知识卡】"]
    for card in cards:
        parts.append(f"### {card['id']}（domain={card['domain']}）\n"
                     f"标题：{card['title']}\n内容：{card['content']}\n"
                     f"标签：{'、'.join(card.get('tags', []))}\n"
                     #: **不要再给一个假的"来源性质"**：卡上没有这个字段时写
                     #: `theory` 等于告诉模型"这是教科书"——实测 1981 张生成卡**全部**
                     #: 没有该字段，于是 738 条边里 `source_kind=experience` 为 **0**，
                     #: L2 经验层形同不存在。改成把"按形态判"的判据再钉一次。
                     f"来源性质：按**知识形态**判（见规则 5）：卡里给的是普遍规则就写 "
                     f"theory＋hard；给的是「某条件下优先/避免什么」的实践取舍就写 "
                     f"experience＋soft；明确写成教训/禁忌才写 lesson。"
                     f"（抽取器不知道这张卡的出处，只能按写法判。）")
    return "\n".join(parts)


class NodeIndex:
    """节点表 ＋ 别名索引：把模型写的成员解析到一个**真实存在**的节点上。

    解析顺序（全部确定性）：① 原样命中且类型相符；② 同 kind 下的同义说法/规范名；
    ③ 漏写 `kind:` 前缀时补前缀。都解析不到就返回 `None`（调用方丢弃该成员）。
    """

    def __init__(self, nodes: Dict[str, hg.Node]):
        self.nodes: Dict[str, hg.Node] = dict(nodes)
        aliases: Dict[str, Dict[str, str]] = {}
        for node_id in sorted(self.nodes):
            node = self.nodes[node_id]
            bucket = aliases.setdefault(node.type, {})
            for name in (node.name, node.value, *node.aliases):
                if name:
                    bucket.setdefault(str(name), node_id)
            bucket.setdefault(node_id, node_id)
        self.aliases = aliases

    def resolve(self, member: hg.Member) -> Optional[hg.Member]:
        node = self.nodes.get(member.node_id)
        if node is not None:
            return member if node.type == member.kind else None
        bucket = self.aliases.get(member.kind, {})
        for key in (member.node_id, member.node_id.split(":", 1)[-1]):
            target = bucket.get(key)
            if target:
                return hg.Member(role=member.role, kind=member.kind, node_id=target)
        return None


def to_edge(raw: Dict, cards: Dict[str, Dict],
            node_index: Optional[NodeIndex] = None) -> Tuple[Optional[hg.HyperEdge], str]:
    """把一条原始边变成 `HyperEdge`。

    `node_index` 给了就顺带做**引用完整性**检查（门③ 只查 `kind` 合法，不查 `node_id`
    是否真的存在）：模型把 `movement:static` 塞进 `lens` 槽、或把情感写成
    `emotion:专注` 这种词表外的值时，边**形式上**仍然合法，落库后却是一条
    指向空气的引用——检索期种子不到、渲染期只能回显裸 id。

    处置分两档，都不算降级（都不是"放宽验收"，是拒绝存悬空引用）：

    * **别名/前缀补正**：模型照抄词表里的**别名**（`pacing:短镜硬切`）或漏写
      `kind:` 前缀（`>8s`）时，按 `NodeIndex` 的确定性规则解析回真实 node_id；
    * **丢弃**：补不出来就丢掉该成员；若它是**必填**成员，整条边判不合格。
    """
    if not isinstance(raw, dict):
        return None, "edge_not_object"
    edge_type = str(raw.get("type", "")).strip()
    if edge_type not in hg.EDGE_TYPES:
        return None, f"bad_type:{edge_type}"
    card_id = str(raw.get("source_card", "")).strip()
    card = cards.get(card_id)
    if card is None:
        return None, f"unknown_source_card:{card_id}"
    members: List[hg.Member] = []
    normalized = 0
    dropped: List[hg.Member] = []
    for item in raw.get("members") or []:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            return None, f"bad_member:{item}"
        member = hg.Member(role=str(item[0]), kind=str(item[1]), node_id=str(item[2]))
        if node_index is not None:
            resolved = node_index.resolve(member)
            if resolved is None:
                dropped.append(member)
                continue
            if resolved.node_id != member.node_id:
                normalized += 1
            member = resolved
        members.append(member)
    # 门④ 的必填成员在第 1 段就查：缺必填的原子边在归并期只会变成"某个槽位没有取值"，
    # 那条信息远不如这里给出的具名原因有用（而且会让归并直接崩）。
    present = {(m.role, m.kind) for m in members}
    missing = [f"{role}/{kind}" for role, kind in hg.REQUIRED_MEMBERS[edge_type]
               if (role, kind) not in present]
    if missing:
        reason = f"missing_required:{edge_type}:{missing}"
        if dropped:
            reason += f":dropped={[str(m) for m in dropped][:3]}"
        return None, reason
    # 门⑤ 在第 1 段就查一次：同一条边里同一个节点不能既 allow 又 forbid
    if {m.node_id for m in members if m.role == "allow"} & \
            {m.node_id for m in members if m.role == "forbid"}:
        return None, f"allow_forbid_overlap:{edge_type}"
    span = dict(card.get("source_span") or {})
    if not span or int(span.get("start", -1)) < 0:
        return None, "unlocatable_source_span"
    source_kind = str(raw.get("source_kind") or "theory")
    if source_kind not in hg.SOURCE_KINDS:
        source_kind = "theory"
    hardness = str(raw.get("hardness") or ("hard" if source_kind == "theory" else "soft"))
    if hardness not in hg.HARDNESS:
        hardness = "hard" if source_kind == "theory" else "soft"
    if source_kind == "experience" and any(m.role == "forbid" for m in members):
        # §2.3b 的关键纪律 1：经验默认不得单独产生 forbid——除非显式标成 lesson。
        return None, "experience_cannot_forbid"
    return hg.HyperEdge(
        type=edge_type,
        members=tuple(members),
        source_kind=source_kind,
        hardness=hardness,
        confidence=float(raw.get("confidence", 0.7) or 0.7),
        confidence_max=float(raw.get("confidence", 0.7) or 0.7),
        occurrences=1,
        sources=(card_id,),
        source_span=span,
        extractor={"prompt_version": PROMPT_VERSION, "normalized_members": normalized,
                   "dropped_members": len(dropped)},
        provenance_kind=str(card.get("provenance_kind", "生成卡片")),
    ), ""


def _required_pairs(edge_type: str) -> set:
    return {(role, kind) for role, kind in hg.REQUIRED_MEMBERS[edge_type]}


def required_signature(edge: hg.HyperEdge) -> Tuple[Tuple[str, str], ...]:
    """一条边"属于哪条耦合"的判据 = 它**必填槽位**的 (kind, node_id) 集合。

    只有必填槽位相同才允许归并：否则"荒诞 pack"会和"压抑 pack"缝成一条，
    那正是 spec 最怕的"成员张冠李戴"。
    """
    pairs = _required_pairs(edge.type)
    return tuple(sorted((m.kind, m.node_id) for m in edge.members
                        if (m.role, m.kind) in pairs))


def merge_windows(cards: Sequence[Dict], *,
                  window_size: int = MERGE_WINDOW) -> List[Tuple[str, ...]]:
    """§2.3 第 2 步的归并窗口：**同一 domain**，每窗 ≤ `window_size` 张卡，
    且把窗口头卡的**一跳 `related` 闭包**优先拉进来。

    窗口内的卡片两两不重叠——一张卡只参与一次归并，结果才能逐字节可复现。
    """
    by_domain: Dict[str, List[Dict]] = {}
    for card in cards:
        by_domain.setdefault(str(card.get("domain", "")), []).append(card)
    windows: List[Tuple[str, ...]] = []
    for domain in sorted(by_domain):
        items = {str(card["id"]): card for card in by_domain[domain]}
        related = {cid: sorted(str(item) for item in (card.get("related") or []))
                   for cid, card in items.items()}
        pending = sorted(items)
        taken: set = set()
        for head in pending:
            if head in taken:
                continue
            window = [head]
            taken.add(head)
            for neighbour in related.get(head, []):
                if len(window) >= window_size:
                    break
                if neighbour in items and neighbour not in taken:
                    window.append(neighbour)
                    taken.add(neighbour)
            for cid in pending:
                if len(window) >= window_size:
                    break
                if cid in taken:
                    continue
                window.append(cid)
                taken.add(cid)
            windows.append(tuple(window))
    return windows


def _merged_span(group: Sequence[hg.HyperEdge]) -> Dict:
    """主 span 取确定性的首条（门⑥ 要可解析），另附**全部**贡献者的 span。"""
    span = dict(group[0].source_span or {})
    spans = []
    for edge in group:
        item = dict(edge.source_span or {})
        spans.append({
            "chunk_id": str(item.get("chunk_id", "")),
            "start": int(item.get("start", 0) or 0),
            "end": int(item.get("end", 0) or 0),
            "card": str(edge.sources[0]) if edge.sources else "",
        })
    spans.sort(key=lambda row: (row["chunk_id"], row["start"], row["end"], row["card"]))
    span["spans"] = spans
    return span


def _merge_group(group: Sequence[hg.HyperEdge], nodes: Dict[str, hg.Node]) -> Tuple[hg.HyperEdge, Dict]:
    """把同一条耦合的若干原子边并成一条完整超边（确定性、逐成员收缩）。"""
    ordered = sorted(group, key=lambda e: (str(e.sources[0]) if e.sources else "", e.edge_id))
    edge_type = ordered[0].type
    required_pairs = _required_pairs(edge_type)

    required: List[hg.Member] = []
    for role, kind in hg.REQUIRED_MEMBERS[edge_type]:
        values = sorted({m.node_id for edge in ordered for m in edge.members
                         if m.role == role and m.kind == kind})
        if not values:
            # 防御性：`to_edge` 已经挡过一道，这里再挡一次（调用方可能直接喂原子边）。
            raise hg.GateError(f"merge_missing_required:{edge_type}:{role}/{kind}")
        required.append(hg.Member(role=role, kind=kind, node_id=values[0]))

    forbid_ids = {m.node_id for edge in ordered for m in edge.forbids}
    forbid_wins = sum(1 for edge in ordered for m in edge.allows if m.node_id in forbid_ids)

    # 选填成员按 **(role, kind) 槽位** 收，而不是按 (role, kind, node_id) 收：
    # 同一个槽位上的多个取值是**备选**（不同卡教的是两种做法），不是"同时成立"。
    # 旧写法把 (role, kind, node_id) 当键、逐个塞进同一条边，于是产出
    #   `SHOT_PATTERN:…,composition_rule=lead_room,composition_rule=rule`
    #   `AXIS_RULE:…,axis_topic=越轴,axis_topic=运动轴`
    # 这类**同 kind 多值**的边（实测 31 条）。它在 oracle 的规格语法里根本写不出来
    # （`tools/check_holdout.parse_spec` 用 dict 收同 kind，第二个值覆盖第一个），
    # 于是门⑩ 对这 31 条边**结构性未解析**——不是标注质量，是索引自己造的语法死角。
    # 修法：主边取每个槽位的第一个取值，**其余备选各自复制一条边**（笛卡尔展开的
    # 最小形式），备选语义完整保留、且每条边的每个 kind 都是单值。
    optional: Dict[Tuple[str, str], List[hg.Member]] = {}
    for edge in ordered:
        for member in edge.members:
            if (member.role, member.kind) in required_pairs:
                continue
            if member.role == "allow" and member.node_id in forbid_ids:
                continue  # §2.3b 关键纪律 2：禁忌压过放行
            bucket = optional.setdefault((member.role, member.kind), [])
            if all(existing.node_id != member.node_id for existing in bucket):
                bucket.append(member)
    for bucket in optional.values():
        bucket.sort(key=lambda member: member.node_id)

    def build(members: Sequence[hg.Member]) -> hg.HyperEdge:
        return hg.HyperEdge(
            type=edge_type,
            members=tuple(members),
            source_kind=ordered[0].source_kind,
            hardness=ordered[0].hardness,
            confidence=max(edge.confidence for edge in ordered),
            confidence_max=max(edge.confidence_max for edge in ordered),
            occurrences=len(ordered),
            sources=tuple(sorted({str(edge.sources[0]) for edge in ordered if edge.sources})),
            source_span=_merged_span(ordered),
            extractor={"prompt_version": PROMPT_VERSION, "merged_from": len(ordered)},
            provenance_kind=ordered[0].provenance_kind,
        )

    def _fits(members: Sequence[hg.Member]) -> bool:
        candidate = build(members)
        if hg.render_tokens(hg.render_edge(candidate, nodes)) > hg.MAX_RENDER_TOKENS:
            return False
        try:
            hg.validate_edge(candidate, nodes)
        except hg.GateError:
            return False
        return True

    members = list(required)
    dropped_optional = 0
    over_budget_dropped = 0
    def _over_budget(trial: Sequence[hg.Member]) -> bool:
        return hg.render_tokens(hg.render_edge(build(trial), nodes)) > hg.MAX_RENDER_TOKENS

    # 主边：每个选填槽位取**第一个装得下**的取值（与旧行为一致）。
    accepted: List[Tuple[Tuple[str, str], hg.Member]] = []
    for key in sorted(optional):
        for member in optional[key]:
            if _fits(members + [member]):
                members.append(member)
                accepted.append((key, member))
                break

    # 备选：同一槽位的**其余取值**各自复制一条边，主边的其它槽位照抄。
    # 没有取到主边取值的槽位（整组都装不下）也在这里统一记账，保证
    # `dropped_optional` 只数一次、且不静默丢知识。
    variants: List[hg.HyperEdge] = []
    for key in sorted(optional):
        chosen = next((member for slot, member in accepted if slot == key), None)
        for alt in optional[key]:
            if chosen is not None and alt.node_id == chosen.node_id:
                continue
            trial = [alt if m is chosen else m for m in members]
            if chosen is None and alt not in trial:
                trial = members + [alt]
            if _fits(trial):
                variants.append(build(trial))
            else:
                dropped_optional += 1
                if _over_budget(trial):
                    over_budget_dropped += 1

    def _dict() -> Dict:
        return {"merged_from": len(ordered), "forbid_wins": forbid_wins,
                "dropped_optional": dropped_optional,
                "over_budget_dropped": over_budget_dropped}

    return [build(members)] + variants, _dict()


def merge_edges(edges: Sequence[hg.HyperEdge], cards_by_id: Dict[str, Dict],
                nodes: Dict[str, hg.Node], *,
                window_size: int = MERGE_WINDOW) -> Tuple[List[hg.HyperEdge], Dict]:
    """§2.3 第 2 段：**同域 ＋ 一跳 related 闭包**内把原子边跨卡归并成完整超边。

    分组键把 `(source_kind, hardness)` 一起带上——与去重键同一条纪律：理论边与
    经验边**不得**被并成一条，否则每条边"谁的 forbid"不可判定，E3 直接失效。
    输出按 `(type, 必填签名, source_kind, hardness, edge_id)` 排序，保证逐字节可复现。
    """
    windows = merge_windows(list(cards_by_id.values()), window_size=window_size)
    window_of: Dict[str, object] = {}
    for index, window in enumerate(windows):
        for card_id in window:
            window_of[card_id] = index

    groups: Dict[Tuple[str, ...], List[hg.HyperEdge]] = {}
    for edge in edges:
        card_id = str(edge.sources[0]) if edge.sources else ""
        slot = window_of.get(card_id, ("solo", card_id))
        key = (str(slot), edge.type, edge.source_kind, edge.hardness) + required_signature(edge)
        groups.setdefault(key, []).append(edge)

    merged: List[hg.HyperEdge] = []
    report = {"windows": len(windows), "groups": len(groups), "merged_edges": 0,
              "multi_card_edges": 0, "forbid_wins": 0, "dropped_optional": 0,
              "over_budget_dropped": 0, "forbid_members": 0, "max_arity": 0,
              "dropped_groups": []}
    for key in sorted(groups):
        try:
            produced, detail = _merge_group(groups[key], nodes)
        except hg.GateError as exc:
            # 畸形的一组：**整组丢弃并留痕**（不静默、也不伪造一条边出来）
            report["dropped_groups"].append({
                "reason": str(exc),
                "edge_ids": sorted(item.edge_id for item in groups[key]),
            })
            continue
        # 一个组可能产出**多条**边：同 kind 的多个取值是备选，各自复制一条
        # （见 `_merge_group` 的说明）。备选边与原边同源、同硬度、同必填签名，
        # 因此 `multi_card_edges` 只对主边计数，避免把备选当"跨卡归并"多算一次。
        merged.extend(produced)
        report["forbid_wins"] += detail["forbid_wins"]
        report["dropped_optional"] += detail["dropped_optional"]
        report["over_budget_dropped"] += detail["over_budget_dropped"]
        report["alternatives"] = report.get("alternatives", 0) + max(0, len(produced) - 1)
        if detail["merged_from"] > 1:
            report["multi_card_edges"] += 1
    merged.sort(key=lambda e: (e.type, required_signature(e), e.source_kind,
                               e.hardness, e.edge_id))
    report["merged_edges"] = len(merged)
    report["forbid_members"] = sum(len(edge.forbids) for edge in merged)
    report["max_arity"] = max((len(edge.members) for edge in merged), default=0)
    return merged, report


def dedupe_by_norm_key(edges: Sequence[hg.HyperEdge]) -> Tuple[List[hg.HyperEdge], Dict]:
    """**全局**按 `norm_key` 去重：同一个 `(type, 成员集, source_kind, hardness)` 只留一条。

    为什么必须在第 2 段之后再补一刀：第 2 段是**按窗口**分组的（同域 ＋ 一跳
    `related` 闭包），同一个耦合如果出现在两个窗口里，就会各留一条——实测
    852 条边里只有 708 个不同的 `norm_key`，**142 个键重复、多出 144 条边**
    （占 17%）。§2.3 的去重键写的是 `(type, members, scope)`，是**全局**的，
    所以这是实现漏了一刀，不是口径问题。

    重复的副作用不只是浪费：同一条知识在索引里有三个副本，查询命中时名次只能
    靠 occurrences/confidence 决定（索引派生 Q1 一度从 0.7555 掉到 0.5786）。
    代表元的取法：**成员最多的那条**（信息最全）→ occurrences 大 → edge_id 小，
    并把所有副本的 `sources` **并起来**（出处不能因为去重而丢），occurrences 相加。
    """
    groups: Dict[Tuple, List[hg.HyperEdge]] = {}
    for edge in edges:
        key = (str(edge.type), edge.norm_key[1], str(edge.source_kind), str(edge.hardness))
        groups.setdefault(key, []).append(edge)
    out: List[hg.HyperEdge] = []
    for key in sorted(groups, key=lambda item: (str(item[0]), sorted(item[1]))):
        group = sorted(groups[key],
                       key=lambda e: (-len(e.members), -e.occurrences, e.edge_id))
        representative = group[0]
        if len(group) == 1:
            out.append(representative)
            continue
        sources: List[str] = []
        for edge in group:
            for source in edge.sources or ():
                if str(source) not in sources:
                    sources.append(str(source))
        out.append(dataclasses.replace(
            representative,
            sources=tuple(sources),
            occurrences=sum(edge.occurrences for edge in group),
            confidence=max(edge.confidence for edge in group),
            confidence_max=max(edge.confidence_max for edge in group),
            extractor={**(representative.extractor or {}),
                       "global_dedupe_from": len(group)},
        ))
    return out, {"keys": len(groups), "duplicate_groups": sum(1 for g in groups.values() if len(g) > 1),
                 "dropped": len(edges) - len(out)}


#: §2.3b 关键纪律 2 的裁决顺序：**硬理论 > 软理论 > 结构化经验 > 案例类比**。
#: 成员集完全相同时（同一条耦合，只是出处不同），只留最硬的那条。
_SOURCE_KIND_RANK = {"theory": 0, "lesson": 1, "experience": 2}
_HARDNESS_RANK = {"hard": 0, "soft": 1}


def arbitrate_by_hardness(edges: Sequence[hg.HyperEdge]) -> Tuple[List[hg.HyperEdge], Dict]:
    """**成员集相同、只有出处/软硬不同**时，按 §2.3b 关键纪律 2 只留最硬那条。

    为什么必须有这一刀：`dedupe_key` 把 `(source_kind, hardness)` 也算进身份，所以
    "同一句耦合，一张理论卡和一张经验卡都说了"会产出**两条成员集完全相同**的边。
    实测（2026-10-02，L2 落地那一轮）783 条边里有 **242 组**这样的孪生边；而
    `check_holdout` 的 `norm_key`（type ＋ 成员集）**不看** source_kind，标注的
    `must` 只指向成员集——孪生边让"该召回的那条"变成两条，检索名次立刻被稀释
    （实测 Q1 0.8655 → **0.3032**、Q4 1.0 → 0.9669）。

    裁决顺序与 `KnowledgeRetriever.edge_columns` 的呈现规则同源（那条规则做的是
    "同一句耦合既当硬约束又当建议"的抑制，这里做的是同一件事的索引侧版本）。
    被裁掉的那条**并进胜者的 `sources`**（出处不能丢），并如实记进合并报告。
    """
    groups: Dict[Tuple, List[hg.HyperEdge]] = {}
    for edge in edges:
        groups.setdefault(edge.norm_key, []).append(edge)
    out: List[hg.HyperEdge] = []
    dropped_kinds: Dict[str, int] = {}
    groups_with_drop = 0
    for key in sorted(groups, key=lambda item: (str(item[0]), sorted(map(str, item[1])))):
        group = sorted(groups[key], key=lambda e: (
            _HARDNESS_RANK.get(str(e.hardness), 9),
            _SOURCE_KIND_RANK.get(str(e.source_kind), 9),
            -e.occurrences, e.edge_id))
        winner = group[0]
        if len(group) == 1:
            out.append(winner)
            continue
        groups_with_drop += 1
        sources: List[str] = []
        for edge in group:
            for source in edge.sources or ():
                if str(source) not in sources:
                    sources.append(str(source))
        for edge in group[1:]:
            label = "%s/%s" % (edge.source_kind, edge.hardness)
            dropped_kinds[label] = dropped_kinds.get(label, 0) + 1
        out.append(dataclasses.replace(
            winner, sources=tuple(sources),
            occurrences=sum(edge.occurrences for edge in group),
            extractor={**(winner.extractor or {}), "arbitrated_from": len(group)}))
    return out, {"groups": groups_with_drop,
                 "dropped": sum(dropped_kinds.values()),
                 "dropped_by_source_kind": dict(sorted(dropped_kinds.items()))}


def unsupported_prohibition_hosts(edges: Sequence[hg.HyperEdge],
                                  cards_by_id: Dict[str, Dict],
                                  nodes: Dict[str, hg.Node],
                                  ) -> Tuple[List[hg.HyperEdge], Dict]:
    """**禁令必须有宿主**：把"只为了挂一条 `forbid` 而编出主体"的边拒收（第 2 段）。

    这一条的存在理由是提示里的规则 4b（"卡里出现 *避免/不要* 时把那个取值写成
    `forbid`"）——它是对的，但它同时给了个**旧宿主**：`EMOTION_PACK`。于是一张
    **只讲运镜**的卡被逼着补出 `emotion`／`intensity` 才能凑满必填槽位：

    ```
    gen_cine_0247「摄影机始终处于某种运动中，避免长时间静止固定」
      → EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定   # 主体是编的
    ```

    这条边的**禁半**（`固定`）在卡里落地，**主体**（`平静`）不在——卡里一个字都没提。
    双模型复核（`docs/knowledge/GATE6_LAST_CARD.panel.json`）也正是这么判的：
    `a(deepseek-chat): 卡只讲运镜持续运动，未支持情绪=平静或强度=low的耦合`。

    **为什么落地判据不能全局施加**：按"每个成员都要在卡里逐字出现"去卡，540 条边
    里会判掉 **538** 条（`allow` 596 个、`qualifier` 701 个成员找不到字面）——抽取器
    本来就在做抽象（`beat_type=coverage`、`intensity=mid` 这类推断永远没有字面）。
    所以判据**只在"这条边是某条禁令的宿主"时**施加，四条同时成立才拒收：

    ① 卡里真有否定表述（`grounding.NEGATION_CUES`，与门⑤ 同一份词表）；
    ② 这条边至少有一条 `forbid` 成员的取值/名字/别名**在卡里落地**；
    ③ 这条边的**必填 `allow` 主体**（如 `EMOTION_PACK` 的 `emotion`）一个都没落地；
    ④ 出处是**已知的卡**（引用了不存在的卡时不做判断，那是另一个缺陷）。

    实测（2026-10-02，540 条边）这一刀只落在 **2 条**上，且两条都是上面那个形状
    （另一条是 `cine_move_handheld`：卡写"*禁忌：安静的对话用手持*"，边却把
    **被禁的**手持写成了 `allow`——同一条规则的另一半）。落地后 `gen_cine_0247`
    变成零条边，与另外 29 张卡同路径离开门⑥ 的分母；被剔的两条**没有任何 oracle
    条目引用**（`work/zz_drop_blast.py` 实测 0 条孤立）。

    这一刀**不是放宽**：它拒收的是"库里没有依据的断言"。把这类边留在索引里，门⑥ 就会
    逼着标注方替它写一条**卡片不支持**的期望（面板已两次判它 rejected）。
    `card_scope_audit.MIN_EXPRESSIBLE_SHARE` 那道下界（可断言卡 ≥ 入库卡 95%）同时
    挡住"把抽取关掉让分母变空"这条自毁路径。
    """
    kept: List[hg.HyperEdge] = []
    dropped: List[Dict] = []
    for edge in edges:
        sources = [str(source) for source in (edge.sources or ())]
        known = [source for source in sources if source in cards_by_id]
        if not sources or len(known) != len(sources):
            kept.append(edge)
            continue
        text = grounding.texts_for(sources, cards_by_id)
        if not grounding.has_negation_cue(text):
            kept.append(edge)
            continue
        forbids = grounding.grounded_forbids(edge, nodes, text)
        if not forbids:
            kept.append(edge)
            continue
        required = hg.REQUIRED_MEMBERS.get(edge.type) or ()
        ungrounded = grounding.ungrounded_required_subjects(edge, required, nodes, text)
        if not ungrounded:
            kept.append(edge)
            continue
        dropped.append({
            "edge_id": edge.edge_id, "type": edge.type, "sources": sources,
            "invented_subject": [member.node_id for member in ungrounded],
            "grounded_forbid": [member.node_id for member in forbids],
        })
        continue
    return kept, {
        "rule": "unsupported_prohibition_host",
        "rule_version": VALIDATION_RULES_VERSION,
        "meaning": "禁令的宿主必须是卡片自己说的：禁半落地、必填 allow 主体不落地 ⇒ 拒收",
        "dropped": len(dropped), "edges": dropped,
        "criterion": ("① 卡里有否定表述 ② 至少一条 forbid 在卡里落地 "
                      "③ 必填 allow 主体一个都不落地 ④ 出处都是已知的卡"),
    }


def extract(cards: Sequence[Dict], vocab: Dict[str, List[str]], client,
            batch_size: int = BATCH_CARDS, limit: int = 0, *,
            concurrency: int = 1,
            nodes: Optional[Dict[str, hg.Node]] = None,
            ) -> Tuple[List[hg.HyperEdge], List[Dict], List[Dict]]:
    """**第 1 段**：逐批把卡片抽成原子边。

    `concurrency > 1` 时按批并行（§2.3 的 R51 口径：第 1 段可并发，默认取
    `rag.extract_concurrency`）。结果按**批号**重排后再吸收，因此并发不影响
    产物顺序——"同一六元指纹两次构建逐字节一致"这条回归基线仍然成立。
    """
    by_id = {str(c["id"]): c for c in cards}
    if nodes is None:
        try:
            nodes = nodes_from_vocab()
        except Exception:  # noqa: BLE001 - 词表不可用时退化为"不做引用完整性检查"
            nodes = None
    node_index = NodeIndex(nodes) if nodes else None
    # 同域归并：批内只放同一个 domain 的卡（§2.3 的"同一 domain"约束）
    groups: Dict[str, List[Dict]] = {}
    for card in cards:
        groups.setdefault(card["domain"], []).append(card)
    batches: List[List[Dict]] = []
    for domain in sorted(groups):
        items = groups[domain]
        for start in range(0, len(items), batch_size):
            batches.append(items[start:start + batch_size])
    if limit:
        batches = batches[:limit]

    edges: List[hg.HyperEdge] = []
    rejects: List[Dict] = []
    batch_log: List[Dict] = []

    def call(item):
        index, batch = item
        try:
            reply = client.chat_json(SYSTEM_PROMPT, build_prompt(batch, vocab, nodes),
                                     0.0, 0, 8192, key=batch[0]["id"])
        except Exception as exc:  # noqa: BLE001
            return index, batch, None, f"{type(exc).__name__}: {exc}"
        return index, batch, reply, ""

    numbered = list(enumerate(batches, 1))
    if concurrency > 1 and len(numbered) > 1:
        with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as pool:
            results = list(pool.map(call, numbered))
    else:
        results = [call(item) for item in numbered]
    results.sort(key=lambda row: row[0])  # 批号定序 → 产物与串行完全一致

    for index, batch, reply, error in results:
        if reply is None:
            rejects.append({"batch": index, "reason": error})
            batch_log.append({"batch": index, "status": "error"})
            continue
        raw_edges = reply.get("edges") if isinstance(reply, dict) else None
        if not isinstance(raw_edges, list):
            rejects.append({"batch": index, "reason": "reply_not_a_list"})
            batch_log.append({"batch": index, "status": "error"})
            continue
        produced = 0
        per_card: Dict[str, int] = {}
        for raw in raw_edges:
            card_id = str(raw.get("source_card", ""))
            if per_card.get(card_id, 0) >= MAX_EDGES_PER_CARD:
                reject = {"batch": index, "reason": "too_many_edges_for_card", "raw": raw}
                rejects.append(reject)
                continue
            edge, reason = to_edge(raw, by_id, node_index)
            if edge is None:
                rejects.append({"batch": index, "reason": reason, "raw": raw})
                continue
            if int(edge.extractor.get("dropped_members", 0) or 0):
                rejects.append({"batch": index, "reason": "dropped_dangling_members",
                                "edge_id": edge.edge_id, "raw": raw})
            per_card[card_id] = per_card.get(card_id, 0) + 1
            edges.append(edge)
            produced += 1
        batch_log.append({"batch": index, "status": "done", "edges": produced,
                          "cards": [c["id"] for c in batch]})
    return edges, rejects, batch_log


def nodes_from_vocab() -> Dict[str, hg.Node]:
    return {node["node_id"]: hg.Node.from_dict(node) for node in
            json.loads(VOCAB.read_text(encoding="utf-8"))["nodes"]}


def chunk_counts(cards: Sequence[Dict], batch_log: Sequence[Dict],
                 atoms: Sequence = ()) -> Tuple[int, int]:
    """构建门的"chunk 处理率"：按**批次覆盖到的 chunk_id** 计数。

    出错/被跳过的批次不贡献任何 chunk，因此比率会掉到 1.0 以下——这正是门要抓的。

    `atoms` 是**这一轮结束后的完整原子边集合**，参与计数是必须的：增量路径
    （`--only-missing` 补边、`--replace-cards` 清洗）只重抽一部分卡，本轮 `batch_log`
    自然只覆盖那一部分，而索引其实覆盖了全量 —— 只看本轮日志会把"补抽/清洗"
    误判成"构建门没过"（实测：清洗 329 张卡后 Q0 报 `processed != total`，
    `tests/test_knowledge_quality.py` 当场转红）。判据本身不变：**每一张卡的
    chunk 都必须在"本轮抽过"或"磁盘上已有它的原子边"里出现一次**。
    """
    all_chunks = {str(c.get("source_span", {}).get("chunk_id", c["id"])) for c in cards}
    by_id = {str(c["id"]): c for c in cards}
    processed: set = set()
    for entry in batch_log:
        if entry.get("status") != "done":
            continue
        for card_id in entry.get("cards", []):
            card = by_id.get(str(card_id))
            if card is not None:
                processed.add(str(card.get("source_span", {}).get("chunk_id", card_id)))
    for edge in atoms:
        for source in (getattr(edge, "sources", ()) or ()):
            card = by_id.get(str(source))
            if card is not None:
                processed.add(str(card.get("source_span", {}).get("chunk_id", source)))
    return len(processed), len(all_chunks)


def _write_index(cards: Sequence[Dict], atoms: Sequence[hg.HyperEdge],
                 rejects: Sequence[Dict], batch_log: Sequence[Dict], *,
                 extractor: Dict[str, str], cache_key: Dict[str, str],
                 fingerprint: str, merged, merge_report: Dict) -> Dict:
    """第 1 段产物之后的公共收尾：归并 → 9 条门 → 落盘 → manifest。"""
    processed, total = chunk_counts(cards, batch_log, atoms)
    gate_rejects: List[Dict] = []
    unique, report = hg.build_index(merged, nodes_from_vocab(),
                                    processed_chunks=processed, total_chunks=total,
                                    reject_sink=gate_rejects)
    merge_rejects = [{"phase": "merge", "reason": item["reason"],
                      "edge_ids": item["edge_ids"]}
                     for item in merge_report["dropped_groups"]]
    # `merge` 段里"这条索引到底有多少禁忌/最大 arity"必须描述**写出去的**那批边，
    # 不是去重校验之前的候选（否则 manifest 与 `hypergraph.edges.jsonl` 对不上，
    # 而 §4.1b 硬规则 2 禁止自报一个对不上的汇总）。候选口径另存 `before_dedupe`。
    merge_report = dict(merge_report)
    merge_report["before_dedupe"] = {
        "merged_edges": merge_report["merged_edges"],
        "forbid_members": merge_report["forbid_members"],
        "max_arity": merge_report["max_arity"],
    }
    merge_report["merged_edges"] = len(unique)
    merge_report["forbid_members"] = sum(len(edge.forbids) for edge in unique)
    merge_report["max_arity"] = max((len(edge.members) for edge in unique), default=0)
    repairs = sum(int((edge.extractor or {}).get("dropped_members", 0) or 0) for edge in unique)
    merge_report["dangling_members_dropped"] = repairs
    common.write_jsonl(EDGES, [edge.to_dict() for edge in unique])
    # 边级拒收 → 与 manifest.rejects 一一对应；原子级/归并级 → 另一个文件（工作区）。
    common.write_jsonl(REJECTS, gate_rejects)
    common.write_jsonl(ATOM_REJECTS, list(rejects) + merge_rejects)
    common.dump_json(REPORT, {**report.to_dict(), "merge": merge_report,
                              "atoms": len(atoms), "merge_rejects": len(merge_rejects),
                              "atom_rejects": len(rejects)})
    common.dump_json(MANIFEST, {
        "fingerprint": fingerprint,
        "cache_key": cache_key,
        "extractor": extractor,
        "prompt_version": PROMPT_VERSION,
        # 清洗路径（`--replace-cards`）会让索引里**混着两个 prompt 版本**的原子边。
        # 六元指纹只有一个 `prompt_version` 字段，所以这里必须把混版这件事**显式记下来**，
        # 否则 manifest 会声称整库都是当前口径 —— 那是自报一个对不上的汇总
        # （§4.1b 硬规则 2 禁止）。`atoms_by_prompt_version` 直接从原子边里数。
        "atom_prompt_versions": dict(collections.Counter(
            str((edge.extractor or {}).get("prompt_version") or "unknown")
            for edge in atoms)),
        "decode": DECODE,
        "chunker_version": common.CHUNKER_VERSION,
        "schema_version": hg.SCHEMA_VERSION,
        #: §2.3："六元指纹 ＋ 校验门代码版本"。这一行是后半句的落点；`cache_key`
        #: 里也有同名分量，所以 `fingerprint_of(manifest["cache_key"])` 仍然自洽。
        "validation_rules_version": VALIDATION_RULES_VERSION,
        "cards": len(cards),
        "raw_edges": report.raw_edges,
        "valid_unique": report.valid_unique,
        "duplicates": report.duplicates,
        "rejects": report.rejects,
        "atom_rejects": len(rejects),
        "merge_rejects": len(merge_rejects),
        "atoms": len(atoms),
        "merge": merge_report,
        "batches": batch_log,
    })
    return {"report": report.to_dict(), "edges": len(unique), "rejects": len(rejects),
            "atoms": len(atoms), "merge": merge_report,
            "merge_rejects": len(merge_rejects)}


def _atom_key(edge) -> Tuple:
    """原子边去重键：**类型 ＋ 成员 ＋ 来源卡**。

    来源卡必须进键：两张不同的卡可能表达同一条耦合，归并期正靠
    `sources` 把 `multi_card_edges` 记出来；只按（类型, 成员）去重会把
    后一张卡的原子边当成重复丢掉——`--only-missing` 补进来的边会原地消失。
    """
    return (str(edge.type),
            tuple(sorted((m.role, m.kind, m.node_id) for m in edge.members)),
            tuple(sorted(str(source) for source in (edge.sources or ()))))


def load_atoms() -> List:
    """读回第 1 段落盘的原子边（`--only-missing` 与 `--rematch` 共用）。"""
    if not ATOMS.is_file():
        return []
    out = []
    for line in ATOMS.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            out.append(hg.HyperEdge.from_dict(json.loads(line)))
    return out


def cards_with_atoms() -> set:
    """已经有原子边的卡 id 集合——`--only-missing` 的输入就是它的补集。"""
    return {str(source) for edge in load_atoms() for source in (edge.sources or ())}


def run(cards: Sequence[Dict], vocab: Dict[str, List[str]], client,
        limit: int = 0, *, concurrency: int = 1,
        extract_only: Optional[Sequence[Dict]] = None,
        keep_atoms: bool = False,
        replace_atoms_for: Optional[Sequence[str]] = None) -> Dict:
    """抽第 1 段 → 落盘 → 归并 → 写索引。

    `extract_only` 限定**抽取哪些卡**（指纹与索引仍然按**全量** `cards` 算），
    `keep_atoms` 把新原子边**并入**已有文件——这是"给漏抽的卡补边"的路径：
    实测 167 张卡（占 9.6%）在整轮抽取里一条原子边都没拿到，重抽整库既慢又不
    保证覆盖它们，而只喂这些卡一批，模型就会认真对待。

    `replace_atoms_for` 是**清洗**路径：重新抽这些卡，并**丢掉它们原来的原子边**。
    与 `keep_atoms` 的区别是决定性的——`keep_atoms` 只做并集，旧边还在索引里，
    "把 `action=人物弧光` 这类边清掉"根本做不到。实测 v6 有 170 条这样的边，
    分布在 329 张卡上，只能靠"重抽 + 替换"。
    """
    todo = list(extract_only) if extract_only is not None else list(cards)
    refresh_info: Optional[Dict] = None
    atoms, rejects, batch_log = extract(todo, vocab, client, BATCH_CARDS, limit,
                                        concurrency=concurrency)
    if keep_atoms:
        previous = load_atoms()
        seen = {_atom_key(edge) for edge in previous}
        atoms = previous + [edge for edge in atoms if _atom_key(edge) not in seen]
    if replace_atoms_for:
        # 清洗路径：**先丢旧的，再放新的**。顺序不能反——反了会把刚抽到的边
        # 当成"旧边"一起丢掉。`sources` 里只要出现被替换的卡，整条原子边就作废。
        dropped = set(str(item) for item in replace_atoms_for)
        previous = load_atoms()
        kept = [edge for edge in previous
                if not (dropped & {str(s) for s in (edge.sources or ())})]
        replaced = len(previous) - len(kept)
        seen = {_atom_key(edge) for edge in kept}
        atoms = kept + [edge for edge in atoms if _atom_key(edge) not in seen]
        # **不许写进 `batch_log`**：那个清单是"抽取批次"的账，构建门 Q0 会数
        # "多少批 done / 共多少批"。塞一条非抽取条目进去会让 `processed != total`
        # （实测 44/45），于是 Q0 把一次**成功的清洗**报成构建失败
        # （`tests/test_knowledge_quality.py` 当场转红）。清洗的账另记在 `refresh`。
        refresh_info = {"cards": len(dropped), "atoms_dropped": replaced,
                        "atoms_kept": len(kept)}
    # §2.3 第 1 段全部落盘**之后**才跑第 2 段，且第 2 段是纯函数（串行、确定）。
    # 落盘原子边是为了"只换归并口径"时不必重抽（改 prompt 要重抽，改归并不是）。
    common.write_jsonl(ATOMS, [edge.to_dict() for edge in atoms])
    merged, merge_report = merge_edges(atoms, {str(card["id"]): card for card in cards},
                                       nodes_from_vocab())
    #: **混版记账必须在 `--rematch` 路径上续上**。清洗（`--replace-cards`）会留下
    #: 两个 prompt 版本的原子边，而 `--rematch` 是"不重抽、只重跑第 2 段"，它建的
    #: 是一份**全新**的 merge_report——上一轮写下的 `refresh` 就这样丢了，
    #: manifest 于是"混着多版却没有任何清洗记录"（§4.1b 硬规则 2 禁止自报一个
    #: 对不上的汇总；`tests/test_build_ledger.py::test_refresh_bookkeeping…` 当场抓到）。
    #: 有旧账就续用，没有就如实造一条"重归并时发现原子边混版"的账。
    versions = collections.Counter(
        str((edge.extractor or {}).get("prompt_version") or "unknown") for edge in atoms)
    if len(versions) > 1:
        previous_report = (json.loads(REPORT.read_text(encoding="utf-8"))
                           if REPORT.is_file() else {})
        previous_refresh = ((previous_report.get("merge") or {}).get("refresh")
                            if isinstance(previous_report, dict) else None)
        merge_report["refresh"] = previous_refresh or {
            "reason": "rematch：原子边是多个 prompt 版本的混合（清洗路径的产物）",
            "atom_prompt_versions": dict(versions)}
        merge_report["refresh_prompt_version"] = PROMPT_VERSION
    # 第 2 段是**按窗口**分组，跨窗口的同 norm_key 会留下副本；§2.3 的去重键是
    # 全局的，所以这里再补一刀（实测 852 条边里有 144 条是副本）。
    merged, global_dedupe = dedupe_by_norm_key(merged)
    merge_report["global_dedupe"] = global_dedupe
    # §2.3b 关键纪律 2：成员集相同、只有出处/软硬不同时，硬理论优先（见函数注释）。
    merged, arbitration = arbitrate_by_hardness(merged)
    merge_report["arbitrate_by_hardness"] = arbitration
    #: 阶段二的**精确度门**：禁令必须有宿主（见 `unsupported_prohibition_hosts`）。
    #: 位置在去重与硬软裁决**之后**——出处是"全部被引卡"的并集，所以一条另有卡片
    #: 支持得住主体的边不会因为某一张卡缺席而被拒收。
    merged, precision = unsupported_prohibition_hosts(
        merged, {str(card["id"]): card for card in cards}, nodes_from_vocab())
    merge_report["unsupported_prohibition_hosts"] = precision
    if refresh_info is not None:
        merge_report["refresh"] = refresh_info
        merge_report["refresh_prompt_version"] = PROMPT_VERSION
    components = fingerprint_components(cards, client)
    return _write_index(cards, atoms, rejects, batch_log, merged=merged,
                        merge_report=merge_report, fingerprint=fingerprint_of(components),
                        cache_key=components,
                        extractor={"model_id": client.model_id, "family": client.family,
                                   "model_version": client.model_version})


def rematch(cards: Sequence[Dict], vocab: Dict[str, List[str]]) -> Dict:
    """**不重抽**：从 `work/hypergraph.atoms.jsonl` 重跑第 2 段归并并重建索引。

    第 2 段是纯函数，所以调归并口径（窗口、禁忌优先级、渲染预算、精确度门）时不该
    再烧一遍 API。指纹里的 `prompt_version`／`validation_rules_version` 仍按**当前**
    口径写——否则"改了 prompt 或改了归并门却用旧产物"会被当成同一份索引。
    """
    if not ATOMS.is_file():
        raise FileNotFoundError(f"没有第 1 段的原子边：{ATOMS}（先跑一次完整抽取）")
    atoms = [hg.HyperEdge.from_dict(row) for row in
             [json.loads(line) for line in ATOMS.read_text(encoding="utf-8").split("\n")
              if line.strip()]]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else {}
    extractor = manifest.get("extractor") or {"model_id": "", "family": "",
                                              "model_version": ""}
    components = fingerprint_components(cards, _ExtractorStub(extractor))
    merged, merge_report = merge_edges(atoms, {str(card["id"]): card for card in cards},
                                       nodes_from_vocab())
    #: 第 2 段的**收尾两步**必须与 `run()` 逐字一致，否则"重归并之后的索引"和
    #: "重抽之后的索引"不是同一份东西。实测代价：漏掉 `arbitrate_by_hardness` 时
    #: 783 条边里留着 **242 组**孪生边（同成员集、不同 source_kind），
    #: Q1 0.8655 → **0.3032**、Q4 1.0 → 0.9669。
    merged, global_dedupe = dedupe_by_norm_key(merged)
    merge_report["global_dedupe"] = global_dedupe
    merged, arbitration = arbitrate_by_hardness(merged)
    merge_report["arbitrate_by_hardness"] = arbitration
    #: 第 2 段的**精确度门**与 `run()` 逐字一致（两条路径必须产出同一份东西）。
    merged, precision = unsupported_prohibition_hosts(
        merged, {str(card["id"]): card for card in cards}, nodes_from_vocab())
    merge_report["unsupported_prohibition_hosts"] = precision
    #: `--rematch` 是"不重抽、只重跑第 2 段"，它建的是**全新**的 merge_report——
    #: 清洗（`--replace-cards`）留下的 `refresh` 账会就此丢掉，manifest 于是
    #: "混着多个 prompt 版本却没有任何清洗记录"（§4.1b 硬规则 2 禁止自报一个
    #: 对不上的汇总；`tests/test_build_ledger.py` 当场抓到）。有旧账就续用，
    #: 没有就如实造一条"重归并时发现原子边混版"的账。
    versions = collections.Counter(
        str((edge.extractor or {}).get("prompt_version") or "unknown") for edge in atoms)
    if len(versions) > 1:
        previous_report = (json.loads(REPORT.read_text(encoding="utf-8"))
                           if REPORT.is_file() else {})
        previous_refresh = ((previous_report.get("merge") or {}).get("refresh")
                            if isinstance(previous_report, dict) else None)
        merge_report["refresh"] = previous_refresh or {
            "reason": "rematch：原子边是多个 prompt 版本的混合（清洗路径的产物）",
            "atom_prompt_versions": dict(versions)}
        merge_report["refresh_prompt_version"] = PROMPT_VERSION
    # 第 1 段的原子级拒收在上一次运行里已经落盘（重抽才会变），这里原样带回去；
    # 归并级拒收是本次重算出来的，所以只要 `phase != merge` 的那些。
    rejects = [row for row in
               [json.loads(line) for line in
                (ATOM_REJECTS.read_text(encoding="utf-8").split("\n")
                 if ATOM_REJECTS.is_file() else [])
                if line.strip()]
               if row.get("phase") != "merge"]
    return _write_index(cards, atoms, rejects, manifest.get("batches", []), merged=merged,
                        merge_report=merge_report,
                        fingerprint=fingerprint_of(components), cache_key=components,
                        extractor=extractor)


class _ExtractorStub:
    """只为 `fingerprint_components` 提供 `model_id/model_version` 的轻量替身。"""

    def __init__(self, extractor: Dict):
        self.model_id = str(extractor.get("model_id", ""))
        self.model_version = str(extractor.get("model_version", ""))
def load_cards() -> List[Dict]:
    """抽取器看到的卡片全集 = 生成卡 ＋ **手写策展卡**。

    v1.5 修正：手写卡（`block_director/knowledge/cards_*.py` 里那 132 张）原先
    **完全不进索引**——`cards_generated/*.jsonl` 里没有它们，于是
    `axis_180`／`axis_cross`／`comp_thirds` 这些旗舰硬规则在超图侧永远召不回。
    实测（2026-10-01）：held-out 涉及 1075 张卡，其中 **268 张在索引里一条边
    都没有**，示例正是上面这几张。

    它们缺的只是出处字段，而"出处"本身就是**卡片自己**：文件在仓库里、
    许可是 `OwnWork`、正文可复算 sha256。所以补一个**如实的**出处即可：
    `chunk_id = curated/<id>`，span 取整段正文，provenance 记 `权威文档`。
    这不是放宽门，而是把一条早就该在索引里的知识放进去。
    """
    out: List[Dict] = []
    directory = common.CARDS_DIR
    if directory.is_dir():
        for path in sorted(directory.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").split("\n"):
                line = line.strip()
                if not line:
                    continue
                card = json.loads(line)
                if card.get("source_span"):
                    out.append(card)
    try:
        from block_director.knowledge.corpus import HANDWRITTEN_CARDS
    except Exception:  # pragma: no cover - 换环境时不该因此失败
        return out
    known = {str(card.get("id")) for card in out}
    for card in HANDWRITTEN_CARDS:
        if card.id in known:
            continue
        span = {"chunk_id": f"curated/{card.id}", "start": 0, "end": len(card.content)}
        out.append({
            "id": card.id,
            "domain": card.domain,
            "title": card.title,
            "content": card.content,
            "keywords": list(card.keywords),
            "tags": list(card.tags),
            "rules": list(card.rules),
            "emotion": card.emotion,
            "chunk_id": span["chunk_id"],
            "source_span": span,
            "provenance_kind": "权威文档",
            "source_ref": {
                "url": f"repo://block_director/knowledge/cards#{card.id}",
                "title": card.title,
                "author": "BlockDirector knowledge team",
                "license": "OwnWork",
                "retrieved_at": "2026-10-01",
                "sha256": common.sha256_text(card.content),
            },
        })
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.build_hypergraph")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="")
    parser.add_argument("--scripted", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=0,
                        help="第 1 段的并发上限；0 = 取 config 的 rag.extract_concurrency")
    parser.add_argument("--rekey-manifest", action="store_true",
                        help="只按当前卡片与 manifest 里记录的分量重算指纹，不重抽")
    parser.add_argument("--rematch", action="store_true",
                        help="不重抽：从 work/hypergraph.atoms.jsonl 重跑第 2 段归并并重建索引")
    parser.add_argument("--only-missing", action="store_true",
                        help="只重抽「现有原子边里没有」的卡，并把新原子边并入旧文件"
                            "（给整轮抽取漏掉的卡补边）")
    parser.add_argument("--replace-cards", default="",
                        help="卡片 id 清单文件（每行一个）：重抽这些卡并**丢弃它们原来的"
                             "原子边**。用于清洗——`--only-missing` 只做并集，清不掉旧边。"
                             "实测用途：v6 把 170 条 `action=人物弧光` 之类的概念名词"
                             "写进了动作槽位（分布在 329 张卡上）。")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.rekey_manifest:
        # 指纹是"记录下来的六个分量"的纯函数：口径升级后就地重算，不重抽语料。
        print(json.dumps(rekey_manifest(), ensure_ascii=False, indent=2))
        return 0

    if not VOCAB.exists():
        print(json.dumps({"error": "先跑 tools.kb_fetch.vocabulary"}, ensure_ascii=False))
        return 1
    vocab = json.loads(VOCAB.read_text(encoding="utf-8"))["vocab"]
    cards = load_cards()
    if not cards:
        print(json.dumps({"error": "没有带 source_span 的生成卡"}, ensure_ascii=False))
        return 1
    if args.rematch:
        print(json.dumps(rematch(cards, vocab), ensure_ascii=False, indent=2))
        return 0
    client = llm.make_client(args.provider, args.model, args.scripted)
    if args.only_missing:
        have = cards_with_atoms()
        missing = [card for card in cards if str(card["id"]) not in have]
        print(json.dumps({"only_missing": True, "cards_total": len(cards),
                          "cards_with_atoms": len(have), "to_extract": len(missing)},
                         ensure_ascii=False))
        summary = run(cards, vocab, client, args.limit,
                      concurrency=_concurrency(args.concurrency),
                      extract_only=missing, keep_atoms=True)
    elif args.replace_cards:
        # 清洗路径：见 `run(..., replace_atoms_for=...)`。与 `--only-missing` 的区别是
        # **替换**而不是并集——只有替换才能把 `action=人物弧光` 这类边真正清出索引。
        wanted = [line.strip() for line in
                  pathlib.Path(args.replace_cards).read_text(encoding="utf-8").split("\n")
                  if line.strip()]
        by_id = {str(card["id"]): card for card in cards}
        todo = [by_id[card_id] for card_id in wanted if card_id in by_id]
        unknown = sorted(set(wanted) - set(by_id))
        print(json.dumps({"replace_cards": True, "requested": len(wanted),
                          "matched": len(todo), "unknown": unknown[:8]},
                         ensure_ascii=False))
        summary = run(cards, vocab, client, args.limit,
                      concurrency=_concurrency(args.concurrency),
                      extract_only=todo, replace_atoms_for=wanted)
    else:
        summary = run(cards, vocab, client, args.limit,
                      concurrency=_concurrency(args.concurrency))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["report"]["passed"] else 1


def _concurrency(override: int) -> int:
    """并发上限：CLI 显式给值优先，否则读 `rag.extract_concurrency`（默认 16）。"""
    if override:
        return max(1, int(override))
    try:
        from block_director.contracts.config import AppConfig

        return max(1, int(AppConfig().rag.extract_concurrency))
    except Exception:  # noqa: BLE001 - 配置层不可用时退回串行，不静默放大并发
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
