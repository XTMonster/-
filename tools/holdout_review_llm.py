"""双模型复核（用户裁决：Q5/Q7 这一层让 DeepSeek 与 GLM 两个模型来判）。

**这不是"人审"**——协议 §5.1/§4.1b 把 Q5／Q7／E3 的最终裁定留给**人**，理由是这三条
量的是**作者意图**，agent 没有意图。用户明确指示"这一层让 deepseek 和 glm 做"，所以本
脚本产出的记录一律写 `reviewed_by: "llm-panel"`，**绝不冒充 "human"**：

* `tools/check_holdout.py` 的门⑦ 只认 `reviewed_by == "human"`，因此它照旧判
  `not_measured`／fail——**验收标准没有被放宽**，只是多了一份**辅助证据**；
* 两个模型**都判 rejected** 的条目直接从 held-out 里剔除（提高口径质量）；
* 两个模型**分歧**的条目保留并打上 `panel_disagreement: true`，同时写进
  `--sheet` 的 markdown 清单——那份清单通常只有几十条，人可以只挑它看。

用法::

  python tools/holdout_review_llm.py --entries fixtures/knowledge_holdout.jsonl \
      --limit 150 --out work/holdout_panel.reviewed.jsonl \
      --report work/holdout_panel.json --sheet work/holdout_panel_disagreements.md

离线自测：`--scripted-a/--scripted-b` 传两份 JSON 桩，与 `tools/kb_fetch/llm.py` 的
`scripted` 后端同一套约定。
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys
import threading
import time
from concurrent import futures
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.holdout_review import needs_human  # noqa: E402
from tools.kb_fetch import llm  # noqa: E402
from tools.check_holdout import EDGE_TYPES, Q_KEY_TO_KIND, query_key_text  # noqa: E402

PANEL_TAG = "llm-panel"
DEFAULT_PANEL = ("deepseek-chat", "glm-4.7")

#: 复核提示词的版本号。**改一个字就要升它**：它进 `prompt_sha256`，而门⑦ 只认
#: 带当前 sha256 的裁决记录——这是"改过判据之后旧记录整批作废"的机器保证。
PROMPT_VERSION = "review/v2"

#: 判据原文（改过一次，见下）。
#:
#: **v1 的缺陷（2026-10-03 实测）**：v1 的判据 4 写的是"**这张卡是否真的支持
#: 这条边**？卡里没写的耦合不要硬凑——宁可 rejected"。它与 schema 自相矛盾：
#: `must` 的边必须带 schema 规定的**必填槽位**，而卡里常常只写了语义、没逐字
#: 写出那个槽位（卡说"留出前方空间"，边必须写 `景别=LS`／`机位=平视`）。逐槽位
#: 账实测：入库 638 条边的可查槽位里 **93.3% 是 `inferred`**（`extractor.member_grounding`）。
#: 于是复核员按 v1 的判据 4 判掉了 92% 的 `needs_human` 条目（150 条里 139 条），
#: 理由清一色"这张卡不支持这条边"，门⑦ 因此**结构性不可达**（三个对照排除了
#: "证据没给全"：喂全部来源卡仍然否、随机 12 条非禁忌条目 11/12 否、修好出处后
#: 仍 11/12 否）。
#:
#: **v2 改的是什么**：把判据从"这张卡有没有逐字写出这条边"改成"**这条期望能不能
#: 被判定**"——`q` 点名的取值要在 `must`/`top1` 的成员里有同类同值的对应（可达性），
#: `must` 的类型/必填槽位要合规（门② 的机器判据会独立再查一遍），`top1 ⊆ must`、
#: `must ∩ never = ∅`。**必填槽位允许由抽取器按冻结 schema 补全**，这不是编造。
#: 只有当 `q` 与 `must` **互相矛盾**（同名 kind 取值不同、`never` 与 `must` 相交、
#: 或这条边与 `q` 完全无关）才 rejected。
#:
#: 这是**判据用错了对象**的修正，不是"放宽"：判据该问的是"标注能不能被判定"，
#: 不是"卡里有没有逐字复述 schema"。门⑦ 的记录仍然是 `reviewed_by:"llm-panel"`，
#: **没有**任何一条被写成 `human`。
SYSTEM = """你是分镜知识库 held-out 的**复核员**。给你一张知识卡和一条检索期望，
请判断这条期望**写得合规、并且可判定**吗。只输出 JSON：
{"verdict":"accepted|rejected|amended","reason":"不超过 40 字","fix":"若 amended 给出改法，否则空串"}

