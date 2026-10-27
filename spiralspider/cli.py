"""spiralspider: quest data for a world from the sources that permit it, as spiraltools quest specs and a gap report."""
import argparse
import os
import sys

from scrapy.crawler import CrawlerProcess
from twisted.internet import defer

from .merge import PRIORITY, merge
from .pipelines import Harvest
from .report import format_report, gap_report, read_report, write_report
from .settings import crawl_settings
from .sources.folio import Folio
from .sources.forum_guide import ForumGuide
from .sources.spiraltracker import SpiralTracker
from .sources.wiki_archive import WikiArchive
from .sources.wiki_live import WikiLive
from .specs import build_spec, spec_id, write_spec
from .spiraltools_import import world

SOURCES = {source.name: source for source in (WikiLive, WikiArchive, SpiralTracker, Folio, ForumGuide)}
SELECTIONS = {"live": ("wiki_live",), "archive": ("wiki_archive",), "all": PRIORITY}


def crawl(registered, selected, cache):
    """Run the selected sources' spiders one after the other, in priority order, in one Scrapy process; a source the
    stop rule blocks is closed and the next one starts. Returns the harvest of all of them."""
    harvest = Harvest(selected)
    process = CrawlerProcess(crawl_settings(cache))
    failures = []

    @defer.inlineCallbacks
    def one_by_one():
        for name in selected:
            yield process.crawl(SOURCES[name], world=registered.name, cache=os.path.join(cache, name), harvest=harvest)

    def stop(_):
        # Imported here, not at the top: importing the reactor installs one, and the crawler must install asyncio's.
        from twisted.internet import reactor
        reactor.stop()

    one_by_one().addErrback(failures.append).addBoth(stop)
    process.start(stop_after_crawl=False)
    if failures:
        failures[0].raiseException()
    return harvest


def write_results(registered, harvest, out_dir):
    """Merge the harvest's records, write a spec per quest and the gap report; returns the report."""
    merged = {key: merge(pairs) for key, pairs in harvest.records.items()}
    ids = {key: spec_id(registered, m["fields"]["name"]) for key, m in merged.items()}
    specs = [build_spec(registered, m, ids) for m in merged.values()]
    for spec in specs:
        write_spec(out_dir, spec)
    report = gap_report(registered.name, harvest.counts, harvest.found, set(harvest.records), harvest.blocked,
                        harvest.errors, specs)
    write_report(out_dir, report)
    return report


def run_crawl(args):
    registered = world(args.world)
    out_dir = os.path.join(args.out, registered.name.lower())
    harvest = crawl(registered, SELECTIONS[args.source], args.cache)
    report = write_results(registered, harvest, out_dir)
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
