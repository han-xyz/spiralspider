import contextlib
import io
import json
import os
import tempfile
import unittest

import context
from spiralspider import assist
from spiralspider.assist import Loaded
from spiralspider.spiraltools_import import archive, world

WIKI = "https://wiki.wizard101central.com/wiki/"
NO_PAGE = "<div id='content'>There is currently no text in this page.</div>"


def category(subcategories=(), quests=(), next_from=None):
    subs = "".join(f'<a href="/wiki/{s}">{s}</a>' for s in subcategories)
    pages = "".join(f'<a href="/wiki/{q}">{q}</a>' for q in quests)
    more = f'<a href="/index.php?title=X&amp;pagefrom={next_from}">next page</a>' if next_from else ""
    return (f'<div id="content"><div id="mw-subcategories">{subs}</div><div id="mw-pages">{pages}{more}'
            '</div><div class="printfooter"></div></div>')


def page(html, status=200):
    return Loaded(status, "Wizard101 Wiki", html, "id=\"content\"" in html or "id='content'" in html)


CHALLENGE = Loaded(403, "Just a moment...", "<html></html>", False)


class FakeBrowser:
    """Answers each URL from `pages`; `challenged` URLs show a challenge on their first load."""

    def __init__(self, pages, challenged=(), interrupt_at=None):
        self.pages, self.challenged, self.interrupt_at = pages, set(challenged), interrupt_at
        self.loads, self.polls = [], 0

    def load(self, url):
        self.loads.append(url)
        if len(self.loads) == self.interrupt_at:
            raise KeyboardInterrupt
        if url in self.challenged:
            self.challenged.discard(url)
            return CHALLENGE
        return self.pages.get(url, page(NO_PAGE, 404))

    def current(self):
        self.polls += 1
        return CHALLENGE if self.polls < 2 else page('<div id="content"></div>')

    def pause(self, seconds):
        pass


def write_index(cache, entries):
    with open(archive.index_path(cache, "Celestia"), "w", encoding="utf-8") as f:
        json.dump(entries, f)


def read_index(cache):
    with open(archive.index_path(cache, "Celestia"), encoding="utf-8") as f:
        return json.load(f)


def entry(page, **flags):
    return {"name": page[len("Quest:"):].replace("_", " "), "page": page, **flags, "zones": [], "type": None}


def quietly(function, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args)


class Checks(unittest.TestCase):
    def test_challenge_titles_and_text(self):
        self.assertTrue(assist.is_challenge("Just a moment...", ""))
        self.assertTrue(assist.is_challenge("Performing security verification", ""))
        self.assertTrue(assist.is_challenge("wiki.wizard101central.com", "<p>Verify you are human by completing</p>"))
        self.assertFalse(assist.is_challenge("Quest:Deeper and Deeper - Wizard101 Wiki", '<div id="content">'))

    def test_missing_page(self):
        self.assertTrue(assist.is_missing(Loaded(404, "", '<div id="content"></div>', True)))
        self.assertTrue(assist.is_missing(Loaded(200, "", "There is currently no text in this page.", False)))
        self.assertFalse(assist.is_missing(Loaded(200, "", '<div id="content">a quest</div>', True)))


class WorkList(unittest.TestCase):
    def test_pages_missing_a_snapshot_without_a_cached_copy(self):
        cache = tempfile.mkdtemp()
        write_index(cache, [entry("Quest:Archived", timestamp="20240101000000"),
                            entry("Quest:Fetched_Before", missing_snapshot=True),
                            entry("Quest:Not_On_The_Wiki", missing_snapshot=True, missing_live=True),
                            entry("Quest:Wanted", missing_snapshot=True)])
        open(os.path.join(cache, "20261027000000_live_Quest_Fetched_Before.html"), "w").close()
        index = quietly(assist.work_index, FakeBrowser({}), cache, world("Celestia"))
        self.assertEqual([e["page"] for e in assist.to_fetch(cache, index)], ["Quest:Wanted"])

    def test_a_world_without_an_index_is_walked_through_the_browser(self):
        cache = tempfile.mkdtemp()
        root, side = "Category:Celestia_Quests", "Category:Celestia_Side_Quests"
        zone = "Category:Stormdrain_Quests"
        browser = FakeBrowser({
            WIKI + root: page(category([zone, side])),
            WIKI + zone: page(category([], ["Quest:Deeper_and_Deeper"], next_from="Quest:Z")),
            "https://wiki.wizard101central.com/index.php?title=X&pagefrom=Quest:Z": page(category([], ["Quest:Zed"])),
            WIKI + side: page(category([], ["Quest:Zed"])),
        })
        index = quietly(assist.work_index, browser, cache, world("Celestia"))
        self.assertEqual(index, [
            {"name": "Deeper and Deeper", "page": "Quest:Deeper_and_Deeper", "missing_snapshot": True,
             "zones": ["Stormdrain"], "type": None},
            {"name": "Zed", "page": "Quest:Zed", "missing_snapshot": True, "zones": ["Stormdrain"], "type": "side"},
        ])
        self.assertEqual(read_index(cache), index)


class Fetch(unittest.TestCase):
    def test_saves_live_copies_marks_missing_pages_and_waits_out_a_challenge(self):
        cache = tempfile.mkdtemp()
        write_index(cache, [entry("Quest:Gone", missing_snapshot=True), entry("Quest:Wanted", missing_snapshot=True)])
        browser = FakeBrowser({WIKI + "Quest:Wanted": page('<div id="content">Quest Information</div>')},
                              challenged=[WIKI + "Quest:Wanted"])
        counts = quietly(assist.assist_world, browser, cache, world("Celestia"))
        self.assertEqual(counts, {"fetched": 1, "404": 1, "remaining": 0})
        self.assertEqual(browser.loads.count(WIKI + "Quest:Wanted"), 2)
        live = [name for name in os.listdir(cache) if name.endswith("_live_Quest_Wanted.html")]
        self.assertEqual(len(live), 1)
        self.assertEqual(archive.cached(cache, "Quest:Wanted")[1], os.path.join(cache, live[0]))
        self.assertEqual([e.get("missing_live") for e in read_index(cache)], [True, None])
        self.assertTrue(all(e["missing_snapshot"] for e in read_index(cache)))

    def test_an_interrupt_keeps_what_was_done(self):
        cache = tempfile.mkdtemp()
        write_index(cache, [entry(f"Quest:Gone_{n}", missing_snapshot=True) for n in range(3)])
        with self.assertRaises(KeyboardInterrupt):
            quietly(assist.assist_world, FakeBrowser({}, interrupt_at=3), cache, world("Celestia"))
        self.assertEqual([e.get("missing_live") for e in read_index(cache)], [True, True, None])
