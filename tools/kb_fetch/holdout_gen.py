"""生成 held-out 标注集（P14-1 产出；执行文档 v1.4 §4.1 RK-13 / §2.3c 的 R49 五条）。

* **换族**：默认用本地 `qwen3-vl:30b`（family=qwen），而抽取器是 DeepSeek
  （family=deepseek）——`annotator.model_id != extractor.model_id`，且不同厂商族
  → `independence: strong`。
* **不可见**：提示里只给**卡片**（语料）与**冻结的词表/schema**，不给索引、
  不给 `knowledge_trace.json`、不给检索器实现、不给抽取 prompt。
* **格式**：一条 JSONL = `{id, from_card, q, must, top1, never, expect_movements,
  annotator, independence}`，`must` 写成 `TYPE:槽位=取值,…`，标注者不写 sha1。
* **覆盖**：按卡片 round-robin 保证"每张卡至少派生 1 条"（门⑥）。

断点续跑：与抽取一样绑在指纹上（卡片清单 sha256 ＋ 模型 id ＋ prompt 版本）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from . import common, llm
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common, llm  # type: ignore

from block_director.knowledge import hypergraph as hg
from tools.check_holdout import Q_KEY_TO_KIND, query_key_text

HOLDOUT = common.ROOT / "fixtures" / "knowledge_holdout.jsonl"
CARDS_JSON = common.ROOT / "fixtures" / "knowledge_holdout.cards.json"
MANIFEST = common.WORK / "holdout.manifest.json"
#: v13：`intensity` 补了查询键（`强度`）。提示里的键清单是**从 schema 渲染**的，
#: 所以模板一个字没改、**有效提示**却变了——版本号是让指纹诚实地跟着变，
#: 免得下一轮"续跑"把旧口径的 partial 当成同一批（那正是 §2.3 禁止的事）。
#:
#: v14：**v13 只换了键清单，却漏了正文**。正文第 1 条当时仍写着
#: "`intensity`／`headroom_policy`／`avg_shot_len` … 协议里没有给它们查询键，所以
#: `q` 里不写它们"，而渲染出来的键清单里**已经有 `强度`**——同一段话自相矛盾。
#: 标注员照正文办（写 `intensity=<取值>` 却不写 `强度=`），产出侧的
#: `query_shortfall()` 就把这些条目整条拒收：上一代 oracle 实测
#: **2449/4539 = 54.0% 不可达**，其中 `intensity` 一个 kind 占 **1501** 条，
#: 是门⑨ 红的**单一最大成因**。v14 把正文、禁写键名单与示例一并改成与 schema 同口径，
#: 并新增一条对抗性回归：**提示里的 JSON 示例本身必须是一条合格条目**
#: （逐条校验 ＋ 词表校验 ＋ `q` 覆盖校验三重）。改动提示文本 ⇒ 必须换版本号，
#: 否则上一轮按 v13 写出的 partial 会被指纹当成同一批续跑。
PROMPT_VERSION = "holdout/v14"
REVIEW_BATCH = 1

SYSTEM_PROMPT = """你是分镜知识库的**独立标注员**。你会看到若干条知识卡（语料）与一份冻结的\
超边 schema ＋ 取值词表。你的工作是：**为每张卡写出 4 条不同的检索期望**，用来检验一个超图\
检索器是否真能召回该卡所表达的知识。第 1 条抓这张卡最核心的那条约束；第 2／3／4 条各换一组\
查询键或取值，并**尽量落到不同的边类型上**（v1.5 后边有 13 类，同一张卡往往能从不同\
类型各考一次：比如一张打斗卡可以同时考 `ACTION_BEAT`／`IMPACT_PACK`／`SOUND_PACK`）。\
不要同义重复。每张卡都必须有 4 条。

只输出 JSON：{"entries":[{...}, ...]}，每条：
{
 "from_card": "<卡片 id>",
 "q": "键=值；键=值",                     // 查询串，键取自下面允许的键集
 "must": ["TYPE:槽位=取值,槽位=取值"],      // 1–3 条，必须能从这个查询检出
 "top1": ["与 must 中某条完全相同"],        // 期望排第一的那条
 "never": ["TYPE:槽位=取值"],              // 不该被召回（可为 []），与 must 不相交
 "expect_movements": ["运镜名"]             // 可缺省；这条查询下作者期望的运镜
}

