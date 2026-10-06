"""Same question as `_probe_forbid_enforcement.py`, but WITH the edge's applicability domain bound.

Why this second probe exists (P14-270's own lesson): the naive check flagged `shot_005` as a
violation ("plan uses dolly_in, the injected block also forbids movement:dolly_in") - but that
forbid sits on an edge whose plain member is `shot_size=MS` while shot_005 is `MCU`.  Ignoring the
domain made a false positive on the very first real run.  So: bind the domain first, then compare.

Domain binding used here (deliberately narrow; its limits are printed, never hidden):
  * parse each `[TYPE] ...` line of the injected block into plain members (`k=kind:value`) and
    forbid members (inside the forbid braces);
  * canonicalise BOTH sides through `hypergraph.VALUE_ALIASES` (the hypergraph's own alias table:
    `static -> 固定`), so the plan's English and the edge's Chinese land in ONE space;
  * an edge APPLIES to a shot iff every plain member whose kind is a shot attribute
    (`shot_size` / `movement` / `intent`) matches that shot;
  * a violation = an applying edge whose forbid member collides with the shot's own value.

Anything it cannot bind is counted and reported, never silently treated as "no violation".
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, ".")
from block_director.knowledge.hypergraph import VALUE_ALIASES  # noqa: E402
from tools.kb_fetch import common  # noqa: E402

RUN = pathlib.Path("docs/evidence/20261006-long21")
OUT = pathlib.Path("work/_forbid_apply.json")

LINE = re.compile(r"^\[([A-Z_]+)\]\s+(.*)$")
FORBID = re.compile(r"([^\s=]{1,3})=\{([^}]*)\}")
MEMBER = re.compile(r"([a-z_]+)=([a-z_]+:([^ ]+))")
SHOT_ID = re.compile(r"shot_(\d{3})")

BINDS = {"shot_size": "shot_type", "movement": "movement", "intent": "intent_type"}


def canon(value):
    text = str(value).strip()
    return VALUE_ALIASES.get(text, VALUE_ALIASES.get(text.lower(), text))


def parse_block(text):
    """-> list of `{type, plain, forbid}` for every `[TYPE] ...` line in the injected block."""
    edges = []
    for line in text.split("\n"):
        m = LINE.match(line.strip())
        if not m:
            continue
        etype, rest = m.group(1), m.group(2)
        forb = []
        for _key, blob in FORBID.findall(rest):
            for token in blob.split(","):
                if ":" in token:
                    kind, value = token.split(":", 1)
                    forb.append((kind.strip(), canon(value)))
        rest = FORBID.sub(" ", rest)
        #: `MEMBER` groups: (key, "kind:value", value) -- key IS the kind for these blocks.
        plain = [(key, canon(value)) for key, _kindvalue, value in MEMBER.findall(rest)]
        edges.append({"type": etype, "plain": plain, "forbid": forb})
    return edges


def main():
    rows = common.read_jsonl(RUN / "llm_trace.jsonl")
    shots = json.loads((RUN / "export/export/shots.json").read_text(encoding="utf-8"))["shots"]
    by_id = {str(s["shot_id"]): s for s in shots}
    sdl = json.loads((RUN / "project/project.bdproj").read_text(encoding="utf-8"))
    sdl_shots = (sdl.get("scenes") or [{}])[0].get("shots") or []
    move = {}
    for entry in sdl_shots:
        cam = entry.get("camera") or {}
        cid = str(cam.get("id") or "")
        if "shot_" in cid and cam.get("movement"):
            move["shot_" + cid.split("shot_", 1)[1]] = canon(cam["movement"])

    applying = violations = unbound = 0
    details = []
    for row in rows:
        text = str(row.get("prompt") or "").replace("\\n", "\n")
        if not FORBID.search(text):
            continue
        ids = SHOT_ID.findall(text)
        if not ids:
            continue
        shot_id = "shot_%s" % ids[0]
        shot = by_id.get(shot_id)
        if not shot:
            continue
        attrs = {"shot_type": canon(shot.get("shot_type", "")),
                 "intent_type": canon(shot.get("intent_type", "")),
                 "movement": move.get(shot_id, "")}
        for edge in parse_block(text):
            bound = True
            for kind, value in edge["plain"]:
                attr = BINDS.get(kind)
                if attr is None:
                    continue
                if not attrs.get(attr):
                    unbound += 1
                    bound = False
                    break
                if value != attrs[attr]:
                    bound = False
                    break
            if not bound:
                continue
            applying += 1
            for kind, value in edge["forbid"]:
                attr = BINDS.get(kind)
                if attr is None or not attrs.get(attr):
                    unbound += 1
                    continue
                if value == attrs[attr]:
                    violations += 1
                    details.append({"shot_id": shot_id, "type": edge["type"],
                                    "plain": edge["plain"], "forbid": edge["forbid"],
                                    "shot_attr": [attr, attrs[attr]]})

    payload = {"run": str(RUN), "edges_applying": applying, "violations": violations,
               "unbound_members": unbound, "details": details}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8", newline="\n")
    print(json.dumps({"edges_applying": applying, "violations": violations,
                      "unbound_members": unbound, "details": len(details)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
