"""A per-world quest listing page (spiraltracker, folio): quest order, the next quest and the goal types.

The listing is read as its list items in page order: the item's link text, else its text before " - " or ":", is the
quest name, and the goal verbs in the rest are its goal types. This reading of the two sites' markup is an assumption
the fixtures encode; it has not been checked against the live pages.
"""
import html
import re
import urllib.parse

from ..spiraltools_import import archive, world
from . import Raw, fetch_cached, provenance

GOAL_TYPES = ("defeat", "talk", "collect", "explore", "find", "use", "survive", "go", "deliver")
ITEM = re.compile(r"<li\b[^>]*>(.*?)</li>", re.S)
LINK_TEXT = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S)


def text_of(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def listed_quests(page):
    """(quest name, goal types) per list item, in page order."""
    quests = []
    for item in ITEM.findall(page):
        link = LINK_TEXT.search(item)
        text = text_of(item)
        name = text_of(link.group(1)) if link else re.split(r"\s+-\s+|:\s", text, maxsplit=1)[0]
        rest = text[len(name):].lower() if text.startswith(name) else text.lower()
        quests.append((name, [verb for verb in GOAL_TYPES if re.search(rf"\b{verb}\b", rest)]))
    return quests


class ListingSource:
    name = ""
    url_template = ""

    def __init__(self, gate, cache):
        self.gate, self.cache = gate, cache
        self.url = ""

    def enumerate(self, world_name):
        slug = world(world_name).wiki.lower().replace("_", "-")
        self.url = self.url_template.format(slug)
        fetched = self.page()
        return [name for name, _ in listed_quests(fetched[1])] if fetched else []

    def page(self):
        key = urllib.parse.urlsplit(self.url).path.strip("/") or "index"
        return fetch_cached(self.gate, self.name, self.cache, key, self.url)

    def fetch(self, quest):
        fetched = self.page()
        return Raw(quest, fetched[1], provenance(self.name, self.url, fetched[0])) if fetched else None

    def parse(self, raw):
        quests = listed_quests(raw.text)
        wanted = archive.title_norm(raw.quest)
        position = next((i for i, (name, _) in enumerate(quests) if archive.title_norm(name) == wanted), None)
        if position is None:
            return None
        following = quests[position + 1:position + 2]
        return {"name": raw.quest, "order": position + 1, "leads_to": [name for name, _ in following],
                "goal_types": quests[position][1]}
