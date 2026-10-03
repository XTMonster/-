"""常驻外部顾问：把冻结的产物交给 **GLM 5.3（智谱）**，按角色出结构化意见。

为什么需要它（2026-10-04 实测）：单模型自审会在**自己没想到的维度**上失灵——
这一轮的三处真缺陷（单人镜头的轴侧、修复回合点不动草案工具、动作窗口重叠）
都是"换一双眼睛"才看见的。所以把它做成常驻能力：遇到难处随时按**不同角色**
问同一个外部模型，再让本 agent 逐条证实/证伪（模型的断言不当作事实）。

设计约束（都是踩过的坑）：

* **密钥只从环境变量读**（`GLM_API_KEY`），绝不入库；
* **会诊必须先看到源码与现状**（用户 2026-10-04 的追问："会诊 AI 有先看目前落实的
  情况与源码么？了解项目才能提出想法"）。所以这里有两道**结构性**保证：
  ① 每一份包都**自动注入"项目现状"**（HEAD、最近提交、未提交改动、`AGENTS.md`
     的状态块、验收台账末尾一节）——现状不再靠调用者转述；
  ② **必须**至少给一份 `--source`（源码，可带 `:起-止` 行段，逐字带行号），
     否则工具**拒绝调用**；真的只想问原理时，得显式写 `--question-only`。
  这两件事都进 `bundle.manifest.json`（逐文件 sha256＋包指纹），所以"它到底看到了
  什么"是**可取证**的，不是记在 README 里的自我声明。
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
      --question work/_q.md --source block_director/cinema/axis.py:160-196 \
      --context docs/evidence/<run>/README.md \
      --out work/_consult/
  ```

  每个角色写一份 `<out>/<role>.json` 与 `<out>/<role>.usage.json`；
  `<out>/bundle.manifest.json` 与 `<out>/bundle.md` 是"它看到了什么"的取证；
  `--dry-run` 只拼提示词、不联网、不写盘（测试用）。
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

GLM_BASE = os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
DEFAULT_MODEL = os.environ.get("GLM_MODEL", "glm-5.3")

#: 仓库根（`tools/` 的上一层）：会诊包里的现状与源码都相对它定位。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 自动注入每一份包的现状真源：`AGENTS.md` 的状态块 ＋ 验收台账的末尾一节。
STATUS_FILES: Tuple[str, ...] = ("AGENTS.md", "docs/knowledge/ACCEPTANCE_STATUS.md")

#: `AGENTS.md` 里"最新一版状态"的起始标记（与 `tests/test_agents_status_is_current.py`
#: 同一判据——那边用它防漂移，这边用它取证）。
STATUS_MARKER = "最新，以这行为准"

#: 自动注入的现状摘要默认占多少字（实测：`glm-5.3` 的 prompt 一旦超过约 1.8k token
#: 就频繁把预算烧在 reasoning 上、正文为空；截断的那部分由 manifest 的 sha256 兜底）。
STATUS_MAX_CHARS = 2000
STATUS_TRUNCATED = "\n…[现状摘要已按 --status-chars 截断；完整文本的字数与 sha256 记在 bundle.manifest.json]"

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
    "领域讲解": (
        "把工艺与原理**讲清楚**：这个问题的第一原理是什么、真实片场怎么做、"
        "为什么在这个项目里成立；按『先原理、再落到这个代码库、最后给可执行步骤』"
        "的顺序解释，允许指出我们漏掉的信息。"),
    "实现顾问": (
        "只谈**怎么落地**：给出改哪个文件/函数、改成什么形状、哪些既有测试会红、"
        "该怎么测；每一步都要说明**为什么**要这样改，以及不这样改会怎样。"),
    "红队反方": (
        "你是**唱反调的那个**：假设作者的每一条结论都是自我安慰，去找"
        "①把指标做绿的动机、②没跑的对照、③被'如实记录'掩盖掉的真实风险。"
        "但只在你**能引用产物原句**时才算数。"),
    "领域专家": (
        "你按**这个领域（预演/分镜/剪辑/再创作）的专业标准**看："
        "现在的判据与产物，缺哪一个专业上必须有的维度？给出可执行的最小补充。"),
}


class ConsultFailed(SystemExit):
    """没有拿到正文。带上**逐档尝试**，让调用方能把证据落盘再退出。"""

    def __init__(self, message: str, attempts: List[dict]) -> None:
        super().__init__(message)
        self.attempts = attempts

SYSTEM_TEMPLATE = """\
你是这个项目的外部顾问，当次扮演的角色是：**{role}**。

