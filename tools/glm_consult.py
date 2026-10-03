"""常驻外部顾问：把冻结的产物交给 **GLM 5.3（智谱）**，按角色出结构化意见。

为什么需要它（2026-10-04 实测）：单模型自审会在**自己没想到的维度**上失灵——
这一轮的三处真缺陷（单人镜头的轴侧、修复回合点不动草案工具、动作窗口重叠）
都是"换一双眼睛"才看见的。所以把它做成常驻能力：遇到难处随时按**不同角色**
问同一个外部模型，再让本 agent 逐条证实/证伪（模型的断言不当作事实）。

设计约束（都是踩过的坑）：

* **密钥只从环境变量读**（`GLM_API_KEY`），绝不入库；
* `glm-5.3` 是"始终思考"的模型：`thinking={"type":"enabled","level":…}`；
  实测 `level=max` ＋ `max_tokens=8192` 会把预算全烧在 reasoning 上、
  `finish_reason=length`、**正文为空** ⇒ 默认 `max_tokens=32768`，
  并在没有正文时**逐档降级**（`max → high → low`），每一档都记进 usage；
* 大 bundle ＋ `level=max` 实测会跑 >30 分钟（连接会被对端断开）；
  `level=high` 在 ~10k token 的 bundle 上也要十几分钟 ⇒ 默认 `high`，
  `--level max` 留给"只有一个问题、值得等"的场合；
* 输出必须是**单一 JSON 对象**（便于入库与逐条对拍），正文为空**判失败**；
* 用法：

  ```
  $env:GLM_API_KEY = "<key>"
  python tools/glm_consult.py --roles 规格一致性,红队反方 \
      --question work/_q.md --context docs/evidence/<run>/README.md \
      --out work/_consult/
  ```

  每个角色写一份 `<out>/<role>.json` 与 `<out>/<role>.usage.json`；
  `--dry-run` 只拼提示词、不联网（测试用）。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

GLM_BASE = os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
DEFAULT_MODEL = os.environ.get("GLM_MODEL", "glm-5.3")

#: 角色表：每个角色给一段"怎么看"，**互相不重复**（多 agent 会诊的意义就在这）。
ROLES: Dict[str, str] = {
    "规格一致性": (
        "你先读执行文档/状态文档里的**验收判据**，再读产物。只挑一种毛病："
        "产物里的结论与判据、或判据与实现**对不上**的地方（含'阈值/分母/期望关系"
        "被挪到刚好变绿'的嫌疑）。"),
    "接口与契约": (
        "你只看**两端之间的契约**：谁写、谁读、字段名与取值域、单一真源在哪。"
        "只挑'两边各写一份、必然漂移'与'契约里表达不出来的东西'。"),
    "测试与验收": (
        "你只看**证据强度**：这条结论有没有对照、有没有成对复验、换不变量没有；"
        "哪些数字是单跑、哪些是可复算。只挑'证据撑不起结论'的地方。"),
    "性能与鲁棒": (
        "你只看**跑得完与跑得久**：超时、重试、并发、预算、长输入、失败路径。"
        "只挑'换一份输入就会崩/会空转/会静默降级'的地方。"),
    "红队反方": (
        "你是**唱反调的那个**：假设作者的每一条结论都是自我安慰，去找"
        "①把指标做绿的动机、②没跑的对照、③被'如实记录'掩盖掉的真实风险。"
        "但只在你**能引用产物原句**时才算数。"),
    "领域专家": (
        "你按**这个领域（预演/分镜/剪辑/再创作）的专业标准**看："
        "现在的判据与产物，缺哪一个专业上必须有的维度？给出可执行的最小补充。"),
}

SYSTEM_TEMPLATE = """\
你是这个项目的外部顾问，当次扮演的角色是：**{role}**。

硬规矩：
* 只依据 bundle 里**真实出现**的文字与数字说话；引用要逐字照抄（中文就照抄中文）。
* 不发明文件路径、行号、函数名、数字。看不到就写进 `not_checked`。
* 一条精确的结论胜过三条含糊的。
* `severity`：`blocker`（结论/实现是错的）、`major`（真缺陷，有绕法）、`minor`（文档/观感）。
* 只输出**一个 JSON 对象**，不要任何额外说明：
  {{"summary": "<一段话>",
    "role": "{role}",
    "findings": [{{"id": "F1", "severity": "blocker|major|minor",
                   "title": "<短标题>", "claim": "<结论是什么>",
                   "where": "<bundle 里的原句/数字>",
                   "why_it_matters": "<后果>",
                   "suggested_check": "<用什么实验/命令可以定案>",
                   "confidence": "high|medium|low"}}],
    "not_checked": ["<bundle 没让你判断的东西>"]}}

