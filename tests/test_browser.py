import unittest

from context import fixture
from spiralspider.browser import Blocked, Gate, RateLimiter, Response, challenge_marker

WIKI = "https://wiki.wizard101central.com/wiki/Quest:Deeper_and_Deeper"
ROBOTS = "https://wiki.wizard101central.com/robots.txt"


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class FakeFetcher:
    def __init__(self, answers, robots="User-agent: *\nDisallow: /private/\n"):
        self.answers = {ROBOTS: [Response(200, robots, ROBOTS)]}
        for url, responses in answers.items():
            self.answers[url] = list(responses)
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        return self.answers[url].pop(0)


def gate(fetcher, clock=None):
    clock = clock or FakeClock()
    return Gate(fetcher, interval=3.0, backoff=60.0, clock=clock, sleep=clock.sleep)


class ChallengeDetector(unittest.TestCase):
    def test_just_a_moment_page_is_a_challenge(self):
        self.assertIsNotNone(challenge_marker(fixture("challenge_just_a_moment.html")))

    def test_turnstile_page_is_a_challenge(self):
        self.assertIsNotNone(challenge_marker(fixture("challenge_turnstile.html")))

    def test_quest_page_is_not_a_challenge(self):
        self.assertIsNone(challenge_marker(fixture("quest_deeper_and_deeper.html")))


class StopRule(unittest.TestCase):
    def test_challenge_page_stops_the_source(self):
        fetcher = FakeFetcher({WIKI: [Response(200, fixture("challenge_turnstile.html"), WIKI)]})
        with self.assertRaises(Blocked) as raised:
            gate(fetcher).fetch("wiki_live", WIKI)
        self.assertEqual((raised.exception.source, raised.exception.url), ("wiki_live", WIKI))
        self.assertIn("challenge", raised.exception.reason)

    def test_403_stops_the_source_without_retry(self):
        fetcher = FakeFetcher({WIKI: [Response(403, "Forbidden", WIKI)]})
        with self.assertRaises(Blocked):
            gate(fetcher).fetch("wiki_live", WIKI)
        self.assertEqual(fetcher.requested.count(WIKI), 1)

    def test_one_429_backs_off_once_then_answers(self):
        clock = FakeClock()
        fetcher = FakeFetcher({WIKI: [Response(429, "", WIKI), Response(200, "<html>ok</html>", WIKI)]})
        self.assertEqual(gate(fetcher, clock).fetch("wiki_live", WIKI).status, 200)
        self.assertIn(60.0, clock.slept)

    def test_second_429_stops_the_source(self):
        fetcher = FakeFetcher({WIKI: [Response(429, "", WIKI), Response(429, "", WIKI)]})
        with self.assertRaises(Blocked) as raised:
            gate(fetcher).fetch("wiki_live", WIKI)
        self.assertIn("429", raised.exception.reason)
        self.assertEqual(fetcher.requested.count(WIKI), 2)

    def test_robots_disallowed_url_is_never_requested(self):
        private = "https://wiki.wizard101central.com/private/page"
        fetcher = FakeFetcher({})
        with self.assertRaises(Blocked) as raised:
            gate(fetcher).fetch("wiki_live", private)
        self.assertNotIn(private, fetcher.requested)
        self.assertIn("robots.txt", raised.exception.reason)

    def test_blocked_is_recorded_with_source_url_and_time(self):
        record = Blocked("wiki_live", WIKI, "HTTP 403").record()
        self.assertEqual(set(record), {"source", "url", "reason", "at"})


class RateLimit(unittest.TestCase):
    def test_requests_are_at_least_the_interval_apart(self):
        clock = FakeClock()
        limiter = RateLimiter(3.0, clock, clock.sleep)
        starts = []
        for _ in range(3):
            limiter.wait()
            starts.append(clock.now)
            clock.now += 0.5
        self.assertEqual([b - a for a, b in zip(starts, starts[1:])], [3.0, 3.0])


if __name__ == "__main__":
    unittest.main()


class CdpUrlTest(unittest.TestCase):
    def test_unset_means_the_bundled_chromium(self):
        from spiralspider.browser import cdp_url
        self.assertIsNone(cdp_url({}))
        self.assertIsNone(cdp_url({"SPIDER_CDP_URL": "  "}))

    def test_set_names_the_users_browser(self):
        from spiralspider.browser import cdp_url
        self.assertEqual(cdp_url({"SPIDER_CDP_URL": "http://host.docker.internal:9222"}), "http://host.docker.internal:9222")
