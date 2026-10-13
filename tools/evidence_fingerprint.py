"""Print a JSON fingerprint of the run configuration (v1.4 S13 / SS B.2 L5).

The acceptance evidence directory must be self-describing: two runs that
produced different numbers must be distinguishable by the config that drove
them. Pure Python, no bpy.

Usage:
  python tools/evidence_fingerprint.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint() -> dict:
    from block_director.contracts.config import (CONFIG_VERSION,
                                                 dump_default_yaml)
    from block_director.cinema.metric_registry import LAYER_WEIGHTS_DEFAULT

    spec = ROOT / "specs" / "config.default.yaml"
    return {
        "package_version": _package_version(),
        "config_version": CONFIG_VERSION,
        "spec_file": "specs/config.default.yaml",
        "spec_sha256": _sha256(spec),
        "generated_config_sha256": hashlib.sha256(
            dump_default_yaml().encode("utf-8")).hexdigest(),
        "golden_expected_sdl_sha256": _sha256(
            ROOT / "fixtures" / "expected_sdl_simple.json"),
        "golden_transcript_sha256": _sha256(
            ROOT / "fixtures" / "tool_transcript_simple.jsonl"),
        #: 空间尺总览分权重表与其指纹（v1.7 I3）：证据目录必须自解释，
        #: 同一份配置换权重后产生的读数能被指纹区分开。运行时真源是
        #: specs/config.default.yaml；这里记录注册表的规格快照。
        "ruler_weights": LAYER_WEIGHTS_DEFAULT,
        "ruler_weights_sha256": hashlib.sha256(
            json.dumps(LAYER_WEIGHTS_DEFAULT, sort_keys=True,
                       ensure_ascii=False).encode("utf-8")).hexdigest(),
    }


def _package_version() -> str:
    try:
        from block_director import __version__
        return str(__version__)
    except Exception:  # noqa: BLE001 - 指纹不是关键路径
        return ""


def main() -> int:
    payload = json.dumps(fingerprint(), ensure_ascii=False, indent=2)
    out = None
    if "--out" in sys.argv:
        index = sys.argv.index("--out")
        if index + 1 < len(sys.argv):
            out = Path(sys.argv[index + 1])
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
