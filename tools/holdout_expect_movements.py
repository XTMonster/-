"""Q5 夹具侧的独立标注：给**计划形状**的 held-out 条目补 `expect_movements`。

为什么单独有这一支（背景见 `docs/knowledge/ACCEPTANCE_STATUS.md` §14.2 与 §15.1）：

* §4.1b 的 Q5 分两步判，第一步是「**夹具里带 `expect_movements` 的条目 ≥ 30**」；
  不足则 Q5 **记 `not_measured`，不得判过**。实测入库的 2953 条 oracle 里
  这个字段是 **0 条**——池通道（`tools/holdout_pool.py`）的模板只写
  `q/must/top1/never`，从来没有这个字段。
* Q5 的 join 键是 `q`，判据是「`SceneContract` 查询串与本条 `q` 的**键值对集合
  相等**」。所以能进这份标注的只有**计划形状**的条目——`q` 的键必须落在
  `shot_constraint_query()` 真正会产出的键里（v1.5 起：`景别/意图/镜头/运镜/动作/特效/对白`）。
  两族入选：
  * **`SHOT_PATTERN`**（`shot_size + lens`；`headroom_policy` 没有查询键）——
    但 `镜头` 只在剧本**声明了焦段**或计划**已解算**时才在发出的串里，
    所以这一族的运行侧分母取决于剧本；
  * **`INTENT_PACK`**（`intent + shot_size + movement`）——三个键 2026-10-03 起
    全部可表达（意图闭集进计划、景别与运镜本来就有），实测 oracle 里 **176 条**
    的 `q` 就是 `意图=…；景别=…；运镜=…`，这是**唯一**与引擎可表达空间完全重合
    的一族。
* 判据是「**这张卡的作者**在这条查询下期望什么运镜」，必须**落在卡片正文里**：
  每个取值都要给出正文原句。这不是把索引的 `movement` 成员抄一遍（那是自证，
  §4.1b 硬规则 2 禁止），也不是模型自己的审美偏好。

换族纪律（协议 §5.1 / R49）：抽取器是 **DeepSeek**，标注/复核用 **GLM**
（`family="zhipu"`）。本工具**只**调用 GLM，并把 `annotator` 写进每一行。

密钥只从环境变量读（`GLM_API_KEY`），**绝不写进仓库**。

用法::

    $env:GLM_API_KEY = '...'
    python tools/holdout_expect_movements.py --out work/q5_expect_movements.jsonl
    python tools/holdout_expect_movements.py --apply    # 写回 fixtures/

`--apply` 之前**必须**先跑复核（`tools/holdout_review_llm.py`）：带
`expect_movements` 的条目按协议要有人/面板裁决记录，否则门⑦ 会当场变红。
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import pathlib
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_holdout import Q_KEY_TO_KIND  # noqa: E402
from tools.kb_fetch.llm import GLMClient, LLMError  # noqa: E402

#: `shot_constraint_query()` 真正会产出的键（`block_director/layer5_orchestrator/
#: scene_contract.py`）。**从那里读不到**（那个模块要 bpy 侧的兄弟依赖才 import
#: 得动），所以在这一处**显式钉住**，并由 `tests/test_q5_plan_shaped_entries.py`
#: 拿真实生产者对拍——两处不一致时测试当场红。
PLAN_QUERY_KEYS: Tuple[str, ...] = ("景别", "意图", "镜头", "运镜", "动作", "特效",
                                    "对白")

DEFAULT_HOLDOUT = "fixtures/knowledge_holdout.jsonl"
DEFAULT_VOCAB = "fixtures/knowledge_holdout.vocab.json"
DEFAULT_OUT = "work/q5_expect_movements.jsonl"

#: 一张卡的正文可能很长；正文截断到这么多字符再喂模型（生成的卡正文实测 < 1200）。
CARD_TEXT_LIMIT = 4000

SYSTEM_PROMPT = (
    "你是一名独立标注员，正在为「白模预演」知识库标注 held-out 的期望运镜。\n"
    "纪律（违反即作废）：\n"
    "1. 你**只能**依据给定那一张知识卡的正文下判断，不得引入任何外部常识、"
    "索引内容、检索结果或其它卡。\n"
    "2. 判据是「**这张卡的作者**在这条查询描述的镜头下期望什么运镜」，"
    "不是你的个人审美。\n"
    "3. 每个取值都必须能在正文里指出依据原句（≤40 字，逐字摘录，不要改写）。\n"
    "4. 正文对运镜**没有**给出期望/建议/禁止时，返回空数组——"
    "宁缺勿猜，编出来的条目会让整份 oracle 不可信。\n"
    "5. **只有正文里明确出现运镜语汇时才算有期望**：推/拉/摇/移/跟拍/升降/甩镜/"
    "变焦/固定/静止/不动/环绕/轨道/手持/机械臂/横移，或英文 dolly/zoom/pan/tilt/"
    "track/crane/orbit/handheld/steadicam。\n"
    "   仅仅描述**取景、器材、机位、焦距、画幅、构图**的句子**不算**运镜期望——"
    "那种情况必须返回空数组。你的 quote 必须包含上面的运镜语汇之一，"
    "否则该取值作废。\n"
    "6. 只输出 JSON，不要解释、不要 markdown 代码块。"
)

USER_TEMPLATE = """【知识卡】
id: {card_id}
标题: {title}
正文:
{content}

