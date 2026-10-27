"""The Scrapy settings of a crawl: politeness, the stop rule, the caches and the browser."""
import os
import socket

from .browser import playwright_settings

BOT_NAME = "spiralspider"
USER_AGENT = "spiralspider/0.1 (quest data for a Wizard101 data pack; read-only; one request per 3 seconds)"
LOG_LEVEL = "INFO"
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 3.0
DOWNLOAD_DELAY_JITTER = 0
CONCURRENT_REQUESTS_PER_DOMAIN = 1
AUTOTHROTTLE_ENABLED = False
RETRY_TIMES = 1
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524]
SPIDER_BACKOFF = 60.0
# Hosts that replay other sites' pages under /web/<timestamp>/<url>: the status and page of a replay are the captured
# site's, so the stop rule does not read them as this host refusing us.
REPLAY_HOSTS = ["web.archive.org"]
HTTPCACHE_ENABLED = True
HTTPCACHE_IGNORE_HTTP_CODES = RETRY_HTTP_CODES
# Responses pass these from the highest number down. The stop rule reads the decompressed page and drops a refusal
# before the HTTP cache can store it, so decompression sits above it, nearest the downloader.
DOWNLOADER_MIDDLEWARES = {
    "scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware": 960,
    "spiralspider.middlewares.StopRule": 950,
    "spiralspider.middlewares.PageCache": 860,
}
ITEM_PIPELINES = {"spiralspider.pipelines.HarvestPipeline": 300}


def crawl_settings(cache, environ=None, resolve=socket.gethostbyname):
    """The settings of a crawl whose caches go under `cache`, with the browser SPIDER_CDP_URL names, if any."""
    return {
        **{name: value for name, value in globals().items() if name.isupper()},
        "HTTPCACHE_DIR": os.path.join(os.path.abspath(cache), "httpcache"),
        **playwright_settings(environ, resolve),
    }
