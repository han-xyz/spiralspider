import unittest

from spiralspider.middlewares import refusal


class RefusalTest(unittest.TestCase):
    def test_refusal_includes_host_and_status(self):
        result = refusal(
            "wiki_archive",
            "https://web.archive.org/cdx/search/cdx",
            "HTTP 403",
            status=403,
        )

        assert result["source"] == "wiki_archive"
        assert result["host"] == "web.archive.org"
        assert result["status"] == 403
        assert result["reason"] == "HTTP 403"
