"""P14-2：把卡片抽取成超边并建索引（执行文档 v1.4 §2.3 的"索引构建"）。

两段式（§2.3）在这里落地为：**逐卡抽原子事实**（batch = 若干张卡）→ **同域归并**。
归并窗口写死为"同一 `domain`（含卡片自身的 `related` 邻域）且每批不超过 8 张卡"，
这与 §2.3 的"同域 ＋ 一跳 related 闭包；每次归并最多 8 张卡"一致。

校验：`block_director/knowledge/hypergraph.build_index` 的 9 条门。不合格的边进
`knowledge/hypergraph.rejects.jsonl`；构建门是 `rejects ≤ 5%` 且没有 chunk 被跳过。

断点续跑：六元指纹（语料 sha256 ＋ 抽取器 model id＋版本 ＋ prompt 版本 ＋ chunk 策略 ＋
解码参数 ＋ schema 版本）写进 `knowledge/hypergraph.manifest.json`。

**六元指纹必须是"记录下来的六个分量的纯函数"**（§2.3 的缓存键 / §6 的"重抽取成本"）：
`fingerprint_of(manifest["cache_key"]) == manifest["fingerprint"]`，且六个分量任一个变了
指纹就必须变——否则"改了 prompt / 换了 chunk 策略"会复用旧索引，而 manifest 上看不出来。
本模块只认这六个键（多一个少一个都直接报错），免得以后加了新分量却忘了进哈希。
"""

from __future__ import annotations

import argparse
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
PROMPT_VERSION = "extract/v5"
BATCH_CARDS = 8
#: 归并窗口的卡片数上限（§2.3 第 2 步写死为 8）。
MERGE_WINDOW = 8
#: 单张卡在一个批次里最多贡献几条**原子边**。旧值 2 把"一张卡讲了三条耦合"
#: 直接记成 `too_many_edges_for_card` 丢掉——那是第 2 段归并没实现时的代偿，
#: 不是 §2.3 的要求。放宽到 4，超出的仍逐条留痕（不静默）。
MAX_EDGES_PER_CARD = 4
#: 解码参数属于六元指纹的一部分：它写死在调用里（`extract()` 的 temperature=0/seed=0/ctx=8192）。
DECODE = "temperature=0;seed=0;ctx=8192"

#: 六元指纹的分量名（顺序即 `cache_key` 的键序）。
CACHE_KEY_FIELDS = ("corpus_sha256", "model", "prompt_version",
                    "chunker_version", "decode", "schema_version")


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
                           decode: str = DECODE,
                           chunker_version: str = "",
                           schema_version: str = "") -> Dict[str, str]:
    """把六元指纹的六个分量算出来（`cache_key` 的**唯一**生产者）。"""
    return {
        "corpus_sha256": corpus_digest(cards),
        "model": f"{client.model_id}@{getattr(client, 'model_version', '')}",
        "prompt_version": str(prompt_version),
        "chunker_version": str(chunker_version or common.CHUNKER_VERSION),
        "decode": str(decode),
        "schema_version": str(schema_version or hg.SCHEMA_VERSION),
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

    指纹是"记录下来的六个分量"的纯函数，所以口径升级（例如以前只哈希 id＋model）
    之后可以就地重算：`corpus_sha256` 用当前卡片重算，其余五个从 manifest 自己读。
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
    }
    rekeyed = {"fingerprint": fingerprint_of(components), "cache_key": components}
    rekeyed.update({key: value for key, value in manifest.items()
                    if key not in ("fingerprint", "cache_key")})
    common.dump_json(target, rekeyed)
    return {"manifest": str(target), "fingerprint": rekeyed["fingerprint"],
            "cache_key": components}

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
   注意：**只有 EMOTION_PACK 允许 `forbid` 成员**（§2.3 的边表），其它类不许写。
