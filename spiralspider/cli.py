"""spiralspider: quest data for a world from the sources that permit it, as spiraltools quest specs and a gap report."""
import argparse
import os
import sys
import urllib.error

from .browser import Blocked, BrowserFetcher, Gate, browser_page
from .merge import PRIORITY, merge
from .report import format_report, gap_report, read_report, write_report
from .sources.folio import Folio
from .sources.forum_guide import ForumGuide
from .sources.spiraltracker import SpiralTracker
from .sources.wiki_archive import WikiArchive
from .sources.wiki_live import WikiLive
from .specs import build_spec, spec_id, write_spec
from .spiraltools_import import archive, world

SOURCES = {source.name: source for source in (WikiLive, WikiArchive, SpiralTracker, Folio, ForumGuide)}
SELECTIONS = {"live": ("wiki_live",), "archive": ("wiki_archive",), "all": PRIORITY}


def crawl(registered, sources, out_dir):
    """Run each source in priority order; a source that refuses us is recorded and the crawl moves to the next one."""
    counts, found, records, blocked, errors = {}, {}, {}, [], []
    for source in sources:
        counts[source.name] = {"enumerated": 0, "parsed": 0}
        try:
            names = source.enumerate(registered.name)
            counts[source.name]["enumerated"] = len(names)
            for name in names:
                key = archive.title_norm(name)
                found.setdefault(key, name)
                if source.name == "wiki_archive" and any(p["source"] == "wiki_live" for _, p in records.get(key, [])):
                    continue
                raw = source.fetch(name)
                record = source.parse(raw) if raw else None
                if record:
                    records.setdefault(key, []).append((record, raw.provenance))
                    counts[source.name]["parsed"] += 1
        except Blocked as e:
            blocked.append(e.record())
            print(f"blocked: {e}; moving to the next source", file=sys.stderr)
        except urllib.error.HTTPError as e:
            errors.append({"source": source.name, "url": e.url, "reason": f"HTTP {e.code}"})
            print(f"{source.name}: {e.url}: HTTP {e.code}; moving to the next source", file=sys.stderr)
    merged = {key: merge(pairs) for key, pairs in records.items()}
    ids = {key: spec_id(registered, m["fields"]["name"]) for key, m in merged.items()}
    specs = [build_spec(registered, m, ids) for m in merged.values()]
    for spec in specs:
        write_spec(out_dir, spec)
    report = gap_report(registered.name, counts, found, set(records), blocked, errors, specs)
    write_report(out_dir, report)
    return report


def run_crawl(args):
    registered = world(args.world)
    out_dir = os.path.join(args.out, registered.name.lower())
    with browser_page() as page:
        gate = Gate(BrowserFetcher(page))
        sources = [SOURCES[name](gate, os.path.join(args.cache, name)) for name in SELECTIONS[args.source]]
        report = crawl(registered, sources, out_dir)
    print(format_report(report))
    print(f"specs and gap report: {out_dir}")


def run_gaps(args):
    print(format_report(read_report(os.path.join(args.out, world(args.world).name.lower()))))


def run_sources(_args):
    for rank, name in enumerate(PRIORITY, 1):
        summary = (sys.modules[SOURCES[name].__module__].__doc__ or "").strip().splitlines()[0]
        print(f"{rank}. {name:<14} {summary}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="spiralspider", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    crawl_parser = commands.add_parser("crawl", help="crawl a world's quests into specs and a gap report")
    crawl_parser.add_argument("world")
    crawl_parser.add_argument("--source", choices=SELECTIONS, default="all")
    crawl_parser.add_argument("--out", default="out", help="specs go to <out>/<world>/ (default ./out)")
    crawl_parser.add_argument("--cache", default="cache", help="fetched pages, one folder per source (default ./cache)")
    crawl_parser.set_defaults(run=run_crawl)
    gaps_parser = commands.add_parser("gaps", help="print the gap report of the last crawl of a world")
    gaps_parser.add_argument("world")
    gaps_parser.add_argument("--out", default="out")
    gaps_parser.set_defaults(run=run_gaps)
    commands.add_parser("sources", help="list the sources in priority order").set_defaults(run=run_sources)
    args = parser.parse_args(argv)
    args.run(args)
