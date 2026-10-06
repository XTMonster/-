"""Does anything check that the built plan OBEYS the constraints that were injected?

GPT-6A's `c_arch` answer (docs/evidence/20261006-gpt6a-round2/answers/c_arch.md, point 3) claims the
biggest omission is the "knowledge -> Blender execution closed loop": the hypergraph's hard
constraints are *injected* into the prompt, but nothing verifies the produced plan honours them.
("检索相关不等于镜头可用")

This probe measures it on a REAL run instead of arguing about it:

1. read the per-shot prompts from `llm_trace.jsonl` (the channel 4.1b rule 2 allows:
   "the prompt that was actually sent"), and pull out the injected `forbid` members
   (the block renders them as `forbid={movement:<value>}`);
2. read the shot's actual plan from `shots.json` (declared/planned camera movement);
3. count how many shots have a plan that VIOLATES an injected forbid member.

Output is written to `work/_forbid_enforcement.json`; stdout stays ASCII-only.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, ".")
from tools.kb_fetch import common  # noqa: E402

RUN = pathlib.Path("docs/evidence/20261006-long21")
TRACE = RUN / "llm_trace.jsonl"
SHOTS = RUN / "export/export/shots.json"
SDL = RUN / "project/project.bdproj"
OUT = pathlib.Path("work/_forbid_enforcement.json")

#: The block renders a forbid member as `<key>={<kind>:<value>, ...}` where `<key>` is a single
#: CJK character, so match the generic "short key + ={...}" shape on the DECODED text.
FORBID = re.compile(r"([^\s=]{1,3})=\{([^}]*)\}")
SHOT_ID = re.compile(r"shot_(\d{3})")


def norm(token):
    """`kind:value` -> `(kind, value)`; values are compared case-insensitively."""
    token = token.strip()
    if ":" not in token:
        return ("", token.strip().lower())
    kind, value = token.split(":", 1)
    return (kind.strip().lower(), value.strip().lower())


def main():
    rows = common.read_jsonl(TRACE)
    shots = json.loads(SHOTS.read_text(encoding="utf-8"))
    shot_rows = shots.get("shots") or []
    by_id = {str(s.get("shot_id", "")): s for s in shot_rows}
    #: **计划的运镜在 SDL 里**（`scenes[].shots[].camera.movement`），不在 `shots.json`——
    #: 后者这一跑 64 镜里只有 1 镜的 `movements[]` 非空。
    sdl = json.loads(SDL.read_text(encoding="utf-8"))
    sdl_shots = (sdl.get("scenes") or [{}])[0].get("shots") or []
    move_by_cam = {}
    for entry in sdl_shots:
        cam = entry.get("camera") or {}
        move = str(cam.get("movement") or "").strip().lower()
        if move:
            #: SDL 的 shot 没有 `shot_id`（用相机名定位）——`BD_Cam_shot_005` -> `shot_005`。
            cid = str(cam.get("id") or "")
            if "shot_" in cid:
                move_by_cam["shot_" + cid.split("shot_", 1)[1]] = move

    per_call = []
    for row in rows:
        text = str(row.get("prompt") or "").replace("\\n", "\n")
        matches = FORBID.findall(text)
        if not matches:
            continue
        ids = SHOT_ID.findall(text)
        members = [norm(m) for _key, blob in matches for m in blob.split(",") if m.strip()]
        per_call.append({"request_id": row.get("request_id"), "purpose": row.get("purpose"),
                         "shot_ids": ["shot_%s" % i for i in ids],
                         "shot_id": ("shot_%s" % ids[0]) if ids else "",
                         "forbid": sorted({m for m in members if m[1]})})

    violations, checked = [], 0
    for call in per_call:
        plan = by_id.get(call["shot_id"])
        if not plan:
            continue
        moves = set()
        if move_by_cam.get(call["shot_id"]):
            moves.add(("movement", move_by_cam[call["shot_id"]]))
        for m in (plan.get("movements") or []):
            if isinstance(m, dict) and m.get("type"):
                moves.add(("movement", str(m["type"]).strip().lower()))
        if not moves or not call["forbid"]:
            continue
        checked += 1
        clash = sorted(moves & set(call["forbid"]))
        if clash:
            violations.append({"shot_id": call["shot_id"], "purpose": call["purpose"],
                               "movements": sorted(moves), "forbidden": call["forbid"],
                               "clash": clash})

    payload = {"trace": str(TRACE), "shots_in_plan": len(shot_rows),
               "shots_with_a_camera_movement": len(move_by_cam),
               "shot_calls_with_forbid": len(per_call),
               "shots_compared": checked, "violations": violations,
               "calls": per_call[:20]}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8", newline="\n")
    print(json.dumps({"trace_rows": len(rows), "shots_in_plan": len(shot_rows),
                      "shots_with_a_camera_movement": len(move_by_cam),
                      "shot_calls_with_forbid": len(per_call),
                      "shots_compared": checked,
                      "violations": len(violations)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
