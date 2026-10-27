"""The live Wizard101 Central wiki through the sandboxed browser: the world's quest categories, then each quest page.

Pages are cached in the layout of spiraltools' archive cache (`<timestamp>_<page>.html` and `index-<world>.json`), so
`spiraltools.py archive parse <World> --cache <cache>/wiki_live` builds client-resolved specs from them.
"""
import html
import json
import os
import re
import urllib.parse

from ..spiraltools_import import archive, world
from . import Raw, fetch_cached, provenance

HOST = "https://wiki.wizard101central.com"
NEXT_PAGE = re.compile(r'<a href="([^"]*pagefrom=[^"]*)"[^>]*>next page</a>')


def read_category(page):
    """The subcategories and quest pages a category page lists, and the URL of its next page or None."""
    subcategories, quests = archive.category_members(page)
    found = NEXT_PAGE.search(page)
    next_url = urllib.parse.urljoin(HOST, html.unescape(found.group(1)).split("#")[0]) if found else None
    return subcategories, quests, next_url


def quest_name(page):
    return page[len("Quest:"):].replace("_", " ")


class WikiLive:
    name = "wiki_live"

    def __init__(self, gate, cache):
        self.gate, self.cache = gate, cache
        self.pages = {}

    def enumerate(self, world_name):
        registered = world(world_name)
        quests = self.walk(registered.category)
        index = [{"name": quest_name(page), "page": page, "zones": sorted(entry["zones"]),
                  "type": "/".join(sorted(entry["types"])) or None} for page, entry in sorted(quests.items())]
        os.makedirs(self.cache, exist_ok=True)
        with open(archive.index_path(self.cache, registered.name), "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        self.pages = {entry["name"]: entry["page"] for entry in index}
        return list(self.pages)

    def walk(self, root):
        """quest page -> {"zones", "types"} over the category tree, as spiraltools' archive walk reads it."""
        quests, seen, queue = {}, set(), [(root, None)]
        while queue:
            category, zone = queue.pop(0)
            if category in seen:
                continue
            seen.add(category)
            url, key, part = f"{archive.WIKI}{category}", category, 0
            while url:
                fetched = fetch_cached(self.gate, self.name, self.cache, key, url)
                if fetched is None:
                    break
                subcategories, members, url = read_category(fetched[1])
                part += 1
                key = f"{category}_part{part}"
                kind = archive.quest_type_of(category)
                for page in members:
                    entry = quests.setdefault(page, {"zones": set(), "types": set()})
                    if zone:
                        entry["zones"].add(zone)
                    if kind:
                        entry["types"].add(kind)
                for sub in subcategories:
                    is_zone = category == root and not archive.quest_type_of(sub)
                    queue.append((sub, sub[len("Category:"):-len("_Quests")].replace("_", " ") if is_zone else zone))
        return quests

    def fetch(self, quest):
        page = self.pages.get(quest) or archive.page_key(f"Quest:{quest}")
        url = archive.WIKI + urllib.parse.quote(page, safe=":_()/,!")
        fetched = fetch_cached(self.gate, self.name, self.cache, page, url)
        if fetched is None:
            return None
        return Raw(quest, fetched[1], provenance(self.name, url, fetched[0]))

    def parse(self, raw):
        return {"name": raw.quest, **archive.read_page(raw.text)}
