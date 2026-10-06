"""Negative control: would the new guard have caught the OLD chain?"""
import pathlib
import re
import subprocess

DATE_PATH = re.compile(r"docs/evidence/\d{8}")
DEF = re.compile(r"\s*\$knowledgeRun\s*=")


def live(text):
    return [(n, line) for n, line in enumerate(text.splitlines(), 1)
            if line.strip() and not line.lstrip().startswith("#")]


def check(text):
    calls = [(n, line) for n, line in live(text) if "injection_audit.py" in line]
    assert len(calls) == 1, calls
    number, line = calls[0]
    uses_var = "$knowledgeRun" in line
    dated = bool(DATE_PATH.search(line))
    defs = [(n, l) for n, l in live(text) if DEF.match(l)]
    ordered = bool(defs) and defs[0][0] < number
    return {"calls": len(calls), "uses_knowledgeRun": uses_var,
            "has_dated_path": dated, "definitions": len(defs),
            "def_before_call": ordered,
            "guard_fails": (not uses_var) or dated or len(defs) != 1 or not ordered}


old = subprocess.run(["git", "show", "HEAD:tools/run_tests.ps1"],
                     capture_output=True).stdout.decode("utf-8")
new = pathlib.Path("tools/run_tests.ps1").read_text(encoding="utf-8")
print("OLD:", check(old))
print("NEW:", check(new))
