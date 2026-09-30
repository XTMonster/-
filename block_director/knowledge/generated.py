"""加载 P14-1 采集进来的生成卡片（执行文档 v1.4 §2.3c / §2.3d 的 T8）。

`tools/kb_fetch/import_cards.py` 会把卡片写成两种**同源**产物：

* ``knowledge/cards_generated/<domain>.jsonl`` —— 运行时投影（本模块读它）；
* ``knowledge/cards_generated/<domain>.yaml`` —— 人类/审计副本。

为什么运行时读 `.jsonl` 而不是 `.yaml`：Blender 的 Python 只有 stdlib，
没有 PyYAML；而 `block_director/` 的硬约束是"只用 stdlib ＋ bpy"。
两份文件由同一次运行、同一份内存列表写出，并由 `tests/test_kb_pipeline.py`
断言逐字段相等，因此不存在两处手改的漂移面。

加载规则（T8）：按 `id` 合并，**重复 id 以手写卡为准**并记录冲突，
由测试断言"冲突集合为空"——生成卡与手写卡撞 id 是作者错误，不静默覆盖。
"""

from __future__ import annotations

import json
import pathlib
from typing import Dict, List, Tuple

from ..contracts.knowledge import Card

#: 生成卡的 id 前缀（`gen_<domain>_<序号>`）。检索侧据此决定哪些字段进检索面。
ID_PREFIX = "gen_"

#: 运行时只认这些字段（生成条目另外带 `source_ref` / `quote` / `topic`，
#: 那是出处与审计用的，不进 `Card`）。
CARD_FIELDS = (
    "id", "domain", "title", "content", "keywords", "rules", "parameters",
    "examples", "related", "engine_support", "emotion", "tags",
)

_PACKAGE_DIR = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parents[1]

#: 依次尝试：包内副本（打好的 Blender 扩展）→ 仓库根。
SEARCH_DIRS = (
    _PACKAGE_DIR / "cards_generated",
    _REPO_ROOT / "knowledge" / "cards_generated",
)


def cards_dir() -> pathlib.Path | None:
    for directory in SEARCH_DIRS:
        if directory.is_dir() and any(directory.glob("*.jsonl")):
            return directory
    return None


def _entry_to_card(entry: Dict) -> Card:
    data = {field: entry[field] for field in CARD_FIELDS if field in entry}
    return Card.from_dict(data)


def load_generated(directory: pathlib.Path | None = None) -> List[Card]:
    """读全部生成卡片；目录不存在时返回空列表（早于 P14-1 的历史状态）。"""
    target = directory if directory is not None else cards_dir()
    if target is None or not target.is_dir():
        return []
    cards: List[Card] = []
    for path in sorted(target.glob("*.jsonl")):
        # 只按 `\n` 切：卡片正文来自抓取到的他人著作，里面可能有 `\u0085` / `\u2028` /
        # `\u2029`（PDF 解码尤其容易），而 `splitlines()` 会把它们当成换行、
        # 把一条记录从中间切断。见 `tools/kb_fetch/common.py::read_jsonl` 的说明。
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as exc:  # pragma: no cover - 明确报错
                raise ValueError(f"{path.name}:{lineno} 不是合法 JSON: {exc}") from exc
            cards.append(_entry_to_card(entry))
    return cards


def merge_cards(handwritten: List[Card],
                generated: List[Card]) -> Tuple[List[Card], List[Tuple[str, str]]]:
    """T8：按 id 排序合并；重复 id 以手写卡为准并返回冲突清单。"""
    by_id: Dict[str, Card] = {}
    collisions: List[Tuple[str, str]] = []
    for card in generated:
        by_id[card.id] = card
    for card in handwritten:
        if card.id in by_id:
            collisions.append((card.id, "handwritten_over_generated"))
        by_id[card.id] = card
    return [by_id[key] for key in sorted(by_id)], collisions
