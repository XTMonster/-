"""第 1 段抽取结果的**缓存／断点续跑**（§2.3），以及 manifest 的 per-chunk 账。

为什么要有这个模块（2026-10-02 实测，`ACCEPTANCE_STATUS.md` §28.1）：
`build_hypergraph` 原先**没有原子边缓存**，正常构建路径每次都对全部 chunk 重新调
一遍模型；而抽取器**不可复现**（`temperature=0` 不等于逐字可复现）。于是"同一份
语料、同一份代码，连建两次必须一样"这条判据实测失败：

    run1  sha256 8c41fb3f…  edges 662  atoms 2527
    run2  sha256 345234ba…  edges 667  atoms 2484

门⑥ 的覆盖率因此量的是"这一轮抽样运气如何"，而不是"这份语料能不能表达"。

判据出处是执行文档，不是本模块自定：

* `改进执行文档v1.4.md:1704`：**"缓存命中时（不重抽取）索引文件逐字节一致"**
  ——这才是可判定的回归基线；
* `改进执行文档v1.4.md:903`：manifest 顶层存 `fingerprint` 与
  `chunks:[{chunk_id, sha256, status, edges, reject_reason, extractor_fingerprint}]`；
  "**先比顶层 fingerprint，不等则整体重抽**"这条规则的目的是"改了 prompt/schema 不许
  复用旧边"。本实现把这道判据**下沉到抽取单元上**（见下），因此比六元指纹**更细**，
  同时也保住了 §6 的另一条要求——"门改了只需重跑门，不必重抽"（校验门版本在六元
  指纹里、不在单元键里）。
* `改进执行文档v1.4.md:918`：第 1 段（抽取）与第 2 段（归并＋门）分开落盘，
  "门改了只需重跑门，不必重抽"——所以缓存存的是**模型的原样回复**，
  判读（`to_edge` 那一层）每轮照旧重跑，改判据不必重抽。

三条不变量：

1. 缓存键只由**抽取的输入**决定（渲染后的整段提示 ＋ 模型 ＋ 温度 ＋ 解码行），
   所以提示 / 词表 / 节点表 / 卡片正文任一变化都会换键——不靠谁记得去升版本号；
2. 只缓存**成功**（`status == "done"`）：传输失败不进缓存，下次仍然真调模型；
3. 缓存文件写 `work/`（不入库、不进指纹），且按 key 稳定排序——否则"逐字节一致"
   会被缓存文件自己的顺序破坏。
4. 条目记着"写它的时候 manifest 的指纹"（`fingerprint`），那是**审计**用的：
   指纹变了而单元键没变（例如只改了校验门）时，缓存照样命中——那正是"门改了不必
   重抽"要做的事；反过来单元键变了（提示、词表、节点表、卡片正文、模型、温度、
   解码行任一变化）就一定未命中。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: 缓存条目格式的版本。它**不**进六元指纹（进指纹会让"改缓存实现"变成"换语料"），
#: 而是写进每一个条目；版本不符的条目直接作废、重抽。
CACHE_VERSION = "atom-cache/v1"


def digest(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def prompt_digest(system: str, user: str) -> str:
    """渲染后的整段提示的哈希（system ＋ 分隔符 ＋ user）。

    分隔符用 `\\x00`：它是正文里不可能出现的字符，所以 `("ab", "c")` 与
    `("a", "bc")` 不会撞成同一个键。
    """
    return digest(f"{system}\x00{user}")


def unit_key(*, prompt_sha256: str, model: str, temperature: float,
             prompt_version: str, decode: str) -> str:
    """一个抽取单元（一批卡）的缓存键。

    `prompt_sha256` 是**渲染后的整段提示**的哈希，因此它已经把提示模板版本、词表、
    节点表、以及这一批卡片的正文全部含进去了——这正是"改任何输入就换键"的机械保证。
    剩下的四项是提示里**看不见**的调用参数。
    """
    payload = json.dumps({
        "cache_version": CACHE_VERSION,
        "prompt_sha256": str(prompt_sha256),
        "model": str(model),
        #: `repr(float(...))` 而不是 `str(...)`：`0` 与 `0.0` 必须算出同一个键，
        #: 否则"主轮 0.0 / 补抽 0.2"这种调用会因为数值类型不同而假性未命中。
        "temperature": repr(float(temperature)),
        "prompt_version": str(prompt_version),
        "decode": str(decode),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AtomCache:
    """`work/hypergraph.atom_cache.jsonl` 的读写与命中统计。

    **命中判据是单元键，不是顶层指纹**：单元键由「渲染后的提示（含这一批卡片的正文、
    词表、节点表、提示版本）＋ 模型 ＋ 温度 ＋ 解码行」算出来，所以"改了 prompt"或
    "改了语料"照样换键、照样重抽；而六元指纹里那些**不影响原样回复**的分量（校验门
    版本、别的 chunk 的正文）不会白白让整库重抽——§6 的原话就是"门改了只需重跑门，
    不必重抽"。条目里的 `fingerprint` 是**审计**信息（这份回复是在哪一枚指纹下拿到的），
    不是开关。
    """

    def __init__(self, path: pathlib.Path, fingerprint: str, *, enabled: bool = True):
        self.path = pathlib.Path(path)
        self.fingerprint = str(fingerprint)
        self.enabled = bool(enabled)
        self.entries: Dict[str, Dict] = {}
        self.stats = {"hit": 0, "miss": 0, "written": 0, "dropped_version": 0,
                      "enabled": self.enabled}
        if not self.enabled or not self.path.is_file():
            return
        for line in self.path.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get("cache_version")) != CACHE_VERSION:
                self.stats["dropped_version"] += 1
                continue
            key = str(row.get("key") or "")
            if key:
                self.entries[key] = row

    def key_for(self, system: str, user: str, *, model: str, temperature: float,
                prompt_version: str, decode: str) -> str:
        return unit_key(prompt_sha256=prompt_digest(system, user), model=model,
                        temperature=temperature, prompt_version=prompt_version,
                        decode=decode)

    def get(self, key: str) -> Optional[Dict]:
        """只有"抽成功过"的单元才算命中；失败不进缓存，下次仍然真调模型。"""
        if not self.enabled:
            return None
        row = self.entries.get(str(key))
        if not row or str(row.get("status")) != "done":
            self.stats["miss"] += 1
            return None
        self.stats["hit"] += 1
        return row

    def put(self, key: str, row: Dict) -> None:
        self.stats["written"] += 1
        self.entries[str(key)] = {"cache_version": CACHE_VERSION, "key": str(key), **row}

    def save(self) -> None:
        """稳定顺序落盘（按 key 排序）＋ 原子替换：缓存文件自己也不许抖。

        指纹在**落盘时**才盖章：抽取跑完才知道服务端报的模型版本（`model_version`
        是第一次回复之后才定下来的），而 manifest 的指纹必须是那个"事后"的值——
        否则 manifest 会同时写着两枚模型事实（`cache_key.model` 与 `extractor`），
        那正是"同一事实两个真源"（`tests/test_hypergraph_determinism.py` 当场对拍）。
        """
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(
            json.dumps({**self.entries[key], "fingerprint": self.fingerprint},
                       ensure_ascii=False, sort_keys=True) + "\n"
            for key in sorted(self.entries))
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.path)


def chunk_sha256(cards: Sequence[Dict]) -> str:
    """一个 chunk 的正文指纹：`(卡 id, 正文 sha256)` 排序后再哈希。"""
    rows = sorted([str(card.get("id", "")),
                   digest(str(card.get("content", "")))] for card in cards)
    return digest(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))


def chunk_id_of(card: Dict) -> str:
    span = card.get("source_span") or {}
    return str(span.get("chunk_id") or card.get("chunk_id") or card.get("id", ""))


def chunk_ledger(cards: Sequence[Dict], units: Iterable[Dict],
                 atoms: Sequence) -> List[Dict]:
    """§2.3 的 per-chunk manifest：`chunks:[{chunk_id, sha256, status, edges,
    reject_reason, extractor_fingerprint}]`。

    抽取单元是**批次**（一个批次只放同一个 domain 的卡，可能跨 chunk），所以这里把
    "批次"投影到"chunk"上：一个 chunk 可能被多个批次覆盖（并发 / 补抽轮），只要
    **有一个**批次成功，它的 `status` 就是 `done`；`extractor_fingerprint` 是该 chunk
    所有覆盖批次键的哈希——任何一个覆盖它的批次换了输入，这一格就会动。
    """
    by_id = {str(card["id"]): card for card in cards}
    chunk_cards: Dict[str, List[Dict]] = {}
    for card in cards:
        chunk_cards.setdefault(chunk_id_of(card), []).append(card)

    status: Dict[str, str] = {}
    reasons: Dict[str, List[str]] = {}
    keys: Dict[str, List[str]] = {}
    for unit in units:
        unit_status = str(unit.get("status") or "")
        unit_key_ = str(unit.get("key") or "")
        covered = set()
        for card_id in unit.get("cards") or ():
            card = by_id.get(str(card_id))
            if card is not None:
                covered.add(chunk_id_of(card))
        for chunk_id in covered:
            keys.setdefault(chunk_id, []).append(unit_key_)
            if unit_status == "done":
                status[chunk_id] = "done"
            else:
                status.setdefault(chunk_id, "error")
                if unit.get("reject_reason"):
                    reasons.setdefault(chunk_id, []).append(str(unit["reject_reason"]))

    edges: Dict[str, List[str]] = {}
    for edge in atoms:
        edge_id = str(getattr(edge, "edge_id", ""))
        for source in (getattr(edge, "sources", ()) or ()):
            card = by_id.get(str(source))
            if card is not None:
                edges.setdefault(chunk_id_of(card), []).append(edge_id)

    ledger: List[Dict] = []
    for chunk_id in sorted(chunk_cards):
        ledger.append({
            "chunk_id": chunk_id,
            "sha256": chunk_sha256(chunk_cards[chunk_id]),
            "status": status.get(chunk_id, "pending"),
            "edges": sorted(set(edges.get(chunk_id) or [])),
            "reject_reason": "; ".join(sorted(set(reasons.get(chunk_id) or []))) or None,
            "extractor_fingerprint": digest(json.dumps(
                sorted(set(keys.get(chunk_id) or [])), ensure_ascii=False,
                separators=(",", ":"))),
        })
    return ledger


def resume_plan(ledger: Sequence[Dict],
                current: Sequence[Dict]) -> Tuple[List[str], List[str]]:
    """§2.3 的续跑规则：返回 `(可跳过的 chunk_id, 必须重抽的 chunk_id)`。

    "相等才按 chunk sha256 跳过 `done`"——**两个条件都要**：账里 `status == "done"`，
    且这个 chunk 现在的 `sha256` 与账里记的一致。（顶层指纹的比较在 `AtomCache`
    构造时已经做过：指纹不等则整份缓存为空，于是这里一个都跳不过。）
    """
    known = {str(row["chunk_id"]): str(row["sha256"]) for row in ledger}
    skip: List[str] = []
    redo: List[str] = []
    for row in current:
        chunk_id = str(row["chunk_id"])
        if row.get("status") == "done" and known.get(chunk_id) == str(row["sha256"]):
            skip.append(chunk_id)
        else:
            redo.append(chunk_id)
    return skip, redo
