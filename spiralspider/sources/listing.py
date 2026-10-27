"""A per-world quest listing page (spiraltracker, folio): quest order, the next quest and the goal types.

Each site's module reads its own markup into (quest name, goal types) rows in page order; a row without a name is
skipped, and a quest the page splits over several rows is one quest with the goal types of all of them.
"""
import html
import re
import urllib.parse

from ..items import Listed, Record
from ..middlewares import FETCHED
from ..spiraltools_import import archive
from . import SourceSpider, provenance, requested_url


def text_of(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def quests_of(rows):
    """(quest name, goal types) per quest, in the order of its first row."""
    quests = {}
    for name, goal_types in rows:
        if not name:
            continue
        kinds = quests.setdefault(name, [])
        for kind in goal_types:
            if kind not in kinds:
                kinds.append(kind)
    return list(quests.items())


def listed_fields(quests, quest):
    """The fields the listing gives for a quest it lists: its place in the order, the quest after it, its goals."""
    wanted = archive.title_norm(quest)
    position = next(i for i, (name, _) in enumerate(quests) if archive.title_norm(name) == wanted)
    following = quests[position + 1:position + 2]
    return {"name": quest, "order": position + 1, "leads_to": [name for name, _ in following],
            "goal_types": quests[position][1]}


class ListingSource(SourceSpider):
    """A listing source: `url_template` takes the world's slug, `listed_quests` reads the page into quest rows."""

    url_template = ""

    @staticmethod
    def listed_quests(page):
        raise NotImplementedError

    async def start(self):
        url = self.url_template.format(self.registered.wiki.lower().replace("_", "-"))
        key = urllib.parse.urlsplit(url).path.strip("/") or "index"
        yield self.page_request(key, url, self.read_listing, errback=self.listing_failed)

    def read_listing(self, response):
        quests = self.listed_quests(response.text)
        source = provenance(self.name, requested_url(response), response.meta[FETCHED])
        for name, _ in quests:
            yield Listed(self.name, name)
        for name, _ in quests:
            yield Record(self.name, name, listed_fields(quests, name), source)