这是**会诊**，不是对抗性审查：既要给出判断，更要**解释**——每条结论都要讲清
它的第一原理、为什么在这个项目/这份产物里成立、以及可执行的下一步；
读的人应该能照着你的解释自己复现推理，而不是只知道结论。

硬规矩：
* 只依据 bundle 里**真实出现**的文字与数字说话；引用要逐字照抄（中文就照抄中文）。
* 不发明文件路径、行号、函数名、数字。看不到就写进 `not_checked`。
* 一条精确的结论胜过三条含糊的。
* `severity`：`blocker`（结论/实现是错的）、`major`（真缺陷，有绕法）、`minor`（文档/观感）。
* 只输出**一个 JSON 对象**，不要任何额外说明：
  {{"summary": "<一段话>",
    "role": "{role}",
    "teaching": "<把这件事讲清楚：第一原理 → 在本项目里为什么成立 → 该怎么做>",
    "findings": [{{"id": "F1", "severity": "blocker|major|minor",
                   "title": "<短标题>", "claim": "<结论是什么>",
                   "explanation": "<为什么：原理与在本项目里的落点，讲给能读代码的人>",
                   "where": "<bundle 里的原句/数字>",
                   "why_it_matters": "<后果>",
                   "suggested_check": "<用什么实验/命令可以定案>",
                   "step_by_step": ["<可执行的第 1 步>", "<第 2 步>"],
                   "confidence": "high|medium|low"}}],
    "not_checked": ["<bundle 没让你判断的东西>"]}}

