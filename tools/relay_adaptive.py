"""**自适应**地让 GPT-6A 吃下"比一次能喂的更大"的材料。

起因（2026-10-06 用户："四五万字符不行么？……**我是说让 gpt6A 自适应**"）：

实测包线告诉我们**单次**喂不动大包——中转站上 **5,309 B 的包 6 分钟返回**，
而 **17.5 KB 的包 64 分钟零输出**（`docs/evidence/20261006-prompt-budget/`）。
所以"把常数改到四万"是错的解法。**对的解法是分块**：把大材料按**合规块**切，
逐块让 GPT-6A 抽要点（带出处），最后让它**带着全部要点**回答问题。

**自适应体现在两处**：

1. **按块的预算切**：块大小取自 `plan_writer.default_max_prompt_chars(provider)`
   （那是**实测包线**推导出来的，不是拍脑袋）。
2. **按实际失败缩块**：某个块失败（超时／空正文／异常）就**把它对半再切**重试，
   直到成功或降到下限 `MIN_CHUNK`——于是"这次的包线到底在哪"由**运行时的真实反馈**决定，
   而不是由一个我写死的常数决定。

**留证**：每次调用记 `{index, kind, chars, ok, error, elapsed_s, usage}` 落 `calls.json`；
最终答复落 `answer.md`。**降级会被如实写出来**：哪几块试了几次、最终用了什么块大小。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Callable, Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import plan_writer as pw  # noqa: E402

#: 最小块：再往下切就没意义了（一句话都装不下）。触到它就**如实报失败**，不硬凑。
MIN_CHUNK = 400

EXTRACT_HEADER = """\
下面是一份**长材料的第 {index}/{total} 块**。请**只做一件事**：把与下面的问题**相关**的
事实、数字、判据、结论**逐条摘出来**，每条后面用 `【块{index}】` 标明它来自哪一块。

问题：{question}

**不要**回答整个问题、**不要**发表意见、**不要**补你没有看到的内容；
这一块里没有相关的就写"本块无相关问题"。

**你没有工具**：不能执行命令、不能读写文件、不能上网、也看不到任何仓库；
**不要**写"我正在检索／我先去核对／如果会话没有暴露终端工具"这类**旁白**——
只输出摘录本身（`plan_writer.py` 上实测过一次：这种旁白烧掉 903 s 并只落了半成品）。
"""

FINAL_HEADER = """\
下面是**从长材料各块里摘出的要点**（每块已标出处）。请据此回答我最初的问题：

问题：{question}

要求：① 只依据下面的要点，**不要**引入外部知识；② 凡结论都要**标明它来自哪一块**；
③ 要点之间若互相矛盾，**明确指出并列出两边**，不要替我选；④ 看不到的写"材料未覆盖"。

**你没有工具**：不能执行命令、不能读写文件、不能上网、也看不到任何仓库；
**不要**写"我正在核对／我调用了某工具"这类**旁白**，直接给结论与出处。

