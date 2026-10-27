import json
import os
import tempfile
import unittest

from scrapy.http import HtmlResponse, Request
from scrapy.spidermiddlewares.httperror import HttpError
from scrapy.utils.misc import build_from_crawler, load_object
from scrapy.utils.conf import build_component_list
from scrapy.utils.test import get_crawler
from twisted.python.failure import Failure

from context import fixture
from spiralspider.items import Listed, Record
from spiralspider.merge import PRIORITY
from spiralspider.middlewares import FETCHED
from spiralspider.pipelines import Harvest
from spiralspider.settings import crawl_settings
from spiralspider.sources import folio, forum_guide, spiraltracker, wiki_archive, wiki_live

DEEPER = "https://wiki.wizard101central.com/wiki/Quest:Deeper_and_Deeper"
CELESTIA = "Category:Celestia_Quests"


def spider(cls):
    return cls(world="Celestia", cache=tempfile.mkdtemp(), harvest=Harvest(PRIORITY))


def response(name, url="https://example.invalid/celestia"):
    return HtmlResponse(url, body=fixture(name), encoding="utf-8", request=Request(url, meta={FETCHED: "20261027"}))


def records(items):
    return {item.quest: item.fields for item in items if isinstance(item, Record)}


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
                                                                    entry=entry, attempts=[(True, "20250827061209")])
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


def own_middlewares(source):
    crawler = get_crawler(source, crawl_settings(tempfile.mkdtemp(), {}))
    paths = build_component_list(crawler.settings.getwithbase("DOWNLOADER_MIDDLEWARES"))
    return [build_from_crawler(load_object(path), crawler) for path in paths if path.startswith("spiralspider.")]


def as_sent(source, url, meta=None):
    request = Request(url, meta=meta or {})
    for middleware in own_middlewares(source):
        middleware.process_request(request)
    return request


class Browser(unittest.TestCase):
    ROBOTS = "https://wiki.wizard101central.com/robots.txt"

    def test_live_wiki_robots_txt_goes_through_the_browser_like_its_pages(self):
        robots = as_sent(wiki_live.WikiLive, self.ROBOTS, {"dont_obey_robotstxt": True})
        self.assertTrue(robots.meta.get("playwright"))
        self.assertEqual(robots.meta.get("playwright_page_goto_kwargs"), {"wait_until": "domcontentloaded"})
        self.assertTrue(as_sent(wiki_live.WikiLive, DEEPER).meta.get("playwright"))

    def test_no_other_source_goes_through_the_browser(self):
        for source in (wiki_archive.WikiArchive, spiraltracker.SpiralTracker, folio.Folio, forum_guide.ForumGuide):
            robots = as_sent(source, "https://web.archive.org/robots.txt", {"dont_obey_robotstxt": True})
            self.assertNotIn("playwright", robots.meta, source.name)

    def test_robots_txt_the_browser_rendered_is_read_from_its_pre(self):
        rendered = HtmlResponse(self.ROBOTS, body=b"<html><head></head><body><pre>User-agent: *\nDisallow: /w/"
                                                  b" &amp; more</pre></body></html>", encoding="utf-8",
                                request=Request(self.ROBOTS))
        [through] = [m for m in own_middlewares(wiki_live.WikiLive) if isinstance(m, wiki_live.ThroughBrowser)]
        robots = through.process_response(rendered.request, rendered)
        self.assertEqual(robots.text, "User-agent: *\nDisallow: /w/ & more")


