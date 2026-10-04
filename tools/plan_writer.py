"""用 **GLM-5.3** 起草执行计划，并**默认自我精炼 5 轮**（用户裁决 2026-10-05）。

为什么是一个独立工具而不是"让主 agent 顺手写"：

* 用户裁决：**写执行计划用 GLM-5.3**（主线的职责是执行与取证，不是起草）；
* 用户裁决：**默认自我精炼 5 次**——草案之后固定跑 5 轮精炼，每轮都要留证；
* 计划必须同时是 PRD ＋ TDD ＋ 技术方案（写作契约 `plan-contract.md`），
  而"契约里写了、产出里没做"正是这个项目反复踩过的坑 —— 所以把契约**当系统提示**
  直接喂给模型，并把每轮的输入/输出都落盘。

纪律（与 `glm_consult.py` / `panel_consult.py` 同源）：

* **密钥只从环境变量读**（`GLM_API_KEY`），**绝不写进仓库**、绝不落进产物；
* **先留证、再联网**：`bundle.manifest.json` / `bundle.md` 在任何一次调用之前落盘；
* **一轮失败不许丢已有成果**：该轮记 `failed` 并保留上一轮草案，继续下一轮；
* **精炼不是改需求**：判据/门限/阈值一个字不许动（写进每轮提示词）；
* 产出 `plan.md`（最后一轮成功稿）＋ `plan.round*.md`（每轮全文）＋
  `plan.refinements.json`（每轮字数/sha256/usage/耗时/finish_reason）。

用法::

    $env:GLM_API_KEY = "<key>"        # 只从环境变量读
    python tools/plan_writer.py --question work/_q.md \
        --source block_director/knowledge/hypergraph.py:1-40 \
        --context docs/knowledge/ACCEPTANCE_STATUS.md \
        --out work/_plan/ --level high            # 默认 --rounds 5

    # 主线（DeepSeek）可在两轮之间插入意见：第 r 轮用 --critique 的第 r-1 个文件
    python tools/plan_writer.py ... --critique work/_critique_1.md --critique work/_critique_2.md

    # 只拼包、不联网、不写盘
    python tools/plan_writer.py ... --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import glm_consult as gc  # noqa: E402  （包构造/现状注入/GLM 档位阶梯的唯一真源）

#: 默认自我精炼轮数（用户裁决 2026-10-05）。
DEFAULT_ROUNDS = 5

#: 与 `tools/glm_consult.py --max-tokens` 的 CLI 默认同源（那边写在 argparse 里）。
#: `tests/test_plan_writer.py` 会读它的源码断言两处一致，漂了当场红。
DEFAULT_MAX_TOKENS = 32768

#: **prompt 预算**（字符）：GLM-5.3 是"始终思考"模型，输入越长、reasoning 越长；
#: 实测 2026-10-05：5164 token 的输入（≈7600 字符）在 `low` 档把 32768 个 completion
#: token 全烧在 reasoning 上（32532），`finish_reason=length`、**正文为空**，白等 460 s。
#: 文档实测的安全区是"~2k token（≈3000 字符）以内"。超预算时**拒绝调用**并给出调法，
#: 而不是烧掉十分钟再失败。
DEFAULT_MAX_PROMPT_CHARS = 3000

#: 写作契约的默认位置：hooks 里的那一份（单一真源），可 `--contract` 覆盖。
DEFAULT_CONTRACT = pathlib.Path.home() / ".codex" / "hooks" / "plan-contract.md"

REFINE_HEADER = """\
这是**第 {round} 轮自我精炼**（共 {rounds} 轮）。上一轮的全文在下面。

本轮只做四件事，逐条写清：

1. **对照契约的自查清单逐条核验**：哪几条已满足、哪几条没满足、哪几条无法核验；
2. **补齐缺口**：把没满足的补上（尤其：用户原话 U1…Un → 需求 R1…Rn 的显式映射、
   每条判据的阈值与分母、出处（含 GitHub 与 commit）、TDD 的对抗性用例、
   `待裁决 D1…Dn`）；
3. **消歧**：把仍然含糊的词换成定义、把指代换成全名、把"更好/尽量"换成数字；
4. **列出"本轮改了什么、为什么"**（一段表格即可）。

