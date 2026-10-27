"""The Internet Archive's copies of the wiki: the CDX index and the category captures, then each quest's snapshot.

The walk, the index and the cache follow spiraltools' own (`quests/archive.py`), so
`spiraltools.py archive parse <World> --cache <cache>/wiki_archive` reads the same cache. A category page (and each of
its next pages) is read from the newest capture with status 200 that lists members: the archive also records the
wiki's redirects and refusals as captures, and serves them as a "Wayback Machine" page of its own.
"""
import glob
import json
import os
import re
import urllib.parse
from typing import NamedTuple

import scrapy
from scrapy.exceptions import IgnoreRequest
from scrapy.spidermiddlewares.httperror import HttpError

from ..items import Listed, Record
from ..middlewares import CAPTURE, FETCHED
from ..spiraltools_import import archive
from . import CategoryWalk, SourceSpider, provenance, quest_name
from .wiki_live import HOST, read_category

CAPTURE_STAMP = re.compile(r"/web/(\d{14})")
CDX_LOOKUP = ("https://web.archive.org/cdx/search/cdx?url=wiki.wizard101central.com/{}"
              "&fl=timestamp,statuscode&filter=statuscode:200")
NEWEST_THREE = "&limit=-3"
# The CDX server answers 503 under load; a lookup is small, so it is asked again more often than a page.
CDX_RETRIES = 3
PAGE_SAFE = ":_()/,!"


def wayback_url(at, raw, page):
    return f"{archive.ARCHIVE}{at}{'id_' if raw else ''}/{archive.WIKI}{urllib.parse.quote(page, safe=PAGE_SAFE)}"


def cdx_lookup(target, callback, errback, query="", **kwargs):
    """The CDX request for the captures with status 200 of `target`, a path and query on the wiki host; `query` adds
    CDX parameters."""
    url = CDX_LOOKUP.format(urllib.parse.quote(target, safe=PAGE_SAFE + "%")) + query
    return scrapy.Request(url, callback=callback, errback=errback, meta={"max_retry_times": CDX_RETRIES}, **kwargs)


def capture_stamps(answer):
    """The timestamps of the captures with status 200 in a CDX answer, oldest first."""
    captures = [line.split() for line in answer.splitlines()]
    return [fields[0] for fields in captures if fields[1:2] == ["200"]]


def is_category_page(page):
    return 'id="mw-pages"' in page or 'id="mw-subcategories"' in page


def cached_copies(cache, key):
    """(timestamp, path) of every cached capture of a page, newest first."""
    paths = sorted(glob.glob(os.path.join(cache, f"[0-9]*_{glob.escape(archive.file_name(key))}.html")), reverse=True)
    return [(os.path.basename(path)[:14], path) for path in paths]


class Part(NamedTuple):
    """A page of a category: `number` 0 is the category page, the next ones its "next page" links. `target` is the
    page's path and query on the wiki host."""
    category: str
    zone: str | None
    number: int
    target: str

    @property
    def key(self):
        return f"{self.category}_part{self.number}" if self.number else self.category


def snapshots(entry):
    """(raw, at) in the order they are tried: the newest raw snapshot, the CDX capture raw, that capture's playback."""
    return (True, archive.NEWEST), (True, entry["timestamp"]), (False, entry["timestamp"])