{role_instruction}
"""


def _git(repo: pathlib.Path, *args: str) -> str:
    """跑一条**只读** git 命令；失败返回空串。

    取证不能成为新的失败点：仓库不在 git 下（或 git 不在 PATH）时，包照拼、
    manifest 里如实写"未知"，而不是让整个会诊崩掉。
    """
    try:
        done = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, timeout=30,
                              #: 仓库里有中文路径，而 Windows 的默认编码是 gbk：
                              #: 不显式指定就会在**读取线程**里炸出 UnicodeDecodeError
                              #: （2026-10-04 实测），取证反而成了失败点。
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    return done.stdout.strip()


def git_snapshot(repo: pathlib.Path = REPO_ROOT) -> Dict[str, object]:
    """HEAD 与工作树快照（纯只读）：会诊包"看的是哪一版"的锚点。"""
    return {
        "repo": str(repo),
        "head": _git(repo, "rev-parse", "--short", "HEAD"),
        "head_subject": _git(repo, "log", "-1", "--pretty=%s"),
        "recent": _git(repo, "log", "--oneline", "-5").splitlines(),
        "uncommitted": _git(repo, "status", "--porcelain").splitlines(),
    }


def _status_block(text: str) -> Optional[str]:
    """`AGENTS.md` 的状态块：标记行起、到第一个空行为止。找不到返回 None。"""
    lines = text.splitlines()
    hits = [index for index, line in enumerate(lines) if STATUS_MARKER in line]
    if not hits:
        return None
    out: List[str] = []
    for line in lines[hits[0]:]:
        if not line.strip():
            break
        out.append(line)
    return "\n".join(out)


def status_digest(repo: pathlib.Path = REPO_ROOT,
                  status_files: Sequence[str] = STATUS_FILES) -> str:
    """**项目现状**：HEAD ＋ 未提交改动 ＋ 状态块 ＋ 台账末尾（逐字）。

    这一段自动进每一份包——用户的要求是"了解项目才能提出想法"，所以"现在是什么
    状态"不能由提问的人转述（转述会掺进提问者的结论），得让顾问直接读到真源。
    """
    snapshot = git_snapshot(repo)
    lines = ["# 项目现状（自动注入；这是**事实**，不是问题的一部分，别把它当结论）",
             f"- 仓库：{snapshot['repo']}",
             f"- HEAD：{snapshot['head'] or '（未知）'} {snapshot['head_subject']}",
             "- 最近提交（`git log --oneline -5`）："]
    lines += [f"    {item}" for item in (snapshot["recent"] or ["（未知）"])]
    lines.append("- 未提交改动（`git status --porcelain`）：")
    lines += [f"    {item}" for item in (snapshot["uncommitted"] or ["（工作树干净）"])]
    for name in status_files:
        path = pathlib.Path(name)
        if not path.is_absolute():
            path = repo / path
        if not path.is_file():
            lines.append(f"- 现状真源缺失：`{name}`（会诊方应把这一点记进 not_checked）")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        block = _status_block(text) if name.endswith("AGENTS.md") else None
        if block is None:
            lines.append(f"- `{name}` 末尾 2000 字（逐字）：")
            block = text[-2000:]
        else:
            lines.append(f"- `{name}` 状态块（逐字）：")
        lines += ["```", block.rstrip(), "```"]
    return "\n".join(lines)


def cap_status(text: Optional[str], max_chars: int) -> Optional[str]:
    """按 `--status-chars` 截断现状摘要（0 = 不截）。截断**要留痕**、不许静默丢。"""
    if text is None or not max_chars or len(text) <= max_chars:
        return text
    return text[:max_chars] + STATUS_TRUNCATED


def parse_source_spec(spec: str) -> Tuple[str, Optional[int], Optional[int]]:
    """`路径[:起[-止]]` → (路径, 起, 止)。

    注意 Windows 盘符里的冒号：只有**尾部**形如 `12` 或 `12-40` 才当行段，
    `E:\\白模预演codex\\a.py` 这种没有行段、也没有尾部数字的照样当路径。
    """
    match = re.match(r"^(?P<path>.+?):(?P<start>\d+)(?:-(?P<end>\d+))?$", spec)
    if not match:
        return spec, None, None
    end = match.group("end")
    return match.group("path"), int(match.group("start")), (int(end) if end else None)


def read_source(spec: str, repo: pathlib.Path = REPO_ROOT) -> Dict[str, object]:
    """读一份**源码**：带行号逐字，附整文件/片段两个 sha256（取证用）。"""
    raw, start, end = parse_source_spec(spec)
    path = pathlib.Path(raw)
    full = path if path.is_absolute() else repo / path
    if not full.is_file():
        raise SystemExit(f"--source 指的文件不存在：{spec}（解析出的路径 {full}）")
    name = str(full)
    try:
        name = str(full.relative_to(repo)).replace("\\", "/")
    except ValueError:
        pass
    text = full.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    first = start if start is not None else 1
    last = end if end is not None else len(lines)
    if first < 1 or last < first:
        raise SystemExit(f"--source 的行段非法：{spec}")
    last = min(last, len(lines))
    chunk = lines[first - 1:last]
    numbered = "\n".join(f"{number:5d}| {line}"
                         for number, line in enumerate(chunk, start=first))
    return {"name": name, "spec": spec, "range": [first, last],
            "file_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "chunk_sha256": hashlib.sha256(numbered.encode("utf-8")).hexdigest(),
            "lines": len(chunk), "chars": len(numbered), "text": numbered}


def compose_user_message(question: str,
                         contexts: Sequence[Tuple[str, str]],
                         sources: Sequence[Dict[str, object]] = (),
                         status_text: Optional[str] = None) -> str:
    """一条 user 消息：**现状 → 问题 → 源码（逐字带行号）→ 产物**。"""
    parts: List[str] = []
    if status_text:
        parts.append(status_text)
    parts.append(f"# 本次要审的问题\n\n{question}")
    for source in sources:
        start, end = source["range"]          # type: ignore[misc]
        parts.append(f"## 源码：{source['name']}（第 {start}–{end} 行，逐字，带行号）"
                     f"\n\n```\n{source['text']}\n```")
    for name, text in contexts:
        parts.append(f"## 产物：{name}\n\n```\n{text}\n```")
    return "\n\n".join(parts)


def build_messages(role: str, question: str,
                   contexts: Sequence[Tuple[str, str]],
                   sources: Sequence[Dict[str, object]] = (),
                   status_text: Optional[str] = None) -> List[dict]:
    """拼一次顾问请求（纯函数：测试直接断言这一段，不联网）。"""
    if role not in ROLES:
        raise SystemExit(f"未知角色 {role!r}；可用：{', '.join(sorted(ROLES))}")
    system = SYSTEM_TEMPLATE.format(role=role, role_instruction=ROLES[role])
    user = compose_user_message(question, contexts, sources, status_text)
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def bundle_manifest(question_path: str, question: str,
                    contexts: Sequence[Tuple[str, str]],
                    sources: Sequence[Dict[str, object]],
                    status_text: Optional[str],
                    status_full: Optional[str] = None,
                    repo: pathlib.Path = REPO_ROOT) -> Dict[str, object]:
    """"它看到了什么"的取证：现状锚点 ＋ 每份输入的字数与 sha256。"""
    stripped = [{key: value for key, value in item.items() if key != "text"}
                for item in sources]
    full = status_text if status_full is None else status_full
    return {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "repo": git_snapshot(repo),
        "question": {"path": str(question_path),
                     "sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
                     "chars": len(question)},
        #: 语义开关：这次会诊到底有没有把真源码送进去（`--question-only` 时为 False）。
        "source_seen": bool(sources),
        "sources": stripped,
        "contexts": [
            {"path": name,
             "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
             "chars": len(text)}
            for name, text in contexts],
        "status": {"sent_chars": len(status_text or ""),
                   "sent_sha256": hashlib.sha256((status_text or "")
                                                 .encode("utf-8")).hexdigest(),
                   "full_chars": len(full or ""),
                   "full_sha256": hashlib.sha256((full or "")
                                                 .encode("utf-8")).hexdigest(),
                   "truncated": bool(full is not None and status_text is not None
                                     and len(status_text) < len(full))},
    }


def bundle_fingerprints(messages: Sequence[dict]) -> Dict[str, object]:
    """某一份包的指纹：写进 manifest，`bundle.md` 与之一对拍即为"逐字送过"。"""
    return {key: {"chars": len(messages[index]["content"]),
                  "sha256": hashlib.sha256(
                      messages[index]["content"].encode("utf-8")).hexdigest()}
            for index, key in ((0, "system"), (1, "user"))}


def render_bundle(bundles: Sequence[Tuple[str, List[dict]]]) -> str:
    """把**实际送进模型**的逐字内容落成一份人可读的证据文件。"""
    out = ["# 会诊包（实际送进模型的逐字内容）", ""]
    for role, messages in bundles:
        out += [f"## system（角色：{role}）", "", "```text",
                messages[0]["content"].rstrip(), "```", ""]
    for role, messages in bundles[:1]:
        out += [f"## user（所有角色共用；角色 {role} 的包逐字如下）", "", "```text",
                messages[1]["content"].rstrip(), "```", ""]
    return "\n".join(out)


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
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        # 实测（2026-10-04）：大 bundle 跑到 ~30 分钟，对端会**直接掐断**连接
        # （`http.client.RemoteDisconnected`）。这必须记成一条失败记录，
        # 而不是把 traceback 抛出去——崩掉的话连"哪一档、跑了多久"都没了。
        return "", {"level": level, "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_s": round(time.time() - started, 1),
                    "finish_reason": "transport_error",
                    "requested_model": model, "max_tokens": max_tokens}
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
    raise ConsultFailed(
        "glm-5.3 没给出正文：" + json.dumps(tried, ensure_ascii=False), tried)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="glm_consult")
    parser.add_argument("--roles", default="规格一致性",
                        help="逗号分隔；可用：" + ",".join(ROLES))
    parser.add_argument("--question", required=True)
    parser.add_argument("--context", action="append", default=[])
    parser.add_argument("--context-tail", type=int, default=0)
    parser.add_argument("--source", action="append", default=[],
                        help="源码文件，可带行段（`path.py:160-196`）；逐字带行号进包。"
                             "不给就拒绝调用，除非显式 --question-only")
    parser.add_argument("--question-only", action="store_true",
                        help="显式承认这一次**没有**源码可给（包照拼，manifest 记 "
                             "source_seen=false）")
    parser.add_argument("--no-status", action="store_true",
                        help="不自动注入项目现状（默认注入；只在现状本身不相关时用）")
    parser.add_argument("--status-chars", type=int, default=STATUS_MAX_CHARS,
                        help="现状摘要的字数上限（0 = 不截断）；截断会在包里留痕，"
                             "完整文本的 sha256 记在 manifest")
    parser.add_argument("--repo", default=str(REPO_ROOT),
                        help="仓库根，用来定位源码、算 REV 与写相对路径")
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--level", default="high", choices=["low", "high", "max"])
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=1500.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    repo = pathlib.Path(args.repo)
    question = pathlib.Path(args.question).read_text(encoding="utf-8")
    contexts = read_contexts(args.context, tail=args.context_tail)
    sources = [read_source(spec, repo) for spec in args.source]
    if not sources and not args.question_only:
        raise SystemExit(
            "拒绝调用：这次会诊**没有源码**。用户 2026-10-04 的要求是"
            "『会诊 AI 要先看目前落实的情况与源码』——请用 --source <文件[:起-止]> "
            "至少给一份相关源码；真的只想问通用原理时，显式写 --question-only。")
    status_full = None if args.no_status else status_digest(repo)
    status_text = cap_status(status_full, args.status_chars)
    roles = [item.strip() for item in args.roles.split(",") if item.strip()]
    ladder = {"max": ["max", "high", "low"], "high": ["high", "low"],
              "low": ["low"]}[args.level]
    out_dir = pathlib.Path(args.out)
    manifest = bundle_manifest(args.question, question, contexts, sources,
                               status_text, status_full, repo)

    if args.dry_run:
        for role in roles:
            messages = build_messages(role, question, contexts, sources, status_text)
            manifest.setdefault("bundles", {})[role] = bundle_fingerprints(messages)
            print(f"dry-run {role}: {len(sources)} sources, {len(contexts)} artefacts, "
                  f"{sum(len(m['content']) for m in messages)} chars")
        print(json.dumps({"source_seen": manifest["source_seen"],
                          "sources": [item["name"] for item in manifest["sources"]],
                          "head": manifest["repo"]["head"],          # type: ignore[index]
                          "bundles": manifest.get("bundles", {})},
                         ensure_ascii=False))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    bundles: List[Tuple[str, List[dict]]] = []
    for role in roles:
        messages = build_messages(role, question, contexts, sources, status_text)
        bundles.append((role, messages))
        manifest.setdefault("bundles", {})[role] = bundle_fingerprints(messages)
    #: **先留证、再联网**：这样即使这一轮失败（空正文/断连），"它看到了什么"仍在。
    (out_dir / "bundle.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "bundle.md").write_text(render_bundle(bundles), encoding="utf-8")
    for role, messages in bundles:
        try:
            content, usage = consult(messages, model=args.model,
                                     max_tokens=args.max_tokens, levels=ladder,
                                     temperature=args.temperature,
                                     timeout=args.timeout)
        except ConsultFailed as exc:
            # 失败也要留证：把逐档尝试写下来，读者才判断得了"这次值不值"。
            (out_dir / f"{role}.failed.json").write_text(
                json.dumps({"role": role, "requested_model": args.model,
                            "attempts": exc.attempts}, ensure_ascii=False,
                           indent=2), encoding="utf-8")
            raise
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