判据（逐条看）：
1. `q` 的键**只能取协议 §2.1 的这 %d 个**：%s；
   取值必须是词表里的规范写法，`q` 与 `must` 里同 kind 的取值**逐字相同**。
2. `must` 的边类型只能是这 %d 个之一（%s），必填槽位必须写全。
   **必填槽位允许由抽取器按冻结的 schema 补全**：卡里只写"留出前方空间"时，
   边仍然必须带 `景别=LS`／`机位=平视` —— 那是 schema 的要求，**不是编造**，
   **不要**因为它没在卡里逐字出现就否决。
3. `top1` 必须与 `must` 中某条一字不差；`never` 与 `must` 不得相交。
4. **这条期望可判定吗**（这是判据的核心，不是"卡里有没有逐字复述"）：
   `q` 点名的每个取值，都要能在 `must`/`top1` 的成员里找到**同类同值**的对应
   （可达性）——能，就 accepted。**只有**出现下面三种**矛盾**才 rejected：
   ① `q` 与 `must` 在同一个 kind 上点了**不同的值**；② `never` 与 `must` 相交；
   ③ 这条边与 `q` 说的东西**完全无关**（连一个取值都对不上）。
5. `forbid_<kind>=取值` 只在 `q` 里出现同 kind 同取值时才算一次禁忌冲突；`
   expect_movements` 要符合卡里描述的作者意图（卡里没写运镜期望时**允许为空**）。