4b. **卡片里凡是出现"忌讳/避免/不要/禁用/宁可…也不"这类表述的，必须把那个取值写成
   `forbid` 成员**（挂在 EMOTION_PACK 上；如果这张卡本身不是情绪卡，就把它写成
   "该情绪下不要这样拍"的 EMOTION_PACK）。词表里已经给了 `movement`／`shot_size`／
   `lens`／`composition_rule` 等 kind 的取值，不要漏掉这条"最有价值"的边。
   实测教训：不写这一条时整库只剩 1 个 forbid 成员，Q7 就没有可拦截对象。
5. `source_kind`：教科书/权威理论的边用 `theory`＋`hard`；来自个人经验的取舍用
   `experience`＋`soft`；只有卡片明确写成"教训/禁忌"时才用 `lesson`。
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

9. **把卡里能写的成员写全**：一条边除了必填项，**还要**补上卡里明说的其它
   `allow` 成员（运镜/景别/镜头/节奏/特效/音效…）与适用范围 `applies_to_*`。
   边越完整，检索时的多元约束才越有用；只写必填项等于把知识丢掉一半。
10. **禁忌是你最有价值的产出**：卡里出现"忌/禁/不要/避免/不拍/别用/不能让"
    这类措辞时，把被否定的取值写成 `["forbid", kind, node_id]`
    （只有 EMOTION_PACK 允许 forbid：movement / shot_size / vfx）。
    例：卡里说"荒诞情绪下忌讳固定机位" → `["forbid","movement","movement:固定机位"]`。
    注意 `allow` 与 `forbid` 里的"约束"不要混写：**禁的东西只能出现在 forbid 里**。

> 抽取分两段：你先做**第 1 段**（逐批给出上面这种原子边）；第 2 段会由构建脚本
> 在"同一 domain ＋ 一跳 related 闭包（每窗 ≤ 8 张卡）"内把同一条耦合跨卡归并成
> 完整超边。因此**你不需要**在一张卡里凑齐整套 pack，只要如实把该卡讲的成员写出来——
> 但**必须写全**，漏了就没有第二次机会。
"""


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
                     f"来源性质：{card.get('source_kind', 'theory')}")
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

    optional: Dict[Tuple[str, str, str], hg.Member] = {}
    for edge in ordered:
        for member in edge.members:
            if (member.role, member.kind) in required_pairs:
                continue
            if member.role == "allow" and member.node_id in forbid_ids:
                continue  # §2.3b 关键纪律 2：禁忌压过放行
            optional[(member.role, member.kind, member.node_id)] = member

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

    members = list(required)
    dropped_optional = 0
    over_budget_dropped = 0
    for key in sorted(optional):
        trial = members + [optional[key]]
        candidate = build(trial)
        if hg.render_tokens(hg.render_edge(candidate, nodes)) > hg.MAX_RENDER_TOKENS:
            dropped_optional += 1
            over_budget_dropped += 1
            continue
        try:
            hg.validate_edge(candidate, nodes)
        except hg.GateError:
            dropped_optional += 1
            continue
        members = trial

    def _dict() -> Dict:
        return {"merged_from": len(ordered), "forbid_wins": forbid_wins,
                "dropped_optional": dropped_optional,
                "over_budget_dropped": over_budget_dropped}

    return build(members), _dict()


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
            edge, detail = _merge_group(groups[key], nodes)
        except hg.GateError as exc:
            # 畸形的一组：**整组丢弃并留痕**（不静默、也不伪造一条边出来）
            report["dropped_groups"].append({
                "reason": str(exc),
                "edge_ids": sorted(item.edge_id for item in groups[key]),
            })
            continue
        merged.append(edge)
        report["forbid_wins"] += detail["forbid_wins"]
        report["dropped_optional"] += detail["dropped_optional"]
        report["over_budget_dropped"] += detail["over_budget_dropped"]
        if detail["merged_from"] > 1:
            report["multi_card_edges"] += 1
    merged.sort(key=lambda e: (e.type, required_signature(e), e.source_kind,
                               e.hardness, e.edge_id))
    report["merged_edges"] = len(merged)
    report["forbid_members"] = sum(len(edge.forbids) for edge in merged)
    report["max_arity"] = max((len(edge.members) for edge in merged), default=0)
    return merged, report


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


def chunk_counts(cards: Sequence[Dict], batch_log: Sequence[Dict]) -> Tuple[int, int]:
    """构建门的"chunk 处理率"：按**批次覆盖到的 chunk_id** 计数。

    出错/被跳过的批次不贡献任何 chunk，因此比率会掉到 1.0 以下——这正是门要抓的。
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
    return len(processed), len(all_chunks)


