"""索引的**失效钥匙**：四格指纹 ＋ 查询端比对（fail closed）。

为什么要有它：索引是派生物，而派生物的头号病是"语料换了、索引还是旧的，账面全绿"
——本项目在 S0（缓存键）与 `53d3e3f`（手抄的 trace）上各踩过一次同形的坑。

四格（写死口径，缺一格**拒收**，不许当空串算）：

1. `cases_digest` —— **案例集合**自己的摘要（不是语料指纹：只换案例集合它也会变）；
2. `lightrag_version` —— 上游版本；
3. `embedding` —— 嵌入路由 ＋ 模型标识（换嵌入器必须整体重建）；
4. `build_args` —— 建索引时真正用到的参数（`build_args` 里键顺序不影响指纹）。

纪律：**先落证、再联网**那一套在这里的形态是"manifest 先写，索引后建"；
而查询端 `verify()` 在任何一次服务之前跑，不匹配就带具名原因拒绝。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Dict, Optional, Sequence, Tuple

MANIFEST_NAME = "INDEX_MANIFEST.json"

#: 四格的名字（缺失即拒收）。
CELLS: Tuple[str, ...] = ("cases_digest", "lightrag_version", "embedding", "build_args")


def _canonical(cells: Dict) -> str:
    return json.dumps({name: cells[name] for name in CELLS},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(cells: Dict) -> Dict:
    """算四格指纹。缺格 ⇒ `ValueError`（不拿空串顶）。"""
    missing = [name for name in CELLS if name not in cells or cells[name] in (None, "")]
    if missing:
        raise ValueError("索引指纹缺格：%s（缺格不许当空串算）" % missing)
    digest = hashlib.sha256(_canonical(cells).encode("utf-8")).hexdigest()
    return {"cells": {name: cells[name] for name in CELLS}, "fingerprint": digest}


def write(index_dir: pathlib.Path, cells: Dict, *, extra: Optional[Dict] = None) -> Dict:
    report = fingerprint(cells)
    payload = {"cells": report["cells"], "fingerprint": report["fingerprint"]}
    if extra:
        payload.update(extra)
    path = pathlib.Path(index_dir) / MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read(index_dir: pathlib.Path) -> Optional[Dict]:
    path = pathlib.Path(index_dir) / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def verify(index_dir: pathlib.Path, expected: Dict) -> Tuple[bool, str]:
    """把**期望的四格**与索引里的 manifest 比。返回 ``(ok, reason)``。"""
    shipped = read(index_dir)
    if not shipped:
        return False, "index_manifest_missing"
    try:
        want = fingerprint(expected)
    except ValueError as exc:
        return False, "index_expected_cells_invalid:%s" % exc
    got = shipped.get("fingerprint")
    if got != want["fingerprint"]:
        #: 具名指出是哪一格变了（读的人一眼知道要不要重建）。
        changed = [name for name in CELLS
                   if (shipped.get("cells") or {}).get(name) != want["cells"].get(name)]
        return False, "index_fingerprint_mismatch:%s" % (changed or ["fingerprint"])
    return True, ""
