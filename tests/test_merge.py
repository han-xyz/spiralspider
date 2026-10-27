import unittest

import context  # noqa: F401
from spiralspider.merge import merge


def prov(source):
    return {"source": source, "url": f"https://{source}.invalid/", "fetched": "20261027000000"}


class Merge(unittest.TestCase):
    def test_higher_priority_source_wins_each_field_whatever_the_order(self):
        merged = merge([
            ({"name": "Survivors", "reward": {"xp": 1, "gold": 1}, "order": 3}, prov("forum_guide")),
            ({"name": "Survivors", "reward": {"xp": 600, "gold": 40}, "mainline": False}, prov("wiki_archive")),
        ])
        self.assertEqual(merged["fields"]["reward"], {"xp": 600, "gold": 40})
        self.assertEqual(merged["provenance"]["reward"]["source"], "wiki_archive")

    def test_lower_priority_source_fills_a_missing_field(self):
        merged = merge([
            ({"name": "Survivors", "reward": {}, "mainline": False}, prov("wiki_live")),
            ({"name": "Survivors", "reward": {"xp": 600, "gold": 40}}, prov("forum_guide")),
        ])
        self.assertEqual(merged["fields"]["reward"], {"xp": 600, "gold": 40})
        self.assertEqual(merged["provenance"]["reward"]["source"], "forum_guide")
        self.assertIs(merged["fields"]["mainline"], False)
        self.assertEqual(merged["provenance"]["mainline"]["source"], "wiki_live")


if __name__ == "__main__":
    unittest.main()
