import asyncio
import os
import tempfile
import unittest

from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse, Request
from scrapy.utils.test import get_crawler

from context import fixture
from spiralspider.middlewares import CAPTURE, FETCHED, PAGE, PageCache, StopRule
from spiralspider.pipelines import Harvest
from spiralspider.settings import crawl_settings
from spiralspider.sources import SourceSpider, wiki_archive, wiki_live

WIKI = "https://wiki.wizard101central.com/wiki/Quest:Deeper_and_Deeper"


class Source(SourceSpider):
    name = "wiki_live"


class Engine:
    def __init__(self):
        self.calls = []

    def pause(self):
        self.calls.append("pause")

    def unpause(self):
        self.calls.append("unpause")

    async def close_spider_async(self, *, reason):
        self.calls.append(f"close: {reason}")


def crawler_for(cache):
    settings = crawl_settings(cache, environ={})
    crawler = get_crawler(Source, {**settings, "SPIDER_BACKOFF": 0})
    crawler.spider = Source(world="Celestia", cache=cache, harvest=Harvest(["wiki_live"]))
    crawler.engine = Engine()
    return crawler


def respond(status, body="<html><body>a quest</body></html>", request=None):
    request = request or Request(WIKI)
    return HtmlResponse(WIKI, status=status, body=body, encoding="utf-8", request=request)


def in_loop(call):
    async def run():
        try:
            return await call()
        finally:
            await asyncio.sleep(0)
    return asyncio.run(run())


def through(middleware, response):
    return in_loop(lambda: middleware.process_response(response.request, response))


async def refused(rule, request, exception):
    return rule.process_exception(request, exception)


class StopRuleTest(unittest.TestCase):
    def setUp(self):
        self.crawler = crawler_for(tempfile.mkdtemp())
        self.rule = StopRule.from_crawler(self.crawler)

    def blocked(self):
        return self.crawler.spider.harvest.blocked

    def test_403_blocks_the_source_and_closes_its_spider(self):
        with self.assertRaises(IgnoreRequest):
            through(self.rule, respond(403, "Forbidden"))
        self.assertEqual([(b["source"], b["url"], b["reason"]) for b in self.blocked()],
                         [("wiki_live", WIKI, "HTTP 403")])
        self.assertIn("close: blocked", self.crawler.engine.calls)

    def test_challenge_page_blocks_the_source(self):
        with self.assertRaises(IgnoreRequest):
            through(self.rule, respond(200, fixture("challenge_turnstile.html")))
        self.assertIn("challenge", self.blocked()[0]["reason"])

    def test_one_429_backs_off_and_retries_once(self):
        retry = through(self.rule, respond(429, ""))
        self.assertIsInstance(retry, Request)
        self.assertEqual(retry.url, WIKI)
        self.assertEqual(self.crawler.engine.calls, ["pause", "unpause"])
        self.assertEqual(self.blocked(), [])

    def test_second_429_after_the_backoff_blocks_the_source(self):
        retry = through(self.rule, respond(429, ""))
        with self.assertRaises(IgnoreRequest):
            through(self.rule, respond(429, "", request=retry))
        self.assertIn("429", self.blocked()[0]["reason"])

    def test_404_is_passed_through_for_the_source_to_read(self):
        response = respond(404, "<html>no such page</html>")
        self.assertIs(through(self.rule, response), response)
        self.assertEqual(self.blocked(), [])

    def test_robots_refusal_blocks_the_source(self):
        with self.assertRaises(IgnoreRequest):
            in_loop(lambda: refused(self.rule, Request(WIKI), IgnoreRequest("Forbidden by robots.txt")))
        self.assertIn("robots.txt", self.blocked()[0]["reason"])

    def test_nothing_more_is_requested_once_blocked(self):
        with self.assertRaises(IgnoreRequest):
            through(self.rule, respond(403, "Forbidden"))
        with self.assertRaises(IgnoreRequest):
            self.rule.process_request(Request("https://wiki.wizard101central.com/wiki/Quest:Survivors"))
        self.assertEqual(len(self.blocked()), 1)

    def test_blocked_is_recorded_with_source_url_reason_and_time(self):
        with self.assertRaises(IgnoreRequest):
            through(self.rule, respond(403, "Forbidden"))
        self.assertEqual(
            set(self.blocked()[0]),
            {"source", "url", "reason", "at", "host", "status"},
        )