**红线**（违反即整轮作废）：不许改动任何判据/门限/阈值；不许编造文件、行号、
出处或 commit；看不到的内容写进"未核验"，不要猜。
输出**完整的计划全文**（不是 diff、不是摘要），Markdown。
"""

CRITIQUE_HEADER = """\
主线（DeepSeek）对本轮的意见如下，必须逐条回应（采纳／不采纳都要写理由）：

```text
{critique}
```
"""


def read_contract(path: pathlib.Path) -> str:
    """读写作契约。缺失就**大声失败**（不许静默换一套弱契约）。"""
    if not path.is_file():
        raise SystemExit(
            f"找不到写作契约 {path}。它是本工具的**必填输入**（PRD+TDD+技术方案的口径），"
            "请用 --contract 指定，或确认 codex hooks 装好了 plan-contract.md。")
    return path.read_text(encoding="utf-8")


def prompt_budget_error(prompt_chars: int, budget: int) -> Optional[str]:
    """超预算时的**拒绝理由**（纯函数，测试直接断言）。未超返回 None。"""
    if budget <= 0 or prompt_chars <= budget:
        return None
    return (
        "拒绝调用：这次包的 prompt 是 {n} 字符，超过预算 {b}（GLM-5.3 是始终思考模型，"
        "输入越长 reasoning 越长；实测 ~5164 token 的输入在 low 档会把 32768 个 completion "
        "token 全烧在 reasoning 上、正文为空）。请先把包压小再重试：\n"
        "  --status-chars 400           # 现状摘要默认 2000 字符\n"
        "  --context-tail 2000          # 产物只留尾部\n"
        "  --question <更短的需求文件>   # 需求只留要点\n"
        "  --source <文件:起-止>         # 源码只给相关行段\n"
        "或显式放宽预算：--max-prompt-chars {n2}（自己承担空正文的风险）。".format(
            n=prompt_chars, b=budget, n2=max(prompt_chars, budget)))


def build_plan_messages(contract: str, question: str,
                        contexts: Sequence[Tuple[str, str]],
                        sources: Sequence[Dict[str, object]],
                        status_text: Optional[str]) -> List[dict]:
    """第 0 轮（起草）：契约当 system，现状＋需求＋源码＋产物当 user。"""
    user = gc.compose_user_message(question, contexts, sources, status_text)
    return [{"role": "system", "content": contract},
            {"role": "user", "content": user}]


def build_refine_messages(contract: str, previous: str, round_index: int,
                          rounds: int, critique: str = "") -> List[dict]:
    """第 r 轮（精炼）：契约 ＋ 精炼规则当 system，上一轮全文（＋主线意见）当 user。"""
    system = contract + "\n\n---\n\n" + REFINE_HEADER.format(round=round_index,
                                                             rounds=rounds)
    parts = []
    if critique:
        parts.append(CRITIQUE_HEADER.format(critique=critique.strip()))
    parts.append("## 上一轮的计划全文\n\n" + previous)
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(parts)}]


def write_plan(contract: str, question: str, contexts, sources, status_text: str,
               out_dir: Optional[pathlib.Path], *,
               model: str, rounds: int, levels: Sequence[str], max_tokens: int,
               temperature: float, timeout: float,
               max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
               critiques: Sequence[str] = (),
               consult_fn: Optional[Callable[..., Tuple[str, dict]]] = None) -> Dict:
    """起草 ＋ `rounds` 轮精炼。`out_dir=None` ⇒ dry-run（不写盘、不联网）。

    `consult_fn=None` ⇒ 用 `glm_consult.consult`（GLM 档位阶梯）。测试注入替身即可离线跑。
    """
    if consult_fn is None:
        consult_fn = gc.consult
    rounds = max(0, int(rounds))
    #: **先算预算、再联网**：超预算直接拒绝（不许烧十分钟换一个空正文）。
    draft_prompt = gc.compose_user_message(question, contexts, sources, status_text)
    complaint = prompt_budget_error(len(draft_prompt), max_prompt_chars)
    if complaint:
        raise SystemExit(complaint)
    bundle = [("draft", build_plan_messages(contract, question, contexts,
                                            sources, status_text))]
    for index in range(1, rounds + 1):
        critique = critiques[index - 1] if index - 1 < len(critiques) else ""
        bundle.append((f"round{index}", [{"role": "system",
                                          "content": REFINE_HEADER.format(
                                              round=index, rounds=rounds)}]))
        #: 精炼轮的 user 依赖上一轮产出，dry-run 里只记形状（见下方指纹）。
        _ = critique

    if out_dir is None:
        return {"dry_run": True, "rounds": rounds,
                "draft_chars": sum(len(m["content"]) for m in bundle[0][1]),
                "refine_rounds": rounds}

    history: List[Dict] = []
    current = ""
    for index in range(0, rounds + 1):
        critique = critiques[index - 1] if index >= 1 and index - 1 < len(critiques) else ""
        messages = (build_plan_messages(contract, question, contexts, sources, status_text)
                    if index == 0 else
                    build_refine_messages(contract, current, index, rounds, critique))
        started = time.time()
        try:
            text, usage = consult_fn(messages, model=model, max_tokens=max_tokens,
                                     levels=levels, temperature=temperature,
                                     timeout=timeout)
        #: `SystemExit` 也要接住：GLM 通道用 `SystemExit` 报"缺 key／没正文"
        #: （`glm_consult.ConsultFailed` 就是它的子类），漏掉会让整轮崩掉，
        #: 而"某一轮失败"本身是要记账、要继续的一等结果。
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            history.append({"round": index, "status": "failed",
                            "error": f"{type(exc).__name__}: {exc}"[:400],
                            "elapsed_s": round(time.time() - started, 1)})
            if index == 0:
                raise
            continue  #: 保留上一轮成果，继续下一轮
        if not text.strip():
            history.append({"round": index, "status": "empty",
                            "usage": usage, "elapsed_s": round(time.time() - started, 1)})
            if index == 0:
                raise SystemExit("GLM-5.3 第 0 轮没有正文：先拆小 bundle 再重试")
            continue
        #: **被截断的一轮不算成功稿**（2026-10-05 实测：精炼轮的 completion 32k 全烧在
        #: reasoning 上、`finish_reason=length`，正文是半截 —— 直接采纳会把计划截掉）。
        #: 按"缺证据不得当成功"的纪律：记 `truncated`，保留上一轮。
        finish = str((usage or {}).get("finish_reason") or "")
        if finish == "length":
            history.append({"round": index, "status": "truncated", "chars": len(text),
                            "usage": usage, "elapsed_s": round(time.time() - started, 1),
                            "note": "finish_reason=length：本轮被截断，不采纳；"
                                    "请压小 bundle 或调大 --max-tokens"})
            print(json.dumps({"round": index, "of": rounds, "status": "truncated",
                              "chars": len(text), "model": usage.get("model"),
                              "level": usage.get("level"), "finish_reason": finish},
                             ensure_ascii=False))
            if index == 0:
                raise SystemExit("GLM-5.3 第 0 轮就被截断（finish_reason=length）："
                                 "先压小 bundle 再重试")
            continue
        #: 大幅缩水要留痕：计划越精炼越短是**可疑信号**（可能是把内容丢了）。
        shrink = bool(current) and len(text) < 0.5 * len(current)
        current = text
        name = "plan.md" if index == 0 else f"plan.round{index}.md"
        (out_dir / f".tmp.{name}").write_text(text, encoding="utf-8")
        (out_dir / f".tmp.{name}").replace(out_dir / name)
        (out_dir / (name.replace(".md", ".usage.json"))).write_text(
            json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")
        history.append({"round": index, "status": "ok",
                        "file": name, "chars": len(text),
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "shrink": shrink, "usage": usage,
                        "elapsed_s": round(time.time() - started, 1)})
        print(json.dumps({"round": index, "of": rounds, "chars": len(text),
                          "model": usage.get("model"), "level": usage.get("level"),
                          "finish_reason": finish, "shrink": shrink,
                          "elapsed_s": history[-1]["elapsed_s"]}, ensure_ascii=False))

    successful = [item for item in history if item["status"] == "ok"]
    if not successful:
        raise SystemExit("每一轮都没拿到正文：先拆小 bundle 再重试")
    final = successful[-1]
    provenance = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "rounds_requested": rounds,
        "rounds_ok": len(successful),
        "contract_sha256": hashlib.sha256(contract.encode("utf-8")).hexdigest(),
        "final_sha256": final["sha256"],
        "draft_sha256": successful[0]["sha256"],
    }
    head = ["<!-- 由 tools/plan_writer.py 产出：草案 → {r} 轮自我精炼；"
            "模型 {m}；取证见 plan.refinements.json -->".format(r=rounds, m=model),
            "<!-- {k} -->".format(k=json.dumps(provenance, ensure_ascii=False)), ""]
    (out_dir / "plan.md").write_text("\n".join(head) + (out_dir / final["file"]).read_text(
        encoding="utf-8"), encoding="utf-8")
    (out_dir / "plan.refinements.json").write_text(
        json.dumps({"provenance": provenance, "history": history},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return {"provenance": provenance, "history": history}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="plan_writer")
    parser.add_argument("--question", required=True, help="需求说明（markdown 文件）")
    parser.add_argument("--source", action="append", default=[],
                        help="源码（可带行段）；不给就拒绝调用，除非 --question-only")
    parser.add_argument("--question-only", action="store_true")
    parser.add_argument("--context", action="append", default=[])
    parser.add_argument("--context-tail", type=int, default=0)
    parser.add_argument("--no-status", action="store_true")
    parser.add_argument("--status-chars", type=int, default=gc.STATUS_MAX_CHARS)
    parser.add_argument("--repo", default=str(gc.REPO_ROOT))
    parser.add_argument("--out", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--model", default=gc.DEFAULT_MODEL)
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS,
                        help="自我精炼轮数（默认 %d，用户裁决）" % DEFAULT_ROUNDS)
    parser.add_argument("--level", default="high", choices=["low", "high", "max"])
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=1500.0)
    parser.add_argument("--max-prompt-chars", type=int, default=DEFAULT_MAX_PROMPT_CHARS,
                        help="prompt 字符预算（0=不限）；超了直接拒绝，不烧 reasoning")
    parser.add_argument("--critique", action="append", default=[],
                        help="主线意见（第 r 轮用第 r-1 个文件）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    repo = pathlib.Path(args.repo)
    contract = read_contract(pathlib.Path(args.contract))
    question = pathlib.Path(args.question).read_text(encoding="utf-8")
    contexts = gc.read_contexts(args.context, tail=args.context_tail)
    sources = [gc.read_source(spec, repo) for spec in args.source]
    if not sources and not args.question_only:
        raise SystemExit(
            "拒绝调用：这次计划**没有源码**。请用 --source <文件[:起-止]> 至少给一份；"
            "真的只想问通用原理时，显式写 --question-only。")
    status_text = None if args.no_status else gc.cap_status(gc.status_digest(repo),
                                                           args.status_chars)
    critiques = [pathlib.Path(item).read_text(encoding="utf-8")
                 for item in args.critique]
    levels = {"max": ["max", "high", "low"], "high": ["high", "low"],
              "low": ["low"]}[args.level]
    out_dir = pathlib.Path(args.out)

    if args.dry_run:
        result = write_plan(contract, question, contexts, sources, status_text, None,
                            model=args.model, rounds=args.rounds, levels=levels,
                            max_tokens=args.max_tokens, temperature=args.temperature,
                            timeout=args.timeout,
                            max_prompt_chars=args.max_prompt_chars, critiques=critiques)
        manifest = gc.bundle_manifest(args.question, question, contexts, sources,
                                      status_text, None, repo)
        print(json.dumps({**result, "source_seen": manifest["source_seen"],
                          "sources": [item["name"] for item in manifest["sources"]],
                          "head": manifest["repo"]["head"]}, ensure_ascii=False))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    #: 先留证、再联网（失败的那一轮也留下"它看到了什么"）。
    manifest = gc.bundle_manifest(args.question, question, contexts, sources,
                                  status_text, None, repo)
    (out_dir / "bundle.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "bundle.md").write_text(
        gc.render_bundle([("draft", build_plan_messages(contract, question, contexts,
                                                        sources, status_text))]),
        encoding="utf-8")
    result = write_plan(contract, question, contexts, sources, status_text, out_dir,
                        model=args.model, rounds=args.rounds, levels=levels,
                        max_tokens=args.max_tokens, temperature=args.temperature,
                        timeout=args.timeout,
                        max_prompt_chars=args.max_prompt_chars, critiques=critiques)
    print(json.dumps(result["provenance"], ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
