"""spiralspider: quest data for a world from the sources that permit it, as spiraltools quest specs and a gap report."""
import argparse
import os
import sys

from scrapy.crawler import AsyncCrawlerRunner
from scrapy.utils.defer import deferred_from_coro
from scrapy.utils.log import configure_logging
from scrapy.utils.reactor import install_reactor

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
ASYNCIO_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"


def crawl(registered, selected, cache):
    """Run the selected sources' spiders one after the other, in priority order; a source the stop rule blocks is
    closed and the next one starts. Returns the harvest of all of them."""
    harvest = Harvest(selected)
    crawls = [(SOURCES[name], {"world": registered.name, "cache": os.path.join(cache, name), "harvest": harvest})
              for name in selected]
    run_one_after_another(crawl_settings(cache), crawls)
    return harvest


def run_one_after_another(settings, crawls):
    """Run each (spider class, spider arguments) of `crawls` to its end before the next starts, in one reactor, as
    Scrapy's "running multiple spiders sequentially" does; the crawls start once the reactor runs."""
    configure_logging(settings)
    install_reactor(ASYNCIO_REACTOR)
    from twisted.internet import reactor
    runner = AsyncCrawlerRunner(settings)
    failures = []

    async def one_by_one():
        for spider, arguments in crawls:
            await runner.crawl(spider, **arguments)

    def start():
        done = deferred_from_coro(one_by_one())
        done.addErrback(failures.append)
        done.addBoth(lambda _: reactor.stop())

    reactor.callWhenRunning(start)
    reactor.run()
    if failures:
        failures[0].raiseException()


def write_results(registered, harvest, out_dir):
    """Merge the harvest's records, write a spec per quest and the gap report; returns the report. A quest whose merged
    record has no name is an error of the sources that gave it, and gets no spec."""
    merged, errors = {}, list(harvest.errors)
    for key, pairs in harvest.records.items():
        record = merge(pairs)
        if "name" in record["fields"]:
            merged[key] = record
            continue
        errors += [{"source": source["source"], "url": source["url"], "reason": "a record without a quest name"}
                   for _, source in pairs]
    ids = {key: spec_id(registered, m["fields"]["name"]) for key, m in merged.items()}
    specs = [build_spec(registered, m, ids) for m in merged.values()]
    for spec in specs:
        write_spec(out_dir, spec)
    report = gap_report(registered.name, harvest.counts, harvest.found, set(merged), harvest.blocked, errors, specs)
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
