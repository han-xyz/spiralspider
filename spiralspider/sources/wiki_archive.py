"""The Internet Archive's copies of the wiki: the category captures, a CDX lookup per quest, then its snapshot.

The walk, the index and the cache follow spiraltools' own (`quests/archive.py`), so
`spiraltools.py archive parse <World> --cache <cache>/wiki_archive` reads the same cache. The archive also records the
wiki's redirects and refusals as captures, replayed with the wiki's status or as a "Wayback Machine" page of its own,
so a page is read from a capture with status 200 that is usable: a category page that lists members, a quest page
with its infobox and no challenge. The captures are tried newest first.

When the world's quest category has no usable capture, the walk goes on from its Storyline, Side and Instance
subcategories, and the quests the world's Quest Tree page links to are added, as spiraltools' archive walk does.
"""
import json
import os
import re
import urllib.parse
from typing import NamedTuple

import scrapy
from scrapy.exceptions import IgnoreRequest
from scrapy.spidermiddlewares.httperror import HttpError

from ..items import Listed, Record
from ..browser import challenge_marker
from ..middlewares import CAPTURE, FETCHED, cached_copies
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
    """A category page that lists subcategories or quest pages."""
    has_lists = 'id="mw-pages"' in page or 'id="mw-subcategories"' in page
    return has_lists and any(archive.category_members(page))


def content_quests(page, key):
    """The Quest: pages the content of a page links to, without the page itself and other quest trees."""
    start = page.find('id="mw-content-text"')
    end = page.find('class="printfooter"', max(start, 0))
    block = page[max(start, 0):end if end >= 0 else None]
    found = [archive.page_key(m) for m in re.findall(r'href="[^"]*/wiki/(Quest:[^"#?]+)"', block)]
    return list(dict.fromkeys(q for q in found if q != key and not q.endswith("_Quest_Tree")))


def is_quest_page(page):
    return 'id="Quest_Information"' in page and challenge_marker(page) is None


def snapshot_attempts(stamps):
    """(raw, timestamp) in the order tried: each capture raw, newest first, then the oldest one's playback form."""
    return [(True, stamp) for stamp in stamps] + [(False, stamps[-1])] if stamps else []


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