规则（违反的条目会被机器拒绝）：
0. **`q` 必须真能把 `must` 那条边查出来**——`must` 里**每个能写进 `q` 的槽位**都要在
   `q` 里出现，取值逐字相同（没有查询键的槽位如 `headroom_policy`／`pair`／`axis_side`
   不写）。例：`SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board` → `q` 要同时写
   `景别=MS` 与 `镜头=50mm`；`AXIS_RULE:…,axis_topic=越轴` → `q` 写 `轴线=越轴`。
   **实测**：查询覆盖到目标边 ≥2 个成员时 Q1=0.727／Q2=0.917（都过验收线），只覆盖 1 个时
   0.508／0.754，覆盖 0 个则根本召不回。
1. `q` 的键**只能**取协议 §2.1 的这 __QKEY_COUNT__ 个：__QKEY_LIST__。
   **不得自造键**——`tools/check_holdout.py::parse_q` 对冻结键集之外的键**直接抛错**，
   整条作废（实测 `轴线侧`／`轴侧`／`景深`／`标签`／`关键词`／`结构` 都是自造键）。
   反过来，冻结键**不必全用**：一条查询用得上几个就写几个（多写无关键只会稀释查询）。
   哪些槽位**没有**查询键？只有 `headroom_policy`／`avg_shot_len`／`pair`／`axis_side`
   这四个 schema 常量，它们不出现在 `q` 里。
   **`intensity` 不在这个名单里**：v1.5 起它有查询键 `强度`，而 `must` 里的
   `intensity=<取值>` 是「能写进 `q` 的槽位」——不写 `强度=<同一个取值>`，
   这条查询就**召不回它自己的 `must`**（产出侧 `query_shortfall()` 整条拒收；
   实测上一代 oracle 因此有 2449/4539 = 54.0% 的条目在数学上不可达）。
   边里写了哪个可查询槽位，`q` 里就要有对应键与逐字相同的取值。
**`type` 只允许这 13 个字符串**：`EMOTION_PACK`、`SHOT_PATTERN`、`AXIS_RULE`、`TROPE`、
`EDIT_RHYTHM`、`LIGHT_PACK`、`ACTION_BEAT`、`PERFORMANCE_PACK`、`INTENT_PACK`、
`IMPACT_PACK`、`STAGING_PACK`、`SOUND_PACK`、`TRANSITION_PACK`、`DIALOGUE_PACK`、
`MUSIC_PACK`、`PROP_PACK`。写别的（`ACTION`／
`SFX`／`MOVEMENT`／`COMPOSITION`／`SHAKE`…）**整条作废**。

