"""Mechanical drift check: does v1.4's own "single source of truth" count table match its tables?

~0.1 claims the counts for phases / work items / defects / RK oracles / fixtures / user stories.
Those are exactly the numbers other documents copy, so a mismatch is the F7 ("同源文档漂移") class.
This probe counts the actual rows and prints an ASCII-only verdict per line.
"""
import pathlib
import re
import sys

DOC = pathlib.Path("改进执行文档v1.4.md")
lines = DOC.read_text(encoding="utf-8").split("\n")


def block_between(start_pat, end_pat, *, skip_header=2):
    """The table rows between two heading regexes (skipping the header + separator rows)."""
    start = end = None
    for i, line in enumerate(lines):
        if start is None and re.match(start_pat, line):
            start = i
            continue
        if start is not None and re.match(end_pat, line):
            end = i
            break
    if start is None or end is None:
        return None
    block = [l for l in lines[start + 1:end] if l.strip().startswith("|")]
    return block[skip_header:]


def rows_between(start_pat, end_pat, *, skip_header=2):
    return len(block_between(start_pat, end_pat, skip_header=skip_header))


def numbered_items(start_pat, end_pat):
    """Count NUMBERED items in the first column, expanding ranges like `#27-33` into 7 items.

    Why this exists: section 1.6 packs `#27-33` (the SDL version-string group, 7 items) into ONE
    row, so counting rows gives 28 while the document *claims* 34 items.  Counting items is the
    only way to check the claim.
    """
    total = 0
    for row in block_between(start_pat, end_pat):
        first = row.split("|")[1]
        #: first column is either `14` / `14 (warn mark)` or a range `27-33（...）`
        span = re.search(r"(\d+)\s*[\u2013-]\s*(\d+)", first)
        if span:
            total += int(span.group(2)) - int(span.group(1)) + 1
            continue
        if re.search(r"\d+", first):
            total += 1
    return total


checks = [
    ("phases   §5", rows_between(r"^## §5 ", r"^## §6 "), 9),
    #: §0.1 itself says "§1.1 表 7 行（BW-4 拆 a/b）" -> 7 rows for 6 observations.
    ("BW rows  §1.1", rows_between(r"^### §1\.1 ", r"^### §1\.2 "), 7),
    ("D        §1.2", rows_between(r"^### §1\.2 ", r"^### §1\.3 "), 5),
    ("F/S rows §1.3", rows_between(r"^### §1\.3 ", r"^### §1\.4 "), 19),
    ("X        §1.4", rows_between(r"^### §1\.4 ", r"^### §1\.5 "), 17),
    ("asserts  §1.6", numbered_items(r"^### §1\.6 ", r"^### §1\.7 "), 34),
    ("oracles  §4.1", rows_between(r"^### §4\.1 ", r"^### §4\.1b "), 19),
    ("stories  §A.3", rows_between(r"^### §A\.3 ", r"^### §A\.4 "), 17),
]

print("%-16s %8s %8s  %s" % ("table", "counted", "claimed", "verdict"))
bad = 0
for name, got, want in checks:
    ok = got == want
    if not ok:
        bad += 1
    print("%-16s %8s %8d  %s" % (name, got, want, "OK" if ok else "DRIFT"))
print()
print("mismatches:", bad)

# fixtures: §B.4 names 6 files - check they exist on disk
fixtures = ["fixtures/script_node5_8_lines.md", "fixtures/script_long_61.md",
            "fixtures/mock_llm_responses/plan_long.json", "fixtures/expected_sdl_long.json",
            "fixtures/expected_shots_long.json", "fixtures/knowledge_holdout.jsonl"]
missing = [f for f in fixtures if not pathlib.Path(f).is_file()]
print("fixtures named by §B.4:", len(fixtures), "| missing on disk:", missing)
