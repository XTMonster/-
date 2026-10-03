"""RK-13 的**硬门**判定：按 id 判，不拿聚合退出码判。

为什么需要它（实测缺陷，2026-10-02）
==================================

验收链只跑了 ``tools/holdout_score.py``，却把那份报告写在 ``knowledge_quality.json``
名下（名字是 AGENTS.md 写给 ``tools/knowledge/quality.py`` 的）。实测后果：
``docs/evidence/<run-id>/knowledge_quality.json`` 的 metric id 集合是
``['Q1','Q2','Q3','Q4','Q6a','Q6b','Q7']`` —— **没有 Q0，也没有 E3**，而
"E3 经验越权率 = 0" 是 §2.3b / §4.1b 写死的**硬门**。也就是说那条硬门在验收链上
从来没有被量过（只有 ``tests/test_knowledge_quality.py`` 在离线单测里碰它）。

为什么不能直接用 ``quality.py`` 的退出码
======================================

``quality.py`` 的聚合口径是"只要有一条 ``not_measured`` 就返回 2"。而 Q5（需要
真实模型运行的逐镜查询）与 E1（需要人工给案例打分）曾经在 CI / 离线上**永远是
``not_measured``**。拿那个退出码当 RK-13 的判据，会把两件不同的事混成一件：
"硬门真的红了" 与 "人工项这次量不到"。所以链要的是**按 id 判**：

* :data:`HARD_IDS` 里的每一条都必须在报告里、且 ``status == "pass"``；
* **缺一条也算失败**——缺证据不是通过（§4.1b 硬规则 1）；
* :data:`SOFT_IDS`（只有 E2）**不参与判定**，但它们必须明文出现在报告里：
  "这一项没量"要让报告自己说出来，不能让读者以为没有这条要求。

2026-10-03 的**门归位**（收紧，不是放宽）
======================================

``Q5`` 与 ``E1`` 曾经只能进 :data:`SOFT_IDS`，理由是"链上没有输入"。现在两条
输入都在链上了，那个理由不成立，而规格一直把它们写成门：

* ``E1 ≥ 70%`` 是 §2.3b 的"经验层三项"之一（E1 ≥70% / E2 记录不设门 / E3 = 0）；
* ``Q5 ≥ 80%`` 是 §4.1 的 RK-13 判据之一，§4.1b 还给了它的分母下界
  （夹具 ≥30 条带 ``expect_movements``；运行侧与本条 ``q`` 等价）
  与"分母为 0 一律判失败"那条全局硬规则。

链上现在喂的是**真实模型运行的证据**（``docs/evidence/20261003_real_glm/`` 的
``export/shots.json`` ＋ ``audit_log.jsonl``；join 键取 audit 事件里**真实发出**
的查询，§4.1b 硬规则 2）与**录档的跨族面板评分**（``--e1-reviews``）。所以两条
都从"这次量不到"变成"这次必须判"：``not_measured`` / 缺 id / 分母 0 一律算
RK-13 未通过。``E2`` 留在 :data:`SOFT_IDS`：规格明写它只**记录**采纳率、
**不设门**（§2.3b），所以它既不判过也不判不过。

单一真源
========

这份清单描述的是 ``tools/knowledge/quality.py`` 会产出的 id，所以
``tests/test_hard_gates.py`` 会真的跑一次 ``quality.build_report``（极小夹具）并
断言两边的 id 集合一致——清单漂了当场红，而不是等到链上某天门变空了才发现。

用法::

    python tools/knowledge/hard_gates.py --report <knowledge_quality.json> [--json]

退出码：0 = 硬门全过；1 = 有硬门没通过或缺失；2 = 报告读不到/不是报告。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Dict, List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.utils.console import force_utf8_streams  # noqa: E402

#: 每一条都有 §4.1 / §4.1b 写死的线，必须过。
HARD_IDS: tuple = (
    "Q0",                          # 构建门：恒等式 + rejects <= 5%
    "Q1", "Q2", "Q3",              # 检索质量的三条线
    "Q4",                          # required 边 top-k 检出
    "Q4_pre_required_edges_exist",  # §2.3 Q6b 前置①：索引构建成功
    "Q6a", "Q6b",                  # 契约往返 / 成员完整
    "Q7",                          # 禁忌拦截
    #: 2026-10-03 归位：**§2.3c 的 K1–K4**（RK-13 的**前置**——"语料合规与覆盖"）。
    #: 文档一直把它们写成前置，但链上从没查过：它们的计算只在**重跑导入**时发生
    #: （`tools/kb_fetch/import_cards.py`），入库产物被换掉、报告没跟上，链上不会红。
    #: 现在由 `tools/knowledge/corpus_gates.py` 从**入库语料重算**（K1/K2/K3 一个字
    #: 都不读构建期报告；K4 的账本必须与语料对得上，且入库语料不许有完全重复的卡），
    #: 由 `quality.py` 写进**同一份报告**——硬门按 id 读的就是这一份。
    "K1_source_ref_complete",      # 出处六字段 100%
    "K2_license_ratio",            # 许可白名单内 100%
    "K3_domain_floor",             # 九域每域 ≥60 且任一域 ≥5%
    "K4_dedupe_ratio",             # 去重有效率 ≥60% ＋ 账语料一致 ＋ 无重复卡
    #: 2026-10-03 归位：Q5 的分子/分母现在都由链上喂进来的**真实运行证据**决定
    #: （`export/shots.json` ＋ `audit_log.jsonl`，join 键取 audit 里真实发出的
    #: 查询）。它在 §4.1 的 RK-13 判据里是"≥80%"，§4.1b 还给了分母下界与
    #: "分母为 0 一律判失败"。缺证据 / NA / 分母 0 都算这一门没通过。
    "Q5",
    #: §2.3b 的"经验层三项"之一（E1 ≥70%）。链上喂的是录档的跨族面板评分
    #: （`--e1-reviews`），所以它和别的门一样在 CI 上就有输入。
    "E1",
    "E3",                          # 经验越权率 = 0（§2.3b 的硬门）
    "E3_cases",                    # 案例层的越权扫描
)

#: 规格明写"不设门"的条目（§2.3b：E2 = 记录采纳率）。它不是门，但必须被如实记录：
#: "这一项没量"要让报告自己说出来，不能让读者以为没有这条要求。
SOFT_IDS: tuple = ("E2",)

PASS = "pass"


def verdict(report: Dict[str, Any]) -> Dict[str, Any]:
    """报告 → ``{passed, missing, red, soft}``。**缺 id 与状态非 pass 同等对待。**"""
    metrics = {}
    for item in (report or {}).get("metrics") or []:
        if isinstance(item, dict) and item.get("id"):
            metrics[str(item["id"])] = item
    missing: List[str] = [ident for ident in HARD_IDS if ident not in metrics]
    red: List[str] = [ident for ident in HARD_IDS
                      if ident in metrics
                      and str(metrics[ident].get("status")) != PASS]
    soft = {ident: str((metrics.get(ident) or {}).get("status") or "absent")
            for ident in SOFT_IDS}
    return {"passed": not missing and not red, "missing": missing, "red": red,
            "soft": soft, "hard_ids": list(HARD_IDS), "soft_ids": list(SOFT_IDS)}


def load_report(path: pathlib.Path) -> Dict[str, Any]:
    """读一份 quality 报告；不是报告就抛 :class:`ValueError`。"""
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("metrics"), list):
        raise ValueError(f"{path} 不是 quality 报告（缺 metrics[]）")
    return data


def _describe(result: Dict[str, Any]) -> str:
    soft = ", ".join(f"{k}={v}" for k, v in result["soft"].items())
    if result["passed"]:
        return f"hard gates: all pass ({len(HARD_IDS)} ids); not measured: {soft}"
    parts = []
    if result["missing"]:
        parts.append("missing ids: " + ",".join(result["missing"]))
    if result["red"]:
        parts.append("not passing: " + ",".join(result["red"]))
    return "; ".join(parts) + f"; not measured: {soft}"


def main(argv: Sequence[str] | None = None) -> int:
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="knowledge-hard-gates")
    parser.add_argument("--report", required=True,
                        help="tools/knowledge/quality.py 写出的报告 JSON")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    try:
        result = verdict(load_report(pathlib.Path(args.report)))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[INCOMPLETE] 读不到 quality 报告：{exc}")
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    print(_describe(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
