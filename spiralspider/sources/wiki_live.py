"""The live Wizard101 Central wiki through the sandboxed browser: the world's quest categories, then each quest page.

Pages are cached in the layout of spiraltools' cache (`<timestamp>_live_<page>.html` and `index-<world>.json`), so
`spiraltools.py archive parse <World> --cache <cache>/wiki_live` builds client-resolved specs from them.
"""
import html
import json
import os
import re
import urllib.parse

from scrapy.spidermiddlewares.httperror import HttpError

from .. import settings
from ..items import Listed, Record
from ..middlewares import FETCHED
from ..spiraltools_import import archive
from . import CategoryWalk, SourceSpider, provenance, quest_name, requested_url

HOST = "https://wiki.wizard101central.com"
NEXT_PAGE = re.compile(r'<a href="([^"]*pagefrom=[^"]*)"[^>]*>next page</a>')
PLAYWRIGHT_HANDLER = "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler"
BROWSER = {"playwright": True, "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded"}}
PRE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S)


def read_category(page):
    """The subcategories and quest pages a category page lists, and the URL of its next page or None."""
    subcategories, quests = archive.category_members(page)
    found = NEXT_PAGE.search(page)
    next_url = urllib.parse.urljoin(HOST, html.unescape(found.group(1)).split("#")[0]) if found else None
    return subcategories, quests, next_url


class ThroughBrowser:
    """Every request of the spider goes through the browser, robots.txt included, so the stop rule judges the site on
    the one client the crawl uses. The browser renders a robots.txt as a page with the text in a <pre>, which is read
    back here for Scrapy's robots.txt parser."""

    def process_request(self, request):
        for key, value in BROWSER.items():
            request.meta.setdefault(key, value)

    def process_response(self, request, response):
        rendered = PRE.search(response.text) if request.url.endswith("/robots.txt") else None
        if rendered is None:
            return response
        return response.replace(body=html.unescape(rendered.group(1)).encode("utf-8"), encoding="utf-8")


class WikiLive(SourceSpider):
    name = "wiki_live"
    # spiraltools' parser reads <timestamp>_live_<page>.html as a live page, an unprefixed name as an archive capture.
    cache_prefix = "live_"
    custom_settings = {
        "DOWNLOAD_HANDLERS": {"http": PLAYWRIGHT_HANDLER, "https": PLAYWRIGHT_HANDLER},
        "HTTPCACHE_ENABLED": False,
        # A spider's DOWNLOADER_MIDDLEWARES replaces the crawl's, so the crawl's are repeated here.
        "DOWNLOADER_MIDDLEWARES": {
            **settings.DOWNLOADER_MIDDLEWARES,
            "spiralspider.sources.wiki_live.ThroughBrowser": 500,
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.walk = CategoryWalk(self.registered.category)

    async def start(self):
        for request in self.next_category():
            yield request

    def next_category(self):
        """The request for the next category of the walk, or, once the walk is done, the world's quest pages."""
        following = self.walk.next()
        if following is None:
            yield from self.quest_pages()
            return
        category, zone = following
        yield self.category_request(category, zone, f"{archive.WIKI}{category}", 0)

    def category_request(self, category, zone, url, part):
        key = f"{category}_part{part}" if part else category
        return self.page_request(key, url, self.read_category_page, errback=self.category_failed,
                                 cb_kwargs={"category": category, "zone": zone, "part": part})

    def read_category_page(self, response, category, zone, part):
        subcategories, members, next_url = read_category(response.text)
        self.walk.add(category, zone, subcategories, members)
        if next_url:
            yield self.category_request(category, zone, next_url, part + 1)
            return
        yield from self.next_category()

    def category_failed(self, failure):
        if failure.check(HttpError):
            self.listing_failed(failure)
            yield from self.next_category()

    def quest_pages(self):
        index = [{"name": quest_name(page), "page": page, "zones": sorted(entry["zones"]),
                  "type": "/".join(sorted(entry["types"])) or None} for page, entry in sorted(self.walk.quests.items())]
        os.makedirs(self.cache, exist_ok=True)
        with open(archive.index_path(self.cache, self.registered.name), "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        for entry in index:
            yield Listed(self.name, entry["name"])
        for entry in index:
            url = archive.WIKI + urllib.parse.quote(entry["page"], safe=":_()/,!")
            yield self.page_request(entry["page"], url, self.read_quest, cb_kwargs={"quest": entry["name"]})

    def read_quest(self, response, quest):
        fields = {"name": quest, **archive.read_page(response.text)}
        yield Record(self.name, quest, fields, provenance(self.name, requested_url(response), response.meta[FETCHED]))