要点：
{notes}
"""


def split_chunks(text: str, budget: int) -> List[str]:
    """按**段落**切，尽量不把一行劈开；单段本身就超预算时才硬切。

    为什么按段落：切在段落中间会毁掉上下文（本仓的语料是"卡片/案例"，
    一段就是一条记录）。单段超预算时**硬切**并如实留痕——不静默丢内容。
    """
    budget = max(int(budget), MIN_CHUNK)
    paragraphs = [p for p in str(text).split("\n\n") if p.strip()]
    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > budget:                       # 单段过长：硬切
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(para), budget):
                chunks.append(para[i:i + budget])
            continue
        if current and len(current) + len(para) + 2 > budget:
            chunks.append(current)
            current = para
        else:
            current = (current + "\n\n" + para) if current else para
    if current:
        chunks.append(current)
    return chunks or [""]


def adaptive_consult(question: str, materials: Sequence[str], *,
                     budget: int, consult_fn: Callable[..., Tuple[str, dict]],
                     model: str, max_tokens: int, temperature: float,
                     timeout: float, levels: Sequence[str] = ("max",)) -> Dict:
    """**先分块抽要点、再合起来回答**；某块失败就对半切重试。

    `consult_fn` 与 `plan_writer` 用同一个签名（`(messages, *, model, max_tokens,
    levels, temperature, timeout)`），测试注入替身即可离线跑。
    """
    #: 每块最多吃多少字符：预算减去问题与提示头（留存的那部分）。
    head_room = len(EXTRACT_HEADER.format(index=99, total=99, question=question))
    per_chunk = max(MIN_CHUNK, int(budget) - head_room)
    blocks = [b for text in materials for b in split_chunks(text, per_chunk)]
    calls: List[Dict] = []
    notes: List[str] = []
    failures: List[Dict] = []

    queue: List[Tuple[int, str, int]] = [(i + 1, b, 0) for i, b in enumerate(blocks)]
    total = len(blocks)
    while queue:
        index, block, attempt = queue.pop(0)
        prompt = EXTRACT_HEADER.format(index=index, total=total, question=question)
        messages = [{"role": "system", "content": "你是材料摘录员，只摘不判。"},
                    {"role": "user", "content": prompt + "\n\n```text\n" + block + "\n```"}]
        started = time.time()
        try:
            text, usage = consult_fn(messages, model=model, max_tokens=max_tokens,
                                     levels=list(levels), temperature=temperature,
                                     timeout=timeout)
        #: `SystemExit` 也要接住：本仓的通道用 `SystemExit` 报"缺 key／没正文"
        #: （`glm_consult.ConsultFailed` 就是它的子类）。漏掉它 ⇒ 异常直接穿出 `main()`，
        #: **`answer.md` / `calls.json` 一个都不会写**，现场只剩下"进程没了"。
        #: 与 `plan_writer.py` / `panel_consult.py` 的同一处修复同规（2026-10-06，P14-294）。
        except (Exception, SystemExit) as exc:       # noqa: BLE001 - 失败要留证并缩块
            calls.append({"index": index, "kind": "extract", "chars": len(block),
                          "ok": False, "error": "%s: %s" % (type(exc).__name__,
                                                            str(exc)[:160]),
                          "elapsed_s": round(time.time() - started, 1)})
            if len(block) <= MIN_CHUNK:
                #: 已经到下限还是失败 ⇒ **如实报失败**，不硬凑、不静默丢。
                failures.append({"index": index, "chars": len(block),
                                 "error": str(exc)[:160]})
                continue
            half = len(block) // 2
            queue.insert(0, (index, block[half:], attempt + 1))
            queue.insert(0, (index, block[:half], attempt + 1))
            continue
        calls.append({"index": index, "kind": "extract", "chars": len(block), "ok": True,
                      "attempt": attempt, "elapsed_s": round(time.time() - started, 1),
                      "usage": usage})
        notes.append(text)

    final_prompt = FINAL_HEADER.format(question=question,
                                       notes="\n\n".join(notes) if notes else "（无）")
    final_messages = [{"role": "system", "content": "你是本项目的裁决/顾问，只依据给定要点。"},
                      {"role": "user", "content": final_prompt}]
    started = time.time()
    answer = ""
    try:
        answer, usage = consult_fn(final_messages, model=model, max_tokens=max_tokens,
                                   levels=list(levels), temperature=temperature,
                                   timeout=timeout)
        calls.append({"index": 0, "kind": "final", "chars": len(final_prompt), "ok": True,
                      "elapsed_s": round(time.time() - started, 1), "usage": usage})
    #: 同上：final 那一次失败也要**记进 calls/failures 并让产物落盘**，不许静默退出。
    except (Exception, SystemExit) as exc:           # noqa: BLE001
        calls.append({"index": 0, "kind": "final", "chars": len(final_prompt), "ok": False,
                      "error": "%s: %s" % (type(exc).__name__, str(exc)[:160]),
                      "elapsed_s": round(time.time() - started, 1)})
        failures.append({"index": 0, "chars": len(final_prompt), "error": str(exc)[:160]})

    return {"answer": answer, "chunks": total, "calls": calls, "failures": failures,
            "budget": int(budget), "per_chunk": per_chunk,
            "final_chars": len(final_prompt)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relay-adaptive")
    parser.add_argument("--question", required=True)
    parser.add_argument("--material", action="append", default=[],
                        help="长材料文件（可多次）；每份都会被切块")
    parser.add_argument("--provider", default="relay", choices=["relay", "glm"])
    parser.add_argument("--model", default="")
    parser.add_argument("--max-prompt-chars", type=int, default=None,
                        help="不填 = 按通道的实测包线（见 plan_writer 的表）")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    budget = (pw.default_max_prompt_chars(args.provider) if args.max_prompt_chars is None
              else int(args.max_prompt_chars))
    question = pathlib.Path(args.question).read_text(encoding="utf-8")
    materials = [pathlib.Path(p).read_text(encoding="utf-8") for p in args.material]
    model, consult_fn = pw.choose_channel(args.provider, args.model)
    result = adaptive_consult(question, materials, budget=budget, consult_fn=consult_fn,
                              model=model, max_tokens=args.max_tokens,
                              temperature=args.temperature, timeout=args.timeout)
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "answer.md").write_text(result["answer"], encoding="utf-8", newline="\n")
    (out_dir / "calls.json").write_text(
        json.dumps({k: v for k, v in result.items() if k != "answer"},
                   ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in result.items() if k != "answer"},
                     ensure_ascii=False))
    return 0 if not result["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
