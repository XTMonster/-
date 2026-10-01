"""`action` 的受控词表：从卡片标签里筛出**看得见的身体行为**（P14，审计 #16）。

## 为什么需要它

`action` 是 `ACTION_BEAT`／`PERFORMANCE_PACK` 的**必填**槽位。旧实现
（`tools/kb_fetch/vocabulary.py` 第 4 步）为了"让必填槽位有的可填"，把
performance／blocking 域卡片里**长度 ≤6 的 tag 全部**铺成 `action` 节点——
而 tag 是卡片生成模型写的**话题词**。实测后果：

```
action 节点 343 个，其中只有 7 个来自受控表
837 条边里 258 条（30.8%）带一个不是动作的 action 取值
  ACTION_BEAT 131 条（占该类的 69%）、PERFORMANCE_PACK 127 条
取值榜：动作×41、反应×27、出场×24、克制×15、准备×14、人物塑造×12 …
```

`action=动作` 这种边"既召不回任何真实查询，还会把这一类边整体稀释"
（`build_hypergraph.py` 规则 8b 的原话）。抽取提示早就写了"不能写概念/技法/
流程/职务"，但**节点表把话题词当成了合法取值**，模型自然照抄。

## 这份词表怎么来的（可复核，不是手写）

1. 候选 = 旧规则会铺成 `action` 的那些 tag（与审计 #16 的清单同源）；
2. 判据 = "演员／角色在镜头前**看得见、能表演出来**的身体行为"，由抽取族模型
   （DeepSeek）按同一条判据逐词判定，**每个词记下理由**；
3. 结果**钉进仓库**（`knowledge/action_lexicon.json`）并带上模型与提示指纹——
   词表是确定的、可审计的，重建语料时不会偷偷漂移。

没有这份文件时，`build_nodes` 回落到**受控表 `ACTIONS` 本身**
（`tools/kb_fetch/vocabulary.py`），而不是回落到那条污染规则。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Dict, Iterable, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch.vocabulary import ACTIONS  # noqa: E402

#: 钉进仓库的位置（与 `hypergraph.vocab.json` 同目录，便于一起备份／回滚）。
DEFAULT_OUT = "knowledge/action_lexicon.json"

#: 判据。**必须写得能让另一个模型复核**：正面例子给"动作短语"，反面例子按
#: 审计 #16 实际出现的污染类别各给一个。
SYSTEM = (
    "你是电影分镜知识库的**词表审查员**。给你一批中文词，每个词的来源是"
    "表演／场面调度类知识卡片的标签。你要判断：这个词是不是**演员／角色在镜头前"
    "看得见、能表演出来的身体行为**。\n"
    "算的（accepted）：单个动作或动作短语，导演可以在片场喊出来——转身、推门、"
    "坐下、挥手、低头、后退、出场、走位、拥抱、擦杯子；**也包括可表演的反应类**"
    "——反应、表情、注视、回头、点头、摇头（反应镜头是剪辑的基本材料）。\n"
    "不算的（rejected）：概念／技法／职务／流程／心理状态／抽象名词／场景名词／"
    "镜头术语／器械装置——人物弧光、舞台调度、观众心理、美术考据、动作设计、"
    "分镜流程、台词处理、创作观、情绪妆、景别、轴线、表演体系、吊杆、灯具。\n"
    "**自身就是类别词的也要 rejected**：`动作`、`运动`、`行为`、`表演`、`动作组`"
    "——查询写成 `动作=动作` 没有任何信息量，等于把这一类边整体稀释。\n"
    "**拿不准就 rejected**：这类词会进检索查询，宁缺勿滥。\n"
    "只输出 JSON：{\"decisions\":[{\"word\":\"…\",\"accept\":true|false,"
    "\"reason\":\"不超过 20 字\"}, …]}，逐个词都要有结论，不要遗漏、不要新增。"
)

#: **自身就是类别词**的动作取值：它们当查询没有任何信息量（`动作=动作`），
#: 实测是污染榜第一名（41 条边）。判据里已经写了这一条，但它是**唯一**一类
#: "模型容易放过、后果又确定"的词，所以在代码里再钉一遍，并如实写进理由。
VACUOUS_ACTION_WORDS = frozenset({"动作", "运动", "行为", "表演", "动作组",
                                  "动作设计", "动作规范"})


def candidates(cards: Sequence) -> List[str]:
    """与旧 `vocabulary.build_nodes` 第 4 步**同一份候选集**。

    只有把这些词逐个判过，才能说"污染清单是钉死的"——所以候选集必须与旧规则的
    输入一致（performance／blocking 域、长度 2–6、不与已知节点重名）。
    """
    known = {str(canon) for canon, _ in ACTIONS}
    out: List[str] = []
    for card in cards:
        if str(getattr(card, "domain", "")) not in ("performance", "blocking"):
            continue
        for tag in getattr(card, "tags", ()) or ():
            tag = str(tag).strip()
            if not tag or tag in known or not 2 <= len(tag) <= 6:
                continue
            if tag not in out:
                out.append(tag)
    return out


def _prompt_sha256() -> str:
    return hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest()[:16]


def classify(words: Sequence[str], client, *, batch_size: int = 40) -> Dict[str, Dict]:
    """逐词判定 → `{word: {"accept": bool, "reason": str}}`。缺答的词按 rejected 记。"""
    decisions: Dict[str, Dict] = {}
    for start in range(0, len(words), batch_size):
        batch = list(words[start:start + batch_size])
        user = "逐个判定下列词，顺序不要变：\n" + "\n".join("- %s" % w for w in batch)
        reply = client.chat_json(SYSTEM, user, temperature=0.0, seed=0, num_ctx=8192)
        got = {}
        for row in reply.get("decisions", []) or []:
            if isinstance(row, dict) and str(row.get("word") or "").strip():
                got[str(row["word"]).strip()] = row
        for word in batch:
            row = got.get(word)
            if row is None:
                decisions[word] = {"accept": False, "reason": "模型漏答，按宁缺勿滥记 rejected"}
                continue
            decisions[word] = {"accept": bool(row.get("accept")),
                               "reason": str(row.get("reason") or "")[:60]}
    for word in list(decisions):
        if word in VACUOUS_ACTION_WORDS:
            decisions[word] = {
                "accept": False,
                "reason": "类别词本身（`动作=动作` 没有信息量），代码层再钉一遍"}
    return decisions


def build(cards: Sequence, client, *, batch_size: int = 40) -> Dict:
    words = candidates(cards)
    decisions = classify(words, client, batch_size=batch_size)
    accepted = sorted(w for w, d in decisions.items() if d["accept"])
    rejected = sorted(w for w, d in decisions.items() if not d["accept"])
    return {
        "_provenance": {
            "purpose": "action 是 ACTION_BEAT/PERFORMANCE_PACK 的必填槽位，只能收"
                       "看得见的身体行为（审计 #16）",
            "criterion": "演员/角色在镜头前看得见、能表演出来的身体行为",
            "model_id": str(getattr(client, "model_id", "")),
            "model_version": str(getattr(client, "model_version", "")),
            "prompt_sha256": _prompt_sha256(),
        },
        "controlled": [canon for canon, _ in ACTIONS],
        "accepted": accepted,
        "rejected": rejected,
        "reason": {w: d["reason"] for w, d in sorted(decisions.items())},
    }


def decided_words(payload: Dict) -> Dict[str, bool]:
    """已判定的词 → accept。**包含人工钉住的结论**，所以重跑不会漂移。"""
    out: Dict[str, bool] = {}
    for word in payload.get("accepted") or []:
        out[str(word)] = True
    for word in payload.get("rejected") or []:
        out[str(word)] = False
    return out


def merge(previous: Dict, cards: Sequence, client, words: Sequence[str],
          *, batch_size: int = 40) -> Dict:
    """**只判新词**，已判定的一个都不重判。

    为什么要这样：分类是模型调用，同一条判据重跑会有抖动（实测第二次重判就把
    `肢体语言`／`情绪姿态` 从 rejected 翻成 accepted）。词表是**索引的输入**，
    抖动会让语料/索引无法复现，所以已判定的结论一旦入库就当**钉住**——
    要翻案得显式改文件（`reason` 里写明是谁改的、为什么），而不是靠"再跑一次"。
    """
    known = decided_words(previous)
    fresh = [w for w in words if w not in known]
    decisions = classify(fresh, client, batch_size=batch_size) if fresh else {}
    payload = dict(previous)
    accepted = list(previous.get("accepted") or [])
    rejected = list(previous.get("rejected") or [])
    reasons = dict(previous.get("reason") or {})
    for word, row in sorted(decisions.items()):
        reasons[word] = row["reason"]
        (accepted if row["accept"] else rejected).append(word)
    payload["accepted"] = sorted(set(accepted))
    payload["rejected"] = sorted(set(rejected))
    payload["reason"] = reasons
    payload["controlled"] = list(previous.get("controlled") or [canon for canon, _ in ACTIONS])
    provenance = dict(previous.get("_provenance") or {})
    provenance["merge_rounds"] = int(provenance.get("merge_rounds", 0)) + 1
    if fresh:
        provenance["last_merged_words"] = sorted(fresh)
        provenance["last_merged_model"] = str(getattr(client, "model_id", ""))
    payload["_provenance"] = provenance
    return payload


def load(path: pathlib.Path | str) -> Dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _read_extra(spec: str) -> List[str]:
    """`--extra` 的词表：`@文件`（每行一个）或逗号分隔。"""
    spec = str(spec or "").strip()
    if not spec:
        return []
    if spec.startswith("@"):
        text = pathlib.Path(spec[1:]).read_text(encoding="utf-8")
    else:
        text = spec
    return [w.strip() for w in text.replace(",", "\n").split("\n") if w.strip()]


def action_values(payload: Dict) -> List[str]:
    """受控表 ＋ 判定通过的标签 —— `build_nodes` 要铺成 `action:` 节点的全集。"""
    values = list(payload.get("controlled") or []) + list(payload.get("accepted") or [])
    seen: List[str] = []
    for value in values:
        value = str(value).strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - 薄 CLI
    from tools.kb_fetch import llm

    parser = argparse.ArgumentParser(prog="kb_fetch.action_lexicon")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--extra", default="",
                        help="额外的候选词（`@文件`，每行一个）。用来把抽取器**提出过"
                             "但被节点表丢掉**的行为（如 `奔跑`／`拿起`）交给同一条判据"
                             "复核：抽取器提议 + 判据通过 = 进词表，形成一个闭到索引的环。"
                             "中文请用 `@文件` 传——PowerShell 会按本地码页转码命令行。")
    parser.add_argument("--rebuild", action="store_true",
                        help="忽略已有词表、把全部候选**重判一遍**（默认是增量：只判"
                             "没判过的词）。重判会有抖动，只在判据本身换版时才用。")
    args = parser.parse_args(list(argv) if argv is not None else None)

    from block_director.knowledge.corpus import CARDS

    client = llm.make_client(args.provider, args.model)
    target = ROOT / args.out
    spec = str(args.extra or "")
    extra = _read_extra(spec)
    rebuild = args.rebuild or not target.is_file()
    if rebuild:
        payload = build(CARDS, client, batch_size=args.batch_size)
        if extra:
            decided = classify(extra, client, batch_size=args.batch_size)
            accepted = set(payload["accepted"])
            rejected = set(payload["rejected"])
            for word, row in sorted(decided.items()):
                payload["reason"][word] = row["reason"]
                (accepted if row["accept"] else rejected).add(word)
            payload["accepted"] = sorted(accepted)
            payload["rejected"] = sorted(rejected)
            payload["_provenance"]["extra_candidates"] = {
                "source": spec[1:] if spec.startswith("@") else "cli",
                "words": sorted(extra),
                "accepted": sorted(w for w, r in decided.items() if r["accept"]),
            }
    else:
        # 增量：候选集里还没判过的词（新卡带来的新标签）＋ 显式给的 extra。
        payload = merge(load(target), CARDS, client, list(candidates(CARDS)) + extra,
                        batch_size=args.batch_size)
        if extra:
            provenance = dict(payload.get("_provenance") or {})
            provenance["extra_candidates"] = {
                "source": spec[1:] if spec.startswith("@") else "cli",
                "words": sorted(extra),
                "accepted": sorted(w for w in extra if w in set(payload["accepted"])),
            }
            payload["_provenance"] = provenance
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                      encoding="utf-8", newline="\n")
    print(json.dumps({"candidates": len(payload["accepted"]) + len(payload["rejected"]),
                      "accepted": len(payload["accepted"]),
                      "rejected": len(payload["rejected"]),
                      "out": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
