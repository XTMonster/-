"""C3 诊断：`topic` 字段的准确率到底能测到什么——只读、只诊断，不改任何生成器/判据。

背景（`执行文档v1.5/TECH_SOLUTIONS.md` 第三节 C3）：90 槽位样本的"机械预读"给出
`topic_mismatch = 88/90`，据此把 97.8% 的样本读成"来源卡的 topic 与成员 kind 不是
一回事"。但 `topic` 本身也是生成物，其准确率从未核过 —— 本脚本把它的**出处、
分辨率、词表覆盖面**量出来，让人能判断那个 88/90 究竟在说什么。

只读输入：
  * `knowledge/cards_generated/*.jsonl`（经判据同款 `attestation.load_cards` 加载）；
  * `docs/evidence/20261007-grounding-sample90/sample90.json`；
  * `block_director/knowledge/hypergraph.py` 的闭集常量；
  * `knowledge/sources.yaml` 的 `theme:` 行。

产出：本目录 `topic_field_audit.json` 与 `topic_field_audit.md`。
"""

from __future__ import annotations

import collections
import io
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.knowledge import attestation as att  # noqa: E402

SAMPLE = ROOT / "docs/evidence/20261007-grounding-sample90/sample90.json"
SOURCES_YAML = ROOT / "knowledge/sources.yaml"
VERDICTS = HERE / "topic_card_verdicts.json"


def topic_of(card: dict) -> str:
    return str(card.get("topic") or "").strip()


