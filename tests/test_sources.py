import asyncio
import tempfile
import unittest

from scrapy.http import HtmlResponse, Request

from context import fixture
from spiralspider.items import Listed, Record
from spiralspider.merge import PRIORITY
from spiralspider.middlewares import FETCHED
from spiralspider.pipelines import Harvest
from spiralspider.sources import folio, forum_guide, spiraltracker, wiki_archive, wiki_live

DEEPER = "https://wiki.wizard101central.com/wiki/Quest:Deeper_and_Deeper"


def spider(cls):
    return cls(world="Celestia", cache=tempfile.mkdtemp(), harvest=Harvest(PRIORITY))


def response(name, url="https://example.invalid/celestia"):
    return HtmlResponse(url, body=fixture(name), encoding="utf-8", request=Request(url, meta={FETCHED: "20261027"}))


def records(items):
    return {item.quest: item.fields for item in items if isinstance(item, Record)}


def first_request(source):
    async def first():
        return await anext(aiter(source.start()))
    return asyncio.run(first())


class WikiSources(unittest.TestCase):
    def test_live_page_parses_into_the_quest_fields(self):
        [record] = spider(wiki_live.WikiLive).read_quest(response("quest_deeper_and_deeper.html", DEEPER),
                                                         quest="Deeper and Deeper")
        self.assertEqual(record.fields["name"], "Deeper and Deeper")
        self.assertEqual(record.fields["prequests"], ["Door to the Stars"])
        self.assertEqual(record.fields["giver"], "Edith Benchley")
        self.assertEqual(record.fields["hand_in"], "Dalton Prescott")
        self.assertEqual(record.fields["reward"], {"xp": 560, "gold": 30})
        self.assertEqual(record.fields["leads_to"], ["Survivors"])
        self.assertTrue(record.fields["mainline"])
        self.assertEqual(record.provenance, {"source": "wiki_live", "url": DEEPER, "fetched": "20261027"})

    def test_archive_page_parses_like_the_live_page(self):
        entry = {"name": "Deeper and Deeper", "page": "Quest:Deeper_and_Deeper", "timestamp": "20250827061209"}
        [archived] = spider(wiki_archive.WikiArchive).read_snapshot(response("quest_deeper_and_deeper.html"),
                                                                    entry=entry, attempt=0)
        [live] = spider(wiki_live.WikiLive).read_quest(response("quest_deeper_and_deeper.html"),
                                                       quest="Deeper and Deeper")
        self.assertEqual(archived.fields, live.fields)

    def test_category_page_lists_subcategories_quests_and_next_page(self):
        subcategories, quests, next_url = wiki_live.read_category(fixture("category_celestia.html"))
        self.assertEqual(subcategories, ["Category:Survey_Camp_Quests", "Category:Celestia_Storyline_Quests"])
        self.assertEqual(quests, ["Quest:Deeper_and_Deeper", "Quest:Door_to_the_Stars"])
        self.assertEqual(next_url, "https://wiki.wizard101central.com/wiki/index.php"
                                   "?title=Category:Celestia_Quests&pagefrom=Gone+Fishing")

    def test_category_walk_follows_the_next_page(self):
        live = spider(wiki_live.WikiLive)
        [request] = live.read_category_page(response("category_celestia.html"), category="Category:Celestia_Quests",
                                            zone=None, part=0)
        self.assertIn("pagefrom=Gone+Fishing", request.url)

    def test_only_the_live_wiki_goes_through_the_browser(self):
        self.assertTrue(first_request(spider(wiki_live.WikiLive)).meta.get("playwright"))
        for source in (wiki_archive.WikiArchive, spiraltracker.SpiralTracker, folio.Folio):
            self.assertFalse(first_request(spider(source)).meta.get("playwright"))


class ListingSources(unittest.TestCase):
    def test_spiraltracker_gives_order_next_quest_and_goal_types(self):
        items = list(spider(spiraltracker.SpiralTracker).read_listing(response("spiraltracker_celestia.html")))
        self.assertEqual(records(items)["Deeper and Deeper"], {"name": "Deeper and Deeper", "order": 2,
                                                                "leads_to": ["Survivors"], "goal_types": ["talk"]})

    def test_folio_gives_order_next_quest_and_goal_types(self):
        items = list(spider(folio.Folio).read_listing(response("folio_celestia.html")))
        self.assertEqual(records(items)["Survivors"], {"name": "Survivors", "order": 3, "leads_to": [],
                                                        "goal_types": ["defeat"]})

    def test_every_listed_quest_and_only_those_has_a_record(self):
        items = list(spider(folio.Folio).read_listing(response("folio_celestia.html")))
        listed = [item.quest for item in items if isinstance(item, Listed)]
        self.assertEqual(list(records(items)), listed)
        self.assertNotIn("Gone Fishing", listed)


class ForumGuide(unittest.TestCase):
    def test_guide_gives_the_reward_of_the_quests_it_rewards(self):
        items = list(spider(forum_guide.ForumGuide).read_guide(response("forum_guide_celestia.html")))
        self.assertEqual(records(items)["Deeper and Deeper"], {"name": "Deeper and Deeper",
                                                                "reward": {"xp": 560, "gold": 30}})
        self.assertNotIn("Survivors", records(items))


if __name__ == "__main__":
    unittest.main()