class ArchivedCategories(unittest.TestCase):
    def setUp(self):
        self.archive = spider(wiki_archive.WikiArchive)
        [self.lookup] = self.archive.category_part(CELESTIA, None, 0, "wiki/" + CELESTIA)

    def captures(self):
        return list(self.archive.read_captures(response("cdx_category_celestia.txt", self.lookup.url),
                                               **self.lookup.cb_kwargs))

    def test_category_is_looked_up_in_the_cdx_with_status_200(self):
        self.assertIn("url=wiki.wizard101central.com/wiki/Category:Celestia_Quests", self.lookup.url)
        self.assertIn("filter=statuscode:200", self.lookup.url)

    def test_newest_capture_is_fetched_raw(self):
        [request] = self.captures()
        self.assertEqual(request.url, "https://web.archive.org/web/20260722063910id_/"
                                      "https://wiki.wizard101central.com/wiki/Category:Celestia_Quests")

    def test_capture_that_lists_nothing_gives_way_to_the_next_older_one(self):
        [newest] = self.captures()
        [older] = self.archive.read_capture(response("wayback_interstitial.html", newest.url), **newest.cb_kwargs)
        self.assertIn("/web/20250101000000id_/", older.url)

    def test_cached_capture_that_lists_nothing_is_passed_over(self):
        with open(os.path.join(self.archive.cache, "20260722063910_Category_Celestia_Quests.html"), "w") as f:
            f.write(fixture("wayback_interstitial.html"))
        [self.lookup] = self.archive.category_part(CELESTIA, None, 0, "wiki/" + CELESTIA)
        [request] = self.captures()
        self.assertIn("/web/20250101000000id_/", request.url)

    def test_next_page_of_a_category_is_looked_up_the_same_way(self):
        [newest] = self.captures()
        [lookup] = self.archive.read_capture(response("category_celestia.html", newest.url), **newest.cb_kwargs)
        self.assertIn("url=wiki.wizard101central.com/wiki/index.php%3Ftitle%3DCategory:Celestia_Quests"
                      "%26pagefrom%3DGone%2BFishing", lookup.url)


class ArchivedQuests(unittest.TestCase):
    def setUp(self):
        self.archive = spider(wiki_archive.WikiArchive)
        self.archive.walk.queue = []
        self.archive.walk.quests = {page: {"zones": {"The Commons"}, "types": set()}
                                    for page in ("Quest:Bad_Blood", "Quest:Crystal-Matic")}
        [self.first] = self.archive.next_category()

    def answer(self, lookup):
        return list(self.archive.read_lookup(response("cdx_quest_bad_blood.txt", lookup.url), **lookup.cb_kwargs))

    def refuse(self, lookup):
        failure = Failure(HttpError(HtmlResponse(lookup.url, status=503, body=b"", request=lookup)))
        failure.request = lookup
        return list(self.archive.lookup_failed(failure))

    def index(self):
        with open(os.path.join(self.archive.cache, "index-celestia.json"), encoding="utf-8") as f:
            return {entry["page"]: entry for entry in json.load(f)}

    def test_each_quest_is_looked_up_on_its_own_with_three_retries(self):
        self.assertIn("url=wiki.wizard101central.com/wiki/Quest:Bad_Blood", self.first.url)
        self.assertIn("filter=statuscode:200", self.first.url)
        self.assertIn("limit=-3", self.first.url)
        self.assertEqual(self.first.meta["max_retry_times"], 3)

    def test_quest_is_indexed_with_its_newest_capture(self):
        [second] = self.answer(self.first)
        self.answer(second)
        self.assertEqual(self.index()["Quest:Bad_Blood"]["timestamp"], "20260105000000")

    def snapshots(self):
        [second] = self.answer(self.first)
        return [item for item in self.answer(second) if isinstance(item, Request)]

    def try_next(self, request, fixture_name):
        page = response(fixture_name, request.url)
        return list(self.archive.read_snapshot(page, **request.cb_kwargs))

    def test_newest_capture_with_status_200_is_fetched_raw_first(self):
        first = self.snapshots()[0]
        self.assertEqual(first.url, "https://web.archive.org/web/20260105000000id_/"
                                    "https://wiki.wizard101central.com/wiki/Quest:Bad_Blood")

    def test_replayed_challenge_page_gives_way_to_the_next_older_capture(self):
        [older] = self.try_next(self.snapshots()[0], "challenge_turnstile.html")
        self.assertIn("/web/20250604000000id_/", older.url)

    def test_page_without_a_quest_infobox_gives_way_to_the_next_capture(self):
        [older] = self.try_next(self.snapshots()[0], "wayback_interstitial.html")
        self.assertIn("/web/20250604000000id_/", older.url)

    def test_oldest_capture_is_tried_raw_then_in_its_playback_form(self):
        request = self.snapshots()[0]
        for _ in range(2):
            [request] = self.try_next(request, "wayback_interstitial.html")
        self.assertIn("/web/20240103000000id_/", request.url)
        [request] = self.try_next(request, "wayback_interstitial.html")
        self.assertIn("/web/20240103000000/", request.url)

    def test_quest_with_no_usable_capture_left_is_missing_its_snapshot(self):
        request = self.snapshots()[0]
        for _ in range(3):
            [request] = self.try_next(request, "wayback_interstitial.html")
        self.assertEqual(self.try_next(request, "wayback_interstitial.html"), [])
        self.assertTrue(self.index()["Quest:Bad_Blood"]["missing_snapshot"])

    def test_usable_cached_snapshot_is_read_without_a_request(self):
        with open(os.path.join(self.archive.cache, "20231122065551_Quest_Bad_Blood.html"), "w") as f:
            f.write(fixture("quest_deeper_and_deeper.html"))
        [second] = self.answer(self.first)
        items = self.answer(second)
        self.assertIn("Bad Blood", records(items))
        self.assertNotIn("Quest:Bad_Blood", " ".join(item.url for item in items if isinstance(item, Request)))

    def test_only_a_usable_snapshot_is_cached(self):
        request = self.snapshots()[0]
        self.assertFalse(self.archive.is_usable(response("challenge_turnstile.html", request.url)))
        self.assertFalse(self.archive.is_usable(response("wayback_interstitial.html", request.url)))
        self.assertTrue(self.archive.is_usable(response("quest_deeper_and_deeper.html", request.url)))

    def test_quest_whose_lookup_fails_is_missing_its_snapshot_not_the_source(self):
        [second] = self.refuse(self.first)
        items = self.answer(second)
        self.assertTrue(self.index()["Quest:Bad_Blood"]["missing_snapshot"])
        self.assertEqual([item.quest for item in items if isinstance(item, Listed)], ["Crystal-Matic"])
        self.assertIn("Quest:Crystal-Matic", [item for item in items if isinstance(item, Request)][0].url)