2. `must` 的边类型只能取下面每一类；**照下面模板逐字写全**（`<…>` 换成词表取值，
   逗号分隔，一项都不能少）：
   * `EMOTION_PACK:emotion=<情绪>,intensity=<low|mid|high>`（要写禁忌时再加
     `,forbid_<kind>=<该 kind 的取值>`）
   * `SHOT_PATTERN:shot_size=<ECU|CU|MCU|MS|MLS|LS|ELS>,lens=<24mm|35mm|50mm|85mm>,headroom_policy=<board|cinematic>`
   * `AXIS_RULE:pair=any_two,axis_side=<left|right|neutral>,axis_topic=<轴线>` ——
     **`axis_topic` 必须写**：`pair`／`axis_side` 是 schema 常量，在查询空间里
     没有对应取值，只写它们的话这条边**一个种子都挂不上**（实测 263 条里只有
     16 条能命中索引）。`q` 里对应写 `轴线=<同一个取值>`。
   * `TROPE:genre=<film|anime|documentary>,emotion=<情绪>`
   * `EDIT_RHYTHM:pacing=<short|medium|long>,avg_shot_len=<时长档>`，其中
     `<时长档>` 只能取这四个**字符串**之一（逐字照抄，**别加引号**）：
     `<1s`、`1-3s`、`3-8s`、`>8s`。
     **注意**：第一个档位本身就是 `<1s` —— **一个**小于号后面直接跟 `1s`。
     把它写成两个小于号开头，会被机器当成词表外的取值整条拒收
     （实测 35 条 `must` 因此解析不到索引边）。
   * `LIGHT_PACK:lighting=<光线>,intensity=<low|mid|high>`
   * `ACTION_BEAT:action=<动作>,beat_type=<establish|coverage|reaction|insert|transition>,intensity=<low|mid|high>`
   * `PERFORMANCE_PACK:emotion=<情绪>,action=<动作>,camera_angle=<低机位|平视|荷兰角|过肩|骑轴|高机位>`
   * `INTENT_PACK:intent=<意图>,shot_size=<景别>,movement=<运镜>`
   * `IMPACT_PACK:vfx=<特效>,sfx=<音效>,movement=<运镜>`
   * `STAGING_PACK:composition_rule=<构图>,shot_size=<景别>,camera_angle=<机位>`
   * `SOUND_PACK:sfx=<音效>,pacing=<short|medium|long>,intensity=<low|mid|high>`
   * `TRANSITION_PACK:transition=<cut|dissolve|fade|whip>,pacing=<short|medium|long>,scene_type=<establish|dialogue|action|reaction|transition|insert>`
   * `DIALOGUE_PACK:delivery=<对白交付方式>,pacing=<short|medium|long>,intensity=<low|mid|high>`
   * `MUSIC_PACK:music=<配乐/环境声策略>,pacing=<short|medium|long>,intensity=<low|mid|high>`
   * `PROP_PACK:prop=<道具/环境元素>,shot_size=<景别>,camera_angle=<机位>`
   `top1` 一律把 `must` 的**第 1 条原样复制**过来（不要改写、不要只写前半段）。
2b. **只有上面那 16 个类型名**。不要发明 `COMPOSITION`／`SHAKE`／`SOUND` 之类的
   新类型——机器会以 `bad_type` 整条拒收。
2c. **构图/机位/特效/音效/动作类知识挂到最接近的那一类边上，作为额外槽位**
   （必填槽位照旧写全）：
   * 构图（均衡/三分/留白/引导空间/遮挡）→ `SHOT_PATTERN` ＋ `composition_rule=<词表取值>`；
   * 机位（高低/荷兰角/过肩/骑轴）→ 就近那类 ＋ `camera_angle=<词表取值>`；
   * 特效/音效 → 就近那类 ＋ `vfx=`／`sfx=<词表取值>`；
   * 动作 → 就近那类 ＋ `action=<词表取值>`；
   * 适用题材/景别 → `applies_to_genre=`／`applies_to_shot_size=<词表取值>`。
   **卡片属于哪个 domain 与边类型无关**：`domain=composition` 的卡也要写成这六类之一。
3. 槽位名 = kind；禁忌槽位写成 `forbid_<kind>=取值`。取值尽量用词表里的规范名。
3b. 取值**必须**是词表里的那一个（闭集，逐字相同）：`q` 里和 `must` 里都一样。
    写了词表外的说法会被机器判成 `unknown_values`——那**整条作废**，不是警告。
3c. **不许把卡片原文的说法抄进取值**。`q` 的每个 `<值>` 都要从下面词表里**逐字挑一个**
    （哪怕卡片说的是"垂直破坏画面统一"，也只能挑词表里最接近的 `构图` 取值，例如
    `rule_of_thirds`／`balance`／`framing`／`headroom`／`lead_room`／`occlusion`）。
    同一 kind 的取值在 `q` 与 `must` 里必须**完全同一串字符**。
3d. **写法顺序**：先想好这条边的 `must`，再把 `q` 里同 kind 的取值**从 `must` 里复制**过来
    ——不要分别想两遍。`q` 里每个键**只写一次**。例：
    `must:["SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board,composition_rule=rule_of_thirds"]`
    对应的 `q` 只能是 `"构图=rule_of_thirds；景别=MS"`（取值与 must 逐字相同，且 `构图` 只出现一次）。