def _write_index(cards: Sequence[Dict], atoms: Sequence[hg.HyperEdge],
                 rejects: Sequence[Dict], batch_log: Sequence[Dict], *,
                 extractor: Dict[str, str], cache_key: Dict[str, str],
                 fingerprint: str, merged, merge_report: Dict) -> Dict:
    """第 1 段产物之后的公共收尾：归并 → 9 条门 → 落盘 → manifest。"""
    processed, total = chunk_counts(cards, batch_log)
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
        "decode": DECODE,
        "chunker_version": common.CHUNKER_VERSION,
        "schema_version": hg.SCHEMA_VERSION,
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


def run(cards: Sequence[Dict], vocab: Dict[str, List[str]], client,
        limit: int = 0, *, concurrency: int = 1) -> Dict:
    atoms, rejects, batch_log = extract(cards, vocab, client, BATCH_CARDS, limit,
                                        concurrency=concurrency)
    # §2.3 第 1 段全部落盘**之后**才跑第 2 段，且第 2 段是纯函数（串行、确定）。
    # 落盘原子边是为了"只换归并口径"时不必重抽（改 prompt 要重抽，改归并不是）。
    common.write_jsonl(ATOMS, [edge.to_dict() for edge in atoms])
    merged, merge_report = merge_edges(atoms, {str(card["id"]): card for card in cards},
                                       nodes_from_vocab())
    components = fingerprint_components(cards, client)
    return _write_index(cards, atoms, rejects, batch_log, merged=merged,
                        merge_report=merge_report, fingerprint=fingerprint_of(components),
                        cache_key=components,
                        extractor={"model_id": client.model_id, "family": client.family,
                                   "model_version": client.model_version})


def rematch(cards: Sequence[Dict], vocab: Dict[str, List[str]]) -> Dict:
    """**不重抽**：从 `work/hypergraph.atoms.jsonl` 重跑第 2 段归并并重建索引。

    第 2 段是纯函数，所以调归并口径（窗口、禁忌优先级、渲染预算）时不该再烧一遍
    API。六元指纹里的 `prompt_version` 仍按**当前**口径写——否则"改了 prompt 却
    用旧原子边"会被当成同一份索引。
    """
    if not ATOMS.is_file():
        raise FileNotFoundError(f"没有第 1 段的原子边：{ATOMS}（先跑一次完整抽取）")
    atoms = [hg.HyperEdge.from_dict(row) for row in
             [json.loads(line) for line in ATOMS.read_text(encoding="utf-8").splitlines()
              if line.strip()]]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else {}
    extractor = manifest.get("extractor") or {"model_id": "", "family": "",
                                              "model_version": ""}
    components = fingerprint_components(cards, _ExtractorStub(extractor))
    merged, merge_report = merge_edges(atoms, {str(card["id"]): card for card in cards},
                                       nodes_from_vocab())
    # 第 1 段的原子级拒收在上一次运行里已经落盘（重抽才会变），这里原样带回去；
    # 归并级拒收是本次重算出来的，所以只要 `phase != merge` 的那些。
    rejects = [row for row in
               [json.loads(line) for line in
                (ATOM_REJECTS.read_text(encoding="utf-8").splitlines()
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
            for line in path.read_text(encoding="utf-8").splitlines():
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
                        help="只按当前卡片与 manifest 里记录的五个分量重算六元指纹，不重抽")
    parser.add_argument("--rematch", action="store_true",
                        help="不重抽：从 work/hypergraph.atoms.jsonl 重跑第 2 段归并并重建索引")
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