class ListingSources(unittest.TestCase):
    def listing(self, source, name):
        return list(spider(source).read_listing(response(name)))

    def test_spiraltracker_gives_order_next_quest_and_goal_types(self):
        items = self.listing(spiraltracker.SpiralTracker, "spiraltracker_dragonspyre.html")
        self.assertEqual(records(items)["Crystal-Matic"], {"name": "Crystal-Matic", "order": 2,
                                                            "leads_to": ["Holger's Crystals"],
                                                            "goal_types": ["explore", "talk"]})

    def test_spiraltracker_quest_split_over_two_rows_is_one_quest(self):
        items = self.listing(spiraltracker.SpiralTracker, "spiraltracker_dragonspyre.html")
        listed = [item.quest for item in items if isinstance(item, Listed)]
        self.assertEqual(listed.count("Forward… Into History!"), 1)
        self.assertEqual(records(items)["Forward… Into History!"]["goal_types"], ["interact", "talk"])

    def test_folio_gives_order_next_quest_and_goal_types(self):
        items = self.listing(folio.Folio, "folio_dragonspyre.html")
        self.assertEqual(records(items)["Holger’s Crystals"], {"name": "Holger’s Crystals", "order": 3,
                                                               "leads_to": ["Stone Tower Pilot"],
                                                               "goal_types": ["use", "talk"]})

    def test_folio_lists_the_quest_tables_and_nothing_else_on_the_page(self):
        items = self.listing(folio.Folio, "folio_dragonspyre.html")
        listed = [item.quest for item in items if isinstance(item, Listed)]
        self.assertEqual((len(listed), listed[0], listed[-1]), (12, "Bad Blood", "Portal Combat"))
        self.assertEqual(list(records(items)), listed)

    def test_folio_goal_types_drop_the_counts(self):
        [(_, goal_types)] = folio.listed_quests("<tr><td>9</td><td><strong>Wizard and Crystal</strong></td>"
                                                "<td>Talk x2 + x4 Boss + Talk</td><td></td></tr>")
        self.assertEqual(goal_types, ["talk", "boss"])

    def test_row_without_a_quest_name_is_skipped(self):
        self.assertEqual(folio.listed_quests("<tr><td>1</td><td><strong> </strong></td><td>Talk</td></tr>"), [])


class ForumGuide(unittest.TestCase):
    def test_guide_gives_the_reward_of_the_quests_it_rewards(self):
        items = list(spider(forum_guide.ForumGuide).read_guide(response("forum_guide_celestia.html")))
        self.assertEqual(records(items)["Deeper and Deeper"], {"name": "Deeper and Deeper",
                                                                "reward": {"xp": 560, "gold": 30}})
        self.assertNotIn("Survivors", records(items))


if __name__ == "__main__":
    unittest.main()