【查询】{query}
（键的对应关系：{key_map}）

【运镜闭集】只能从这里选，输出**逐字拷贝**的取值，不要翻译、不要改写：
{movements}

【任务】这张卡的作者在上面这条查询描述的镜头下，期望用什么运镜？

只输出这个 JSON：
{{"expect_movements": [{{"value": "<闭集里的取值>", "quote": "<正文原句>"}}],
  "empty_reason": "<为空时写一句为什么>"}}
"""

JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)

#: 判定「这句话真的在说运镜」的语汇表。**与提示词第 5 条同源**：模型给的 quote
#: 里找不到任何一项时，这个取值当场丢掉——防止"拿一句取景描述凑一个 `固定`"。
MOVEMENT_CUES: Tuple[str, ...] = (
    "推", "拉", "摇", "移", "跟拍", "跟镜", "升降", "甩", "变焦", "固定", "静止",
    "不动", "环绕", "轨道", "手持", "机械臂", "横移",
    "dolly", "zoom", "pan", "tilt", "track", "crane", "orbit", "handheld",
    "steadicam", "static",
)


def load_entries(path: pathlib.Path) -> List[dict]:
    """读 JSONL。**不**注入 `__line__`——`--apply` 要逐字写回入库文件。"""
    rows: List[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def plan_shape(entry: dict) -> bool:
    """`q` 的键是否**全部**落在 :data:`PLAN_QUERY_KEYS` 里（且非空）。"""
    keys = [part.split("=", 1)[0].strip()
            for part in str(entry.get("q") or "").split("；") if "=" in part]
    return bool(keys) and set(keys) <= set(PLAN_QUERY_KEYS)


def card_text(card) -> str:
    parts = [str(getattr(card, "title", "") or "")]
    content = str(getattr(card, "content", "") or "")
    for extra in ("rules", "examples", "keywords", "tags"):
        value = getattr(card, extra, None) or []
        if value:
            parts.append(" / ".join(str(item) for item in value))
    parts.append(content)
    return "\n".join(part for part in parts if part)[:CARD_TEXT_LIMIT]


def key_map_of(query: str) -> str:
    pairs = []
    for part in query.split("；"):
        if "=" not in part:
            continue
        key = part.split("=", 1)[0].strip()
        pairs.append(f"{key}={Q_KEY_TO_KIND.get(key, '?')}")
    return "，".join(pairs)


def _parse_json(text: str) -> dict:
    match = JSON_OBJECT_RE.search(text or "")
    if not match:
        raise ValueError("模型没有输出 JSON 对象")
    return json.loads(match.group(0))


def annotate_entry(client, entry: dict, card, movements: Sequence[str]) -> dict:
    query = str(entry.get("q") or "")
    user = USER_TEMPLATE.format(
        card_id=getattr(card, "id", entry.get("from_card")),
        title=str(getattr(card, "title", "") or ""),
        content=card_text(card),
        query=query,
        key_map=key_map_of(query),
        movements=", ".join(movements),
    )
    payload = client.chat_json(SYSTEM_PROMPT, user, temperature=0.2, seed=7,
                               num_ctx=8192)
    allowed = {str(value) for value in movements}
    picked: List[str] = []
    evidence: List[dict] = []
    dropped: List[dict] = []
    for item in payload.get("expect_movements") or []:
        if isinstance(item, str):
            value, quote = item, ""
        elif isinstance(item, dict):
            value, quote = str(item.get("value") or ""), str(item.get("quote") or "")
        else:
            continue
        if value not in allowed:
            continue
        if not quote or not any(cue in quote for cue in MOVEMENT_CUES):
            # 提示词第 5 条：quote 里没有运镜语汇 = 拿取景/器材描述凑数，丢掉。
            dropped.append({"value": value, "quote": quote,
                            "reason": "quote 里没有运镜语汇（提示词第 5 条）"})
            continue
        if value not in picked:
            picked.append(value)
        evidence.append({"value": value, "quote": quote})
    return {
        "id": entry.get("id"),
        "from_card": entry.get("from_card"),
        "q": query,
        "expect_movements": picked,
        "evidence": evidence,
        "dropped": dropped,
        "empty_reason": str(payload.get("empty_reason") or ""),
        "annotator": {
            "model_id": getattr(client, "model_id", ""),
            "family": getattr(client, "family", ""),
            "model_version": getattr(client, "model_version", ""),
            "decode": getattr(client, "decode_tag", ""),
        },
        "ran_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }


def apply_to_fixture(holdout: pathlib.Path, rows: Iterable[dict]) -> Dict[str, int]:
    """把 `expect_movements` 写回**入库**的 held-out（其余字段逐字不动）。"""
    wanted: Dict[str, List[str]] = {}
    for row in rows:
        values = [str(v) for v in (row.get("expect_movements") or []) if str(v)]
        if values:
            wanted[str(row["id"])] = values
    lines = holdout.read_text(encoding="utf-8").splitlines()
    out: List[str] = []
    patched = 0
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        values = wanted.get(str(record.get("id")))
        if values:
            record["expect_movements"] = values
            patched += 1
        out.append(json.dumps(record, ensure_ascii=False))
    holdout.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"patched": patched, "candidates": len(wanted)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout-expect-movements")
    parser.add_argument("--holdout", default=DEFAULT_HOLDOUT)
    parser.add_argument("--vocab", default=DEFAULT_VOCAB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--model", default="glm-4.7-flash")
    parser.add_argument("--limit", type=int, default=0,
                        help="0 = 全部（默认）")
    parser.add_argument("--resume", action="store_true",
                        help="跳过 --out 里已经有的 id（断点续跑）")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="并发条数（1 = 顺序）。实测单条含思考约 40-70 s，"
                             "顺序跑 176 条要数小时；结果 append + flush，"
                             "任何中断都能 --resume 续跑")
    parser.add_argument("--edge-type", action="append", default=None,
                        metavar="TYPE",
                        help="只标注 `must[0]` 属于这些边类的条目（可重复）。"
                             "为什么要这个开关：候选里 `SHOT_PATTERN` 那一族"
                             "（236 条）的 `q` 带 `镜头=`，而焦段在**逐镜检索那一刻**"
                             "还不存在（剧本没声明就不可能有），它的运行侧分母取决于"
                             "剧本；`INTENT_PACK` 那一族（176 条）三个键全部可表达，"
                             "是唯一真能 join 上的。不给开关就只能整批跑，"
                             "把额度花在结构上不可能 join 的条目上。")
    parser.add_argument("--apply", action="store_true",
                        help="把结果写回 --holdout（入库前的最后一步）")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    holdout = ROOT / args.holdout if not pathlib.Path(args.holdout).is_absolute() \
        else pathlib.Path(args.holdout)
    entries = load_entries(holdout)
    selected = [entry for entry in entries if plan_shape(entry)]
    wanted_types = {str(name).upper() for name in (args.edge_type or [])}
    if wanted_types:
        selected = [entry for entry in selected
                    if (entry.get("must") or [""])[0].split(":", 1)[0].upper()
                    in wanted_types]

    from block_director.knowledge.corpus import CARDS  # noqa: PLC0415

    by_id = {str(card.id): card for card in CARDS}
    vocab = json.loads((ROOT / args.vocab).read_text(encoding="utf-8"))
    kinds = vocab.get("kinds") if isinstance(vocab, dict) and "kinds" in vocab else vocab
    movements = [str(value) for value in (kinds.get("movement") or [])]
    if not movements:
        print(json.dumps({"error": "词表里没有 movement 取值"}, ensure_ascii=False))
        return 1

    out_path = ROOT / args.out if not pathlib.Path(args.out).is_absolute() \
        else pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done: Dict[str, dict] = {}
    if args.resume and out_path.is_file():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[str(row.get("id"))] = row

    client = GLMClient(model_id=args.model)
    todo = [entry for entry in selected if str(entry.get("id")) not in done]
    if args.limit:
        todo = todo[:args.limit]
    failures: List[dict] = []
    counts: collections.Counter = collections.Counter()
    write_lock = threading.Lock()

    def work(index: int, entry: dict) -> None:
        """标注一条并追加落盘。**每条独立**：一条失败不影响别的条。"""
        card = by_id.get(str(entry.get("from_card")))
        if card is None:
            with write_lock:
                failures.append({"id": entry.get("id"),
                                 "reason": f"卡片不存在：{entry.get('from_card')}"})
            return
        try:
            row = annotate_entry(client, entry, card, movements)
        except (LLMError, ValueError, json.JSONDecodeError) as exc:  # noqa: BLE001
            with write_lock:
                failures.append({"id": entry.get("id"),
                                 "reason": f"{type(exc).__name__}: {exc}"})
            return
        with write_lock:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            counts["empty" if not row["expect_movements"] else "filled"] += 1
            print(f"[{index}/{len(todo)}] {row['id']} {row['q']} -> "
                  f"{row['expect_movements'] or '（空）'}", flush=True)

    with out_path.open("a", encoding="utf-8") as handle:
        workers = max(1, int(args.concurrency))
        if workers == 1:
            for index, entry in enumerate(todo, 1):
                work(index, entry)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(lambda pair: work(*pair), enumerate(todo, 1)))

    summary = {
        "holdout": str(holdout), "plan_shaped_entries": len(selected),
        "annotated_this_run": len(todo),
        "filled": counts["filled"], "empty": counts["empty"],
        "failures": failures[:20], "failure_count": len(failures),
        "movement_vocabulary": len(movements),
        "out": str(out_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.apply:
        rows = done.values() if done else []
        if not args.resume and out_path.is_file():
            rows = [json.loads(line) for line in
                    out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(json.dumps(apply_to_fixture(holdout, rows), ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
