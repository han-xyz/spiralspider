"""The stop rule and the page cache, as Scrapy downloader middlewares."""
import asyncio
import datetime
import glob
import os
import re
import urllib.parse

from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse, TextResponse
from scrapy.utils.defer import deferred_from_coro

from .browser import challenge_marker
from .spiraltools_import import archive

PAGE = "spiralspider_page"
FETCHED = "spiralspider_fetched"
CAPTURE = "spiralspider_capture"
BACKED_OFF = "spiralspider_backed_off"
# The message of the IgnoreRequest Scrapy's RobotsTxtMiddleware raises for a URL robots.txt disallows.
ROBOTS_REFUSAL = "Forbidden by robots.txt"
REPLAY_PATH = re.compile(r"/web/\d+[a-z_]*/.")
BACKOFFS = 1
REPLAY_BACKOFFS = 5


def cached_copies(cache, key, prefix=""):
    """(timestamp, path) of every cached copy of a page, newest first; `prefix` goes between timestamp and page."""
    name = f"_{prefix}{archive.file_name(key)}.html"
    paths = [path for path in glob.glob(os.path.join(cache, f"[0-9]*{glob.escape(name)}"))
             if os.path.basename(path)[14:] == name]
    return sorted(((os.path.basename(path)[:14], path) for path in paths), reverse=True)


def refusal(source, url, reason):
    at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return {"source": source, "url": url, "reason": reason, "at": at}


class StopRule:
    """A 403, a challenge page, a second 429 after one backoff, or a URL robots.txt disallows blocks the spider's
    source: the refusal goes into the harvest, the spider is closed and nothing more is requested for it. It is never
    worked around. A first 429 pauses the crawl for SPIDER_BACKOFF seconds, then asks once more.

    A replay (a /web/<timestamp>/<url> page of a REPLAY_HOSTS host) carries the status and page the captured site gave
    then: its 403 or challenge page is an unusable capture, passed on for the spider to try another. Only the replay
    host's own 429 counts there, backed off REPLAY_BACKOFFS times before it blocks."""

    def __init__(self, crawler):
        self.crawler = crawler
        self.backoff = crawler.settings.getfloat("SPIDER_BACKOFF")
        self.replay_hosts = set(crawler.settings.getlist("REPLAY_HOSTS"))
        self.blocked = False
        self.closing = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request):
        if self.blocked:
            raise IgnoreRequest(f"{self.crawler.spider.name} is blocked")

    async def process_response(self, request, response):
        is_replay = self.is_replay(request.url)
        if response.status == 429:
            backoffs = request.meta.get(BACKED_OFF, 0)
            if backoffs >= (REPLAY_BACKOFFS if is_replay else BACKOFFS):
                self.block(request, f"HTTP 429 again after {backoffs} backoff(s)")
            await self.back_off()
            return request.replace(dont_filter=True, meta={**request.meta, BACKED_OFF: backoffs + 1})
        if is_replay:
            return response
        if response.status == 403:
            self.block(request, "HTTP 403")
        marker = challenge_marker(response.text) if isinstance(response, TextResponse) else None
        if marker:
            self.block(request, f"challenge page ({marker})")
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, IgnoreRequest) and str(exception) == ROBOTS_REFUSAL:
            self.block(request, "robots.txt disallows it")

    def is_replay(self, url):
        parts = urllib.parse.urlsplit(url)
        return parts.hostname in self.replay_hosts and REPLAY_PATH.match(parts.path) is not None

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
    """A source's pages in the layout of spiraltools' cache. A request whose meta[PAGE] names a page the spider fetched
    before is answered from <cache>/<timestamp>_<cache_prefix><page>.html, the newest one, or the one of the timestamp
    in meta[CAPTURE]; a page fetched now (status 200, past the stop rule, one the spider can use) is written there.
    Either way the response's meta[FETCHED] is that timestamp."""

    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request):
        key = request.meta.get(PAGE)
        if key is None:
            return None
        spider, stamp = self.crawler.spider, request.meta.get(CAPTURE)
        if stamp:
            path = os.path.join(spider.cache, f"{stamp}_{spider.cache_prefix}{archive.file_name(key)}.html")
            hit = (stamp, path) if os.path.exists(path) else None
        else:
            hit = next(iter(cached_copies(spider.cache, key, spider.cache_prefix)), None)
        if not hit:
            return None
        with open(hit[1], encoding="utf-8") as f:
            body = f.read()
        request.meta[FETCHED] = hit[0]
        return HtmlResponse(request.url, body=body, encoding="utf-8", request=request, flags=["cached"])

    def process_response(self, request, response):
        key = request.meta.get(PAGE)
        spider = self.crawler.spider
        if key is None or FETCHED in request.meta or response.status != 200 or not spider.is_usable(response):
            return response
        stamp = spider.fetched_stamp(response)
        os.makedirs(spider.cache, exist_ok=True)
        name = f"{stamp}_{spider.cache_prefix}{archive.file_name(key)}.html"
        with open(os.path.join(spider.cache, name), "w", encoding="utf-8") as f:
            f.write(response.text)
        request.meta[FETCHED] = stamp
        return response
