"""DeepSeek × GLM-5.3 **智能体联合会诊**：同一个问题、同一份包、两个族各答一遍，再逐条对拍。

为什么是"联合"而不是"再问一次"（2026-10-04）：

* 单模型自审会在**自己没想到的维度**上失灵——这一轮的真缺陷（单人镜头的轴侧、
  修复回合点不动草案工具、动作窗口重叠）都是"换一双眼睛"才看见的；
* 但"换个模型再问一遍"本身不是证据：两份回答长得像，可能只是同一个前提的两份复述。
  所以这里把**分歧**当成一等产物——`both` / `severity_conflict` / `glm_only` /
  `deepseek_only` 四栏分开记账，**缺失的一侧永远不算同意**。

与既有工具的关系（单一真源，不另抄一份）：

* 包的构造（现状注入、`--source` 逐字带行号、manifest 先写再联网、角色表、
  GLM 的档位阶梯与 usage）**全部 import 自 `tools/glm_consult.py`**；
* DeepSeek 侧走仓库既有的 `tools/kb_fetch/llm.py::DeepSeekClient`
  （`DEEPSEEK_API_KEY`，只从环境变量读）；
* 判词记录沿用双模型复核的既有口径：`reviewed_by: "llm-panel"`，**绝不写 `human`**。

纪律（与 `glm_consult.py` 一致）：

* **先留证、再联网**：`bundle.manifest.json` / `bundle.md` 在任何一次调用之前落盘，
  失败的那一轮也留得下"它看到了什么"；
* 一侧没拿到正文 ⇒ 记 `failed` 并**判这一次会诊不完整**，绝不把缺席读成同意；
* 会诊的结论**不是验收**：不改判据 / 门限 / 阈值，只出可执行建议。

用法::

    $env:GLM_API_KEY = "<key>"; $env:DEEPSEEK_API_KEY = "<key>"
    python tools/panel_consult.py --roles 规格一致性,红队反方 \
        --question work/_q.md --source block_director/cinema/axis.py:160-196 \
        --context docs/evidence/<run>/README.md --out work/_panel/

    # 主线程本身就是 DeepSeek：把自己的判词写成文件当 DeepSeek 侧入口（不必再走 API）
    python tools/panel_consult.py ... --main-answer work/_main.json

    # 只拼包、不联网、不写盘
    python tools/panel_consult.py ... --dry-run
"""

from __future__ import annotations

import argparse
import difflib
import json
import pathlib
import re
import sys
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import glm_consult as gc  # noqa: E402  （包构造/角色/GLM 通道的单一真源）

#: 判词归属：与 `holdout_review_llm.py` 同一口径——机器面板，**不是人**。
PANEL_TAG = "llm-panel"

#: 与 `tools/glm_consult.py --max-tokens` 的默认值同源（那边写在 argparse 里）。
#: `tools/glm_consult.py` 是 GLM 通道的唯一真源，所以这里是**引用**而不是另立一套：
#: `tests/test_panel_consult.py` 会读它的源码断言两处一致，漂了当场红。
DEFAULT_MAX_TOKENS = 32768

#: 配对阈值：标题＋结论的字符相似度（`difflib`）。0.45 是实测的折中——
#: 同一件事的两份措辞通常落在 0.5–0.9，不同两件事落在 0.1–0.35。
MATCH_THRESHOLD = 0.45

#: 第二条下界：二元组 Jaccard。防的是"模板句相同、内容不同"被算成同一件事
#: （实测：「只有 GLM 提到的东西」vs「只有 DeepSeek 提到的东西」字面比例 > 0.45，
#: 只看比例会把"各说各话"报成"两侧都提"——正好是联合会诊最该防的**假同意**）。
MIN_TOKEN_OVERLAP = 0.5


