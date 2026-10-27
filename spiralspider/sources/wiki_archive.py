"""The Internet Archive's copies of the wiki: the CDX index and the category captures, then each quest's snapshot.

The walk, the index and the cache follow spiraltools' own (`quests/archive.py`), so
`spiraltools.py archive parse <World> --cache <cache>/wiki_archive` reads the same cache.
"""
import json
import os
import re
import types
import urllib.parse

import scrapy
from scrapy.spidermiddlewares.httperror import HttpError

from ..items import Listed, Record
from ..middlewares import FETCHED
from ..spiraltools_import import archive
from . import CategoryWalk, SourceSpider, provenance, quest_name

CAPTURE = re.compile(r"/web/(\d{14})")


def wayback_url(at, raw, page):
    return f"{archive.ARCHIVE}{at}{'id_' if raw else ''}/{archive.WIKI}{urllib.parse.quote(page, safe=':_()/,!')}"


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
        return CAPTURE.search(response.url).group(1)

    def next_category(self):
        """The request for the next category of the walk, or, once the walk is done, the CDX index."""
        following = self.walk.next()
        if following is None:
            yield scrapy.Request(archive.CDX, callback=self.read_index, errback=self.listing_failed)
            return
        yield self.category_request(*following, year=0)

    def category_request(self, category, zone, year):
        """The category's capture nearest the year archive.CATEGORY_YEARS[year]."""
        url = wayback_url(archive.CATEGORY_YEARS[year], False, category)
        return self.page_request(category, url, self.read_category_page, errback=self.category_failed,
                                 cb_kwargs={"category": category, "zone": zone, "year": year})

    def read_category_page(self, response, category, zone, year):
        self.walk.add(category, zone, *archive.category_members(response.text))
        yield from self.next_category()

    def category_failed(self, failure):
        """A 404 tries the next older capture; another HTTP error is recorded and the walk goes on without it."""
        if not failure.check(HttpError):
            return
        asked = failure.request.cb_kwargs
        is_missing = failure.value.response.status == 404
        if is_missing and asked["year"] + 1 < len(archive.CATEGORY_YEARS):
            yield self.category_request(asked["category"], asked["zone"], asked["year"] + 1)
            return
        if not is_missing:
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
