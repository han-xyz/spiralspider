import unittest

from context import fixture
from spiralspider.browser import challenge_marker


class ChallengeDetector(unittest.TestCase):
    def test_just_a_moment_page_is_a_challenge(self):
        self.assertIsNotNone(challenge_marker(fixture("challenge_just_a_moment.html")))

    def test_turnstile_page_is_a_challenge(self):
        self.assertIsNotNone(challenge_marker(fixture("challenge_turnstile.html")))

    def test_quest_page_is_not_a_challenge(self):
        self.assertIsNone(challenge_marker(fixture("quest_deeper_and_deeper.html")))


if __name__ == "__main__":
    unittest.main()


class CdpUrlTest(unittest.TestCase):
    def test_unset_means_the_bundled_chromium(self):
        from spiralspider.browser import cdp_url
        self.assertIsNone(cdp_url({}, resolve=self.no_lookup))
        self.assertIsNone(cdp_url({"SPIDER_CDP_URL": "  "}, resolve=self.no_lookup))

    def test_an_address_or_localhost_is_used_as_given(self):
        from spiralspider.browser import cdp_url
        self.assertEqual(cdp_url({"SPIDER_CDP_URL": "http://127.0.0.1:9222"}, resolve=self.no_lookup), "http://127.0.0.1:9222")
        self.assertEqual(cdp_url({"SPIDER_CDP_URL": "http://localhost:9222/"}, resolve=self.no_lookup), "http://localhost:9222/")

    def test_a_host_name_is_resolved_to_its_address(self):
        from spiralspider.browser import cdp_url
        resolved = cdp_url({"SPIDER_CDP_URL": "http://browser:9222"}, resolve={"browser": "172.18.0.2"}.__getitem__)
        self.assertEqual(resolved, "http://172.18.0.2:9222")

    @staticmethod
    def no_lookup(host):
        raise AssertionError("no lookup expected for " + host)