4. `must` 最多 3 条（上限是硬的：top-3 内 100% 可检出要求 |must| ≤ 3）。
5. `top1` 必须与 `must` 里的某一条**一字不差**。
6. 期待排序靠前的边应当是"这张卡最核心的那条约束"；把"调用方必须避开的东西"
   写成 `forbid_*` 槽位（例如查询里出现"运镜=固定"时，若卡里说这个情绪忌讳固定机位，
   就写 `forbid_movement=固定`）——这类条目是禁忌拦截率的判据。
7. **禁忌槽位只出现在 EMOTION_PACK 上**（§2.3 的边表：只有它有 `forbid` 成员）；
   其它五类写 `forbid_` 会被判成不可召回。
8. **q 与 must 必须自洽**：`q` 里出现的 kind，只要 `must` 里有同类槽位，
    取值就必须与 `q` **逐字相同**（校验器会逐条对拍）。
8b. **`q` 里同一个键只能出现一次**（写两遍 `节奏=…` 会被判红）；同一个 kind 在
    `q` 与 `must` 里必须用**同一个取值**，不许一个写中文、一个写英文代号。
9. 词表里的**每个取值都必须至少出现在一条 `q` 里**（覆盖门③）；
   因此请在多个条目之间轮换取值，不要反复只用同一个词。

**输出前逐条自检（这四类错误占实测拒收的绝大多数，务必先自查再输出）**：
* 每条 `must` 的**必填槽位是否写全**？（SHOT_PATTERN 必须同时有 shot_size ＋ lens ＋
  headroom_policy —— 少 headroom_policy 是最常见的一种。）
* `top1` 是否与 `must` 里的某一条**逐字相同**（复制粘贴，不要改写、不要只写一部分）？
* `never` 与 `must` 是否**有交集**？（有交集整条作废。）
* `q` 里同一个键是否只出现一次？`q` 的取值与 `must` 里同 kind 的取值是否逐字相同？