class WikiArchive(SourceSpider):
    name = "wiki_archive"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.walk = CategoryWalk(self.registered.category)
        self.captures = {}

    async def start(self):
        for request in self.next_category():
            yield request

    def fetched_stamp(self, response):
        """The capture's timestamp, as spiraltools caches it."""
        return CAPTURE_STAMP.search(response.url).group(1)

    def next_category(self):
        """The next category of the walk, or, once the walk is done, the CDX lookups of its quest pages."""
        following = self.walk.next()
        if following is None:
            yield from self.next_lookup()
            return
        category, zone = following
        yield from self.category_part(category, zone, 0, "wiki/" + urllib.parse.quote(category, safe=PAGE_SAFE))

    def category_part(self, category, zone, number, target):
        """A category page from the newest cached capture that lists members, else the CDX lookup of its captures."""
        part = Part(category, zone, number, target)
        cached = []
        for stamp, path in cached_copies(self.cache, part.key):
            with open(path, encoding="utf-8") as f:
                page = f.read()
            if is_category_page(page):
                yield from self.read_part(page, part)
                return
            cached.append(stamp)
        yield cdx_lookup(target, self.read_captures, self.category_failed, cb_kwargs={"part": part, "cached": cached})

    def read_captures(self, response, part, cached):
        stamps = capture_stamps(response.text)
        yield from self.next_capture(part, [stamp for stamp in reversed(stamps) if stamp not in cached])

    def next_capture(self, part, stamps):
        """The request for the newest capture left, raw; with none left, the walk goes on without this page."""
        if not stamps:
            self.logger.info("%s: no capture lists its members; its pages are listed only through other categories",
                             part.key)
            yield from self.next_category()
            return
        url = f"{archive.ARCHIVE}{stamps[0]}id_/{HOST}/{part.target}"
        yield self.page_request(part.key, url, self.read_capture, errback=self.capture_failed,
                                meta={CAPTURE: stamps[0]}, cb_kwargs={"part": part, "stamps": stamps[1:]})

    def read_capture(self, response, part, stamps):
        if not is_category_page(response.text):
            yield from self.next_capture(part, stamps)
            return
        yield from self.read_part(response.text, part)

    def read_part(self, page, part):
        subcategories, members, next_url = read_category(page)
        self.walk.add(part.category, part.zone, subcategories, members)
        if next_url:
            parts = urllib.parse.urlsplit(next_url)
            target = parts.path.lstrip("/") + (f"?{parts.query}" if parts.query else "")
            yield from self.category_part(part.category, part.zone, part.number + 1, target)
            return
        yield from self.next_category()

    def capture_failed(self, failure):
        if failure.check(HttpError):
            asked = failure.request.cb_kwargs
            yield from self.next_capture(asked["part"], asked["stamps"])

    def category_failed(self, failure):
        """The CDX lookup of a category failed: recorded, and the walk goes on without that category."""
        if failure.check(HttpError):
            self.listing_failed(failure)
            yield from self.next_category()

    def next_lookup(self):
        """The CDX lookup of the next quest page of the walk; once all are looked up, the index and the snapshots."""
        pending = [page for page in sorted(self.walk.quests) if page not in self.captures]
        if not pending:
            yield from self.write_index()
            return
        target = "wiki/" + urllib.parse.quote(pending[0], safe=PAGE_SAFE)
        yield cdx_lookup(target, self.read_lookup, self.lookup_failed, NEWEST_THREE, cb_kwargs={"page": pending[0]})

    def read_lookup(self, response, page):
        stamps = capture_stamps(response.text)
        self.captures[page] = stamps[-1] if stamps else None
        yield from self.next_lookup()

    def lookup_failed(self, failure):
        """A lookup that failed after its retries leaves that quest without a snapshot and the source goes on; a lookup
        the stop rule dropped ends the source."""
        if failure.check(IgnoreRequest) and not failure.check(HttpError):
            return
        self.captures[failure.request.cb_kwargs["page"]] = None
        yield from self.next_lookup()

    def write_index(self):
        index = []
        for page in sorted(self.walk.quests):
            entry = {"name": quest_name(page), "page": page}
            if self.captures[page]:
                entry["timestamp"] = self.captures[page]
            else:
                entry["missing_snapshot"] = True
            entry["zones"] = sorted(self.walk.quests[page]["zones"])
            entry["type"] = "/".join(sorted(self.walk.quests[page]["types"])) or None
            index.append(entry)
        os.makedirs(self.cache, exist_ok=True)
        with open(archive.index_path(self.cache, self.registered.name), "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        entries = [entry for entry in index if not entry.get("missing_snapshot")]
        for entry in entries:
            yield Listed(self.name, entry["name"])
        parsed_live = self.harvest.parsed_by("wiki_live")
        for entry in entries:
            if archive.title_norm(entry["name"]) not in parsed_live:
                yield self.snapshot_request(entry, 0)

    def snapshot_request(self, entry, attempt):
        raw, at = snapshots(entry)[attempt]
        return self.page_request(entry["page"], wayback_url(at, raw, entry["page"]), self.read_snapshot,
                                 errback=self.snapshot_failed, cb_kwargs={"entry": entry, "attempt": attempt})

    def read_snapshot(self, response, entry, attempt):
        raw, _ = snapshots(entry)[attempt]
        stamp = response.meta[FETCHED]
        url = f"{archive.ARCHIVE}{stamp}{'id_' if raw else ''}/{archive.WIKI}{entry['page']}"
        fields = {"name": entry["name"], **archive.read_page(response.text)}
        yield Record(self.name, entry["name"], fields, provenance(self.name, url, stamp))

    def snapshot_failed(self, failure):
        asked = failure.request.cb_kwargs
        if failure.check(HttpError) and asked["attempt"] + 1 < len(snapshots(asked["entry"])):
            yield self.snapshot_request(asked["entry"], asked["attempt"] + 1)
