"""Quest data sources. Each one has a `name` and the same three steps:

- `enumerate(world)`: the names of the world's quests the source knows;
- `fetch(quest)`: the raw page for that quest as a `Raw`, or None when the source has no page for it;
- `parse(raw)`: the quest's fields as the source gives them, or None.

Every request goes through the crawl's `Gate`, which raises `Blocked` when the source refuses us.
"""
import datetime
import os
from typing import NamedTuple

import scrapy

from .. import spiraltools_import
from ..spiraltools_import import archive

STAMP = "%Y%m%d%H%M%S"


class Raw(NamedTuple):
    quest: str
    text: str
    provenance: dict


def provenance(source, url, fetched):
    return {"source": source, "url": url, "fetched": fetched}


def fetch_cached(gate, source, cache, key, url):
    """(timestamp, text) of a page from the cache, else fetched and cached as <timestamp>_<key>.html.

    None when the source answers with anything but 200.
    """
    hit = archive.cached(cache, key)
    if hit:
        with open(hit[1], encoding="utf-8") as f:
            return hit[0], f.read()
    response = gate.fetch(source, url)
    if response.status != 200:
        return None
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime(STAMP)
    os.makedirs(cache, exist_ok=True)
    with open(os.path.join(cache, f"{stamp}_{archive.file_name(key)}.html"), "w", encoding="utf-8") as f:
        f.write(response.text)
    return stamp, response.text


class SourceSpider(scrapy.Spider):
    """A source as a Scrapy spider named after it, given the world's name, the source's cache folder and the crawl's
    harvest. Every request it makes passes the stop rule; a page it requests with meta[PAGE] is cached (PageCache)."""

    def __init__(self, world, cache, harvest, **kwargs):
        super().__init__(**kwargs)
        self.registered = spiraltools_import.world(world)
        self.cache, self.harvest = cache, harvest

    def fetched_stamp(self, response):
        """The timestamp a page fetched now is cached and cited under: the UTC time of the fetch."""
        return datetime.datetime.now(datetime.timezone.utc).strftime(STAMP)
