"""从契约层生成规格文件，保证规格与代码不漂移（执行文档 v1.2 §16.5）。

用法：python tools/gen_specs.py            # 生成
      python tools/gen_specs.py --check    # 仅检查是否一致（CI 用）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.config import dump_default_yaml  # noqa: E402


TARGET = ROOT / "specs" / "config.default.yaml"


def main(argv: list[str]) -> int:
    expected = dump_default_yaml()
    check_only = "--check" in argv

    if check_only:
        actual = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if actual != expected:
            print(f"[FAIL] {TARGET} 与代码不一致，请运行 python tools/gen_specs.py")
            return 1
        print(f"[OK] {TARGET} 与代码一致")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n"：.gitattributes 规定文本文件在仓库里用 LF；不写死的话
    # Windows 上 write_text 会把 \n 翻成 CRLF，工作区与规格的换行不一致。
    TARGET.write_text(expected, encoding="utf-8", newline="\n")
    print(f"[OK] 已生成 {TARGET}（{len(expected)} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
