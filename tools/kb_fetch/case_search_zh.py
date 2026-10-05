"""给 L3 案例生成**中文检索线索**（只做检索键，不替换作者的原文）。

为什么需要它（2026-10-02 实测，`ACCEPTANCE_STATUS.md` §三十.4）：产品的查询是**中文
散文**（"米迦尔自信面朝画面左侧，推镜缓入…"），而 L3 的 810 篇案例**含中文的 0 篇**
——`CaseIndex._text` 只吃作者写的字（英文 `excerpt` ＋ 出处标题），BM25 对中文查询
**恒 0 命中**，E1 连分母都没有。同语言对照（英文查询打英文语料）也只有 0–1/18，
说明"查询与语料对不上"是独立于语言的第二层缺口。

本工具为每个案例生成一句**中文检索线索**：它**只是检索键**，用来把中文查询和这条
案例接上；返回给模型/用户的仍然是作者的英文原文摘录（`excerpt`），一个字都不改。

纪律：

* **换族**：抽取器是 DeepSeek，所以这里走 GLM（与 `holdout_pool` 同一条通道）；
* **不是我们写的理论**：这条线索是**翻译/改写作者自己的摘录**，不是新观点；提示词
  明确要求"只搬运，不评论"；
* **不许带约束**：出现 `禁止/必须/不得/务必` 的线索**丢弃**（L3 不许产出约束，
  §2.3b 的 E3）——这条在产出侧机械检查，不靠模型自觉；
* **可复算**：文件记 `cases_sha256`（`knowledge/cases.jsonl` 的字节摘要）与
  `prompt_sha256`；案例层一变，旧线索文件**作废**（`CaseIndex` 拒用，见那里的注释）。

用法::

    python -m tools.kb_fetch.case_search_zh --provider glm --model glm-5.3 \\
        --workers 6            # 默认：读 knowledge/ 的分片，写 knowledge/cases/ 的分片
    python -m tools.kb_fetch.case_search_zh --cases <新层>/cases --out <新层>/cases \\
        --seed knowledge       # 换代重建：同代同输入的条目直接沿用（见 seed_index）
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import re
import sys
from typing import Dict, List, Optional, Sequence

try:
    from . import common
    from . import llm
    from . import vocabulary
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common, llm  # type: ignore
    from tools.kb_fetch import vocabulary  # type: ignore

#: 案例索引：**目录**（分片布局 `knowledge/cases/part-*.jsonl`）或旧布局的单文件。
CASES = common.KNOWLEDGE
#: 线索的落点：**目录**时写分片（`knowledge/cases/search_zh.part-*.jsonl`，每片 ≤512 KB），
#: 给一份 `.jsonl` 路径时写旧布局的单文件。
OUT = common.KNOWLEDGE / "cases"
#: 分片目标（与 `build_cases.SHARD_TARGET_BYTES` 同一口径：门的 93%）。
SHARD_TARGET_BYTES = int(common.MAX_CARD_FILE_BYTES * 0.93)

#: 线索的长度带宽（太短没有信息量、太长会盖过原文摘录）。
MIN_CHARS = 8
MAX_CHARS = 90
#: 出现这些词就丢弃——L3 **不许**产出约束（E3）。机械检查，不靠模型自觉。
CONSTRAINT_WORDS = ("禁止", "必须", "不得", "务必", "一定要")
#: 出现这些词就丢弃——**元话术**（"本摘录未涉及景别…"）。为什么它是一条硬规则：
#: 2026-10-03 实测，glm-5.3 在"摘要形状"的提示词下会给**没有任何内容**的碎片
#: （`Lecture 1.` / `4.` / 版权页）写出"仅含编号，未涉及景别、运镜或剪辑"这类句子
#: ——那等于把 `景别/运镜/剪辑` 这些**查询里的工艺词**灌进垃圾文档，BM25 于是让
#: 它们比真案例更容易被中文查询命中（E1 的 top-3 因此被 1900 年代散句占满）。
#: 线索是**检索键**；键里出现"我没讲什么"这种自述，只会制造假命中。
META_WORDS = ("摘录", "本段", "本文", "文中", "书中", "这篇文章", "该文",
              "未涉及", "不涉及", "未提及", "未包含", "不含", "未给出", "未说明")

#: 查询侧词表里**没有**、而真实查询一定会用的几个说法（2026-10-04 实测）。
#:
#: 为什么需要这一条：检索是**词面**匹配。拿一次真实运行的 64 条逐镜查询与入库线索
#: 对拍，查询里点名的 309 处工艺词有 **153 处（49.5%）在整个线索库里一次都不存在**
#: ——`固定机位` 31、`景深` 23、`浅景深` 19、`越轴` 15、`逆光` 15、`侧光` 11、
#: `留白` 11、`中远景` 8、`硬光` 5。那些概念**数学上不可能**被这条查询召回，
#: 与排序好坏无关（复算：`python work/e1_vocab_probe.py --cases-dir knowledge …`）。
#:
#: 这里只补"词"，不改判据：`SYSTEM` 第 6 条原样保留——**摘录没讲到就不许用**。
#: 补词不是"编理论"，是把产品的**查询真用到的说法**告诉标注员。
QUERY_SIDE_WORDS_EXTRA = ("轴线", "景深", "浅景深", "深景深", "硬光", "柔光",
                          "反打", "正反打")


def query_side_vocabulary() -> Tuple[str, ...]:
    """查询侧（产品侧）的中文工艺词表——**从 `tools.kb_fetch.vocabulary` 同源派生**。

    为什么必须派生而不是在这里再抄一份（2026-10-04）：`tools/kb_fetch/vocabulary.py`
    的那几张表（`SHOT_SIZE_NAMES` / `MOVEMENT_ZH` / `LIGHTING` / `CAMERA_ANGLES` /
    `COMPOSITION_RULES_ZH` / `AXIS_TOPICS` / `PACING_ZH`）已经是**查询词表的单一真源**
    ——它们被 `vocab_payload()` 铺成超图节点、被 `check_holdout.py` 当作门③ 的词表。
    线索是**检索键**，它的词表必须与查询词表同源；各抄一份正是本仓库付过三次代价的
    那类漂移（v1.5 的 6 类型 / 16 kind、v1.6 的查询键、P9.4 的 `SUFFIX_HELP`）。

    返回值保序去重：同一份输入永远得到同一份列表——它进 `prompt_sha256`，
    所以这份列表**必须**是确定性的。
    """
    words: List[str] = []

    def add(values) -> None:
        for value in values:
            text = str(value or "").strip()
            if text and text not in words:
                words.append(text)

    for aliases in vocabulary.SHOT_SIZE_NAMES.values():
        add(aliases)
    for aliases in vocabulary.MOVEMENT_ZH.values():
        add(aliases)
    for canonical, aliases in vocabulary.LIGHTING:
        add((canonical, *aliases))
    for canonical, aliases in vocabulary.CAMERA_ANGLES:
        add((canonical, *aliases))
    for aliases in vocabulary.COMPOSITION_RULES_ZH.values():
        add(aliases)
    for canonical, aliases in vocabulary.AXIS_TOPICS:
        add((canonical, *aliases))
    for aliases in vocabulary.PACING_ZH.values():
        add(aliases)
    add(QUERY_SIDE_WORDS_EXTRA)
    return tuple(words)


def craft_words_sentence() -> str:
    """给提示词用的"闭集词表"一句（**由 :func:`query_side_vocabulary` 生成**）。"""
    return "、".join(query_side_vocabulary())


#: 提示词的形状 = **查询的形状**（v2，2026-10-03）。v1 写的是"把它改写成一句中文线索"，
#: 模型于是写成**摘要**（"本片讲的是什么"）；而产品的查询是**导演的追问**
#: （"这一镜要怎么拍"）。两条文本的词表因此对不上：v1 的线索里几乎不含
#: `推镜/跟拍/低角度/视线/留白` 这类**查询一定会说的工艺词**，BM25 只能靠
#: 单字（的/在/面/下）把 1900 年代散句顶到 top-3（实测 3/18 = 0.1667）。
#: v2 把线索固定成"**先说'要拍什么'，再说'摘录里的做法/规律'**"这一形状，
#: 并允许（且只允许）在摘录真的讲到时使用工艺词；摘录不含工艺信息时**给空串**。
SYSTEM = (
    "你是分镜知识库的检索线索标注员。给你一条**英文影评/制作分析摘录**，"
    "请把它改写成**一句中文检索线索**——**形状要像导演会拿来问这一镜的那句话的答案**：\n"
    "先说'要拍/要表现什么'（景别、机位、运镜、画面里发生的事、要传达的情绪或节奏），"
    "再说'这条摘录给出的做法、规律或例子'。\n"
    "硬规则：\n"
    "1. **只搬运摘录里已有的信息**（画面、景别、机位、运镜、剪辑、节奏、声音、构图、"
    "表演、调度…），不要评论、不要补充外部知识、不要写成观后感；\n"
    "2. 摘录若**不含任何拍摄工艺信息**（例如只有讲次编号、目录行、人名、书名、"
    "版权或页眉页脚），`zh` 必须给**空串**——宁可没有线索，也不许硬编；\n"
    "3. 直接写内容本身：不许出现'摘录/本段/本文/文中/书中/这篇文章'，也不许写"
    "'未涉及/不涉及/未提及/不含'这类**元话术**；\n"
    "4. 只用**陈述句**，**不要**出现'必须/禁止/不得/务必/一定要'这类要求或禁令；\n"
    "5. " + f"{MIN_CHARS}–{MAX_CHARS} 字，一句，不要标点堆砌，不要列点；\n"
    "6. 优先用中文拍摄现场会说的**工艺词**：下面这一串就是产品查询用的那一份词表"
    "（`tools/kb_fetch/vocabulary.py` 同源派生，不另抄一份）——{craft_words}。"
    "**只能用在摘录真的讲到它的时候**：摘录没讲到的概念，一个都不许写；\n"
    "只输出 JSON：{\"zh\": \"<中文线索；摘录不含工艺信息时给空串>\"}"
).replace("{craft_words}", craft_words_sentence())


def cases_digest(source: pathlib.Path) -> str:
    """案例索引的**字节**摘要——案例一变，旧线索文件就作废。

    **口径与 `block_director.knowledge.cases` 同一份**（那是消费者）：
    分片按序拼接后取摘要；只有一片时等于 `sha256(那一份文件的字节)`，
    所以旧的单文件线索不用换口径。
    """
    from block_director.knowledge import cases as block_cases

    paths = block_cases.case_paths(source) if pathlib.Path(source).is_dir() \
        else [pathlib.Path(source)]
    return block_cases.cases_digest(paths)


def write_dropped(dropped_out: str, dropped_rows: List[dict]) -> None:
    """把丢弃账落盘（`--dropped-out` 为空就什么都不做）。

    它**跟着检查点一起写**：0 覆盖率的成因（"摘录真没有工艺信息"还是"上游抖动"）
    是这一轮的核心读数，跑了几小时之后才看得到就太晚了。
    """
    out = str(dropped_out or "").strip()
    if not out:
        return
    path = pathlib.Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(dropped_rows, key=lambda row: str(row.get("case_id")))
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8", newline="\n")


def load_lines(target: pathlib.Path) -> List[dict]:
    """读线索（**目录**＝分片；文件＝旧布局的那一份）。缺文件返回空。"""
    from block_director.knowledge import cases as block_cases

    if pathlib.Path(target).is_dir():
        paths = [path for path in sorted(
            pathlib.Path(target).glob(block_cases.SEARCH_ZH_SHARD_GLOB))
            if path.is_file()]
    else:
        paths = [pathlib.Path(target)] if pathlib.Path(target).is_file() else []
    rows: List[dict] = []
    for path in paths:
        rows.extend(json.loads(line) for line
                    in path.read_text(encoding="utf-8").split("\n") if line.strip())
    return rows


def write_lines(target: pathlib.Path, rows: Sequence[dict]) -> Dict:
    """写线索。**目录** → 分片（每片 ≤512 KB）；文件 → 旧布局的那一份。

    分片**不放松体积门**：每片仍 ≤ 512 KB、总量仍 ≤ 20 MB（§2.3c，与卡片同口径）。
    切点只在行边界，所以"各片按序拼接"与"一份单文件"逐字节相同。
    """
    target = pathlib.Path(target)
    if not target.is_dir() and target.suffix == ".jsonl":
        common.write_jsonl(target, rows)
        return {"path": str(target), "files": [
            {"name": target.name, "bytes": target.stat().st_size, "rows": len(rows)}]}
    target.mkdir(parents=True, exist_ok=True)
    from block_director.knowledge import cases as block_cases

    for stale in target.glob(block_cases.SEARCH_ZH_SHARD_GLOB):
        stale.unlink()
    info: List[Dict] = []
    shard: List[dict] = []
    used = 0
    def flush(index: int) -> None:
        nonlocal shard, used
        if not shard:
            return
        path = target / f"search_zh.part-{index:03d}.jsonl"
        common.write_jsonl(path, shard)
        info.append({"name": str(path), "bytes": path.stat().st_size,
                     "rows": len(shard)})
        shard, used = [], 0

    for row in rows:
        size = len((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        if shard and used + size > SHARD_TARGET_BYTES:
            flush(len(info))
        shard.append(row)
        used += size
    flush(len(info))
    return {"path": str(target), "files": info,
            "rows": sum(item["rows"] for item in info),
            "shard_target_bytes": SHARD_TARGET_BYTES}


def prompt_sha() -> str:
    return hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest()


def load_cases(source: pathlib.Path) -> List[dict]:
    """读案例：**目录**（分片布局）或一份 jsonl（旧布局 / 单片的线索账也用这条）。"""
    path = pathlib.Path(source)
    if path.is_dir():
        from block_director.knowledge import cases as block_cases

        return [row.to_dict() for row in block_cases.read_cases(path)]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n")
            if line.strip()]


def line_for(client, case: dict) -> Optional[dict]:
    """一条案例 → 一条线索（不合格返回 None，**不编**）。"""
    return make_line(client, case)[0]


def classify(zh: str) -> str:
    """一条线索文本 → 被丢弃的具名原因（`""` = 合格）。**与 :func:`make_line` 同源**。"""
    if not zh:
        return "empty（摘录不含工艺信息，按规则给空串）"
    if not (MIN_CHARS <= len(zh) <= MAX_CHARS):
        return f"length（{len(zh)} 字，带宽 {MIN_CHARS}–{MAX_CHARS}）"
    if any(word in zh for word in CONSTRAINT_WORDS):
        return "constraint（含约束词，E3）"
    if any(word in zh for word in META_WORDS):
        return "meta（元话术：" + "、".join(w for w in META_WORDS if w in zh) + "）"
    if not re.search(r"[\u4e00-\u9fff]", zh):
        return "not-chinese"
    return ""


def case_key(case: dict) -> tuple:
    """一条案例的**线索输入**：`(摘录, 出处标题)`。

    为什么就是这两项（2026-10-05）：`make_line` 拼给模型的 user 模板只有
    `【摘录】` 与 `【出处标题】`——没有 case_id、没有邻居、没有顺序。所以
    **这两项逐字节相同**的案例，就是同一次生成的输入。据此，"同代复用"不是近似，
    是同一份产物（见 :func:`seed_index`）。
    """
    source = case.get("source_ref") if isinstance(case.get("source_ref"), dict) else {}
    return (str(case.get("excerpt") or "").strip(),
            str(source.get("title") or "").strip())


def seed_index(seed_dir: pathlib.Path, expected_prompt: str) -> Dict[tuple, dict]:
    """从**同代**的另一份案例层里取回线索行，键是 `(摘录, 出处标题)`。

    为什么允许这样复用（2026-10-05）：线索是**输入的纯函数**——提示词里只有摘录与
    出处标题两项。两项都逐字节相同的案例，让模型把同一句话再"改写"一遍，只会引入
    一次非确定性（`temperature=0` 也不保证逐字节相同），不会提高质量。
    重建 v4 案例层时 783 条里有 **521** 条的 `(摘录, 标题)` 与现役层逐字节相同，
    而现役层的线索已过审（`test_the_shipped_sidecar_matches_the_shipped_cases`
    全量扫过），当场重跑等于把已审过的键换成一批没审过的同义句。

    三条硬门（任一不满足就**不用**，当场重生成）：

    1. `prompt_sha256` 必须与**当前**提示词相同——跨代复用等于把过期的键塞进新索引
       （与断点续跑那条纪律同一份理由）；
    2. 摘录与出处标题都要逐字节相同（见 :func:`case_key`）；
    3. 沿用文本必须过得了**现行** `classify`——判据是会长的，旧行不一定按今天的
       规则合格（元话术／约束词／长度都重查一遍）。
    """
    from block_director.knowledge import cases as block_cases

    rows_by_id: Dict[str, dict] = {}
    for path in block_cases.search_zh_paths(seed_dir):
        for row in common.read_jsonl(path):
            if str(row.get("prompt_sha256") or "") != str(expected_prompt):
                continue
            if classify(str(row.get("zh") or "")):
                continue
            rows_by_id[str(row.get("case_id") or "")] = row
    out: Dict[tuple, dict] = {}
    for seed_case in block_cases.read_cases(seed_dir):
        payload = seed_case.to_dict()
        row = rows_by_id.get(str(seed_case.case_id))
        if row:
            out.setdefault(case_key(payload), {
                "zh": str(row.get("zh") or ""),
                "model": str(row.get("model") or ""),
                "family": str(row.get("family") or "")})
    return out


def make_line(client, case: dict) -> tuple:
    """一条案例 → （线索行或 None, 丢弃原因）。原因用于**如实记账**（谁被丢掉、为什么）。"""
    excerpt = str(case.get("excerpt") or "").strip()
    if not excerpt:
        return None, "excerpt-empty"
    source = case.get("source_ref") or {}
    user = ("【摘录】\n%s\n\n【出处标题】%s\n\n【原语言】英文"
            % (excerpt[:800], str(source.get("title") or "")[:120]))
    try:
        reply = client.chat_json(SYSTEM, user, 0.0, 0, 1024)
    except Exception as exc:  # noqa: BLE001 - 这一条的失败不该拖死整批
        #: **瞬时失败与规则丢弃必须分开记**（2026-10-03 实测：14 并发下 810 条里
        #: 204 条 `call-failed`，占 25%——把它们和 273 条"摘录不含工艺信息"混在
        #: 一个 `dropped` 里，覆盖率就被失败悄悄拉低）。带上异常类型与首句，
        #: 才分得清"上游限流"与"模型恒空正文"。
        return None, f"call-failed（{type(exc).__name__}：{str(exc)[:60]}）"
    zh = str(reply.get("zh") or "").strip()
    zh = re.sub(r"\s+", "", zh)
    reason = classify(zh)
    if reason:
        return None, reason
    return {"case_id": str(case.get("case_id")), "zh": zh}, ""


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.case_search_zh")
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--provider", default="glm")
    #: 用户裁决（2026-10-04）：GLM 只用 `glm-5.3`（只有它还有额度）。
    parser.add_argument("--model", default="glm-5.3")
    parser.add_argument("--scripted", default="")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    #: 断点落盘：每完成这么多条就把产物写一次。**为什么必须有它**（2026-10-04）：
    #: 一次全量生成要几千次调用、跑几个小时，而"只在结束时写盘"意味着进程一挂
    #: 就丢掉**全部**已完成的工作（包括已经花掉的额度）。节流写盘的代价只是
    #: 几百 KB 的重复 I/O。
    parser.add_argument("--checkpoint-every", type=int, default=200,
                        help="每完成这么多条落盘一次（0 = 只在结束时写）")
    parser.add_argument("--dropped-out", default="",
                        help="把被丢弃的条目与**具名原因**写到这个文件（缺省不写）")
    #: 定向重跑：**只**重跑上一轮"瞬时失败"的那些条目。为什么需要它——空串丢弃是
    #: 规则要求的（摘录真没有工艺信息），重跑它们只是白烧调用；而 `call-failed`
    #: 是上游抖动，重跑就能回收（2026-10-03 实测：204 条 call-failed 把 810 条的
    #: 覆盖率从应有的 ~60% 压到 41%，低于产物下界）。
    parser.add_argument("--retry-from", default="",
                        help="从这份丢弃账（--dropped-out 的产物）里挑要重跑的 case_id")
    parser.add_argument("--retry-reasons", default="call-failed",
                        help="配合 --retry-from：只重跑原因以这些前缀开头的条目（逗号分隔）")
    #: 同代复用：另一份案例层里 `(摘录, 出处标题)` 逐字节相同的线索直接沿用，
    #: 不再花一次调用（见 `seed_index` 的三条硬门）。
    parser.add_argument("--seed", default="",
                        help="另一份**同代**案例层目录：摘录与出处标题逐字节相同的条目"
                             "直接沿用它的线索（不花调用）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    cases_path = pathlib.Path(args.cases)
    out_path = pathlib.Path(args.out)
    cases = load_cases(cases_path)
    digest = cases_digest(cases_path)

    done: Dict[str, dict] = {}
    #: 断点续跑：同代文件里已有的直接复用。**两份指纹都要对上**——
    #: 只看 `cases_sha256` 会把"上一代提示词"写出来的线索当成已完成复用，
    #: 于是同一份文件里混着两代提示词的键，而 `prompt_sha256` 记的是最后一批。
    #: 2026-10-04 实测：同一份 `cases.search_zh.jsonl` 里 436 行是一枚 sha、
    #: 739 行是另一枚，正是这个洞造成的（当时判据只有案例摘要）。
    for row in load_lines(out_path):
        if (row.get("cases_sha256") == digest
                and row.get("prompt_sha256") == prompt_sha()
                and row.get("zh")):
            done[str(row["case_id"])] = row
    todo = [case for case in cases if str(case.get("case_id")) not in done]
    if args.retry_from:
        prefixes = tuple(part.strip() for part in str(args.retry_reasons).split(",")
                         if part.strip())
        prior: Dict[str, str] = {}
        retry_path = pathlib.Path(args.retry_from)
        if retry_path.is_file():
            for row in load_cases(retry_path):
                prior[str(row.get("case_id"))] = str(row.get("reason") or "")
        todo = [case for case in todo
                if str(case.get("case_id")) in prior
                and prior[str(case.get("case_id"))].startswith(prefixes)]
        print(json.dumps({"retry_from": str(retry_path), "reasons": list(prefixes),
                          "retry_todo": len(todo)}, ensure_ascii=False))
    #: 同代复用放在**取 todo 之后**：它只影响"哪些案例还要花调用"。
    seeded: Dict[str, dict] = {}
    if args.seed:
        seed_map = seed_index(pathlib.Path(args.seed), prompt_sha())
        for case in todo:
            row = seed_map.get(case_key(case))
            if row:
                seeded[str(case.get("case_id"))] = row
        todo = [case for case in todo if str(case.get("case_id")) not in seeded]
    if args.limit:
        todo = todo[:args.limit]
    print(json.dumps({"cases": len(cases), "resumed": len(done), "todo": len(todo),
                      "seeded": len(seeded), "cases_sha256": digest[:16]},
                     ensure_ascii=False))

    client = llm.make_client(args.provider, args.model, args.scripted)
    rows: List[dict] = list(done.values())
    #: 复用来的行按**当前**案例集合重签（`cases_sha256` 是这一层自己的摘要）。
    for case_id, row in seeded.items():
        rows.append({"case_id": case_id, "zh": row["zh"], "cases_sha256": digest,
                     "model": row["model"], "family": row["family"],
                     "prompt_sha256": prompt_sha()})
    rows.sort(key=lambda row: str(row["case_id"]))
    dropped = 0
    dropped_rows: List[dict] = []
    checkpoint_every = max(0, int(args.checkpoint_every))
    finished = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for case, result, reason in pool.map(
                lambda case: (case, *make_line(client, case)), todo):
            finished += 1
            if result is None:
                dropped += 1
                dropped_rows.append({"case_id": str(case.get("case_id")),
                                     "reason": reason,
                                     "excerpt": str(case.get("excerpt") or "")[:200]})
            else:
                rows.append({**result, "cases_sha256": digest,
                             "model": client.model_id, "family": client.family,
                             "prompt_sha256": prompt_sha()})
            #: 断点落盘：几千次调用要跑几小时，"只在结束时写盘"= 一挂就全丢。
            if checkpoint_every and finished % checkpoint_every == 0:
                rows.sort(key=lambda row: str(row["case_id"]))
                write_lines(out_path, rows)
                write_dropped(args.dropped_out, dropped_rows)
                print(json.dumps({"progress": finished, "of": len(todo),
                                  "written": len(rows), "dropped": dropped},
                                 ensure_ascii=False), flush=True)
    rows.sort(key=lambda row: str(row["case_id"]))
    written = write_lines(out_path, rows)
    write_dropped(args.dropped_out, dropped_rows)
    print(json.dumps({"written": len(rows), "dropped": dropped,
                      "coverage": round(len(rows) / max(1, len(cases)), 4),
                      "path": str(out_path),
                      "shards": [item["name"] for item in written["files"]]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