**示例（照这个形状写，别只写个 `TYPE:` 占位符）**：
```json
{"entries": [
  {"from_card": "gen_cine_0001",
   "q": "情绪=荒诞；强度=high；运镜=固定",
   "must": ["EMOTION_PACK:emotion=荒诞,intensity=high,forbid_movement=固定"],
   "top1": ["EMOTION_PACK:emotion=荒诞,intensity=high,forbid_movement=固定"],
   "never": ["SHOT_PATTERN:shot_size=ELS,lens=24mm,headroom_policy=board"],
   "expect_movements": ["甩镜"]}
]}
```
注意示例里：`q` 用的是**中文键**；`must` 里写的是**真实的边类型名**
（__EDGE_TYPES__），
不是字面量 `TYPE`；`forbid_movement` 的取值与 `q` 的 `运镜=` **一模一样**；
`intensity=high` 出现在 `must` 里，所以 `q` 里**必须**有 `强度=high`
（少了它这条查询就召不回自己的 `must`）。
**这个示例本身是一条合格条目**：它同时过逐条校验、词表校验与「`q` 覆盖 `must` 可写槽位」
校验（`tests/test_knowledge_holdout.py::test_holdout_prompt_example_is_a_citable_entry`）。
示例里的每个取值也都在词表里——**照抄示例不会产出废条**。
"""

#: 提示里的**键集与类型清单一律从 schema 渲染**，不得手抄：手抄的那份曾经多出
#: `强度`／`头留白`／`平均镜长` 三个协议里并不存在的查询键，而
#: `tools/check_holdout.py::parse_q` 对冻结键集之外的键直接抛错——**每一条**用到它们
#: 的期望都会被整条拒收。渲染之后，"契约变、提示跟着变"由机器保证。
SYSTEM_PROMPT = (SYSTEM_PROMPT
                 .replace("__QKEY_COUNT__", str(len(Q_KEY_TO_KIND)))
                 .replace("__QKEY_LIST__", query_key_text())
                 .replace("__EDGE_TYPES__", "／".join(hg.EDGE_TYPES)))


def cards_fingerprint(cards: Sequence[Dict]) -> str:
    payload = "".join(sorted(str(c.get("id", "")) + hashlib.sha256(
        str(c.get("content", "")).encode("utf-8")).hexdigest() for c in cards))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_prompt(cards: Sequence[Dict], vocab: Dict[str, List[str]]) -> str:
    # 词表按 kind 打印时，**必须同时给出对应的中文查询键**：只印英文 kind 名，
    # 模型会把 `q` 写成 `emotion=...；pacing=...`（实测 qwen2.5:7b 就是这样），
    # 而协议冻结的 `q` 键只有中文那一套，于是整批被格式门拒收。
    from tools.check_holdout import Q_KEY_TO_KIND

    zh_of: Dict[str, str] = {}
    for key, kind in Q_KEY_TO_KIND.items():
        zh_of.setdefault(kind, key)
    lines = ["【冻结的取值词表】（`q` 的键用括号里的中文键；取值用这里的规范名）"]
    for kind, values in sorted(vocab.items()):
        key = zh_of.get(kind)
        head = f"{key}/{kind}" if key else f"{kind}（仅用于 must 槽位）"
        lines.append(f"- {head}: " + ", ".join(values[:60]))
    lines.append("\n【知识卡】")
    for card in cards:
        lines.append(f"### {card['id']}（domain={card['domain']}）\n"
                     f"标题：{card['title']}\n内容：{card['content']}\n"
                     f"标签：{'、'.join(card.get('tags', []))}\n"
                     f"关键词：{'、'.join(card.get('keywords', []))}")
    return "\n".join(lines)


_SPEC_RE = re.compile(r"^(?P<etype>[A-Z_]+):(?P<slots>.+)$")
_SLOT_RE = re.compile(r"^(?P<forbid>forbid_)?(?P<kind>[a-z_]+)=(?P<value>.+)$")


def validate_entry(raw: Dict, card_ids: set) -> Tuple[Optional[Dict], str]:
    from tools.check_holdout import (ALLOWED_KINDS, EDGE_TYPES, REQUIRED_SLOTS,
                                     illegal_members)

    if not isinstance(raw, dict):
        return None, "entry_not_object"
    card = str(raw.get("from_card", "")).strip()
    if card not in card_ids:
        return None, f"unknown_from_card:{card}"
    q = str(raw.get("q", "")).strip()
    if "=" not in q:
        return None, "empty_q"
    must = raw.get("must")
    if not isinstance(must, list) or not 1 <= len(must) <= 3:
        return None, "must_size"
    top1 = raw.get("top1")
    if not isinstance(top1, list) or not top1 or not set(top1) <= set(must):
        return None, "top1_not_subset"
    never = raw.get("never") or []
    if not isinstance(never, list) or set(never) & set(must):
        return None, "never_overlaps_must"
    for spec in list(must) + list(never):
        match = _SPEC_RE.match(str(spec).strip())
        if not match:
            return None, f"bad_spec:{spec}"
        etype = match.group("etype")
        if etype not in EDGE_TYPES:
            return None, f"bad_type:{etype}"
        seen = set()
        plain_seen = set()
        forbid_seen = set()
        for slot in match.group("slots").split(","):
            slot = slot.strip()
            if not slot:
                continue
            sm = _SLOT_RE.match(slot)
            if not sm or sm.group("kind") not in ALLOWED_KINDS:
                return None, f"bad_slot:{slot}"
            seen.add(sm.group("kind"))
            (forbid_seen if sm.group("forbid") else plain_seen).add(sm.group("kind"))
        # 角色合法性走**校验器的同一份**实现：`forbid_<kind>` 只能挂在 schema 允许
        # 它的边类型上。产出侧原先不查这一条，于是 `forbid_lighting` 这类
        # "索引里不可能存在"的边照样落盘（上一代 oracle 实测 243 个）。
        illegal = illegal_members(etype, plain_seen, forbid_seen)
        if illegal:
            return None, f"illegal_slot:{etype}:{illegal}"
        missing = [s for s in REQUIRED_SLOTS[etype] if s not in seen]
        if missing:
            return None, f"missing_slots:{etype}:{missing}"
    entry = {"from_card": card, "q": q, "must": [str(s) for s in must],
             "top1": [str(s) for s in top1], "never": [str(s) for s in never]}
    movements = raw.get("expect_movements")
    if isinstance(movements, list) and movements:
        entry["expect_movements"] = [str(m) for m in movements]
    return entry, ""


def run(cards: Sequence[Dict], vocab: Dict[str, List[str]], client,
        batch_size: int = 8, limit: int = 0, target: int = 0) -> Tuple[List[Dict], List[Dict]]:
    card_ids = {str(c["id"]) for c in cards}
    prompt_sha = hashlib.sha256((SYSTEM_PROMPT + PROMPT_VERSION).encode("utf-8")).hexdigest()
    annotator = {"model_id": client.model_id, "family": client.family,
                 "model_version": client.model_version, "prompt_sha256": prompt_sha}
    annotation = {"model_id": client.model_id, "model_version": client.model_version,
                  "family": client.family, "prompt_sha256": prompt_sha}

    batches = [list(cards[i:i + batch_size]) for i in range(0, len(cards), batch_size)]
    if limit:
        batches = batches[:limit]

    entries: List[Dict] = []
    rejects: List[Dict] = []
    counter = 0
    for index, batch in enumerate(batches, 1):
        try:
            reply = client.chat_json(SYSTEM_PROMPT, build_prompt(batch, vocab), 0.0, 0, 8192,
                                     key=batch[0]["id"])
        except Exception as exc:  # noqa: BLE001 - 记因由而不是静默跳过
            rejects.append({"batch": index, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        raw_entries = reply.get("entries") if isinstance(reply, dict) else None
        if not isinstance(raw_entries, list):
            rejects.append({"batch": index, "reason": "reply_not_a_list"})
            continue
        for raw in raw_entries:
            entry, reason = validate_entry(raw, card_ids)
            if entry is None:
                rejects.append({"batch": index, "reason": reason,
                                "raw": str(raw)[:200]})
                continue
            counter += 1
            entries.append({"id": f"hq_{counter:04d}", **entry,
                            "annotator": annotation,
                            "independence": "strong", "pilot": False})
        if target and counter >= target:
            break

    sweep_rejects: List[Dict] = []
    if not limit and not target:
        extra, sweep_rejects = sweep_unused(entries, cards, vocab, client, counter)
        entries.extend(extra)

    common.write_jsonl(HOLDOUT, entries)
    common.dump_json(CARDS_JSON, sorted(card_ids))
    rejects = rejects + sweep_rejects
    common.dump_json(MANIFEST, {
        "fingerprint": hashlib.sha256(
            (cards_fingerprint(cards) + client.model_id + PROMPT_VERSION)
            .encode("utf-8")).hexdigest(),
        "cards_fingerprint": cards_fingerprint(cards),
        "annotator": annotator,
        "prompt_version": PROMPT_VERSION,
        "entries": len(entries),
        "rejects": len(rejects),
        "cards": len(cards),
    })
    return entries, rejects


SWEEP_PROMPT = """你是分镜知识库的独立标注员。下面的**取值**还没有被任何查询用到，\
而覆盖门要求词表里每个取值至少出现在一条查询里。

