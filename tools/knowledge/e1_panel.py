"""E1（经验引用相关性 ≥70%）的**打分通道**：把一次真实运行的逐镜查询与案例层召回的案例打分。

为什么要有这个工具（而不是留在 `work/` 里）
==========================================
链上 `tools/run_tests.ps1` 的 `quality.py --e1-reviews <file>` 消费的是**这个工具
产出的文件**，而在此之前那份文件是由 `work/zz_e1_panel.py` ＋ `work/zz_e1_zh_measure.py`
两个**未跟踪**的临时脚本生成的——"链的输入来自一个不在库里的脚本"就是
`ACCEPTANCE_STATUS.md` §24.1 那个"过期证据被当成现行证据"的同一形状：没人能复算，
也没人能在换代之后重跑。本工具把它固化下来。

判据（与 §2.3b 一致，一个字没改）
================================
* 单位是**逐镜**：查询取每一镜自己的散文（编辑器喂给 L3 的那段 `analogy`），
  不是计划期那种把整段剧本塞进去的串（那种串判官只能答"不知道"）。
* 召回 `top_k` 条案例，**两个不同族**的模型（默认 deepseek-chat ＋ glm-5.3，
  见 `DEFAULT_PANEL`——本账号的智谱资源包只覆盖 `glm-5.3`）
  逐条打 1–5 分；`score ≥ 4` 记为相关。
* 每条记录写明 `reviewed_by: "llm-panel"`（**绝不冒充 `human`**）、面板模型、
  提示指纹，以及**这一份案例索引的指纹**——`quality.py::e1_evidence_is_stale`
  靠后者判"这批打分是不是这一代语料"，缺了只能记 `stale_evidence`。

用法::

  python tools/knowledge/e1_panel.py --project <run>/project/project.bdproj \
      --out docs/evidence/<run>/e1_reviews.jsonl
  python tools/knowledge/e1_panel.py --queries work/queries.txt --out ...      # 手给查询
  python tools/knowledge/e1_panel.py ... --scripted work/stub.json             # 离线自测
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.cases import load_index  # noqa: E402
from tools.kb_fetch import llm  # noqa: E402

#: L3 相关性过滤器的**判据提示词**（单一真源：产品 sidecar 的那一份）。
#: 这里只 import 文本，**不重写一份**——过滤器的判据与产品必须逐字相同，
#: 否则"E1 带过滤"量的就不是产品会做的事。
from tools.sidecar_server import CASE_FILTER_SYSTEM  # noqa: E402

#: 用户裁决（2026-10-04）：**GLM 只用 `glm-5.3`**——智谱的资源包按模型分开计费，
#: 这个账号下只有 `glm-5.3` 还有额度（`glm-4.7` 会 429「余额不足或无可用资源包」，
#: 实测见 `docs/knowledge/ACCEPTANCE_STATUS.md` §七十八）。
DEFAULT_PANEL = ("deepseek-chat", "glm-5.3")
DEFAULT_FAMILIES = ("deepseek", "glm")
RELEVANT = 4.0
#: 判分是**逐查询独立**的，所以并发只改吞吐、不改产物（行序仍按查询序）。
#: 默认 4：实测串行跑一次 64 查询 × 2 模型要一小时以上，通道就没法复算了；
#: 4 是"比串行快得多、又不至于把上游打成 429"的折中（429 由客户端长退避兜底）。
DEFAULT_WORKERS = 4

SYSTEM = (
    "你是分镜预演工具的知识检索复核员。下面给你一条**导演查询串**和若干条被检索回来的"
    "**参考案例**。请判断每条案例对这条查询是否**真的相关**（能不能拿来指导这一次拍摄）。\n"
    "只输出 JSON：{\"scores\":[{\"case_id\":\"...\",\"score\":1-5,\"reason\":\"不超过 20 字\"}]}\n"
    "5=直接相关且可照做；4=相关；3=沾边；2=几乎无关；1=完全无关。"
)


def queries_from_project(path: pathlib.Path) -> List[str]:
    """每一镜的散文查询（`prompt`）——**与编辑器喂给 L3 的那段文字同源**。

    `shots.json`（交付清单）不带 `prompt`，所以这里读的是工程文件 `project.bdproj`。
    计划期那种"剧本《…》：4 场…"的串被丢掉：它把整段剧本塞进 query，
    判官无从判断"这条案例相关吗"。
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    shots = [shot for scene in payload.get("scenes") or []
             for shot in (scene.get("shots") or [])]
    out: List[str] = []
    for shot in shots:
        text = str(shot.get("prompt") or "").strip()
        if text and "剧本《" not in text and text not in out:
            out.append(text)
    return out


def queries_from_lines(path: pathlib.Path) -> List[str]:
    out: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and text not in out:
            out.append(text)
    return out


def make_llm_case_filter(*, model: str, provider: str = "deepseek",
                         client=None) -> Callable[[str, Sequence[Any]], List[Any]]:
    """装配 L3 的**相关性过滤器**（`--cases-filter llm`），判据用产品那条提示词。

    为什么要有这条缝（2026-10-05）：E1 是**精确率**指标，而产品在把参考案例塞给模型前
    会走一遍"只留能沾上这一镜拍法的"过滤（`tools/sidecar_server.py::make_case_filter`，
    `--cases-filter llm`）。可**E1 面板一直没装过滤器**——也就是说：
    红线 0.70 到底够不够得着，我们量的从来是"未过滤"的那一路。
    过滤器**只许做减法**（`CaseIndex._filtered` 会把不属于入参的结果剔掉），
    所以它不可能"造"案例；失败的具名降级也在那里（`filter_reason`）。

    诚实提醒（写进报告，不写进代码）：过滤器的模型若与**评委**同族，
    评委就会倾向于同意过滤器的取舍——所以本工具每行都留着**逐评委分数**
    （`scores`），报告里可以只用"与过滤器不同族的那位评委"复核。
    """
    judge_client = client or llm.make_client(provider, model)

    def _filter(query: str, cases):
        listing = "\n".join("%s｜%s" % (case.case_id, str(case.excerpt)[:160])
                            for case in cases)
        reply = judge_client.chat_json(
            CASE_FILTER_SYSTEM, "查询：%s\n\n候选：\n%s" % (query, listing), 0.0, 0, 512)
        keep = {str(item) for item in (reply.get("keep") or [])}
        return [case for case in cases if str(case.case_id) in keep]

    return _filter


