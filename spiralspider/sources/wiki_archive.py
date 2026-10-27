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
import types
import urllib.parse
from typing import NamedTuple

import scrapy
from scrapy.spidermiddlewares.httperror import HttpError

from ..items import Listed, Record
from ..middlewares import CAPTURE, FETCHED
from ..spiraltools_import import archive
from . import CategoryWalk, SourceSpider, provenance, quest_name
from .wiki_live import HOST, read_category

CAPTURE_STAMP = re.compile(r"/web/(\d{14})")
CATEGORY_CDX = ("https://web.archive.org/cdx/search/cdx?url=wiki.wizard101central.com/{}"
                "&fl=timestamp,statuscode&filter=statuscode:200")
PAGE_SAFE = ":_()/,!"


def wayback_url(at, raw, page):
    return f"{archive.ARCHIVE}{at}{'id_' if raw else ''}/{archive.WIKI}{urllib.parse.quote(page, safe=PAGE_SAFE)}"


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

    async def start(self):
        for request in self.next_category():
            yield request

    def fetched_stamp(self, response):
        """The capture's timestamp, as spiraltools caches it."""
        return CAPTURE_STAMP.search(response.url).group(1)

    def next_category(self):
        """The next category of the walk, or, once the walk is done, the request for the CDX index of quest pages."""
        following = self.walk.next()
        if following is None:
            yield scrapy.Request(archive.CDX, callback=self.read_index, errback=self.listing_failed)
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
        lookup = CATEGORY_CDX.format(urllib.parse.quote(target, safe=PAGE_SAFE + "%"))
        yield scrapy.Request(lookup, callback=self.read_captures, errback=self.category_failed,
                             cb_kwargs={"part": part, "cached": cached})

    def read_captures(self, response, part, cached):
        captures = [line.split() for line in response.text.splitlines()]
        stamps = [fields[0] for fields in captures if fields[1:2] == ["200"]]
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

    def read_index(self, response):
        archived = archive.archived_quests(types.SimpleNamespace(get=lambda url: (response.url, response.body)))
        index = []
        for page in sorted(self.walk.quests):
            entry = {"name": quest_name(page), "page": page}
            if page in archived:
                entry["timestamp"] = archived[page]
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