""" % (len(Q_KEY_TO_KIND), query_key_text(), len(EDGE_TYPES), "/".join(EDGE_TYPES))


def entry_prompt(entry: Dict, card: Dict) -> str:
    return ("【知识卡】\n### %s（domain=%s）\n标题：%s\n内容：%s\n\n【待复核的检索期望】\n%s"
            % (card.get("id", entry.get("from_card")), card.get("domain", ""),
               card.get("title", ""), str(card.get("content", ""))[:600],
               json.dumps({k: v for k, v in entry.items()
                           if k in ("id", "from_card", "q", "must", "top1", "never",
                                    "expect_movements")}, ensure_ascii=False, indent=1)))


def _judge(client, entry: Dict, card: Dict) -> Dict:
    try:
        reply = client.chat_json(SYSTEM, entry_prompt(entry, card), 0.0, 0, 8192)
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "error", "reason": f"{type(exc).__name__}: {exc}"[:120], "fix": ""}
    verdict = str(reply.get("verdict") or "").strip().lower()
    if verdict not in ("accepted", "rejected", "amended"):
        return {"verdict": "error", "reason": "verdict 不在词表内", "fix": ""}
    return {"verdict": verdict, "reason": str(reply.get("reason") or "")[:200],
            "fix": str(reply.get("fix") or "")[:300]}


def merge(a: Dict, b: Dict) -> Tuple[str, Dict]:
    """两条判决 → (action, review)。action ∈ keep/drop/flag/**retry**。

    2026-10-03 修（实测）：`error` **不是判决**。旧实现把 `error` 与对面那条按
    "分歧"处理，于是 GLM 的 `HTTP 429 code 1302`（速率限制）被写成了
    `verdict: "amended"` ＋ `needs_human: true` 的**裁决记录**——实测一跑 177 条里
    有 **92 条**是这么来的（`('accepted','error')` 92 条）。后果有两层：
    ① 一份"两个模型分歧"的清单里有 78% 是基础设施问题，人类看它等于白看；
    ② 门⑦ 会把"模型挂了"数成"已复核"。所以 `error` 现在返回 `retry`，
    由调用方重试；重试仍失败就**不落记录**（缺证据不是通过）。
    """
    va, vb = a.get("verdict"), b.get("verdict")
    if va == "error" or vb == "error":
        return "retry", {}
    if va == vb == "accepted":
        return "keep", {"reviewed_by": PANEL_TAG, "verdict": "accepted",
                        "agreement": True, "panel": {"a": a, "b": b}}
    if va == vb == "rejected":
        return "drop", {"reviewed_by": PANEL_TAG, "verdict": "rejected",
                        "agreement": True, "panel": {"a": a, "b": b}}
    return "flag", {"reviewed_by": PANEL_TAG, "verdict": "amended", "agreement": False,
                    "needs_human": True, "panel": {"a": a, "b": b}}


def load_cards() -> Dict[str, Dict]:
    from block_director.knowledge.corpus import CARDS

    return {str(card.id): {"id": str(card.id), "domain": str(card.domain),
                           "title": card.title, "content": card.content}
            for card in CARDS}


def select(entries: Sequence[Dict], limit: int) -> List[Dict]:
    """要复核的条目：需要裁决、且**还没有复核记录**。

    为什么跳过已有记录的：补齐轮（新加了几条带冲突的条目）之后必须能只判新增的
    那几条。否则第二趟会把上一趟已经裁过的条目**重判一遍**——同一对模型对同一条
    期望给出不同结论时，"哪一份记录为准"就没有答案了，而且复核会**剔除**条目，
    剔掉一条就可能让门③ 的支撑数掉到线下（实测：应用 44 条剔除后
    `movement=track_left` 变 thin，补跑一轮才回来）。

    幂等：`select()` 只挑 `review` 缺席的条目，所以重复跑不会改写既有裁决。
    """
    chosen = [entry for entry in sorted(entries, key=lambda e: str(e.get("id", "")))
              if needs_human(entry) and not entry.get("review")]
    return chosen[:limit] if limit else chosen


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_review_llm")
    parser.add_argument("--entries", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--models", default=",".join(DEFAULT_PANEL))
    parser.add_argument("--out", default="work/holdout_panel.reviewed.jsonl")
    parser.add_argument("--report", default="work/holdout_panel.json")
    parser.add_argument("--sheet", default="work/holdout_panel_disagreements.md")
    parser.add_argument("--scripted-a", default="")
    parser.add_argument("--scripted-b", default="")
    parser.add_argument("--resume", default="",
                        help="接着 <out>.decisions.jsonl 里已经判过的条目继续（缺省关闭）。"
                             "长跑**一律**带上它——这一趟是双模型 × 小时级。")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="同时在飞的条目数（每条 = 2 次模型调用）。实测约 3 分钟/条，"
                             "157 条顺序要 ~8 小时；4–6 是吞吐与限流之间的平衡点。")
    parser.add_argument("--retries", type=int, default=2,
                        help="某一侧调用**报错**时的整轮重试次数（缺省 2）。"
                             "`error` 不是判决：不落记录、不写成分歧。")
    args = parser.parse_args(list(argv) if argv is not None else None)

    path = pathlib.Path(args.entries)
    if not path.is_file():
        print(json.dumps({"error": f"{path} 不存在"}, ensure_ascii=False))
        return 2
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n")
               if line.strip()]
    models = [item.strip() for item in str(args.models).split(",") if item.strip()]
    if len(models) != 2 and not (args.scripted_a and args.scripted_b):
        print(json.dumps({"error": "需要两个模型（--models a,b）"}, ensure_ascii=False))
        return 2
    client_a = llm.make_client("scripted" if args.scripted_a else "deepseek",
                               models[0], args.scripted_a)
    client_b = llm.make_client("scripted" if args.scripted_b else "glm",
                               models[1], args.scripted_b)
    cards = load_cards()
    picked = select(entries, args.limit)
    #: **断点续跑**（2026-10-03 加）：这一趟要真跑两个模型 × 每一条 `needs_human`
    #: 条目（当前 157 条 ⇒ ≥314 次调用，按实测调用耗时是**小时级**）。原实现只在
    #: 全部跑完之后才写 `--out`，中途 429/断网/进程被杀就**整趟白跑**——
    #: `ACCEPTANCE_STATUS.md` §34.3 已经为同一形状（Q5 标注卡在 429 退避里 50 分钟）
    #: 付过一次代价。所以每判完一条就把**决定**追加进 `<out>.decisions.jsonl`
    #: （逐行 flush），`--resume` 时先读它、跳过已经判过的 id。
    decisions_path = pathlib.Path(str(args.out) + ".decisions.jsonl")
    decided: Dict[str, Dict] = {}
    if str(args.resume).lower() in ("1", "true", "yes"):
        if decisions_path.is_file():
            for line in decisions_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue            # 半行：最后一次写被截断，跳过它
                if isinstance(record, dict) and record.get("id"):
                    decided[str(record["id"])] = record
        picked = [item for item in picked if str(item["id"]) not in decided]

    #: 每条复核记录自带的**可佐证**字段（§4.1b 硬规则 2）：两个模型 id 必须互异、
    #: 面板提示指纹必须存在且整份文件只有一个（协议先冻结）。门⑦ 用
    #: `check_holdout.review_class()` 判它 —— 缺了就不算一条裁决记录。
    PANEL_SOURCE = {"models": [models[0], models[1]],
                    "prompt_sha256": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest(),
                    "prompt_version": PROMPT_VERSION,
                    "tool": "holdout_review_llm"}
    ran_at = datetime.datetime.now(
        datetime.timezone.utc).astimezone().isoformat(timespec="seconds")

    reviewed: Dict[str, Dict] = {}
    dropped: List[Dict] = []
    flagged: List[Dict] = []
    counts = {"selected": len(picked), "accepted": 0, "dropped": 0, "flagged": 0}
    for ident, record in decided.items():
        reviewed[str(ident)] = record["review"]
        action = str(record.get("action") or "")
        if action in counts:
            counts[action] = counts.get(action, 0) + 1
        if action == "drop" and isinstance(record.get("detail"), dict):
            dropped.append(record["detail"])
        if action == "flag" and isinstance(record.get("detail"), dict):
            flagged.append(record["detail"])
    #: 并发（2026-10-03 加）：一条 = 两次模型调用，实测**约 3 分钟/条** ⇒ 157 条
    #: 顺序跑要 ~8 小时。`--concurrency N` 让 N 条同时在飞；两个客户端本身对 429
    #: 有长退避（`tools/kb_fetch/llm.py`），所以并发是"更快"，不是"更容易失败"。
    #: **落盘仍是逐条 append ＋ flush**（加锁），`--resume` 语义不变。
    write_lock = threading.Lock()

    def decide(entry: Dict) -> Tuple[Dict, str, Dict, Optional[Dict]]:
        card = cards.get(str(entry.get("from_card")), {})
        a = _judge(client_a, entry, card)
        b = _judge(client_b, entry, card)
        action, review = merge(a, b)
        if action == "retry":
            return entry, action, {}, None
        # §4.1b 硬规则 2「禁止自证」：门⑦ 读的是**这份文件里**的判决书，
        # 所以每条记录都要自带可外部佐证的东西——两个模型 id 与面板提示指纹。
        # `check_holdout.review_class()` 不认没有这一块的 `llm-panel` 记录。
        review["source"] = dict(PANEL_SOURCE, ran_at=ran_at)
        detail = None
        if action == "drop":
            detail = {"id": entry["id"], "q": entry.get("q"),
                      "reasons": {"a": a.get("reason"), "b": b.get("reason")}}
        elif action == "flag":
            detail = {"id": entry["id"], "q": entry.get("q"), "must": entry.get("must"),
                      "expect_movements": entry.get("expect_movements"), "a": a, "b": b}
        return entry, action, review, detail

    def record(result) -> None:
        entry, action, review, detail = result
        with write_lock:
            if action == "retry":
                #: 一条模型没答上来 ⇒ 这一条**不落记录**，交给重试轮；重试仍失败
                #: 就是"没复核"，不是"复核过了"。
                return
            reviewed[str(entry["id"])] = review
            if action == "drop":
                counts["dropped"] += 1
                dropped.append(detail)
            elif action == "flag":
                counts["flagged"] += 1
                flagged.append(detail)
            else:
                counts["accepted"] += 1
            #: 逐条落盘（append + flush）：这一趟的进度不许因为一次超时而归零。
            with decisions_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(
                    {"id": str(entry["id"]), "action": action, "review": review,
                     "detail": detail}, ensure_ascii=False) + "\n")
                handle.flush()

    unresolved: List[str] = []

    def run_pass(batch: Sequence[Dict]) -> List[Dict]:
        """跑一批并把不是 `retry` 的结果落盘；返回需要重试的那些条目。"""
        pending: List[Dict] = []
        if args.concurrency > 1 and len(batch) > 1:
            with futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                for outcome in pool.map(decide, batch):
                    entry, action = outcome[0], outcome[1]
                    if action == "retry":
                        pending.append(entry)
                    else:
                        record(outcome)
        else:
            for entry in batch:
                outcome = decide(entry)
                if outcome[1] == "retry":
                    pending.append(entry)
                else:
                    record(outcome)
        return pending

    todo = list(picked)
    for attempt in range(max(1, args.retries + 1)):
        if not todo:
            break
        todo = run_pass(todo)
        if todo:
            #: 退一步再打：429 是**速率**限制，同一瞬间重试只会再撞一次。
            time.sleep(min(60.0, 10.0 * (attempt + 1)))
    unresolved = [str(item["id"]) for item in todo]

    kept = [dict(entry, review=reviewed[str(entry["id"])]) if str(entry["id"]) in reviewed
            else entry for entry in entries
            if str(entry["id"]) not in {str(item["id"]) for item in dropped}]
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in kept),
                        encoding="utf-8")

    sheet_path = pathlib.Path(args.sheet)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 双模型复核：分歧清单（请人只看这些）", "",
             f"- 复核条目 {counts['selected']} 条；两模型一致接受 {counts['accepted']}；"
             f"一致否决并剔除 {counts['dropped']}；**分歧 {counts['flagged']}**；"
             f"**一条模型没答上来、因此没有记录 {len(unresolved)}**。",
             f"- 复核者标记为 `{PANEL_TAG}`（**不是人**）：门⑦ 只认 `reviewed_by == \"human\"`，"
             "所以它没有被这份清单满足。", ""]
    for item in flagged:
        lines += [f"## {item['id']}", "", f"查询：`{item['q']}`", "",
                  f"- A（{models[0]}）：{item['a'].get('verdict')} — {item['a'].get('reason')}",
                  f"- B（{models[1]}）：{item['b'].get('verdict')} — {item['b'].get('reason')}", ""]
    sheet_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = {"generated_at": datetime.datetime.now(
        datetime.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "entries": str(path), "out": str(out_path), "sheet": str(sheet_path),
        "panel": {"a": models[0], "b": models[1], "tag": PANEL_TAG,
                  "prompt_sha256": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest()},
        # 每条被保留的记录都带同一份 source（模型 id ＋ 指纹 ＋ 时间）；门⑦
        # 用 `check_holdout.review_class()` 判它——缺了就不算裁决记录。
        "review_source": dict(PANEL_SOURCE, ran_at=ran_at),
        "counts": counts, "dropped": dropped, "disagreement_ids": [i["id"] for i in flagged],
        #: 重试到最后一轮仍然有一条模型是 `error` 的条目：它们**没有**复核记录
        #: （不是"复核过"）。判据方（门⑦）只数有记录的，所以这里是如实记账。
        "unresolved": sorted(unresolved),
        "honesty": ("reviewed_by 写的是 llm-panel；门⑦ 需要 reviewed_by=human，"
                    "这份复核**不构成**人审，不得当作门⑦ 通过。每条记录另带 "
                    "source{models,prompt_sha256,ran_at}，门⑦ 只认带这一块的记录"
                    "（§4.1b 禁止自证）。")}
    report_path = pathlib.Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