class ReplayTest(unittest.TestCase):
    CAPTURE = ("https://web.archive.org/web/20260706213806id_/"
               "https://wiki.wizard101central.com/wiki/Quest:Training_Wings")

    def setUp(self):
        self.crawler = crawler_for(tempfile.mkdtemp())
        self.rule = StopRule.from_crawler(self.crawler)

    def replay(self, status, body="", request=None):
        request = request or Request(self.CAPTURE)
        return HtmlResponse(self.CAPTURE, status=status, body=body, encoding="utf-8", request=request)

    def test_replayed_403_is_an_unusable_capture_not_a_refusal(self):
        response = self.replay(403, "Forbidden")
        self.assertIs(through(self.rule, response), response)
        self.assertEqual(self.crawler.spider.harvest.blocked, [])

    def test_replayed_challenge_page_is_an_unusable_capture_not_a_refusal(self):
        response = self.replay(200, fixture("challenge_turnstile.html"))
        self.assertIs(through(self.rule, response), response)
        self.assertEqual(self.crawler.spider.harvest.blocked, [])

    def test_archive_429_is_retried_five_times_then_blocks(self):
        request = Request(self.CAPTURE)
        for _ in range(5):
            request = through(self.rule, self.replay(429, request=request))
            self.assertIsInstance(request, Request)
        with self.assertRaises(IgnoreRequest):
            through(self.rule, self.replay(429, request=request))
        self.assertIn("429", self.crawler.spider.harvest.blocked[0]["reason"])

    def test_403_from_the_cdx_still_blocks(self):
        lookup = "https://web.archive.org/cdx/search/cdx?url=wiki.wizard101central.com/wiki/Quest:Training_Wings"
        with self.assertRaises(IgnoreRequest):
            through(self.rule, HtmlResponse(lookup, status=403, body=b"", request=Request(lookup)))


class PageCacheTest(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.pages = PageCache.from_crawler(crawler_for(self.cache))

    def test_fetched_page_is_written_as_timestamp_and_page(self):
        response = respond(200, request=Request(WIKI, meta={PAGE: "Quest:Deeper_and_Deeper"}))
        self.pages.process_response(response.request, response)
        [name] = os.listdir(self.cache)
        self.assertRegex(name, r"^\d{14}_Quest_Deeper_and_Deeper\.html$")
        self.assertEqual(response.meta[FETCHED], name[:14])

    def written_name(self, source):
        self.pages.crawler.spider.cache_prefix = source.cache_prefix
        response = respond(200, request=Request(WIKI, meta={PAGE: "Quest:Deeper_and_Deeper"}))
        self.pages.process_response(response.request, response)
        [name] = os.listdir(self.cache)
        return name

    def test_live_wiki_pages_are_cached_as_live_pages(self):
        self.assertRegex(self.written_name(wiki_live.WikiLive), r"^\d{14}_live_Quest_Deeper_and_Deeper\.html$")

    def test_archive_captures_are_cached_without_a_prefix(self):
        self.assertRegex(self.written_name(wiki_archive.WikiArchive), r"^\d{14}_Quest_Deeper_and_Deeper\.html$")

    def test_live_page_is_read_back_from_its_own_name(self):
        self.written_name(wiki_live.WikiLive)
        self.assertIsNotNone(self.pages.process_request(Request(WIKI, meta={PAGE: "Quest:Deeper_and_Deeper"})))

    def test_cached_page_is_answered_without_a_request(self):
        with open(os.path.join(self.cache, "20261027000000_Quest_Deeper_and_Deeper.html"), "w") as f:
            f.write("<html>cached</html>")
        answer = self.pages.process_request(Request(WIKI, meta={PAGE: "Quest:Deeper_and_Deeper"}))
        self.assertEqual((answer.text, answer.meta[FETCHED]), ("<html>cached</html>", "20261027000000"))

    def test_request_for_one_capture_is_not_answered_with_another(self):
        with open(os.path.join(self.cache, "20260722063910_Category_Celestia_Quests.html"), "w") as f:
            f.write("<html>Wayback Machine</html>")
        asked = Request(WIKI, meta={PAGE: "Category:Celestia_Quests", CAPTURE: "20250101000000"})
        self.assertIsNone(self.pages.process_request(asked))

    def test_page_the_spider_cannot_use_is_not_cached(self):
        self.pages.crawler.spider.is_usable = lambda response: False
        response = respond(200, request=Request(WIKI, meta={PAGE: "Quest:Deeper_and_Deeper"}))
        self.pages.process_response(response.request, response)
        self.assertEqual(os.listdir(self.cache), [])

    def test_error_page_is_not_cached(self):
        response = respond(404, request=Request(WIKI, meta={PAGE: "Quest:Deeper_and_Deeper"}))
        self.pages.process_response(response.request, response)
        self.assertEqual(os.listdir(self.cache), [])


if __name__ == "__main__":
    unittest.main()