请为**每一个**取值写一条使用它的检索期望（一次输出多条）。只输出 JSON：
{"entries":[{"from_card":"<卡片 id>","q":"键=值；键=值","must":[...],"top1":[...],"never":[...]}]}

键与槽位的规则与之前完全一致：`must` 的边必须写全必填槽位，`top1` 必须与 `must` 里
某条一字不差，`|must| ≤ 3`，`never` 与 `must` 不相交。取值请用词表里的规范名。
"""


def sweep_unused(entries: List[Dict], cards: Sequence[Dict],
                 vocab: Dict[str, List[str]], client, counter_start: int,
                 batch: int = 12) -> Tuple[List[Dict], List[Dict]]:
    """把词表里"一次都没被 q 用到"的取值补成查询（门③ 的双向要求）。"""
    from tools.check_holdout import Q_KEY_TO_KIND

    kind_by_key = Q_KEY_TO_KIND
    used: Dict[str, set] = {}
    for entry in entries:
        for chunk in re.split(r"[；;]", entry["q"]):
            if "=" not in chunk:
                continue
            key, _, value = chunk.partition("=")
            kind = kind_by_key.get(key.strip())
            if kind:
                used.setdefault(kind, set()).add(value.strip())
    missing = [(kind, value) for kind, values in vocab.items()
               for value in values if value not in used.get(kind, set())]
    if not missing:
        return [], []

    card_ids = sorted({str(c["id"]) for c in cards})
    extra: List[Dict] = []
    rejects: List[Dict] = []
    counter = counter_start
    for start in range(0, len(missing), batch):
        group = missing[start:start + batch]
        sample = [str(c["id"]) + "｜" + str(c["content"])[:120]
                  for c in cards if str(c["id"]) in set(card_ids[:40])]
        lines = ["【需要覆盖的取值】"] + [f"- {kind}={value}" for kind, value in group]
        lines += ["", "【可用卡片片段】"] + sample[:20]
        try:
            reply = client.chat_json(SWEEP_PROMPT, "\n".join(lines), 0.0, 0, 8192,
                                     key="sweep:" + ",".join(f"{k}={v}" for k, v in group))
        except Exception as exc:  # noqa: BLE001
            rejects.append({"sweep": str(group), "reason": f"{type(exc).__name__}: {exc}"})
            continue
        raw_entries = reply.get("entries") if isinstance(reply, dict) else None
        if not isinstance(raw_entries, list):
            rejects.append({"sweep": str(group), "reason": "reply_not_a_list"})
            continue
        for raw in raw_entries:
            entry, reason = validate_entry(raw, set(card_ids))
            if entry is None:
                rejects.append({"sweep": str(group), "reason": reason})
                continue
            counter += 1
            extra.append({"id": f"hq_{counter:04d}", **entry,
                          "annotator": {"model_id": client.model_id,
                                        "family": client.family,
                                        "model_version": client.model_version},
                          "independence": "strong", "pilot": False})
    return extra, rejects


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.holdout_gen")
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model", default="")
    parser.add_argument("--scripted", default="")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--target", type=int, default=0, help="达到该条数即停（0 = 全跑）")
    parser.add_argument("--cards", default="", help="卡片 JSONL 路径（默认用运行时 CARDS）")
    parser.add_argument("--out", default="", help="输出路径（默认 fixtures/knowledge_holdout.jsonl）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.out:
        global HOLDOUT, CARDS_JSON
        HOLDOUT = pathlib.Path(args.out)
        CARDS_JSON = HOLDOUT.with_suffix(".cards.json")

    vocab_path = common.KNOWLEDGE / "hypergraph.vocab.json"
    if not vocab_path.exists():
        print(json.dumps({"error": "先跑 tools.kb_fetch.vocabulary"}, ensure_ascii=False))
        return 1
    payload = json.loads(vocab_path.read_text(encoding="utf-8"))
    # 只能用 14 个查询 kind 的子集：门③ 会遍历词表的**每一个** kind，
    # 把 qualifier 类（intensity/pair/…）也塞进去会被判成"取值从没被用到"。
    vocab = payload["holdout_vocab"]

    if args.cards:
        cards = [json.loads(line) for line in
                 pathlib.Path(args.cards).read_text(encoding="utf-8").split("\n") if line.strip()]
    else:
        from block_director.knowledge.corpus import CARDS
        cards = [{"id": c.id, "domain": c.domain, "title": c.title, "content": c.content,
                  "tags": list(c.tags), "keywords": list(c.keywords),
                  "emotion": c.emotion} for c in CARDS]

    client = llm.make_client(args.provider, args.model, args.scripted)
    entries, rejects = run(cards, vocab, client, args.batch_size, args.limit, args.target)
    print(json.dumps({"entries": len(entries), "rejects": len(rejects),
                      "rejects_detail": rejects[:5]}, ensure_ascii=False))
    return 0 if entries else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
