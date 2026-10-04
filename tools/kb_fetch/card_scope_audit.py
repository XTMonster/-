"""门⑥ 的分母：**可断言卡**（§4.1b「每张入库卡（L1/L2）至少派生 1 条」）。

## 判据（`scope/v3`，确定性、可复现、不调模型）

```
excluded  ⟺  全语料抽取对这张卡一条边都没抽出来
             （`knowledge/hypergraph.edges.jsonl` 的 `sources` 里没有它）
```

为什么分母必须这样定：门⑥ 要求每张入库卡至少派生一条 held-out 条目，而条目里的
`must` 必须落到索引的某条边上（门⑩ `exact` 关系）。**冻结的 node 词表表达不出这张卡
的知识时，这条要求在构造上无解**——不是"还没标"，是"标了也解析不到边"。

## 一条必须写下来的教训：补边是**有害的**

门⑥ 缺卡时最省事的做法是"重抽缺边的那一批"。实测（2026-10-02）
`python tools/kb_fetch/build_hypergraph.py --only-missing` 单喂这 29 张卡，
模型对**每一张**都吐出了边：

| 卡片正文 | 重抽得到的边 |
|---|---|
| `gen_story_0064`「场景表只需列出外景与内景的清单」 | `SHOT_PATTERN:景别=MS,焦距=50mm,留白=cinematic` |
| `gen_story_0020`「写剧本要慢工出细活」 | `EMOTION_PACK:情绪=平静,强度=low` |
| `gen_block_0048`「任何采购未经导演许可不得进行」 | `ACTION_BEAT:动作=出场,节拍=establish,强度=mid` |
| `gen_anime_0309`「学习前缩姿态可参考米开朗基罗的湿壁画」 | `STAGING_PACK:构图=framing,景别=MS` |

也就是说：**"整轮抽取一条边都没抽出来"是"这张卡的知识落不到镜头层"的证据，
而单卡重抽会把它变成一张必答题**。用它凑覆盖率＝把噪声写进索引换一个绿字。
这一版索引曾经真被这样污染过（542 条边里 3 条是新的、另有 25 条老边被挂上了
这些卡的出处），已按原样回退；`work/hypergraph.atoms.jsonl` 里那 36 条
`extract/v12` 原子边同样删掉了，`--rematch` 之后索引与 HEAD 逐字节一致。

## 它为什么不是橡皮章

1. **分母本身仍是一条硬要求**：每张可断言卡至少 1 条条目。实测 2084 张可断言卡里
   有 2083 张已覆盖，唯一缺的 `gen_cine_0247` 是**真缺口**，要补标注——不是把卡剔掉。
2. **反向对照**（`--edge-control`）：从"索引确实抽出了边"的卡里抽 N 张交给面板，
   若面板判它没落到镜头层，就说明判据会误伤——记进 `criterion_errors`，
   并且**一律保留在分母里**（保守方向永远是不剔）。
3. **被剔的卡逐张列出**，带索引证据（`edges` 计数）与面板旁证。

## 面板只作旁证，不作判据（2026-10-02 实测）

双模型（DeepSeek ＋ GLM，跨族、闭集类别）判读**在同一批卡上不可复现**。固定同一份
21 张卡的名单、同一提示、`temperature=0`、同一对模型，连跑两遍
（`--panel-only @名单 --panel-out …`）：

| | DeepSeek | GLM |
|---|---|---|
| 21 张里类别与上一次相同 | **21** | **11** |
| 类别变了 | 0 | **10** |

10 次翻转**全部**是 GLM 从 `not_expressible` 翻成 `shot_language`（批内邻居一换结果
就变）。原始记录：`docs/evidence/20261002-1130_panel/panel_run_{a,b}.json`。
用一个不可复现的判据去缩小分母，等于把验收标准交给运气——所以判据是确定性的索引
证据，面板的原始判决只留在 `--panel-out` 指向的文件里，用来回答"这个边界像不像话"。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import sys
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.utils.console import force_utf8_streams  # noqa: E402

DEFAULT_OUT = "knowledge/card_scope.json"
DEFAULT_CATALOGUE = "fixtures/knowledge_holdout.cards.json"
DEFAULT_EDGES = "knowledge/hypergraph.edges.jsonl"

#: 判据版本。改判据 ⇒ 换版本号。
CRITERION_VERSION = "scope/v3"

CRITERION = (
    "门⑥ 的分母＝**可断言卡**：冻结的 node 词表能表达它的镜头级取舍。"
    "判据是确定性的——全语料抽取对这张卡抽出了至少一条边"
    "（`knowledge/hypergraph.edges.jsonl` 的 `sources` 含该 id）。"
    "抽不出边的卡在构造上无法派生可解析的门⑩ 条目（`must` 落不到任何边），"
    "故不进分母；它们逐张列在本产物的 `excluded` 里。"
)

#: 面板用的闭集类别 → 是否 assertable（可断言）。
CATEGORIES: Dict[str, bool] = {
    "shot_language": True,
    "not_expressible": False,
    "film_chemistry": False,
    "drawing_technique": False,
    "electrical_construction": False,
    "manuscript_format": False,
    "production_admin": False,
    "casting": False,
    "stage_management": False,
    "craft_process": False,
    "general_theory": False,
}

PANEL_SYSTEM = (
    "你是电影白模预演工具的**知识范围审查员**。这个工具只服务**镜头层面**的预演："
    "机位/镜头/运镜/景别/构图/调度/光线/剪辑节奏/声画/表演与动作/分镜与剧本的场面设计。\n"
    "逐张判断，只输出 JSON："
    '{"decisions":[{"id":"<卡片 id>","category":"<类别>","reason":"不超过 25 字",'
    '"quote":"最相关的一句原文"}]}。\n'
    "类别只能取这些之一：%s\n"
    "\n判法：\n"
    "1) 正文给出的东西**拿来就能对某个镜头做画面或声音上的取舍**，且能落进上面那些槽位"
    " → `shot_language`；\n"
    "2) 确属电影/视频制作，但本工具的词表**没有槽位**放它（跟焦标尺、测光读表、"
    "稿件/表格格式、洗印、动画描线工位）→ `not_expressible`；\n"
    "3) 别的工种/别的媒介、或与影片制作无关 → 取对应的那一类。\n"
    "**不算 shot_language 的**：只是**提到**电影、只是**学习方法/史料/书目**、"
    "只是**格式排版**、只是**某人分工或管理职责**、只是**别的工种施工或工艺**。\n"
    "**拿不准就判 shot_language**（宁可留着，也不要把片子相关的东西剔出去）。"
    % "、".join(CATEGORIES)
)


def _prompt(batch: Sequence[Dict]) -> str:
    return "\n\n".join("### %s（domain=%s）\n标题：%s\n内容：%s"
                       % (item["id"], item.get("domain", ""), item["title"],
                          item["content"]) for item in batch)


def _ask(client, batch: Sequence[Dict], batch_size: int) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for start in range(0, len(batch), batch_size):
        chunk = list(batch[start:start + batch_size])
        try:
            reply = client.chat_json(PANEL_SYSTEM, _prompt(chunk), 0.0, 0, 8192)
        except Exception as exc:  # noqa: BLE001
            for item in chunk:
                out[item["id"]] = {"category": "shot_language",
                                   "error": type(exc).__name__}
            continue
        got = {}
        for row in reply.get("decisions") or []:
            if isinstance(row, dict) and str(row.get("id") or "").strip():
                got[str(row["id"]).strip()] = row
        for item in chunk:
            row = got.get(item["id"]) or {}
            category = str(row.get("category") or "").strip()
            if category not in CATEGORIES:
                category = "shot_language"
            out[item["id"]] = {
                "category": category,
                "reason": str(row.get("reason") or "模型漏答，按 shot_language 计")[:80],
                "quote": str(row.get("quote") or "")[:160]}
    return out


def panel(items: Sequence[Dict], models: Sequence[Tuple[str, object]], *,
          batch_size: int = 10, concurrency: int = 4) -> Dict[str, Dict]:
    """两名审查员各判一遍（跨族）。**只作旁证**，不参与剔除判定。"""
    out: Dict[str, Dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(_ask, client, list(items), batch_size): name
                   for name, client in models}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            for ident, row in future.result().items():
                out.setdefault(ident, {})[name] = row
    return out


def _cards(catalogue: str = DEFAULT_CATALOGUE) -> Dict[str, Dict]:
    """**全量**语料（生成卡 ＋ 手写策展卡）。卡片 id 以入库清单为准。"""
    from block_director.knowledge.corpus import CARDS

    by_id = {str(card.id): card for card in CARDS}
    ids = [str(item) for item in json.loads(
        (ROOT / catalogue).read_text(encoding="utf-8"))]
    missing = [ident for ident in ids if ident not in by_id]
    if missing:
        raise SystemExit("入库清单里有 %d 张卡不在 CARDS 里：%s"
                         % (len(missing), missing[:5]))
    return {ident: {"id": ident, "domain": str(by_id[ident].domain),
                    "title": str(by_id[ident].title)[:80],
                    "content": str(by_id[ident].content)[:600]}
            for ident in ids}


def edges_per_card(edges_path: pathlib.Path) -> Dict[str, int]:
    """卡的 id → 索引里引用它的边数。**确定性判据的唯一输入。**"""
    counts: Dict[str, int] = {}
    for line in edges_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        for source in (json.loads(line).get("sources") or []):
            counts[str(source)] = counts.get(str(source), 0) + 1
    return counts


def control_pool(cards: Sequence[str], wanted: Sequence[str],
                 covered: Sequence[str], count: int, seed: int) -> List[str]:
    """对照组：抽 `count` 张**在 `covered` 里、又没被点名**的卡。

    它证明"剔"这个动作真的会开火，而不是随手把不想管的都塞进去。所以这里
    **必须**是 `(cards - wanted) & covered`：早先写成
    `set(cards) - set(wanted) & set(covered)`，`&` 的优先级高于 `-`，于是对照池
    变成了"几乎全部卡片"（含大量不在 `covered` 里的），对照组就不再是对照组了。
    """
    if count <= 0:
        return []
    import random

    pool = sorted((set(cards) - set(wanted)) & set(covered))
    random.Random(seed).shuffle(pool)
    return pool[:count]


def audit(cards: Dict[str, Dict], edge_counts: Dict[str, int], *,
          covered: Sequence[str]) -> Dict:
    """确定性判据。**不调模型、不读 oracle 内容**。"""
    names = sorted(cards)
    excluded = [ident for ident in names if int(edge_counts.get(ident, 0)) == 0]
    edge_backed = [ident for ident in names
                   if int(edge_counts.get(ident, 0)) > 0]
    used = set(str(item) for item in covered)
    gap = [ident for ident in edge_backed if ident not in used]
    return {
        "criterion": CRITERION, "criterion_version": CRITERION_VERSION,
        "rule": "excluded ⟺ 全语料抽取对该卡零条边（sources 不含该 id）",
        "catalogue": len(names), "edge_backed": len(edge_backed),
        "excluded": excluded, "excluded_count": len(excluded),
        #: 兼容旧读取方（`check_holdout --exclude-cards` 两个键都认）。
        "out_of_scope": excluded, "out_of_scope_count": len(excluded),
        #: 不变量：被剔的卡**不许**在索引里有边（否则就是剔掉了能断言的知识）。
        "excluded_with_edges": sorted(
            ident for ident in excluded if int(edge_counts.get(ident, 0)) > 0),
        #: 诚实计数：被剔的卡里已有条目的（多出来的覆盖，不是损失）。
        "excluded_with_entries": sorted(ident for ident in excluded if ident in used),
        #: 门⑥ 真正在测的东西：可断言卡里还缺条目的（**必须补标注**）。
        "edge_backed_without_entry": gap, "edge_backed_without_entry_count": len(gap),
        "edges_per_card": {ident: int(edge_counts.get(ident, 0)) for ident in names},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.card_scope_audit")
    parser.add_argument("--catalogue", default=DEFAULT_CATALOGUE)
    parser.add_argument("--edges", default=DEFAULT_EDGES)
    parser.add_argument("--covered-from", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--edge-control", type=int, default=0,
                        help="另抽 N 张**索引抽出了边**的卡交给面板（过宽检测；"
                             "判它们没落到镜头层的记 criterion_errors，且**一律保留**）")
    parser.add_argument("--control", type=int, default=0,
                        help="另抽 N 张**已有条目**的卡交给面板（对照组）")
    parser.add_argument("--panel-out", default="",
                        help="把面板旁证写到这个文件（默认不跑面板：判据是确定性的，"
                             "面板同批不可复现，见模块文档）")
    parser.add_argument("--panel-only", default="",
                        help="面板只判这些 id（`@文件` 或逗号分隔），默认判全部被剔的卡。"
                             "**不影响判据与产物**：用来在固定的一份名单上重复跑，"
                             "把「同一批卡不可复现」这件事本身留成证据。")
    #: 用户裁决（2026-10-04）：GLM 只用 `glm-5.3`（只有它还有额度）。
    parser.add_argument("--models", default="deepseek-chat,glm-5.3")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261002)
    args = parser.parse_args(list(argv) if argv is not None else None)
    # 判据的产物里带中文（判据原文、卡片 id），而 stdout 的字节不许取决于控制台
    # 码页：cp936 下 `⊆` 这类符号编不出，会让一次**成功的**运行以
    # `UnicodeEncodeError` 退出（退出码 1 = "有门失败"）。同 `tools/check_holdout.py`。
    force_utf8_streams()

    cards = _cards(args.catalogue)
    edge_counts = edges_per_card(ROOT / args.edges)
    covered = [str(json.loads(line).get("from_card")) for line in
               (ROOT / args.covered_from).read_text(encoding="utf-8").split("\n")
               if line.strip()]
    report = audit(cards, edge_counts, covered=covered)
    target = ROOT / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8", newline="\n")

    if args.panel_out:
        from tools.kb_fetch import llm

        edge_controls = control_pool(sorted(cards), report["excluded"],
                                     sorted(edge_counts), args.edge_control,
                                     args.seed)
        plain_controls = control_pool(sorted(cards), report["excluded"],
                                      sorted(set(covered)), args.control, args.seed)
        if args.panel_only:
            spec = str(args.panel_only)
            if spec.startswith("@"):
                spec = pathlib.Path(spec[1:]).read_text(encoding="utf-8")
            named = [item.strip() for item in spec.replace("\n", ",").split(",")
                     if item.strip()]
        else:
            named = list(report["excluded"])
        wanted = named + plain_controls + edge_controls
        models = []
        for mid in [m.strip() for m in str(args.models).split(",") if m.strip()]:
            provider = ("glm" if mid.lower().startswith("glm")
                        else "ollama" if mid.lower().startswith(("qwen", "ollama"))
                        else "deepseek")
            models.append((mid, llm.make_client(provider, mid)))
        items = [cards[ident] for ident in wanted if ident in cards]
        verdicts = panel(items, models, batch_size=args.batch_size,
                         concurrency=args.concurrency)
        errors = sorted(ident for ident in edge_controls
                        if not CATEGORIES.get(
                            str(((verdicts.get(ident) or {}).get(models[0][0]) or {})
                                .get("category") or "shot_language"), True))
        payload = {
            "models": [mid for mid, _ in models],
            "controls": plain_controls, "edge_controls": edge_controls,
            #: 索引抽出了边、面板却说它落不到镜头层 —— 判据可能过宽；
            #: 这些卡**全部保留在分母里**（保守方向的代价只是一张卡要标一条）。
            "criterion_errors": errors,
            "decisions": verdicts,
        }
        panel_path = ROOT / args.panel_out
        panel_path.parent.mkdir(parents=True, exist_ok=True)
        panel_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8", newline="\n")
        print(json.dumps({"panel": str(panel_path),
                          "criterion_errors": len(errors),
                          "edge_controls": len(edge_controls)}, ensure_ascii=False))

    print(json.dumps({k: v for k, v in report.items()
                      if k != "edges_per_card"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
