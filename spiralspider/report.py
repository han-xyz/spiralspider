"""The gap report of a crawl: per world, the quests found, parsed and missing, the sources that refused us, and what
the specs still need, by field."""
import json
import os

REPORT_FILE = "gap-report.json"


def gap_report(world_name, counts, found, parsed, blocked, errors, specs):
    """counts: source -> {"enumerated", "parsed"}; found: quest key -> name; parsed: the keys with a record."""
    needs = {}
    for spec in specs:
        for item in spec["needs_review"]:
            entry = needs.setdefault(item["field"], {"blocking": 0, "review": 0})
            entry["blocking" if item["blocking"] else "review"] += 1
    return {
        "world": world_name,
        "sources": counts,
        "found": len(found),
        "parsed": len(parsed),
        "specs_ready": sum(1 for spec in specs if not any(i["blocking"] for i in spec["needs_review"])),
        "blocked_sources": blocked,
        "errors": errors,
        "needs_review": dict(sorted(needs.items())),
        "missing_from_every_source": sorted(name for key, name in found.items() if key not in parsed),
    }


def write_report(out_dir, report):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, REPORT_FILE)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return path


def read_report(out_dir):
    path = os.path.join(out_dir, REPORT_FILE)
    if not os.path.exists(path):
        raise SystemExit(f"{path}: no gap report; run `spiralspider crawl <World>` first")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def format_report(report):
    missing = len(report["missing_from_every_source"])
    lines = [f"{report['world']}: {report['found']} quests found, {report['parsed']} parsed, "
             f"{report['specs_ready']} specs ready, {missing} missing from every source"]
    lines.append(f"{'source':<14} {'enumerated':>10} {'parsed':>8}")
    lines += [f"{name:<14} {c['enumerated']:>10} {c['parsed']:>8}" for name, c in report["sources"].items()]
    for event in report["blocked_sources"]:
        lines.append(f"blocked: {event['source']} at {event['at']}: {event['url']}: {event['reason']}")
    for event in report["errors"]:
        lines.append(f"error: {event['source']}: {event['url']}: {event['reason']}")
    lines.append(f"{'field':<20} {'blocking':>8} {'review':>8}")
    lines += [f"{field:<20} {n['blocking']:>8} {n['review']:>8}" for field, n in report["needs_review"].items()]
    lines += [f"missing: {name}" for name in report["missing_from_every_source"]]
    return "\n".join(lines)
