"""Negative control: would the new E1-certification guard have caught the OLD chain?"""
import io
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
sys.path.insert(0, str(ROOT))
from tools.knowledge import quality  # noqa: E402


def live(text):
    return [(n, line) for n, line in enumerate(text.splitlines(), 1)
            if line.strip() and not line.lstrip().startswith("#")]


def check(text):
    lines = [line for _n, line in live(text) if "--e1-reviews" in line]
    if len(lines) != 1:
        return {"calls": len(lines), "guard_fails": True}
    match = re.search(r"--e1-reviews\s+(\S+)", lines[0])
    path = ROOT / match.group(1)
    rows = [json.loads(line) for line in
            io.open(path, encoding="utf-8").read().split("\n") if line.strip()]
    contexts = sorted({int(row.get("judge_batch") or 0) for row in rows})
    return {"file": match.group(1), "rows": len(rows), "contexts": contexts,
            "product_context": quality.PRODUCT_CONTEXT,
            "guard_fails": contexts != [quality.PRODUCT_CONTEXT]}


old = subprocess.run(["git", "show", "HEAD:tools/run_tests.ps1"],
                     capture_output=True).stdout.decode("utf-8")
new = (ROOT / "tools" / "run_tests.ps1").read_text(encoding="utf-8")
print("OLD:", check(old))
print("NEW:", check(new))