def main() -> int:
    cards = att.load_cards(ROOT / "knowledge/cards_generated")
    rows = json.loads(SAMPLE.read_text(encoding="utf-8"))["rows"]

    generated = {cid: card for cid, card in cards.items()
                 if str(cid).startswith("gen_")}
    curated = {cid: card for cid, card in cards.items()
               if not str(cid).startswith("gen_")}

    topic_counts: collections.Counter = collections.Counter(
        topic_of(card) for card in cards.values())
    vocab = sorted(t for t in topic_counts if t)
    gen_with = sum(1 for c in generated.values() if topic_of(c))
    cur_with = sum(1 for c in curated.values() if topic_of(c))

    allowed = set(hg.ALLOWED_KINDS)
    overlap = sorted(set(vocab) & allowed)

    by_chunk: dict = collections.defaultdict(set)
    by_url: dict = collections.defaultdict(set)
    for card in cards.values():
        topic = topic_of(card)
        chunk = str(card.get("chunk_id") or "")
        url = str((card.get("source_ref") or {}).get("url") or "")
        if chunk:
            by_chunk[chunk].add(topic)
        if url:
            by_url[url].add(topic)
    chunk_multi = sorted(k for k, v in by_chunk.items() if len(v) > 1)
    url_multi = sorted(k for k, v in by_url.items() if len(v) > 1)

    absent: list = []
    mismatch: list = []
    matched: list = []
    for row in rows:
        nonempty = [topic_of(cards[s]) for s in row["sources"]
                    if s in cards and topic_of(cards[s])]
        if not nonempty:
            absent.append(row)
        elif row["kind"] in nonempty:
            matched.append(row)
        else:
            mismatch.append(row)

    kind_stats: dict = {}
    for kind in sorted({row["kind"] for row in rows}):
        kind_rows = [r for r in rows if r["kind"] == kind]
        kind_stats[kind] = {
            "rows": len(kind_rows),
            "kind_in_topic_vocab": kind in set(vocab),
            "rows_with_any_topic": sum(
                1 for r in kind_rows
                if any(topic_of(cards[s]) for s in r["sources"] if s in cards)),
            "rows_matched": sum(1 for r in kind_rows if r in matched),
        }

    dom_agree = sum(1 for c in generated.values()
                    if topic_of(c) and topic_of(c) == str(c.get("domain") or ""))
    tag_agree = sum(1 for c in generated.values()
                    if topic_of(c) and topic_of(c) in
                    [str(t) for t in (c.get("tags") or [])])
    blob_checked = 0
    blob_mention = 0
    for card in generated.values():
        topic = topic_of(card)
        if not topic:
            continue
        blob_checked += 1
        if topic.replace("_", " ") in att.card_blob(card).lower():
            blob_mention += 1

    src_ids = sorted({s for row in rows for s in row["sources"] if s in cards})
    src_table = []
    for cid in src_ids:
        card = cards[cid]
        src_table.append({
            "card_id": cid,
            "topic": topic_of(card),
            "domain": str(card.get("domain") or ""),
            "tags": [str(t) for t in (card.get("tags") or [])],
            "title": str(card.get("title") or ""),
            "blob_head": " ".join(att.card_blob(card).split())[:220],
            "chunk_id": str(card.get("chunk_id") or ""),
            "url": str((card.get("source_ref") or {}).get("url") or ""),
        })

    theme_lines = re.findall(r"^\s*theme:\s*(\S+)\s*$",
                             SOURCES_YAML.read_text(encoding="utf-8",
                                                    errors="replace"), re.M)

    #: I. 抽查判读（人工，proxy-only）的汇总：先断言判读集**恰好**覆盖样本里
    #: 带非空 topic 的全部来源卡，避免"抽了几张就说准确率"。
    verdict_doc = json.loads(VERDICTS.read_text(encoding="utf-8"))
    verdicts = verdict_doc["verdicts"]
    verdict_ids = {v["card_id"] for v in verdicts}
    covered_ids = {s["card_id"] for s in src_table if s["topic"]}
    coverage_exact = verdict_ids == covered_ids
    by_verdict = collections.Counter(v["verdict"] for v in verdicts)
    by_topic: dict = collections.defaultdict(collections.Counter)
    for item in verdicts:
        by_topic[item["topic"]][item["verdict"]] += 1
    #: 判读集里各 topic 在全库的词表计数，用来把"错标率"放回它的样本量。
    corpus_by_topic = {t: topic_counts[t] for t in sorted(by_topic)}

    payload = {
        "card_counts": {
            "total": len(cards),
            "generated": len(generated),
            "curated": len(curated),
            "generated_with_topic": gen_with,
            "curated_with_topic": cur_with,
            "generated_with_topic_share": round(gen_with / max(1, len(generated)), 4),
        },
        "topic_vocab": {t: topic_counts[t] for t in vocab},
        "topic_vocab_intersect_allowed_kinds": overlap,
        "allowed_kinds_total": len(allowed),
        "resolution": {
            "chunks": len(by_chunk),
            "chunks_with_more_than_one_topic": len(chunk_multi),
            "chunk_examples": chunk_multi[:5],
            "sources_with_more_than_one_topic": len(url_multi),
            "source_examples": url_multi[:5],
        },
        "sample_decomposition": {
            "rows": len(rows),
            "matched": len(matched),
            "mismatch_with_topic": len(mismatch),
            "no_topic_at_all": len(absent),
            "matched_edges": [
                {"edge_id": r["edge_id"], "kind": r["kind"],
                 "n_sources": len(r["sources"])} for r in matched],
            "absent_kinds": collections.Counter(
                r["kind"] for r in absent).most_common(),
        },
        "per_kind": kind_stats,
        "card_level_agreement": {
            "topic_equals_domain": dom_agree,
            "topic_in_card_tags": tag_agree,
            "topic_token_in_card_blob": blob_mention,
            "topic_token_checked": blob_checked,
        },
        "sources_yaml_theme_lines": {
            "n": len(theme_lines),
            "distinct": sorted(set(theme_lines)),
            "in_topic_vocab": sorted(set(theme_lines) & set(vocab)),
            "not_in_topic_vocab": sorted(set(theme_lines) - set(vocab)),
        },
        "spot_audit": {
            "audited_cards": len(verdicts),
            "sample_cards_with_topic": len(covered_ids),
            "covers_exactly_the_with_topic_sample": coverage_exact,
            "by_verdict": dict(by_verdict),
            "by_topic": {t: dict(c) for t, c in sorted(by_topic.items())},
            "corpus_cards_per_audited_topic": corpus_by_topic,
            "reviewer": verdict_doc["_who"],
        },
        "sample_source_cards": src_table,
    }
    (HERE / "topic_field_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")

    with_topic = [s for s in src_table if s["topic"]]
    lines = [
        "# C3：`topic` 字段的准确率诊断（只诊断，不改生成器）",
        "",
        "生成器：`topic_field_audit.py`（只读）。判据同款加载器："
        "`tools.knowledge.attestation.load_cards`。",
        "",
        "## 一、`topic` 是什么（出处）",
        "",
        "- 生产者：`tools/kb_fetch/import_cards.py:81-83` —— "
        "`theme = 该 chunk 的 theme 或 record.theme`，"
        "`topic = theme or (domain if domain in TOPIC_QUOTAS else \"\")`。",
        "- `theme` 是**来源级**声明：`knowledge/sources.yaml` 有 %d 行 `theme:`，"
        "取值 %s。" % (len(theme_lines), sorted(set(theme_lines))),
        "- `TOPIC_QUOTAS`（`tools/kb_fetch/common.py:51`）＝ "
        "lighting/color/camera_angle/editing/anime/storyboard，"
        "是 domain 兜底的那一支。",
        "",
        "⇒ `topic` 不是「这张卡讲了什么」的**卡级判断**，而是"
        "「这张卡来自哪个主题来源」的**来源级标签**，"
        "被复制到该来源产出的每一张卡上。",
        "",
        "## 二、分辨率：来源级，不是卡级",
        "",
        "| 量 | 值 |",
        "|---|---|",
        "| 卡总数 / 生成 / 手写策展 | %d / %d / %d |"
        % (len(cards), len(generated), len(curated)),
        "| 生成卡带非空 `topic` | %d（%.1f%%） |"
        % (gen_with, 100.0 * gen_with / max(1, len(generated))),
        "| 手写策展卡带非空 `topic` | %d |" % cur_with,
        "| 词表（非空取值） | %s |" % ", ".join(vocab),
        "| `chunk_id` 里出现 >1 个 topic 的 | %d / %d |"
        % (len(chunk_multi), len(by_chunk)),
        "| 同一来源 url 出现 >1 个 topic 的 | %d |" % len(url_multi),
        "",
        "⇒ 同一个 chunk 的卡片 topic **恒相同**，因此 `topic` 对"
        "「同 chunk 内部哪张卡讲什么」**零分辨率**。",
        "",
        "## 三、词表覆盖面：机械 `topic_mismatch` 只可能在这几个 kind 上不落空",
        "",
        "- `topic` 词表 ∩ `hypergraph.ALLOWED_KINDS`（共 %d 个）＝ **%s**。"
        % (len(allowed), overlap or "（空）"),
        "- 也就是说，`kind not in card_topics` 这条机械判据"
        "**只有在成员 kind 恰好是 %s 时才有机会判成「匹配」**；"
        "其余 %d 个 kind 是「结构性不可能匹配」，与卡片挂得对不对无关。"
        % (overlap, len(allowed) - len(overlap)),
        "",
        "## 四、把 88/90 拆开（这才是机械预读真正说的东西）",
        "",
        "| 分类 | 行数 | 含义 |",
        "|---|---|---|",
        "| `matched`（有来源卡 topic 等于成员 kind） | %d | 词表巧合 |" % len(matched),
        "| `mismatch_with_topic`（有 topic，但无一等于 kind） | %d | 词表不相交 |"
        % len(mismatch),
        "| `no_topic_at_all`（全部来源卡 topic 为空串） | %d | **缺失**，不是「不等」 |"
        % len(absent),
        "",
        "两条 `matched` 行：",
        "",
    ]
    for item in payload["sample_decomposition"]["matched_edges"]:
        lines.append("- `%s` ｜ kind=%s ｜ 来源卡 %d 张"
                     % (item["edge_id"], item["kind"], item["n_sources"]))
    lines += ["", "逐 kind 明细：", "",
              "| kind | 行数 | kind 在 topic 词表里 | 有 topic 的行 | 判成匹配 |",
              "|---|---|---|---|---|"]
    for kind, stat in kind_stats.items():
        lines.append("| %s | %d | %s | %d | %d |"
                     % (kind, stat["rows"], stat["kind_in_topic_vocab"],
                        stat["rows_with_any_topic"], stat["rows_matched"]))
    lines += [
        "",
        "`no_topic_at_all` 的 kind 分布：%s。"
        % (payload["sample_decomposition"]["absent_kinds"] or "（无）"),
        "",
        "## 五、`topic` 与卡级标签的对拍（能算的那部分）",
        "",
        "| 对拍 | 命中 | 分母 |",
        "|---|---|---|",
        "| `topic == card.domain` | %d | %d 张带 topic 的生成卡 |"
        % (dom_agree, gen_with),
        "| `topic` 落在 `card.tags` 里 | %d | %d |" % (tag_agree, gen_with),
        "| `topic` 字面出现在卡的 `card_blob` 里 | %d | %d |"
        % (blob_mention, blob_checked),
        "",
        "（`card_blob` 与判据同源；`tags` 是卡自己的中文标签。）",
        "",
        "## 六、样本来源卡（%d 张，供人工/独立通道抽查）"
        % len(src_table),
        "",
        "- 带非空 `topic` 的 %d 张；空 `topic` 的 %d 张。"
        % (len(with_topic), len(src_table) - len(with_topic)),
        "- 逐张摊平见 `topic_field_audit.json` 的 `sample_source_cards`。",
        "",
        "## 七、独立抽查：`topic` 描述得了这张卡吗（82 张，人工判读）",
        "",
        "判读数据：`topic_card_verdicts.json`。判读者：%s" % verdict_doc["_who"],
        "抽样规则（确定可复现）：90 槽位样本里出现的 204 张来源卡，"
        "取其中 `topic` 非空的**全部** 82 张，按 `card_id` 升序。",
        "覆盖校验：判读集与样本带 topic 卡的集合**完全相等 = %s**"
        "（%d 张）。" % (coverage_exact, len(covered_ids)),
        "",
        "| 判词 | 张数 | 占比 |",
        "|---|---|---|",
        "| `faithful`（topic 就是这张卡的主题） | %d | %.1f%% |"
        % (by_verdict.get("faithful", 0),
           100.0 * by_verdict.get("faithful", 0) / max(1, len(verdicts))),
        "| `partial`（topic 是上位/邻接学科） | %d | %.1f%% |"
        % (by_verdict.get("partial", 0),
           100.0 * by_verdict.get("partial", 0) / max(1, len(verdicts))),
        "| `mislabeled`（该卡属于别的 topic 桶） | %d | %.1f%% |"
        % (by_verdict.get("mislabeled", 0),
           100.0 * by_verdict.get("mislabeled", 0) / max(1, len(verdicts))),
        "",
        "按 topic 拆（错标集中在哪几个来源主题）：",
        "",
        "| topic | 抽查张数 | faithful | partial | mislabeled | 全库该 topic 卡数 |",
        "|---|---|---|---|---|---|",
    ]
    for topic, counter in sorted(by_topic.items()):
        lines.append("| %s | %d | %d | %d | %d | %d |"
                     % (topic, sum(counter.values()), counter.get("faithful", 0),
                        counter.get("partial", 0), counter.get("mislabeled", 0),
                        corpus_by_topic.get(topic, 0)))
    lines += [
        "",
        "## 八、诊断结论",
        "",
        "1. **`topic` 是来源级标签，不是卡级判断**——同一 `chunk_id` 与同一来源 "
        "url 内 topic 恒相同（%d 个 chunk、%d 个 url，出现 >1 个 topic 的**各为 0**），"
        "所以它对「同一来源内部哪张卡讲什么」零分辨率。"
        % (len(by_chunk), len(by_url)),
        "2. **机械预读那个 `topic_mismatch = 88/90` 不能读成「97.8%% 挂错卡」**："
        "`topic` 词表（%d 个非空取值）与 `ALLOWED_KINDS`（%d 个）只在 %s 上相交，"
        "因此任何成员 kind 不落在这 %d 个值上的行都是「结构性不可能匹配」。"
        "88 条里 %d 条是「有 topic 但词表不相交」、%d 条是「来源卡压根没 topic」"
        "（缺失 ≠ 不等）。"
        % (len(vocab), len(allowed), overlap, len(overlap),
           len(mismatch), len(absent)),
        "3. **`topic` 自身的准确率**（82 张人工抽查，proxy）：faithful %d / "
        "partial %d / mislabeled %d。错标不是均匀的，而是集中在"
        "「把一本泛题材书归到某个主题配额下」的那几个来源主题"
        "（camera_angle / color / editing）；"
        "学科专精的来源（anime / shot_language / storyboard）几乎全 faithful。"
        % (by_verdict.get("faithful", 0), by_verdict.get("partial", 0),
           by_verdict.get("mislabeled", 0)),
        "4. **对下游的含义**：任何拿 `topic` 当「这张卡的主题」来判「挂错卡」的判据，"
        "都会把来源级标签的错标**当成卡级事实**。要它承担卡级判断，"
        "得先改生成器把 `topic` 落成卡级字段——那是**改判据/改生成物**，"
        "按红线 R-5 属于**须裁决**，本卡只出读数、不动手。",
        "",
        "## 九、未做 / 未验证（如实记）",
        "",
        "- **GLM 交叉对拍未跑**：本机 `GLM_API_KEY` 缺失，"
        "而 GLM 类调用按 README 环境约束必须串行且带「不可用即跳过」退路 ⇒ "
        "第七节的判读只有**单通道（DeepSeek 主线 agent）**，不是双通道对拍。",
        "- 抽查是**确定性取全部**（82/82），不是随机抽样 ⇒ 给的是"
        "**分层覆盖**，不是置信区间。",
        "- `topic` 的消费者（已枚举，全部只读）："
        "`tools/kb_fetch/import_cards.py:236`（写进 jsonl）与 `:289`（import 报告统计）；"
        "`docs/evidence/20261007-grounding-sample90/sample_grounding90.py:41,78,120-125`"
        "（机械预读 `mechanical_pre_read`）；"
        "`docs/evidence/20261007-wrong-card-correction/probe_wrong_card_full.py:109`"
        "（P14-318 探针，读作 `topic_or_domain`）。"
        "**运行时检索侧看不到它**：`block_director/knowledge/generated.py` 的 "
        "`CARD_FIELDS` 不含 `topic`（只进审计，不进 `Card`）。",
        "",
    ]
    (HERE / "topic_field_audit.md").write_text("\n".join(lines) + "\n",
                                               encoding="utf-8", newline="\n")

    print(json.dumps({k: v for k, v in payload.items() if k != "sample_source_cards"},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
