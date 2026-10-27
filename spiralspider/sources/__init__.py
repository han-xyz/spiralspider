"""Quest data sources, one Scrapy spider each, named after the source. A source spider lists the world's quests (a
`Listed` item per quest) and yields a `Record` of the fields it gives for each quest it has a page for.

Every request passes the stop rule (`middlewares.StopRule`). A page requested through `page_request` is cached in the
layout of spiraltools' archive cache (`middlewares.PageCache`), and its timestamp is the provenance's `fetched`.
"""
import datetime

import scrapy
from scrapy.spidermiddlewares.httperror import HttpError

from .. import spiraltools_import
from ..middlewares import PAGE
from ..spiraltools_import import archive

STAMP = "%Y%m%d%H%M%S"


def provenance(source, url, fetched):
    return {"source": source, "url": url, "fetched": fetched}


def requested_url(response):
    """The URL a page was asked for, before any redirect."""
    return response.meta.get("redirect_urls", [response.request.url])[0]


def quest_name(page):
    return page[len("Quest:"):].replace("_", " ")


class SourceSpider(scrapy.Spider):
    """A source as a Scrapy spider, given the world's name, the source's cache folder and the crawl's harvest."""

    def __init__(self, world, cache, harvest, **kwargs):
        super().__init__(**kwargs)
        self.registered = spiraltools_import.world(world)
        self.cache, self.harvest = cache, harvest

    def page_request(self, key, url, callback, meta=None, **kwargs):
        """A request for the page `key` (its file name in the cache), answered from the cache when it is there."""
        return scrapy.Request(url, callback=callback, meta={PAGE: key, **(meta or {})}, **kwargs)

    def fetched_stamp(self, response):
        """The timestamp a page fetched now is cached and cited under: the UTC time of the fetch."""
        return datetime.datetime.now(datetime.timezone.utc).strftime(STAMP)

    def listing_failed(self, failure):
        """A listing page answered with another HTTP error: recorded, and the source goes on with what it has."""
        if failure.check(HttpError):
            response = failure.value.response
            self.harvest.errors.append({"source": self.name, "url": response.url, "reason": f"HTTP {response.status}"})


class CategoryWalk:
    """The walk over a world's quest categories that spiraltools' archive walk makes, breadth first: quest page ->
    {"zones", "types"}, where a zone is a subcategory of the root that is not a quest type."""

    def __init__(self, root):
        self.root, self.queue, self.seen, self.quests = root, [(root, None)], set(), {}

    def next(self):
        """The next category not yet walked and its zone, or None when the walk is done."""
        while self.queue:
            category, zone = self.queue.pop(0)
            if category not in self.seen:
                self.seen.add(category)
                return category, zone
        return None

    def add(self, category, zone, subcategories, members):
        kind = archive.quest_type_of(category)
        for page in members:
            entry = self.quests.setdefault(page, {"zones": set(), "types": set()})
            if zone:
                entry["zones"].add(zone)
            if kind:
                entry["types"].add(kind)
        for sub in subcategories:
            is_zone = category == self.root and not archive.quest_type_of(sub)
            self.queue.append((sub, sub[len("Category:"):-len("_Quests")].replace("_", " ") if is_zone else zone))
