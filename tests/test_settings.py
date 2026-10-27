import unittest

from scrapy.utils.conf import build_component_list
from scrapy.utils.test import get_crawler

import context  # noqa: F401
from spiralspider.cli import SOURCES
from spiralspider.settings import crawl_settings


def no_lookup(host):
    raise AssertionError("no lookup expected for " + host)


def settings(environ=None, resolve=no_lookup, spider=None):
    return get_crawler(spider, crawl_settings("cache", environ or {}, resolve)).settings


class Politeness(unittest.TestCase):
    def test_one_request_per_host_at_least_three_seconds_apart(self):
        crawl = settings()
        self.assertEqual(crawl.getfloat("DOWNLOAD_DELAY"), 3.0)
        self.assertEqual(crawl.getfloat("DOWNLOAD_DELAY_JITTER"), 0)
        self.assertEqual(crawl.getint("CONCURRENT_REQUESTS_PER_DOMAIN"), 1)
        self.assertFalse(crawl.getbool("AUTOTHROTTLE_ENABLED"))

    def test_no_source_loosens_the_politeness(self):
        for spider in SOURCES.values():
            crawl = settings(spider=spider)
            self.assertEqual((crawl.getfloat("DOWNLOAD_DELAY"), crawl.getint("CONCURRENT_REQUESTS_PER_DOMAIN"),
                              crawl.getbool("ROBOTSTXT_OBEY")), (3.0, 1, True), spider.name)

    def test_every_source_keeps_the_stop_rule_and_the_page_cache(self):
        for spider in SOURCES.values():
            enabled = build_component_list(settings(spider=spider).getwithbase("DOWNLOADER_MIDDLEWARES"))
            self.assertIn("spiralspider.middlewares.StopRule", enabled, spider.name)
            self.assertIn("spiralspider.middlewares.PageCache", enabled, spider.name)

    def test_robots_txt_is_obeyed(self):
        self.assertTrue(settings().getbool("ROBOTSTXT_OBEY"))

    def test_one_retry_for_server_errors_only(self):
        crawl = settings()
        self.assertEqual(crawl.getint("RETRY_TIMES"), 1)
        self.assertTrue(all(500 <= code < 600 for code in crawl.getlist("RETRY_HTTP_CODES")))

    def test_user_agent_names_the_spider_and_impersonates_no_browser(self):
        agent = settings()["USER_AGENT"]
        self.assertIn("spiralspider", agent)
        self.assertNotIn("Mozilla", agent)


class BrowserSettings(unittest.TestCase):
    def test_unset_means_the_bundled_headless_chromium(self):
        crawl = settings()
        self.assertIsNone(crawl.get("PLAYWRIGHT_CDP_URL"))
        self.assertEqual(crawl["PLAYWRIGHT_BROWSER_TYPE"], "chromium")
        self.assertTrue(crawl.getdict("PLAYWRIGHT_LAUNCH_OPTIONS")["headless"])

    def test_spider_cdp_url_becomes_the_playwright_cdp_url_by_address(self):
        crawl = settings({"SPIDER_CDP_URL": "http://browser:9222"}, {"browser": "172.18.0.2"}.__getitem__)
        self.assertEqual(crawl["PLAYWRIGHT_CDP_URL"], "http://172.18.0.2:9222")


if __name__ == "__main__":
    unittest.main()
