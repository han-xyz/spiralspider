"""A per-world quest listing page (spiraltracker, folio): quest order, the next quest and the goal types.

The listing is read as its list items in page order: the item's link text, else its text before " - " or ":", is the
quest name, and the goal verbs in the rest are its goal types. This reading of the two sites' markup is an assumption
the fixtures encode; it has not been checked against the live pages.
"""
import html
import re
import urllib.parse

from ..items import Listed, Record
from ..middlewares import FETCHED
from ..spiraltools_import import archive
from . import SourceSpider, provenance, requested_url

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


def listed_fields(quests, quest):
    """The fields the listing gives for a quest it lists: its place in the order, the quest after it, its goals."""
    wanted = archive.title_norm(quest)
    position = next(i for i, (name, _) in enumerate(quests) if archive.title_norm(name) == wanted)
    following = quests[position + 1:position + 2]
    return {"name": quest, "order": position + 1, "leads_to": [name for name, _ in following],
            "goal_types": quests[position][1]}


class ListingSource(SourceSpider):
    url_template = ""

    async def start(self):
        url = self.url_template.format(self.registered.wiki.lower().replace("_", "-"))
        key = urllib.parse.urlsplit(url).path.strip("/") or "index"
        yield self.page_request(key, url, self.read_listing, errback=self.listing_failed)

    def read_listing(self, response):
        quests = listed_quests(response.text)
        source = provenance(self.name, requested_url(response), response.meta[FETCHED])
        for name, _ in quests:
            yield Listed(self.name, name)
        for name, _ in quests:
            yield Record(self.name, name, listed_fields(quests, name), source)