class WikiArchive(SourceSpider):
    name = "wiki_archive"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cdx_unavailable = False
        self.lookup_failures = {}
        self.walk = CategoryWalk(self.registered.category)
        self.captures = {}

    async def start(self):
        for request in self.next_category():
            yield request

    def is_usable(self, response):
        return is_category_page(response.text) or is_quest_page(response.text)

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
            yield from self.without_listing(part)
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
        """Record a failed category lookup and preserve listings already collected."""
        if not failure.check(HttpError):
            return

        response = failure.value.response

        if response.status == 403:
            self.cdx_unavailable = True
            self.logger.warning(
                "Internet Archive CDX returned HTTP 403; "
                "preserving the partial archive index"
            )
            yield from self.quest_pages()
            return

        self.listing_failed(failure)
        yield from self.without_listing(failure.request.cb_kwargs["part"])

    def without_listing(self, part):
        """The walk goes on without a category page; for the world's quest category, from its typed subcategories and
        its Quest Tree page instead."""
        if part.category != self.walk.root or part.number:
            yield from self.next_category()
            return
        wiki = self.registered.wiki
        self.walk.queue += [(f"Category:{wiki}_{kind.title()}_Quests", None) for kind in archive.QUEST_TYPES]
        key = f"Quest:{wiki}_Quest_Tree"
        yield cdx_lookup("wiki/" + urllib.parse.quote(key, safe=PAGE_SAFE), self.read_tree_captures,
                         self.tree_failed, cb_kwargs={"key": key})

    def read_tree_captures(self, response, key):
        yield from self.next_tree(key, capture_stamps(response.text)[::-1])

    def next_tree(self, key, stamps):
        """The request for the newest capture of the Quest Tree page left; with none left, the walk goes on."""
        if not stamps:
            yield from self.next_category()
            return
        url = f"{archive.ARCHIVE}{stamps[0]}id_/{archive.WIKI}{urllib.parse.quote(key, safe=PAGE_SAFE)}"
        yield scrapy.Request(url, callback=self.read_tree, errback=self.tree_failed,
                             cb_kwargs={"key": key, "stamps": stamps[1:]})

    def read_tree(self, response, key, stamps):
        quests = content_quests(response.text, key) if challenge_marker(response.text) is None else []
        if not quests:
            yield from self.next_tree(key, stamps)
            return
        for quest in quests:
            self.walk.quests.setdefault(quest, {"zones": set(), "types": set()})
        yield from self.next_category()

    def tree_failed(self, failure):
        if failure.check(HttpError):
            asked = failure.request.cb_kwargs
            yield from self.next_tree(asked["key"], asked.get("stamps", []))

    def next_lookup(self):
        """The CDX lookup of the next quest page of the walk; once all are looked up, the index and the snapshots."""
        pending = [page for page in sorted(self.walk.quests) if page not in self.captures]
        if not pending:
            yield from self.quest_pages()
            return
        target = "wiki/" + urllib.parse.quote(pending[0], safe=PAGE_SAFE)
        yield cdx_lookup(target, self.read_lookup, self.lookup_failed, NEWEST_THREE, cb_kwargs={"page": pending[0]})

    def read_lookup(self, response, page):
        stamps = capture_stamps(response.text)
        self.captures[page] = stamps[::-1]
        yield from self.next_lookup()

    def lookup_failed(self, failure):
        """Distinguish an unavailable lookup from a successful empty result."""
        if failure.check(IgnoreRequest) and not failure.check(HttpError):
            return

        page = failure.request.cb_kwargs["page"]

        if failure.check(HttpError):
            response = failure.value.response
            status = response.status

            self.lookup_failures[page] = f"http_{status}"

            if status == 403:
                self.cdx_unavailable = True
                self.logger.warning(
                    "Internet Archive CDX returned HTTP 403; "
                    "stopping archive lookups and preserving partial results"
                )
                yield from self.quest_pages()
                return
        else:
            self.lookup_failures[page] = "request_failed"

        self.captures[page] = []
        yield from self.next_lookup()

    def write_index(self):
        """Write quest listings while distinguishing missing snapshots from failed lookups."""
        index = []

        for page in sorted(self.walk.quests):
            entry = {"name": quest_name(page), "page": page}
            stamps = self.captures.get(page, [])

            if stamps:
                entry["timestamp"] = stamps[0]
            elif page in self.lookup_failures:
                entry["lookup_status"] = self.lookup_failures[page]
                entry["missing_snapshot"] = True
            elif self.cdx_unavailable:
                entry["lookup_status"] = "cdx_unavailable"
                entry["missing_snapshot"] = True
            else:
                entry["missing_snapshot"] = True

            entry["zones"] = sorted(self.walk.quests[page]["zones"])
            entry["type"] = (
                "/".join(sorted(self.walk.quests[page]["types"])) or None
            )
            index.append(entry)

        os.makedirs(self.cache, exist_ok=True)
        with open(
            archive.index_path(self.cache, self.registered.name),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

        return index

    def quest_pages(self):
        """Emit known quest listings and fetch snapshots only when CDX is available."""
        index = self.write_index()

        # Category pages can establish that a quest exists even when its
        # archived page or CDX lookup is unavailable.
        for entry in index:
            yield Listed(self.name, entry["name"])

        # If CDX was refused, do not schedule further archive requests.
        if self.cdx_unavailable:
            return

        parsed_live = self.harvest.parsed_by("wiki_live")

        for entry in index:
            if not entry.get("timestamp"):
                continue

            if archive.title_norm(entry["name"]) not in parsed_live:
                yield from self.snapshot(entry)
    def snapshot(self, entry):
        """The quest's newest usable cached copy, else the request for its first capture not tried yet."""
        cached = []
        for stamp, path in cached_copies(self.cache, entry["page"]):
            with open(path, encoding="utf-8") as f:
                page = f.read()
            if is_quest_page(page):
                yield self.record(entry, page, True, stamp)
                return
            cached.append(stamp)
        stamps = [stamp for stamp in self.captures[entry["page"]] if stamp not in cached]
        yield from self.next_snapshot(entry, snapshot_attempts(stamps))

    def next_snapshot(self, entry, attempts):
        """The request for the first of `attempts`; with none left, the quest is missing its snapshot."""
        if not attempts:
            self.logger.info("%s: no usable capture", entry["page"])
            self.captures[entry["page"]] = []
            self.write_index()
            return
        raw, stamp = attempts[0]
        yield self.page_request(entry["page"], wayback_url(stamp, raw, entry["page"]), self.read_snapshot,
                                errback=self.snapshot_failed, meta={CAPTURE: stamp},
                                cb_kwargs={"entry": entry, "attempts": attempts})

    def read_snapshot(self, response, entry, attempts):
        if not is_quest_page(response.text):
            yield from self.next_snapshot(entry, attempts[1:])
            return
        yield self.record(entry, response.text, attempts[0][0], response.meta[FETCHED])

    def snapshot_failed(self, failure):
        if failure.check(HttpError):
            asked = failure.request.cb_kwargs
            yield from self.next_snapshot(asked["entry"], asked["attempts"][1:])

    def record(self, entry, page, raw, stamp):
        url = f"{archive.ARCHIVE}{stamp}{'id_' if raw else ''}/{archive.WIKI}{entry['page']}"
        fields = {"name": entry["name"], **archive.read_page(page)}
        return Record(self.name, entry["name"], fields, provenance(self.name, url, stamp))
