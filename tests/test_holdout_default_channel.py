"""守门：held-out 那两条生成/标注通路**不许再把已弃用的本地模型当默认**。

为什么（2026-10-06 全量审查抓到）：`tools/kb_fetch/holdout_gen.py` 与
`tools/holdout_fill.py` 的 `--provider` 默认值还是 `ollama`、默认模型还是
`qwen3-vl:30b` —— 而用户已经两次裁决弃用本地模型（"别用本地模型了"），
本机那份 blob 还是**坏修订**（输出纯噪声）。也就是说：**不带 `--provider` 直接跑这两条通路，
得到的是坏模型的产物或直接失败**，而它们正是"标注族"的执行入口。
现行分工是 **抽取 ＝ DeepSeek／标注 ＝ GLM-5.3**（`family=zhipu`，天然换族）。

这条守门做两件事：① 两个入口的默认 provider 必须是 `glm`；② 全仓 `default=` 里
**不许**再出现 `ollama`（显式 `--provider ollama` 仍然可用——禁的是"默认"）。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCAN_ROOTS = ("tools", "block_director")
DEFAULT_OLLAMA = re.compile(r"default\s*=\s*[\"']ollama[\"']")


def _tool_source(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def test_the_two_annotation_entry_points_default_to_glm():
    for relpath in ("tools/kb_fetch/holdout_gen.py", "tools/holdout_fill.py"):
        source = _tool_source(relpath)
        assert 'parser.add_argument("--provider", default="glm")' in source, (
            "%s 的默认 provider 必须是 glm（GLM-5.3），不是本地模型" % relpath)


def test_no_tool_defaults_to_a_retired_local_model():
    offenders = []
    for root in SCAN_ROOTS:
        for path in (ROOT / root).rglob("*.py"):
            if DEFAULT_OLLAMA.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], (
        "这些地方还把已弃用的本地模型当默认：%s" % offenders)


def test_the_retired_model_still_reachable_explicitly():
    """**禁的是默认，不是通道**：显式 `--provider ollama` 仍然要有实现（不许为了过这条守门删掉它）。"""
    from tools.kb_fetch import llm  # noqa: PLC0415

    source = pathlib.Path(llm.__file__).read_text(encoding="utf-8")
    assert 'if provider == "ollama"' in source
