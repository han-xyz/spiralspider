"""spiraltools quest specs from merged quest records, checked against the spec schema of spiraldb/tools/README.md.

The sources give what the wiki shows: names, rewards, prerequisites. The client's keys a spec also needs (the WizQst
lang, personas, mob and item adjectives) cannot be read here, so each spec lists them in `needs_review` as blocking
and is written under `blocked/`, as spiraltools does; `spiraltools.py archive parse --cache <cache>/wiki_live`
resolves them against the client.
"""
import json
import os

from .spiraltools_import import archive

# The spec fields of spiraldb/tools/README.md ("Spec"), plus spiraltools' `source` and `needs_review`.
SPEC_FIELDS = {
    "id": str, "lang": str, "title": str, "giver": dict, "requires": list, "successors": list, "min_level": int,
    "mainline": bool, "level": int, "reward": dict, "dialogs": dict, "goals": list, "personas": dict, "source": dict,
    "needs_review": list,
}
GOAL_NEEDS = {
    "persona": ("persona",),
    "bounty": ("mobs", "count", "target"),
    "bountycollect": ("mobs", "count", "target"),
    "waypoint": ("zone",),
    "usage": ("items", "count", "descriptor"),
}


class SpecError(ValueError):
    pass


def spec_id(registered, name):
    """spiraltools' id for a quest it cannot match to the client: <folder>-Q-<normalised title>."""
    return f"{registered.folder}-Q-{archive.norm(name)}"


def build_spec(registered, merged, ids):
    """The spec of one merged quest record; ids maps a normalised quest title to its spec id."""
    fields, review = merged["fields"], []

    def unresolved(field, value, blocking):
        review.append({"field": field, "value": value, "blocking": blocking})

    def known_ids(titles, field):
        found = [ids[archive.title_norm(t)] for t in titles if archive.title_norm(t) in ids]
        for title in (t for t in titles if archive.title_norm(t) not in ids):
            unresolved(field, title, False)
        return found

    spec = {"id": spec_id(registered, fields["name"])}
    unresolved("lang", fields["name"], True)
    giver = fields.get("giver") or ("starts automatically" if fields.get("auto_start") else "none")
    unresolved("giver", giver, True)
    spec["requires"] = known_ids(fields.get("prequests", []), "requires")
    if not spec["requires"]:
        spec["min_level"] = registered.level
    successors = known_ids(fields.get("leads_to", []), "successors")
    if successors:
        spec["successors"] = successors
    if "mainline" in fields:
        spec["mainline"] = fields["mainline"]
    spec["level"] = registered.level
    reward = fields.get("reward", {})
    if {"xp", "gold"} <= set(reward):
        spec["reward"] = {"xp": reward["xp"], "gold": reward["gold"]}
    else:
        unresolved("reward", reward, False)
    spec["goals"] = []
    unresolved("goals", {"lines": fields.get("goals", []), "goal_types": fields.get("goal_types", []),
                         "hand_in": fields.get("hand_in")}, True)
    spec["source"] = merged["provenance"]
    spec["needs_review"] = review
    return spec


def validate(spec):
    """Raise SpecError when the spec has a field, type or goal the schema does not allow."""
    for field, value in spec.items():
        if field not in SPEC_FIELDS:
            raise SpecError(f"{spec.get('id')}: {field} is not a spec field")
        if not isinstance(value, SPEC_FIELDS[field]):
            raise SpecError(f"{spec.get('id')}: {field} must be {SPEC_FIELDS[field].__name__}")
    for goal in spec.get("goals", []):
        needs = GOAL_NEEDS.get(goal.get("type"))
        if needs is None:
            raise SpecError(f"{spec.get('id')}: goal type {goal.get('type')!r} is not one of {', '.join(GOAL_NEEDS)}")
        missing = [field for field in needs if field not in goal]
        if missing:
            raise SpecError(f"{spec.get('id')}: {goal['type']} goal lacks {', '.join(missing)}")


def write_spec(out_dir, spec):
    """Write the spec as <id>.json, under blocked/ when it has a blocking gap; returns the path."""
    validate(spec)
    is_blocked = any(item["blocking"] for item in spec.get("needs_review", []))
    directory = os.path.join(out_dir, "blocked") if is_blocked else out_dir
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{spec['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
    return path