{role_instruction}
"""


def build_messages(role: str, question: str,
                   contexts: Sequence[Tuple[str, str]]) -> List[dict]:
    """拼一次顾问请求（纯函数：测试直接断言这一段，不联网）。"""
    if role not in ROLES:
        raise SystemExit(f"未知角色 {role!r}；可用：{', '.join(sorted(ROLES))}")
    system = SYSTEM_TEMPLATE.format(role=role, role_instruction=ROLES[role])
    parts = [f"# 本次要审的问题\n\n{question}"]
    for name, text in contexts:
        parts.append(f"## 产物：{name}\n\n```\n{text}\n```")
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(parts)}]


def read_contexts(paths: Sequence[str], tail: int = 0,
                  max_chars: int = 200_000) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for path in paths:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
        if tail and len(text) > tail:
            text = "... [earlier part omitted] ...\n" + text[-tail:]
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... [truncated]"
        out.append((path, text))
    return out


def call_once(messages: List[dict], *, model: str, max_tokens: int, level: str,
              temperature: float, timeout: float,
              api_key: Optional[str] = None) -> Tuple[str, dict]:
    """一次调用。返回 (正文, usage)；失败时正文为空串（**不当成功**）。"""
    key = api_key if api_key is not None else os.environ.get("GLM_API_KEY", "")
    if not key:
        raise SystemExit("缺少 GLM_API_KEY（只从环境变量读，绝不入库）")
    payload = {
        "model": model,
        "stream": False,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": {"type": "enabled", "level": level},
    }
    request = urllib.request.Request(
        f"{GLM_BASE}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST")
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        return "", {"level": level, "error": f"HTTP {exc.code}: {detail}",
                    "elapsed_s": round(time.time() - started, 1),
                    "finish_reason": f"http_{exc.code}"}
    choice = (reply.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = {
        "model": reply.get("model"), "requested_model": model, "level": level,
        "max_tokens": max_tokens, "elapsed_s": round(time.time() - started, 1),
        "usage": reply.get("usage"), "finish_reason": choice.get("finish_reason"),
    }
    return (message.get("content") or ""), usage


def consult(messages: List[dict], *, model: str, max_tokens: int,
            levels: Sequence[str], temperature: float, timeout: float,
            api_key: Optional[str] = None) -> Tuple[str, dict]:
    """按档位阶梯要一次**有正文**的答复；每一档都记进 usage。"""
    tried: List[dict] = []
    for level in levels:
        content, usage = call_once(messages, model=model, max_tokens=max_tokens,
                                   level=level, temperature=temperature,
                                   timeout=timeout, api_key=api_key)
        tried.append(dict(usage))
        if content.strip():
            usage["attempts"] = tried
            return content, usage
        if "429" in str(usage.get("error", "")) or usage.get("error"):
            # 限流/传输错误：换档无益，直接上报
            break
        time.sleep(1.0)
    raise SystemExit("glm-5.3 没给出正文：" + json.dumps(tried, ensure_ascii=False))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="glm_consult")
    parser.add_argument("--roles", default="规格一致性",
                        help="逗号分隔；可用：" + ",".join(ROLES))
    parser.add_argument("--question", required=True)
    parser.add_argument("--context", action="append", default=[])
    parser.add_argument("--context-tail", type=int, default=0)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--level", default="high", choices=["low", "high", "max"])
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=1500.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    question = pathlib.Path(args.question).read_text(encoding="utf-8")
    contexts = read_contexts(args.context, tail=args.context_tail)
    roles = [item.strip() for item in args.roles.split(",") if item.strip()]
    ladder = {"max": ["max", "high", "low"], "high": ["high", "low"],
              "low": ["low"]}[args.level]
    out_dir = pathlib.Path(args.out)

    if args.dry_run:
        for role in roles:
            messages = build_messages(role, question, contexts)
            print(f"dry-run {role}: {len(contexts)} artefacts, "
                  f"{sum(len(m['content']) for m in messages)} chars")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for role in roles:
        messages = build_messages(role, question, contexts)
        content, usage = consult(messages, model=args.model,
                                 max_tokens=args.max_tokens, levels=ladder,
                                 temperature=args.temperature, timeout=args.timeout)
        (out_dir / f"{role}.json").write_text(content, encoding="utf-8")
        (out_dir / f"{role}.usage.json").write_text(
            json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"role": role, "model": usage.get("model"),
                          "level": usage.get("level"),
                          "elapsed_s": usage.get("elapsed_s"),
                          "finish_reason": usage.get("finish_reason")},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
