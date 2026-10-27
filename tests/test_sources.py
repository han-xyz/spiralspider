import unittest

from context import fixture
from spiralspider.sources import Raw
from spiralspider.sources import folio, forum_guide, spiraltracker, wiki_archive, wiki_live


def raw(source, quest, name):
    return Raw(quest, fixture(name), {"source": source, "url": "https://example.invalid/", "fetched": "20261027"})


class WikiSources(unittest.TestCase):
    def test_live_page_parses_into_the_quest_fields(self):
        record = wiki_live.WikiLive(None, None).parse(raw("wiki_live", "Deeper and Deeper",
                                                          "quest_deeper_and_deeper.html"))
        self.assertEqual(record["name"], "Deeper and Deeper")
        self.assertEqual(record["prequests"], ["Door to the Stars"])
        self.assertEqual(record["giver"], "Edith Benchley")
        self.assertEqual(record["hand_in"], "Dalton Prescott")
        self.assertEqual(record["reward"], {"xp": 560, "gold": 30})
        self.assertEqual(record["leads_to"], ["Survivors"])
        self.assertTrue(record["mainline"])

    def test_archive_page_parses_like_the_live_page(self):
        archived = wiki_archive.WikiArchive(None, None).parse(raw("wiki_archive", "Deeper and Deeper",
                                                                  "quest_deeper_and_deeper.html"))
        live = wiki_live.WikiLive(None, None).parse(raw("wiki_live", "Deeper and Deeper",
                                                        "quest_deeper_and_deeper.html"))
        self.assertEqual(archived, live)

    def test_category_page_lists_subcategories_quests_and_next_page(self):
        subcategories, quests, next_url = wiki_live.read_category(fixture("category_celestia.html"))
        self.assertEqual(subcategories, ["Category:Survey_Camp_Quests", "Category:Celestia_Storyline_Quests"])
        self.assertEqual(quests, ["Quest:Deeper_and_Deeper", "Quest:Door_to_the_Stars"])
        self.assertEqual(next_url, "https://wiki.wizard101central.com/wiki/index.php"
                                   "?title=Category:Celestia_Quests&pagefrom=Gone+Fishing")


class ListingSources(unittest.TestCase):
    def test_spiraltracker_gives_order_next_quest_and_goal_types(self):
        record = spiraltracker.SpiralTracker(None, None).parse(raw("spiraltracker", "Deeper and Deeper",
                                                                   "spiraltracker_celestia.html"))
        self.assertEqual(record, {"name": "Deeper and Deeper", "order": 2, "leads_to": ["Survivors"],
                                  "goal_types": ["talk"]})

    def test_folio_gives_order_next_quest_and_goal_types(self):
        record = folio.Folio(None, None).parse(raw("folio", "Survivors", "folio_celestia.html"))
        self.assertEqual(record, {"name": "Survivors", "order": 3, "leads_to": [], "goal_types": ["defeat"]})

    def test_quest_absent_from_the_listing_has_no_record(self):
        self.assertIsNone(folio.Folio(None, None).parse(raw("folio", "Gone Fishing", "folio_celestia.html")))


class ForumGuide(unittest.TestCase):
    def test_guide_gives_the_reward(self):
        record = forum_guide.ForumGuide(None, None).parse(raw("forum_guide", "Deeper and Deeper",
                                                              "forum_guide_celestia.html"))
        self.assertEqual(record, {"name": "Deeper and Deeper", "reward": {"xp": 560, "gold": 30}})

    def test_quest_without_a_reward_line_has_no_record(self):
        self.assertIsNone(forum_guide.ForumGuide(None, None).parse(raw("forum_guide", "Survivors",
                                                                       "forum_guide_celestia.html")))


if __name__ == "__main__":
    unittest.main()