def rerank_cases(scorer, query: str, cases, keep: int):
    """按重排分取前 `keep` 条——**只做减法**，并列按 `case_id` 定序（确定性）。

    为什么是"取前 keep"而不是"过滤"：R3 的算术（`docs/evidence/20261005-e1-filter/`）
    说明在 top-3 上再过滤到不了 0.70；能改变结论的是"**哪 3 条被返回**"——
    先取宽候选（如 20 条）再重排取 3，才是成熟做法（retrieve-then-rerank）。
    本函数是纯函数：scorer 由调用方注入，离线可测。
    """
    items = list(cases)
    if not items:
        return []
    scores = list(scorer(query, items))
    if len(scores) != len(items):
        raise ValueError("重排分与候选数不匹配：%d != %d" % (len(scores), len(items)))
    order = sorted(range(len(items)),
                   key=lambda index: (-float(scores[index]),
                                      str(items[index].case_id)))
    return [items[index] for index in order[:max(1, int(keep))]]


def load_cross_encoder(model_name: str = "BAAI/bge-reranker-v2-m3",
                       device: str = ""):
    """加载 cross-encoder 重排器。**延迟 import**：主环境零依赖，只有 venv 里跑得动。

    实测约束（本机）：`huggingface.co` 不可达、`hf-mirror.com` 通 ⇒ 先设 `HF_ENDPOINT`；
    sidecar 的 venv 里已有 `torch 2.5.1+cu121`（`cuda.is_available()==True`）与
    transformers ⇒ 重排器是**跑得动**的（放进 sidecar 或构建期，插件进程依旧零依赖）。
    确定性：`model.eval()` ＋ `torch.no_grad()` ＋ 不采样 ⇒ 同一输入同一分数。
    """
    import os

    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    chosen = device or ("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name).to(chosen)
    model.eval()

    def score(query: str, cases):
        pairs = [(str(query), str(case.excerpt)) for case in cases]
        batch = tokenizer([left for left, _ in pairs], [right for _, right in pairs],
                          padding=True, truncation=True, max_length=512,
                          return_tensors="pt")
        batch = {key: value.to(chosen) for key, value in batch.items()}
        with torch.no_grad():
            logits = model(**batch).logits.view(-1)
        return [float(value) for value in logits]

    return score


LLM_RERANK_SYSTEM = (
    "你是分镜预演工具的参考案例排序员。给你一条**导演的镜头查询**与若干条候选案例，"
    "请按「**能不能拿来指导这一镜怎么拍**」从最有用到最没用排序。\n"
    "判据：景别／机位／运镜／构图／光线／剪辑节奏／表演调度上对得上就排前面；"
    "只是气氛像、剧情叙述、演员轶事、或讲的完全是另一回事的排后面。\n"
    "**必须把给出的 id 一个不漏地排完**，只输出 JSON："
    "{\"order\":[\"<id>\", ...]}（按你的排序，最有用在前）。"
)

#: 另两种**重排提示词形状**（2026-10-06 要对照的变量）：`select` ＝ 只挑最该看的 3 条；
#: `score` ＝ 逐条打 0–10 分。为什么要试：已测的"全序排序"只拿到**上限的 36%**
#: （0.2812 / 0.7760，见 `docs/evidence/20261006-e1-ceiling/`），而让一个模型把 20 条
#: 一次排全序是它最容易出错的任务形状——挑选/打分都比全序稳。
LLM_RERANK_SELECT_SYSTEM = (
    "你是分镜预演工具的参考案例挑选员。给你一条**导演的镜头查询**与若干条候选案例，"
    "请**只挑出最该给这位导演看的 3 条**（按有用程度从高到低），其余不要列。\n"
    "判据：能拿来指导**这一镜怎么拍**（景别／机位／运镜／构图／光线／剪辑节奏／表演调度）"
    "的才挑；只是气氛像、剧情叙述、演员轶事、或讲的完全是另一回事的不要挑。\n"
    "只输出 JSON：{\"best\":[\"<id>\",\"<id>\",\"<id>\"]}"
)

LLM_RERANK_SCORE_SYSTEM = (
    "你是分镜预演工具的参考案例评分员。给你一条**导演的镜头查询**与若干条候选案例，"
    "请给**每一条**打 0–10 分（10 ＝ 直接能指导这一镜怎么拍；0 ＝ 完全无关）。\n"
    "判据：能对上景别／机位／运镜／构图／光线／剪辑节奏／表演调度的给高分；"
    "只是气氛像、剧情叙述、演员轶事的给低分。\n"
    "只输出 JSON：{\"scores\":{\"<id>\":<0-10>, ...}}——**每一条候选都要有分**。"
)

RERANK_PROMPTS = {"order": LLM_RERANK_SYSTEM, "select": LLM_RERANK_SELECT_SYSTEM,
                  "score": LLM_RERANK_SCORE_SYSTEM}


def _case_fields(case, *, with_title: bool) -> str:
    """候选清单里"这条案例长什么样"的那一段。

    `with_title=False`（默认）＝ `excerpt[:160]`，与历次重排读数逐字同口径。
    `with_title=True` ＝ `title[:60]｜excerpt[:220]`——**与 E1 的评委看到的一模一样**
    （见 `judge()`；注意 `Case` **没有** `summary` 字段，所以评委那边那个
    `getattr(case,"summary","")` 永远拿到空串、退回 `excerpt`——这里照它的**实际行为**对齐）。

    为什么要有它（2026-10-06 实测出来的第二处信息缺口）：重排器原先只拿到 160 字符的英文摘录，
    而**评委看得到标题与 220 字符**。也就是说"挑哪 3 条"的那个组件，**手里的信息比打分的那个更少**——
    这没有任何理由，只会把重排器人为削弱。
    """
    if not with_title:
        return str(getattr(case, "excerpt", "") or "")[:160]
    title = str(getattr(case, "title", "") or "")[:60]
    #: 照 `judge()` 的**实际行为**对齐：`Case` 没有 `summary` 字段 ⇒ 那边永远退回 `excerpt`。
    body = str(getattr(case, "summary", "") or getattr(case, "excerpt", "") or "")[:220]
    return "%s｜%s" % (title, body)


def _clue_suffix(clue_of, case) -> str:
    """给出"中文线索"那一格（没有就返回空串）。

    为什么需要它（2026-10-06，本轮最大的一处"信息没给到"）：重排器原来的候选清单只有
    `case_id｜excerpt[:160]`——**摘录是英文，而导演的查询是中文**。也就是说重排器被要求
    在**看不到中文线索**的情况下跨越语种判断相关性；而案例层的 `search_zh`（英文摘录的
    中文蒸馏）**本来就是 BM25 那一侧在用的对齐面**。把它一并交给重排器，就是把这个
    已经存在的对齐面从"检索侧"延伸到"重排侧"——不是放宽判据，是把**信息补齐**。

    `clue_of=None` ⇒ 返回空串 ⇒ 与历次读数逐字同口径。
    """
    clue = _clue_text(clue_of, case)
    return ("｜" + clue) if clue else ""


def _clue_text(clue_of, case) -> str:
    """取该案例的**中文线索原文**（没有就空串）。"""
    if clue_of is None:
        return ""
    try:
        return str(clue_of(str(case.case_id)) or "").strip()
    except Exception:  # noqa: BLE001 - 线索取不到就退回无线索，不许吞掉重排
        return ""


def load_embedder(model_name: str = "BAAI/bge-small-zh-v1.5", device: str = ""):
    """加载**中文嵌入器**（延迟 import；主环境零依赖，只有 venv 里跑得动）。

    为什么走这条路（2026-10-06，P14-226 的结论）：`deepseek-chat` 那条"大模型读清单挑 3 条"
    的重排**六种配置全试过、见顶在 ~0.44**（上限 0.8438 的 52～55%），换形状/补信息/拆批次
    都推不动。而 D3 实测过：**同一路由换更好的嵌入器，E1 提高约 5.6 倍** ⇒ 嵌入这一侧
    才是没被压榨过的地方。它还有两个附带好处：**确定性**（同输入同分数，可复现）与
    **与两位评委不同族**（把"同族自证"那条折扣也去掉）。

    `bge` 系列的推荐池化是取 `[CLS]`（`last_hidden_state[:, 0]`），本函数照它做。
    """
    import os

    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    import torch
    from transformers import AutoModel, AutoTokenizer

    chosen = device or ("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).to(chosen)
    model.eval()

    def encode(texts):
        batch = tokenizer(list(texts), padding=True, truncation=True,
                          max_length=512, return_tensors="pt")
        batch = {key: value.to(chosen) for key, value in batch.items()}
        with torch.no_grad():
            hidden = model(**batch).last_hidden_state
        return [[float(value) for value in row] for row in hidden[:, 0]]

    return encode


def make_embedding_reranker(*, model_name: str = "BAAI/bge-small-zh-v1.5",
                            device: str = "", clue_of=None, encoder=None):
    """**嵌入重排**：查询与候选各编码一次，按余弦排序（确定性、便宜、与评委不同族）。

    被编码的候选文本＝**该案例的中文线索**（`search_zh`）；没有线索的案例退回英文摘录。
    查询是中文 ⇒ 与中文线索在同一语种面上比，绕开"中文查询 vs 英文摘录"那道跨语种鸿沟。
    """
    encode = encoder or load_embedder(model_name, device=device)

    def scorer(query: str, cases):
        items = list(cases)
        texts = [(_clue_text(clue_of, case) or str(getattr(case, "excerpt", "") or ""))
                 for case in items]
        vectors = encode([str(query)] + texts)
        query_vector = _unit(vectors[0])
        return [_dot(query_vector, _unit(vector)) for vector in vectors[1:]]

    return scorer


def _unit(vector):
    norm = sum(float(value) * float(value) for value in vector) ** 0.5
    if norm <= 0:
        return [0.0 for _ in vector]
    return [float(value) / norm for value in vector]


def _dot(left, right) -> float:
    return float(sum(a * b for a, b in zip(left, right)))


def _llm_rerank_label(args) -> str:
    """重排的自述标签：**默认路径逐字节不变**，只有开了非默认开关才往后缀加记号。"""
    label = "%s/%s" % (args.rerank_llm_model, args.rerank_llm_prompt)
    if int(args.rerank_llm_max_tokens) != 1024:
        label += "@%d" % int(args.rerank_llm_max_tokens)
    if args.rerank_clue == "on":
        label += "+clue"
    if args.rerank_title == "on":
        label += "+title"
    if int(args.rerank_llm_stages) >= 2:
        label += "+2stage%d/%d" % (int(args.rerank_llm_chunk), int(args.rerank_llm_keep))
    return label


def make_llm_reranker(*, model: str, provider: str = "qwen", client=None,
                      prompt: str = "order", max_tokens: int = 1024,
                      clue_of=None, with_title: bool = False,
                      stages: int = 1, chunk: int = 10, keep_per_chunk: int = 3):
    """用 LLM 给宽候选**排序**（`--cases-rerank llm`），返回打分可调用对象。

    为什么是"排序"而不是产品那个"过滤"：R3 的算术说明**删行**改变不了"哪 3 条被返回"
    这一步（要 91% 无关行识别率＋100% 相关行召回）；把 20 条候选**整体排序**再取前 3，
    才是能动结论的那一步。判据提示词与产品的 `CASE_FILTER_SYSTEM` 同源精神
    （"能不能指导这一镜怎么拍"），但**形状不同**（有序列表 vs keep 集合）——
    所以这里是一份独立的、可对拍的提示词，而不是把那份改掉。

    族别：默认走 `qwen`（阿里云百炼 **`qwen3.8-max`**）——它**既不是评委**
    （deepseek-chat／glm-5.3）也不是抽取器（deepseek），所以"重排把 E1 抬上去"
    不可能是"重排者和评委同族"造出来的假象。
    """
    if prompt not in RERANK_PROMPTS:
        raise ValueError("未知重排提示词形状：%r（只认 %s）"
                         % (prompt, sorted(RERANK_PROMPTS)))
    judge_client = client or llm.make_client(provider, model)
    system = RERANK_PROMPTS[prompt]

    def _listing(query: str, items) -> str:
        return "查询：%s\n\n候选：\n%s" % (
            query, "\n".join("%s｜%s%s" % (case.case_id,
                                           _case_fields(case, with_title=with_title),
                                           _clue_suffix(clue_of, case))
                             for case in items))

    def _ask_select(query: str, items):
        """`select` 那一问：返回模型点名的 id 序列（漏写的 id 由调用方垫底）。"""
        reply = judge_client.chat_json(system, _listing(query, items), 0.0, 0,
                                       int(max_tokens))
        order = [str(item) for item in (reply.get("best") or [])]
        if not order:
            raise llm.LLMError("重排器没有给出 best")
        return order

    def scorer(query: str, cases):
        items = list(cases)
        #: **两段式**（`--rerank-llm-stages 2`）：把"一次从 50 条里挑 3 条"拆成
        #: "每次看 `chunk` 条各挑 `keep_per_chunk` 条，再到幸存者里挑 3 条"。
        #: 为什么试它（2026-10-06 实测）：`order`（全序）在 50 条上只有 0.2760，
        #: 说明"一次看太长的清单"本身就是重排器的弱点；而**线索与标题都补过了、没有再涨**
        #: ⇒ 缺口在"单次挑"这件事上，不在"少看了什么"。所以拆小。
        if int(stages) >= 2 and prompt == "select" and int(chunk) > 0 \
                and len(items) > int(chunk):
            survivors = []
            seen = set()
            for start in range(0, len(items), int(chunk)):
                group = items[start:start + int(chunk)]
                for case_id in _ask_select(query, group)[:int(keep_per_chunk)]:
                    if case_id in seen:
                        continue
                    for case in group:
                        if str(case.case_id) == case_id:
                            seen.add(case_id)
                            survivors.append(case)
                            break
            pool = survivors or items[:int(chunk)]
            order = _ask_select(query, pool)
            rank = {case_id: index for index, case_id in enumerate(order)}
            scores = []
            for position, case in enumerate(items):
                case_id = str(case.case_id)
                if case_id in rank:
                    scores.append(float(len(order) - rank[case_id]))
                else:
                    #: 没进第二段的**垫底**（与单段那套同一约定：只改序，不丢）。
                    scores.append(-1.0 - position / 1000.0)
            return scores
        listing = "\n".join("%s｜%s%s" % (case.case_id,
                                          _case_fields(case, with_title=with_title),
                                          _clue_suffix(clue_of, case))
                            for case in items)
        reply = judge_client.chat_json(system, "查询：%s\n\n候选：\n%s" % (query, listing),
                                       0.0, 0, int(max_tokens))
        if prompt == "score":
            raw = reply.get("scores") or {}
            if not isinstance(raw, dict) or not raw:
                raise llm.LLMError("重排器没有给出 scores")
            out = []
            for position, case in enumerate(items):
                value = raw.get(case.case_id)
                out.append(float(value) if isinstance(value, (int, float))
                           else -1.0 - position / 1000.0)   # 漏写 = 垫底（不丢）
            return out
        if prompt == "select":
            order = [str(item) for item in (reply.get("best") or [])]
            if not order:
                raise llm.LLMError("重排器没有给出 best")
        else:
            order = [str(item) for item in (reply.get("order") or [])]
            if not order:
                raise llm.LLMError("重排器没有给出 order")
        rank = {case_id: index for index, case_id in enumerate(order)}
        total = len(order)
        scores = []
        for position, case in enumerate(items):
            if case.case_id in rank:
                #: 名次越靠前分越高（`rerank_cases` 按分数降序取前 k）。
                scores.append(float(total - rank[case.case_id]))
            else:
                #: 模型漏写的 id **垫底而不是丢掉**（垫到所有已排名的下面，序仍确定）——
                #: 重排只许改变次序；裁到 top-k 是 `rerank_cases` 的事。
                scores.append(-1.0 - position / 1000.0)
        return scores

    return scorer


QUERY_EXPAND_SYSTEM = (
    "你是电影/动画分镜检索的查询改写员。给你一条**中文的镜头指令**（导演要拍什么），"
    "把它改写成**一段英文检索串**，用来在**英文学术／教程摘录**里做词面检索。\n"
    "要求：\n"
    "1. 只搬运这条指令里已有的信息（景别／机位／运镜／构图／光线／剪辑节奏／表演调度／"
    "画面里发生的事），**不要解释、不要评论、不要补充指令里没有的内容**；\n"
    "2. 用这些工艺词在英文影评／教程里的通行说法（例如 固定机位→static tripod shot、"
    "越轴→crossing the line、反打→reverse shot、浅景深→shallow depth of field）；\n"
    "3. 不要写完整句子，写成一串**检索词／短语**（逗号或空格分隔）；\n"
    "4. 别丢掉专有名词与数字（镜头号、毫米数、时间）。\n"
    "只输出 JSON：{\"en\": \"<英文检索串>\"}"
)


def make_query_expander(*, model: str, provider: str = "deepseek", client=None):
    """把中文镜头指令改写成**英文学术摘录能词面命中的检索串**（查询侧对齐）。

    为什么这条值得试（三条杠杆的实测）：产品自带的 LLM 过滤与 `ms-marco` 系
    cross-encoder 都让 E1 **下降**，而"让模型读懂中文指令↔英文摘录的关系"那一条
    （第三方 LLM 重排）把 E1 从 0.1927 抬到 0.2812 ⇒ 真正稀缺的是**两边的对齐**。
    案例侧已经有一条（中文线索：把英文摘录改写成中文），**查询侧还没有**——
    这条缝补的就是它：把中文指令改写成英文工艺词，让 BM25 直接命中**摘录自己的词**。

    只改**检索串**：判分用的查询仍是冻结的那 64 条原文（行里两条都记，
    `query` 与 `query_retrieval`），提示词要求只搬运、不解释、不编造。
    """
    expander = client or llm.make_client(provider, model)

    def expand(query: str) -> str:
        reply = expander.chat_json(QUERY_EXPAND_SYSTEM,
                                   "中文镜头指令：%s" % query, 0.0, 0, 512)
        return str(reply.get("en") or "").strip()

    return expand


def judge(client, query: str, cases) -> Dict[str, Dict[str, Any]]:
    listing = "\n".join(
        "%s｜%s｜%s" % (case.case_id, str(getattr(case, "title", ""))[:60],
                       str(getattr(case, "summary", "")
                           or getattr(case, "excerpt", ""))[:220])
        for case in cases)
    #: `key=query` 是给 `scripted` 后端用的：离线用例按查询串取预置回答，
    #: 测试因此**不用碰网络**（生产后端忽略这个参数）。
    reply = client.chat_json(SYSTEM, "查询串：%s\n\n案例：\n%s" % (query, listing),
                             0.0, 0, 2048, key=query)
    out: Dict[str, Dict[str, Any]] = {}
    for row in reply.get("scores") or []:
        if isinstance(row, dict) and row.get("case_id") is not None:
            out[str(row["case_id"])] = row
    return out


def _score_one(index, query: str, clients: Sequence[tuple],
               top_k: int, rerank=None, retrieve_k: int = 0,
               rerank_label: str = "", expand=None,
               expand_mode: str = "union", judge_batch: int = 0
               ) -> List[Dict[str, Any]]:
    """一条查询的打分行（逐镜）。失败侧在 `scores` 里留 ``None``，不写成 1 分。

    `rerank` 给了就**先取宽候选**（`retrieve_k` 条）再重排取 `top_k` 条——
    retrieve-then-rerank；没给就与历次读数逐字同口径（`index.retrieve(query, top_k)`）。

    **`judge_batch`（判分语境 C，2026-10-06 新增）**：把"**每次判分调用喂几条候选**"
    从 `--top-k` 里拆出来。为什么要拆：`docs/evidence/20261006-e1-judge-context/` 实测
    评委的给分**随这次调用看到的候选条数上漂**（同一检索、同内容、同提示词：
    k=3 → E1 0.177～0.193、k=20 → 0.271～0.302、k=50 → 0.3177，**单调**），
    于是"完美重排上限"（在 20 条语境里量的）与红线 E1（在 3 条语境里量的）
    **不是一把尺子**。固定 C、把池子按连续 C 元组重判，两者才同尺。
    尾部**不满一批**的那些**不入证**（它们是另一种语境），条数记在每行的
    `partial_batch_dropped` 里。默认 0 ⇒ C ＝ `len(cases)`，与历次读数逐字同口径。
    """
    rows: List[Dict[str, Any]] = []
    #: **查询侧对齐**：判分用的 `query` 一个字不动；只把**检索串**换成"原文 ＋ 英文改写"
    #: （`replace` 档只留改写）。失败具名降级回原文。
    retrieval_query = str(query)
    expansion = ""
    expand_label = "off"
    if expand is not None:
        expand_label = "on"
        try:
            expansion = str(expand(query) or "").strip()
        except Exception as exc:  # noqa: BLE001 - 增强失败不吞检索
            expansion = ""
            expand_label = "failed:%s" % type(exc).__name__
        if expansion:
            retrieval_query = (expansion if str(expand_mode) == "replace"
                               else "%s %s" % (query, expansion))
    wide = int(retrieve_k) if (rerank is not None and int(retrieve_k) > 0) else int(top_k)
    cases = index.retrieve(retrieval_query, top_k=wide)
    if rerank is not None:
        try:
            cases = rerank_cases(rerank, query, cases, top_k)
        except Exception as exc:  # noqa: BLE001 - 重排是增强，失败要具名且不吞掉检索
            #: 具名降级：退回**未重排**的前 `top_k`（不是空列表），原因写进每行。
            rerank_label = "failed:%s" % type(exc).__name__
            cases = list(cases)[:int(top_k)]
    if not cases:
        return rows
    #: 判分语境：`judge_batch>0` 时按连续 N 元组切；否则整批一次判（历次口径）。
    requested = int(judge_batch or 0)
    batch = requested if requested > 0 else len(cases)
    if requested > 0:
        chunks = [list(cases)[i:i + batch] for i in range(0, len(cases), batch)]
        full = [chunk for chunk in chunks if len(chunk) == batch]
        partial_batch_dropped = sum(len(chunk) for chunk in chunks if len(chunk) != batch)
        cases = [case for chunk in full for case in chunk]
    else:
        full = [list(cases)]
        partial_batch_dropped = 0
    verdicts: Dict[str, Dict[str, Any]] = {}
    for chunk in full:
        for name, client in clients:
            try:
                verdicts.setdefault(name, {}).update(judge(client, query, chunk))
            except Exception as exc:  # noqa: BLE001 — 单条失败不吞掉整批
                #: 失败的那一批**只让那几条没有分**（行被跳过），不抹掉其他批次的判决。
                #: 单批时（默认口径）这条路与旧实现逐字等价：verdicts[name] 就是错误标记。
                verdicts.setdefault(name, {})["__error__"] = \
                    f"{type(exc).__name__}: {exc}"[:120]
    for case in cases:
        scores = [verdicts.get(name, {}).get(str(case.case_id), {}).get("score")
                  for name, _client in clients]
        numbers = [float(s) for s in scores if isinstance(s, (int, float))]
        if not numbers:
            continue
        rows.append({
            "case_id": str(case.case_id), "query": query,
            "zh": str(getattr(index, "search_zh", {}).get(str(case.case_id), "")),
            "excerpt": str(getattr(case, "excerpt", "") or "")[:200],
            "scores": scores,
            "score": sum(numbers) / len(numbers),
            "reviewed_by": "llm-panel",
            #: `quality.e1_evidence_is_stale` 要求每条自带**这一份**索引的指纹。
            "cases_fingerprint": str(getattr(index, "fingerprint", "") or ""),
            #: **案例集合**的摘要（2026-10-05 会诊 D1）。`cases_fingerprint` 是
            #: **语料**指纹：只换案例集合（`--max-cases`/闸门/线索）它一个字都不变，
            #: 于是"上一代索引上的打分"会被当成现行证据（实测：案例 810→1097 时
            #: `cases_digest` 由 `e1148200…` 变 `227869414e0e014b…`，而
            #: `manifest.fingerprint` 仍是 `69791dbacd…`，E1 照报旧读数的 0.0885）。
            #: 这枚摘要只有"案例集合"能改，所以它才是代际的真钥匙。
            "cases_digest": str(getattr(index, "cases_digest", "") or ""),
            #: **线索层的状态**（`read_search_zh` 的第二个返回值）。空串 = 线索可用；
            #: 其余是具名原因（`search_zh_missing` / `search_zh_stale` / …）。
            #: 为什么每条都要带（2026-10-05 实测）：v4 案例层整份缺中文线索时，
            #: 三臂 E1 从 0.20 塌到 0.0065，而产物里**没有一行**写着原因——
            #: 每行只有一个空的 `zh`。判分记录必须自证"这一代索引的线索层是什么状态"。
            "clue_state": str(getattr(index, "search_zh_reason", "") or ""),
            "clues": len(getattr(index, "search_zh", None) or {}),
            #: 这次检索走的是哪条路（`hybrid` = 产品现行的 BM25；`lexical` = 零依赖适配器）。
            #: 判分必须能自证"测的是哪条路"，否则两条路的读数会混在一份证据里。
            "retrieval_path": str(getattr(index, "path_label", "") or ""),
            #: **实际干活的后端**与降级原因。`retrieval_path` 是"请求的臂"，而
            #: LightRAG 一失败 `CaseIndex.retrieve` 就退回 BM25——2026-10-05 实测：
            #: sidecar 的常驻事件循环缺陷让 5773 次查询抛 `bound to a different
            #: event loop`，**退回 BM25 的那些行仍被标成 `lightrag`**。请求的臂与
            #: 实际干的活必须分开写，否则"这条臂不行"与"这条臂根本没跑到"会混成
            #: 同一个结论（这正是 D8 要判的那件事）。
            "cases_backend_effective": str(getattr(index, "effective", "") or ""),
            "cases_degrade_reason": str(getattr(index, "reason", "") or ""),
            #: 这一跑的 L3 相关性过滤器**开着没有**、以及它自己报的降级原因
            #: （`CaseIndex._filtered` 在过滤器抛错时退回未过滤并具名记账）。
            "cases_filter": "on" if getattr(index, "case_filter", None) else "off",
            "cases_filter_reason": str(getattr(index, "filter_reason", "") or ""),
            #: 重排的自述：用的什么模型、取了多少条候选（`off` 就是历次口径）。
            "cases_rerank": str(rerank_label or "off"),
            "cases_retrieve_k": int(wide),
            #: 查询侧对齐的自述：判分查询、实际检索串、改写文本、以及它是开着的还是挂了。
            "query_expand": expand_label,
            "query_retrieval": retrieval_query,
            "query_expansion": expansion,
            "panel": [name for name, _client in clients],
            "prompt_sha256": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest(),
            #: **判分语境自述**（P14-205）：这次调用喂了几条候选（C）与尾部被丢了几条。
            #: 为什么要写进产物：不写的话"这把尺子是哪一把"事后只能靠重做配对实验才知道。
            "judge_batch": int(batch),
            "partial_batch_dropped": int(partial_batch_dropped),
        })
    return rows


def score_queries(index, queries: Sequence[str], clients: Sequence[tuple], *,
                  top_k: int = 3, workers: int = DEFAULT_WORKERS,
                  rerank=None, retrieve_k: int = 0, rerank_label: str = "",
                  expand=None, expand_mode: str = "union", judge_batch: int = 0
                  ) -> List[Dict[str, Any]]:
    """跑一遍打分。**纯函数式**：索引与客户端都由调用方注入，因此可离线测。

    `workers` 只改**吞吐**，不改判据、不改产物形状：判分是**逐查询独立**的，
    汇总仍是"查询序 × 该查询的案例序"，所以并发与否得到**同序同内容的行**。
    为什么需要它（2026-10-04 实测）：一次 64 条查询 × 两条模型 = 128 次调用，
    串行跑（其中一条是"始终思考"的 `glm-5.3`）实测要一小时以上——那种通道既没法
    迭代，也没法在换代之后重测。守门见 `tests/test_e1_panel.py` 的
    "串行与并发产出逐行相同"。
    """
    if int(workers) > 1 and len(queries) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=int(workers)) as pool:
            batches = list(pool.map(
                lambda query: _score_one(index, query, clients, top_k,
                                         rerank=rerank, retrieve_k=retrieve_k,
                                         rerank_label=rerank_label,
                                         expand=expand, expand_mode=expand_mode,
                                         judge_batch=judge_batch),
                queries))
        return [row for batch in batches for row in batch]
    return [row for query in queries
            for row in _score_one(index, query, clients, top_k,
                                  rerank=rerank, retrieve_k=retrieve_k,
                                  rerank_label=rerank_label,
                                  expand=expand, expand_mode=expand_mode,
                                  judge_batch=judge_batch)]


def summarise(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    good = [row for row in rows if float(row["score"]) >= RELEVANT]
    #: 尾部丢弃数是**逐查询**的，所以按查询去重后相加（同一查询的每条行都带同一个值）。
    seen: Dict[str, int] = {}
    for row in rows:
        seen.setdefault(str(row.get("query", "")),
                        int(row.get("partial_batch_dropped") or 0))
    return {"scored": len(rows), "relevant": len(good),
            "value": round(len(good) / len(rows), 4) if rows else None,
            "line": 0.70,
            #: 判分语境（C）：报 E1 必须连同"这次调用喂了几条候选"一起报。
            "judge_batch": int(rows[0].get("judge_batch") or 0) if rows else 0,
            "partial_batch_dropped": sum(seen.values())}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge-e1-panel")
    parser.add_argument("--project", default="",
                        help="真实运行的 project.bdproj（逐镜散文查询的来源）")
    parser.add_argument("--queries", default="", help="或直接给一行一条查询的文本文件")
    parser.add_argument("--cases-dir", default="knowledge")
    parser.add_argument("--out", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--models", default=",".join(DEFAULT_PANEL))
    parser.add_argument("--scripted", default="",
                        help="离线桩（`llm` 的 scripted 后端）；给了就完全不碰网络")
    parser.add_argument("--limit", type=int, default=0, help="0 = 全部")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="并发判分的查询条数（只改吞吐，不改判据与产物形状）")
    parser.add_argument("--adapter", default="none",
                        choices=("none", "lexical", "lightrag"),
                        help="检索臂：none=产品现行 hybrid；lexical=零依赖适配器；"
                             "lightrag=sidecar 上的真索引（需要先起服务）")
    parser.add_argument("--lightrag-url", default="",
                        help="lightrag 臂的 sidecar 地址（默认走适配器的环境变量/默认值）")
    parser.add_argument("--lightrag-fingerprint", default="",
                        help="lightrag 臂要求的索引指纹（给了就 fail closed）")
    parser.add_argument("--cases-filter", default="off", choices=("off", "llm"),
                        help="L3 相关性过滤器：`llm` ＝ 产品那条（`--cases-filter llm`）。"
                             "默认 off ＝ 与历次读数同一口径")
    parser.add_argument("--judge-batch", type=int, default=0,
                        help="判分语境 C：每次判分调用喂几条候选。0（默认）＝ C 跟 "
                             "`--top-k`（历次口径，逐字不变）。>0 时把候选按**连续 N 元组**"
                             "切开分别判，尾部不满一批的不入证（条数记进 partial_batch_dropped）——"
                             "这是把\"上限\"与红线放到同一把尺子上的唯一办法，见 "
                             "docs/evidence/20261006-e1-judge-context/")
    parser.add_argument("--filter-provider", default="deepseek",
                        help="过滤器的 LLM 通道（判据提示词与产品同一份）")
    parser.add_argument("--filter-model", default="deepseek-chat")
    parser.add_argument("--cases-rerank", default="off",
                        choices=("off", "cross-encoder", "llm", "embedding"),
                        help="retrieve-then-rerank：`cross-encoder` ＝ 先取宽候选"
                             "（`--rerank-retrieve-k`）再重排取 `--top-k`；`llm` ＝ 用 LLM 排序。"
                             "默认 off ＝ 历次口径")
    parser.add_argument("--rerank-model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--rerank-retrieve-k", type=int, default=20,
                        help="重排前的候选条数（只会被减法裁到 `--top-k`）")
    parser.add_argument("--rerank-device", default="",
                        help="留空＝cuda 可用就用 cuda")
    parser.add_argument("--rerank-embed-model", default="BAAI/bge-small-zh-v1.5",
                        help="`--cases-rerank embedding` 用的中文嵌入器（默认 "
                             "bge-small-zh-v1.5：本机已缓存、CUDA 可用。D3 实测："
                             "同一路由换更好的嵌入器，E1 提高约 5.6 倍 ⇒ 嵌入这一侧值得压榨）")
    parser.add_argument("--rerank-llm-provider", default="qwen",
                        help="`--cases-rerank llm` 的通道（默认 qwen ＝ 第三方裁决通道）")
    parser.add_argument("--rerank-llm-model", default="qwen3.8-max")
    parser.add_argument("--rerank-llm-max-tokens", type=int, default=1024,
                        help="重排调用给模型的 completion 预算（默认 1024 ＝ 历次口径）。"
                             "**始终思考**的模型（`kimi-k3`）在长候选清单上会把 1024 全烧进"
                             " reasoning，正文变空 ⇒ 那一查询具名降级成 `failed:LLMError`。"
                             "实测（`work/_probe_kimi_rerank_quiet.py`）：顺序跑 64 条有 **8 条**"
                             "失败，其中 **7 条**就是这个空正文陷阱 ⇒ 这条缝就是给它的。")
    parser.add_argument("--rerank-clue", default="off", choices=("off", "on"),
                        help="重排时**把案例的中文线索一并交给重排器**（默认 off ＝ 历次口径）。"
                             "为什么该开：候选清单原来只有 `case_id｜英文摘录[:160]`，"
                             "而查询是**中文**——重排器被要求跨语种判断，却看不到案例层"
                             "**本来就有**的中文对齐面（`search_zh`）。这不是放宽判据，"
                             "是把已经存在于检索侧的信息补到重排侧。证据见 "
                             "docs/evidence/20261006-rerank-shapes/")
    parser.add_argument("--rerank-title", default="off", choices=("off", "on"),
                        help="重排的候选清单里给出 `title[:60]｜(summary|excerpt)[:220]`"
                             "——**与 E1 评委看到的一模一样**（默认 off ＝ `excerpt[:160]`）。"
                             "为什么该开：重排器原来**手里的信息比评委更少**，那是人为削弱。"
                             "它与 `--rerank-clue` 是**两处独立的信息缺口**，分两个开关以便分别取证。")
    parser.add_argument("--rerank-llm-stages", type=int, default=1, choices=(1, 2),
                        help="重排的段数：`1`（默认，历次口径）＝一次从宽候选里挑；"
                             "`2` ＝**两段式**：先按 `--rerank-llm-chunk` 分块各挑 "
                             "`--rerank-llm-keep` 条，再到幸存者里挑。只对 `select` 生效。"
                             "为什么试：`order` 在 50 条上只有 0.2760，说明**一次看太长的清单**"
                             "本身就是弱点；而线索与标题都补过且没再涨 ⇒ 缺口在**单次挑选**上。")
    parser.add_argument("--rerank-llm-chunk", type=int, default=10,
                        help="两段式的第一段每批看几条（默认 10）")
    parser.add_argument("--rerank-llm-keep", type=int, default=3,
                        help="两段式的第一段每批留几条（默认 3）")
    parser.add_argument("--rerank-llm-prompt", default="order",
                        choices=("order", "select", "score"),
                        help="重排提示词的形状：`order` 全序排序／`select` 只挑最该看的 3 条／"
                             "`score` 逐条 0–10 分（对照用）")
    parser.add_argument("--query-expand", default="off", choices=("off", "llm"),
                        help="查询侧对齐：`llm` ＝ 把中文指令改写成英文工艺词检索串"
                             "（判分仍用冻结的原文；默认 off ＝ 历次口径）")
    parser.add_argument("--expand-provider", default="deepseek")
    parser.add_argument("--expand-model", default="deepseek-chat")
    parser.add_argument("--expand-mode", default="union", choices=("union", "replace"),
                        help="`union` ＝ 原文 ＋ 英文改写一起检索；`replace` ＝ 只用改写")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    if bool(args.project) == bool(args.queries):
        print(json.dumps({"error": "必须**恰好**给一个：--project 或 --queries"},
                         ensure_ascii=False))
        return 2
    queries = (queries_from_project(ROOT / args.project) if args.project
               else queries_from_lines(ROOT / args.queries))
    if args.limit:
        queries = queries[:args.limit]
    if not queries:
        print(json.dumps({"error": "一条查询都没有：分母为 0，不许当成通过"},
                         ensure_ascii=False))
        return 2

    #: L3 相关性过滤器（`off` ＝ 现行行为；`llm` ＝ 产品那条 `--cases-filter llm`）。
    #: 判据提示词 import 自 sidecar（单一真源），这里只装配调用。
    case_filter = (make_llm_case_filter(model=args.filter_model,
                                       provider=args.filter_provider)
                   if args.cases_filter == "llm" else None)
    if args.adapter == "lexical":
        from block_director.knowledge.lexical_adapter import make_lexical_adapter

        index = load_index(ROOT / args.cases_dir, backend="lightrag",
                           adapter=make_lexical_adapter(ROOT / args.cases_dir),
                           case_filter=case_filter)
        index.path_label = "lexical"          # type: ignore[attr-defined]
    elif args.adapter == "lightrag":
        #: 第三条臂（D8 的判定对象）：走 sidecar 上的**真** LightRAG 索引。
        #: `expected_fingerprint` 给了就 fail closed——不匹配连查都不查。
        from block_director.knowledge.lightrag_adapter import make_lightrag_adapter

        index = load_index(
            ROOT / args.cases_dir, backend="lightrag",
            adapter=make_lightrag_adapter(base_url=args.lightrag_url,
                                          expected_fingerprint=args.lightrag_fingerprint),
            case_filter=case_filter)
        index.path_label = "lightrag"         # type: ignore[attr-defined]
    else:
        index = load_index(ROOT / args.cases_dir, backend="hybrid",
                           case_filter=case_filter)
        index.path_label = "hybrid"           # type: ignore[attr-defined]
    #: 把**案例集合摘要**挂到索引上，供每条打分自带（`e1_evidence_is_stale` 用它判代际）。
    #: `load_index` 自己不记它（那是案例层的事），而这里正是"这份索引被拿去打分"的现场，
    #: 所以在这一处取一次、跟着行落盘。
    from block_director.knowledge import cases as _cases

    index.cases_digest = _cases.cases_digest(
        _cases.case_paths(ROOT / args.cases_dir))       # type: ignore[attr-defined]
    names = [item.strip() for item in str(args.models).split(",") if item.strip()]
    families = list(DEFAULT_FAMILIES[:len(names)]) or ["scripted"]
    if len(set(families[:len(names)])) < 2 and not args.scripted:
        print(json.dumps({"error": "面板必须换族（两个不同的 family）"},
                         ensure_ascii=False))
        return 2
    clients = []
    for position, name in enumerate(names):
        if args.scripted:
            client = llm.make_client("scripted", name, args.scripted)
        else:
            client = llm.make_client(families[position], name)
        clients.append((name, client))

    if args.cases_rerank == "cross-encoder":
        reranker, rerank_label = load_cross_encoder(args.rerank_model,
                                                   device=args.rerank_device), \
            args.rerank_model
    elif args.cases_rerank == "llm":
        reranker, rerank_label = make_llm_reranker(
            model=args.rerank_llm_model,
            provider=args.rerank_llm_provider,
            prompt=args.rerank_llm_prompt,
            max_tokens=args.rerank_llm_max_tokens,
            clue_of=((lambda cid: (getattr(index, "search_zh", None) or {}).get(cid, ""))
                     if args.rerank_clue == "on" else None),
            with_title=(args.rerank_title == "on"),
            stages=int(args.rerank_llm_stages),
            chunk=int(args.rerank_llm_chunk),
            keep_per_chunk=int(args.rerank_llm_keep)), \
            _llm_rerank_label(args)
    elif args.cases_rerank == "embedding":
        #: 嵌入重排：编码查询与各候选的**中文线索**，按余弦排序。与两位评委**不同族**，
        #: 所以它的读数**不带**"同族自证"那条折扣（P14-226 定的方向）。
        #: 线索**无条件**给它（没有线索的案例退回英文摘录）：对嵌入来说线索不是"额外信息"，
        #: 而是让"中文查询 ↔ 中文线索"落在同一语种面上的**被编码文本本身**。
        reranker, rerank_label = make_embedding_reranker(
            model_name=args.rerank_embed_model, device=args.rerank_device,
            clue_of=(lambda cid: (getattr(index, "search_zh", None) or {}).get(cid, ""))), \
            "embed:%s+clue(fallback=excerpt)" % args.rerank_embed_model
    else:
        reranker, rerank_label = None, ""
    rows = score_queries(index, queries, clients, top_k=args.top_k,
                         workers=args.workers, rerank=reranker,
                         retrieve_k=(args.rerank_retrieve_k if reranker else 0),
                         rerank_label=rerank_label,
                         expand=(make_query_expander(model=args.expand_model,
                                                     provider=args.expand_provider)
                                 if args.query_expand == "llm" else None),
                         expand_mode=args.expand_mode,
                         judge_batch=args.judge_batch)
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                               for row in rows), encoding="utf-8", newline="\n")
    summary = {"out": str(out_path), "queries": len(queries),
               "cases_fingerprint": str(getattr(index, "fingerprint", "") or ""),
               #: 汇总也要自述线索层：空串 = 可用；否则这一跑的数**不是**可比读数。
               "clue_state": str(getattr(index, "search_zh_reason", "") or ""),
               "cases_backend_effective": str(getattr(index, "effective", "") or ""),
               "cases_degrade_reason": str(getattr(index, "reason", "") or ""),
               **summarise(rows)}
    print(json.dumps(summary, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if rows else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
