"""The stop rule and the page cache, as Scrapy downloader middlewares."""
import asyncio
import datetime
import os

from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse, TextResponse
from scrapy.utils.defer import deferred_from_coro

from .browser import challenge_marker
from .spiraltools_import import archive

PAGE = "spiralspider_page"
FETCHED = "spiralspider_fetched"
BACKED_OFF = "spiralspider_backed_off"
# The message of the IgnoreRequest Scrapy's RobotsTxtMiddleware raises for a URL robots.txt disallows.
ROBOTS_REFUSAL = "Forbidden by robots.txt"


def refusal(source, url, reason):
    at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return {"source": source, "url": url, "reason": reason, "at": at}


class StopRule:
    """A 403, a challenge page, a second 429 after one backoff, or a URL robots.txt disallows blocks the spider's
    source: the refusal goes into the harvest, the spider is closed and nothing more is requested for it. It is never
    worked around. A first 429 pauses the crawl for SPIDER_BACKOFF seconds, then asks once more."""

    def __init__(self, crawler):
        self.crawler = crawler
        self.backoff = crawler.settings.getfloat("SPIDER_BACKOFF")
        self.blocked = False
        self.closing = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request):
        if self.blocked:
            raise IgnoreRequest(f"{self.crawler.spider.name} is blocked")

    async def process_response(self, request, response):
        if response.status == 429:
            if request.meta.get(BACKED_OFF):
                self.block(request, "HTTP 429 again after one backoff")
            await self.back_off()
            return request.replace(dont_filter=True, meta={**request.meta, BACKED_OFF: True})
        if response.status == 403:
            self.block(request, "HTTP 403")
        marker = challenge_marker(response.text) if isinstance(response, TextResponse) else None
        if marker:
            self.block(request, f"challenge page ({marker})")
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, IgnoreRequest) and str(exception) == ROBOTS_REFUSAL:
            self.block(request, "robots.txt disallows it")

    async def back_off(self):
        self.crawler.engine.pause()
        try:
            await asyncio.sleep(self.backoff)
        finally:
            self.crawler.engine.unpause()

    def block(self, request, reason):
        """Record the refusal (once per source), close the spider, and drop the response by raising IgnoreRequest."""
        spider = self.crawler.spider
        if not self.blocked:
            self.blocked = True
            spider.harvest.blocked.append(refusal(spider.name, request.url, reason))
            spider.logger.warning("blocked: %s: %s: %s; moving to the next source", spider.name, request.url, reason)
            self.closing = deferred_from_coro(self.crawler.engine.close_spider_async(reason="blocked"))
        raise IgnoreRequest(f"{spider.name}: {request.url}: {reason}")


class PageCache:
    """A source's pages in the layout of spiraltools' archive cache. A request whose meta[PAGE] names a page the spider
    fetched before is answered from <cache>/<timestamp>_<page>.html; a page fetched now (status 200, past the stop rule)
    is written there. Either way the response's meta[FETCHED] is that timestamp."""

    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request):
        key = request.meta.get(PAGE)
        hit = archive.cached(self.crawler.spider.cache, key) if key else None
        if not hit:
            return None
        with open(hit[1], encoding="utf-8") as f:
            body = f.read()
        request.meta[FETCHED] = hit[0]
        return HtmlResponse(request.url, body=body, encoding="utf-8", request=request, flags=["cached"])

    def process_response(self, request, response):
        key = request.meta.get(PAGE)
        if key is None or FETCHED in request.meta or response.status != 200:
            return response
        spider = self.crawler.spider
        stamp = spider.fetched_stamp(response)
        os.makedirs(spider.cache, exist_ok=True)
        with open(os.path.join(spider.cache, f"{stamp}_{archive.file_name(key)}.html"), "w", encoding="utf-8") as f:
            f.write(response.text)
        request.meta[FETCHED] = stamp
        return response