def parse_side(text: str) -> Optional[dict]:
    """一侧的原始正文 → JSON 对象；不是 JSON 返回 None（**不当成功**）。"""
    if not text or not text.strip():
        return None
    body = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", body, flags=re.S)
    if fence:
        body = fence.group(1).strip()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        #: 模型偶尔前后带一句解释：取第一个花括号到最后一个花括号再试一次。
        start, end = body.find("{"), body.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(body[start:end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def findings_of(payload: Optional[dict]) -> List[dict]:
    """从一侧的判词里取 findings（缺字段的补空串，保证后面可配对）。"""
    if not payload:
        return []
    out: List[dict] = []
    for index, item in enumerate(payload.get("findings") or [], start=1):
        if not isinstance(item, dict):
            continue
        out.append({
            "id": str(item.get("id") or f"F{index}"),
            "title": str(item.get("title") or ""),
            "claim": str(item.get("claim") or ""),
            "severity": str(item.get("severity") or "unknown"),
            "confidence": str(item.get("confidence") or "unknown"),
            "where": str(item.get("where") or ""),
        })
    return out


def _fingerprint(item: dict) -> str:
    """配对用的规范化指纹：只看标题＋结论（`where` 是引用，措辞差异大）。"""
    text = f"{item.get('title', '')} {item.get('claim', '')}".lower()
    return re.sub(r"[\s，。、；：,.;:!?！？*`\"'()\[\]（）]+", "", text)


def _bigrams(text: str) -> set:
    return {text[index:index + 2] for index in range(max(0, len(text) - 1))}


def similarity(a: str, b: str) -> Tuple[float, float]:
    """两条指纹的相似度：`(difflib 比例, 二元组 Jaccard)`。

    **为什么不能只看 `difflib`**：会诊里的 finding 常是"模板句 ＋ 内容"，例如
    「只有 GLM 提到的东西」与「只有 DeepSeek 提到的东西」——字面比例能过 0.45，
    但它们是两件不同的事。缺了第二条下界，配对会把"各说各话"报成"两侧都提"。
    """
    if not a or not b:
        return 0.0, 0.0
    if len(a) < 8 or len(b) < 8:
        #: 太短就没有词面统计可言：只有逐字相同才算同一件事。
        return (1.0, 1.0) if a == b else (0.0, 0.0)
    left, right = _bigrams(a), _bigrams(b)
    union = left | right
    return (difflib.SequenceMatcher(None, a, b).ratio(),
            (len(left & right) / len(union)) if union else 0.0)


def pair_findings(glm: Sequence[dict], deepseek: Sequence[dict],
                  threshold: float = MATCH_THRESHOLD,
                  min_overlap: float = MIN_TOKEN_OVERLAP) -> Dict[str, list]:
    """两侧 findings 逐条配对（**纯函数**，测试直接断言它，不联网）。

    四栏：`both`（同一件事且严重度一致）、`severity_conflict`（同一件事但严重度不同）、
    `glm_only` / `deepseek_only`（只有一侧提出）。**没有匹配上 ≠ 同意**。

    参数按**名字**而不是位置（2026-10-04 实测的教训：按位置时消费端把 `left`
    当成 DeepSeek 标反了列，测试当场抓到）。
    """
    left_items = [dict(item) for item in glm]
    right_items = [dict(item) for item in deepseek]
    scored: List[Tuple[float, int, int]] = []
    for i, a in enumerate(left_items):
        fa = _fingerprint(a)
        for j, b in enumerate(right_items):
            fb = _fingerprint(b)
            if not fa or not fb:
                continue
            ratio, overlap = similarity(fa, fb)
            if ratio >= threshold and overlap >= min_overlap:
                scored.append((ratio, i, j))
    scored.sort(reverse=True)
    used_left, used_right = set(), set()
    both: List[dict] = []
    conflict: List[dict] = []
    for ratio, i, j in scored:
        if i in used_left or j in used_right:
            continue
        used_left.add(i)
        used_right.add(j)
        pair = {"ratio": round(ratio, 3),
                "left": left_items[i], "right": right_items[j]}
        if left_items[i]["severity"] == right_items[j]["severity"]:
            both.append(pair)
        else:
            conflict.append(pair)
    return {
        "both": both,
        "severity_conflict": conflict,
        "glm_only": [item for i, item in enumerate(left_items) if i not in used_left],
        "deepseek_only": [item for j, item in enumerate(right_items) if j not in used_right],
    }


def render_panel(role_reports: Sequence[dict], *, glm_model: str,
                 deepseek_model: str, sources: Sequence[dict],
                 contexts: Sequence[Tuple[str, str]]) -> str:
    """人可读的会诊纪要（证据先写：哪一版、看了什么、两侧各说了什么、哪里分歧）。"""
    lines = ["# 联合会诊纪要（DeepSeek × GLM-5.3）", "",
             f"- 模型：`{deepseek_model}`（deepseek 族） × `{glm_model}`（zhipu 族）——**天然换族**",
             f"- 判词归属：`reviewed_by: {PANEL_TAG}`（**不是** human，也不冒充 human）",
             f"- 输入：{len(sources)} 份源码、{len(contexts)} 份产物；逐份 sha256 见 `bundle.manifest.json`",
             "- 纪律：**一侧缺席不算同意**；会诊结论不改判据/门限/阈值。", ""]
    for report in role_reports:
        lines += [f"## 角色：{report['role']}", ""]
        status = report["status"]
        lines.append(f"- 状态：deepseek=`{status['deepseek']}`，glm=`{status['glm']}`；"
                     f"完整={report['complete']}")
        if report.get("usage"):
            lines.append(f"- usage：{json.dumps(report['usage'], ensure_ascii=False)}")
        lines.append("")
        for key, title in (("both", "两侧都提（严重度一致）"),
                           ("severity_conflict", "两侧都提但**严重度不同**"),
                           ("glm_only", "只有 GLM-5.3 提"),
                           ("deepseek_only", "只有 DeepSeek 提")):
            items = report["pairs"].get(key) or []
            lines.append(f"### {title}（{len(items)}）")
            if not items:
                lines.append("（无）")
            for item in items:
                if "left" in item:
                    a, b = item["left"], item["right"]
                    lines.append(f"- **{a['title'] or a['id']}** ｜相似度 {item['ratio']}"
                                 f" ｜ deepseek: {a['severity']} / glm: {b['severity']}")
                    lines.append(f"  - deepseek：{a['claim']}")
                    lines.append(f"  - glm-5.3：{b['claim']}")
                else:
                    lines.append(f"- **{item['title'] or item['id']}**（{item['severity']}）："
                                 f"{item['claim']}")
            lines.append("")
    return "\n".join(lines)


def load_main_answer(path: str) -> Dict[str, dict]:
    """主线程（本身就是 DeepSeek）自己写的判词：`{role: payload}` 或带 `role` 的单份。"""
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("role") and "findings" in payload:
        return {str(payload["role"]): payload}
    if isinstance(payload, dict):
        return {str(key): value for key, value in payload.items()
                if isinstance(value, dict)}
    raise SystemExit(f"--main-answer 的形状不对：{path}")


def deepseek_caller(model: str) -> Callable[[List[dict]], Tuple[str, dict]]:
    """DeepSeek 侧：复用仓库既有客户端（密钥只从 `DEEPSEEK_API_KEY` 读）。"""
    from tools.kb_fetch import llm as kbllm

    def call(messages: List[dict]) -> Tuple[str, dict]:
        client = kbllm.DeepSeekClient(model)
        payload = client.chat_json(messages[0]["content"], messages[1]["content"],
                                   temperature=0.2, seed=0, num_ctx=8192,
                                   key="panel")
        return json.dumps(payload, ensure_ascii=False), {
            "model": client.model_version, "requested_model": model,
            "usage": dict(client.last_usage),
        }

    return call


def glm_caller(model: str, level: str, max_tokens: int,
               timeout: float) -> Callable[[List[dict]], Tuple[str, dict]]:
    """GLM 侧：走 `glm_consult` 的档位阶梯（`max → high → low` 逐档记 usage）。"""
    ladder = {"max": ["max", "high", "low"], "high": ["high", "low"],
              "low": ["low"]}[level]

    def call(messages: List[dict]) -> Tuple[str, dict]:
        return gc.consult(messages, model=model, max_tokens=max_tokens,
                          levels=ladder, temperature=0.2, timeout=timeout)

    return call


def relay_caller(model: str, max_tokens: int,
                 timeout: float) -> Callable[[List[dict]], Tuple[str, dict]]:
    """**中转站 GPT-6A** 侧：用户 2026-10-06 把"难题攻关／会诊／提出方案"也划给了它
    （原话："难题攻关和会诊gpt6A吧"＋"提出方案类用gpt6A，执行交给DeepSeek"）。

    与 GLM 侧的形状差别：**没有档位阶梯**（中转站没有那个开关），所以只做带退避的一次性调用；
    思考强度由 `RelayClient` 的 `reasoning_effort`（默认 `max`）保证——实测同一问题
    reasoning 40 → 1034 token（`work/_probe_linkai_thinking.py`）。
    """
    from tools import relay_consult as rc

    def call(messages: List[dict]) -> Tuple[str, dict]:
        return rc.consult(messages, model=model, max_tokens=max_tokens,
                          levels=["max"], temperature=0.2, timeout=timeout)

    return call


def run_role(role: str, question: str, contexts, sources, status_text: str,
             out_dir: Optional[pathlib.Path], *, glm_model: str, deepseek_model: str,
             glm_call: Callable, deepseek_call: Optional[Callable],
             main_answer: Optional[dict]) -> dict:
    """跑一个角色：两侧各一次，然后配对。（`out_dir=None` = dry-run，不写盘。）"""
    messages = gc.build_messages(role, question, contexts, sources, status_text)
    sides: Dict[str, Optional[dict]] = {"deepseek": None, "glm": None}
    usage: Dict[str, dict] = {}
    status: Dict[str, str] = {}
    raw: Dict[str, str] = {}

    if main_answer is not None:
        sides["deepseek"] = main_answer
        status["deepseek"] = "main-answer"
        usage["deepseek"] = {"model": "main-thread(deepseek)", "source": "main-answer"}
    elif deepseek_call is not None:
        try:
            text, info = deepseek_call(messages)
            raw["deepseek"] = text
            sides["deepseek"] = parse_side(text)
            usage["deepseek"] = info
            status["deepseek"] = "ok" if sides["deepseek"] else "unparsed"
        #: `SystemExit` 也要接住：仓库的通道用 `SystemExit` 报"缺 key / 没正文"
        #: （`glm_consult.ConsultFailed` 就是它的子类），漏掉就会把整次会诊打死，
        #: 而"一侧失败"本身是要记账的一等结果。
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            status["deepseek"] = "failed"
            usage["deepseek"] = {"error": f"{type(exc).__name__}: {exc}"}
    else:
        status["deepseek"] = "skipped"

    try:
        text, info = glm_call(messages)
        raw["glm"] = text
        sides["glm"] = parse_side(text)
        usage["glm"] = info
        status["glm"] = "ok" if sides["glm"] else "unparsed"
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - 同 DeepSeek 侧：失败要记账
        status["glm"] = "failed"
        usage["glm"] = {"error": f"{type(exc).__name__}: {exc}"}

    if out_dir is not None:
        for side, text in raw.items():
            (out_dir / f"{role}.{side}.json").write_text(text, encoding="utf-8")
        for side, info in usage.items():
            (out_dir / f"{role}.{side}.usage.json").write_text(
                json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    pairs = pair_findings(findings_of(sides["glm"]), findings_of(sides["deepseek"]))
    report = {
        "role": role,
        "status": status,
        #: 主线程自己答的那一侧记作 `main-answer`：它同样是**真判词**，算完整的一份。
        "complete": (status.get("glm") == "ok"
                     and status.get("deepseek") in ("ok", "main-answer")),
        "usage": usage,
        "pairs": pairs,
        "not_checked": {
            "glm": (sides["glm"] or {}).get("not_checked", []),
            "deepseek": (sides["deepseek"] or {}).get("not_checked", []),
        },
        "reviewed_by": PANEL_TAG,
    }
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="panel_consult")
    parser.add_argument("--roles", default="规格一致性",
                        help="逗号分隔；可用：" + ",".join(gc.ROLES))
    parser.add_argument("--question", required=True)
    parser.add_argument("--context", action="append", default=[])
    parser.add_argument("--context-tail", type=int, default=0)
    parser.add_argument("--source", action="append", default=[],
                        help="源码（可带行段）；不给就拒绝调用，除非 --question-only")
    parser.add_argument("--question-only", action="store_true")
    parser.add_argument("--no-status", action="store_true")
    parser.add_argument("--status-chars", type=int, default=gc.STATUS_MAX_CHARS)
    parser.add_argument("--repo", default=str(gc.REPO_ROOT))
    parser.add_argument("--out", required=True)
    parser.add_argument("--glm-model", default=gc.DEFAULT_MODEL)
    parser.add_argument("--partner", default="relay", choices=("glm", "relay"),
                        help="会诊的**第二侧**走哪条通道：`relay`（默认，中转站 GPT-6A——"
                             "用户 2026-10-06：\"难题攻关和会诊gpt6A吧\"、"
                             "\"提出方案类用gpt6A，执行交给DeepSeek\"）／"
                             "`glm`（GLM-5.3 档位阶梯，留作对拍与回退）。"
                             "**执行**永远只在主线的 DeepSeek 上做。")
    parser.add_argument("--partner-model", default="",
                        help="第二侧的型号（留空＝按 --partner 取：relay→gpt-6-astra、glm→glm-5.3）")
    parser.add_argument("--deepseek-model", default="deepseek-chat")
    parser.add_argument("--main-answer", default="",
                        help="主线程（DeepSeek）自己的判词文件；给了就不走 DeepSeek API")
    parser.add_argument("--level", default="high", choices=["low", "high", "max"])
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--timeout", type=float, default=1500.0)
    parser.add_argument("--match-threshold", type=float, default=MATCH_THRESHOLD)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    repo = pathlib.Path(args.repo)
    question = pathlib.Path(args.question).read_text(encoding="utf-8")
    contexts = gc.read_contexts(args.context, tail=args.context_tail)
    sources = [gc.read_source(spec, repo) for spec in args.source]
    if not sources and not args.question_only:
        raise SystemExit(
            "拒绝调用：这次会诊**没有源码**。请用 --source <文件[:起-止]> 至少给一份；"
            "真的只想问通用原理时，显式写 --question-only。")
    status_text = None if args.no_status else gc.cap_status(
        gc.status_digest(repo), args.status_chars)
    roles = [item.strip() for item in args.roles.split(",") if item.strip()]
    out_dir = pathlib.Path(args.out)
    manifest = gc.bundle_manifest(args.question, question, contexts, sources,
                                  status_text, None, repo)

    if args.dry_run:
        for role in roles:
            messages = gc.build_messages(role, question, contexts, sources, status_text)
            manifest.setdefault("bundles", {})[role] = gc.bundle_fingerprints(messages)
        print(json.dumps({"source_seen": manifest["source_seen"],
                          "roles": roles,
                          "heads": manifest["repo"]["head"],
                          "bundles": manifest.get("bundles", {})},
                         ensure_ascii=False))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    #: **先留证、再联网**：失败的那一轮也要留下"它看到了什么"。
    (out_dir / "bundle.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "bundle.md").write_text(
        gc.render_bundle([(role, gc.build_messages(role, question, contexts, sources,
                                                   status_text)) for role in roles]),
        encoding="utf-8")

    main_answers = load_main_answer(args.main_answer) if args.main_answer else {}
    #: 第二侧的通道与型号：用户 2026-10-06 把"难题攻关／会诊／提出方案"划给中转站 GPT-6A
    #: （`--partner relay`，默认），GLM-5.3 留作对拍与回退（`--partner glm`）。
    #: 显式给了 `--partner-model` 就听显式的；再显式给了 `--glm-model` 也听显式的（老调用方兼容）。
    if args.partner_model:
        partner_model = args.partner_model
    elif args.partner == "glm":
        partner_model = args.glm_model
    else:
        from tools import relay_consult as rc
        partner_model = rc.DEFAULT_MODEL
    if args.partner == "glm":
        glm_call = glm_caller(partner_model, args.level, args.max_tokens, args.timeout)
    else:
        glm_call = relay_caller(partner_model, args.max_tokens, args.timeout)
    deepseek_call = None if args.main_answer else deepseek_caller(args.deepseek_model)

    reports: List[dict] = []
    for role in roles:
        report = run_role(role, question, contexts, sources, status_text, out_dir,
                          glm_model=partner_model, deepseek_model=args.deepseek_model,
                          glm_call=glm_call, deepseek_call=deepseek_call,
                          main_answer=main_answers.get(role))
        reports.append(report)
        print(json.dumps({"role": role, "status": report["status"],
                          "both": len(report["pairs"]["both"]),
                          "severity_conflict": len(report["pairs"]["severity_conflict"]),
                          "glm_only": len(report["pairs"]["glm_only"]),
                          "deepseek_only": len(report["pairs"]["deepseek_only"])},
                         ensure_ascii=False))

    panel = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "reviewed_by": PANEL_TAG,
        "models": {"deepseek": args.deepseek_model, "glm": args.glm_model},
        "partner": {"channel": args.partner, "model": partner_model},
        "families": {"deepseek": "deepseek",
                     "partner": ("zhipu" if args.partner == "glm" else "relay")},
        "source_seen": manifest["source_seen"],
        "sources": [item["name"] for item in manifest["sources"]],
        "complete": all(item["complete"] for item in reports),
        "roles": reports,
    }
    (out_dir / "panel.json").write_text(
        json.dumps(panel, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "panel.md").write_text(
        render_panel(reports, glm_model=partner_model,
                     deepseek_model=args.deepseek_model,
                     sources=sources, contexts=contexts),
        encoding="utf-8")
    return 0 if panel["complete"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
