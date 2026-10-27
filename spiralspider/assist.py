"""Assisted live fetch: the wiki pages a world's archive index has no snapshot of, fetched from the live wiki in a
visible browser. A person solves the wiki's challenge in that window; the tool never touches the challenge, it waits
until a wiki page shows and then navigates page by page, one every three seconds. Pages are cached in spiraltools'
layout as `<timestamp>_live_<page>.html`, beside the archive's captures."""
import datetime
import json
import os
import time
import urllib.parse
from typing import NamedTuple

from .sources import STAMP, CategoryWalk, quest_name
from .sources.wiki_archive import PAGE_SAFE
from .sources.wiki_live import HOST, read_category
from .spiraltools_import import archive

MAIN_PAGE = f"{HOST}/wiki/Main_Page"
CHALLENGE_TITLES = ("Just a moment", "Performing security")
CHALLENGE_TEXT = "Verify you are human"
NO_TEXT = "There is currently no text"
WAITING = "solve the check in the browser window; waiting"
NAVIGATION_INTERVAL = 3.0
POLL_INTERVAL = 1.0
LOAD_TIMEOUT_MS = 30000
WRITE_EVERY = 20
WINDOW = {"width": 1280, "height": 900}
# Resolves once the page shows the wiki's content or a challenge; it only reads the page.
SETTLED = """() => document.querySelector('#content') !== null
    || /Just a moment|Performing security/.test(document.title)
    || (document.body !== null && document.body.innerText.includes('Verify you are human'))"""


class Loaded(NamedTuple):
    """A page as the browser shows it: the HTTP status of its navigation (None when polled), title, HTML and whether
    it has the wiki's #content."""
    status: int | None
    title: str
    html: str
    has_content: bool


def is_challenge(title, html):
    return any(marker in title for marker in CHALLENGE_TITLES) or CHALLENGE_TEXT in html


def is_missing(loaded):
    """A page the live wiki does not have."""
    return loaded.status == 404 or (not loaded.has_content and NO_TEXT in loaded.html)


def run(worlds, cache, profile):
    """Fetches the pages each world's index lacks in a headed Chromium with the persistent profile `profile`; Ctrl-C
    stops after saving the index."""
    from playwright.sync_api import sync_playwright

    results = {}
    with sync_playwright() as playwright:
        browser_context = playwright.chromium.launch_persistent_context(profile, headless=False, viewport=WINDOW)
        try:
            browser = Browser(browser_context)
            load(browser, MAIN_PAGE)
            for registered in worlds:
                results[registered.name] = assist_world(browser, cache, registered)
        except KeyboardInterrupt:
            print("interrupted; the index is saved")
        finally:
            browser_context.close()
    return results


def assist_world(browser, cache, registered):
    """Fetches the world's wanted pages; the index is written every WRITE_EVERY pages and on the way out, an interrupt
    included. Returns the counts fetched, 404 and remaining."""
    index = work_index(browser, cache, registered)
    pages = to_fetch(cache, index)
    wanted = sum(1 for entry in index if entry.get("missing_snapshot"))
    print(f"{registered.name}: wanted {wanted}, to fetch {len(pages)}")
    counts = {"fetched": 0, "404": 0}
    try:
        for done, entry in enumerate(pages, 1):
            loaded = load(browser, f"{HOST}/wiki/{urllib.parse.quote(entry['page'], safe=PAGE_SAFE)}")
            if is_missing(loaded):
                entry["missing_live"] = True
                counts["404"] += 1
            elif loaded.has_content:
                save_live(cache, entry["page"], loaded.html)
                counts["fetched"] += 1
            else:
                print(f"{entry['page']}: no wiki content shown; left for the next run")
            if done % WRITE_EVERY == 0:
                write_index(cache, registered.name, index)
    finally:
        write_index(cache, registered.name, index)
        counts["remaining"] = len(to_fetch(cache, index))
        print(f"{registered.name}: fetched {counts['fetched']}, 404 {counts['404']}, remaining {counts['remaining']}")
    return counts


def work_index(browser, cache, registered):
    """The world's index from the cache; when it is missing or empty, built by walking the world's categories on the
    live wiki and written."""
    path = archive.index_path(cache, registered.name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            index = json.load(f)
        if index:
            return index
    index = walked_index(browser, registered)
    os.makedirs(cache, exist_ok=True)
    write_index(cache, registered.name, index)
    return index


def walked_index(browser, registered):
    """Index entries, as the archive source writes them, for the quests of the world's live categories; none has an
    archive snapshot looked up, so each is marked missing one."""
    walk = CategoryWalk(registered.category)
    while (following := walk.next()) is not None:
        category, zone = following
        url = f"{HOST}/wiki/{urllib.parse.quote(category, safe=PAGE_SAFE)}"
        while url:
            loaded = load(browser, url)
            if is_missing(loaded):
                break
            subcategories, members, url = read_category(loaded.html)
            walk.add(category, zone, subcategories, members)
    return [{"name": quest_name(page), "page": page, "missing_snapshot": True,
             "zones": sorted(walk.quests[page]["zones"]), "type": "/".join(sorted(walk.quests[page]["types"])) or None}
            for page in sorted(walk.quests)]


def to_fetch(cache, index):
    """The entries without an archive snapshot or a cached copy that the live wiki has not answered 404 for."""
    return [entry for entry in index if entry.get("missing_snapshot") and not entry.get("missing_live")
            and archive.cached(cache, entry["page"]) is None]


def write_index(cache, world, index):
    with open(archive.index_path(cache, world), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def save_live(cache, page, html):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime(STAMP)
    with open(os.path.join(cache, f"{stamp}_live_{archive.file_name(page)}.html"), "w", encoding="utf-8") as f:
        f.write(html)


def load(browser, url):
    """The page at `url`; on a challenge, waits for the person to solve it and loads the page again."""
    loaded = browser.load(url)
    while is_challenge(loaded.title, loaded.html):
        wait_for_person(browser)
        loaded = browser.load(url)
    return loaded


def wait_for_person(browser):
    print(WAITING, flush=True)
    while True:
        browser.pause(POLL_INTERVAL)
        shown = browser.current()
        if shown.has_content and not is_challenge(shown.title, shown.html):
            return


class Browser:
    """The one tab of the persistent context: paced navigation and reads of what it shows."""

    def __init__(self, browser_context):
        self.page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
        self.last = 0.0

    def load(self, url):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        time.sleep(max(0.0, self.last + NAVIGATION_INTERVAL - time.monotonic()))
        self.last = time.monotonic()
        response = self.page.goto(url, wait_until="domcontentloaded")
        try:
            self.page.wait_for_function(SETTLED, timeout=LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            # Neither content nor a challenge in time: the caller judges the page as it is shown.
            pass
        return self.shown(response.status if response else None)

    def current(self):
        from playwright.sync_api import Error

        try:
            return self.shown(None)
        except Error:
            # The challenge navigates on its own once solved; a read during that navigation fails and is polled again.
            return Loaded(None, "", "", False)

    def shown(self, status):
        return Loaded(status, self.page.title(), self.page.content(), self.page.query_selector("#content") is not None)

    def pause(self, seconds):
        self.page.wait_for_timeout(seconds * 1000)
