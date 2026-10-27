"""The sandboxed browser and the rules every request obeys: one request per interval, robots.txt, and the stop rule."""
import contextlib
import os
import datetime
import tempfile
import time
import urllib.parse
import urllib.robotparser
from typing import NamedTuple

REQUEST_INTERVAL = 3.0
BACKOFF = 60.0
# Cloudflare's interstitials: the "Just a moment" page, its managed challenge script, and the Turnstile widget.
CHALLENGE_MARKERS = (
    "<title>Just a moment...</title>",
    "Performing security verification",
    "Verify you are human",
    "challenges.cloudflare.com",
    "cf-turnstile",
    "_cf_chl_opt",
    "cf-chl-",
)


class Response(NamedTuple):
    status: int
    text: str
    url: str


class Blocked(Exception):
    """A source refused us. The crawl records it and moves to the next source; it never works around it."""

    def __init__(self, source, url, reason):
        super().__init__(f"{source}: {url}: {reason}")
        self.source, self.url, self.reason = source, url, reason
        self.at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    def record(self):
        return {"source": self.source, "url": self.url, "reason": self.reason, "at": self.at}


def challenge_marker(text):
    """The first challenge marker in a page, or None for an ordinary page."""
    return next((marker for marker in CHALLENGE_MARKERS if marker in text), None)


class RateLimiter:
    def __init__(self, interval, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.last = None

    def wait(self):
        if self.last is not None:
            self.sleep(max(0.0, self.last + self.interval - self.clock()))
        self.last = self.clock()


class Gate:
    """Every request of a crawl goes through here: robots.txt, the rate limit, and the stop rule.

    A 403 or a challenge page raises Blocked at once; a 429 gets one backoff and one retry, and a second 429 raises
    Blocked. Any other status is returned for the source to read (a 404 is a missing page, not a refusal).
    """

    def __init__(self, fetcher, interval=REQUEST_INTERVAL, backoff=BACKOFF, clock=time.monotonic, sleep=time.sleep):
        self.fetcher, self.backoff, self.sleep = fetcher, backoff, sleep
        self.limiter = RateLimiter(interval, clock, sleep)
        self.robots = {}

    def fetch(self, source, url):
        if not self.allowed(source, url):
            raise Blocked(source, url, "robots.txt disallows it")
        return self.request(source, url)

    def request(self, source, url):
        for attempt in range(2):
            self.limiter.wait()
            response = self.fetcher.get(url)
            if response.status == 429:
                if attempt == 0:
                    self.sleep(self.backoff)
                    continue
                raise Blocked(source, url, "HTTP 429 again after one backoff")
            if response.status == 403:
                raise Blocked(source, url, "HTTP 403")
            marker = challenge_marker(response.text)
            if marker:
                raise Blocked(source, url, f"challenge page ({marker})")
            return response

    def allowed(self, source, url):
        parts = urllib.parse.urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self.robots:
            response = self.request(source, f"{host}/robots.txt")
            rules = urllib.robotparser.RobotFileParser()
            rules.parse(response.text.splitlines() if response.status == 200 else [])
            self.robots[host] = rules
        return self.robots[host].can_fetch("*", url)


class BrowserFetcher:
    """Page navigations in one Playwright page; the HTML as rendered, other content types as sent."""

    def __init__(self, page):
        self.page = page

    def get(self, url):
        response = self.page.goto(url, wait_until="domcontentloaded")
        if response is None:
            return Response(0, "", url)
        is_html = "html" in response.headers.get("content-type", "")
        return Response(response.status, self.page.content() if is_html else response.text(), self.page.url)


CDP_URL_VARIABLE = "SPIDER_CDP_URL"


def cdp_url(environ=None):
    """The DevTools endpoint of a browser the user runs themselves (SPIDER_CDP_URL), or None for the bundled Chromium."""
    value = (os.environ if environ is None else environ).get(CDP_URL_VARIABLE, "").strip()
    return value or None


@contextlib.contextmanager
def browser_page(environ=None):
    """A page in either the bundled headless Chromium (fresh user-data directory, deleted afterwards: no profile, no
    cookies) or, when SPIDER_CDP_URL names a DevTools endpoint, a browser the user runs themselves, attached over the
    Chrome DevTools Protocol. The challenge rule applies to both: it reads the page that comes back."""
    from playwright.sync_api import sync_playwright

    endpoint = cdp_url(environ)
    with sync_playwright() as playwright:
        if endpoint:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            try:
                yield page
            finally:
                page.close()
                browser.close()
            return
        with tempfile.TemporaryDirectory(prefix="spiralspider-") as profile:
            context = playwright.chromium.launch_persistent_context(profile, headless=True)
            try:
                yield context.new_page()
            finally:
                context.close()
